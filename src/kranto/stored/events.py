"""``events.payload``: an event's facts, a JSON object of ids and small facts
(``core.events._check_payload``: at most three levels deep, short strings, ``MAX_PAYLOAD``
bytes), kept whole. A payload that is not an object reads as empty."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Stored


@dataclass(frozen=True)
class Payload(Stored):
    COLUMN = ("events", "payload")
    extra: dict[str, Any] = field(default_factory=dict)
