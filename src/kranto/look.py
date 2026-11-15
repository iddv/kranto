"""Look before judging: what is gathered for an item between screen and judge.

An item that passes the screen has what is one step away from it read before
the judge sees it: the Hacker News discussion beyond the top comments, pages the
item, its article and its comments link to, and repositories they name (the
#81 gatherers in ``sources.gather``). No model call is made here. Everything is
fetched through the safe HTTP client and bounded:

- per item: ``look.max_links`` pages that read as articles (at most twice as
  many fetched), ``look.max_repos`` repositories, and ``look.item_seconds`` of
  wall-clock time shared by every request, each cut off at
  ``look.request_seconds``;
- per run: ``look.max_per_run`` items gathered for (the rest are judged
  without gathering, and counted) and ``look.max_repo_lookups`` GitHub lookups.

Links in sponsor or advertising context, and ad or affiliate URLs, are never
followed (#86, ``sources.sponsors``); they are counted per run.

Gathering is context, never a reason to lose an item: anything that fails
leaves the item to be judged with what was read. Pages whose canonical URL the
library has already judged are not read again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import library
from .config import LookConfig
from .sources import HTTP, Item, gather
from .store import Store

# Source kinds whose items can be gathered for; others are judged as they are.
GATHER_KINDS = frozenset({"hackernews", "reddit", "rss"})


@dataclass
class Look:
    """What was gathered for one item."""

    gathered: list[gather.Gathered] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    requests: int = 0
    seconds: float = 0.0
    # Links left out as sponsor or advertising context: URL -> reason.
    sponsored: dict[str, str] = field(default_factory=dict)


class Looker:
    """Gathering for one ingest run, with the run's caps."""

    def __init__(self, cfg: LookConfig, http: HTTP, store: Store, *,
                 clock=time.monotonic) -> None:
        self.cfg, self.http, self.store, self.clock = cfg, http, store, clock
        self.repos = gather.RepoReader(http, max_lookups=cfg.max_repo_lookups)
        self.items = 0

    def look(self, kind: str, params: dict, item: Item) -> Look | None:
        """What is one step from ``item`` (a ``GATHER_KINDS`` source's); None once
        the run's cap is reached."""
        if self.items >= self.cfg.max_per_run:
            return None
        self.items += 1
        started = self.clock()
        box = gather.TimeBox(self.http, seconds=self.cfg.item_seconds,
                             request_seconds=self.cfg.request_seconds, clock=self.clock)
        parent = gather.Parent(
            prefix=f"look:{item.id}", source_kind=kind, source_params=params,
            item_id=item.id, title=item.title, source_url=item.url,
            canonical=item.canonical_url())
        try:
            found, notes, sponsored = gather.collect(
                box, parent, max_links=self.cfg.max_links, max_repos=self.cfg.max_repos,
                max_comments=self.cfg.max_comments, reddit_comments=self.cfg.reddit_comments,
                repos=self.repos, skip=lambda canonical: library.already_judged(
                    self.store, canonical))
        except Exception as exc:  # a hostile page must never stop ingest
            found, sponsored = [], {}
            notes = [f"gathering failed: {type(exc).__name__}: {exc}"[:300]]
        return Look(found, notes, box.requests, self.clock() - started, sponsored)
