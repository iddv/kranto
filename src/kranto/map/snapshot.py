"""Take a map snapshot: cluster the whole library and record it.

Every snapshot re-clusters the full library from scratch. Cluster numbers
mean nothing outside their snapshot; lineage ids carry identity across
snapshots, and anything durable (links, ideas) anchors on observation ids.

A snapshot is refused when the library has not changed since the last one
(same corpus fingerprint): re-clustering identical data produces nothing new,
and downstream consumers must not mistake a repeated picture for movement.

Every observation is clustered, but counting is by story: copies of one
text (``stories``) count once in a cluster's share, source mix, topic mix and
size for the cross-source rule, and only a story's first observation is a new
arrival. A cluster is cross-source only if no origin (registrable domain)
supplies more than 70% of its stories either, and a lineage is rising only if
no origin supplies more than 70% of its new stories.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from .. import activity, notify, prompts, stories
from ..config import StoriesConfig
from ..embed import Embedder
from ..intern import extract_json_object
from ..library import CHILD_ADMISSIONS, IMPORTED
from ..llm import LLMClient, LLMError
from ..store import Store, blob_to_vec, iso, utcnow, vec_to_blob
from ..stored import runs as stored_runs
from ..stored.map import (
    Centroid2d,
    ClusterKeywords,
    ClusterOriginMix,
    ClusterRepresentatives,
    ClusterSourceMix,
    ClusterTopicMix,
    ClusterTrajectory,
    SnapshotQuality,
)
from ..tick import RunLocked, run_lock
from . import bursts, compute

NOT_ARRIVALS = (*CHILD_ADMISSIONS, IMPORTED)
NAME_REUSE_DISTANCE = 0.05
NAME_SAMPLE = 12
SUMMARY_CHARS = 300


@dataclass
class SnapshotReport:
    run_uuid: str
    status: str = "ok"
    error: str | None = None
    snapshot_id: int | None = None
    n: int = 0
    k: int = 0
    new_lineages: int = 0
    continued_lineages: int = 0
    names_reused: int = 0
    names_generated: int = 0
    names_failed: int = 0
    names_skipped: str | None = None
    burst_candidates: int = 0
    quality: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        return json.dumps({k: v for k, v in self.__dict__.items()
                           if k not in ("run_uuid", "status", "error")})


def latest_snapshot(store: Store) -> Any:
    return store.query_one("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1")


def _load(store: Store, model: str) -> tuple[Any, Any, Any]:
    rows = store.query(
        """
        SELECT o.id, o.embedding, o.summary, o.source_id, o.item_id, o.source_url,
               COALESCE(s.label, 'unknown') AS label, o.admitted_by,
               (SELECT i.canonical_url FROM items_seen i WHERE i.source_id = o.source_id
                AND i.item_id = o.item_id) AS canonical_url
        FROM observations o LEFT JOIN sources s ON s.id = o.source_id
        WHERE o.embedding_model = ?
          AND NOT EXISTS (SELECT 1 FROM observations n WHERE n.supersedes = o.id)
        ORDER BY o.id
        """,
        (model,),
    )
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    x = np.stack([blob_to_vec(r["embedding"]) for r in rows]) if rows else np.zeros((0, 0))
    return rows, ids, x


def _name(llm: LLMClient, keywords: list[str], summaries: list[str],
          run_uuid: str) -> tuple[str | None, int | None]:
    prompt = prompts.load("name")
    text = prompt.render(
        keywords=", ".join(keywords) or "(none)",
        observations="\n".join(f"- {s[:SUMMARY_CHARS]}" for s in summaries),
    )
    completion = llm.complete(
        tier="judge", purpose="name", prompt_version=prompt.version, run_uuid=run_uuid,
        messages=[{"role": "user", "content": text}], max_tokens=llm.max_tokens("name"),
        temperature=0.2, retry_truncated=True, schema=prompts.schema("name"),
    )
    obj = extract_json_object(completion.text) or {}
    name = obj.get("name")
    if isinstance(name, str) and 0 < len(name.strip()) <= 80:
        return name.strip(), completion.call_id
    return None, completion.call_id


def take_snapshot(
    store: Store,
    embedder: Embedder,
    llm: LLMClient | None,
    *,
    force: bool = False,
    stories_cfg: StoriesConfig | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> SnapshotReport:
    report = SnapshotReport(run_uuid=activity.run_uuid("snapshot"))
    started = clock()
    lock = store.lock_path("snapshot")
    try:
        # Two overlapping snapshots (cron and serve) made two maps of the same
        # data and paid for naming twice.
        with run_lock(lock) if lock else contextlib.nullcontext():
            _snapshot(store, embedder, llm, report, force, clock,
                      stories_cfg or StoriesConfig())
    except RunLocked as exc:
        report.status, report.error = "skipped", str(exc)
    except ValueError as exc:
        report.status, report.error = "skipped", str(exc)
    except Exception as exc:  # recorded and alarmed rather than lost in a log
        report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "snapshot", "status": report.status,
        "started_at": iso(started), "finished_at": iso(clock()),
        "summary": stored_runs.text_for("snapshot", report.summary()), "error": report.error,
    })
    notify.alarm_for_run(store, kind="snapshot", run_uuid=report.run_uuid,
                         status=report.status, error=report.error)
    return report


def _names_owed(store: Store, prev: Any, llm: LLMClient | None) -> bool:
    """Whether the last map skipped naming its themes (watching was paused, or over budget)
    and they can be named now: then an unchanged library is mapped again, so a resume does
    not leave the themes unnamed until the library next changes."""
    if llm is None:
        return False
    last = store.query_one("SELECT summary FROM runs WHERE kind = 'snapshot' AND status = 'ok' "
                           "ORDER BY started_at DESC, rowid DESC LIMIT 1")
    summary = stored_runs.SnapshotSummary.load(last["summary"] if last else None)
    if not summary.names_skipped or summary.snapshot_id != prev["id"]:
        return False
    try:
        llm.check_can_spend()
    except LLMError:
        return False
    return True


def _snapshot(store: Store, embedder: Embedder, llm: LLMClient | None,
              report: SnapshotReport, force: bool, clock: Callable[[], datetime],
              stories_cfg: StoriesConfig) -> None:
    rows, ids, x = _load(store, embedder.model_name)
    report.n = len(ids)
    fp = compute.fingerprint(ids.tolist(), embedder.model_name)
    prev = latest_snapshot(store)
    if prev is not None and prev["fingerprint"] == fp and not force \
            and not _names_owed(store, prev, llm):
        raise ValueError("library unchanged since the last snapshot")

    if llm is not None:
        try:
            llm.check_can_spend()
        except LLMError as exc:
            report.names_skipped = str(exc)
            llm = None

    result = compute.cluster(x)
    k = result.k
    report.k = k
    centers = compute.centroids(x, result.labels, k)

    # Lineage against the previous snapshot, matched on original-space centroids.
    prev_clusters = (
        store.query("SELECT * FROM clusters WHERE snapshot_id = ? ORDER BY cluster", (prev["id"],))
        if prev is not None else []
    )
    prev_centers = (np.stack([blob_to_vec(c["centroid"]) for c in prev_clusters])
                    if prev_clusters else np.zeros((0, x.shape[1]), dtype=np.float32))
    matches = compute.match_lineages(centers, prev_centers)

    # Stories: copies of one text count once. Rows are in id order, so the
    # first row seen of a story is its earliest observation.
    # A deep dive's child belongs to its parent's story: it never adds one.
    story_of = stories.story_keys(store, rows)
    origin_of = {r["id"]: stories.origin(r["canonical_url"] or r["source_url"]) for r in rows}
    first_of_story: dict[str, int] = {}
    for r in rows:
        first_of_story.setdefault(story_of[r["id"]], r["id"])
    firsts = [r for r in rows if first_of_story[story_of[r["id"]]] == r["id"]]
    is_first = {r["id"] for r in firsts}
    n_stories = len(firsts)

    by_cluster: list[list[Any]] = [[] for _ in range(k)]
    for row, label in zip(rows, result.labels, strict=True):
        by_cluster[int(label)].append(row)
    kw = compute.keywords([[r["summary"] for r in members] for members in by_cluster])
    reps = compute.representatives(x, result.labels, centers, ids)

    topic_of_source: dict[int, list[str]] = {}
    for r in store.query("SELECT ts.source_id, t.name FROM topic_links ts "
                         "JOIN topics_now t ON t.id = ts.topic_id"):
        topic_of_source.setdefault(r["source_id"], []).append(r["name"])

    source_totals: dict[str, int] = {}
    for r in firsts:
        source_totals[r["label"]] = source_totals.get(r["label"], 0) + 1
    prev_totals = (SnapshotQuality.load(prev["quality"]).extra.get("source_totals") or {}
                   if prev else {})

    # Arrivals: observations newer than anything the previous snapshot saw. Movement is
    # measured on these alone, so old points moving between clusters when the library is
    # re-clustered cannot read as a theme gaining or losing ground.
    prev_max_id = 0
    if prev is not None:
        top = store.query_one(
            "SELECT COALESCE(MAX(observation_id), 0) AS m FROM snapshot_points "
            "WHERE snapshot_id = ?", (prev["id"],))
        assert top is not None                 # an aggregate always answers one row
        prev_max_id = top["m"]
    # Children (a deep dive's, #67, or gathered at ingest, #84) are not independent
    # arrivals: they follow their parent into its neighbourhood, and counting them
    # would read one item's thread as a theme gaining ground. They are on the map,
    # but not in movement. Nor is a copy of an earlier story: only a story's
    # first observation arrives. Nor is an imported archive (``python -m kranto import parallax``):
    # thousands of rows observed months ago would read as one enormous burst.
    def arrived(r: Any) -> bool:
        return (r["id"] > prev_max_id and r["admitted_by"] not in NOT_ARRIVALS
                and r["id"] in is_first)

    arrivals_by_source: dict[str, int] = {}
    old_by_source: dict[str, int] = {}
    for r in firsts:  # a copy of an earlier story is not a new arrival
        if r["admitted_by"] == IMPORTED:   # nor part of the rates arrivals are tested against
            continue
        if r["id"] > prev_max_id:
            if arrived(r):
                arrivals_by_source[r["label"]] = arrivals_by_source.get(r["label"], 0) + 1
        else:
            old_by_source[r["label"]] = old_by_source.get(r["label"], 0) + 1
    new_total = sum(arrivals_by_source.values())
    n_old = sum(old_by_source.values())
    # Movement is tested only once the previous map was large enough to give
    # each source a stable rate: after an 80-observation first map, 10% of the
    # next map's tests reached q < 0.05 on shuffled data.
    testable = prev is not None and prev["n"] >= MOVEMENT_MIN_PREVIOUS_N

    cluster_rows: list[dict[str, Any]] = []
    arrivals: list[tuple[list[int], list[str]]] = []
    for c in range(k):
        members = by_cluster[c]
        # One row per story in this cluster: its earliest member here.
        seen_stories: set[str] = set()
        distinct = []
        for m in members:
            if story_of[m["id"]] not in seen_stories:
                seen_stories.add(story_of[m["id"]])
                distinct.append(m)
        origins = [origin_of[m["id"]] for m in distinct]
        mix, max_share, cross = compute.source_mix([m["label"] for m in distinct], origins)
        o_mix, max_origin = stories.origin_mix(origins)
        topics: dict[str, int] = {}
        for m in distinct:
            for topic_name in topic_of_source.get(m["source_id"], []):
                topics[topic_name] = topics.get(topic_name, 0) + 1
        share = len(distinct) / n_stories
        centroid_2d = result.coords[result.labels == c].mean(axis=0)

        if c in matches:
            p = prev_clusters[matches[c]]
            lineage = p["lineage_id"]
            history = ClusterTrajectory.load(p["trajectory"]).items
            report.continued_lineages += 1
            prev_mix = ClusterSourceMix.load(p["source_mix"]).extra
            expected = _expected_share(prev_mix, prev_totals, source_totals, n_stories)
            old_in_cluster: dict[str, int] = {}
            for m in members:
                if m["id"] <= prev_max_id and m["id"] in is_first \
                        and m["admitted_by"] != IMPORTED:
                    old_in_cluster[m["label"]] = old_in_cluster.get(m["label"], 0) + 1
            expected_new = (_expected_new(old_in_cluster, sum(old_in_cluster.values()) / n_old,
                                          old_by_source, arrivals_by_source)
                            if testable and n_old else None)
        else:
            p, lineage, history = None, uuid.uuid4().hex[:12], []
            expected, expected_new = None, None
            report.new_lineages += 1
        new_members = [m for m in members if arrived(m)]
        new_in_cluster = len(new_members)
        _, new_max_origin = stories.origin_mix(origin_of[m["id"]] for m in new_members)
        trajectory = history + [{
            "at": iso(clock()), "share": round(share, 5), "size": len(members),
            "stories": len(distinct),
            "new_max_origin_share": new_max_origin if new_members else None,
            "expected_share": round(expected, 5) if expected is not None else None,
            "new_total": new_total, "new_in_cluster": new_in_cluster,
            "expected_new": round(expected_new, 4) if expected_new is not None else None,
        }]

        name: str | None = None
        name_call: int | None = None
        if p is not None and p["name"] and \
                float(1.0 - centers[c] @ blob_to_vec(p["centroid"])) <= NAME_REUSE_DISTANCE:
            name, name_call = p["name"], p["name_call_id"]
            report.names_reused += 1
        elif llm is not None:
            by_id = {m["id"]: m for m in members}
            sample = [by_id[i]["summary"] for i in reps[c] if i in by_id]
            sample += [m["summary"] for m in members[:: max(1, len(members) // NAME_SAMPLE)]
                       if m["id"] not in reps[c]]
            try:
                name, name_call = _name(llm, kw[c], sample[:NAME_SAMPLE], report.run_uuid)
                report.names_generated += 1 if name else 0
                report.names_failed += 0 if name else 1
            except LLMError:
                report.names_failed += 1

        new_ids = [m["id"] for m in new_members]
        new_sources = sorted({m["label"] for m in new_members})
        cluster_rows.append({
            "cluster": c, "lineage_id": lineage, "size": len(members), "share": share,
            "centroid": vec_to_blob(centers[c]),
            "centroid_2d": Centroid2d.write([round(float(v), 5) for v in centroid_2d]),
            "keywords": ClusterKeywords.write(kw[c]), "name": name, "name_call_id": name_call,
            "source_mix": ClusterSourceMix.write(mix), "max_source_share": max_share,
            "cross_source": int(cross), "topic_mix": ClusterTopicMix.write(topics),
            "stories": len(distinct), "origin_mix": ClusterOriginMix.write(o_mix),
            "max_origin_share": max_origin,
            "representatives": ClusterRepresentatives.write(reps[c]), "trajectory": trajectory,
        })
        arrivals.append((new_ids, new_sources))

    _score_movement(cluster_rows)
    for row in cluster_rows:
        row["trajectory"] = json.dumps(row["trajectory"])

    quality = {**result.quality, "source_totals": source_totals, "stories": {
        "observations": len(rows), "distinct": n_stories,
        "near_duplicate_check": stories.null_check(store, stories_cfg, clock())}}
    report.quality = {k: v for k, v in result.quality.items() if k != "silhouette_by_k"}
    with store.tx() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (fingerprint, embedding_model, n, k, params, quality, density,"
            " run_uuid, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fp, embedder.model_name, len(rows), k, json.dumps(result.params),
             json.dumps(quality), json.dumps(compute.density_grid(result.coords)),
             report.run_uuid, iso(clock())),
        )
        assert cur.lastrowid is not None       # an INSERT always has one
        snapshot_id = int(cur.lastrowid)
        conn.executemany(
            "INSERT INTO snapshot_points (snapshot_id, observation_id, cluster, x, y) "
            "VALUES (?, ?, ?, ?, ?)",
            [(snapshot_id, int(i), int(label), round(float(xy[0]), 5), round(float(xy[1]), 5))
             for i, label, xy in zip(ids, result.labels, result.coords, strict=True)],
        )
        for row in cluster_rows:
            conn.execute(
                f"INSERT INTO clusters (snapshot_id, {', '.join(row)}) "
                f"VALUES (?, {', '.join('?' * len(row))})",
                (snapshot_id, *row.values()),
            )
        # In the same transaction: a snapshot committed without its burst
        # candidates could never get them, since a rerun is refused as unchanged.
        for row, (new_ids, new_sources) in zip(cluster_rows, arrivals, strict=True):
            if bursts.rising(ClusterTrajectory.load(row["trajectory"]).items,
                             bool(row["cross_source"])):
                _record_burst(store, report, snapshot_id, row, new_ids, new_sources, clock)
    report.snapshot_id = snapshot_id


MOVEMENT_MIN_PREVIOUS_N = 200


def _expected_share(prev_mix: dict[str, int], prev_totals: dict[str, int],
                    totals: dict[str, int], n: int) -> float | None:
    """The share this cluster would have now if each source kept contributing to it at its
    previous rate. Growth beyond this is not explained by which sources were running."""
    if not prev_totals or n == 0:
        return None
    expected = 0.0
    for source, count in prev_mix.items():
        if prev_totals.get(source):
            expected += count / prev_totals[source] * totals.get(source, 0)
    return expected / n


def _expected_new(old_in_cluster: dict[str, int], old_share: float,
                  old_by_source: dict[str, int], arrivals_by_source: dict[str, int]) -> float:
    """How many of this snapshot's arrivals the cluster would receive if each source sent
    it the fraction of its earlier observations that the cluster holds now.

    Both counts use the current map's boundaries. The previous map's cluster was
    used before, but re-clustering moves old points between clusters: a cluster that
    absorbed old points when k changed received more arrivals than its old boundaries
    predicted, with nothing moving. On shuffled data that raised 19 false rising flags
    in 30 runs; on current boundaries, none.

    Each source's rate carries one pseudo-observation at the cluster's share of old
    points: a source never seen before gets that share instead of zero (which would make
    any arrival from it infinitely surprising), and a source seen a handful of times is
    pulled toward it.
    """
    expected = 0.0
    for source, arrived in arrivals_by_source.items():
        rate = (old_in_cluster.get(source, 0) + old_share) / (old_by_source.get(source, 0) + 1)
        expected += rate * arrived
    return expected


def _score_movement(cluster_rows: list[dict[str, Any]]) -> None:
    """Burst state, p-value and BH q-value on each cluster's newest trajectory point."""
    p_values = []
    for row in cluster_rows:
        trajectory = row["trajectory"]
        series = [(pt["new_in_cluster"], pt["new_total"]) for pt in trajectory
                  if pt.get("new_total") is not None]
        last = trajectory[-1]
        last["burst"] = bursts.burst_states(series)[-1]
        p = (bursts.binomial_p_value(last["new_in_cluster"], last["new_total"],
                                     last["expected_new"])
             if last["expected_new"] is not None else None)
        last["p_value"] = _sig(p)
        p_values.append(p)
    for row, q in zip(cluster_rows, bursts.benjamini_hochberg(p_values), strict=True):
        row["trajectory"][-1]["q_value"] = _sig(q)


