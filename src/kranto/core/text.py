"""Text helpers a feature's prompts and checks use, re-exported from the core's own."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from .. import legacy
from ..scrub import scrub
from ..store import iso, utcnow
from ..websearch import NO_SEARCH, Results, combine, fenced, hit_for, is_backend_label, outlet

__all__ = ["NO_SEARCH", "OLD_VERB_ON", "Results", "combine", "domain", "fenced", "hit_for",
           "is_backend_label", "iso", "outlet", "parse_time", "possessive", "scrub", "utcnow",
           "words"]

# A why line stored before a prompt changed can open with the verb that was also the old
# product's name ("<verb> on robot costs"); legacy.COMMAND is that word.
OLD_VERB_ON = re.compile(rf"^\s*(?:it\s+)?{re.escape(legacy.COMMAND)}\s+on\s+", re.IGNORECASE)

# Second-level labels under which the registrable domain is three labels (co.uk, com.au...).
_SECOND = {"co", "com", "org", "net", "gov", "ac", "edu"}


def domain(url: str | None) -> str | None:
    """The registrable domain of a URL, near enough for "independent origins": the last two
    labels, or three under a country's ``co.``/``com.``-style second level."""
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if not host or re.fullmatch(r"[0-9.]+", host):
        return host or None
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def words(text: str | None) -> int:
    return len(str(text or "").split())


def possessive(name: str) -> str:
    """A name's possessive as the run's words say it: "Robotics' brief", "Newsletter's"."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
