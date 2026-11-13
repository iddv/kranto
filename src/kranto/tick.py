"""One ingest pass over every approved source.

Per source: fetch, drop items already consumed, keep the newest
``max_items_per_source`` (the rest roll to the next run, unconsumed), run the
tier-0 prefilter, then look before judging (#84, ``look.enabled``): a short,
lenient tier-1 screen drops clear junk (``screened_out``, with its call); for
what passes, the discussion, linked pages and repositories one step away are
gathered (``look``, no model call, capped per item and per run); the tier-1
judge then reads the item with that material, and may keep gathered sources
as observations of their own, linked to the item's (``observation_links``) in
the same transaction.

A body that is only page chrome or a cookie-consent wall is blanked before any
model reads it, and the judge is told what was there (``Item.capture_note``).

Sponsors and ads are a hard no. An item whose title marks it as an ad,
or that links to an ad or affiliate URL, is consumed as ``sponsored`` without a
model call (``sources.sponsors``); gathering never follows a link in sponsor or
advertising context. Both are counted in the run summary with their reasons
(``sponsor_reasons``, at most ``MAX_SPONSOR_REASONS`` per source). The judge's
``override`` is counted too (set, lifted, refused), so a rising rate shows.

A source muted from Kranto UI (``source_health.mutes``) is not fetched until its
mute ends, and is listed in the run as ``muted``; one set to read less is read at half
its cap.

A source that has never consumed an item is backfilled once: its cap is
``backfill_items`` for that run, and adapters that can reach further back on
a first fetch (``fetch_backfill``, HN queries) do so. Thin items that pass
the prefilter get the linked page's main text before judging when
``fetch_full_text`` is on (``sources.fulltext``).

An item whose canonical URL (``Item.canonical_url``) the judge has already
read, through any source or an earlier submission, is consumed as
``duplicate`` without a model call. An item whose own text repeats one judged
recently (``stories``: a crosspost, a repost) is consumed as
``near_duplicate`` without a model call; a similar but edited copy from
another source is judged and joins the earlier item's story.

An item is consumed (written to ``items_seen``) only once it reaches a
terminal outcome. LLM failures never consume items. A fatal LLM error (bad
key, no credit, missing model) stops the run immediately and marks it
failed: continuing would only record the same failure against every item.

The run's status is data, not a log line:

- ``ok``: no source failed persistently and no model call failed. A paced source
  (a 429, a 503, a timeout: ``sources.pacing``) is not a failure: it is fetched
  once more at the end of the run, else deferred until its host may be asked again.
- ``degraded``: a source failed ``fetch.failing_after_runs`` runs in a row (it then
  backs off by itself) or needs login, some model calls failed, or the run stopped
  early for budget or pause.
- ``failed``: a fatal model error, or every source failed to fetch.
- ``skipped``: paused, over budget, or another run holds the lock.

A run always ends in a ``runs`` row, whatever it raised: without one the
scheduler would see ingest as overdue and start it again every tick. The one
exception is a database that cannot be written, which is checked before any
paid call; there is nothing to record the run in, so the error propagates and
the scheduler backs off.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import random
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import activity, library, notify, source_health, sources, spend, stories
from .config import Config
from .embed import Embedder
from .intern import (
    SHORT_POST_KINDS,
    Screen,
    judge,
    override_effect,
    screen,
    screen_batch,
    short_post,
)
from .llm import (
    BudgetExceeded,
    EmptyReply,
    FatalLLMError,
    LLMClient,
    LLMError,
    Paused,
    RefusedReply,
    TransientLLMError,
    UnpricedModel,
)
from .look import GATHER_KINDS, Look, Looker
from .sources import sponsors
from .sources.fulltext import blank_no_content, with_full_text
from .sources.github import RepoStats
from .store import Store, iso, utcnow
from .stored import runs as stored_runs

MAX_CONSECUTIVE_TRANSIENT = 3
# Item-level model errors (a 400, a reply cut off or empty) are held back and
# only consumed once a later call in the run succeeds, which shows the endpoint
# works and the fault was the item's. This many in a row means the endpoint is
# failing every request: the run stops, fails with an alarm, and consumes none
# of them.
MAX_CONSECUTIVE_ITEM_ERRORS = 3
# Sponsor and ad rejections listed with their reasons in a run's summary, per source.
MAX_SPONSOR_REASONS = 10


@dataclass
class SourceReport:
    source_id: int
    label: str
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
    # Look before judging.
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
    # Override: replies with ratings, replies that set it, items it kept
    # below the gate, items too thin for it (gated anyway).
    rated: int = 0
    override_set: int = 0
    override_lifted: int = 0
    override_refused: int = 0
    # Sponsors and ads: items consumed as ``sponsored``, links left out.
    sponsored: int = 0
    sponsor_links: int = 0
    sponsor_reasons: list[str] = field(default_factory=list)
    # Scrubbed before it is stored; fetch_state is what the
    # source's row shows: ok, paced, failing or needs_login (source_health).
    fetch_error: str | None = None
    fetch_state: str | None = None
    # Pacing (sources.pacing): when a paced source's host may be asked again; whether it
    # was fetched again at the end of the run; runs in a row its fetch failed, this one
    # included; and, for a source not fetched this run because it is paced or backing
    # off, until when.
    retry_at: str | None = None
    retried: bool = False
    failing_runs: int = 0
    waiting_until: str | None = None
    not_reached: bool = False
    # Muted from Kranto UI (source_health.mutes): not fetched this run; or read less,
    # at half its cap.
    muted: bool = False
    read_less: bool = False


@dataclass
class RunReport:
    run_uuid: str
    status: str = "ok"
    error: str | None = None
    spend_usd: float = 0.0
    # The run's model calls in tokens, {"in", "out"} (None: no call with counts).
    tokens: dict[str, Any] | None = None
    sources: list[SourceReport] = field(default_factory=list)

    @property
    def contributed(self) -> int:
        return sum(s.contributed for s in self.sources)

    def overrides(self) -> dict[str, Any]:
        """The judge's override over the run: how often it was set among
        replies with ratings, and what it did."""
        rated = sum(s.rated for s in self.sources)
        used = sum(s.override_set for s in self.sources)
        return {"rated": rated, "set": used,
                "lifted": sum(s.override_lifted for s in self.sources),
                "refused": sum(s.override_refused for s in self.sources),
                "rate": round(used / rated, 3) if rated else None}

    def to_json(self) -> str:
        return json.dumps(
            {
                "spend_usd": round(self.spend_usd, 6),
                "tokens": self.tokens,
                "contributed": self.contributed,
                "overrides": self.overrides(),
                "sponsored": sum(s.sponsored for s in self.sources),
                "sponsor_links": sum(s.sponsor_links for s in self.sources),
                "sources": [s.__dict__ for s in self.sources],
            }
        )


class RunLocked(Exception):
    pass


@contextmanager
def run_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RunLocked(f"another run holds {path}") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _record_run(store: Store, report: RunReport, started: datetime, kind: str = "ingest") -> None:
    store.insert(
        "runs",
        {
            "run_uuid": report.run_uuid,
            "kind": kind,
            "status": report.status,
            "started_at": iso(started),
            "finished_at": iso(utcnow()),
            "summary": stored_runs.text_for(kind, report.to_json()),
            "error": report.error,
        },
    )
    notify.alarm_for_run(store, kind=kind, run_uuid=report.run_uuid, status=report.status,
                         error=report.error)


@dataclass
class Progress:
    """How far the running ingest is (MEM, S2: a stranger's first read ran 39 minutes with
    nothing said). ``source_index`` counts from 1; ``item`` is the current source's items
    done of ``items``; ``done_items`` and ``kept`` are the run's so far."""
    run_uuid: str
    started_at: str
    sources: int
    source_index: int = 0
    source: str | None = None
    items: int | None = None
    item: int = 0
    done_items: int = 0
    kept: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