def _sig(x: float | None) -> float | None:
    return None if x is None else float(f"{x:.4g}")


def _record_burst(store: Store, report: SnapshotReport, snapshot_id: int, row: dict[str, Any],
                  new_ids: list[int], new_sources: list[str],
                  clock: Callable[[], datetime]) -> None:
    last = ClusterTrajectory.load(row["trajectory"]).items[-1]
    keywords = ClusterKeywords.load(row["keywords"]).items
    label = row["name"] or ", ".join(keywords[:3]) or f"cluster {row['cluster']}"
    r, d, e, q = (last["new_in_cluster"], last["new_total"], last["expected_new"],
                  last["q_value"])
    notify.record_candidate(
        store, origin="burst", subject_key=f"lineage:{row['lineage_id']}", score=1.0 - q,
        title=f"Burst: {label}",
        body=(f"{r} of the {d} observations added since the last map landed in \"{label}\"; "
              f"the sources that were running explain about {e:.1f}. The lineage entered "
              f"the burst state this snapshot (q = {q:.3g}, one-sided binomial test "
              "corrected across all lineages in the map), and no single source dominates it. "
              f"Arriving from: {', '.join(new_sources)}."),
        evidence_ids=new_ids[:10],
        detail={"snapshot_id": snapshot_id, "cluster": row["cluster"],
                "lineage_id": row["lineage_id"], "new_in_cluster": r, "new_total": d,
                "expected_new": e, "p_value": last["p_value"], "q_value": q,
                "arriving_sources": new_sources},
        run_uuid=report.run_uuid, now=clock(),
    )
    report.burst_candidates += 1
