"""One bad row never takes a page down, and every error Kranto says has an
id the person can send (B3).

A list the API builds row by row builds each row inside ``row()`` (or ``each()``). A row that
raises is still listed: ``unreadable()`` puts in its place a row with its id, the words
"Couldn't read this <thing>" and ``unreadable: {what, words, error_id, exception}``. The answer
is never a 500 for one row. A response that still fails is answered by the app's error handler
(``web/app.py``) with the same id, the version, Try again and Send this error.

**The error id** is the first eight hex digits of ``errtrace``'s signature (the one scrubber:
the exception's class and Kranto's own frames, without their lines). ``errtrace`` says the frames
as ``module.function:line`` and the message as a template of known words, so a value, a path or
a token cannot reach the id, the file or the report. The same bug on every row of every request
is one id, and the telemetry's error reports (B1) carry the same signature.

**Each id is kept once** per process (``note()``): one log line with the traceback for the
journal, and one line in ``<Kranto data>/errors.jsonl`` (at most ``KEEP`` lines; the oldest go)
that ``kranto report``, ``GET /api/errors/<id>``, the post-update self-check and the telemetry's
error reports read. The page keeps the same file, in the same shape, with the same ids
(``src/kranto/page/rowsafe.py``).

**The report** (``report()``) is what Send this error and ``kranto report`` send: the id, the
exception's class, the scrubbed frames, where it happened, the version, the OS family and the
last ``kranto doctor``'s summary (its counts and the names of the checks that were not OK, never
their details). Nothing in it comes from the person's data.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import threading
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

FILE = "errors.jsonl"
DOCTOR_FILE = "doctor.json"
KEEP = 200
MAX_FRAMES = 8

_lock = threading.Lock()
_seen: dict[str, dict] = {}
_dir: Path | None = None


def configure(data_dir: Path | str | None) -> None:
    """Where ``errors.jsonl`` is kept: the server's data folder (``create_app`` sets it)."""
    global _dir
    _dir = Path(data_dir) if data_dir else None


def where_kept() -> Path | None:
    return _dir / FILE if _dir else None


def _kept(eid: str) -> dict | None:
    """The record ``errors.jsonl`` already keeps for ``eid``, if any: a failure kept before a
    restart or an update is not new (#488: a stored incident was logged again as a new error at
    each update, since every activity read notes it and a new process had seen nothing)."""
    path = where_kept()
    if path is None or not path.exists():
        return None
    try:
        for line in reversed(path.read_text().splitlines()):
            if f'"{eid}"' not in line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and rec.get("id") == eid:
                return rec
    except (OSError, ValueError):
        return None
    return None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _version() -> str:
    from . import __version__
    return __version__


def frames(exc: BaseException, limit: int = MAX_FRAMES) -> list[str]:
    """Kranto's own frames of ``exc``'s traceback (``errtrace``: outermost first, as
    ``module.function:line``), the innermost ``limit``: no values, no paths, no message."""
    from . import errtrace
    return [f for f in errtrace.scrub(exc).frames if not f.startswith("[")][-limit:]


def error_id(exc: BaseException) -> str:
    """Eight hex digits: the start of ``errtrace``'s signature (the type and Kranto's own frames
    without their lines), the same for the same bug wherever and in whichever release it
    happens, and the telemetry's error reports' signature begins with it."""
    from . import errtrace
    return errtrace.scrub(exc).signature[:8]


def note(exc: BaseException, where: str, *, kind: str = "row") -> dict:
    """Keep ``exc`` once by its id: the log line (with the traceback, for the journal) and the
    line in ``errors.jsonl`` are written the first time this process sees the id. Returns the
    record. Never raises."""
    from . import errtrace
    try:
        t = errtrace.scrub(exc)
        eid = t.signature[:8]
        record = {"id": eid, "at": _now(), "kind": kind, "where": str(where)[:120],
                  "exception": t.type, "message": t.message, "signature": t.signature,
                  "frames": [f for f in t.frames if not f.startswith("[")][-MAX_FRAMES:],
                  "version": _version()}
    except Exception:  # noqa: BLE001 - the net itself must never fail the page
        return {"id": "00000000", "kind": kind, "where": str(where)[:120],
                "exception": type(exc).__name__, "frames": [], "version": "?"}
    with _lock:
        first = eid not in _seen
        if first:
            _seen[eid] = record
    if first:
        log.error("error %s (%s) in %s; it is shown as its id from now on", eid,
                  record["exception"], record["where"], exc_info=exc)
        _keep(record)
    if kind == "row":
        # a row's error never escapes a route, so the telemetry's hook (timing.py) never sees
        # it: reported here, each time, if the person chose to send (ERR, B1; never raises)
        from .telemetry import errors
        errors.report(exc, "row")
    return _seen.get(eid, record)


