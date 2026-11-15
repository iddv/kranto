"""Retention and compaction.

An observation is kept for its retention age: a per-source override (an
append-only ``source_retention`` event, latest wins), else the setting for its
source's kind, else ``retention.default_days``. Past it, the observation is
compacted: grouped with the other expired observations of its calendar week
(by ``created_at``, weeks starting Monday UTC), clustered by k-means on the
stored embeddings, and each cluster becomes one ``rollups`` row. Then, in one
transaction per week, the observations are removed together with their map
points, the model calls behind them (whose request and response hold the
source's raw text), cached explanations that cite them, and deep-dive links
(``observation_links``) with either end among them. Each removal is a
``purges`` row saying what went, how many, why, when, and into which rollups.
Model calls for items that were judged but not kept (gated, skipped, screened
out, a reply that did not parse), and every item's screen call, expire at
the same age, per the item's source; no observation stands for them, so they
are removed without a rollup. Every other
call (failed calls, scout, names, explanations, cards, verification) expires at
``retention.default_days`` unless something that remains still references it.

Text signatures (``item_signatures``, #35) are compared over the stories
window only, and are removed through the same recorded purge once older than
it, whatever the retention age.

What stays: ``items_seen`` (the dedup key and canonical URL, no text), so an
expired item is never fetched and judged again; story links (ids only); clusters and their
trajectories, which hold counts and shares; idea cards, which carry a snapshot
of their evidence; and the rollups, which keep a centroid embedding (with its
model) so they remain searchable.

A rollup's name and summary are one tier-1 call per cluster, scrubbed before
they are stored. When no call can be made (paused, over budget, no key) the
rollups are written without them rather than keeping text past its age.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from . import activity, notify, prompts, stories
from .config import KIND_MAX_DAYS, MAX_TOKENS, RetentionConfig, StoriesConfig, cap_days
from .intern import extract_json_object
from .llm import BudgetExceeded, FatalLLMError, LLMClient, LLMError, Paused
from .map import compute
from .scrub import scrub
from .sources import safe_url
from .store import Store, blob_to_vec, iso, utcnow, vec_to_blob
from .stored import runs as stored_runs
from .stored.cards import Card
from .stored.map import (
    RollupKeywords,
    RollupKindCounts,
    RollupPlatformMix,
    RollupSourceMix,
    RollupTopicMix,
    RollupUrls,
)
from .tick import RunLocked, run_lock

# Below this many observations a week's group is one rollup; a split of a
# handful of points is noise.
MIN_TO_SPLIT = 10
# No cluster smaller than about this: k is clamped to n // MIN_ROLLUP_SIZE.
MIN_ROLLUP_SIZE = 5
MAX_URLS = 5
SAMPLE = 12
SUMMARY_CHARS = 300
NAME_CHARS = 80
ROLLUP_SUMMARY_CHARS = 1500
# Measured 2026-09-27 on copies of the #63 benchmark library and the Parallax
# import (61 calls on Haiku 4.5): completion tokens averaged 177, at most 265.
# Unused tokens cost nothing; a cut-off reply is an error.
ROLLUP_MAX_TOKENS = MAX_TOKENS["rollup"]
CHUNK = 500


@dataclass
class CompactReport:
    run_uuid: str
    status: str = "ok"
    error: str | None = None
    expired: int = 0
    periods: int = 0
    rollups: int = 0
    summaries_written: int = 0
    summaries_failed: int = 0
    summaries_skipped: str | None = None
    removed: dict[str, int] = field(default_factory=dict)
    unkept_calls: int = 0
    unreferenced_calls: int = 0
    rollup_ids: list[int] = field(default_factory=list)

    def summary(self) -> str:
        return json.dumps({k: v for k, v in self.__dict__.items()
                           if k not in ("run_uuid", "status", "error", "rollup_ids")})


# -- retention ages --------------------------------------------------------------


def set_source_retention(store: Store, source_id: int, days: float | None,
                         note: str | None = None, *, now: datetime | None = None) -> None:
    """Record a retention override for one source; ``None`` returns it to the defaults."""
    row = store.query_one("SELECT kind FROM sources WHERE id = ?", (source_id,))
    if row is None:
        raise ValueError(f"no source {source_id}")
    if days is not None and days < 0:
        raise ValueError("retention days must be 0 or more (0: keep forever)")
    cap = KIND_MAX_DAYS.get(row["kind"])
    if days is not None and cap is not None and (days == 0 or days > cap):
        raise ValueError(f"a {row['kind']} source is kept at most {cap:g} days ({row['kind']}'s "
                         "policies for API data)")
    store.insert("source_retention", {
        "source_id": source_id, "days": days, "note": note, "created_at": iso(now or utcnow()),
    })


def source_overrides(store: Store) -> dict[int, float | None]:
    """The latest override per source; a ``None`` value means back to the defaults."""
    rows = store.query(
        "SELECT r.source_id, r.days FROM source_retention r WHERE r.id = "
        "(SELECT MAX(id) FROM source_retention l WHERE l.source_id = r.source_id)")
    return {r["source_id"]: r["days"] for r in rows}


def retention_days(store: Store, cfg: RetentionConfig) -> dict[int | None, float]:
    """Retention age per source id (``None``: observations without a source)."""
    overrides = source_overrides(store)
    out: dict[int | None, float] = {None: cfg.default_days}
    for r in store.query("SELECT id, kind FROM sources"):
        override = overrides.get(r["id"])
        out[r["id"]] = cap_days(r["kind"], override) if override is not None \
            else cfg.days_for_kind(r["kind"])
    return out


def _expired(store: Store, cfg: RetentionConfig, now: datetime) -> list[Any]:
    rows = []
    for source_id, days in retention_days(store, cfg).items():
        if days <= 0:
            continue
        where = "o.source_id IS NULL" if source_id is None else "o.source_id = ?"
        params = () if source_id is None else (source_id,)
        rows += store.query(
            f"""SELECT o.id, o.source_id, o.kind, o.signal, o.summary, o.source_url,
                       o.item_published_at, o.embedding, o.embedding_model, o.llm_call_id,
                       o.created_at, COALESCE(s.label, 'unknown') AS label
                FROM observations o LEFT JOIN sources s ON s.id = o.source_id
                WHERE {where} AND o.created_at < ? ORDER BY o.id""",
            (*params, iso(now - timedelta(days=days))),
        )
    return rows


def week_start(created_at: str) -> datetime:
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


# -- clustering ------------------------------------------------------------------


def choose_k(x: np.ndarray) -> int:
    """k for one week's group, as the map chooses it, clamped for small groups.

    From ``compute.MIN_OBSERVATIONS`` up, the map's own selection (UMAP, then the
    most stable of the best silhouettes), with k at most n // MIN_ROLLUP_SIZE.
    Below that UMAP has too few neighbours to mean much, so k is picked by
    cosine silhouette of k-means on the stored embeddings over the same clamped
    range; below ``MIN_TO_SPLIT``, one rollup."""
    n = len(x)
    if n < MIN_TO_SPLIT:
        return 1
    cap = max(2, n // MIN_ROLLUP_SIZE)
    if n >= compute.MIN_OBSERVATIONS:
        return compute.select_k(x, hi_cap=cap).k
    best_k, best = 2, -2.0
    for k in range(2, min(cap, compute.k_range(n)[1]) + 1):
        score = compute._silhouette(x, compute._kmeans(x, k), "cosine")
        if score > best + 1e-9:
            best_k, best = k, score
    return best_k


def cluster_group(x: np.ndarray) -> np.ndarray:
    k = choose_k(x)
    if k == 1:
        return np.zeros(len(x), dtype=int)
    return compute._kmeans(x, k).astype(int)


# -- naming ----------------------------------------------------------------------


def _summarise(llm: LLMClient, *, period: str, size: int, sources: dict[str, int],
               keywords: list[str], summaries: list[str],
               run_uuid: str) -> tuple[str | None, str | None, int | None]:
    prompt = prompts.load("rollup")
    text = prompt.render(
        period=period, size=str(size),
        sources=", ".join(f"{s} ({n})" for s, n in list(sources.items())[:8]),
        keywords=", ".join(keywords) or "(none)",
        observations="\n".join(f"- {' '.join(s.split())[:SUMMARY_CHARS]}" for s in summaries),
    )
    completion = llm.complete(
        tier="judge", purpose="rollup", prompt_version=prompt.version, run_uuid=run_uuid,
        messages=[{"role": "user", "content": text}], max_tokens=llm.max_tokens("rollup"),
        retry_truncated=True,
        temperature=0.2,
    )
    obj = extract_json_object(completion.text) or {}
    name, summary = obj.get("name"), obj.get("summary")
    name = scrub(name.strip()) if isinstance(name, str) and name.strip() else None
    if name is not None and len(name) > NAME_CHARS:
        name = None
    summary = (_clip(scrub(" ".join(summary.split())))
               if isinstance(summary, str) and summary.strip() else None)
    return name, summary, completion.call_id


def _clip(text: str) -> str:
    """At most ``ROLLUP_SUMMARY_CHARS``, cut after the last whole sentence that fits."""
    if len(text) <= ROLLUP_SUMMARY_CHARS:
        return text
    head = text[:ROLLUP_SUMMARY_CHARS]
    end = max(head.rfind(". "), head.rfind("! "), head.rfind("? "))
    return head[:end + 1] if end > 0 else head.rsplit(" ", 1)[0] + "..."


# -- compaction ------------------------------------------------------------------


def compact(
    store: Store,
    cfg: RetentionConfig,
    llm: LLMClient | None,
    *,
    stories_cfg: StoriesConfig | None = None,
    clock: Callable[[], datetime] = utcnow,
    activity_cfg: Any = None,
) -> CompactReport:
    """``activity_cfg`` (``config.ActivityConfig``): the runs' marks past their keep are
    removed too, with their purge record; None leaves them."""
    report = CompactReport(run_uuid=activity.run_uuid("compact"))
    started = clock()
    # The snapshot lock too: a snapshot that read an observation compaction then
    # removed would write map points for a row that is gone.
    locks = [p for p in (store.lock_path("compact"), store.lock_path("snapshot")) if p]
    try:
        with contextlib.ExitStack() as stack:
            for path in locks:
                stack.enter_context(run_lock(path))
            _compact(store, cfg, llm, report, clock)
            signatures = stories.purge_signatures(store, stories_cfg or StoriesConfig(),
                                                  clock(), report.run_uuid)
            if signatures:
                report.removed["item_signatures"] = signatures
            if activity_cfg is not None:
                marks = activity.prune(store, keep_days=activity_cfg.keep_days,
                                       max_rows=activity_cfg.max_rows,
                                       run_uuid_=report.run_uuid, now=clock())
                if marks:
                    report.removed["run_marks"] = marks
    except RunLocked as exc:
        report.status, report.error = "skipped", str(exc)
    except Exception as exc:  # recorded and alarmed rather than lost in a log
        report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"
    # Nothing past its age is still a run that did its work ("ok"): a skipped run
    # does not count for due-ness, so the scheduler would retry it every minute.
    if report.status == "ok" and report.summaries_failed:
        report.status = "degraded"
        report.error = f"{report.summaries_failed} rollup summaries could not be written"
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "compact", "status": report.status,
        "started_at": iso(started), "finished_at": iso(clock()),
        "summary": stored_runs.text_for("compact", report.summary()), "error": report.error,
    })
    notify.alarm_for_run(store, kind="compact", run_uuid=report.run_uuid,
                         status=report.status, error=report.error)
    return report


def _compact(store: Store, cfg: RetentionConfig, llm: LLMClient | None,
             report: CompactReport, clock: Callable[[], datetime]) -> None:
    now = clock()
    days = retention_days(store, cfg)
    rows = _expired(store, cfg, now)
    report.expired = len(rows)
    if rows:
        _compact_observations(store, rows, days, llm, report, clock)
    _purge_unkept_calls(store, days, now, report, clock)
    _purge_unreferenced_calls(store, days[None], now, report, clock)


def _compact_observations(store: Store, rows: list[Any], days: dict[int | None, float],
                          llm: LLMClient | None, report: CompactReport,
                          clock: Callable[[], datetime]) -> None:
    if llm is not None:
        try:
            llm.check_can_spend()
        except LLMError as exc:
            report.summaries_skipped = str(exc)
            llm = None
    else:
        report.summaries_skipped = "no model client"

    topic_of_source: dict[int, list[str]] = {}
    for r in store.query("SELECT ts.source_id, t.name FROM topic_links ts "
                         "JOIN topics_now t ON t.id = ts.topic_id"):
        topic_of_source.setdefault(r["source_id"], []).append(r["name"])

    weeks: dict[datetime, list[Any]] = {}
    for r in rows:
        weeks.setdefault(week_start(r["created_at"]), []).append(r)
    for start in sorted(weeks):
        members = weeks[start]
        rollups: list[dict[str, Any]] = []
        for model in sorted({r["embedding_model"] for r in members}):
            group = [r for r in members if r["embedding_model"] == model]
            llm = _rollups_for(group, start, model, topic_of_source, llm, report, rollups)
        _write_period(store, start, members, rollups, days, report, clock)
        report.periods += 1


def _rollups_for(group: list[Any], start: datetime, model: str,
                 topic_of_source: dict[int, list[str]], llm: LLMClient | None,
                 report: CompactReport, out: list[dict[str, Any]]) -> LLMClient | None:
    """Cluster one week's observations of one embedding model into rollup rows.

    Returns the model client to keep using: ``None`` once a call showed that no
    more can be made this run (paused, over budget, a fatal provider error)."""
    x = np.stack([blob_to_vec(r["embedding"]) for r in group]).astype(np.float32)
    labels = cluster_group(x)
    k = int(labels.max()) + 1
    by_cluster = [[i for i in range(len(group)) if labels[i] == c] for c in range(k)]
    kw = compute.keywords([[group[i]["summary"] for i in idx] for idx in by_cluster])
    period = f"{start.date().isoformat()} to {(start + timedelta(days=6)).date().isoformat()}"
    for c, idx in enumerate(by_cluster):
        if not idx:
            continue
        rows = [group[i] for i in idx]
        center = x[idx].mean(axis=0)
        center /= np.linalg.norm(center) or 1.0
        mix, _, _ = compute.source_mix([r["label"] for r in rows])
        platforms = Counter(compute.platform(r["label"]) for r in rows)
        topics: Counter[Any] = Counter()
        for r in rows:
            topics.update(topic_of_source.get(r["source_id"], []))
        urls: list[str] = []
        for r in sorted(rows, key=lambda r: (-r["signal"], r["id"])):
            url = safe_url(r["source_url"])
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= MAX_URLS:
                break
        name = summary = call_id = None
        if llm is not None:
            nearest = [rows[j] for j in np.argsort(-(x[idx] @ center))[:SAMPLE]]
            try:
                name, summary, call_id = _summarise(
                    llm, period=period, size=len(rows), sources=mix, keywords=kw[c],
                    summaries=[r["summary"] for r in nearest], run_uuid=report.run_uuid)
            except (Paused, BudgetExceeded, FatalLLMError) as exc:
                report.summaries_skipped = str(exc)
                report.summaries_failed += 1
                llm = None
            except LLMError:
                report.summaries_failed += 1
            else:
                if summary:
                    report.summaries_written += 1
                else:
                    report.summaries_failed += 1
        ids = [r["id"] for r in rows]
        out.append({
            "period_start": iso(start), "period_end": iso(start + timedelta(days=7)),
            "first_at": min(r["created_at"] for r in rows),
            "last_at": max(r["created_at"] for r in rows),
            "size": len(rows), "source_mix": RollupSourceMix.write(mix),
            "platform_mix": RollupPlatformMix.write(dict(platforms.most_common())),
            "topic_mix": RollupTopicMix.write(dict(topics.most_common())),
            "mean_signal": round(float(np.mean([r["signal"] for r in rows])), 5),
            "kind_counts": RollupKindCounts.write(
                dict(Counter(r["kind"] for r in rows).most_common())),
            "keywords": RollupKeywords.write(kw[c]), "name": name, "summary": summary,
            "summary_call_id": call_id, "urls": RollupUrls.write(urls),
            "centroid": vec_to_blob(center), "embedding_model": model,
            "replaced_count": len(ids), "replaced_fingerprint": compute.fingerprint(ids, model),
            "run_uuid": report.run_uuid,
        })
    return llm


def _chunks(ids: list[int]) -> Iterator[list[int]]:
    for i in range(0, len(ids), CHUNK):
        yield ids[i:i + CHUNK]


def remove_observations(store: Store, ids: list[int], reason: str, *,
                        clock: Callable[[], datetime] = utcnow) -> CompactReport:
    """Remove observations before their age, through the recorded purge, with no rollup:
    a post its author deleted, or one the person asked to be removed,
    leaves nothing derived from it behind but the purge record and its ``items_seen`` row (so
    it is never fetched again). Model calls, map points, explanations and deep-dive links go
    with it, as in compaction."""
    report = CompactReport(run_uuid=uuid.uuid4().hex)
    ids = sorted({int(i) for i in ids})
    if not ids:
        return report
    marks = ",".join("?" * len(ids))
    rows = store.query(
        f"""SELECT o.id, o.source_id, o.kind, o.llm_call_id, o.created_at, o.summary,
                   o.source_url, o.item_published_at, COALESCE(s.label, 'unknown') AS label
            FROM observations o LEFT JOIN sources s ON s.id = o.source_id
            WHERE o.id IN ({marks}) ORDER BY o.id""", tuple(ids))
    if rows:
        start = week_start(min(r["created_at"] for r in rows))
        _write_period(store, start, rows, [], {None: 0}, report, clock, reason=reason)
    report.expired = len(rows)
    return report


def _write_period(store: Store, start: datetime, members: list[Any],
                  rollups: list[dict[str, Any]], days: dict[int | None, float],
                  report: CompactReport, clock: Callable[[], datetime], *,
                  reason: str | None = None) -> None:
    """Write a week's rollups and remove what they replace, in one transaction."""
    ids = [r["id"] for r in members]
    id_set = set(ids)
    created = iso(clock())
    ages = sorted({days.get(r["source_id"], days[None]) for r in members})
    reason = reason or (
        f"retention: observed more than {ages[0]:g} days ago" if len(ages) == 1 else
        f"retention: observed longer ago than their sources' retention ages "
        f"({', '.join(f'{a:g}' for a in ages)} days)")
    with store.purge() as conn:
        rollup_ids = []
        for row in rollups:
            cur = conn.execute(
                f"INSERT INTO rollups ({', '.join(row)}, created_at) "
                f"VALUES ({', '.join('?' * len(row))}, ?)", (*row.values(), created))
            assert cur.lastrowid is not None   # an INSERT always has one
            rollup_ids.append(int(cur.lastrowid))
        _snapshot_idea_evidence(conn, members, id_set, created)

        # The model calls behind these observations, unless a row that stays uses one.
        call_ids = sorted({r["llm_call_id"] for r in members if r["llm_call_id"]})
        stay = _calls_kept(conn, set(call_ids), id_set)
        call_ids = [c for c in call_ids if c not in stay]

        cost_by_day: dict[str, float] = {}
        for chunk in _chunks(call_ids):
            for r in conn.execute(
                    f"SELECT created_at, cost_usd FROM llm_calls WHERE id IN "
                    f"({','.join('?' * len(chunk))})", chunk):
                if r[1]:
                    cost_by_day[r[0][:10]] = round(cost_by_day.get(r[0][:10], 0.0) + r[1], 8)

        synth_ids = []
        for r in conn.execute("SELECT id, subject, input_ids FROM syntheses"):
            cited = set(json.loads(r[2] or "[]"))
            subject = r[1] or ""
            if cited & id_set or (subject.startswith("obs:")
                                  and _int(subject[4:]) in id_set):
                synth_ids.append(r[0])

        # A deep dive's link goes with either end. The other end stays an
        # ordinary observation until its own age.
        link_ids: list[int] = []
        relations: Counter[str] = Counter()
        for chunk in _chunks(ids):
            marks = ",".join("?" * len(chunk))
            for r in conn.execute(
                    f"SELECT id, relation FROM observation_links WHERE parent_id IN ({marks}) "
                    f"OR child_id IN ({marks})", (*chunk, *chunk)):
                if r[0] not in link_ids:
                    link_ids.append(r[0])
                    relations[r[1]] += 1

        removed = {
            "snapshot_points": _delete(conn, "snapshot_points", "observation_id", ids),
            "llm_calls": _delete(conn, "llm_calls", "id", call_ids),
            "syntheses": _delete(conn, "syntheses", "id", synth_ids),
            "observation_links": _delete(conn, "observation_links", "id", link_ids),
            "observations": _delete(conn, "observations", "id", ids),
        }
        period = {"period_start": iso(start), "period_end": iso(start + timedelta(days=7))}
        details = {
            "observations": {**period, "by_source": dict(Counter(
                r["label"] for r in members).most_common())},
            "snapshot_points": period,
            "llm_calls": {**period, "cost_by_day": cost_by_day,
                          "cost_usd": round(sum(cost_by_day.values()), 8)},
            "syntheses": period,
            "observation_links": {**period, "relations": dict(relations.most_common())},
        }
        for table in ("observations", "snapshot_points", "llm_calls", "syntheses",
                      "observation_links"):
            if removed[table]:
                conn.execute(
                    "INSERT INTO purges (run_uuid, table_name, row_count, reason, rollup_ids, "
                    "detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (report.run_uuid, table, removed[table], reason, json.dumps(rollup_ids),
                     json.dumps(details[table]), created))
    report.rollups += len(rollup_ids)
    report.rollup_ids += rollup_ids
    for table, n in removed.items():
        report.removed[table] = report.removed.get(table, 0) + n


