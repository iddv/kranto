"""Import observations, and the themes they formed, from a Parallax library.

**Observations** come from schema v1 JSONL (``library.jsonl`` files). Parallax embedded
``summary + "\\n" + why_it_matters`` with nomic-embed-text-v1.5, the ``search_document:``
prefix and Matryoshka truncation to 384 dimensions: the same scheme as the server, verified
to give identical vectors. Imported observations therefore share the index with new ones.
Each Parallax firehose becomes a source of kind ``parallax`` with status ``imported``; it
is a label for provenance and is never polled.

Records are taken oldest first, and each one is checked in turn:

1. its Parallax id, stored as ``external_id``: a row already imported is skipped, so the
   import is idempotent;
2. its canonical URL (``sources.canonical_url``, the rule ingest uses) against everything
   the library holds and every archive row kept before it: the first observation of a URL
   is the one kept;
3. near duplicates: the item's own text (``source_excerpt``) matching a kept row's at
   ``stories.skip_at`` or above, the story rule ingest uses for a crosspost, **and** the
   two embeddings at least ``NEAR_DUPLICATE_MIN_COSINE`` alike. Text alone is not enough:
   Parallax's Hacker News excerpts are boilerplate that matches across unrelated posts;
4. a record without ratings, ``why_it_matters`` or a compatible embedding is skipped:
   nothing is invented for it.

Imported rows keep the time Parallax observed them as ``created_at``, so they are never
"new since your last visit"; ``admitted_by`` is ``import``, which keeps them out of the
map's movement (``map/snapshot.py``) and, by default, out of card evidence. Their kind's
retention defaults to keep (``config.KIND_DEFAULT_DAYS``).

**A snapshot bundle** (``observations.json``, ``embeddings.bin``, ``trajectories.json``,
``keywords.json``, ``cluster_names.json`` in it and in its dated siblings) reconciles the
JSONL records with what Parallax clustered, and supplies its themes:
``import_parallax_themes`` writes one ``archive_themes`` row per lineage, named by the
most recent name Parallax gave it, with its history and its members.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import textsig
from .config import StoriesConfig
from .embed import EMBED_DIM, NOMIC_MODEL_NAME
from .sources import canonical_url, safe_url
from .store import Store, blob_to_vec, iso, utcnow, vec_to_blob
from .stored.misc import ThemeHistory, ThemeKeywords, ThemeNames
from .stored.observations import Tags
from .stored.sources import Params

PARALLAX_MODELS = {"nomic-embed-text-v1.5": NOMIC_MODEL_NAME}
ARCHIVE = "parallax"
# Two Parallax observations of the same URL (two interns, one post) are at least this
# alike in 95% of pairs (210 URLs, 307 pairs; median 0.936). A crosspost whose text
# matches must also say the same thing at least this closely to count as a copy.
NEAR_DUPLICATE_MIN_COSINE = 0.88
# Firehoses whose items share a template, so that different items match as text (the
# stories rule's templated sources): Polymarket's markets reach 1.0 between different events.
TEMPLATED_FIREHOSES = ("polymarket:",)
SNAPSHOT_SCHEMA_VERSIONS = (1, 2)


@dataclass
class ImportReport:
    files: int = 0
    read: int = 0
    imported: int = 0
    already_present: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    snapshot: dict | None = None

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


def _jsonl_files(paths: Iterable[Path]) -> list[Path]:
    """Files given directly, plus every ``library.jsonl`` under given directories."""
    out = set()
    for path in paths:
        if path.is_dir():
            out.update(path.rglob("library.jsonl"))
        elif path.is_file():
            out.add(path)
    return sorted(out)


def _source_for(store: Store, firehose: str, cache: dict[str, int]) -> int:
    if firehose in cache:
        return cache[firehose]
    params = json.dumps({"firehose": firehose}, sort_keys=True, separators=(",", ":"))
    row = store.query_one(
        "SELECT id FROM sources WHERE kind = 'parallax' AND params = ?", (params,)
    )
    if row:
        cache[firehose] = int(row["id"])
        return cache[firehose]
    label = firehose.split(":", 1)[-1]
    if firehose.startswith("reddit:"):
        label = "r/" + label.removeprefix("r/")
    source_id = store.insert("sources", {
        "kind": "parallax", "params": params, "label": f"{label} (Parallax)",
        "origin": "import", "created_at": iso(utcnow()),
    })
    store.set_status("source", source_id, "imported", "Parallax import")
    cache[firehose] = source_id
    return source_id


def _rating(rec: dict, key: str) -> float | None:
    try:
        return max(0.0, min(1.0, float(rec[key])))
    except (KeyError, TypeError, ValueError):
        return None


def _read_records(paths: Iterable[Path], report: ImportReport) -> list[dict]:
    """Every parseable record with an id, oldest first; a repeated id is counted once."""
    records: dict[str, dict] = {}
    for path in _jsonl_files(paths):
        report.files += 1
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                report.read += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    report.skip("unparseable line")
                    continue
                ext = str(rec.get("id") or "") if isinstance(rec, dict) else ""
                if not ext:
                    report.skip("no id")
                elif ext in records:
                    report.skip("repeated id")
                else:
                    records[ext] = rec
    return sorted(records.values(), key=lambda r: (str(r.get("ts") or ""), str(r["id"])))


class _Kept:
    """What the import compares a record with: the library's URLs, and the excerpt
    signatures and embeddings of the rows kept so far, for the near-duplicate rule."""

    def __init__(self, store: Store, skip_at: float) -> None:
        self.skip_at = skip_at
        self.own_urls = {r["canonical_url"] for r in store.query(
            "SELECT DISTINCT canonical_url FROM items_seen WHERE canonical_url IS NOT NULL")}
        self.archive_urls: set[str] = set()
        rows = store.query(
            "SELECT o.source_url, o.source_excerpt, o.embedding, o.admitted_by, s.kind, s.params "
            "FROM observations o LEFT JOIN sources s ON s.id = o.source_id "
            "WHERE o.embedding_model = ?", (NOMIC_MODEL_NAME,))
        self.vectors = np.zeros((len(rows) + 1024, EMBED_DIM), dtype=np.float32)
        self.sigs: list[np.ndarray | None] = []
        self.groups: list[str | None] = []
        for r in rows:
            url = canonical_url(r["source_url"])
            if url:
                (self.archive_urls if r["admitted_by"] == "import" else self.own_urls).add(url)
            firehose = Params.load(r["params"]).text("firehose") if r["kind"] == "parallax" \
                else None
            self._add(blob_to_vec(r["embedding"]), r["source_excerpt"], firehose)

    def _add(self, vec: np.ndarray, excerpt: str | None, firehose: str | None) -> None:
        n = len(self.sigs)
        if n == len(self.vectors):
            self.vectors = np.concatenate([self.vectors, np.zeros_like(self.vectors)])
        self.vectors[n] = vec
        self.sigs.append(textsig.signature(excerpt) if excerpt else None)
        self.groups.append(_template_group(firehose))

    def url_reason(self, url: str | None) -> str | None:
        if url in self.own_urls:
            return "same URL as an observation the library already holds"
        if url in self.archive_urls:
            return "same URL as an earlier archive observation"
        return None

    def near_duplicate(self, vec: np.ndarray, excerpt: str | None, firehose: str) -> bool:
        sig = textsig.signature(excerpt) if excerpt else None
        if sig is None or not self.sigs:
            return False
        close = np.nonzero(self.vectors[:len(self.sigs)] @ vec >= NEAR_DUPLICATE_MIN_COSINE)[0]
        group = _template_group(firehose)
        for i in close:
            other = self.sigs[i]
            if other is None or (group is not None and self.groups[i] == group):
                continue
            if float(textsig.similarity(sig, other[None, :])[0]) >= self.skip_at:
                return True
        return False

    def keep(self, url: str | None, vec: np.ndarray, excerpt: str | None, firehose: str) -> None:
        if url:
            self.archive_urls.add(url)
        self._add(vec, excerpt, firehose)


def _template_group(firehose: str | None) -> str | None:
    """Items of one templated firehose are never compared with each other."""
    if firehose and firehose.startswith(TEMPLATED_FIREHOSES):
        return firehose
    return None


def import_parallax(store: Store, paths: Iterable[Path], *, snapshot: Path | None = None,
                    stories: StoriesConfig | None = None, batch: int = 500) -> ImportReport:
    """Import schema v1 JSONL records from ``paths``; with ``snapshot`` (a bundle
    directory), also report how the records and the bundle reconcile."""
    report = ImportReport()
    records = _read_records(paths, report)
    if snapshot is not None:
        report.snapshot = reconcile(snapshot, records)
    existing = {r["external_id"] for r in store.query(
        "SELECT external_id FROM observations WHERE external_id IS NOT NULL")}
    kept = _Kept(store, (stories or StoriesConfig()).skip_at)
    sources: dict[str, int] = {}
    pending: list[tuple] = []

    def flush():
        if not pending:
            return
        with store.tx() as conn:
            conn.executemany(
                """INSERT INTO observations (
                    source_id, item_id, kind, title, summary, why_it_matters, content_quality,
                    durability, opportunity, signal, override, override_reason, tags,
                    source_url, source_excerpt, embedding, embedding_model, external_id,
                    prompt_version, admitted_by, created_at
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'parallax-import', 'import', ?)""",
                pending,
            )
        report.imported += len(pending)
        pending.clear()

    for rec in records:
        ext = str(rec["id"])
        if ext in existing:
            report.already_present += 1
            continue
        model = PARALLAX_MODELS.get(rec.get("embedding_model", ""))
        emb = rec.get("embedding")
        if model is None or not isinstance(emb, list) \
                or len(emb) != EMBED_DIM:  # stored-shape: isinstance first
            report.skip("no compatible embedding")
            continue
        ratings = [_rating(rec, k) for k in ("content_quality", "durability", "opportunity")]
        summary = str(rec.get("summary") or "").strip()
        why = str(rec.get("why_it_matters") or "").strip()
        if None in ratings or not summary or not why:
            report.skip("missing ratings or text")
            continue
        url = safe_url(rec.get("source_url"))
        canonical = canonical_url(url)
        reason = kept.url_reason(canonical)
        if reason:
            report.skip(reason)
            continue
        vec = np.asarray(emb, dtype=np.float32)
        vec /= np.linalg.norm(vec) or 1.0
        firehose = str(rec.get("firehose") or "unknown")
        excerpt = rec.get("source_excerpt")
        if kept.near_duplicate(vec, excerpt, firehose):
            report.skip("near duplicate (same text, same meaning)")
            continue
        cq, du, op = ratings
        pending.append((
            _source_for(store, firehose, sources),
            str(rec.get("data_source") or ext),
            rec.get("kind") if rec.get("kind") in ("beat", "mild_signal",
                                                   "sharp_signal") else "beat",
            summary, why, cq, du, op, cq * du * op,
            int(rec.get("override") is True), rec.get("override_reason"),
            Tags.write([str(t) for t in rec.get("tags") or []][:8]),
            url, excerpt, vec_to_blob(vec), model, ext,
            str(rec.get("ts") or iso(utcnow()))[:19] + "Z",
        ))
        existing.add(ext)
        kept.keep(canonical, vec, excerpt, firehose)
        if len(pending) >= batch:
            flush()
    flush()
    return report


# -- the snapshot bundle -----------------------------------------------------------


def _manifest(bundle: Path) -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") not in SNAPSHOT_SCHEMA_VERSIONS:
        raise ValueError(f"{bundle}: snapshot schema_version {manifest.get('schema_version')} "
                         f"is not one of {SNAPSHOT_SCHEMA_VERSIONS}")
    return manifest


def _bundle_observations(bundle: Path) -> tuple[list[dict], np.ndarray]:
    manifest = _manifest(bundle)
    obs = json.loads((bundle / "observations.json").read_text(encoding="utf-8"))
    n, d = int(manifest["observation_count"]), int(manifest["embedding_dim"])
    if len(obs) != n:
        raise ValueError(f"{bundle}: {len(obs)} observations, the manifest says {n}")
    emb = np.fromfile(bundle / "embeddings.bin", dtype=np.float32)
    if emb.size != n * d:
        raise ValueError(f"{bundle}: embeddings.bin holds {emb.size} floats, expected {n * d}")
    return obs, emb.reshape(n, d)


def reconcile(bundle: Path, records: list[dict]) -> dict:
    """How the JSONL records and a snapshot bundle agree: ids in one and not the other,
    and whether the embeddings are the same vectors."""
    obs, emb = _bundle_observations(bundle)
    by_id = {str(r["id"]): r for r in records}
    snap_ids = {str(o["id"]) for o in obs}
    differ = 0
    for o in obs:
        rec = by_id.get(str(o["id"]))
        vec = rec.get("embedding") if rec else None
        if isinstance(vec, list) and len(vec) == emb.shape[1]:
            a = np.asarray(vec, dtype=np.float32)
            b = emb[int(o["embedding_index"])]
            cos = float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))
            differ += cos < 0.999
    return {"snapshot": len(obs), "records": len(records),
            "in_both": len(snap_ids & set(by_id)),
            "snapshot_only": len(snap_ids - set(by_id)),
            "records_only": len(set(by_id) - snap_ids),
            "embeddings_differ": differ}


@dataclass
class ThemesReport:
    bundle: str = ""
    lineages: int = 0
    written: int = 0
    already_present: int = 0
    alive: int = 0
    named: int = 0
    members: int = 0


def _epoch_dir(snapshot_ts: str) -> str:
    """``2026-05-06T00:30:00Z`` -> ``2026-05-06T0030Z``, the dated bundle's directory."""
    day, _, clock = snapshot_ts.partition("T")
    return f"{day}T{clock[:2]}{clock[3:5]}Z"


