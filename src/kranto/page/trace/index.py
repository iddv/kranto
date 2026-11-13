"""The trace index (decision D-8): ``<loop home>/trace.db``, a
rebuildable **cache** of trace summaries and span summaries with their file positions, never
of payloads. Not a migration of ``loop.db``: a version this reader does not know, or a file
SQLite cannot open, is set aside (``trace.db.bad-<ts>``) and built again from the files.

- ``traces``: one row per trace, with the signature of its files (sizes and times), so the
  trace list reads a build's files again only when they changed;
- ``spans``: the open trace's spans in tree order (``seq`` is the depth-first position), with
  their file and byte range and a 240-character text column for search (FTS5 when this
  SQLite has it, else ``LIKE``);
- ``trace_files``: each file's size, time and read offset (the cursor's positions).

Only Kranto's process writes it; the CLI reads it read-only and falls back to the files."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .. import migrate

VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, source TEXT, key TEXT, n INTEGER,
  title TEXT, state TEXT, started REAL, ended REAL, usd REAL, tokens_in INTEGER,
  tokens_out INTEGER, sessions INTEGER, tools INTEGER, errors INTEGER, failed_at TEXT,
  failed_label TEXT, outcome TEXT, model TEXT, root TEXT, sig TEXT, indexed_at REAL);
CREATE INDEX IF NOT EXISTS traces_started ON traces (started);
CREATE TABLE IF NOT EXISTS trace_files (trace TEXT, rel TEXT, size INTEGER, mtime REAL,
  offset INTEGER, PRIMARY KEY (trace, rel));
CREATE TABLE IF NOT EXISTS spans (id TEXT, trace TEXT, parent TEXT, seq INTEGER, kind TEXT,
  name TEXT, stage TEXT, start REAL, "end" REAL, status TEXT, usd REAL, usd_kind TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cache_read INTEGER, cache_write INTEGER,
  thinking INTEGER, depth INTEGER, file TEXT, line INTEGER, byte_from INTEGER, byte_to INTEGER,
  text TEXT, attrs TEXT, error TEXT, PRIMARY KEY (trace, id));
CREATE INDEX IF NOT EXISTS spans_trace ON spans (trace, seq);
CREATE INDEX IF NOT EXISTS spans_parent ON spans (trace, parent, seq);
CREATE INDEX IF NOT EXISTS spans_err ON spans (trace, status);
CREATE INDEX IF NOT EXISTS spans_tool ON spans (trace, kind, name);
CREATE TABLE IF NOT EXISTS links (trace TEXT, src TEXT, dst TEXT, kind TEXT, note TEXT);
"""
TRACE_COLS = ("id", "source", "key", "n", "title", "state", "started", "ended", "usd",
              "tokens_in", "tokens_out", "sessions", "tools", "errors", "failed_at",
              "failed_label", "outcome", "model", "root", "sig", "indexed_at")


def _query(source=None, key=None, state=None, since=None, limit=50, before=None):
    where, args = [], []
    for col, v in (("source", source), ("key", key), ("state", state)):
        if v:
            where.append(f"{col}=?")
            args.append(v)
    if since:
        where.append("started>=?")
        args.append(since)
    if before is not None:
        where.append("started<?")
        args.append(before)
    sql = (f"SELECT {', '.join(TRACE_COLS)} FROM traces"
           + (f" WHERE {' AND '.join(where)}" if where else "")
           + " ORDER BY started DESC LIMIT ?")
    return sql, (*args, int(limit))


