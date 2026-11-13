"""``observations.tags`` and the model calls' ``llm_calls.request`` / ``.response``
.

``tags`` is ``intern.parse``'s list of up to ``MAX_TAGS`` short strings (the Parallax import:
up to 8). ``request`` is the body Kranto sent the provider, ``response`` the provider's raw
answer: the provider's own JSON, kept whole in ``extra`` and read totally (a response that is
not JSON, or NULL for a call that failed before an answer, reads as empty).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Stored


@dataclass(frozen=True)
class Tags(Stored):
    COLUMN = ("observations", "tags")
    LIST_ROOT = "items"
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LlmRequest(Stored):
    """What Kranto sent: the provider's request body (model, messages, ...), as sent."""

    COLUMN = ("llm_calls", "request")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LlmResponse(Stored):
    """What the provider answered, as it answered (None: no answer)."""

    COLUMN = ("llm_calls", "response")
    extra: dict[str, Any] = field(default_factory=dict)