def _names_at(history_dir: Path | None, snapshot_ts: str, cache: dict) -> dict:
    key = _epoch_dir(snapshot_ts)
    if key not in cache:
        names = {}
        path = history_dir / key / "cluster_names.json" if history_dir else None
        if path is not None and path.is_file():
            try:
                names = json.loads(path.read_text(encoding="utf-8")).get("names") or {}
            except (json.JSONDecodeError, AttributeError):
                names = {}
        cache[key] = names
    return cache[key]


def _cluster_number(cluster_id: str) -> str:
    return str(cluster_id).rsplit("_", 1)[-1]


def import_parallax_themes(store: Store, bundle: Path, *, history_dir: Path | None = None,
                           now=None) -> ThemesReport:
    """One ``archive_themes`` row per lineage in the bundle's ``trajectories.json``.

    A theme's name is the most recent non-null name Parallax gave its cluster, read from
    ``cluster_names.json`` in the dated bundle of each epoch (``history_dir``, by default
    the bundle's parent directory), else its keywords. A lineage alive in this bundle has
    its keywords and its members: the imported observations in its cluster here. Run it
    after the observations are imported. Idempotent per bundle."""
    manifest = _manifest(bundle)
    history_dir = history_dir if history_dir is not None else bundle.parent
    traj = json.loads((bundle / "trajectories.json").read_text(encoding="utf-8"))
    keywords_path = bundle / "keywords.json"
    keywords = (json.loads(keywords_path.read_text(encoding="utf-8")).get("keywords") or {}
                if keywords_path.is_file() else {})
    obs, _ = _bundle_observations(bundle)
    epochs = {e["snapshot_ts"]: e for e in traj.get("epochs") or []}
    last_epoch = max(epochs) if epochs else None
    report = ThemesReport(bundle=f"{manifest['generation_ts']} "
                                 f"{str(manifest.get('substrate_fingerprint', ''))[:23]}")
    ids = {r["external_id"]: r["id"] for r in store.query(
        "SELECT id, external_id FROM observations WHERE external_id IS NOT NULL")}
    by_cluster: dict[str, list[int]] = {}
    for o in obs:
        oid = ids.get(str(o["id"]))
        if oid is not None:
            by_cluster.setdefault(str(o["cluster_id"]), []).append(oid)
    names_cache: dict = {}
    created = iso(now or utcnow())
    for lineage in traj.get("lineages") or []:
        report.lineages += 1
        history = sorted(lineage.get("history") or [], key=lambda h: h["snapshot_ts"])
        if not history:
            continue
        lid = str(lineage["lineage_id"])
        if store.query_one("SELECT 1 FROM archive_themes WHERE archive = ? AND lineage_id = ? "
                           "AND bundle = ?", (ARCHIVE, lid, report.bundle)):
            report.already_present += 1
            continue
        names: list[dict] = []
        for h in reversed(history):
            name = _names_at(history_dir, h["snapshot_ts"], names_cache).get(
                _cluster_number(h["cluster_id"]))
            if isinstance(name, str) and name.strip():
                name = " ".join(name.split())
                if names and names[-1]["name"] == name:
                    names[-1]["first_at"] = h["snapshot_ts"]
                else:
                    names.append({"name": name, "first_at": h["snapshot_ts"],
                                  "last_at": h["snapshot_ts"]})
        last = history[-1]
        alive = last["snapshot_ts"] == last_epoch
        kw = [str(k) for k in keywords.get(_cluster_number(last["cluster_id"])) or []] \
            if alive else []
        name = names[0]["name"] if names else (", ".join(kw[:4]) or None)
        members = by_cluster.get(str(last["cluster_id"]), []) if alive else []
        row = {
            "archive": ARCHIVE, "lineage_id": lid, "bundle": report.bundle,
            "name": name, "names": ThemeNames.write(names), "keywords": ThemeKeywords.write(kw),
            "alive": int(alive), "size": int(last["observation_count"]),
            "first_at": history[0]["snapshot_ts"], "last_at": last["snapshot_ts"],
            "epochs": len(history),
            "history": ThemeHistory.write([
                {"at": h["snapshot_ts"], "cluster": h["cluster_id"],
                 "n": int(h["observation_count"]),
                 "share": round(h["observation_count"] / epochs[h["snapshot_ts"]][
                     "observation_count"], 5) if epochs.get(h["snapshot_ts"]) else None}
                for h in history]),
            "created_at": created,
        }
        with store.tx() as conn:
            theme_id = conn.execute(
                f"INSERT INTO archive_themes ({', '.join(row)}) "
                f"VALUES ({', '.join('?' * len(row))})", tuple(row.values())).lastrowid
            conn.executemany(
                "INSERT INTO archive_theme_members (theme_id, observation_id) VALUES (?, ?)",
                [(theme_id, oid) for oid in members])
        report.written += 1
        report.alive += int(alive)
        report.named += int(bool(names))
        report.members += len(members)
    return report


