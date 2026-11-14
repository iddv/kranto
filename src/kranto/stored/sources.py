"""``sources.validation`` and ``sources.params`` (the table).

``validation`` is what the test fetch found when a source was added. Its writers, and what each
stores:

1. the scout's proposals (``scout.scout_topic``): the measurement (``status``, ``items``,
   ``recent``, ``latest``, ``median_similarity``, ``error``, ``discovered_from``), ``why``,
   ``topic_id``, ``role``, ``grounding``, ``cites``, ``search``, maybe ``cost_usd``,
   ``replaces``, ``preset``/``fields``;
2. a site watched through live search (``scout._watch_by_search``): the same, ``unverified``,
   ``preset: "web.search"``;
3. **Add sources by describing them** (``resolve.take``): the measurement, ``why``, ``from``,
   ``batch``, ``role: "core"``, and **``topic_id`` and ``median_similarity`` None when no topic
   was chosen** (the RCA's row: without a topic the similarity is not measured);
4. a preset's form (``source_health.add_from_preset``): ``items``, ``preset``, ``fields``,
   ``checked: "preview"``, no ``status``;
5. ``python -m kranto pack``: ``items``, ``checked: "pack"``;
6. ``python -m kranto source add`` and the plain add form: ``items``, ``checked: "manual"``;
7. the Parallax import: no record at all (the column is NULL).

So every key but ``items`` may be absent, and ``status`` is absent on four writers.

``params`` is the source kind's keyword arguments (``sources.build(kind, **params)``), stored as
``sources.canonical_params`` writes them: that text is UNIQUE with the kind, so it stays the one
writer. :class:`Params` names the keys the kinds take, so a reader asks ``p.query`` and gets
``None`` rather than a ``KeyError`` (the F3: an arxiv source's ``params['query']``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .base import Iso, Stored

Status = Literal["valid", "invalid", "unverified"]
Role = Literal["core", "wildcard"]
Checked = Literal["preview", "pack", "manual"]


@dataclass(frozen=True)
class Cost(Stored):
    """What testing a source cost, and what one run of it would (X's paid reads)."""

    check: float | None = None
    run: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Validation(Stored):
    """What the test fetch found when a source was added (``sources.validation``). A field is
    None when its writer did not measure it: a source tested without a topic has no
    ``median_similarity``, a pack's has no ``status``. NULL (a Parallax import) is no record:
    ``SourceRow.validation is None``."""

    COLUMN = ("sources", "validation")
    JSON_NAMES = {"from_text": "from"}

    status: Status | None = None
    items: int = 0
    recent: int | None = None
    latest: Iso | None = None
    median_similarity: float | None = None
    error: str | None = None
    discovered_from: str | None = None
    why: str | None = None
    topic_id: int | None = None
    role: Role | None = None
    preset: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    checked: Checked | None = None
    from_text: str | None = None          # "from" in the JSON: the sentence it was described in
    batch: str | None = None
    grounding: str | None = None
    cites: list[dict[str, Any]] = field(default_factory=list)
    search: dict[str, Any] | None = None
    cost_usd: Cost | None = None
    replaces: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def checked_by(cls, how: Checked, items: int | None = None) -> Validation:
        """A pack's, a hand-added source's or a preset's record: what was read, no test."""
        return cls(items=items or 0, checked=how)

    @classmethod
    def named_odd(cls) -> list[Validation]:
        return [
            # Add sources by describing them, no topic chosen: the RCA's row
            cls(status="valid", items=12, recent=3, median_similarity=None, topic_id=None,
                role="core", from_text="sources about tea", batch="fromtext:1", why="a blog"),
            cls(items=3, checked="pack"),
            cls(items=9, checked="manual"),
            cls(items=4, preset="rss.feed", fields={"url": "https://example.org/feed"},
                checked="preview"),
            cls(status="unverified", preset="web.search", fields={"site": "example.org"},
                error="no feed found: example.org", role="core", topic_id=1),
            cls(status="invalid", error="feed has no items"),
            cls(status="valid", role="wildcard", topic_id=1, median_similarity=0.31),
        ]

    def api(self) -> dict[str, Any]:
        """The keys the API's ``SourceValidation`` shows (``web/types.py``), when set."""
        keys = ("status", "items", "recent", "median_similarity", "error", "discovered_from",
                "checked", "from", "batch", "latest", "topic_id", "role", "preset", "why",
                "replaces")
        d = super().api()
        return {k: d[k] for k in keys if k in d}


@dataclass(frozen=True)
class Params(Stored):
    """A source's parameters (``sources.params``): the keyword arguments of its kind's class
    (``url`` for rss; ``feed`` or ``query`` for hackernews; ``query`` for arxiv; ``subreddit``;
    ``instance``, ``what``, ``list_id`` for mastodon; ``feed_uri``, ``list_uri``, ``what``,
    ``query`` for bluesky; ``site`` for websearch; ...). Each kind's class declares and checks its
    own, so every key is kept exactly as stored (a value dropped here would change what is
    read): ``kwargs()`` is what ``sources.build`` takes, ``text(key)`` a key read as text. The
    stored text is written by ``sources.canonical_params`` only (UNIQUE with the kind)."""

    COLUMN = ("sources", "params")

    extra: dict[str, Any] = field(default_factory=dict)

    def kwargs(self) -> dict[str, Any]:
        return dict(self.extra)

    def text(self, key: str) -> str | None:
        """The key's value when it is text, else None (absent, null, or not text)."""
        v = self.extra.get(key)
        return v if isinstance(v, str) else None

    @classmethod
    def named_odd(cls) -> list[Params]:
        return [cls(extra={"url": "https://example.org/feed"}), cls(extra={"feed": "top"}),
                cls(extra={"query": "tea"}), cls(extra={"subreddit": "tea"}),
                cls(extra={"site": "example.org"}), cls(extra={"what": "home", "x": None})]
