"""The server's stop (STOP): from SIGTERM to exit within ``STOP_BUDGET_S``, nothing orphaned.

``kranto.service`` is ``KillMode=process``: systemd signals the server alone and kills it at the
unit's ``TimeoutStopSec``, so the server itself must end on time and end its own children.
The 0.4.9 update's warning ("did not stop on SIGTERM: systemd killed it after 91 s") was the
scheduler waiting 60 s for a running ingest, then 60 s for each lane, then 60 s again; a
child ``claude -p`` would have outlived it.

The order, all inside one budget measured from the signal:

1. at SIGTERM (``begin``, from the server's signal handler): the scheduler and its lanes are
   told at once (no job or long step starts; a running one sees the stop), and a watchdog
   thread is started;
2. open requests get ``HTTP_GRACE_S`` (uvicorn's graceful shutdown), then are cancelled;
3. the cub host ends its processes and their ``kranto-cub-*`` scopes (``CUBS_S`` at most);
4. the scheduler's job and each lane's tick get what is left, less ``CHILDREN_S``;
5. the server's own children are ended (``end_children``): SIGTERM, SIGKILL what is left after
   their grace. Detached jobs (builds, fixes, pre-push checks: the page's ``detached_jobs``)
   are left running, as before: the next start adopts them;
6. the process exits. Whatever still runs then is cut off and resumes after the start: a job
   records its run only when it ends, so an interrupted one is still due; a loop tick's steps
   are the daemon's, built to be cut at SIGTERM; a terminal session is ended just before step
   5 with "ended: restart" written on its record first (``end_terminals``), and Open resumes
   it.

The watchdog ends the process at ``HARD_EXIT_S`` whatever is left (its children SIGKILLed
first), so a stop never needs systemd's kill; the unit's ``TimeoutStopSec`` (``UNIT_STOP_S``)
is only the last resort. Each stop logs one ``stop:`` line that ``kranto update`` reports."""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import threading
import time
from collections.abc import Callable, Iterable

log = logging.getLogger("kranto.stop")

STOP_BUDGET_S = 10.0     # SIGTERM to exit
HTTP_GRACE_S = 3         # open requests (a live feed, a terminal's socket never end by themselves)
CUBS_S = 4.0             # the cub host's processes and scopes
CHILDREN_S = 2.0         # the server's children, from SIGTERM to SIGKILL
ACTIVITY_S = 0.5         # the activity writer's last batch
HARD_EXIT_S = 12.0       # the watchdog
UNIT_STOP_S = 15         # kranto.service's TimeoutStopSec: systemd's kill, never reached


class Stop:
    """One server's stop: when it began, what is left of the budget, and the watchdog."""

    def __init__(self, budget_s: float = STOP_BUDGET_S, hard_exit_s: float | None = HARD_EXIT_S,
                 clock: Callable[[], float] = time.monotonic,
                 exit: Callable[[int], None] = os._exit, own_children: bool = True) -> None:
        """``hard_exit_s`` None: no watchdog. ``own_children`` False: this process's children
        are not the server's to end (an app in a test, inside pytest's process)."""
        self.budget_s, self.hard_exit_s = budget_s, hard_exit_s
        self.clock, self._exit = clock, exit
        self.own_children = own_children
        self.began: float | None = None
        self.phase = "running"
        self.on_begin: list[Callable[[], object]] = []
        self.keep: Callable[[], Iterable[int] | None] = detached_jobs
        self.root: int | None = None      # whose children are ended (None: this process's)
        self._mu = threading.Lock()
        self.done = threading.Event()

    def begin(self, why: str = "SIGTERM") -> bool:
        """Start the stop (once): tell ``on_begin``'s hooks, start the watchdog. False when it
        had begun already."""
        with self._mu:
            if self.began is not None:
                return False
            self.began = self.clock()
        log.warning("stop: %s; ending within %.0f s", why, self.budget_s)
        for fn in self.on_begin:
            try:
                fn()
            except Exception:  # noqa: BLE001 - a hook that raises must not hold the stop
                log.exception("stop: a hook raised")
        if self.hard_exit_s is not None:
            threading.Thread(target=self._watchdog, name="kranto-stop-watchdog",
                             daemon=True).start()
        return True

    def elapsed(self) -> float:
        return 0.0 if self.began is None else self.clock() - self.began

    def left(self, reserve: float = 0.0) -> float:
        """Seconds of the budget left, less ``reserve`` (never below 0)."""
        if self.began is None:
            self.begin("shutdown")
        return max(0.0, self.budget_s - self.elapsed() - reserve)

    def finished(self, still: list[str]) -> None:
        """The stop's line: clean, or what was still running when the process exits."""
        took = self.elapsed()
        if still:
            log.warning("stop: done in %.1f s; cut off (resumes after the start): %s",
                        took, "; ".join(still))
        else:
            log.warning("stop: done in %.1f s, clean", took)
        self.done.set()

    def _watchdog(self) -> None:
        wait = self.hard_exit_s - self.elapsed()
        if self.done.wait(max(0.0, wait)):
            return
        alive = sorted(t.name for t in threading.enumerate()
                       if t is not threading.current_thread() and t.is_alive())
        log.error("stop: forced exit after %.1f s (phase: %s); threads: %s",
                  self.elapsed(), self.phase, ", ".join(alive)[:600])
        self.end_children(0.0)
        logging.shutdown()
        self._exit(0)

    def end_children(self, grace_s: float = CHILDREN_S) -> list[dict]:
        """``end_children`` with this stop's ``keep`` (the detached jobs)."""
        if not self.own_children:
            return []
        try:
            keep = self.keep()
        except Exception:  # noqa: BLE001 - unknown: every session leader is kept
            log.exception("stop: the detached jobs could not be read")
            keep = None
        return end_children(grace_s, keep=keep, root=self.root)


