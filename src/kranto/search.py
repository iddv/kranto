"""Search over the library: embedding rank fused with full-text rank.

Dense: brute-force cosine over an in-memory float32 matrix. 100k observations
at 384-d is 150 MB and a query is one matrix-vector product, so no
approximate index is needed (and exact top-k keeps results honest).

Lexical: SQLite FTS5 (BM25, Porter stemming) over title, summary,
why_it_matters and tags. The two rankings are fused by reciprocal rank
(``1 / (60 + rank)`` summed over both lists). Measured on 41 graded queries
over the 7,113-observation Parallax import, fusion raised P@10 from
0.50 to 0.59 (lenient; 26 queries better, 11 worse) over dense alone: exact
terms (a product name, "sycophancy", "Claude Code") rescue queries the
embedding blurs. Each hit still carries its cosine similarity, which is what
the UI shows.

Rollups, the summaries compaction leaves in place of expired
observations, are searched the same way but ranked on their own: by their
centroid for meaning and by name, summary and keywords for words. A centroid
is a mean of many observations, so its similarity to a query is not on the
same scale as one observation's, and the two lists are never merged.

Cosine similarity is not a relevance score: on the same set, 54% of relevant
items scored below 0.70 and a quarter of non-relevant ones scored above it.
It does separate off-topic queries. Unrelated control queries had a best
match of 0.53-0.59 (0.64-0.66 in Parallax, exp 14), while every covered
subject had a best match of 0.68 or more. A best match below
``OFF_TOPIC_BELOW`` therefore says the library may not cover the query; it
says nothing about the individual results of a covered one.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass

import numpy as np

from .embed import Embedder
from .store import Store, blob_to_vec

OFF_TOPIC_BELOW = 0.65
# The Library page leaves out results more than this below the closest one.
# On the graded set, 13% of pooled items this far below the best match were
# on subject, against 24-48% of those within it.
CUTOFF_BELOW_BEST = 0.15
RRF_K = 60
# Each ranking contributes at least this many candidates to the fusion.
CANDIDATES = 100
# Words that carry no subject; BM25 would weight them low anyway, but they
# make nearly every observation a candidate.
STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "how", "i", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "their",
    "this", "to", "was", "what", "when", "where", "which", "who", "why", "with", "without",
    "about",
})
MAX_TERMS = 32
_WORD = re.compile(r"\w+")


@dataclass(frozen=True)
class Hit:
    observation_id: int
    score: float  # cosine similarity to the query
    weak: bool  # below the off-topic line


def floor2(score: float) -> float:
    """Round down to two decimals, so a score shown next to the off-topic line
    never reads as equal to it while being below it (0.699 is 0.69, not 0.70)."""
    return math.floor(score * 100) / 100


def off_topic(hits: list[Hit]) -> bool:
    """True when even the closest result is as far as unrelated queries land."""
    return bool(hits) and max(h.score for h in hits) < OFF_TOPIC_BELOW


def within_cutoff(hits: list[Hit]) -> list[Hit]:
    """The hits no more than ``CUTOFF_BELOW_BEST`` below the closest of them."""
    if not hits:
        return []
    floor = max(h.score for h in hits) - CUTOFF_BELOW_BEST
    return [h for h in hits if h.score >= floor]


def match_expression(query: str) -> str | None:
    """An FTS5 query matching any word of the query, each quoted as a literal."""
    terms: list[str] = []
    for word in _WORD.findall(query.lower()):
        if word not in STOPWORDS and word not in terms:
            terms.append(word)
    return " OR ".join(f'"{t}"' for t in terms[:MAX_TERMS]) or None


@dataclass(frozen=True)
class RollupHit:
    rollup_id: int
    score: float  # cosine similarity of the query to the rollup's centroid


class Index:
    """Current observations' embeddings, reloaded when the library grows or is
    compacted, and the rollups' centroids."""

    def __init__(self, store: Store, embedding_model: str) -> None:
        self.store = store
        self.embedding_model = embedding_model
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self.ids = np.zeros(0, dtype=np.int64)
        self.matrix = np.zeros((0, 0), dtype=np.float32)
        self._position: dict[int, int] = {}
        self._rollup_max = -1
        self.rollup_ids = np.zeros(0, dtype=np.int64)
        self.rollup_matrix = np.zeros((0, 0), dtype=np.float32)
        self._rollup_position: dict[int, int] = {}

    def refresh(self) -> None:
        # The count as well as the newest id: compaction removes old rows.
        row = self.store.query_one(
            "SELECT COALESCE(MAX(id), 0) AS m, COUNT(*) AS n FROM observations")
        if (row["m"], row["n"]) == self._key:
            return
        with self._lock:
            rows = self.store.query(
                """
                SELECT o.id, o.embedding FROM observations o
                WHERE o.embedding_model = ?
                  AND NOT EXISTS (SELECT 1 FROM observations n WHERE n.supersedes = o.id)
                ORDER BY o.id
                """,
                (self.embedding_model,),
            )
            self.ids = np.array([r["id"] for r in rows], dtype=np.int64)
            self.matrix = (
                np.stack([blob_to_vec(r["embedding"]) for r in rows])
                if rows
                else np.zeros((0, 0), dtype=np.float32)
            )
            self._position = {int(i): p for p, i in enumerate(self.ids)}
            self._key = (row["m"], row["n"])

    def refresh_rollups(self) -> None:
        row = self.store.query_one("SELECT COALESCE(MAX(id), 0) AS m FROM rollups")
        if row["m"] == self._rollup_max:
            return
        with self._lock:
            rows = self.store.query(
                "SELECT id, centroid FROM rollups WHERE embedding_model = ? ORDER BY id",
                (self.embedding_model,))
            self.rollup_ids = np.array([r["id"] for r in rows], dtype=np.int64)
            self.rollup_matrix = (np.stack([blob_to_vec(r["centroid"]) for r in rows])
                                  if rows else np.zeros((0, 0), dtype=np.float32))
            self._rollup_position = {int(i): p for p, i in enumerate(self.rollup_ids)}
            self._rollup_max = row["m"]

    def rollups(self, vector: np.ndarray, query: str, k: int = 5) -> list[RollupHit]:
        """Rollups by centroid similarity and full-text rank, fused like observations."""
        self.refresh_rollups()
        if not len(self.rollup_ids):
            return []
        scores = self.rollup_matrix @ vector.astype(np.float32)
        depth = max(k, CANDIDATES)
        dense = [int(p) for p in np.argsort(-scores)[:depth]]
        lexical: list[int] = []
        expr = match_expression(query)
        if expr is not None:
            rows = self.store.query(
                "SELECT rowid FROM rollups_fts WHERE rollups_fts MATCH ? ORDER BY rank LIMIT ?",
                (expr, depth))
            lexical = [self._rollup_position[r["rowid"]] for r in rows
                       if r["rowid"] in self._rollup_position]
        fused: dict[int, float] = {}
        for ranking in (dense, lexical):
            for rank, position in enumerate(ranking):
                fused[position] = fused.get(position, 0.0) + 1.0 / (RRF_K + rank + 1)
        order = sorted(fused, key=lambda p: -fused[p])[:k]
        return [RollupHit(int(self.rollup_ids[p]), float(scores[p])) for p in order]

    def _hit(self, position: int, scores: np.ndarray) -> Hit:
        score = float(scores[position])
        return Hit(int(self.ids[position]), score, score < OFF_TOPIC_BELOW)

    def nearest(
        self, vector: np.ndarray, k: int = 10, exclude: set[int] | None = None
    ) -> list[Hit]:
        """By cosine similarity alone."""
        self.refresh()
        if not len(self.ids):
            return []
        scores = self.matrix @ vector.astype(np.float32)
        hits = []
        for idx in np.argsort(-scores):
            if exclude and int(self.ids[idx]) in exclude:
                continue
            hits.append(self._hit(int(idx), scores))
            if len(hits) >= k:
                break
        return hits

    def lexical(self, query: str, n: int) -> list[int]:
        """Index positions of the best BM25 matches, best first.

        Observations outside the index (superseded, or embedded with another
        model) are dropped, so both rankings cover the same rows."""
        self.refresh()
        expr = match_expression(query)
        if expr is None:
            return []
        rows = self.store.query(
            "SELECT rowid FROM observations_fts WHERE observations_fts MATCH ? "
            "ORDER BY rank LIMIT ?", (expr, n),
        )
        return [self._position[r["rowid"]] for r in rows if r["rowid"] in self._position]

    def fused(self, vector: np.ndarray, query: str, k: int = 10) -> list[Hit]:
        """Dense and lexical rankings combined by reciprocal rank fusion."""
        self.refresh()
        if not len(self.ids):
            return []
        scores = self.matrix @ vector.astype(np.float32)
        depth = max(k, CANDIDATES)
        dense = [int(p) for p in np.argsort(-scores)[:depth]]
        fused: dict[int, float] = {}
        for ranking in (dense, self.lexical(query, depth)):
            for rank, position in enumerate(ranking):
                fused[position] = fused.get(position, 0.0) + 1.0 / (RRF_K + rank + 1)
        # A stable sort: equal fused scores keep the dense order.
        order = sorted(fused, key=lambda p: -fused[p])[:k]
        return [self._hit(p, scores) for p in order]

    def vector_of(self, observation_id: int) -> np.ndarray | None:
        self.refresh()
        where = np.nonzero(self.ids == observation_id)[0]
        return self.matrix[where[0]] if len(where) else None


def search(index: Index, embedder: Embedder, query: str, k: int = 10) -> list[Hit]:
    """The library's search: embedding and full-text rank, fused."""
    return index.fused(embedder.embed_query(query), query, k)


def search_rollups(index: Index, embedder: Embedder, query: str, k: int = 5) -> list[RollupHit]:
    """Compacted periods matching the query, best first."""
    return index.rollups(embedder.embed_query(query), query, k)


def nearest_to_query(index: Index, embedder: Embedder, query: str, k: int = 10) -> list[Hit]:
    """By cosine similarity alone: whether the library covers the query at all."""
    return index.nearest(embedder.embed_query(query), k)


def similar_to(index: Index, observation_id: int, k: int = 12) -> list[Hit]:
    vec = index.vector_of(observation_id)
    if vec is None:
        return []
    return index.nearest(vec, k, exclude={observation_id})