def _calls_kept(conn: sqlite3.Connection, calls: set[int], removing: set[int]) -> set[int]:
    kept = set()
    for chunk in _chunks(sorted(calls)):
        for r in conn.execute(
                f"SELECT id, llm_call_id FROM observations WHERE llm_call_id IN "
                f"({','.join('?' * len(chunk))})", chunk):
            if r[0] not in removing:
                kept.add(r[1])
    return kept


def _delete(conn: sqlite3.Connection, table: str, column: str, ids: list[int]) -> int:
    n = 0
    for chunk in _chunks(list(ids)):
        n += conn.execute(f"DELETE FROM {table} WHERE {column} IN "
                          f"({','.join('?' * len(chunk))})", chunk).rowcount
    return n


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _snapshot_idea_evidence(conn: sqlite3.Connection, members: list[Any], removing: set[int],
                            created: str) -> None:
    """Keep what a card cites readable once its observations are gone.

    Cards written since #71 carry this snapshot in their own JSON; earlier cards
    get an ``evidence_snapshots`` row per removed observation they cite."""
    by_id = {r["id"]: r for r in members}
    for idea in conn.execute("SELECT id, card FROM ideas").fetchall():
        for e in Card.load(idea[1]).evidence:
            oid = e.observation_id
            if oid not in removing or e.summary is not None:
                continue
            if conn.execute("SELECT 1 FROM evidence_snapshots WHERE idea_id = ? AND "
                            "observation_id = ?", (idea[0], oid)).fetchone():
                continue
            r = by_id[oid]
            conn.execute(
                "INSERT INTO evidence_snapshots (idea_id, observation_id, source_label, "
                "observed_at, summary, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (idea[0], oid, r["label"], r["item_published_at"] or r["created_at"],
                 r["summary"], safe_url(r["source_url"]), created))


