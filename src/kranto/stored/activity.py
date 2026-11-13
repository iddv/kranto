"""What the activity keeps: a waiting mark's ``needs`` and a mark's
``detail`` (``run_marks``), and ``<data>/activity.json``, the running runs' mirror.

``needs`` names the owner's verb and where it is pressed (``activity.Run.waiting`` clips it to
``verb``, ``href``, ``words``). ``detail`` is a step's own facts, scrubbed and capped at
``DETAIL_MAX`` (over it: ``{"note": ...}``), kept whole in ``extra``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .base import Iso, Stored


@dataclass(frozen=True)
class Needs(Stored):
    COLUMN = ("run_marks", "needs")
    verb: str | None = None
    href: str | None = None
    words: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkDetail(Stored):
    COLUMN = ("run_marks", "detail")
    note: str | None = None               # "its detail was over ... bytes"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        # a step's facts may hold a date: kept as its text, as the writer always did
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ActivityMirror(Stored):
    """``activity.json``: a sequence number, when, and the runs in progress (their views)."""

    FILE = "activity.json"
    seq: int = 0
    updated: Iso | None = None
    running: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
