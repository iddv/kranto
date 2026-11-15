"""Why a model call failed, in the owner's words, said for the provider in use.

A failed write, a failed brief and the angle step's proposals all end in a model's error
("Claude Code: Claude Code is not installed (no claude on PATH)", "no API key: set
$OPENROUTER_API_KEY", "HTTP 401 from …"). Each said it its own way, and one said "Check the
model key" to an owner whose provider (Claude Code, their own login) has no key. Here the error
becomes one sentence that names what is wrong and where it is fixed: the words "model key"
only when the provider takes a key.

``said(error, provider)`` answers ``{"words", "fix", "key"}`` (``fix``: the page's route that
fixes it, ``key``: whether the provider takes a key) or None when the error is not a model's.
"""

from __future__ import annotations

import re
from typing import Any

from .activity.incidents import classify

WATCHING = "settings/watching"
SPEND = "settings/spend"
PLACE = "Settings › Watching"
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"

NOT_INSTALLED = ("Claude Code is not installed on this machine. Install it "
                 f"({CLAUDE_INSTALL}) and run claude once to sign in, or choose another "
                 f"provider on {PLACE}.")
NOT_SIGNED_IN = ("Claude Code is not signed in on this machine. Run claude once to sign in, or "
                 f"choose another provider on {PLACE}.")
NO_KEY = f"No model key is set. Add one on {PLACE}."
CAPPED = ("The month's spending cap is reached, so the model was not called. Raise it on "
          "Settings › Spend.")

_MISSING_ENV = re.compile(r"\$[A-Z][A-Z0-9_]*_KEY\b[^.;]*\bnot set|no api key|no model key", re.I)
_MODEL = re.compile(r"model did not answer|llmerror|did not answer: fatal|claude code:", re.I)


def inline(words: str) -> str:
    """The sentence after a colon ("No draft was written: the model did not answer."): its
    first word lowered unless it is a name (Claude Code stays)."""
    if words.startswith(("The ", "Your ", "No ")):
        return words[:1].lower() + words[1:]
    return words


def provider_of(rt: Any) -> str | None:
    """The watcher's provider (``claude_code``, ``openrouter``, …), or None when it cannot say."""
    try:
        return str(rt.llm.provider_for("reason").name)
    except Exception:  # noqa: BLE001 - no client, or a tier it does not know
        pass
    try:
        return str(rt.cfg.llm.provider)
    except Exception:  # noqa: BLE001
        return None


def said(error: Any, provider: str | None = None) -> dict[str, Any] | None:
    """The sentence for a model's error, or None when ``error`` is not one."""
    text = str(error or "")
    if not text.strip():
        return None
    low = text.lower()
    claude = "claude code" in low or provider == "claude_code"
    if "claude code is not installed" in low or "no claude on path" in low:
        return {"words": NOT_INSTALLED, "fix": WATCHING, "key": False}
    if "claude code" in low and ("not signed in" in low or "not logged in" in low
                                 or "auth login" in low):
        return {"words": NOT_SIGNED_IN, "fix": WATCHING, "key": False}
    if _MISSING_ENV.search(text):
        return {"words": NO_KEY, "fix": WATCHING, "key": True}
    if "budget" in low or "spending cap" in low or "over its cap" in low:
        return {"words": CAPPED, "fix": SPEND, "key": False}
    c = classify(text)
    if c is not None and c["provider"] != "claude_code":
        name = f"{c['name']} key" if c["name"] else "model key"
        cause = c["cause"]
        if cause == "out of credit":
            words = f"Your {name} is out of credit. Add credit, then test it on {PLACE}."
        elif cause == "missing":
            words = NO_KEY
        else:
            words = f"Your {name} was refused ({cause}). Renew it on {PLACE}."
        return {"words": words, "fix": WATCHING, "key": True}
    if _MODEL.search(text) or c is not None:
        if claude:
            return {"words": f"Claude Code did not answer. Check it on {PLACE}.",
                    "fix": WATCHING, "key": False}
        return {"words": f"The model did not answer. Check the model key on {PLACE}.",
                "fix": WATCHING, "key": True}
    return None


__all__ = ["CLAUDE_INSTALL", "NOT_INSTALLED", "NOT_SIGNED_IN", "NO_KEY", "PLACE", "WATCHING",
           "inline", "provider_of", "said"]