_CURRENT: Progress | None = None


def progress_words(p: Progress) -> str:
    """The running ingest in words: "source 2 of 8, Lobsters · 4 of 10 items · 3 kept so far"."""
    out = f"source {max(1, p.source_index)} of {p.sources}"
    if p.source:
        out += f", {p.source}"
    if p.items:
        out += f" · {p.item + 1} of {p.items} items"
    if p.kept:
        out += f" · {p.kept} kept so far"
    return out


def current_progress() -> dict[str, Any] | None:
    """The running ingest's ``Progress`` in this process, or None."""
    p = _CURRENT
    return p.as_dict() if p is not None else None


def run_ingest(
    cfg: Config,
    store: Store,
    llm: LLMClient,
    embedder: Embedder,
    http: sources.HTTP,
    *,
    rng: random.Random | None = None,
    clock: Callable[[], datetime] = utcnow,
    lock_path: Path | None = None,
    connections: Any = None,
    on_progress: Callable[[Progress], None] | None = None,
) -> RunReport:
    """``connections`` (``kranto.connections.Connections``) is what sources that read
    with a connected account use; without it they record "needs login" and the run
    goes on. ``on_progress`` is called as each source starts, once its new items are
    known, and before each item (``afk run`` prints from it)."""
    global _CURRENT
    report = RunReport(run_uuid=activity.run_uuid("ingest"))
    started = clock()
    try:
        with run_lock(lock_path or cfg.data_dir / "ingest.lock"):
            # Fails fast on a read-only or locked database, before any paid call
            # whose llm_calls row could not be written.
            store.set_setting("ingest_write_check", iso(clock()), now=clock())
            try:
                _ingest(cfg, store, llm, embedder, http, report, rng or random.Random(), clock,
                        connections, on_progress)
            except sqlite3.Error:
                raise
            except Exception as exc:  # recorded and alarmed below, never lost in a log
                report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"
            finally:
                _CURRENT = None
    except RunLocked as exc:
        report.status, report.error = "skipped", str(exc)
    spent = store.query_one(
        "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM llm_calls WHERE run_uuid = ?",
        (report.run_uuid,))
    assert spent is not None                   # an aggregate always answers one row
    report.spend_usd = float(spent["s"])
    report.tokens = store.run_tokens([report.run_uuid]).get(report.run_uuid)
    _record_run(store, report, started)
    return report


