"""Background work you can see: every run is recorded as it goes.

A **run** is one unit of background work with a beginning and an end, whoever started it: a
scheduled job, a press that does work (Brief now, the scout), a cub's job.
``runs`` stays what it was, the end record the scheduler's due-ness reads; a run's life is a
second, append-only table of **marks** (``run_marks``, migration 39): ``started`` when it
begins, ``progress`` as it goes, ``waiting`` when it stopped for the owner, ``stopping`` when
the owner pressed Stop, ``ended`` when it is over, ``dismissed`` when the owner put a failure
away.

The marker::

    with activity.run(store, "news.brief", origin="press", by="ui") as r:
        ...                         # the job; its runs row takes r.uuid (``run_uuid``)
        activity.progress("source 2 of 5, arXiv", step=2, steps=5)
        if activity.stop_requested():
            ...

Writes never slow the work: every mark is a queue put that **one writer thread** commits in
batches, at most every ``BATCH_S`` or ``BATCH_N`` marks, a run's progress marks coalesced (the
newest wins) and dropped first when the queue is long; ``started``, ``waiting``, ``stopping``
and ``ended`` are never dropped and make the writer commit at once. What runs in this process
is known without them (``open_runs``), and the scheduler's due-ness reads ``runs`` rows, so no
mark is written on the job's thread (measured two commits there at a third of a 50 ms
job); the read and the server's stop flush the writer first. After each batch
the writer rewrites ``<data>/activity.json`` (the running runs, a sequence number): the live
feed's watcher stats it, the page then reads ``/api/activity``.

Every word a mark carries passes ``scrub`` before it is written; ``detail`` is a small JSON of
counts and ids, never a payload (``DETAIL_MAX`` bytes).

A run's uuid is the one its job's ``runs`` row, its model calls and its events carry: the job
asks ``run_uuid(kind)`` for it (the first report of the run's own kind gets the run's; any other
a fresh one), so the trace of a run is one id from its first mark to its last call.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import queue
import sqlite3
import threading
import time
import uuid as uuid_mod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..store import Store, iso, utcnow
from ..stored.activity import ActivityMirror, MarkDetail, Needs

log = logging.getLogger("kranto.activity")

MARKS = ("started", "progress", "waiting", "stopping", "ended", "dismissed")
ORIGINS = ("schedule", "press", "event", "loop", "owner")
BATCH_S = 1.0           # the writer commits at most this often
BATCH_N = 50            # or this many marks, whichever comes first
QUEUE_MAX = 1000        # past this many waiting marks, progress marks are dropped first
DETAIL_MAX = 2000       # bytes of a mark's detail
WORDS_MAX = 300         # characters of a mark's words, title, error
MIRROR = "activity.json"
IDLE_EXIT_S = 30.0      # a writer with nothing to do this long ends; the next mark starts one


def _clip(text: str | None, n: int = WORDS_MAX) -> str | None:
    if text is None:
        return None
    from ..scrub import scrub
    s = scrub(" ".join(str(text).split()))
    return s if len(s) <= n else s[:n - 1] + "…"


def _subject(subject: tuple[Any, ...] | None) -> tuple[Any, ...] | None:
    """A subject with its name scrubbed: (kind, id, name)."""
    if not subject:
        return None
    kind, sid, name = (tuple(subject) + (None, None))[:3]
    return (str(kind), None if sid is None else str(sid)[:80], _clip(name) if name else None)


def _detail(detail: dict[str, Any] | None) -> str | None:
    if not detail:
        return None
    from ..scrub import scrub
    raw = scrub(MarkDetail.write(detail))
    if len(raw.encode()) > DETAIL_MAX:
        raw = MarkDetail(note=f"its detail was over {DETAIL_MAX} bytes").to_json()
    return raw


@dataclass
class Run:
    """One run in progress in this process."""

    store: Store
    kind: str
    uuid: str
    origin: str = "schedule"
    by: str | None = None
    title: str | None = None
    subject: tuple[Any, ...] | None = None          # (kind, id, name)
    started: datetime = field(default_factory=utcnow)
    words: str | None = None
    step: int | None = None
    steps: int | None = None
    claimed: bool = False                 # a report of this kind took the uuid
    waiting_words: str | None = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    stopped_by: str | None = None
    result: dict[str, Any] | None = None   # a press's summary, its runs row's (``ctx.run``)

    # -- what a job says as it goes -----------------------------------------------------------

    def progress(self, words: str | None = None, *, step: int | None = None,
                 steps: int | None = None, detail: dict[str, Any] | None = None) -> None:
        self.words = _clip(words) if words is not None else self.words
        self.step = step if step is not None else self.step
        self.steps = steps if steps is not None else self.steps
        _enqueue(self, "progress", words=self.words, step=self.step, steps=self.steps,
                 detail=detail)

    def waiting(self, words: str, needs: dict[str, Any] | None = None, *,
                subject: tuple[Any, ...] | None = None) -> None:
        """The run stopped for the owner: it is over for the scheduler (its runs row is
        written as usual) and open for the owner until its subject moves (the read checks
        the subject; nothing needs clearing)."""
        self.waiting_words = _clip(words)
        if subject is not None:
            self.subject = _subject(subject)
        n = {k: _clip(str(v)) for k, v in (needs or {}).items() if k in ("verb", "href", "words")}
        _enqueue(self, "waiting", words=self.waiting_words, needs=Needs.write(n) if n else None,
                 subject=self.subject, keep=True)

    def stop_requested(self) -> bool:
        return self.stop_event.is_set()

    def request_stop(self, by: str = "owner") -> None:
        if self.stop_event.is_set():
            return
        self.stopped_by = by
        self.stop_event.set()
        _enqueue(self, "stopping", words="stopping: asked by you", keep=True)

    def view(self) -> dict[str, Any]:
        """What the mirror file and the read say of a run in progress."""
        return {"uuid": self.uuid, "kind": self.kind, "title": self.title, "words": self.words,
                "step": self.step, "steps": self.steps, "origin": self.origin, "by": self.by,
                "subject": list(self.subject) if self.subject else None,
                "started": iso(self.started), "stopping": self.stop_event.is_set()}


_CURRENT: contextvars.ContextVar[Run | None] = contextvars.ContextVar("kranto_run", default=None)
_OPEN: dict[str, Run] = {}
_OPEN_LOCK = threading.Lock()


def current() -> Run | None:
    return _CURRENT.get()


def open_runs() -> list[Run]:
    """The runs in progress in this process, oldest first."""
    with _OPEN_LOCK:
        return sorted(_OPEN.values(), key=lambda r: r.started)


def find(run_uuid: str) -> Run | None:
    with _OPEN_LOCK:
        return _OPEN.get(run_uuid)


def run_uuid(kind: str | None = None) -> str:
    """The uuid a job's report takes: the current run's, the first time a report of the run's
    own kind asks (``kind`` None: any kind), else a fresh one."""
    r = _CURRENT.get()
    if r is not None and not r.claimed and (kind is None or kind == r.kind):
        r.claimed = True
        return r.uuid
    return uuid_mod.uuid4().hex


def progress(words: str | None = None, *, step: int | None = None, steps: int | None = None,
             detail: dict[str, Any] | None = None) -> None:
    """A progress mark on the current run; nothing outside one."""
    r = _CURRENT.get()
    if r is not None:
        r.progress(words, step=step, steps=steps, detail=detail)


def waiting(words: str, needs: dict[str, Any] | None = None, *,
            subject: tuple[Any, ...] | None = None) -> None:
    r = _CURRENT.get()
    if r is not None:
        r.waiting(words, needs, subject=subject)


def stop_requested() -> bool:
    """Whether the owner asked the current run to stop (False outside a run)."""
    r = _CURRENT.get()
    return r is not None and r.stop_event.is_set()


def request_stop(run_uuid_: str, by: str = "owner") -> bool:
    """Ask a run of this process to stop at its next step. False when it is not running here."""
    r = find(run_uuid_)
    if r is None:
        return False
    r.request_stop(by)
    return True


# -- the run ------------------------------------------------------------------------------------


@contextlib.contextmanager
def run(store: Store, kind: str, *, origin: str = "schedule", by: str | None = None,
        title: str | None = None, subject: tuple[Any, ...] | None = None,
        uuid: str | None = None) -> Iterator[Run]:
    """One run around a job: ``started`` now, ``ended`` when the block ends (with the state its
    ``runs`` row says, or ``failed`` when the block raised, or ``stopped`` when the owner
    stopped it). Inside a run of the same kind already (a scheduled cub job that calls the
    runtime), the current run is used and nothing more is written."""
    cur = _CURRENT.get()
    if cur is not None and cur.kind == kind:
        yield cur
        return
    if origin not in ORIGINS:
        origin = "press"
    subject = _subject(subject)
    r = Run(store=store, kind=kind, uuid=uuid or uuid_mod.uuid4().hex, origin=origin, by=by,
            title=_clip(title) if title else None, subject=subject)
    if uuid:
        r.claimed = True
    token = _CURRENT.set(r)
    with _OPEN_LOCK:
        _OPEN[r.uuid] = r
    _write_now(r, "started", subject=subject, proc=True)
    error = None
    try:
        yield r
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        with _OPEN_LOCK:
            _OPEN.pop(r.uuid, None)
        _CURRENT.reset(token)
        try:
            _end(r, error)
        except Exception:  # noqa: BLE001 - a mark that cannot be written never fails the job
            log.exception("the ended mark of %s could not be written", kind)


def _end(r: Run, error: str | None) -> None:
    row = r.store.query_one("SELECT status, error FROM runs WHERE run_uuid = ? "
                            "ORDER BY rowid DESC LIMIT 1", (r.uuid,))
    if r.stop_event.is_set():
        state = "stopped"
    elif row is not None:
        state = row["status"]
    elif error is not None:
        state = "failed"
    else:
        state = "skipped"           # nothing was recorded: the job did not run (refused, off)
    # a run that had nothing to do is not a row: its reason is the store's note
    skip = r.store.skip_of(r.uuid) if row is None and hasattr(r.store, "skip_of") else None
    err = error or (row["error"] if row is not None else (skip or {}).get("error"))
    _write_now(r, "ended", state=state, error=err,
               words=r.waiting_words if r.waiting_words else r.words)
    if state == "failed" and error is None:
        _report_failed(r.kind, err)


def _report_failed(kind: str, error: str | None) -> None:
    """A run that failed without raising (its ``runs`` row says failed), as an error report
    when the person chose to send them (a run that raised is reported where it was caught,
    with its stack). ``KeyError: ...`` gives the type (a class name only: any other first word
    could be the person's own); the rest is a template."""
    import re

    from ..telemetry import errors

    m = re.match(r"(?:[a-z_][a-z0-9_]*\.)*([A-Z][A-Za-z0-9]{0,60}(?:Error|Exception|Timeout|"
                 r"Interrupt|Exit)): ?(.*)", str(error or ""), re.S)
    type_, message = (m.group(1), m.group(2)) if m else ("JobFailed", str(error or ""))
    errors.report_failure(type_, "job", message=message, job=kind)


# -- writing ------------------------------------------------------------------------------------

_COLS = ("run_uuid", "kind", "ts", "mark", "state", "trigger", "by", "subject_kind",
         "subject_id", "subject_name", "title", "words", "error", "step", "steps", "pid",
         "pstart", "needs", "detail")


def _row(r: Run, mark: str, *, state: str | None = None, words: str | None = None,
         error: str | None = None, step: Any = None, steps: Any = None, needs: Any = None,
         detail: Any = None, subject: tuple[Any, ...] | None = None,
         proc: bool = False) -> dict[str, Any]:
    sub = subject or (r.subject if mark in ("started", "waiting") else None)
    me = _me() if proc else {}
    return {"run_uuid": r.uuid, "kind": r.kind, "ts": iso(utcnow()), "mark": mark,
            "state": state, "trigger": r.origin if mark == "started" else None,
            "by": r.by if mark == "started" else None,
            "subject_kind": str(sub[0]) if sub else None,
            "subject_id": str(sub[1]) if sub and len(sub) > 1 and sub[1] is not None else None,
            "subject_name": _clip(str(sub[2])) if sub and len(sub) > 2 and sub[2] else None,
            "title": r.title if mark == "started" else None,
            "words": words, "error": _clip(error), "step": step, "steps": steps,
            "pid": me.get("pid"), "pstart": me.get("start"), "needs": needs,
            "detail": _detail(detail)}


_ME: dict[str, Any] = {}


def _me() -> dict[str, Any]:
    """This process (``proc.me``), read from /proc once per process (a fork reads it again)."""
    if _ME.get("pid") != os.getpid():
        from .. import proc as proc_mod
        _ME.clear()
        _ME.update(proc_mod.me())
    return _ME


def _write_now(r: Run, mark: str, **kw: Any) -> None:
    """``started`` and ``ended``: queued like every mark, never dropped, in order, and the writer
    told to commit now. What runs in this process is known at once without them (``open_runs``);
    the scheduler's due-ness reads ``runs`` rows. Written on the job's thread, two commits cost a
    short job (compaction, 50 ms) a third of its time (measured): a queue put does not."""
    _queue(r.store, r.uuid, mark, _row(r, mark, **kw), True)
    _bump(r.store)


def _enqueue(r: Run, mark: str, *, keep: bool = False, **kw: Any) -> None:
    _queue(r.store, r.uuid, mark, _row(r, mark, **kw), keep)


def write_mark(store: Store, *, run_uuid_: str, kind: str, mark: str, words: str | None = None,
               detail: dict[str, Any] | None = None) -> int:
    """A mark of a run that is not in progress here (the owner's Dismiss of a failure)."""
    if mark not in MARKS:
        raise ValueError(f"a mark is one of {', '.join(MARKS)}")
    rid = store.insert("run_marks", {"run_uuid": run_uuid_, "kind": kind, "ts": iso(utcnow()),
                                     "mark": mark, "words": _clip(words),
                                     "detail": _detail(detail)})
    _bump(store)
    return rid


class Writer:
    """One thread per database: the marks a job queues, committed in batches."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._q: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._pending = 0
        self._lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = threading.Event()
        self._closed = False
        self.dropped = 0
        self.batches = 0
        self._thread = threading.Thread(target=self._loop, name="kranto-activity", daemon=True)
        self._thread.start()

    def put(self, uuid_: str, mark: str, row: dict[str, Any], *, keep: bool = False) -> bool:
        """Queue a mark; False when this writer has ended (``writer_for`` makes another)."""
        with self._lock:
            if self._closed:
                return False
            if self._pending >= QUEUE_MAX and not keep:
                self.dropped += 1
                return True
            self._pending += 1
            self._idle.clear()
            self._q.put((uuid_, mark, row, keep))
        return True

    def nudge(self) -> bool:
        """Rewrite the mirror at the next turn (a sync mark was written)."""
        with self._lock:
            if self._closed:
                return False
            self._idle.clear()
            self._q.put(None)
        return True

    def _take(self) -> list[Any]:
        got: list[Any] = []
        deadline = time.monotonic() + BATCH_S
        while len(got) < BATCH_N:
            left = deadline - time.monotonic()
            if left <= 0 and got:
                break
            try:
                item = self._q.get(timeout=max(0.01, left) if got else BATCH_S)
            except queue.Empty:
                break                   # a batch to commit, or a quiet second to report
            got.append(item)
            if item is None:
                # a nudge (a flush, a started or ended mark): commit what is here now
                break
        return got

    def _loop(self) -> None:
        conn = None
        quiet_since = time.monotonic()
        while True:
            items = self._take()
            if not items:
                self._idle.set()
                with self._lock:
                    # stopped, or idle for a while: end (a later mark starts another writer)
                    if self._pending == 0 and self._q.empty() and (
                            self._stop.is_set() or time.monotonic() - quiet_since > IDLE_EXIT_S):
                        self._closed = True
                        break
                continue
            quiet_since = time.monotonic()
            marks = [i for i in items if i is not None]
            # coalesce: a run's progress marks, the newest wins; every other mark in order
            newest: dict[str, int] = {}
            for n, (u, mark, _row, _keep) in enumerate(marks):
                if mark == "progress":
                    newest[u] = n
            rows = [row for n, (u, mark, row, _k) in enumerate(marks)
                    if (mark != "progress" or newest.get(u) == n)
                    and (mark != "progress" or find(u) is not None)]
            try:
                if rows:
                    conn = self._commit(rows, conn)
                write_mirror(self.store)
            except Exception:  # noqa: BLE001 - marks are what is lost, never the work
                log.exception("the activity writer could not commit %d marks", len(rows))
            with self._lock:
                self._pending -= len(marks)
            self.batches += 1
            if self._q.empty():
                self._idle.set()
        if conn is not None:
            conn.close()

    def _commit(self, rows: list[dict[str, Any]],
                conn: sqlite3.Connection | None) -> sqlite3.Connection | None:
        sql = (f"INSERT INTO run_marks ({', '.join(_COLS)}) "
               f"VALUES ({', '.join('?' * len(_COLS))})")
        args = [tuple(r.get(c) for c in _COLS) for r in rows]
        path = self.store.path
        if path is None:                 # an in-memory store (tests): its own connection only
            with self.store.tx() as c:
                c.executemany(sql, args)
            return conn
        if conn is None:
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            conn.execute("PRAGMA busy_timeout = 5000")
            # its commits wait for no fsync (WAL keeps them whole; a power cut can lose only the
            # last marks, never the database): measured, a batch held the write lock ~40 ms at
            # FULL, which the job's own writes waited on
            conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.executemany(sql, args)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        return conn

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until every queued mark is committed (the server's stop, the tests)."""
        if not self.nudge():
            return True
        return self._idle.wait(timeout)

    def close(self, timeout: float = 2.0) -> None:
        self.flush(timeout)
        self._stop.set()
        with self._lock:
            if not self._closed:
                self._q.put(None)
        self._thread.join(timeout)


_WRITERS: dict[int, Writer] = {}
_WRITERS_LOCK = threading.Lock()


def writer_for(store: Store) -> Writer:
    with _WRITERS_LOCK:
        w = _WRITERS.get(id(store))
        if w is None or w.store is not store or w._closed:
            w = _WRITERS[id(store)] = Writer(store)
        return w


def _queue(store: Store, uuid_: str, mark: str, row: dict[str, Any], keep: bool) -> None:
    for _ in range(3):              # a writer that ended between the lookup and the put
        if writer_for(store).put(uuid_, mark, row, keep=keep):
            return


def flush(timeout: float = 2.0) -> bool:
    """Every writer flushed within ``timeout`` in all (the server's stop)."""
    deadline = time.monotonic() + timeout
    ok = True
    with _WRITERS_LOCK:
        writers = list(_WRITERS.values())
    for w in writers:
        ok = w.flush(max(0.0, deadline - time.monotonic())) and ok
    return ok


def shutdown(timeout: float = 2.0) -> None:
    """Flush and stop every writer (a closed store, the end of a test)."""
    with _WRITERS_LOCK:
        writers = list(_WRITERS.values())
        _WRITERS.clear()
    for w in writers:
        w.close(timeout)


# -- the mirror ---------------------------------------------------------------------------------

_SEQ = {"n": 0}
_SEQ_LOCK = threading.Lock()


def _bump(store: Store) -> None:
    with _SEQ_LOCK:
        _SEQ["n"] += 1
    for _ in range(3):                  # the writer commits and rewrites the mirror, at once
        if writer_for(store).nudge():
            return


def settle(store: Store, timeout: float = 1.0) -> None:
    """Every mark queued for ``store`` committed (a read that must see them all): nothing when
    no writer has anything for it."""
    with _WRITERS_LOCK:
        w = _WRITERS.get(id(store))
    if w is not None and w.store is store and not w._closed:
        w.flush(timeout)


def mirror_path(store: Store) -> Path | None:
    return Path(store.path).parent / MIRROR if store.path is not None else None


def write_mirror(store: Store) -> None:
    """``activity.json``: the runs in progress here and a sequence number, rewritten atomically
    (0600). The live feed stats it; nothing reads it but a page's follow."""
    path = mirror_path(store)
    if path is None:
        return
    with _SEQ_LOCK:
        _SEQ["n"] += 1
        seq = _SEQ["n"]
    body = {"seq": seq, "updated": iso(utcnow()),
            "running": [r.view() for r in open_runs() if r.store is store][:50]}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(ActivityMirror.write(body))
    os.replace(tmp, path)


# -- retention ----------------------------------------------------------------------------------


def prune(store: Store, *, keep_days: float, max_rows: int, run_uuid_: str,
          now: datetime | None = None) -> int:
    """Marks older than ``keep_days``, then the oldest past ``max_rows``, removed through the
    recorded purge (``Store.purge``: a ``purges`` row says how many, why and from when). A run
    in progress keeps its marks. Returns how many went."""
    from datetime import timedelta
    now = now or utcnow()
    cutoff = iso(now - timedelta(days=keep_days))
    # the marks still queued are counted too: a run in progress has written its start
    writer_for(store).flush(2.0)
    live = {r.uuid for r in open_runs()}
    old = [r["id"] for r in store.query("SELECT id, run_uuid FROM run_marks WHERE ts < ?",
                                        (cutoff,)) if r["run_uuid"] not in live]
    counted = store.query_one("SELECT COUNT(*) AS n FROM run_marks")
    assert counted is not None                 # COUNT(*) always answers one row
    total = counted["n"]
    over = total - len(old) - int(max_rows)
    extra = []
    if over > 0:
        skip = set(old)
        extra = [r["id"] for r in store.query(
            "SELECT id, run_uuid FROM run_marks ORDER BY id LIMIT ?", (over + len(old),))
            if r["id"] not in skip and r["run_uuid"] not in live][:over]
    removed = 0
    for ids, reason in ((old, f"activity: marks older than {keep_days:g} days"),
                        (extra, f"activity: over {int(max_rows):,} marks, the oldest first")):
        if not ids:
            continue
        with store.purge() as conn:
            first = conn.execute("SELECT ts FROM run_marks WHERE id = ?",
                                 (min(ids),)).fetchone()[0]
            n = 0
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                n += conn.execute(f"DELETE FROM run_marks WHERE id IN "
                                  f"({','.join('?' * len(chunk))})", chunk).rowcount
            conn.execute(
                "INSERT INTO purges (run_uuid, table_name, row_count, reason, rollup_ids, detail, "
                "created_at) VALUES (?, 'run_marks', ?, ?, '[]', ?, ?)",
                (run_uuid_, n, reason, json.dumps({"from": first}), iso(now)))
        removed += n
    return removed


# -- after a crash ------------------------------------------------------------------------------


def recover(store: Store) -> int:
    """Runs a previous process left without an end (it was killed, or stopped mid-run): each
    gets its ``ended`` mark, ``stopped``, "cut off: Kranto restarted". Returns how many."""
    from datetime import timedelta

    from .. import proc as proc_mod
    rows = store.query(
        "SELECT m.run_uuid, m.kind, m.pid, m.pstart FROM run_marks m "
        "WHERE m.mark = 'started' AND m.ts >= ? "
        "AND NOT EXISTS (SELECT 1 FROM run_marks e WHERE e.run_uuid = m.run_uuid "
        "AND e.mark = 'ended')", (iso(utcnow() - timedelta(days=30)),))
    n = 0
    for r in rows:
        if find(r["run_uuid"]) is not None or proc_mod.running(r["pid"], r["pstart"]):
            continue
        done = store.query_one("SELECT status FROM runs WHERE run_uuid = ? LIMIT 1",
                               (r["run_uuid"],))
        store.insert("run_marks", {
            "run_uuid": r["run_uuid"], "kind": r["kind"], "ts": iso(utcnow()), "mark": "ended",
            "state": done["status"] if done else "stopped",
            "words": None if done else "cut off: Kranto restarted; it runs again at its time"})
        n += 1
    return n
