"""Read models for the map and clusters pages."""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from ..store import Store, blob_to_vec
from ..stored.map import ClusterOriginMix, SnapshotDensity, SnapshotQuality
from . import bursts

POINT_TEXT_CHARS = 200


def latest(store: Store) -> Any:
    return store.query_one("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1")


def clusters(store: Store, snapshot_id: int) -> list[dict[str, Any]]:
    """The snapshot's clusters, read. One that cannot be read is left out (every theme, the map
    and Today compute from these fields, so a stand-in row would break them) and kept once by
    its error's id (``rowsafe``, A3): the rest of every page still answers."""
    from .. import rowsafe
    out = []
    for r in store.query("SELECT * FROM clusters WHERE snapshot_id = ? ORDER BY size DESC",
                         (snapshot_id,)):
        try:
            out.append(_cluster(r))
        except Exception as exc:  # noqa: BLE001 - one cluster never fails the map's pages
            rowsafe.note(exc, "map:cluster")
    return out


def _cluster(r: Any) -> dict[str, Any]:
    d = dict(r)
    d.pop("centroid")
    for key in ("centroid_2d", "keywords", "source_mix", "topic_mix", "representatives",
                "trajectory"):
        d[key] = json.loads(d[key])
    # Maps from before #35 have no story count or origin mix.
    d["origin_mix"] = ClusterOriginMix.load(d.get("origin_mix")).extra
    d["label"] = d["name"] or ", ".join(d["keywords"][:3]) or f"cluster {d['cluster']}"
    d["cross_source"] = bool(d["cross_source"])
    d["movement"] = movement(d["trajectory"])
    d["rising"] = bursts.rising(d["trajectory"], d["cross_source"])
    return d


def movement(trajectory: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Change since the previous snapshot, and how much of it the source mix explains.

    ``excess`` is the part of the change in cumulative share not explained by
    which sources were running: a cluster that grows only because its dominant
    source posted more has excess near zero. Parallax's phase 4 found that raw
    counts and even raw shares mislead without this baseline. It is kept for
    continuity, but it dilutes new motion by the size of the library and moves
    when old points are re-clustered.

    The arrival fields do neither: ``new_in_cluster`` of ``new_total``
    observations added since the previous snapshot landed here, against
    ``expected_new`` from the previous per-source rates. ``burst`` is the
    Kleinberg state, ``q_value`` the corrected significance of this snapshot's
    count, and ``rising`` whether the lineage entered a burst this snapshot,
    significantly and cross-source (see ``map/bursts.py``).
    """
    if len(trajectory) < 2:
        return None
    prev, last = trajectory[-2], trajectory[-1]
    delta = last["share"] - prev["share"]
    expected = last.get("expected_share")
    excess = last["share"] - expected if expected is not None else None
    return {
        "since": prev["at"], "delta": round(delta, 5),
        "excess": round(excess, 5) if excess is not None else None,
        "points": len(trajectory),
        "new_total": last.get("new_total"), "new_in_cluster": last.get("new_in_cluster"),
        "expected_new": last.get("expected_new"), "burst": last.get("burst"),
        "entered_burst": bursts.entered_burst(trajectory),
        "p_value": last.get("p_value"), "q_value": last.get("q_value"),
    }


def map_payload(store: Store, snapshot: Any) -> dict[str, Any]:
    points = store.query(
        """
        SELECT p.observation_id AS id, p.x, p.y, p.cluster, o.signal, o.summary,
               COALESCE(s.label, 'unknown') AS source
        FROM snapshot_points p
        JOIN observations o ON o.id = p.observation_id
        LEFT JOIN sources s ON s.id = o.source_id
        WHERE p.snapshot_id = ? ORDER BY p.observation_id
        """,
        (snapshot["id"],),
    )
    from .. import rowsafe
    source_index: dict[str, int] = {}
    cols: dict[str, list[Any]] = {"id": [], "x": [], "y": [], "c": [], "s": [], "t": [], "src": []}
    for p in points:
        try:              # a point is built whole before it is added: the columns stay aligned
            text = " ".join(p["summary"].split())
            one = (p["id"], p["x"], p["y"], p["cluster"], round(p["signal"], 3),
                   text if len(text) <= POINT_TEXT_CHARS else text[: POINT_TEXT_CHARS - 3] + "...")
        except Exception as exc:  # noqa: BLE001 - a point that cannot be drawn is left out
            rowsafe.note(exc, "map:point")
            continue
        for k, v in zip(("id", "x", "y", "c", "s", "t"), one, strict=True):
            cols[k].append(v)
        cols["src"].append(source_index.setdefault(p["source"], len(source_index)))
    quality = dict(SnapshotQuality.load(snapshot["quality"]).extra)
    quality.pop("source_totals", None)
    return {
        "snapshot": {"id": snapshot["id"], "created_at": snapshot["created_at"],
                     "n": snapshot["n"], "k": snapshot["k"], "quality": quality},
        "density": SnapshotDensity.load(snapshot["density"]).items,
        "clusters": [
            {k: c[k] for k in ("cluster", "label", "name", "keywords", "size", "share",
                               "centroid_2d", "cross_source", "max_source_share")}
            for c in clusters(store, snapshot["id"])
        ],
        "sources": list(source_index),
        "points": cols,
    }


def member_ids(store: Store, snapshot_id: int, cluster: int) -> tuple[int, ...]:
    return tuple(
        r["observation_id"] for r in store.query(
            "SELECT observation_id FROM snapshot_points WHERE snapshot_id = ? AND cluster = ?",
            (snapshot_id, cluster),
        )
    )


def centroid(store: Store, snapshot_id: int, cluster: int) -> np.ndarray | None:
    row = store.query_one("SELECT centroid FROM clusters WHERE snapshot_id = ? AND cluster = ?",
                          (snapshot_id, cluster))
    return blob_to_vec(row["centroid"]) if row else None