def archived(path: Path | None, **q) -> list[dict]:
    """The trace rows a ``trace.db`` keeps (``Index.traces``' filters), read-only: the file is
    never written, created or set aside here. No file, another version's, or one SQLite cannot
    read: none."""
    if path is None or not Path(path).is_file():
        return []
    try:
        c = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=2)
        try:
            v = c.execute("SELECT v FROM trace_meta WHERE k='version'").fetchone()
            if not v or v[0] != VERSION:
                return []
            sql, args = _query(**q)
            return [dict(zip(TRACE_COLS, r)) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()
    except sqlite3.Error:
        return []


class Index:
    """``Index(path)``; ``path`` None: in memory (a test, or a home that has no loop)."""

    def __init__(self, path: Path | None):
        self.path = Path(path) if path is not None else None
        self.lock = threading.Lock()
        self.fts = False
        self.db = self._open()

    # -- opening, or setting a bad file aside ------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path) if self.path else ":memory:", timeout=10,
                            check_same_thread=False)
        if self.path:
            migrate.wal(c, 10)
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def _open(self) -> sqlite3.Connection:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            c = self._connect()
            row = c.execute("SELECT name FROM sqlite_master WHERE name='trace_meta'").fetchone()
            v = c.execute("SELECT v FROM trace_meta WHERE k='version'").fetchone() if row else None
            if row and (v is None or v[0] != VERSION):
                c.close()
                self._drop()                         # another version's cache: no migration
                c = self._connect()
            c.executescript(SCHEMA)
        except sqlite3.DatabaseError:
            self._set_aside()
            c = self._connect()
            c.executescript(SCHEMA)
        c.execute("INSERT OR REPLACE INTO trace_meta VALUES ('version', ?)", (VERSION,))
        c.execute("INSERT OR IGNORE INTO trace_meta VALUES ('built_at', ?)", (str(time.time()),))
        try:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS spans_fts USING fts5 "
                      "(text, trace UNINDEXED, id UNINDEXED)")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False                         # no FTS5 here: LIKE does
        c.commit()
        return c

    def _drop(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def _set_aside(self) -> None:
        """A file SQLite cannot read: renamed ``trace.db.bad-<ts>``, never deleted."""
        if self.path is None:
            return
        if self.path.exists():
            self.path.rename(self.path.with_name(f"{self.path.name}.bad-{int(time.time())}"))
        for suffix in ("-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def version(self) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT v FROM trace_meta WHERE k='version'").fetchone()
        return row[0] if row else None

    # -- traces ------------------------------------------------------------------------------
    def trace_row(self, tid: str) -> dict | None:
        with self.lock:
            row = self.db.execute(f"SELECT {', '.join(TRACE_COLS)} FROM traces WHERE id=?",
                                  (tid,)).fetchone()
        return dict(zip(TRACE_COLS, row)) if row else None

    def put_trace(self, summary: dict, sig: str, failed_label: str | None = None,
                  files: list[dict] | None = None) -> None:
        tok = summary.get("tokens") or {}
        tin = sum(int(tok.get(k) or 0) for k in ("in", "cache_read", "cache_write"))
        row = (summary["id"], summary["source"], summary["key"], summary.get("n"),
               summary.get("title"), summary.get("state"), summary.get("started"),
               summary.get("ended"), summary.get("usd"), tin, int(tok.get("out") or 0),
               summary.get("sessions"), summary.get("tools"), summary.get("errors"),
               summary.get("failed_at"), failed_label, summary.get("outcome"),
               summary.get("model"), summary.get("root"), sig, time.time())
        with self.lock, self.db:
            self.db.execute(f"INSERT OR REPLACE INTO traces ({', '.join(TRACE_COLS)}) VALUES "
                            f"({', '.join('?' * len(TRACE_COLS))})", row)
            if files is not None:
                self.db.execute("DELETE FROM trace_files WHERE trace=?", (summary["id"],))
                self.db.executemany(
                    "INSERT INTO trace_files VALUES (?, ?, ?, ?, ?)",
                    [(summary["id"], f["rel"], f.get("bytes"), f.get("mtime"), f.get("offset"))
                     for f in files])

    def traces(self, source: str | None = None, key: str | None = None,
               state: str | None = None, since: float | None = None, limit: int = 50,
               before: float | None = None) -> list[dict]:
        """Newest first; ``before``: the page after the one that ended at that start."""
        sql, args = _query(source, key, state, since, limit, before)
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [dict(zip(TRACE_COLS, r)) for r in rows]

    def forget(self, keep: set[str]) -> None:
        """Rows of traces whose build is gone (its folder removed)."""
        with self.lock, self.db:
            have = [r[0] for r in self.db.execute("SELECT id FROM traces")]
            for tid in have:
                if tid not in keep:
                    self._drop_trace(tid)

    def _drop_trace(self, tid: str) -> None:
        for table in ("traces", "trace_files", "spans", "links"):
            col = "id" if table == "traces" else "trace"
            self.db.execute(f"DELETE FROM {table} WHERE {col}=?", (tid,))
        if self.fts:
            self.db.execute("DELETE FROM spans_fts WHERE trace=?", (tid,))

    # -- spans -------------------------------------------------------------------------------
    def put_spans(self, tid: str, spans, texts: dict[str, str], links: list[dict]) -> None:
        """Every span of the trace, replacing what was there (one transaction)."""
        rows, fts = [], []
        for sp in spans:
            t = sp.tokens or {}
            src = sp.source or {}
            text = " ".join(x for x in (sp.name, sp.preview, texts.get(sp.id, "")[:240]) if x)
            rows.append((sp.id, tid, sp.parent, sp.pos, sp.kind, sp.name, sp.stage, sp.start,
                         sp.end, sp.status, sp.usd, sp.usd_kind, t.get("in"), t.get("out"),
                         t.get("cache_read"), t.get("cache_write"), t.get("thinking"),
                         sp.depth, src.get("file"), src.get("line"), src.get("from"),
                         src.get("to"), text, json.dumps(sp.attrs, default=str)[:4000],
                         (sp.error or {}).get("message")))
            fts.append((text, tid, sp.id))
        with self.lock, self.db:
            self.db.execute("DELETE FROM spans WHERE trace=?", (tid,))
            self.db.execute("DELETE FROM links WHERE trace=?", (tid,))
            self.db.executemany(f"INSERT INTO spans VALUES ({', '.join('?' * 25)})", rows)
            self.db.executemany("INSERT INTO links VALUES (?, ?, ?, ?, ?)",
                                [(tid, lk.get("ref"), lk.get("span"), lk.get("kind"),
                                  lk.get("note")) for lk in links])
            if self.fts:
                self.db.execute("DELETE FROM spans_fts WHERE trace=?", (tid,))
                self.db.executemany("INSERT INTO spans_fts VALUES (?, ?, ?)", fts)

    def search(self, tid: str, q: str, limit: int = 500) -> list[str]:
        """Span ids whose name, preview or text match ``q`` (words, all of them)."""
        words = [w for w in str(q or "").split() if w][:8]
        if not words:
            return []
        with self.lock:
            if self.fts:
                expr = " AND ".join('"' + w.replace('"', '""') + '"' for w in words)
                try:
                    return [r[0] for r in self.db.execute(
                        "SELECT id FROM spans_fts WHERE trace=? AND spans_fts MATCH ? LIMIT ?",
                        (tid, expr, limit))]
                except sqlite3.OperationalError:
                    pass
            sql = ("SELECT id FROM spans WHERE trace=? AND "
                   + " AND ".join("text LIKE ? ESCAPE '\\'" for _ in words) + " LIMIT ?")
            pats = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                    for w in words]
            return [r[0] for r in self.db.execute(sql, (tid, *pats, limit))]

    def span_count(self, tid: str) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM spans WHERE trace=?", (tid,)).fetchone()[0]

    def close(self) -> None:
        with self.lock:
            self.db.close()
