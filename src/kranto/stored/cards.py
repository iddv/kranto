"""An idea card and what is stored beside it: ``ideas.card``,
``ideas.dropped``, ``ideas.input_ids``, ``idea_topics.shares``, ``syntheses.input_ids``.

Two writers store a card. ``ideate.cards._card_one`` stores ``parse_card``'s fields, then the
prior art (``prior_art``, ``novelty_dropped``), the check (each evidence entry gets the cited
observation's ``evidence_snapshot``, ``demand.supported``), ``citations``, ``prompts`` and
``why_selected``. ``ideate.dispatches.card_for`` stores the same keys with ``pitch*``,
``dispatch``, ``lineages`` and ``links``.

A card from an older prompt has fewer keys: no ``who``, ``smallest_v1``, ``demand``,
``citations`` or ``prior_art`` before #96 and none of the v1 fields (``insight``,
``existing``, ``gap``, ``moment``, ``mechanism``) or ``editor_notes`` unless the prompt wrote
them. Each reads as its field's None or empty.

**An evidence entry always has ``observation_id``** (both writers merge
``evidence_snapshot`` into every entry since v0.2.0; the F4). The type says what a reader
gets when one does not: ``observation_id`` None, and every reader skips such an entry instead of
indexing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Stored


@dataclass(frozen=True)
class Evidence(Stored):
    """A claim a card cites: the model's ``n`` and ``claim``, and the cited observation as the
    card keeps it (``evidence_snapshot``)."""

    n: int | None = None
    claim: str | None = None
    observation_id: int | None = None
    summary: str | None = None
    source: str | None = None
    observed_at: str | None = None
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rating(Stored):
    """One of the five ratings: its value (0 to 1), the writer's reason, the claims it cites."""

    value: float | None = None
    reason: str | None = None
    cites: list[int] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Demand(Stored):
    """Who asks for it: the statement, the claims that show it, and how many held up."""

    statement: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    supported: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Prediction(Stored):
    statement: str | None = None
    by: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Existing(Stored):
    """What exists already, as a v1 card (and an editor's notes) says it: the claim it cites,
    the name, what it covers (``ideate.cards._v1_fields``)."""

    n: int | None = None
    name: str | None = None
    covers: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EditorNotes(Stored):
    """The weekly editor's block (``ideate.cards._editor_notes``): each key only when the
    reply had it."""

    kind: str | None = None
    existing: list[Existing] = field(default_factory=list)
    gap: str | None = None
    absorber: str | None = None
    facets: list[str] = field(default_factory=list)
    integration_point: str | None = None
    channel: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriorArtHit(Stored):
    """A live-search result as the card keeps it; one the card says shows what exists adds
    ``what``."""

    label: str | None = None
    url: str | None = None
    title: str | None = None
    date: str | None = None
    what: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriorArt(Stored):
    """The card's prior-art search (``ideate.cards.apply_prior_art``)."""

    live: bool | None = None
    searched_at: str | None = None
    query: str | None = None
    backends: list[str] = field(default_factory=list)
    note: str | None = None
    results: int | None = None
    hits: list[PriorArtHit] = field(default_factory=list)
    existing: list[PriorArtHit] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NoveltyDrop(Stored):
    """A novelty claim the prior-art check removed: the card's field, the sentence, why."""

    extra: dict[str, Any] = field(default_factory=dict)
    field: str | None = None            # after ``extra``: the name is dataclasses' too
    sentence: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Card(Stored):
    """An idea card (``ideas.card``). Text a writer may leave out is ``str | None``; lists and
    objects a writer may leave out are empty. ``extra`` keeps every key no field names (the
    dispatch card's ``pitch*``, ``links``; a newer prompt's)."""

    COLUMN = ("ideas", "card")

    title: str | None = None
    pattern: str | None = None
    where_now: str | None = None
    thesis: str | None = None
    who: str | None = None
    smallest_v1: str | None = None
    one_liner: str | None = None
    output_kind: str | None = None
    demand: Demand | str | None = None    # a card from before #96: the statement alone
    evidence: list[Evidence] = field(default_factory=list)
    prediction: Prediction | None = None
    cheapest_test: str | None = None
    risks: str | None = None
    ratings: dict[str, Rating] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    prompts: dict[str, Any] = field(default_factory=dict)
    why_selected: str | None = None
    prior_art: PriorArt | None = None
    novelty_dropped: list[NoveltyDrop] = field(default_factory=list)
    insight: str | None = None
    existing: list[Existing] = field(default_factory=list)
    gap: str | None = None
    moment: str | None = None
    mechanism: str | None = None
    editor_notes: EditorNotes | None = None
    # a card made from one of the owner's dispatches
    pitch: str | None = None
    pitch_text: str | None = None
    pitch_kind: str | None = None
    pitch_label: str | None = None
    dispatch: dict[str, Any] | None = None
    lineages: list[dict[str, Any]] = field(default_factory=list)
    links: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def cited_ids(self) -> list[int]:
        """The observations its evidence cites, in order (an entry without an id is left out)."""
        return [e.observation_id for e in self.evidence if e.observation_id is not None]

    def demand_of(self) -> Demand | None:
        """Its demand as a Demand (a statement stored as text alone is one with no evidence)."""
        if isinstance(self.demand, str):
            text = self.demand.strip()
            return Demand(statement=text, supported=0) if text else None
        return self.demand

    @classmethod
    def named_odd(cls) -> list[Card]:
        return [
            # a card from the first prompt: none of the later fields
            cls(title="An old card", thesis="t", pattern="p", where_now="w",
                evidence=[Evidence(n=1, claim="c", observation_id=1)],
                ratings={"demand_validation": Rating(value=0.5, reason="r")}),
            # a dispatch card: no ratings, its pitch
            cls(title="A dispatch", pitch="p", pitch_kind="app", dispatch={"id": "d1"},
                evidence=[Evidence(n=1, claim="c", observation_id=2)]),
            # an evidence entry with no observation id (F4: no writer stores one)
            cls(title="No id", evidence=[Evidence(n=1, claim="c")]),
        ]


@dataclass(frozen=True)
class DroppedClaim(Stored):
    """A claim the check did not support (``ideas.dropped`` holds a list of them)."""

    n: int | None = None
    claim: str | None = None
    reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dropped(Stored):
    COLUMN = ("ideas", "dropped")
    LIST_ROOT = "items"
    items: list[DroppedClaim] = field(default_factory=list)


@dataclass(frozen=True)
class InputIds(Stored):
    """The observation ids a card (or an explained neighbourhood) was written from."""

    COLUMN = ("ideas", "input_ids")
    LIST_ROOT = "items"
    items: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class SynthesisInputIds(InputIds):
    COLUMN = ("syntheses", "input_ids")


@dataclass(frozen=True)
class Share(Stored):
    """A topic's share of a card's evidence (``idea_topics.shares``)."""

    id: int | None = None
    name: str | None = None
    kind: str | None = None
    n: int = 0
    share: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Shares(Stored):
    COLUMN = ("idea_topics", "shares")
    LIST_ROOT = "items"
    items: list[Share] = field(default_factory=list)
