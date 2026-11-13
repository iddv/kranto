"""The ``settings`` keys that hold an object. The other keys hold plain
text (``setup.done``, ``seen_at``, ``paused``, the purge token, a websearch failure count, the
broker's adapter id) and stay strings through ``Store.get_setting``.

Each module that owns a key reads it with :func:`get_blob` and writes it with :func:`set_blob`;
the value it hands its callers is the type's ``to_dict()``, so their reads are unchanged. A
value that is not the key's object (text left by a hand edit, a list) reads as no value, noted
once, where ``json.loads`` used to raise.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from .base import SETTINGS, Iso, Stored

if TYPE_CHECKING:
    from ..store import Store

T = TypeVar("T", bound=Stored)


@dataclass(frozen=True)
class KeyTest(Stored):
    """The last test of the model key (``setup.record_key_test``)."""

    SETTING = "setup.key_test"
    ok: bool | None = None
    detail: str | None = None
    base_url: str | None = None
    at: Iso | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WatchPause(Stored):
    """A provider's pause on watching (``llm.LLMClient._pause``): until when, why, whose."""

    SETTING = "watch_paused"
    until: Iso | None = None
    reason: str | None = None
    provider: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SanitySite(Stored):
    """Where the Sanity Studio and the site's posts are (never a secret)."""

    SETTING = "sanity.site"
    studio: str | None = None
    post_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PostingSites(Stored):
    """The sites the person posts to (Settings › Posting, ``core.sites.choices``): ``sites``
    ticked, in no order; ``direct`` site -> True where Kranto posts directly after their yes
    (absent: Open only); ``instance`` the Mastodon server Open goes to; ``disclose`` site ->
    True where a post ends with the disclosure line (off by default). Readers: ``sites.choices``,
    ``web/post_api`` (``posting_read``, ``posting_write``); each takes a missing key and a key
    stored as null."""

    SETTING = "post.sites"
    sites: list[str] = field(default_factory=list)
    direct: dict[str, Any] = field(default_factory=dict)
    instance: str | None = None
    disclose: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MoneyHalt(Stored):
    """Invest's Stop in force (``core.money.halt``)."""

    SETTING = "money.halted"
    reason: str | None = None
    since: Iso | None = None
    by: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MoneyLive(Stored):
    """Live trading switched on on the page (``core.money.set_live``, until paper-first was
    retired: D-6); kept as history, read by nothing since."""

    SETTING = "money.live"
    since: Iso | None = None
    by: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolsApproved(Stored):
    """The broker server's tools the owner approved (``core.money.approve_tools``): the list's
    hash, which tool does which operation, what did not map, when, by whom, each tool's hash."""

    SETTING = "money.broker.*.approved"
    list_hash: str | None = None
    map: dict[str, str] = field(default_factory=dict)
    problems: list[Any] = field(default_factory=list)
    at: Iso | None = None
    by: str | None = None
    tools: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsletterSender(Stored):
    """The newsletter platform chosen at Connect, and what its last check found missing."""

    SETTING = "newsletter.sender"
    JSON_NAMES = {"from_": "from"}
    platform: str | None = None
    from_: str | None = None
    audience_id: str | None = None
    audience_name: str | None = None
    last_check: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def contract_for_key(key: str) -> type[Stored] | None:
    """The contract of a settings key (a pattern's ``*`` matches any part), or None for a key
    that holds plain text."""
    if key in SETTINGS:
        return SETTINGS[key]
    return next((t for pat, t in SETTINGS.items() if fnmatch.fnmatchcase(key, pat)), None)


def get_blob(store: Store, key: str, cls: type[T]) -> T | None:
    """The key's object, or None when the key is not set (or holds no readable object)."""
    return cls.parse(store.get_setting(key))


def set_blob(store: Store, key: str, value: Stored) -> None:
    store.set_setting(key, value.to_json())
