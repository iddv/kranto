"""The rest of the library's stored JSON: messages and strikes, feedback,
grades and outcomes, connections' scopes, the Parallax archive's themes, the search cache,
topic revisions and deep dives. Each has one writer (``notify``, ``gate``, ``feedback``,
``grades``, ``outcomes``, ``connections``, ``importers``, ``websearch``, ``library``,
``deepdive``) and is kept whole: its readers get a total read, never a raise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Stored


@dataclass(frozen=True)
class MessageLinks(Stored):
    COLUMN = ("messages", "links")
    LIST_ROOT = "items"
    items: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class MessageEvidenceIds(Stored):
    COLUMN = ("messages", "evidence_ids")
    LIST_ROOT = "items"
    items: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateLinks(Stored):
    COLUMN = ("strike_candidates", "links")
    LIST_ROOT = "items"
    items: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateEvidenceIds(Stored):
    COLUMN = ("strike_candidates", "evidence_ids")
    LIST_ROOT = "items"
    items: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateDetail(Stored):
    COLUMN = ("strike_candidates", "detail")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionDetail(Stored):
    COLUMN = ("strike_decisions", "detail")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedbackReasons(Stored):
    """The why chips given (``feedback.validate`` checks them against the vocabulary)."""

    COLUMN = ("feedback", "reasons")
    LIST_ROOT = "items"
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeedbackPair(Stored):
    """A pair comparison's two sides (NULL for a single grade)."""

    COLUMN = ("feedback", "pair")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedbackContext(Stored):
    """What the grade was given on: a card's id (a build grade's ``card``), an idea's ref."""

    COLUMN = ("feedback", "context")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GradeContext(Stored):
    """The frozen ``grades`` table's context (``feedback`` replaced it in L1)."""

    COLUMN = ("grades", "context")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutcomeDetail(Stored):
    COLUMN = ("outcomes", "detail")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionScopes(Stored):
    COLUMN = ("connections", "scopes")
    LIST_ROOT = "items"
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ThemeNames(Stored):
    """An archive theme's names over time: ``[{name, first_at, last_at}]``."""

    COLUMN = ("archive_themes", "names")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ThemeKeywords(Stored):
    COLUMN = ("archive_themes", "keywords")
    LIST_ROOT = "items"
    items: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class ThemeHistory(Stored):
    """An archive theme's points: ``[{at, cluster, n, ...}]``."""

    COLUMN = ("archive_themes", "history")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResults(Stored):
    """A cached live search's hits (``websearch.Hit`` as dicts)."""

    COLUMN = ("search_cache", "results_json")
    LIST_ROOT = "items"
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TopicChanged(Stored):
    """A topic revision's changed fields' names."""

    COLUMN = ("topic_revisions", "changed")
    LIST_ROOT = "items"
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeepDiveDetail(Stored):
    COLUMN = ("deep_dive_events", "detail")
    extra: dict[str, Any] = field(default_factory=dict)
