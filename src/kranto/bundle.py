"""``kranto watch export bundle``: a static, read-only copy of the latest map.

For publishing a map somewhere without running the server (the way
example.com/parallax read Parallax's snapshot bundle). The format is versioned
and marked unstable: freezing it as a public contract is a decision for
later, not a side effect of shipping an exporter.

Files: manifest.json, observations.json, clusters.json, embeddings.bin
(float32, row-major, one row per entry in observations.json, unit norm). An
observation from X has no title in a bundle (its title is the post's own text).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import __version__
from .map import read as map_read
from .store import Store, blob_to_vec
from .stored.map import SnapshotQuality

FORMAT = "kranto-bundle"
VERSION = 0


def export_bundle(store: Store, out_dir: Path) -> dict:
    snap = map_read.latest(store)
    if snap is None:
        raise ValueError("no map yet; run 'kranto watch snapshot' first")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = store.query(
        """
        SELECT o.id, o.title, o.summary, o.source_url, o.item_published_at, o.created_at,
               o.signal, o.embedding, COALESCE(s.label, 'unknown') AS source,
               s.kind AS source_kind, p.cluster, p.x, p.y
        FROM snapshot_points p JOIN observations o ON o.id = p.observation_id
        LEFT JOIN sources s ON s.id = o.source_id
        WHERE p.snapshot_id = ? ORDER BY o.id
        """,
        (snap["id"],),
    )
    # An X post's title is its own text: X's terms govern displaying it, so a bundle (made to
    # be published) carries Kranto's summary and the post's URL only.
    observations = [
        {"id": r["id"], "title": None if r["source_kind"] == "x" else r["title"],
         "summary": r["summary"],
         "source": r["source"], "source_url": r["source_url"],
         "published_at": r["item_published_at"], "observed_at": r["created_at"],
         "signal": round(r["signal"], 4), "cluster": r["cluster"],
         "xy": [r["x"], r["y"]]}
        for r in rows
    ]
    matrix = np.stack([blob_to_vec(r["embedding"]) for r in rows]).astype("<f4")
    (out_dir / "embeddings.bin").write_bytes(matrix.tobytes(order="C"))
    (out_dir / "observations.json").write_text(json.dumps(observations, ensure_ascii=False))
    clusters = [
        {k: c[k] for k in ("cluster", "lineage_id", "label", "name", "keywords", "size",
                           "share", "centroid_2d", "cross_source", "max_source_share",
                           "source_mix", "representatives", "trajectory")}
        for c in map_read.clusters(store, snap["id"])
    ]
    (out_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False))
    quality = dict(SnapshotQuality.load(snap["quality"]).extra)
    quality.pop("source_totals", None)
    manifest = {
        "format": FORMAT, "version": VERSION, "stability": "unstable",
        "generator": f"the server {__version__}", "snapshot_id": snap["id"],
        "created_at": snap["created_at"], "fingerprint": snap["fingerprint"],
        "embedding_model": snap["embedding_model"], "dim": int(matrix.shape[1]),
        "n": len(observations), "k": snap["k"], "quality": quality,
        "files": ["observations.json", "clusters.json", "embeddings.bin"],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
