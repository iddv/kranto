"""What a prepared press keeps (migration 41, ``web/verbs_api.py``): the verb's fields.

``fields`` are the verb's typed fields as the assistant gave them, checked against the verb
before they were kept (``core.verbs``); the keys are the verb's, so they are kept whole in
``extra``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Iso, Stored


@dataclass(frozen=True)
class PreparedFields(Stored):
    COLUMN = ("prepared", "fields")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerbsMirror(Stored):
    """``<data>/verbs.json``: what assistants did lately (a verb run or prepared), newest first,
    at most 30, and a sequence number the page's live feed and ``GET /api/verbs/recent?since=``
    read. Each line: ``seq``, ``verb``, ``title``, ``subject``, ``page``, ``mark``, ``by``,
    ``by_words``, ``prepared`` (a prepared press's uuid, or null), ``run``, ``at``."""

    FILE = "verbs.json"
    seq: int = 0
    updated: Iso | None = None
    recent: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
