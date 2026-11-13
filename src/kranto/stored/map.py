"""The map's stored JSON: a snapshot's ``params``, ``quality`` and
``density``; a cluster's centroid, keywords, mixes, representatives, trajectory and
``origin_mix``; a rollup's mixes, keywords and URLs; a purge's rollup ids and detail.

One writer each (``map.snapshot``, ``retention``, ``Store.purge``). A cluster written before
#35 has trajectory points with only ``at``, ``share`` and ``size`` (live had four): a point is
kept whole, and its readers ask for the newer keys with ``.get``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Stored


@dataclass(frozen=True)
class SnapshotParams(Stored):
    COLUMN = ("snapshots", "params")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotQuality(Stored):
    COLUMN = ("snapshots", "quality")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotDensity(Stored):
    """The density grid the map draws (``compute.density_grid``: rows of floats, max 1)."""

    COLUMN = ("snapshots", "density")
    LIST_ROOT = "items"
    items: list[list[float]] = field(default_factory=list)


@dataclass(frozen=True)
class Centroid2d(Stored):
    COLUMN = ("clusters", "centroid_2d")
    LIST_ROOT = "items"
    items: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterKeywords(Stored):
    COLUMN = ("clusters", "keywords")
    LIST_ROOT = "items"
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterSourceMix(Stored):
    COLUMN = ("clusters", "source_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterTopicMix(Stored):
    COLUMN = ("clusters", "topic_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterRepresentatives(Stored):
    COLUMN = ("clusters", "representatives")
    LIST_ROOT = "items"
    items: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterTrajectory(Stored):
    """Its points, oldest first: ``{at, share, size, ...}``, the newer keys when written."""

    COLUMN = ("clusters", "trajectory")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterOriginMix(Stored):
    """Where its stories came from (migration 14; NULL on an older cluster)."""

    COLUMN = ("clusters", "origin_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollupSourceMix(Stored):
    COLUMN = ("rollups", "source_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollupPlatformMix(Stored):
    COLUMN = ("rollups", "platform_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollupTopicMix(Stored):
    COLUMN = ("rollups", "topic_mix")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollupKindCounts(Stored):
    COLUMN = ("rollups", "kind_counts")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RollupKeywords(Stored):
    COLUMN = ("rollups", "keywords")
    LIST_ROOT = "items"
    items: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class RollupUrls(Stored):
    COLUMN = ("rollups", "urls")
    LIST_ROOT = "items"
    items: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class PurgeRollupIds(Stored):
    COLUMN = ("purges", "rollup_ids")
    LIST_ROOT = "items"
    items: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class PurgeDetail(Stored):
    COLUMN = ("purges", "detail")
    extra: dict[str, Any] = field(default_factory=dict)
