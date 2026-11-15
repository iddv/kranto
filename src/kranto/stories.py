"""Stories and origins: one voice must not count as many.

A launch, a crosspost or a repost puts the same text in front of Kranto
several times. Each copy used to be judged and stored as an independent
observation, so one party speaking several times read as several voices: it
inflated clusters, read as a rising topic and passed the cross-source rule.

**Stories.** Before an item is judged, its title and the start of its body are
compared (``textsig``: word shingles, MinHash) with the items judged in the
last ``window_days``:

- At ``skip_at`` or above, an item from another source is the same text. It is
  consumed as ``near_duplicate`` without a model call: the judge has already
  read it. Within one source the same holds for an item posted again within
  ``same_source_days``, unless the source is templated (below).
- From ``link_at`` up to ``skip_at``, an item from another source is judged as
  usual (an edited crosspost can carry new detail) and joins the earlier
  item's story.

Each match is a ``story_links`` row naming the story's root, its earliest
member. Movement, bursts, idea candidates and the cross-source rule count
distinct stories, not observations (``map/snapshot.py``).

Thresholds were measured on Parallax's pre-judge item text (35,118 items, 138
pairs labelled; numbers on #35): cross-source pairs at 0.5 or more were the
same story in 99% of the weighted sample, while same-source pairs below 0.9 were
mostly templated posts (status bots, newsletters, changelogs) and, at 0.9 or
more, reposts within days or recurring threads a week or more apart.

**Templated sources.** Some feeds produce distinct events in nearly identical
words: Polymarket's markets reached a similarity of 1.0 between different
events. A source is treated as templated, and its items are never matched
with each other, when at least ``TEMPLATE_SHARE`` of its items in the window
each look like ``TEMPLATE_SIBLINGS`` or more of its other items (similarity
``TEMPLATE_MATCH_AT``, within ``same_source_days``): 26% of Polymarket's items,
at most 1% of any other Parallax source. Same-source matching also waits until
a source has ``TEMPLATE_MIN_ITEMS`` items in the window, so a templated feed's
first run is not read as reposts. ``stories.templated_sources`` lists sources
by hand.

**Origins.** The registrable domain of an item's canonical URL (the public
suffix list, via ``tld``): a vendor's blog, docs and changelog are one origin
however many sources carry them. Discussion and hosting platforms
(``PLATFORM_HOSTS``) name the place, not the speaker, so their own pages have
no origin; the platform rule already bounds them. The cross-source rule
and movement require that no origin supplies more than 70% of a cluster's
stories or of its new arrivals.

**The check.** ``null_check`` compares the share of recent items that match
another item with the same share on column-permuted signatures, which keep
each position's distribution (shared boilerplate survives) and break each
item's identity. If chance explains the matches, the map page says so.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

import numpy as np

from . import textsig
from .config import StoriesConfig
from .sources import Item, canonical_url
from .store import Store, iso, utcnow

# Fewer words than this and a title is not evidence that two items are one story.
MIN_WORDS = 5
TEMPLATE_MATCH_AT = 0.8
TEMPLATE_SIBLINGS = 3
TEMPLATE_SHARE = 0.05
TEMPLATE_MIN_ITEMS = 20
# The null must explain no more than this fraction of the observed match rate.
NULL_MAX_FRACTION = 0.2
NULL_SAMPLE = 400
SEED = 35
_COMPARE_BYTES = 32_000_000

# Hosts whose pages are written by many unrelated people: their domain names the
# platform, not the speaker.
PLATFORM_HOSTS = frozenset({
    "reddit.com", "redd.it", "ycombinator.com", "lobste.rs", "x.com", "twitter.com",
    "bsky.app", "mastodon.social", "github.com", "gitlab.com", "medium.com", "youtube.com",
    "youtu.be", "huggingface.co", "substack.com", "news.google.com",
})


def signature(item: Item) -> np.ndarray | None:
    """The item's pre-judge text as a signature, or None when it is too short to
    tell one story from another."""
    text = textsig.item_text(item.title, item.body)
    if len(textsig.normalise(text)) < MIN_WORDS:
        return None
    return textsig.signature(text)


@dataclass(frozen=True)
class Match:
    source_id: int
    item_id: str
    root_source_id: int
    root_item_id: str
    similarity: float
    skip: bool  # True: the same text; consumed without judging


class Index:
    """Signatures of the items judged in the window, in memory for one run."""

    def __init__(self, cfg: StoriesConfig, rows: list, now: datetime) -> None:
        self.cfg = cfg
        self.now = now
        self._sources: list[int] = [r["source_id"] for r in rows]
        self._items: list[str] = [r["item_id"] for r in rows]
        self._roots: list[tuple[int, str]] = [
            (r["root_source_id"], r["root_item_id"]) if r["root_item_id"] is not None
            else (r["source_id"], r["item_id"]) for r in rows]
        self._times = np.array([_ts(r["created_at"]) for r in rows], dtype=np.float64)
        self._sigs = (np.stack([textsig.from_blob(r["signature"]) for r in rows])
                      if rows else np.zeros((0, textsig.PERMUTATIONS), dtype=np.uint32))
        self._pending: list[np.ndarray] = []
        self.templated = self._templated()
        counts = Counter(self._sources)
        self.established = {s for s, n in counts.items() if n >= TEMPLATE_MIN_ITEMS}

    @classmethod
    def load(cls, store: Store, cfg: StoriesConfig, now: datetime | None = None) -> Index:
        now = now or utcnow()
        rows = store.query(
            """
            SELECT s.source_id, s.item_id, s.signature, s.created_at,
                   l.root_source_id, l.root_item_id
            FROM item_signatures s
            LEFT JOIN story_links l ON l.source_id = s.source_id AND l.item_id = s.item_id
            WHERE s.method = ? AND s.created_at >= ?
            ORDER BY s.id
            """,
            (textsig.METHOD, iso(now - timedelta(days=cfg.window_days))),
        )
        return cls(cfg, rows, now)

    def __len__(self) -> int:
        return len(self._sources)

    def _matrix(self) -> np.ndarray:
        if self._pending:
            self._sigs = np.vstack([self._sigs, np.stack(self._pending)])
            self._pending = []
        return self._sigs

    def _templated(self) -> set[int]:
        """Sources whose items mostly look like several of their other items."""
        out = set(self.cfg.templated_sources)
        sources = np.array(self._sources)
        window = self.cfg.same_source_days * 86400
        for source, n in Counter(self._sources).items():
            if n < TEMPLATE_MIN_ITEMS or source in out:
                continue
            idx = np.nonzero(sources == source)[0]
            sigs, times = self._sigs[idx], self._times[idx]
            siblings = np.zeros(len(idx), dtype=np.int64)
            step = _rows_per_chunk(len(idx))
            for lo in range(0, len(idx), step):
                sims = (sigs[lo:lo + step, None, :] == sigs[None, :, :]).mean(axis=2)
                near = np.abs(times[lo:lo + step, None] - times[None, :]) <= window
                hit = (sims >= TEMPLATE_MATCH_AT) & near
                hit[np.arange(hit.shape[0]), np.arange(lo, lo + hit.shape[0])] = False
                siblings[lo:lo + step] = hit.sum(axis=1)
            if (siblings >= TEMPLATE_SIBLINGS).mean() >= TEMPLATE_SHARE:
                out.add(source)
        return out

    def same_source_allowed(self, source_id: int) -> bool:
        return source_id in self.established and source_id not in self.templated

    def match(self, sig: np.ndarray | None, source_id: int, item_id: str,
              now: datetime) -> Match | None:
        """The earlier item this one repeats, if any: the most similar qualifying one."""
        if sig is None or not len(self):
            return None
        sims = textsig.similarity(sig, self._matrix())
        sources = np.array(self._sources)
        cross = (sources != source_id) & (sims >= self.cfg.link_at)
        same = np.zeros_like(cross)
        if self.same_source_allowed(source_id):
            recent = (_ts(iso(now)) - self._times) <= self.cfg.same_source_days * 86400
            same = (sources == source_id) & recent & (sims >= self.cfg.skip_at)
            if same.any():
                same &= np.array([i != item_id for i in self._items])
        candidates = np.nonzero(cross | same)[0]
        if not len(candidates):
            return None
        best = int(candidates[np.argmax(sims[candidates])])  # ties: the earliest
        root = self._roots[best]
        return Match(self._sources[best], self._items[best], root[0], root[1],
                     round(float(sims[best]), 4), bool(sims[best] >= self.cfg.skip_at))

    def add(self, source_id: int, item_id: str, sig: np.ndarray, root: tuple[int, str],
            now: datetime) -> None:
        self._sources.append(source_id)
        self._items.append(item_id)
        self._roots.append(root)
        self._times = np.append(self._times, _ts(iso(now)))
        self._pending.append(np.asarray(sig, dtype=np.uint32))


def record(store: Store, index: Index, *, source_id: int, item_id: str,
           sig: np.ndarray | None, match: Match | None, judged: bool, run_uuid: str | None,
           now: datetime) -> None:
    """Keep the item's signature for later comparisons and, if it repeated an
    earlier item, the story link. Called once the item is consumed."""
    if sig is None:
        return
    created = iso(now)
    root = (match.root_source_id, match.root_item_id) if match else (source_id, item_id)
    with store.tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO item_signatures (source_id, item_id, method, signature, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (source_id, item_id, textsig.METHOD, textsig.to_blob(sig), created))
        if match is not None:
            conn.execute(
                "INSERT OR IGNORE INTO story_links (source_id, item_id, matched_source_id, "
                "matched_item_id, root_source_id, root_item_id, similarity, judged, run_uuid, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, item_id, match.source_id, match.item_id, root[0], root[1],
                 match.similarity, int(judged), run_uuid, created))
    index.add(source_id, item_id, sig, root, now)


# -- reading ---------------------------------------------------------------------


def story_roots(store: Store) -> dict[tuple[int, str], tuple[int, str]]:
    """(source_id, item_id) -> the root of its story, for every linked item."""
    return {(r["source_id"], r["item_id"]): (r["root_source_id"], r["root_item_id"])
            for r in store.query("SELECT source_id, item_id, root_source_id, root_item_id "
                                 "FROM story_links")}


def deep_dive_parents(store: Store) -> dict[int, int]:
    """child observation id -> parent observation id, for deep dives' children.

    A child is something one step from its parent (its discussion, a page it
    links to, a repository it names), reached because the parent scored high:
    it is not an independent voice, so it belongs to its parent's story and
    never adds one of its own."""
    return {r["child_id"]: r["parent_id"]
            for r in store.query("SELECT child_id, parent_id FROM observation_links")}


def story_keys(store: Store, rows) -> dict[int, str]:
    """observation id -> story key for ``rows`` (``id``, ``source_id``, ``item_id``):
    the root of its item's story, or for a deep dive's child its parent's story."""
    roots = story_roots(store)
    parents = deep_dive_parents(store)
    keys = {r["id"]: story_key(roots, r["id"], r["source_id"], r["item_id"]) for r in rows}
    missing = sorted({p for c, p in parents.items() if c in keys and p not in keys})
    if missing:
        for r in store.query(f"SELECT id, source_id, item_id FROM observations WHERE id IN "
                             f"({','.join('?' * len(missing))})", tuple(missing)):
            keys.setdefault(r["id"], story_key(roots, r["id"], r["source_id"], r["item_id"]))
    for child in list(keys):
        parent = parents.get(child)
        if parent in keys:
            keys[child] = keys[parent]
    return keys