def _purge_unkept_calls(store: Store, days: dict[int | None, float], now: datetime,
                        report: CompactReport, clock: Callable[[], datetime]) -> None:
    """Remove the model calls for items that were judged but not kept, and every
    item's screen call, once the item is past its source's retention age.

    They hold the source's raw text in their request and response, and no
    observation (so no rollup) stands for them. ``items_seen`` rows stay, with
    their outcome, so the item is never judged again. A call a remaining
    observation uses is never removed."""
    candidates: dict[int, tuple[str, str]] = {}
    for source_id, age in days.items():
        if source_id is None or age <= 0:
            continue
        cutoff = iso(now - timedelta(days=age))
        for column in ("llm_call_id", "screen_call_id"):
            # a screen call shared by short posts screened together waits for
            # the last item that names it
            for r in store.query(
                    f"SELECT i.{column} AS call, i.outcome FROM items_seen i "
                    f"JOIN llm_calls l ON l.id = i.{column} "
                    "WHERE i.source_id = ? AND i.created_at < ? "
                    "AND NOT EXISTS (SELECT 1 FROM observations o "
                    f"                WHERE o.llm_call_id = i.{column}) "
                    "AND NOT EXISTS (SELECT 1 FROM items_seen j "
                    f"                WHERE j.{column} = i.{column} AND j.created_at >= ?)",
                    (source_id, cutoff, cutoff)):
                outcome = r["outcome"] if column == "llm_call_id" else "screen"
                candidates.setdefault(r["call"], (outcome, f"{age:g}"))
    if not candidates:
        return
    ids = sorted(candidates)
    created = iso(clock())
    ages = sorted(set(a for _, a in candidates.values()), key=float)
    with store.purge() as conn:
        cost_by_day: dict[str, float] = {}
        for chunk in _chunks(ids):
            for r in conn.execute(
                    f"SELECT created_at, cost_usd FROM llm_calls WHERE id IN "
                    f"({','.join('?' * len(chunk))})", chunk):
                if r[1]:
                    cost_by_day[r[0][:10]] = round(cost_by_day.get(r[0][:10], 0.0) + r[1], 8)
        n = _delete(conn, "llm_calls", "id", ids)
        detail = {"items": "judged, not kept; screen calls (outcome \"screen\")",
                  "outcomes": dict(Counter(o for o, _ in candidates.values()).most_common()),
                  "cost_by_day": cost_by_day,
                  "cost_usd": round(sum(cost_by_day.values()), 8)}
        conn.execute(
            "INSERT INTO purges (run_uuid, table_name, row_count, reason, rollup_ids, detail, "
            "created_at) VALUES (?, 'llm_calls', ?, ?, '[]', ?, ?)",
            (report.run_uuid, n, "retention: model calls for items judged but not kept, "
             f"older than their sources' retention ages ({', '.join(ages)} days)",
             json.dumps(detail), created))
    report.unkept_calls += n
    report.removed["llm_calls"] = report.removed.get("llm_calls", 0) + n


