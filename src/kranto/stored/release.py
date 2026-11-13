"""The promotion's two files under ``<home>/update/`` (the owner's
decisions of 2026-10-24): what the gate found, and the owner's press.

- :class:`Candidate`, ``update/candidate.json``: written by ``scripts/release/gate.py tick``
  (hourly, and after a press), read by ``GET /api/update`` on the maintainer's install. Its
  ``state`` is ``none`` (nightly is not ahead of stable), ``candidate`` (the press is open),
  ``blocked`` (a health check blocks it), ``promoting`` (``step``: cutting, rc_check,
  releasing), ``promoted`` or ``failed`` (``step``, ``reason``, ``log``); a state this Kranto does
  not know reads as it is, and the page shows no press for it. The facts are the build, the
  pull requests since the last stable (``big`` named), the settings that stay off on stable,
  and each check (``ok`` true, false: blocks, or null: could not read, said in ``blind``);
  ``setup``: the install's own trouble (a refused model key), said, never blocking.
  Nothing in it is a count of days: ``nightly_since`` is information only.
- :class:`PromoteAsk`, ``update/promote.json``: written by ``POST /api/update/promote`` (the
  press, on the maintainer's install only), read and removed by the gate's tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Iso, Stored


@dataclass(frozen=True)
class ReleaseCheck(Stored):
    """One health check: ``ok`` True, False (blocks the press) or None (could not read)."""

    name: str = ""
    ok: bool | None = None
    said: str = ""
    found: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReleasePR(Stored):
    """A pull request the candidate carries (``repo`` on the ``big`` ones)."""

    number: int = 0
    title: str = ""
    repo: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OffOnStable(Stored):
    """A setting whose stable default keeps the old behaviour (``Setting(default_stable=)``)."""

    key: str = ""
    default: Any = None
    default_stable: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromoteAsk(Stored):
    """The owner's press: promote this nightly build to stable."""

    FILE = "update/promote.json"
    tag: str = ""
    by: str | None = None
    at: Iso | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Candidate(Stored):
    """What the gate found: the candidate for stable and its checks, or what became of a
    press."""

    FILE = "update/candidate.json"
    schema: int = 1
    at: Iso | None = None
    state: str = "none"
    said: str | None = None
    stable: str | None = None
    tag: str | None = None
    version: str | None = None
    to: str | None = None
    installed: str | None = None
    published_at: Iso | None = None
    nightly_since: Iso | None = None
    prs: dict[str, list[ReleasePR]] = field(default_factory=dict)
    count: int = 0
    big: list[ReleasePR] = field(default_factory=list)
    off_on_stable: list[OffOnStable] = field(default_factory=list)
    checks: list[ReleaseCheck] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    blind: list[str] = field(default_factory=list)
    # the install's own trouble the errors check found and did not block on (a model key
    # refused), in words; absent or null when there is none
    setup: str | None = None
    step: str | None = None
    reason: str | None = None
    log: str | None = None
    asked: PromoteAsk | None = None
    refused: dict[str, Any] | None = None
    promoted: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        """The press is open: a candidate nothing blocks."""
        return self.state == "candidate" and bool(self.tag) and not self.blocking