def _ingest(
    cfg: Config,
    store: Store,
    llm: LLMClient,
    embedder: Embedder,
    http: sources.HTTP,
    report: RunReport,
    rng: random.Random,
    clock: Callable[[], datetime],
    connections: Any = None,
    on_progress: Callable[[Progress], None] | None = None,
) -> None:
    global _CURRENT
    # A paused topic's sources wait; a source another active topic also uses is read.
    # Checked before the key: a new kranto home has neither until onboarding, and with
    # nothing to read there is nothing that needs one.
    paused = library.paused_topic_sources(store)
    approved = [s for s in library.list_sources(store, status="approved") if s.id not in paused]
    if not approved:
        report.status, report.error = "skipped", "no approved sources"
        return
    # A muted source waits until its mute ends; it is listed in the run as muted.
    mutes = source_health.mutes(store, now=clock())
    for row in approved:
        if (mutes.get(row.id) or {}).get("muted_until"):
            report.sources.append(SourceReport(row.id, row.label, muted=True))
    approved = [s for s in approved if not (mutes.get(s.id) or {}).get("muted_until")]
    if not approved:
        report.status, report.error = "skipped", "every approved source is muted"
        return

    try:
        llm.check_can_spend()
    except (Paused, BudgetExceeded) as exc:
        report.status, report.error = "skipped", str(exc)
        return
    except FatalLLMError as exc:
        report.status, report.error = "failed", str(exc)
        return

    settings = cfg.ingest
    look_cfg = cfg.look
    repo_stats = RepoStats(http)
    looker = Looker(look_cfg, http, store)
    story_index = stories.Index.load(store, cfg.stories, clock())
    consecutive_transient = 0
    held_errors: list[dict[str, Any]] = []  # item-level errors not yet consumed
    stop: str | None = None

    def flush_held() -> None:
        """A call succeeded, so the endpoint works: consume the held items."""
        for held in held_errors:
            library.mark_seen(store, held.pop("source_id"), held.pop("item_id"),
                              "item_error", run_uuid=report.run_uuid, now=clock(), **held)
        held_errors.clear()

    # Paced and persistently failing sources wait (source_health.fetch_plan); a source
    # paced in this run is fetched once more after the others, when its host has had
    # the time the judging took to recover.
    plans = source_health.fetch_plan(store, cfg, now=clock())
    queue = list(approved)
    reps: dict[int, SourceReport] = {}
    again: set[int] = set()
    progress = _CURRENT = Progress(report.run_uuid, iso(clock()), len(approved))
    finished = 0                    # items of the sources before this one

    def emit() -> None:
        progress.kept = sum(s.contributed for s in report.sources)
        # a mark costs a queue put; the writer keeps the newest (activity.py)
        activity.progress(progress_words(progress), step=progress.source_index,
                          steps=progress.sources)
        if on_progress is not None:
            on_progress(progress)

    for row in queue:
        retrying = row.id in again
        if retrying:
            rep = reps[row.id]
            again.discard(row.id)
        else:
            rep = reps[row.id] = SourceReport(row.id, row.label)
            report.sources.append(rep)
        if not stop and activity.stop_requested():
            stop = "owner"
        if stop:
            rep.not_reached = not retrying
            continue
        progress.source_index = min(len(reps), progress.sources)
        progress.source, progress.items, progress.item = row.label, None, 0
        emit()
        plan = plans.get(row.id) or {}
        if row.kind == "x" and plan.get("wait_until") and plan.get("retry_at") \
                and _x_cap_lifted(cfg, store, row.id, clock()):
            plan = {}               # deferred by the X cap, which was raised or removed since
        if not retrying and plan.get("wait_until"):
            rep.waiting_until = plan["wait_until"]
            rep.failing_runs = plan.get("failing_runs") or 0
            continue
        seen = library.seen_item_ids(store, row.id)
        # First run for this source: backfill once. Once any item is consumed the
        # source has items_seen rows and later runs use the normal cap.
        rep.backfill = not seen
        cap = settings.max_items_per_source
        if rep.backfill:
            cap = max(cap, settings.backfill_items)
        if (mutes.get(row.id) or {}).get("read_less"):
            # "read less": half the cap, the newest items; the rest roll to later runs
            rep.read_less = True
            cap = max(1, cap // 2)
        if row.kind in ("x", "xai_search") and not retrying:
            # X bills every post read: over its cap the source waits for next
            # month, and a search, bookmarks and likes are read once a day
            held = _x_hold(cfg, store, row, clock())
            if held is not None:
                rep.fetch_state, rep.fetch_error, rep.retry_at, rep.waiting_until = held
                if rep.fetch_state == "paced":
                    source_health.record_fetch(store, row.id, trigger="run", state="paced",
                                               fetched=0, new=0, error=rep.fetch_error,
                                               run_uuid=report.run_uuid, now=clock(),
                                               retry_at=rep.retry_at)
                continue
        try:
            with spend.attributed(row.id, report.run_uuid):
                adapter = sources.build(row.kind, row.params, http, connections=connections,
                                        llm=llm)
                if hasattr(adapter, "bind_store"):
                    # a pushed source (the browser's captures): read from the library, no HTTP
                    adapter.bind_store(store, row.id)
                if hasattr(adapter, "fetch_after"):
                    # a paid API: ask for exactly what this run consumes, after the newest
                    # item consumed (X: since_id, max_results)
                    limit = cap if rep.backfill else min(cap, _x_limit(cfg, row.params))
                    items = adapter.fetch_after(None if rep.backfill else _newest_id(seen),
                                                limit, threads=cfg.x.read_threads)
                elif rep.backfill and hasattr(adapter, "fetch_backfill"):
                    items = adapter.fetch_backfill(now=clock())
                else:
                    items = adapter.fetch()
        except Exception as exc:  # any adapter failure belongs to this source alone
            rep.fetch_state, rep.fetch_error = source_health.fetch_state(exc)
            rep.retry_at = source_health.retry_at_of(exc) if rep.fetch_state == "paced" else None
            if rep.fetch_state == "failing":
                rep.failing_runs = (plan.get("failing_runs") or 0) + 1
            source_health.record_fetch(store, row.id, trigger="run", state=rep.fetch_state,
                                       fetched=0, new=0, error=rep.fetch_error,
                                       run_uuid=report.run_uuid, now=clock(),
                                       retry_at=rep.retry_at)
            if rep.fetch_state == "paced" and not retrying:
                again.add(row.id)
                queue.append(row)
            continue
        if retrying:
            rep.retried = True
        rep.fetch_error = rep.retry_at = None
        rep.fetched = len(items)
        # A feed can repeat an id within one fetch; keep the first.
        fresh, batch_ids = [], set()
        for it in items:
            # an edited X post arrives under a new id, its earlier ids in its history: the
            # judgment was on the text then, so it is not judged twice
            earlier = (it.meta.get("x") or {}).get("seen_ids") if isinstance(it.meta, dict) \
                else None
            if earlier and set(earlier) & seen:
                continue
            if it.id not in seen and it.id not in batch_ids:
                batch_ids.add(it.id)
                fresh.append(it)
        # Newest first; the remainder stays unconsumed and is reconsidered next run.
        fresh.sort(key=lambda it: it.published_at.timestamp() if it.published_at else 0.0,
                   reverse=True)
        rep.new = len(fresh)
        rep.fetch_state = "ok"
        source_health.record_fetch(store, row.id, trigger="run", state="ok", fetched=rep.fetched,
                                   new=rep.new, error=None, run_uuid=report.run_uuid,
                                   now=clock())
        batch = fresh[:cap]
        rep.deferred = len(fresh) - len(batch)
        progress.items = len(batch)
        base, finished = finished, finished + len(batch)
        emit()
        if not batch:
            continue

        topics = library.topics_for_source(store, row.id)
        sims = _topic_similarity(embedder, topics, batch)
        # Short posts are screened together: when one reaches the screen, the
        # next ones that will reach it too (short, not hygiene, past the prefilter, not a
        # duplicate) go in the same call, and their verdicts wait here for them.
        batching = look_cfg.enabled and look_cfg.screen_batch > 1 and row.kind in SHORT_POST_KINDS
        prescreened: dict[str, Screen] = {}

        def batchable(it: sources.Item, sim: float | None) -> bool:
            if not short_post(it) or _hygiene(it, settings.max_age_days, clock()) or \
                    sponsors.sponsored_item(it):
                return False
            marked = bool((it.meta.get("x") or {}).get("mine")) or bool(it.meta.get("browser"))
            if not marked and sim is not None and sim < settings.prefilter_min_similarity:
                return False
            return not library.already_judged(store, it.canonical_url())

        for pos, (item, sim) in enumerate(zip(batch, sims, strict=True)):
            if activity.stop_requested():
                stop = "owner"          # the rest of this source's items wait for the next run
                break
            progress.item, progress.done_items = pos, base + pos
            emit()
            raw = item
            canonical = item.canonical_url()
            hygiene = _hygiene(item, settings.max_age_days, clock())
            ad = None if hygiene else sponsors.sponsored_item(item)
            if ad:
                # An ad is a hard no, decided without a model call.
                hygiene = "sponsored"
                _sponsor_reason(rep, f"item {item.id}: {ad}")
            if hygiene:
                library.mark_seen(store, row.id, item.id, hygiene, run_uuid=report.run_uuid,
                                  topic_similarity=sim, canonical_url=canonical, now=clock())
                setattr(rep, hygiene, getattr(rep, hygiene) + 1)
                continue
            read = item.meta.get("browser") if isinstance(item.meta, dict) else None
            if (item.meta.get("x") or {}).get("mine"):
                # the person bookmarked or liked it: their own mark, never prefiltered away,
                # and the judge is told (intern._item_payload)
                admitted_by = "marked"
            elif isinstance(read, dict):
                # the person read it in their browser: Save is their mark, a read on a
                # watched site is "read"; neither is prefiltered away, and the judge is told
                admitted_by = "marked" if read.get("mode") == "save" else "read"
            elif sim is None:
                admitted_by = "no_topics"
            elif sim >= settings.prefilter_min_similarity:
                admitted_by = "topic"
            elif rng.random() < settings.exploration_fraction:
                admitted_by = "exploration"
                rep.explored += 1
            else:
                library.mark_seen(store, row.id, item.id, "prefiltered", run_uuid=report.run_uuid,
                                  topic_similarity=sim, canonical_url=canonical, now=clock())
                rep.prefiltered += 1
                continue

            if library.already_judged(store, canonical):
                library.mark_seen(store, row.id, item.id, "duplicate", run_uuid=report.run_uuid,
                                  topic_similarity=sim, canonical_url=canonical, now=clock())
                rep.duplicates += 1
                continue

            # The item's own text, before enrichment: what the source supplied.
            signature = stories.signature(item)
            story = story_index.match(signature, row.id, item.id, clock())
            if story is not None and story.skip:
                library.mark_seen(store, row.id, item.id, "near_duplicate",
                                  run_uuid=report.run_uuid, topic_similarity=sim,
                                  canonical_url=canonical, now=clock())
                stories.record(store, story_index, source_id=row.id, item_id=item.id,
                               sig=signature, match=story, judged=False,
                               run_uuid=report.run_uuid, now=clock())
                rep.near_duplicates += 1
                continue

            # Judge the item without its comments rather than lose it.
            with contextlib.suppress(Exception):
                item = adapter.enrich(item)
            # A body that is only page chrome or a consent wall is no content: it
            # is blanked, so the full text below is tried, and the judge is told.
            item = blank_no_content(item)
            rep.no_content += int(item.capture_note is not None)
            if settings.fetch_full_text:
                item, replaced = with_full_text(http, row.kind, item)
                rep.full_text += int(replaced)
            with contextlib.suppress(Exception):  # context, never a reason to lose the item
                item = repo_stats.enrich(item)

            topic_texts = [t.description for t in topics]
            screened: Screen | None = None
            looked: Look | None = None
            try:
                if look_cfg.enabled:
                    screened = prescreened.pop(item.id, None)
                    if screened is None and batching and short_post(raw):
                        group = [item] + [
                            it for it, s in zip(batch[pos + 1:], sims[pos + 1:], strict=True)
                            if it.id not in prescreened and batchable(it, s)
                        ][:look_cfg.screen_batch - 1]
                        if len(group) > 1:
                            verdicts = screen_batch(llm, group, source_label=row.label,
                                                    topics=topic_texts, run_uuid=report.run_uuid)
                            screened = verdicts[0]
                            prescreened.update({it.id: v for it, v in
                                                zip(group[1:], verdicts[1:], strict=True)})
                    if screened is None:
                        screened = screen(llm, item, source_label=row.label,
                                          topics=topic_texts, run_uuid=report.run_uuid)
                    rep.screened += 1
                    consecutive_transient = 0
                    flush_held()
                if screened is None or screened.passed:
                    if look_cfg.enabled and row.kind in GATHER_KINDS:
                        looked = looker.look(row.kind, row.params, item)
                        if looked is None:
                            rep.look_capped += 1
                        else:
                            rep.looked += 1
                            rep.gathered += len(looked.gathered)
                            rep.gather_requests += looked.requests
                            rep.sponsor_links += len(looked.sponsored)
                            for url, why in looked.sponsored.items():
                                _sponsor_reason(rep, f"link {url[:120]}: {why}")
                    verdict = judge(
                        llm, item, source_label=row.label, topics=topic_texts,
                        threshold=settings.signal_threshold, run_uuid=report.run_uuid,
                        gathered=looked.gathered if looked else None,
                        gathered_chars=look_cfg.gathered_chars,
                    )
            except (FatalLLMError, UnpricedModel) as exc:
                rep.llm_errors += 1
                report.status, report.error = "failed", str(exc)
                stop = "fatal"
                break
            except (Paused, BudgetExceeded) as exc:
                report.error = str(exc)
                stop = "halted"
                break
            except TransientLLMError as exc:
                # an empty reply too (EmptyReply): the item waits for the next run, counted
                rep.llm_errors += 1
                rep.empty_replies += int(isinstance(exc, EmptyReply))
                consecutive_transient += 1
                if consecutive_transient >= MAX_CONSECUTIVE_TRANSIENT:
                    report.error = f"stopping after {consecutive_transient} transient errors: {exc}"
                    stop = "transient"
                    break
                continue
            except RefusedReply as exc:
                # declined by the model or a safety filter: the same text meets the same filter
                # next run, so the item is consumed with its call (which holds the words), and
                # the endpoint works, so it never counts toward stopping the run
                rep.item_errors += 1
                rep.refused += 1
                library.mark_seen(store, row.id, item.id, "item_error", run_uuid=report.run_uuid,
                                  llm_call_id=exc.call_id, topic_similarity=sim,
                                  canonical_url=canonical, now=clock())
                continue
            except LLMError as exc:
                rep.item_errors += 1
                held_errors.append({
                    "source_id": row.id, "item_id": item.id, "llm_call_id": exc.call_id,
                    "topic_similarity": sim, "canonical_url": canonical})
                if len(held_errors) >= MAX_CONSECUTIVE_ITEM_ERRORS:
                    report.status = "failed"
                    report.error = (f"stopping after {len(held_errors)} consecutive model "
                                    f"errors on different items (none consumed): {exc}")
                    stop = "fatal"
                    break
                continue
            consecutive_transient = 0
            flush_held()
            screen_call = screened.completion.call_id if screened else None

            if screened is not None and not screened.passed:
                # Dropped by the screen: consumed with its call, which holds the reason.
                library.mark_seen(store, row.id, item.id, "screened_out",
                                  run_uuid=report.run_uuid, llm_call_id=screen_call,
                                  screen_call_id=screen_call, topic_similarity=sim,
                                  canonical_url=canonical, now=clock())
                rep.screened_out += 1
                rep.screened_spam += int(screened.reason.lower().startswith("spam"))
                stories.record(store, story_index, source_id=row.id, item_id=item.id,
                               sig=signature, match=story, judged=True,
                               run_uuid=report.run_uuid, now=clock())
                rep.linked += int(story is not None)
                continue
            rep.judged += 1
            if verdict.fields is not None:
                rep.rated += 1
                effect = override_effect(verdict.fields, settings.signal_threshold)
                rep.override_set += int(effect is not None)
                rep.override_lifted += int(effect == "lifted")
                rep.override_refused += int(effect == "refused")

            if verdict.outcome == "contributed":
                assert verdict.fields is not None      # a kept item's verdict has its fields
                gathered = looked.gathered if looked is not None else []
                kept = [c for c in verdict.children if c.outcome == "contributed"]
                rep.children_gated += len(verdict.children) - len(kept)
                vecs = embedder.embed_documents(
                    [library.observation_embed_text(verdict.fields)]
                    + [library.observation_embed_text(c.fields) for c in kept])
                children = [
                    library.Child(gathered[c.ref - 1].item, c.fields, vec,
                                  gathered[c.ref - 1].relation)
                    for c, vec in zip(kept, vecs[1:], strict=True)]
                library.record_observation(
                    store, source_id=row.id, item=item, fields=verdict.fields, embedding=vecs[0],
                    embedding_model=embedder.model_name, llm_call_id=verdict.completion.call_id,
                    prompt_version=_prompt_version(store, verdict.completion.call_id),
                    run_uuid=report.run_uuid, admitted_by=admitted_by, topic_similarity=sim,
                    now=clock(), screen_call_id=screen_call, children=children,
                )
                rep.contributed += 1
                rep.children += len(children)
            else:
                library.mark_seen(store, row.id, item.id, verdict.outcome,
                                  run_uuid=report.run_uuid,
                                  llm_call_id=verdict.completion.call_id,
                                  screen_call_id=screen_call,
                                  topic_similarity=sim, canonical_url=canonical, now=clock())
                setattr(rep, verdict.outcome, getattr(rep, verdict.outcome) + 1)
            if verdict.outcome in library.JUDGED_OUTCOMES:
                # A reply that did not parse is not a reading of the text: no
                # signature, so a later copy is judged rather than skipped.
                stories.record(store, story_index, source_id=row.id, item_id=item.id,
                               sig=signature, match=story, judged=True,
                               run_uuid=report.run_uuid, now=clock())
                rep.linked += int(story is not None)

    if report.status == "failed":
        return
    if stop == "owner":
        # skipped, so the read is due again at its re-check, not lost
        done = sum(1 for s in report.sources if s.fetched or s.fetch_state)
        report.status = "skipped"
        report.error = (f"stopped by you after source {done} of {len(report.sources)}; "
                        "the rest at the next read")
        return
    # Paced is not a failure (the owner's ruling, 2026-10-09): only a source that fails
    # persistently, or needs its account connected again, marks the run degraded.
    # Every source failing is still an outage (the network, DNS), unless every one of
    # them was only throttled (paced with a time to retry at).
    unfetched = [s for s in report.sources if s.fetch_error]
    throttled = [s for s in unfetched if s.fetch_state == "paced" and s.retry_at]
    failed = [s for s in report.sources if s.fetch_state in ("failing", "needs_login")]
    persistent = [s for s in failed if s.fetch_state == "needs_login"
                  or s.failing_runs >= cfg.fetch.failing_after_runs]
    if unfetched and len(unfetched) == len(report.sources) and len(throttled) < len(unfetched):
        report.status = "failed"
        report.error = report.error or "every source failed to fetch"
    elif stop or persistent or any(s.llm_errors or s.item_errors for s in report.sources):
        report.status = "degraded"


# What a feed shows for a post its author or a moderator took down.
REMOVED_BODIES = frozenset({"[removed]", "[deleted]", "[removed by moderator]",
                            "[deleted by user]"})


def _hygiene(item: sources.Item, max_age_days: float, now: datetime) -> str | None:
    """'removed' or 'stale' for an item that should never reach the judge.

    Deterministic and free: a post taken down by its author or a moderator, or one
    published longer ago than ``max_age_days``, is not news, whatever the judge
    would make of it."""
    body = " ".join((item.body or "").split()).lower()
    if body in REMOVED_BODIES or item.title.strip().lower() in REMOVED_BODIES:
        return "removed"
    # a page the person read in their browser is as new as the read, whatever its date: an
    # old thread they open today is today's reading
    browser_read = isinstance(item.meta, dict) and isinstance(item.meta.get("browser"), dict)
    if max_age_days and item.published_at is not None and not browser_read \
            and (now - item.published_at).total_seconds() > max_age_days * 86400:
        return "stale"
    return None


def _newest_id(seen: set[str]) -> str | None:
    """The largest numeric id consumed (X's ids are time-ordered), or None."""
    ids = [int(i) for i in seen if i.isdigit()]
    return str(max(ids)) if ids else None


def _x_limit(cfg: Config, params: dict[str, Any]) -> int:
    from .sources.x import limit_for

    return limit_for(params, cfg.x)


def _x_hold(cfg: Config, store: Store, row: library.SourceRow,
            now: datetime) -> tuple[str | None, str | None, str | None, str | None] | None:
    """Why an X source is not fetched this run, as (state, error, retry_at, waiting_until):
    over the month's cap (paced until the first of next month), or a search, bookmarks or
    likes read less than their cadence ago (waiting, no fetch). None: fetch it."""
    from datetime import timedelta

    from .sources.x import cadence_hours

    # X through Grok is a model call: the watcher's budget holds it, not the X cap
    capped = spend.capped(store, cfg.x.monthly_usd, now=now) if row.kind == "x" else None
    if capped is not None:
        when, why = capped
        return "paced", why, iso(when), None
    hours = cadence_hours(row.params if row.kind == "x" else {"what": "search"}, cfg.x)
    if hours <= 0:
        return None
    last = store.query_one("SELECT created_at FROM source_fetches WHERE source_id = ? AND "
                           "trigger = 'run' AND state = 'ok' ORDER BY id DESC LIMIT 1",
                           (row.id,))
    if last is None:
        return None
    until = datetime.fromisoformat(last["created_at"].replace("Z", "+00:00")) \
        + timedelta(hours=hours)
    return (None, None, None, iso(until)) if until > now else None


def _x_cap_lifted(cfg: Config, store: Store, source_id: int, now: datetime) -> bool:
    """Whether an X source's last fetch was deferred by the cap and the cap no longer holds."""
    last = store.query_one("SELECT state, error FROM source_fetches WHERE source_id = ? "
                           "ORDER BY id DESC LIMIT 1", (source_id,))
    return last is not None and last["state"] == "paced" \
        and str(last["error"] or "").startswith("X cap reached") \
        and spend.capped(store, cfg.x.monthly_usd, now=now) is None


def _sponsor_reason(rep: SourceReport, line: str) -> None:
    if len(rep.sponsor_reasons) < MAX_SPONSOR_REASONS:
        rep.sponsor_reasons.append(line[:240])


def _prompt_version(store: Store, call_id: int) -> str:
    row = store.query_one("SELECT prompt_version FROM llm_calls WHERE id = ?", (call_id,))
    return row["prompt_version"] if row else "unknown"


def _topic_similarity(
    embedder: Embedder, topics: list[library.Topic], items: list[sources.Item]
) -> list[float | None]:
    if not topics:
        return [None] * len(items)
    item_vecs = embedder.embed_documents([it.text_for_prefilter() for it in items])
    topic_vecs = np.stack([t.embedding for t in topics])
    return [float(x) for x in (item_vecs @ topic_vecs.T).max(axis=1)]