def story_key(roots: dict, observation_id: int, source_id: int | None,
              item_id: str | None) -> str:
    """A story's identity: its root item, or the observation itself when it has no
    item (imported rows)."""
    if source_id is None or item_id is None:
        return f"obs:{observation_id}"
    root = roots.get((source_id, item_id), (source_id, item_id))
    return f"item:{root[0]}:{root[1]}"


def origin(url: str | None) -> str | None:
    """The registrable domain of ``url`` (``docs.example.co.uk`` -> ``example.co.uk``),
    or None for a platform page, an address without a public suffix, or no URL."""
    from tld import get_fld

    url = canonical_url(url)
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    domain = get_fld(f"https://{host}", fail_silently=True)
    if not domain or domain in PLATFORM_HOSTS:
        return None
    return domain


def origin_mix(origins: Iterable[str | None]) -> tuple[dict[str, int], float]:
    """Counts per origin and the largest origin's share of all (including stories
    with no origin, which never dominate)."""
    origins = list(origins)
    counts = Counter(o for o in origins if o)
    total = len(origins) or 1
    ordered = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return ordered, round(max(counts.values(), default=0) / total, 4)


# -- the check -------------------------------------------------------------------


def null_check(store: Store, cfg: StoriesConfig, now: datetime | None = None,
               sample: int = NULL_SAMPLE) -> dict:
    """Is the near-duplicate match rate more than shared boilerplate explains?

    Real: the share of sampled items in the window whose signature reaches
    ``link_at`` against any other item. Null: the same on signatures whose
    columns were permuted independently across items, which keeps how common
    each hash value is in each position (a template shared by many items
    survives) and destroys which item it belonged to. On distinct texts the
    null is near zero; on texts that share most of their words it is not, and
    the check fails.
    """
    now = now or utcnow()
    rows = store.query(
        "SELECT signature FROM item_signatures WHERE method = ? AND created_at >= ?",
        (textsig.METHOD, iso(now - timedelta(days=cfg.window_days))))
    out = {"method": "column-permuted MinHash signatures", "link_at": cfg.link_at,
           "items": len(rows)}
    if len(rows) < 2 * TEMPLATE_MIN_ITEMS:
        return {**out, "status": "too_few"}
    sigs = np.stack([textsig.from_blob(r["signature"]) for r in rows])
    rng = np.random.default_rng(SEED)
    null = np.column_stack([rng.permutation(sigs[:, j]) for j in range(sigs.shape[1])])
    picked = rng.choice(len(sigs), size=min(sample, len(sigs)), replace=False)
    real_rate = _match_rate(sigs, picked, cfg.link_at)
    null_rate = _match_rate(null, picked, cfg.link_at)
    explained = null_rate > NULL_MAX_FRACTION * real_rate if real_rate else null_rate > 0
    return {**out, "status": "ok", "sample": int(len(picked)),
            "real_rate": round(real_rate, 4), "null_rate": round(null_rate, 4),
            "explained_by_chance": bool(explained)}


