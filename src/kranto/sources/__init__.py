"""Source registry: kind name -> adapter, plus canonical parameter handling.

A kind whose adapter declares ``needs`` (a connection provider), or whose
``needs_for(params)`` names one for some sources (Bluesky's home timeline and
search, not its public feeds), reads with a connected account: ``build`` asks
``connections`` for an ``HTTP`` that carries the account's credentials, and
raises a transient ``SourceError`` marked ``needs_login`` when there is no
usable connection, so a run continues and the source's row says why
(section 3.6). A kind that declares ``uses`` (Stack Exchange's
app key) reads with the connection when there is one and without it otherwise.
"""

from __future__ import annotations

import contextlib
import json

from .arxiv import ArxivSource
from .base import HTTP, Item, Source, SourceError, canonical_url, safe_url
from .bluesky import BlueskySource
from .github_stars import GitHubSource
from .hackernews import HackerNewsSource
from .mastodon import MastodonSource
from .producthunt import ProductHuntSource
from .reddit import RedditSource
from .rss import RSSSource
from .stackexchange import StackExchangeSource
from .websearch_source import WebSearchSource
from .x import XSource
from .xai_search import XAISearchSource
from .youtube import YouTubeSource

KINDS = {
    "reddit": RedditSource,
    "hackernews": HackerNewsSource,
    "rss": RSSSource,
    "arxiv": ArxivSource,
    "bluesky": BlueskySource,
    "mastodon": MastodonSource,
    "github": GitHubSource,
    "youtube": YouTubeSource,
    "producthunt": ProductHuntSource,
    "stackexchange": StackExchangeSource,
    "x": XSource,
    "xai_search": XAISearchSource,
    "websearch": WebSearchSource,
}
# Kinds whose every source reads with a connected account, and that account's provider.
NEEDS = {kind: cls.needs for kind, cls in KINDS.items() if getattr(cls, "needs", None)}

__all__ = [
    "HTTP", "KINDS", "NEEDS", "Item", "Source", "SourceError", "build", "canonical_params",
    "canonical_url", "needs", "params_from_value", "safe_url", "uses",
]


def needs(kind: str, params: dict | None) -> str | None:
    """The connection provider a source cannot be read without, or None."""
    cls = KINDS.get(kind)
    if cls is None:
        return None
    if hasattr(cls, "needs_for"):
        return cls.needs_for(params or {})
    return getattr(cls, "needs", None)


def uses(kind: str) -> str | None:
    """The connection provider a kind reads with when one is connected (optional)."""
    return getattr(KINDS.get(kind), "uses", None)


def canonical_params(kind: str, params: dict) -> str:
    """Stable JSON for (kind, params) uniqueness in the sources table."""
    if kind not in KINDS:
        raise ValueError(f"unknown source kind {kind!r}; one of {', '.join(KINDS)}")
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    if kind == "reddit":
        clean["subreddit"] = str(clean.get("subreddit", "")).removeprefix("r/").lower()
    if kind == "mastodon":
        clean["instance"] = str(clean.get("instance", "")).lower()
        clean.pop("title", None)  # a list's name is a label, not what is read
    if kind == "bluesky":
        clean.pop("title", None)
    if kind == "x":
        clean.pop("title", None)    # a list's name and an account's handle are labels
        clean.pop("handle", None)
    if kind == "stackexchange":
        clean["site"] = str(clean.get("site", "")).lower()
    if kind == "websearch":
        from .websearch_source import host_of
        clean["site"] = host_of(str(clean.get("site", "")))
    return json.dumps(clean, sort_keys=True, separators=(",", ":"))


def params_from_value(kind: str, value: str) -> dict:
    """Turn the single user-facing value for a kind into adapter parameters."""
    value = value.strip()
    if kind == "reddit":
        return {"subreddit": value}
    if kind == "hackernews":
        from .hackernews import FEEDS

        return {"feed": value} if value in FEEDS else {"query": value}
    if kind == "rss":
        return {"url": value}
    if kind == "arxiv":
        return {"query": value}
    if kind in KINDS:
        raise ValueError(f"a {kind} source is added from the catalog, not from a single value")
    raise ValueError(f"unknown source kind {kind!r}; one of {', '.join(KINDS)}")


def build(kind: str, params: dict | str, http: HTTP, *, connections=None, llm=None) -> Source:
    """The adapter for a source. ``connections`` (``kranto.connections.Connections``)
    is needed for kinds in ``NEEDS``; without a usable connection this raises a
    transient ``SourceError`` with ``needs_login`` set. ``llm`` (the metered client) is given
    to a kind that reads through a model (``needs_llm``: X search through Grok)."""
    if isinstance(params, str):
        params = json.loads(params)
    try:
        cls = KINDS[kind]
    except KeyError:
        raise ValueError(f"unknown source kind {kind!r}") from None
    provider = needs(kind, params)
    if provider:
        if connections is None:
            raise SourceError(f"needs login: no {provider} connection is available here",
                              needs_login=True)
        http = connections.http_for(provider, params.get("instance"), http)
    elif uses(kind) and connections is not None:
        # No usable key: read without one, at the smaller allowance.
        with contextlib.suppress(SourceError):
            http = connections.http_for(uses(kind), params.get("instance"), http)
    if getattr(cls, "needs_llm", False):
        return cls(http, **params, llm=llm)
    return cls(http, **params)
