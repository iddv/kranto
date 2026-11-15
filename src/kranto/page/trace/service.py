"""What the trace routes answer, as plain functions over one ``Traces``:
every string redacted (``redact.py``), every answer bounded.

The open traces are kept in memory (an LRU of ``OPEN_MAX``): a trace's readers hold their
place in each file, so a refresh reads only new bytes, and a page of 500 spans out of 50,000
is a slice. The index (``index.py``) keeps the trace list across restarts and the search text.

**Revisions and the cursor.** Each refresh that changes a trace bumps its ``rev``; a span whose
summary changed (a tool's result landed, a session ended, a position moved) takes that rev.
The cursor (``{"r": rev, "p": position}``, base64, opaque to the page) asks for two things at
once: the spans that changed since rev ``r`` and are at or before position ``p`` (already
shown), and the next page after ``p``. A trace whose file was rewritten (it shrank) starts
over: an old cursor is refused (422) and the page reads from the top.

**The build loop's traces** (``build:``, ``maint:``, ``loop:``) left with it. Their rows in
``trace.db`` still list, read-only and drawn with their stored words; they do not open (404).
``trace.db`` is never written: the index of the traces read now is in memory, a cache."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

from .base import Trace, failed_label
from .index import Index, archived
from .model import parse_trace_id
from .payload import PayloadError, payload
from .redact import Redactor

OPEN_MAX = 4                 # traces held open in memory
LIMIT = 500                  # spans a page by default
LIMIT_MAX = 2000             # and at most
INDEX_EVERY_S = 5.0          # a running trace's spans go to the index at most this often
FILTERS = ("errors", "tool", "stage", "kind", "cost")
GONE = ("build", "maint", "loop")    # the build loop's traces: listed from the archive only
# the list's sources (``Traces.list``): what Kranto runs now, each of its kinds, the old rows
SOURCES = ("all", "session", "afk", "research", *GONE)
DEFAULT_SOURCE = "all"


class TraceError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def encode_cursor(rev: int, pos: int, epoch: str = "") -> str:
    return base64.urlsafe_b64encode(json.dumps({"e": epoch, "r": rev, "p": pos}).encode()).decode()


def decode_cursor(c: str | None) -> tuple[int, int] | None:
    """``(rev, pos)``; the epoch is checked by ``cursor_epoch``."""
    if not c:
        return None
    try:
        d = json.loads(base64.urlsafe_b64decode(c.encode() + b"=" * (-len(c) % 4)))
        return int(d["r"]), int(d["p"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise TraceError(422, "that cursor is not one this server made; read from the top")


def cursor_epoch(c: str) -> str | None:
    try:
        return str(json.loads(base64.urlsafe_b64decode(c.encode() + b"=" * (-len(c) % 4)))
                   .get("e") or "")
    except (ValueError, TypeError, binascii.Error, AttributeError):
        return None


def _fingerprint(sp) -> tuple:
    return (sp.parent, sp.pos, sp.depth, sp.children, sp.status, sp.end, sp.start, sp.usd,
            sp.usd_kind, sp.name, sp.preview, sp.stage,
            tuple(sorted(sp.tokens.items())) if sp.tokens else None,
            bool(sp.attrs.get("denied")), (sp.error or {}).get("message"), len(sp.events))


class Open:
    """One trace held open: its ``Trace``, revisions and the time it was last indexed."""

    def __init__(self, t: Trace):
        self.t = t
        # a cursor's revisions mean something to this reading only: another (a restart, the
        # trace dropped from memory and read again) answers its cursor "read from the top"
        self.epoch = os.urandom(4).hex()
        self.rev = 0
        self.reset = 0                  # the rev of the last start-over (a file rewritten)
        self.revs: dict[str, int] = {}
        self.fps: dict[str, tuple] = {}
        self.order: list = []           # the spans in tree order
        self.indexed = 0.0
        self.indexing: threading.Thread | None = None   # the spans' write to the index
        self.lock = threading.Lock()

    def mark(self) -> None:
        """After a refresh: bump ``rev`` and give it to every span whose summary changed."""
        self.rev += 1
        gone = set(self.fps) - set(self.t.spans)
        if gone:
            self.reset = self.rev
        fps = {}
        for sid, sp in self.t.spans.items():
            fp = _fingerprint(sp)
            fps[sid] = fp
            if self.fps.get(sid) != fp:
                self.revs[sid] = self.rev
        self.fps = fps
        for sid in gone:
            self.revs.pop(sid, None)
        self.order = sorted(self.t.spans.values(), key=lambda s: s.pos)   # pos == its index


class Traces:
    """The traces kranto reads now, with their index at ``index_path`` (None: in memory) and
    the rows of the traces that left with the build loop in ``archive`` (``trace.db``, read
    only; None: none). ``page_kb`` and ``payload_max_mb``: the ``trace.*`` settings."""

    def __init__(self, index_path: Path | None = None, page_kb: int = 64,
                 payload_max_mb: int = 2, loop_home: Path | None = None, afk_fetch=None,
                 afk_mirror=None, archive: Path | None = None):
        self.afk_fetch = afk_fetch                 # GET a server path as the owner
        self.afk_mirror = afk_mirror               # () -> the server's activity.json, or None
        self.archive = Path(archive) if archive is not None else None
        self.loop_home = Path(loop_home) if loop_home is not None else None   # term/ sessions
        self.index_path = index_path
        self._index: Index | None = None
        self.page_bytes = int(page_kb) * 1024
        self.max_bytes = int(payload_max_mb) * 1024 * 1024
        self.open_: OrderedDict[str, Open] = OrderedDict()
        self.lock = threading.Lock()

    @property
    def index(self) -> Index:
        if self._index is None:
            self._index = Index(self.index_path)
        return self._index

    def get(self, tid: str) -> Open:
        """The trace, read up to now (opened on first use, refreshed after)."""
        try:
            src, key, n = parse_trace_id(tid)
        except ValueError as e:
            raise TraceError(404, str(e)) from None
        if src in GONE:
            raise TraceError(404, f"{src} traces left with the build loop: the list keeps "
                                  "their row, and they no longer open")
        if src not in ("session", "research", "afk"):
            raise TraceError(404, f"{src} traces are not readable yet")
        with self.lock:
            o = self.open_.get(tid)
            if o is not None:
                self.open_.move_to_end(tid)
        if o is None:
            t = self._session(key) if src == "session" else self._research(key) \
                if src == "research" else self._afk(key)
            t.page_bytes, t.max_bytes = self.page_bytes, self.max_bytes
            o = Open(t)
            with o.lock:
                t.refresh()
                if src == "session" and not t.rec:
                    raise TraceError(404, f"no session {key!r}")
                if src == "research" and not t.files():
                    raise TraceError(404, f"no research run {key!r}")
                o.mark()
                self._to_index(o, force=True)
            with self.lock:
                self.open_[tid] = o
                while len(self.open_) > OPEN_MAX:
                    self.open_.popitem(last=False)
            return o
        with o.lock:
            if o.t.refresh():
                o.mark()
                self._to_index(o)
        return o

    def _afk(self, uuid: str):
        """A server run, read through the server's API (``afk_fetch``), never its file."""
        import re as _re

        from .afk import AfkTrace
        if self.afk_fetch is None or not _re.fullmatch(r"[A-Za-z0-9-]{8,64}", uuid or ""):
            raise TraceError(404, f"no server run {uuid!r}")

        def fetch(path: str) -> dict:
            try:
                return self.afk_fetch(path)
            except Exception as e:                      # noqa: BLE001 - its HttpError, a 404
                code = getattr(e, "code", 502)
                raise TraceError(404 if code == 404 else 502, str(e)) from None
        mirror = self.afk_mirror() if self.afk_mirror is not None else None
        return AfkTrace(fetch, uuid, mirror)

    def _research(self, stem: str):
        from .file import FileTrace, research_file
        p = research_file(self.loop_home, stem) if self.loop_home is not None else None
        if p is None:
            raise TraceError(404, f"no research run {stem!r}")
        when = time.strftime("%d %b %H:%M", time.localtime(int(stem.split("-")[0])))
        return FileTrace(p, f"research:{stem}", f"Research · {when}")

    def _session(self, tid: str):
        from ..term.store import valid_tid
        from .session import SessionTrace
        if self.loop_home is None or not valid_tid(tid):
            raise TraceError(404, f"no session {tid!r}")
        return SessionTrace(self.loop_home / "term" / tid, tid)

    def _sig(self, t: Trace) -> str:
        h = hashlib.sha1()
        for p in t.files():
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{t.rel(p)}:{st.st_size}:{st.st_mtime_ns};".encode())
        return h.hexdigest()

    def _to_index(self, o: Open, force: bool = False) -> None:
        now = time.time()
        if not force and o.t.running and now - o.indexed < INDEX_EVERY_S:
            return
        o.indexed = now
        t = o.t
        self.index.put_trace({**t.summary, "root": str(t.taskdir)}, self._sig(t),
                             failed_label(t), self.files(t))
        # the spans go to the index behind the answer: the page reads the open trace from
        # memory, the index serves the list, the search and the CLI
        spans, links, readers = list(t.spans.values()), list(t.links), list(t.streams.values())
        prev = o.indexing

        def write():
            if prev is not None:
                prev.join()
            try:
                texts: dict[str, str] = {}
                for r in readers:
                    texts.update(r.texts)
                self.index.put_spans(t.id, spans, texts, links)
            except (RuntimeError, sqlite3.Error):        # a span changed under it: next time
                o.indexed = 0.0
        o.indexing = threading.Thread(target=write, name="trace-index", daemon=True)
        o.indexing.start()

    def settle(self) -> None:
        """Wait for the index writes in flight (the tests, the CLI before it exits)."""
        for o in list(self.open_.values()):
            if o.indexing is not None:
                o.indexing.join()

    @staticmethod
    def files(t: Trace) -> list[dict]:
        out = []
        readers = dict(t.streams)
        for p in t.files():
            rel = t.rel(p)
            try:
                st = p.stat()
            except OSError:
                continue
            r = readers.get(rel)
            out.append({"rel": rel, "bytes": st.st_size, "mtime": st.st_mtime,
                        "offset": getattr(r, "offset", None), "pruned": False})
        return out

    # -- the list ----------------------------------------------------------------------------
    def list(self, source: str | None = DEFAULT_SOURCE, key: str | None = None,
             state: str | None = None, since: float | None = None, limit: int = 50,
             after: str | None = None) -> dict:
        """The traces of ``source`` (``SOURCES``), newest first. ``all`` (the default, also
        None or empty): what Kranto runs now, its console and Open in Claude Code sessions (their
        records in the loop home's ``term/``, read as they are, opened or not), the server's runs
        (its ``/api/runs``) and the kept research runs. ``build``, ``maint``, ``loop``: the rows
        the build loop's traces left in ``trace.db`` (read-only), each under its own source
        only."""
        source = source or DEFAULT_SOURCE
        if source not in SOURCES:
            raise TraceError(400, f"source is one of {', '.join(SOURCES)}")
        before = None
        if after:
            try:
                before = float(base64.urlsafe_b64decode(after.encode() + b"=" * (-len(after) % 4)))
            except (ValueError, binascii.Error):
                raise TraceError(422, "that cursor is not one this server made")
        lim = max(1, min(int(limit), 200))
        red = Redactor()
        if source in GONE:
            q = {"source": source, "key": key, "state": state, "since": since,
                 "limit": lim + 1, "before": before}
            rows = [self._summary_of_row(r, red) for r in archived(self.archive, **q)] \
                if self.archive else []
        else:
            rows = []
            if source in ("all", "session"):
                rows += self._session_rows(red)
            if source in ("all", "afk"):
                rows += self._afk_rows(red, lim + 1 + (0 if before is None else 200))
            if source in ("all", "research"):
                rows += self._research_list(200)["traces"]
            rows = [r for r in rows
                    if (not key or r["key"] == key) and (not state or r["state"] == state)
                    and (since is None or (r["started"] or 0) >= since)
                    and (before is None or (r["started"] or 0) < before)]
        rows.sort(key=lambda r: -(r["started"] or 0))
        more = len(rows) > lim
        rows = rows[:lim]
        nxt = base64.urlsafe_b64encode(str(rows[-1]["started"]).encode()).decode() \
            if more and rows else None
        return {"traces": rows, "next": nxt}

    def _session_rows(self, red: Redactor) -> list[dict]:
        """Every console and Open in Claude Code session in the loop home's ``term/``, from its
        record (read-only; a transcript is read only when the trace is opened). A trace read
        since keeps its fuller summary (the index's row)."""
        from ..term.store import Store
        if self.loop_home is None:
            return []
        out = []
        for rec in Store(Path(self.loop_home) / "term").all():
            tid = rec.get("tid")
            row = self.index.trace_row(f"session:{tid}")
            if row is not None:
                out.append(self._summary_of_row(row, red))
                continue
            running = rec.get("state") == "running"
            start = rec.get("created")
            end = None if running else rec.get("updated")
            tok = rec.get("tokens") if isinstance(rec.get("tokens"), dict) else {}
            usd = float(rec["usd"]) if isinstance(rec.get("usd"), (int, float)) else None
            out.append({
                "id": f"session:{tid}", "source": "session", "key": tid, "n": None,
                "title": red.text(str(rec.get("title") or f"Session {tid}")),
                "state": "running" if running else
                ("stopped" if rec.get("reason") == "cap" else "ok"),
                "outcome": None, "started": start, "ended": end,
                "wall_s": round(end - start, 1) if end and start else None,
                "usd": usd, "usd_kind": "exact" if usd is not None else "none",
                "tokens": {"in": int(tok.get("in") or 0), "out": int(tok.get("out") or 0)},
                "sessions": 1, "tools": 0, "errors": 0, "failed_at": None,
                "failed_label": None, "model": rec.get("model"), "spans": None,
                "href": _href(tid, None, "session")})
        return out

    def _afk_rows(self, red: Redactor, limit: int) -> list[dict]:
        """The server's runs (``GET /api/runs``, the owner's read), newest first; none when
        the server is not known here or cannot be read."""
        from .afk import _ts
        if self.afk_fetch is None:
            return []
        try:
            body = self.afk_fetch(f"/api/runs?limit={max(1, min(int(limit), 500))}")
        except Exception:                                # noqa: BLE001 - the rest still lists
            return []
        out = []
        for r in (body or {}).get("runs") or [] if isinstance(body, dict) else []:
            uuid = str(r.get("run_uuid") or "")
            if not uuid:
                continue
            start, end = _ts(r.get("started_at")), _ts(r.get("finished_at"))
            usd = float(r["cost_usd"]) if isinstance(r.get("cost_usd"), (int, float)) else None
            st = "running" if end is None and r.get("status") in (None, "", "running") else \
                {"failed": "error"}.get(str(r.get("status") or ""), "ok")
            out.append({
                "id": f"afk:{uuid}", "source": "afk", "key": uuid, "n": None,
                "title": red.text(str(r.get("kind") or "run")), "state": st, "outcome": None,
                "started": start, "ended": end,
                "wall_s": round(end - start, 1) if end and start else None,
                "usd": usd, "usd_kind": "exact" if usd is not None else "none",
                "tokens": {"in": 0, "out": 0}, "sessions": 0, "tools": 0,
                "errors": 1 if st == "error" else 0, "failed_at": None,
                "failed_label": red.text(str(r["error"]))[:200] if r.get("error") else None,
                "model": None, "spans": None, "calls": r.get("calls"),
                "href": _href(uuid, None, "afk")})
        return out

    def _research_list(self, limit: int) -> dict:
        """The research runs that kept their stream, newest first (read now: a few files)."""
        from .file import transcripts_dir
        if self.loop_home is None:
            return {"traces": [], "next": None}
        stems = sorted((p.name.removesuffix(".transcript.jsonl")
                        for p in transcripts_dir(self.loop_home).glob("*.transcript.jsonl")),
                       key=lambda s: -int(s.split("-")[0]) if s.split("-")[0].isdigit() else 0)
        red, out = Redactor(), []
        for stem in stems[:min(int(limit), 200)]:
            try:
                o = self.get(f"research:{stem}")
            except TraceError:
                continue
            out.append(self._trace_summary(o.t, red))
        return {"traces": out, "next": None}

    @staticmethod
    def _summary_of_row(r: dict, red: Redactor) -> dict:
        wall = round(r["ended"] - r["started"], 1) if r["ended"] and r["started"] else None
        return {"id": r["id"], "source": r["source"], "key": r["key"], "n": r["n"],
                "title": red.text(r["title"] or ""), "state": r["state"],
                "outcome": r["outcome"], "started": r["started"], "ended": r["ended"],
                "wall_s": wall, "usd": r["usd"],
                "usd_kind": "exact" if r["usd"] is not None else "none",
                "tokens": {"in": r["tokens_in"] or 0, "out": r["tokens_out"] or 0},
                "sessions": r["sessions"] or 0, "tools": r["tools"] or 0,
                "errors": r["errors"] or 0, "failed_at": r["failed_at"],
                "failed_label": red.text(r["failed_label"]) if r["failed_label"] else None,
                "model": r["model"], "spans": None, "href": _href(r["key"], r["n"], r["source"])}

    # -- one trace ---------------------------------------------------------------------------
    def summary(self, tid: str) -> dict:
        o = self.get(tid)
        t, red = o.t, Redactor()
        stages = [s for s in sorted(t.spans.values(), key=lambda s: s.pos) if s.kind == "stage"]
        # what a stage holds, in the fold's words: its sessions, their turns, its one-shot calls
        held: dict[str, dict[str, int]] = {s.id: {"sessions": 0, "turns": 0, "calls": 0}
                                           for s in stages}
        for sp in t.spans.values():
            up = t.spans.get(sp.parent) if sp.parent else None
            if sp.kind in ("session", "call") and sp.parent in held:
                held[sp.parent]["sessions" if sp.kind == "session" else "calls"] += 1
            elif sp.kind == "turn" and up is not None and up.parent in held:
                held[up.parent]["turns"] += 1
        rows = []
        for s in stages:
            r = self._row(s, o, red)
            r.setdefault("attrs", {}).update(held[s.id])
            rows.append(r)
        return {**self._trace_summary(t, red),
                "stages": rows,
                "links": [{**lk, "note": red.text(lk.get("note")) if lk.get("note") else None,
                           "detail": red.text(lk["detail"]) if isinstance(lk.get("detail"), str)
                           else None} for lk in t.links],
                "files": self.files(t), "cursor": encode_cursor(o.rev, -1, o.epoch),
                "running": t.running,
                "note": red.text(t.summary["note"]) if t.summary.get("note") else None,
                # a server run's plain head line and its Stop, while it runs
                "line": red.text(t.summary["line"]) if t.summary.get("line") else None,
                "stop": t.summary.get("stop")}

    def _trace_summary(self, t: Trace, red: Redactor) -> dict:
        s = t.summary
        extra = {"calls": s["calls"]} if s.get("calls") is not None else {}   # a Watching run's
        return {**extra, "id": s["id"], "source": s["source"], "key": s["key"], "n": s["n"],
                "title": red.text(s["title"] or ""), "state": s["state"],
                "outcome": s.get("outcome"), "started": s["started"], "ended": s["ended"],
                "wall_s": s["wall_s"], "usd": s["usd"], "usd_kind": s["usd_kind"],
                "tokens": s["tokens"], "sessions": s["sessions"], "tools": s["tools"],
                "errors": s["errors"], "failed_at": s["failed_at"],
                "failed_label": red.text(failed_label(t) or "") or None, "model": s["model"],
                "spans": s["spans"], "href": _href(s["key"], s["n"], s["source"])}

    @staticmethod
    def _row(sp, o: Open, red: Redactor) -> dict:
        r = sp.summary()
        r["name"] = red.text(r["name"])
        r["preview"] = red.text(r["preview"])
        if r["error"]:
            r["error"] = red.text(r["error"])
        r["rev"] = o.revs.get(sp.id, 0)
        for k in ("unlisted_usd", "children_usd", "file_path", "lines_added", "lines_removed",
                  "model", "turns", "level", "why", "runs"):
            if sp.attrs.get(k) is not None:
                r.setdefault("attrs", {})[k] = red.text(sp.attrs[k]) \
                    if isinstance(sp.attrs[k], str) else sp.attrs[k]
        return r

    def search(self, tid: str, q: str) -> dict:
        """Every payload of the trace searched for the words (``search.py``): the hits in tree
        order with a redacted preview each, at most 500."""
        from .search import search
        if not str(q or "").strip():
            raise TraceError(400, "q is required: the words to look for")
        o = self.get(tid)
        with o.lock:
            out = search(o.t, q, max_bytes=self.max_bytes)
        return {**out, "rev": o.rev}

    def spans(self, tid: str, after: str | None = None, limit: int | None = None,
              parent: str | None = None, filter: str | None = None, q: str | None = None,
              payloads: bool = False) -> dict:
        o = self.get(tid)
        t, red = o.t, Redactor()
        limit = max(1, min(int(limit or LIMIT), LIMIT_MAX))
        order = o.order
        if parent is not None:
            if parent not in t.spans:
                raise TraceError(404, "no such span in this trace")
            kids = [s for s in order if s.parent == parent]
            return {"spans": [self._row(s, o, red) for s in kids[:limit]],
                    "cursor": encode_cursor(o.rev, -1, o.epoch), "more": len(kids) > limit,
                    "total": len(kids), "rev": o.rev}
        if filter or q:
            keep, hits = self._filtered(o, filter, q, payloads)
            rows = [s for s in order if s.id in keep]
            return {"spans": [self._row(s, o, red) for s in rows[:LIMIT_MAX]],
                    "cursor": encode_cursor(o.rev, -1, o.epoch), "more": len(rows) > LIMIT_MAX,
                    "total": len(rows), "rev": o.rev,
                    "matches": [s.id for s in order if s.id in hits]}
        cur = decode_cursor(after)
        r0, p0 = cur if cur is not None else (0, -1)
        if cur is not None and (r0 < o.reset or cursor_epoch(after) != o.epoch):
            raise TraceError(422, "the trace was read again from its files; read from the top")
        changed = sorted((t.spans[sid] for sid, rv in o.revs.items()
                          if rv > r0 and sid in t.spans and t.spans[sid].pos <= p0),
                         key=lambda s: s.pos) if cur is not None else []
        page = order[p0 + 1:p0 + 1 + limit]          # a span's pos is its place in order
        last = page[-1].pos if page else p0
        more = bool(page) and last < order[-1].pos
        return {"spans": [self._row(s, o, red) for s in changed + page],
                "cursor": encode_cursor(o.rev, last, o.epoch), "more": more, "total": len(order),
                "rev": o.rev, "running": t.running}

    def _filtered(self, o: Open, flt: str | None, q: str | None,
                  payloads: bool = False) -> tuple[set, set]:
        """``(the spans to show, the spans that matched)``. ``errors``: the error spans;
        ``tool:<name>``, ``stage:<name>``, ``kind:<kind>``, ``cost:<usd>`` (at least); ``q``:
        the words, in the name, the preview or the call's text; with ``payloads`` also in every
        payload the trace's files hold (``search.py``). The matches' ancestors are shown too,
        so the tree still reads."""
        t = o.t
        sel = set(t.spans)
        for part in [p for p in str(flt or "").split(",") if p]:
            name, _, arg = part.partition(":")
            if name not in FILTERS:
                raise TraceError(400, f"filter is one of {', '.join(FILTERS)}")
            if name == "errors":
                cur = {s.id for s in t.spans.values() if s.status == "error"}
            elif name == "tool":
                cur = {s.id for s in t.spans.values() if s.attrs.get("tool") == arg}
            elif name == "stage":
                cur = {s.id for s in t.spans.values() if s.stage == arg}
            elif name == "kind":
                cur = {s.id for s in t.spans.values() if s.kind in arg.split("|")}
            else:
                try:
                    floor = float(arg)
                except ValueError:
                    raise TraceError(400, "cost:<usd> takes a number") from None
                cur = {s.id for s in t.spans.values() if (s.usd or 0) >= floor}
            sel &= cur
        hits = set(sel)
        if q:
            words = [w.lower() for w in str(q).split()][:8]
            owner = {sid: r for r in t.streams.values() for sid in r.args}
            found = set()
            for sid in sel:
                sp = t.spans[sid]
                r = owner.get(sid)
                hay = f"{sp.name}\n{sp.preview}\n{r.text(sid) if r else ''}".lower()
                if all(w in hay for w in words):
                    found.add(sid)
            if payloads:
                from .search import search
                found |= {h["span"] for h in search(t, q, max_bytes=self.max_bytes)["hits"]
                          if h["span"] in sel}
            hits = found
        keep = set()
        for sid in hits:
            cur, hops = t.spans.get(sid), 0
            while cur is not None and cur.id not in keep and hops < 64:
                keep.add(cur.id)
                cur = t.spans.get(cur.parent) if cur.parent else None
                hops += 1
        return keep, hits

    def span(self, tid: str, sid: str) -> dict:
        o = self.get(tid)
        sp = o.t.spans.get(sid)
        if sp is None:
            raise TraceError(404, "no such span in this trace")
        red = Redactor()
        full = sp.full()
        out = {**self._row(sp, o, red), "attributes": red.value(full["attributes"]),
               "events": red.value(full["events"]), "links": red.value(full["links"]),
               "inputs": full["inputs"], "outputs": full["outputs"],
               "source": {"file": (sp.source or {}).get("file"),
                          "line": (sp.source or {}).get("line")},
               "error_detail": red.value(full["error_detail"]),
               "path": str(o.t.taskdir / (sp.source or {}).get("file", "")) if sp.source
               else None}
        out["redactions"] = red.report()
        return out

    def follow(self, tid: str) -> dict:
        """Watch the trace's files for a while; renewed by each call. A trace
        that is over is not watched: nothing will change."""
        from ..ui.live import FOLLOW_S, FOLLOWS
        o = self.get(tid)
        if o.t.running:
            t = o.t
            FOLLOWS.add(tid, t.files, FOLLOW_S)
        return {"cursor": encode_cursor(o.rev, len(o.order) - 1, o.epoch), "running": o.t.running,
                "until": FOLLOW_S if o.t.running else 0.0}

    def payload(self, tid: str, sid: str, part: str, offset: int = 0) -> dict:
        o = self.get(tid)
        try:
            with o.lock:
                return payload(o.t, sid, part, offset)
        except PayloadError as e:
            raise TraceError(e.code, str(e)) from None

    def download(self, tid: str) -> dict:
        """The trace with every tool's input and output, redacted, capped a span."""
        o = self.get(tid)
        red = Redactor()
        spans = []
        for sp in sorted(o.t.spans.values(), key=lambda s: s.pos):
            row = {**self._row(sp, o, red), "attributes": red.value(sp.attrs)}
            if sp.kind in ("tool", "subagent", "turn"):
                for part in ("input", "output"):
                    try:
                        p = payload(o.t, sp.id, part, red=red)
                    except PayloadError as e:
                        p = {"error": str(e)}
                    p.pop("redactions", None)
                    row[part] = p
            spans.append(row)
        return {"trace": self._trace_summary(o.t, red), "links": red.value(o.t.links),
                "spans": spans, "redactions": red.report()}


