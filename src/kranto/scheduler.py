"""In-process scheduler for ``python -m kranto serve``.

Due-ness is computed from the ``runs`` table, not from process uptime, so a
restart neither skips a run nor starts a duplicate one. A job that raises
instead of recording a run (for example, a database that cannot be written)
would stay due forever; it is retried with a growing backoff, from
``FIRST_BACKOFF`` doubling up to the job's own interval, rather than every
tick. Every job runs inside one ``activity.run``: a ``started`` mark when it begins,
an ``ended`` mark when it is over, so what runs shows while it runs. Jobs
take the same
file locks as the CLI, so a cron-driven ``python -m kranto run`` and the server can
coexist.

A scheduler may also carry **lanes**: something that ticks on its own short
interval, on its own thread, started and stopped with the job thread. ``kranto
serve`` ran the page's build loop as one until builds left Kranto (CUT); it runs
none today, and the seam stays for the next thing that needs its own pace.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from . import activity
from .memory import release as release_memory
from .store import Store, iso, utcnow

log = logging.getLogger("kranto.scheduler")

FIRST_BACKOFF = timedelta(minutes=5)
# A skipped run (nothing to do: an unchanged map, a refused idea run) does not
# reset a job's interval, so new data is picked up soon; it defers the next
# attempt by this much, or by the interval if shorter. Without it a job
# that keeps skipping ran, and recorded a row, on every tick.
SKIP_RECHECK = timedelta(hours=1)
# Jobs that follow another: right after a run of the job on the left that was a run
# (a row: not a scheduled skip), each job on the right is due in the same round, whatever its
# interval. News' job writes a topic's first brief the moment its first read ends; the ideas
# job reads a map the moment one is drawn, so the first cards come the night 30 items are kept
# rather than on the ideas job's own day. A follower that finds nothing to do skips, as any
# job does (no row). Its backoff after a failure still holds.
FOLLOWS: dict[str, tuple[str, ...]] = {"ingest": ("news.brief",), "snapshot": ("ideas",)}
# After a pressed run (Welcome's finish starts the first read; Run now), only these lead their
# followers: a pressed read is followed by News' first brief, but the map page's "Map now" is the
# map alone (the cards it would start are a spend nobody pressed for).
PRESS_LEADS = ("ingest",)
# How long ``stop`` waits, in all, for a running job and the lanes' ticks. The server's stop
# passes what is left of its own budget instead (stopping.py, 10 s from SIGTERM to exit).
STOP_WAIT_SECONDS = 60.0


@dataclass
class Job:
    kind: str  # the runs.kind this job records
    every_hours: float
    run: Callable[[], object]


class Lane(Protocol):
    """A second scheduler lane. ``run`` is the thread body and returns once ``stop`` is
    set; ``request_stop`` asks a tick in progress to end early; ``status`` is what
    Health and ``kranto status`` show."""

    name: str

    def run(self, stop: threading.Event) -> None: ...

    def request_stop(self) -> None: ...

    def status(self) -> dict: ...


def _count_error(exc: BaseException, where: str, job: str | None = None) -> None:
    """The error in the usage counters and, with consent, an error report (telemetry)."""
    from .telemetry.timing import record_error

    record_error(exc, where, job=job)


def _latest(store: Store, kind: str, skipped: bool) -> datetime | None:
    if skipped:
        # a skip is not a row: the store keeps this process's last one; an
        # older row (from before, or the update check's) counts too
        noted = store.skipped_at(kind) if hasattr(store, "skipped_at") else None
        row = _latest_row(store, kind, True)
        return max((t for t in (noted, row) if t is not None), default=None)
    return _latest_row(store, kind, False)


def _latest_row(store: Store, kind: str, skipped: bool) -> datetime | None:
    op = "=" if skipped else "!="
    row = store.query_one(
        f"SELECT MAX(finished_at) AS t FROM runs WHERE kind = ? AND status {op} 'skipped'", (kind,)
    )
    if not row or not row["t"]:
        return None
    return datetime.fromisoformat(row["t"].replace("Z", "+00:00"))


def last_finished(store: Store, kind: str) -> datetime | None:
    return _latest(store, kind, skipped=False)


def is_due(store: Store, job: Job, now: datetime) -> bool:
    if job.every_hours <= 0:
        return False
    own = getattr(job, "due", None)          # a cub's job at a time of day (its at and days)
    if own is not None:
        got = own(store, now)
        if got is not None:
            return got
    interval = timedelta(hours=job.every_hours)
    last = last_finished(store, job.kind)
    if last is not None and now - last < interval:
        return False
    skipped = _latest(store, job.kind, skipped=True)
    if skipped is not None and (last is None or skipped > last):
        return now - skipped >= min(interval, SKIP_RECHECK)
    return True


def next_due(store: Store, job: Job, now: datetime) -> datetime | None:
    """When ``is_due`` next turns true for ``job`` (``now`` if it already is); None for a
    job that is off. What the header's "next read" says."""
    if job.every_hours <= 0:
        return None
    own = getattr(job, "next_at", None)
    if own is not None:
        got = own(store, now)
        if got is not None:
            return max(got, now)
    interval = timedelta(hours=job.every_hours)
    last = last_finished(store, job.kind)
    at = last + interval if last is not None else now
    skipped = _latest(store, job.kind, skipped=True)
    if skipped is not None and (last is None or skipped > last):
        at = max(at, skipped + min(interval, SKIP_RECHECK))
    return max(at, now)