def _match_rate(sigs: np.ndarray, picked: np.ndarray, threshold: float) -> float:
    hits = 0
    step = _rows_per_chunk(len(sigs))
    for lo in range(0, len(picked), step):
        rows = picked[lo:lo + step]
        sims = (sigs[rows, None, :] == sigs[None, :, :]).mean(axis=2)
        sims[np.arange(len(rows)), rows] = 0.0
        hits += int((sims >= threshold).any(axis=1).sum())
    return hits / len(picked)


def _rows_per_chunk(n: int) -> int:
    """Rows compared at once with ``n`` others, keeping the comparison under ~32 MB."""
    return max(1, _COMPARE_BYTES // max(1, n * textsig.PERMUTATIONS))


# -- retention -------------------------------------------------------------------


def purge_signatures(store: Store, cfg: StoriesConfig, now: datetime,
                     run_uuid: str | None) -> int:
    """Remove signatures older than the comparison window, with a purge record.

    They are compared over ``window_days`` only; afterwards nothing reads them.
    Story links (ids only) and ``items_seen`` stay."""
    cutoff = iso(now - timedelta(days=cfg.window_days))
    with store.purge() as conn:
        n = conn.execute("DELETE FROM item_signatures WHERE created_at < ?",
                         (cutoff,)).rowcount
        if n:
            conn.execute(
                "INSERT INTO purges (run_uuid, table_name, row_count, reason, rollup_ids, "
                "detail, created_at) VALUES (?, 'item_signatures', ?, ?, '[]', ?, ?)",
                (run_uuid, n, f"older than the {cfg.window_days:g}-day comparison window",
                 json.dumps({"before": cutoff}), iso(now)))
    return n


def _ts(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