# Everything that can reference a model call. A call any remaining row names stays.
CALL_REFERENCES = (
    ("observations", "llm_call_id"), ("items_seen", "llm_call_id"),
    ("items_seen", "screen_call_id"), ("ideas", "gen_call_id"), ("ideas", "verify_call_id"),
    ("syntheses", "llm_call_id"),
    ("rollups", "summary_call_id"), ("clusters", "name_call_id"),
    ("sources", "origin_call_id"),
)


def _purge_unreferenced_calls(store: Store, age: float, now: datetime, report: CompactReport,
                              clock: Callable[[], datetime]) -> None:
    """Remove model calls older than ``retention.default_days`` that nothing remaining
    references: failed calls, and scout, name, explain, card and verify calls whose
    subject is gone. Their requests hold third-party text as well.

    Calls on ``items_seen`` rows are left to ``_purge_unkept_calls``, which uses
    the item's own source's age."""
    if age <= 0:
        return
    referenced = " AND ".join(
        f"NOT EXISTS (SELECT 1 FROM {table} r WHERE r.{column} = l.id)"
        for table, column in CALL_REFERENCES)
    rows = store.query(
        f"SELECT l.id, l.purpose, l.status FROM llm_calls l "
        f"WHERE l.created_at < ? AND {referenced}", (iso(now - timedelta(days=age)),))
    if not rows:
        return
    ids = [r["id"] for r in rows]
    with store.purge() as conn:
        cost_by_day: dict[str, float] = {}
        for chunk in _chunks(ids):
            for r in conn.execute(
                    f"SELECT created_at, cost_usd FROM llm_calls WHERE id IN "
                    f"({','.join('?' * len(chunk))})", chunk):
                if r[1]:
                    cost_by_day[r[0][:10]] = round(cost_by_day.get(r[0][:10], 0.0) + r[1], 8)
        n = _delete(conn, "llm_calls", "id", ids)
        detail = {"items": "referenced by nothing that remains",
                  "purposes": dict(Counter(r["purpose"] for r in rows).most_common()),
                  "failed": sum(1 for r in rows if r["status"] == "error"),
                  "cost_by_day": cost_by_day,
                  "cost_usd": round(sum(cost_by_day.values()), 8)}
        conn.execute(
            "INSERT INTO purges (run_uuid, table_name, row_count, reason, rollup_ids, detail, "
            "created_at) VALUES (?, 'llm_calls', ?, ?, '[]', ?, ?)",
            (report.run_uuid, n, f"retention: model calls older than {age:g} days that "
             "nothing remaining references", json.dumps(detail), iso(clock())))
    report.unreferenced_calls += n
    report.removed["llm_calls"] = report.removed.get("llm_calls", 0) + n