def latest_themes(store: Store, archive: str = ARCHIVE) -> list[dict]:
    """The current row of each theme of ``archive``: the latest bundle's."""
    rows = store.query(
        "SELECT t.* FROM archive_themes t WHERE t.archive = ? AND t.id = (SELECT MAX(l.id) "
        "FROM archive_themes l WHERE l.archive = t.archive AND l.lineage_id = t.lineage_id) "
        "ORDER BY t.alive DESC, t.size DESC, t.id", (archive,))
    out = []
    for r in rows:
        d = dict(r)
        for k in ("names", "keywords", "history"):
            d[k] = json.loads(d[k])
        out.append(d)
    return out


def theme_member_ids(store: Store, lineage_id: str, archive: str = ARCHIVE) -> list[int]:
    """The observations in a theme's current row that are still in the library."""
    return [r["observation_id"] for r in store.query(
        "SELECT m.observation_id FROM archive_theme_members m JOIN observations o "
        "ON o.id = m.observation_id WHERE m.theme_id = (SELECT MAX(id) FROM archive_themes "
        "WHERE archive = ? AND lineage_id = ?) ORDER BY m.observation_id",
        (archive, lineage_id))]


def lineage_at(themes: list[dict], cluster_id: str, at: str) -> dict | None:
    """The theme whose lineage held ``cluster_id`` at the last epoch on or before ``at``
    (an ISO time): cluster ids are only meaningful within one epoch."""
    epochs = sorted({h["at"] for t in themes for h in t["history"]})
    before = [e for e in epochs if e <= at]
    epoch = before[-1] if before else None
    if epoch is None:
        return None
    for t in themes:
        if any(h["at"] == epoch and h["cluster"] == cluster_id for h in t["history"]):
            return t
    return None