def note_failure(kind: str, message: str | None, *, where: str | None = None) -> dict:
    """A failure with no exception (a job's run that failed, Activity's Fix row): kept once by
    an id from ``errtrace.failure`` (its kind; the message as a template), so Send this error
    can file it like any other. Never raises."""
    import re

    from . import errtrace
    name = re.sub(r"[^A-Za-z0-9_.]", "_", str(kind or "job"))[:60].strip(".") or "job"
    try:
        t = errtrace.failure(name, message or "")
        eid = t.signature[:8]
        record = {"id": eid, "at": _now(), "kind": "failure", "where": (where or
                  f"job:{name}")[:120], "exception": t.type, "message": t.message,
                  "signature": t.signature, "frames": [], "version": _version()}
    except Exception:  # noqa: BLE001
        return {"id": "00000000", "kind": "failure", "where": f"job:{name}",
                "exception": name, "frames": [], "version": "?"}
    with _lock:
        first = eid not in _seen
        if first:
            _seen[eid] = _kept(eid) or record
            first = _seen[eid] is record
    if first:
        log.warning("failure %s (%s) kept for Send this error", eid, record["where"])
        _keep(record)
    return _seen.get(eid, record)


def _keep(record: dict) -> None:
    path = where_kept()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text().splitlines() if path.exists() else []
        lines = [x for x in lines if x.strip()][-(KEEP - 1):] + [json.dumps(record)]
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("could not keep error %s in %s: %s", record["id"], path, exc)


def words(what: str) -> str:
    return f"Couldn't read this {what}"


def unreadable(what: str, ident, exc: BaseException, *, where: str | None = None,
               **keep) -> dict:
    """The row that stands for one that raised: its id, what the caller could still say of it
    (``keep``: a label, a kind) and ``unreadable``."""
    rec = note(exc, where or f"list:{what}")
    return {**{k: v for k, v in keep.items() if v is not None}, "id": ident,
            "unreadable": {"what": what, "words": words(what), "error_id": rec["id"],
                           "exception": rec["exception"]}}


@contextlib.contextmanager
def row(out: list, what: str, ident, *, where: str | None = None, **keep):
    """Build one row of ``out`` inside this block; if it raises, the row is ``unreadable``
    (in place of anything the block had already appended) and the list goes on."""
    n = len(out)
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - one row never fails the list
        del out[n:]
        out.append(unreadable(what, ident, exc, where=where, **keep))


def each(items, build, what: str, *, ident=None, where: str | None = None, keep=None) -> list:
    """``[build(x) for x in items]``, a row that raises listed as ``unreadable``. ``ident(x)``
    is its id (default ``x.id``, ``x["id"]``), ``keep(x)`` what else it still says."""
    out: list = []
    for x in items:
        with row(out, what, _ident(x, ident), where=where, **(_safe(keep, x) or {})):
            out.append(build(x))
    return out


def readable(items, build, what: str, *, ident=None) -> list:
    """``each`` for a reader whose schema has no unreadable row (a cub's v1 read): a row that
    raises is left out, and kept once by its id like any other."""
    return [r for r in each(items, build, what, ident=ident) if not is_unreadable(r)]


def _ident(x, ident):
    try:
        if ident is not None:
            return ident(x)
        if isinstance(x, dict):
            return x.get("id")
        return getattr(x, "id", None)
    except Exception:  # noqa: BLE001
        return None


def _safe(fn, x):
    if fn is None:
        return None
    try:
        return fn(x)
    except Exception:  # noqa: BLE001
        return None


def is_unreadable(r) -> bool:
    return isinstance(r, dict) and isinstance(r.get("unreadable"), dict)


class Unreadable(Exception):
    """An object's own page asked for a row that could not be read: the page answers with the
    error page under that row's error id (no second id for the same bug)."""

    def __init__(self, r: dict) -> None:
        self.row = r
        self.error_id = r["unreadable"]["error_id"]
        super().__init__(r["unreadable"]["words"])