def stop_server(stop: Stop, cubs=None, scheduler=None) -> list[str]:
    """Steps 3 to 6, at the end of the app's lifespan (after the open requests): the cub host,
    the scheduler's job and lanes, then the server's children, within what is left of the
    budget. Returns what was cut off; logs the stop's line."""
    still: list[str] = []
    try:
        if cubs is not None:
            stop.phase = "cubs"
            try:
                left = cubs.stop_all("host", budget_s=min(CUBS_S, stop.left(CHILDREN_S)))
                still += [f"cub {c}" for c in left or []]
            except Exception:  # noqa: BLE001 - the scheduler and the children still stop
                log.exception("stop: the cub host's stop raised")
        if scheduler is not None:
            stop.phase = "scheduler"
            scheduler.stop(timeout=stop.left(CHILDREN_S))
        stop.phase = "activity"
        try:
            # the marks the runs wrote as they went, committed (activity.py's one writer)
            from . import activity
            activity.flush(timeout=min(ACTIVITY_S, stop.left(CHILDREN_S)))
        except Exception:  # noqa: BLE001 - marks are what is lost, never the stop
            log.exception("stop: the activity writer's flush raised")
        stop.phase = "terminals"
        try:
            end_terminals()
        except Exception:  # noqa: BLE001 - the children still end; the next start marks them
            log.exception("stop: ending the terminal sessions raised")
        stop.phase = "children"
        ended = stop.end_children(min(CHILDREN_S, stop.left()))
        if ended:
            names = sorted({_name(p["pid"]) or "?" for p in ended})
            still.append(f"{len(ended)} child process{'es' if len(ended) != 1 else ''} "
                         f"({', '.join(names)[:120]})")
        if scheduler is not None:
            # a tick or a job that waited on a child just ended returns now
            scheduler.wait(timeout=min(0.5, stop.left()))
            still += scheduler.still_running()
    finally:
        stop.phase = "exiting"
        stop.finished(still)
    return still


def _name(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        return None


def end_terminals() -> list[str]:
    """the page's open Claude Code sessions, each ended with "restart" written on its record
    before its program is signalled; [] without the page, or with one from before it said so
    (its next start then marks them, as before)."""
    import importlib.util

    if importlib.util.find_spec("kranto.page") is None:
        return []
    try:
        from kranto.page.host_api import term_shutdown
    except (ImportError, AttributeError):
        return []
    return list(term_shutdown("restart"))


def detached_jobs() -> list[int] | None:
    """the page's detached jobs (whatever it starts in a session of its own: reapers, and on
    a the page from before the cut its builds), which a stop leaves running; [] without
    the page (``afk serve`` starts none); None when the page cannot say (one from before
    STOP): then every child leading a session of its own is kept."""
    import importlib.util

    if importlib.util.find_spec("kranto.page") is None:
        return []
    try:
        from kranto.page.host_api import detached_jobs as jobs
    except (ImportError, AttributeError):
        return None
    return list(jobs())


# -- the server's children -----------------------------------------------------------------

def _stat(pid: int) -> tuple[int, int, int, str, int] | None:
    """``(ppid, pgid, start time, state, session)`` from ``/proc/<pid>/stat``, or None."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            rest = fh.read().rsplit(")", 1)[1].split()
        return int(rest[1]), int(rest[2]), int(rest[19]), rest[0], int(rest[3])
    except (OSError, ValueError, IndexError):
        return None


def children(root: int | None = None, keep: Iterable[int] | None = ()) -> list[dict]:
    """Every live process descended from ``root`` (this process), each ``{"pid", "pgid",
    "start"}``, without the subtrees of ``keep`` (detached jobs, which outlive the server).
    ``keep`` None: the jobs are not known, so every child that leads a session of its own is
    kept (each detached job does; so do a terminal and a stoppable ``claude -p``)."""
    root = os.getpid() if root is None else root
    procs: dict[int, tuple[int, int, int, str, int]] = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            st = _stat(int(d))
            if st is not None and st[3] != "Z":
                procs[int(d)] = st
    kids: dict[int, list[int]] = {}
    for p, st in procs.items():
        kids.setdefault(st[0], []).append(p)
    kept = set(keep) if keep is not None else {p for p in kids.get(root, [])
                                               if procs[p][4] == p}
    out, todo = [], list(kids.get(root, []))
    while todo:
        p = todo.pop()
        if p in kept or p not in procs:
            continue
        out.append({"pid": p, "pgid": procs[p][1], "start": procs[p][2]})
        todo += kids.get(p, [])
    return out


def _same(p: dict) -> bool:
    st = _stat(p["pid"])
    return st is not None and st[2] == p["start"] and st[3] != "Z"


def _signal(procs: list[dict], sig: int) -> None:
    for p in procs:
        if _same(p):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(p["pid"], sig)


def end_children(grace_s: float = CHILDREN_S, keep: Iterable[int] | None = (),
                 root: int | None = None) -> list[dict]:
    """SIGTERM every child of the server (a terminal, a ``claude -p`` of a tick or a request,
    a ``git``, a cub left over) and what it started, except ``keep``'s subtrees; SIGKILL what is
    left after ``grace_s``. Returns the processes found. Each is identified by its start time,
    so a recycled pid is never signalled."""
    keep = None if keep is None else set(keep)
    procs = children(root, keep)
    if not procs:
        return []
    _signal(procs, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(_same(p) for p in procs):
        time.sleep(0.05)
    left = [p for p in procs if _same(p)]
    if left:
        _signal(left + children(root, keep), signal.SIGKILL)
    return procs
