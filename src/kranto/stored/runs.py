"""``runs.summary`` (the F2): what each run kind recorded about itself.

Twelve writers store ``json.dumps`` of a dict, one shape per kind: ingest (``tick.RunReport``),
snapshot, compact, ideas (two writers), deepdive, heartbeat, telemetry, update, xrecheck,
dispatch_import, and every feature's job (``core.context.record_run``, any dict). A reader asks
:func:`summary_of` with the row's kind, and gets that kind's type:

- :class:`IngestSummary`: the run's totals and its per-source reports (``sources``), each a
  :class:`SourceReport` with every count an int and the fetch's error, state and pacing
  ``None`` when the source was not fetched;
- :class:`SnapshotSummary`: the snapshot it took, and why naming was skipped;
- :class:`IdeasSummary`: the map fingerprint the cards were written from;
- every other kind: :class:`RunSummary` itself. Its keys are kept in ``extra`` and read with
  ``text(key)``. A kind gets a type of its own when a reader reads one of its fields.

Older rows read too. An ingest summary from v0.2.0 has no ``tokens`` or ``overrides``, which
read as None. NULL, text that is not JSON, and JSON that is not an object (``[]``) all read as
the kind's empty summary, and the problem is noted once.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .base import Noter, Stored


@dataclass(frozen=True)
class RunSummary(Stored):
    """A run's summary: the base of every kind's type, and the type of a kind with none of its
    own (a feature's job, compact, deepdive, ...), whose keys are all in ``extra``."""

    COLUMN = ("runs", "summary")

    extra: dict[str, Any] = field(default_factory=dict)

    def text(self, key: str) -> str | None:
        """The key's value when it is text that is not empty, else None."""
        v = self.extra.get(key)
        return v if isinstance(v, str) and v else None

    def to_json(self) -> str:
        # a feature's job may record a date or a path: kept as its text, as record_run did
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class SourceReport(Stored):
    """One source's part of an ingest run (``tick.SourceReport``, as ``sources[i]``)."""

    source_id: int | None = None
    label: str | None = None
    fetched: int = 0
    new: int = 0
    deferred: int = 0
    backfill: bool = False
    full_text: int = 0
    prefiltered: int = 0
    explored: int = 0
    judged: int = 0
    contributed: int = 0
    gated: int = 0
    skipped: int = 0
    duplicates: int = 0
    near_duplicates: int = 0
    linked: int = 0
    removed: int = 0
    stale: int = 0
    parse_failed: int = 0
    item_errors: int = 0
    llm_errors: int = 0
    # of llm_errors, the replies that came back empty after their retries; and items the
    # model or a safety filter declined (consumed as item_error,)
    empty_replies: int = 0
    refused: int = 0
    no_content: int = 0
    screened: int = 0
    screened_out: int = 0
    looked: int = 0
    look_capped: int = 0
    gathered: int = 0
    gather_requests: int = 0
    children: int = 0
    children_gated: int = 0
    screened_spam: int = 0
    rated: int = 0
    override_set: int = 0
    override_lifted: int = 0
    override_refused: int = 0
    sponsored: int = 0
    sponsor_links: int = 0
    sponsor_reasons: list[str] = field(default_factory=list)
    fetch_error: str | None = None
    fetch_state: str | None = None
    retry_at: str | None = None
    retried: bool = False
    failing_runs: int = 0
    waiting_until: str | None = None
    not_reached: bool = False
    muted: bool = False
    read_less: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tokens(Stored):
    """A run's model calls in tokens (None on the summary: no call with counts)."""

    JSON_NAMES = {"tokens_in": "in", "tokens_out": "out"}
    tokens_in: int = 0
    tokens_out: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Overrides(Stored):
    """The judge's override over a run."""

    JSON_NAMES = {"set_": "set"}
    rated: int = 0
    set_: int = 0
    lifted: int = 0
    refused: int = 0
    rate: float | None = None             # None: no reply had ratings
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestSummary(RunSummary):
    """An ingest run (``tick.RunReport.to_json``)."""

    spend_usd: float = 0.0
    tokens: Tokens | None = None
    contributed: int | None = None        # None: a run that did not record it
    overrides: Overrides | None = None
    sponsored: int = 0
    sponsor_links: int = 0
    sources: list[SourceReport] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def named_odd(cls) -> list[IngestSummary]:
        return [cls(tokens=None, overrides=Overrides(rate=None)),       # an older run's
                cls(sources=[SourceReport(source_id=1, label="Feed", fetch_error="HTTP 503",
                                          fetch_state="failing", failing_runs=3)]),
                cls(sources=[SourceReport(source_id=2, not_reached=True,
                                          waiting_until="2026-10-23T12:00:00Z")])]


@dataclass(frozen=True)
class SnapshotSummary(RunSummary):
    """A snapshot run (``map.snapshot.SnapshotReport.summary``): the fields a reader reads
    (``snapshot_id``, ``names_skipped``); the rest in ``extra``."""

    snapshot_id: int | None = None
    names_skipped: str | None = None      # why naming the themes was skipped, or None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IdeasSummary(RunSummary):
    """An ideas run (``ideate.cards``): the map fingerprint its cards came from (None before a
    first card run, or for one that found nothing to card)."""

    fingerprint: str | None = None
    snapshot_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


KINDS: dict[str, type[RunSummary]] = {
    "ingest": IngestSummary, "snapshot": SnapshotSummary, "ideas": IdeasSummary,
}


def summary_of(kind: str | None, raw: str | bytes | Mapping[str, Any] | None) -> RunSummary:
    """A run's summary as its kind's type (a kind with none of its own: :class:`RunSummary`).
    Never raises; NULL, broken JSON or a non-object read as the empty summary."""
    return KINDS.get(kind or "", RunSummary).load(raw)


def text_for(kind: str, summary: str | Mapping[str, Any]) -> str:
    """What a writer stores for its run: the summary read through its kind's type and written
    back (sorted, compact; a key no field names is kept as it was). A value the type cannot
    read is noted once, and then the writer's own dict is stored as it is: a summary never
    loses what its run recorded (the odd install and the tests keep the types and the writers
    in step)."""
    cls = KINDS.get(kind, RunSummary)
    n = Noter(cls.where())
    d = summary if isinstance(summary, Mapping) else cls._decode(summary, n)
    if d is None:
        return cls.empty().to_json()
    got = cls.read(d, n)
    if n.problems:
        return json.dumps(dict(d), sort_keys=True, separators=(",", ":"), default=str)
    return got.to_json()