# -- what is kept, and what is sent -------------------------------------------------------------


def kept(path: Path | None = None) -> list[dict]:
    """The errors kept in ``errors.jsonl``, oldest first (this process's too)."""
    path = path or where_kept()
    out: list[dict] = []
    try:
        lines = path.read_text().splitlines() if path else []
    except OSError:
        lines = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            out.append(r)
    with _lock:
        have = {r["id"] for r in out}
        out += [r for r in _seen.values() if r["id"] not in have]
    return out


def find(eid: str, path: Path | None = None) -> dict | None:
    """The newest record kept under ``eid``."""
    eid = (eid or "").strip().lower()
    with _lock:
        if eid in _seen:
            return _seen[eid]
    return next((r for r in reversed(kept(path)) if r["id"] == eid), None)


def os_family() -> str:
    s = platform.system()
    return {"Darwin": "macOS"}.get(s, s or "unknown")


def keep_doctor(data_dir: Path, checks) -> None:
    """Keep ``kranto doctor``'s summary for the reports: the counts by status and the names of
    the checks that were not OK (never their details: they name paths and accounts)."""
    counts: dict[str, int] = {}
    names: dict[str, list[str]] = {}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
        if c.status != "ok":
            names.setdefault(c.status, []).append(str(c.name)[:30])
    try:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        (Path(data_dir) / DOCTOR_FILE).write_text(json.dumps(
            {"at": _now(), "counts": counts, "not_ok": names}) + "\n")
    except OSError:
        pass


def doctor_line(data_dir: Path | None) -> str:
    """``kranto doctor``'s last summary in a line, or that it has not run."""
    try:
        d = json.loads((Path(data_dir) / DOCTOR_FILE).read_text()) if data_dir else None
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict):
        return "not run yet (kranto doctor)"
    counts = d.get("counts") or {}
    parts = [f"{counts[k]} {k.lower()}" for k in ("ok", "warn", "FAIL") if counts.get(k)]
    bad = "; ".join(f"{k}: {', '.join(v)}" for k, v in (d.get("not_ok") or {}).items() if v)
    return f"{', '.join(parts) or 'no checks'} ({str(d.get('at') or '')[:16]})" + \
        (f"; {bad}" if bad else "")


REPO = "iddv/kranto"
# the release repository's issue form (.github/ISSUE_TEMPLATE/feedback.yml): it takes no blank
# issue, so the link names the form, whose one field's id is ``body`` (FB)
TEMPLATE = "feedback.yml"


def issue_url(title: str, body: str, repo: str = REPO) -> str:
    """GitHub's new-issue page with the report filled in (the person presses Submit)."""
    from urllib.parse import quote
    return (f"https://github.com/{repo}/issues/new?template={TEMPLATE}"
            f"&title={quote(title, safe='')}&body={quote(body, safe='')}"
            f"&labels={quote('feedback,bug', safe='')}")


def said(eid: str) -> str:
    """What a failed answer says: the id is in the words, so any page that shows them can find
    the report (``Failed`` reads it there)."""
    return f"Something went wrong on Kranto's side (error {eid}). Try again, or send this error."


def report(record: dict, data_dir: Path | None = None) -> dict:
    """What Send this error and ``kranto report`` send for one kept error: ``title`` and
    ``body`` (markdown), every part Kranto's own words, ids and code locations."""
    data_dir = data_dir or _dir
    frames_ = [f for f in record.get("frames") or [] if isinstance(f, str)][:MAX_FRAMES]
    title = f"Error {record.get('id')}: {record.get('exception')} in {record.get('where')}"
    lines = [
        "### Error Kranto caught",
        f"- error id: `{record.get('id')}`",
        f"- what: {record.get('exception')} ({record.get('kind') or 'row'}, "
        f"{record.get('where')})",
        *([f"- message, as a template: {record['message']}"] if record.get("message") else []),
        f"- first seen: {record.get('at')}",
        f"- Kranto: {record.get('version') or _version()} (running {_version()})",
        f"- OS: {os_family()}",
        f"- kranto doctor: {doctor_line(data_dir)}",
        "",
        "Where in Kranto's code (outermost first; no values, no paths):",
        "```",
        *(frames_ or ["(no frame of Kranto's own code)"]),
        "```",
    ]
    return {"id": record.get("id"), "title": title[:120], "body": "\n".join(lines) + "\n"}
