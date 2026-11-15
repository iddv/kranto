"""The page's live feed: ``GET /api/stream``, server-sent events that say *what
changed*, never the data; the page refetches what it shows through its usual reads.

One watcher thread per process, whatever the number of open pages, looks every second at the
files that already change with every state change: Open in Claude Code's sessions' records,
the server's ``activity.json`` (``change`` of kind ``activity``) and ``verbs.json``, and the
files of a
trace a page follows (``FOLLOWS``: ``change`` of kind ``trace``, its id in ``keys``). It stats
them and reads nothing, never the network or a model (no request waits on either). A change
wakes every stream through one ``Condition``.

    retry: 3000
    event: host        data: {"version": "0.3.50"}            first; a new one means reload
    event: change      data: {"kinds": ["activity"], "keys": [], "seq": 7}
    : ping                                                     every PING_S, to keep it open

At most ``MAX_STREAMS`` at once per process; one more is answered ``event: busy`` and closed,
and the page polls (it was a 503, an error in the console: QA B20). A
stream nobody has read for ``STALE_S`` (its client went away while the server was blocked)
gives its place up. The watcher stops when the last stream ends.
"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from .. import __version__, paths

TICK_S = 1.0
PING_S = 15.0
STALE_S = 60.0
MAX_STREAMS = 8
KEEP = 64                     # recent events, for a stream that fell behind


class Busy(Exception):
    """Every stream place is taken: the stream says so (``busy_events``), the page polls."""


RETRY_BUSY_MS = 30000


def busy_events(why: str) -> Iterator[bytes]:
    """What a stream refused for want of a place answers (200, then closed): try again in 30 s,
    and that it is busy. A 503 here was an error in the page's console on every page past the
    hub's places (QA B20); the page polls meanwhile and its status bar says live updates are
    paused."""
    yield f"retry: {RETRY_BUSY_MS}\n\n".encode()
    yield _event("busy", {"why": why, "retry_ms": RETRY_BUSY_MS})


def _stat(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


FOLLOW_S = 120.0              # a trace's files are watched this long after its page asked


class Follows:
    """The traces a page has open: their files are watched while someone
    looks, never otherwise (a build's transcripts grow by megabytes a minute). ``add`` renews
    a trace for ``FOLLOW_S``; ``files`` is asked each tick, so a session that starts later is
    watched too."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by: dict[str, tuple] = {}          # trace id -> (files(), until)

    def add(self, tid: str, files, seconds: float = FOLLOW_S) -> float:
        until = time.monotonic() + seconds
        with self.lock:
            self.by[tid] = (files, until)
        return until

    def look(self) -> dict[str, tuple]:
        now = time.monotonic()
        with self.lock:
            for tid in [t for t, (_, u) in self.by.items() if u < now]:
                del self.by[tid]
            items = list(self.by.items())
        out = {}
        for tid, (files, _) in items:
            try:
                out[tid] = tuple((str(p), _stat(p)) for p in files())
            except Exception:                    # noqa: BLE001 - a file gone is no event
                out[tid] = ()
        return out


FOLLOWS = Follows()


def _dirs(root: Path) -> list[Path]:
    try:
        return [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []


class Watcher:
    """What one App's state files look like now, and which kinds changed since last time."""

    def __init__(self, app):
        self.app = app
        self.last: dict[str, object] = {}
        self.home = Path(app.loop_cfg().home)
        data = getattr(app, "kranto_data", None)
        self.afk_activity = Path(data) / "activity.json" if data else None
        # what an assistant did (the server verbs_api,): the page marks the row
        self.afk_verbs = Path(data) / "verbs.json" if data else None

    def look(self) -> dict[str, object]:
        return {
            # Open in Claude Code: each session's record (its state, cost, proposals), never
            # its transcript, which moves with every key
            "term": tuple(sorted((d.name, _stat(d / "session.json"))
                                 for d in _dirs(paths.LoopLayout(self.home).term))),
            # the traces a page follows: their transcripts and hook rows
            "trace": FOLLOWS.look(),
            # the server's runs as they go: its mirror file, rewritten at each batch of marks
            #; stat'ed, never read
            "activity": _stat(self.afk_activity) if self.afk_activity else None,
            "verbs": _stat(self.afk_verbs) if self.afk_verbs else None,
        }

    def changes(self) -> dict | None:
        """``{"kinds", "keys"}`` since the last look, or None. The first look is the baseline."""
        now = self.look()
        before, self.last = self.last, now
        if not before:
            return None
        kinds, keys = [], []
        if now["term"] != before["term"]:
            kinds.append("term")
        # the server's runs moved: the activity read
        if now.get("activity") != before.get("activity"):
            kinds.append("activity")
        if now.get("verbs") != before.get("verbs"):
            kinds.append("verb")
        t0, t1 = before.get("trace") or {}, now["trace"]
        grew = sorted(t for t in t1 if t in t0 and t0[t] != t1[t])   # a new follow: no event
        if grew:
            kinds.append("trace")
            keys += grew
        return {"kinds": kinds, "keys": keys} if kinds else None


class Hub:
    """The process's streams and the one thread that watches for them."""

    def __init__(self):
        self.cond = threading.Condition()
        self.seq = 0
        self.events: list[tuple[int, dict]] = []
        self.streams: dict[int, float] = {}         # id -> when it was last read
        self.next_id = 0
        self.thread: threading.Thread | None = None
        self.watchers: dict[int, Watcher] = {}

    def publish(self, change: dict) -> None:
        with self.cond:
            self.seq += 1
            self.events = [*self.events[-(KEEP - 1):], (self.seq, {**change, "seq": self.seq})]
            self.cond.notify_all()

    def _run(self) -> None:
        while True:
            with self.cond:
                if not self.streams:
                    self.thread = None
                    self.watchers.clear()
                    return
                watchers = list(self.watchers.values())
            for w in watchers:
                try:
                    c = w.changes()
                except Exception:                    # noqa: BLE001 - a missing file is no event
                    c = None
                if c:
                    self.publish(c)
            time.sleep(TICK_S)

    def open(self, app) -> int:
        with self.cond:
            now = time.monotonic()
            for sid, seen in list(self.streams.items()):
                if now - seen > STALE_S:
                    del self.streams[sid]
            if len(self.streams) >= MAX_STREAMS:
                raise Busy(f"{MAX_STREAMS} live streams are open; poll instead")
            self.next_id += 1
            self.streams[self.next_id] = now
            if id(app) not in self.watchers:
                self.watchers[id(app)] = w = Watcher(app)
                try:
                    w.changes()                        # the baseline, before the first event
                except Exception:                      # noqa: BLE001
                    pass
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="kranto-live",
                                               daemon=True)
                self.thread.start()
            return self.next_id

    def close(self, sid: int) -> None:
        with self.cond:
            self.streams.pop(sid, None)

    def stream(self, app, last: int | None = None) -> Stream:
        """One client's events. Opens its place now (``Busy`` when none is free), so the
        caller can still answer 503; the place is given up when the stream closes. A fresh
        stream starts from the change count *now*, not from when its client first reads past
        the host line: a change in between is sent, not lost."""
        sid = self.open(app)
        with self.cond:
            seen = self.seq if last is None else last
        return Stream(self, sid, self._events(sid, seen))

    def _events(self, sid: int, seen: int) -> Iterator[bytes]:
        try:
            yield b"retry: 3000\n\n"
            yield _event("host", {"version": __version__})
            while True:
                with self.cond:
                    if sid not in self.streams:
                        return
                    self.streams[sid] = time.monotonic()
                    if self.seq == seen:
                        self.cond.wait(PING_S)
                    fresh = [e for s, e in self.events if s > seen]
                    seen = self.seq
                if fresh:
                    for e in fresh:
                        yield _event("change", e, e["seq"])
                else:
                    yield b": ping\n\n"
        finally:
            self.close(sid)


class Stream:
    """A client's events, as an iterator of bytes. ``close`` (or losing the last reference)
    gives its place back, even when it was never read: a generator's ``finally`` alone would
    not run for one that never started."""

    def __init__(self, hub: Hub, sid: int, events: Iterator[bytes]):
        self.hub, self.sid, self.events = hub, sid, events

    def __iter__(self) -> Stream:
        return self

    def __next__(self) -> bytes:
        return next(self.events)

    def close(self) -> None:
        self.hub.close(self.sid)          # a wait under way sees it and ends within PING_S
        try:
            self.events.close()
        except ValueError:                # being read in another thread right now
            pass

    def __del__(self):
        self.close()


def _event(name: str, data: dict, eid: int | None = None) -> bytes:
    head = f"id: {eid}\n" if eid is not None else ""
    return f"{head}event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


HUB = Hub()