def _href(key: str, n: int | None, source: str = "build") -> str | None:
    """The trace's page (lib/nodes.json: sessions/:tid/trace, afk/:uuid/trace); None for a
    trace that no longer opens (the build loop's) or a source with no page."""
    from urllib.parse import quote
    if source in ("session", "research", "afk"):
        return f"#/{source}{'s' if source == 'session' else ''}/{quote(key, safe='')}/trace"
    return None


_TRACES: dict[tuple, Traces] = {}


def for_app(app) -> Traces:
    """The app's ``Traces`` (one per loop home), with the loop's settings. ``trace.db`` is the
    archive, read-only: the index of the traces read now is in memory."""
    from ..settings.store import Config
    cfg = Config(app.loop_home)
    tr = cfg.get("trace") or {}
    key = (str(cfg.home), int(tr.get("page_kb") or 64), int(tr.get("payload_max_mb") or 2))
    t = _TRACES.get(key)
    if t is None:
        home = Path(cfg.home)
        t = _TRACES[key] = Traces(None, page_kb=key[1], payload_max_mb=key[2],
                                  loop_home=home, archive=home / "trace.db",
                                  afk_fetch=lambda p: app.afk("GET", p, owner=True),
                                  afk_mirror=lambda: Path(app.kranto_data) / "activity.json"
                                  if getattr(app, "kranto_data", None) else None)
    return t