class Scheduler:
    def __init__(
        self,
        store: Store,
        jobs: list[Job],
        *,
        tick_seconds: float = 60.0,
        clock: Callable[[], datetime] = utcnow,
        lanes: list[Lane] | None = None,
        ticks: list[Callable[[], object]] | None = None,
        job_source: Callable[[], list] | None = None,
    ) -> None:
        self.store = store
        self._jobs = jobs
        # jobs that come and go while Kranto runs (an installed cub's): read every tick
        self.job_source = job_source
        self.tick_seconds = tick_seconds
        self.clock = clock
        self.lanes: list[Lane] = list(lanes or [])
        # run after every round of jobs (the event bus's delivery,); one that
        # raises is logged and the next tick runs it again
        self.ticks: list[Callable[[], object]] = list(ticks or [])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lane_threads: list[threading.Thread] = []
        self._busy = threading.Lock()
        self._retry_at: dict[str, datetime] = {}
        self._backoff: dict[str, timedelta] = {}
        self.running: str | None = None  # the kind of the job running now, if any
        # The update's drain (section 4.2): while set, no job starts and each
        # lane is held. In memory only: a helper that dies leaves the server working normally
        # once it restarts or the hold is released.
        self.hold: dict | None = None

    @property
    def jobs(self) -> list:
        if self.job_source is None:
            return self._jobs
        try:
            extra = list(self.job_source())
        except Exception:  # noqa: BLE001 - a broken source must not stop Kranto's own jobs
            log.exception("the scheduler's job source raised")
            extra = []
        return self._jobs + extra

    @jobs.setter
    def jobs(self, value: list) -> None:
        self._jobs = value

    def set_hold(self, reason: str, *, stop_builds: bool = False) -> dict:
        """Start no job; hold every lane (the loop lane's tick then watches and publishes
        only). ``stop_builds``: also stop the running builds (their rounds resume after the
        restart). Returns the hold, with what was stopped."""
        self.hold = {"reason": reason, "since": iso(self.clock()), "stopped": []}
        for lane in self.lanes:
            if hasattr(lane, "hold"):
                lane.hold = reason
            if stop_builds and hasattr(lane, "stop_builds"):
                try:
                    self.hold["stopped"] += lane.stop_builds()
                except Exception:  # noqa: BLE001 - reported as nothing stopped
                    log.exception("lane %s: stop_builds raised", lane.name)
        log.warning("hold: %s%s", reason, " (builds stopped)" if stop_builds else "")
        return self.hold

    def release_hold(self) -> bool:
        """End the hold. False if there was none."""
        had = self.hold is not None
        self.hold = None
        for lane in self.lanes:
            if hasattr(lane, "hold"):
                lane.hold = None
        if had:
            log.warning("hold released")
        return had

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="afk-scheduler", daemon=True)
            self._thread.start()
            for lane in self.lanes:
                t = threading.Thread(target=self._run_lane, args=(lane,),
                                     name=f"afk-lane-{lane.name}", daemon=True)
                t.start()
                self._lane_threads.append(t)

    def request_stop(self) -> None:
        """Start no job from now on, and ask each lane's tick in progress to start no long
        step. Returns at once: the server's stop calls it at SIGTERM (``stopping.py``), so
        the job and the ticks wind down while open requests drain."""
        if self._stop.is_set():
            return
        self._stop.set()
        for lane in self.lanes:
            try:
                lane.request_stop()
            except Exception:  # a lane that cannot be asked still gets joined
                log.exception("lane %s: request_stop raised", lane.name)

    def still_running(self) -> list[str]:
        """What a stop would cut off now: the running job, each lane still ticking."""
        out = [f"the {self.running or 'scheduler'} job"] if self._busy.locked() else []
        out += [f"the {t.name.removeprefix('afk-lane-')} lane's tick"
                for t in self._lane_threads if t.is_alive()]
        return out

    def stop(self, timeout: float = STOP_WAIT_SECONDS) -> bool:
        """Stop scheduling and wait for a running job, and each lane's tick, to finish: at
        most ``timeout`` seconds **in all**. Each wait used to take the full ``timeout`` in
        turn, so a stop during an ingest could wait 180 s and be killed by systemd with nothing
        logged (the 0.4.8 server on the 0.4.9 update). Returns False if one was still running
        at the end; its work is not lost (runs are recorded as they end, so an interrupted job
        is still due at the next start, and watch matches are recovered by the next run, #44).
        Every thread here is a daemon, so the process still exits."""
        running = self._busy.locked()
        log.warning("stopping: %s; waiting at most %.1fs",
                    f"the {self.running or 'scheduler'} job is running" if running
                    else "no job running", timeout)
        self.request_stop()
        clean = self.wait(timeout)
        for what in self.still_running():
            log.warning("stopping: %s still running after %.1fs", what, timeout)
        return clean

    def wait(self, timeout: float) -> bool:
        """Wait, ``timeout`` seconds in all, for the scheduler's thread, each lane's and a
        running job to end. True when all of them did."""
        deadline = time.monotonic() + timeout

        def left() -> float:
            return max(0.0, deadline - time.monotonic())

        if self._thread is not None:
            self._thread.join(timeout=left())
        for t in self._lane_threads:
            t.join(timeout=left())
        if not self._busy.acquire(timeout=left()):
            return False
        self._busy.release()
        return not any(t.is_alive() for t in self._lane_threads)

    def _run_lane(self, lane: Lane) -> None:
        try:
            lane.run(self._stop)
        except Exception as exc:  # a lane that dies must not take the server with it
            log.exception("lane %s stopped with an error", lane.name)
            _count_error(exc, "loop", "loop")

    def lane_status(self) -> dict[str, dict]:
        out = {}
        for lane in self.lanes:
            try:
                out[lane.name] = lane.status()
            except Exception as exc:  # the status is for a page; it must not raise
                out[lane.name] = {"state": "error", "error": f"{type(exc).__name__}: {exc}"}
        return out

    def run_due(self) -> list[str]:
        """Run every due job once, in order, and each job that follows one that ran
        (``FOLLOWS``). Returns the kinds that ran."""
        ran: list[str] = []
        if self.hold is not None or not self._busy.acquire(blocking=False):
            return ran
        try:
            followed: set[str] = set()     # kinds that follow a run of this round
            for job in self.jobs:
                if self._stop.is_set():
                    break
                now = self.clock()
                if job.kind in self._retry_at and now < self._retry_at[job.kind]:
                    continue
                follows = job.kind in followed and job.every_hours > 0
                if follows or is_due(self.store, job, now):
                    log.info("running %s (%s)", job.kind,
                             "after the job it follows" if follows and not
                             is_due(self.store, job, now) else f"due at {iso(now)}")
                    if self._run_one(job):
                        followed.update(FOLLOWS.get(job.kind, ()))
                    ran.append(job.kind)
        finally:
            self._busy.release()
        return ran

    def _run_one(self, job, origin: str = "schedule", by: str | None = None) -> bool:
        """Run one job under its activity run, with its backoff on a failure. True when it
        was a run (it wrote a runs row: not a skip), which is what its followers wait for."""
        before = _latest_row(self.store, job.kind, False)
        self.running = job.kind
        try:
            with activity.run(self.store, job.kind, origin=origin, by=by):
                job.run()
        except Exception as exc:  # a failing job must not kill the scheduler
            log.exception("%s job raised", job.kind)
            _count_error(exc, "scheduler", job.kind)
            self._back_off(job)
        else:
            self._retry_at.pop(job.kind, None)
            self._backoff.pop(job.kind, None)
        finally:
            self.running = None
            release_memory()
        after = _latest_row(self.store, job.kind, False)
        return after is not None and (before is None or after > before)

    def _run_followers(self, kind: str) -> None:
        """After a pressed run of ``kind`` (``trigger``), the jobs that follow it, in order:
        what ``run_due`` does for a scheduled one. Called with the busy lock held."""
        want = FOLLOWS.get(kind, ())
        for job in self.jobs:
            if self._stop.is_set() or self.hold is not None:
                return
            if job.kind not in want or job.every_hours <= 0:
                continue
            if job.kind in self._retry_at and self.clock() < self._retry_at[job.kind]:
                continue
            if self._run_one(job):
                self._run_followers(job.kind)

    def _back_off(self, job: Job) -> None:
        cap = timedelta(hours=job.every_hours)
        delay = min(self._backoff.get(job.kind, FIRST_BACKOFF / 2) * 2, cap)
        self._backoff[job.kind] = delay
        self._retry_at[job.kind] = self.clock() + delay
        log.warning("%s will be retried after %s", job.kind, iso(self._retry_at[job.kind]))

    def why_not(self, kind: str) -> str | None:
        """Why ``trigger(kind)`` would not start it now, in words; None when it would."""
        from .activity import words as W
        if not any(j.kind == kind for j in self.jobs):
            return f"Kranto has no job {kind}"
        if self.hold is not None:
            return f"Kranto is holding every job ({self.hold.get('reason') or 'held'})"
        if self._stop.is_set():
            return "Kranto is stopping"
        if self.running or self._busy.locked():
            what = W.title_of(self.running, "running") if self.running else "another job"
            return f"{what} is running, and Kranto runs one job at a time"
        return None

    def trigger(self, kind: str, *, origin: str = "press", by: str | None = None) -> bool:
        """Run one job now in a background thread. False if something is already running.
        ``origin``/``by``: who asked (the run's trigger: "you pressed Run ingest now")."""
        job = next((j for j in self.jobs if j.kind == kind), None)
        if job is None or self.hold is not None or self._stop.is_set() \
                or not self._busy.acquire(blocking=False):
            return False

        def work():
            self.running = kind
            ran = False
            try:
                before = _latest_row(self.store, kind, False)
                with activity.run(self.store, kind, origin=origin, by=by):
                    job.run()
                after = _latest_row(self.store, kind, False)
                ran = after is not None and (before is None or after > before)
            except Exception as exc:
                log.exception("%s job raised", kind)
                _count_error(exc, "scheduler", kind)
            finally:
                self.running = None
                release_memory()
            try:
                # the first read pressed by Welcome's finish, or Run now: what follows it runs
                # now too (FOLLOWS), as after a scheduled run
                if ran and kind in PRESS_LEADS:
                    self._run_followers(kind)
            except Exception as exc:  # noqa: BLE001 - logged; the next round tries again
                log.exception("the jobs after %s raised", kind)
                _count_error(exc, "scheduler", kind)
            finally:
                self._busy.release()

        threading.Thread(target=work, name=f"afk-{kind}", daemon=True).start()
        return True

    def next_runs(self) -> dict[str, str | None]:
        """Each job's next due time (ISO), counting a backoff after a failure. A job that is
        off (its feature off, or every_hours 0) has no row."""
        now = self.clock()
        out: dict[str, str | None] = {}
        for job in self.jobs:
            if job.every_hours <= 0:
                continue
            at = next_due(self.store, job, now)
            if at is not None and job.kind in self._retry_at:
                at = max(at, self._retry_at[job.kind])
            out[job.kind] = iso(at) if at is not None else None
        return out

    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def run_ticks(self) -> None:
        if self.hold is not None:
            return
        for fn in self.ticks:
            try:
                fn()
            except Exception as exc:  # a failing delivery must not kill the scheduler
                log.exception("a tick hook raised")
                _count_error(exc, "scheduler")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.run_due()
            self.run_ticks()
            self._stop.wait(self.tick_seconds)
