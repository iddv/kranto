"""News' stored JSON: a brief's ``items``, ``search`` and ``checks``; an
article's ``body``, ``sources``, ``material`` and ``checks``, and a page's lead ``image``
(migration 40, ``articles.write`` writes them, ``articles.row_view`` reads them).

``items`` is ``brief.write``'s list, each ``{headline, body, why, cites, date, background,
observation_ids, urls, signal, sources}``; a failed or quiet brief's is ``[]``. ``quiet`` is a
sentence, not JSON. Kept whole, read totally (``api._brief`` builds the page's row from them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kranto.stored.base import Stored


@dataclass(frozen=True)
class BriefItems(Stored):
    COLUMN = ("news_briefs", "items")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BriefSearch(Stored):
    """The live search behind a brief (``brief._search_meta``); NULL when none ran."""

    COLUMN = ("news_briefs", "search")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BriefChecks(Stored):
    """What the brief's checks found (``{"no_material": true}`` when there was nothing)."""

    COLUMN = ("news_briefs", "checks")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArticleBody(Stored):
    """An article: sections, numbers, timeline, series (or none), entities, relations, themes,
    idea_seed (or none), standfirst_cites, evidence_timeline, image (or none), item."""

    COLUMN = ("news_articles", "body")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArticleSources(Stored):
    """The article's sources, each ``{label, kind, id?, n?, date?, title?, url?, source?, obs?,
    fetched_at?}``."""

    COLUMN = ("news_articles", "sources")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ArticleMaterial(Stored):
    """What the article was written from: lines, log, counts, earlier."""

    COLUMN = ("news_articles", "material")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArticleChecks(Stored):
    """The checks' counts, words, material, earlier, pages_read, search_live;
    ``{"no_material": true}`` on a quiet article."""

    COLUMN = ("news_articles", "checks")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PageImage(Stored):
    """A read page's lead image, or none (NULL)."""

    COLUMN = ("news_article_pages", "image")
    url: str | None = None
    site: str | None = None
    alt: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
