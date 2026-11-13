"""Error reports: an error Kranto did not handle, with its cause, sent
within minutes in the person's telemetry choice.

**The rule.** Error reports follow the usage-report choice exactly. With ``basic`` or
``detailed`` (and an endpoint), an error is reported; with ``local``, ``off``, unanswered or
``DO_NOT_TRACK``, nothing is kept for sending and nothing is sent, and choosing ``off`` deletes
what was waiting. ``basic``: no identifier, and no time finer than the hour. ``detailed``: also
the random install id the daily report carries.

**What one report holds** (``schema.json``'s ``error``): ``errtrace.scrub``'s exception type,
scrubbed stack, message template and signature; where it happened (``api``, ``job``, ``row``,
``scheduler``, ``loop``, ``update``); the route's pattern or the job's kind, never an address or
its ids; how often it happened since that signature was last reported; and the resource every
report has (the version, the OS family, the tier).

**How.** ``report(exc, where, ...)`` never raises. In the server, it adds to this process's
pending reports, one per signature with a count; in any other process (the command line, the
update helper) it appends one line to ``<home>/telemetry/errors/spool.jsonl``, which the server
takes in. The server's flusher looks every ``TICK_S``: a signature never reported, or last
reported over ``RESEND_S`` ago, is due; a batch of at most ``MAX_BATCH`` goes once the oldest
due one has waited ``GATHER_S`` (so a burst goes as one batch), at most ``MAX_BATCHES_HOUR``
batches an hour and ``MAX_DAY`` reports a day; the rest waits, counted. A batch is checked
against the allow-list and the personal-data patterns before it leaves, posted like the daily
report (``send.post``), and its exact bytes kept in ``errors/sent/``
(``kranto telemetry show --sent``)."""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from .. import errtrace
from . import local, send
from . import schema as schema_mod

log = logging.getLogger("kranto.telemetry")

TICK_S = 30.0
GATHER_S = 60.0
RESEND_S = 3600.0
RETRY_S = 300.0
MAX_BATCH = 10
MAX_BATCHES_HOUR = 4
MAX_DAY = 50
MAX_PENDING = 200
SPOOL_BYTES = 256_000
SENT_KEEP = 200
EVENT = "kranto.error"

_lock = threading.Lock()
_pending: dict[str, dict] = {}
_dirty = False
_flusher: Flusher | None = None


def edir(home: Path) -> Path:
    return local.tdir(home) / "errors"


# -- reporting ---------------------------------------------------------------------------------

def _sending(home: Path | None) -> bool:
    if home is None:
        return False
    if local.configured() is not None and Path(home) == local.configured():
        return local.current_mode() in local.SENDING
    try:
        return local.effective(home).mode in local.SENDING
    except Exception:  # noqa: BLE001 - a broken config sends nothing
        return False


def _entry(trace: errtrace.Trace, where: str, route: str | None, job: str | None,
           now: float, verb: str | None = None) -> dict:
    enums = schema_mod.union()["enums"]
    out = {"signature": trace.signature, "type": trace.type,
           "where": where if where in enums["where"] else "api",
           "message": trace.message, "stack": trace.stack, "count": 1,
           "first": now, "last": now}
    if route is not None:
        out["route"] = route if route in enums["route"] else "other"
    if job is not None:
        out["job"] = job if job in enums["job"] else "other"
    if verb is not None:
        out["verb"] = verb if verb in enums["verb"] else "other"
    return out


def report(exc: BaseException, where: str, *, route: str | None = None,
           job: str | None = None, home: Path | None = None, verb: str | None = None) -> None:
    """Report an error, if the person chose to send (see the module's doc). Never raises.
    ``verb``: the console's own errors (``where: console``), the verb whose tool failed."""
    try:
        _add(home, errtrace.scrub(exc), where, route, job, verb)
    except Exception:  # noqa: BLE001 - reporting an error never makes another
        log.debug("error report not kept", exc_info=True)


def report_failure(type_: str, where: str, *, message: str = "", route: str | None = None,
                   job: str | None = None, home: Path | None = None,
                   verb: str | None = None) -> None:
    """Report a failure known only by a name and a message (a job's run that failed without
    raising, an update rolled back by its self-check). Never raises."""
    try:
        _add(home, errtrace.failure(type_, message), where, route, job, verb)
    except Exception:  # noqa: BLE001
        log.debug("error report not kept", exc_info=True)


def _add(home, trace: errtrace.Trace, where: str, route, job, verb=None) -> None:
    global _dirty
    home = Path(home) if home is not None else local.configured()
    if not _sending(home):
        return
    e = _entry(trace, where, route, job, time.time(), verb)
    fl = _flusher
    if fl is not None and fl.home == home:
        with _lock:
            _merge(e)
            _dirty = True
        return
    spool = edir(home) / "spool.jsonl"
    spool.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if spool.stat().st_size > SPOOL_BYTES:
            return
    except OSError:
        pass
    with open(spool, "a", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1, **e}, separators=(",", ":")) + "\n")


def _merge(e: dict) -> None:
    """Into ``_pending`` (the lock held): one entry per signature, its count added."""
    sig = e["signature"]
    have = _pending.get(sig)
    if have is None:
        if len(_pending) >= MAX_PENDING:
            return
        _pending[sig] = dict(e)
        return
    have["count"] = min(have["count"] + int(e.get("count") or 1), 1_000_000)
    have["last"] = max(have["last"], e.get("last") or e["first"])
    have["first"] = min(have["first"], e["first"])
    # the newest occurrence's, whole
    for k in ("where", "route", "job", "verb", "message", "stack"):
        if e.get(k) is not None:
            have[k] = e[k]
        else:
            have.pop(k, None)


def pending() -> list[dict]:
    """What waits to be sent in this process, oldest first."""
    with _lock:
        return sorted((dict(e) for e in _pending.values()), key=lambda e: e["first"])


def waiting(home: Path) -> list[dict]:
    """What waits to be sent from this install, oldest first: the server's pending reports
    (in memory here, else as it last saved them) and the lines other processes left."""
    fl = _flusher
    if fl is not None and fl.home == Path(home):
        return pending()
    merged: dict[str, dict] = {}
    try:
        items = json.loads((edir(home) / "pending.json").read_text())
    except (OSError, ValueError):
        items = []
    try:
        lines = (edir(home) / "spool.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for raw in lines:
        try:
            items.append(json.loads(raw))
        except ValueError:
            continue
    for e in items if isinstance(items, list) else ():
        if not isinstance(e, dict) or not isinstance(e.get("signature"), str):
            continue
        e.pop("v", None)
        have = merged.get(e["signature"])
        if have is None:
            merged[e["signature"]] = dict(e)
        else:
            have["count"] = have.get("count", 1) + int(e.get("count") or 1)
    return sorted(merged.values(), key=lambda e: e.get("first") or 0)


def preview(home: Path, tier: str, environ=None) -> dict:
    """What the next batch would hold, as it would be sent: ``{resource, reports, bytes,
    wire}`` (every report waiting, not only those due)."""
    entries = waiting(home)
    res, ok = build(home, entries, tier, environ)
    body = wire(res, ok) if ok else b""
    return {"resource": res, "reports": [record_of(e) for e in ok], "bytes": len(body),
            "wire": body.decode()}


# -- the batch ---------------------------------------------------------------------------------

FIELDS = ("signature", "type", "where", "route", "job", "verb", "message", "stack", "count")


def record_of(e: dict) -> dict:
    return {k: e[k] for k in FIELDS if e.get(k) is not None}


def hour_of(ts: float) -> int:
    return int(ts // 3600 * 3600)


def envelope(resource: dict, entries: list[dict]) -> dict:
    attrs = [send._attr("service.name", "kranto")]
    attrs += [send._attr(send.OTEL_NAMES.get(k, f"kranto.{k}"), v)
              for k, v in sorted(resource.items())]
    records = []
    for e in entries:
        rec = record_of(e)
        records.append({"timeUnixNano": str(hour_of(e["first"]) * 10**9), "severityNumber": 17,
                        "severityText": "ERROR", "body": {"stringValue": EVENT},
                        "attributes": [send._attr("event.name", EVENT)]
                        + [send._attr(f"kranto.{k}", v) for k, v in sorted(rec.items())]})
    return {"resourceLogs": [{"resource": {"attributes": attrs}, "scopeLogs": [
        {"scope": {"name": "kranto.telemetry", "version": "1"}, "logRecords": records}]}]}


def build(home: Path, entries: list[dict], tier: str, environ=None) -> tuple[dict, list[dict]]:
    """``(resource, the entries that pass)``: each record checked against the list and the
    personal-data patterns; one that fails either is left out (and logged by its key)."""
    from collections import Counter

    from ..scrub import scrub
    from .report import resource as resource_of

    res = resource_of(home, tier, environ)
    schema_mod.check_resource(res)
    ok = []
    for e in entries:
        rec = record_of(e)
        try:
            schema_mod.check_error(rec)
        except schema_mod.SchemaError as exc:
            log.warning("telemetry: an error report was not sent: %s", exc)
            continue
        hits: Counter = Counter()
        for v in rec.values():
            if isinstance(v, str):
                scrub(v, hits)
        if hits:
            log.warning("telemetry: an error report matched a personal-data pattern; not sent")
            continue
        ok.append(e)
    return res, ok


def wire(resource: dict, entries: list[dict]) -> bytes:
    return json.dumps(envelope(resource, entries), separators=(",", ":"),
                      sort_keys=True).encode()


# -- state, the spool, what was sent ------------------------------------------------------------

def read_state(home: Path) -> dict:
    try:
        st = json.loads((edir(home) / "state.json").read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(home: Path, st: dict) -> None:
    p = edir(home) / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(f".state.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, sort_keys=True) + "\n")
    os.replace(tmp, p)


def take_spool(home: Path) -> list[dict]:
    """The lines other processes left, taken (the file is moved away first, so a line written
    meanwhile goes to a new file)."""
    spool = edir(home) / "spool.jsonl"
    taking = spool.with_name(f"spool.{os.getpid()}.taking")
    try:
        os.replace(spool, taking)
    except OSError:
        return []
    out = []
    try:
        for raw in taking.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("v") == 1 and isinstance(d.get("signature"), str) \
                    and isinstance(d.get("first"), int | float):
                d.pop("v")
                out.append(d)
    finally:
        taking.unlink(missing_ok=True)
    return out


def _save_pending(home: Path) -> None:
    global _dirty
    with _lock:
        items = list(_pending.values())
        _dirty = False
    p = edir(home) / "pending.json"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(f".pending.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(items, sort_keys=True))
    os.replace(tmp, p)


def _load_pending(home: Path) -> None:
    try:
        items = json.loads((edir(home) / "pending.json").read_text())
    except (OSError, ValueError):
        return
    with _lock:
        for e in items if isinstance(items, list) else ():
            if isinstance(e, dict) and isinstance(e.get("signature"), str):
                _merge(e)


def _owns(home: Path) -> bool:
    """Whether what waits in memory is ``home``'s: this process's flusher is for it, or there
    is none. A flush or forget of another home never touches it (a flusher left
    from an earlier test, of a home whose mode said off, emptied the next test's reports)."""
    fl = _flusher
    return fl is None or Path(fl.home) == Path(home)


def forget(home: Path) -> None:
    """Delete what waits to be sent (``off``, or sending stopped)."""
    global _dirty
    if _owns(home):
        with _lock:
            _pending.clear()
            _dirty = False
    for name in ("spool.jsonl", "pending.json"):
        (edir(home) / name).unlink(missing_ok=True)


def sent(home: Path) -> list[dict]:
    """The batches sent, newest first: ``{id, at, status, bytes, gzip_bytes, endpoint, tier,
    reports}``."""
    out = []
    for meta in sorted((edir(home) / "sent").glob("*.meta.json"), reverse=True):
        try:
            out.append(json.loads(meta.read_text()))
        except (OSError, ValueError):
            continue
    return out


def sent_body(home: Path, batch: str) -> bytes | None:
    if not batch.replace("-", "").replace("T", "").isalnum():
        return None
    try:
        return (edir(home) / "sent" / f"{batch}.json").read_bytes()
    except OSError:
        return None


def _keep(home: Path, batch: str, body: bytes, meta: dict) -> None:
    d = edir(home) / "sent"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / f"{batch}.json").write_bytes(body)
    (d / f"{batch}.meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    metas = sorted(d.glob("*.meta.json"))
    for old in metas[:-SENT_KEEP]:
        old.unlink(missing_ok=True)
        (d / old.name.replace(".meta.json", ".json")).unlink(missing_ok=True)


# -- the flusher --------------------------------------------------------------------------------

def due(entries: list[dict], st: dict, now: float) -> list[dict]:
    """The entries that may go now, oldest first: never reported, or last reported at least
    ``RESEND_S`` ago."""
    last = st.get("sent") or {}
    return sorted((e for e in entries if now - float(last.get(e["signature"], 0)) >= RESEND_S),
                  key=lambda e: e["first"])


def room(st: dict, now: float) -> int:
    """How many reports the limits allow now (0: wait)."""
    if now < float(st.get("retry_at") or 0):
        return 0
    if len([t for t in st.get("batches") or () if now - t < 3600]) >= MAX_BATCHES_HOUR:
        return 0
    today = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    used = int(st.get("day_n") or 0) if st.get("day") == today else 0
    return max(0, min(MAX_BATCH, MAX_DAY - used))


def flush(home: Path, *, now: float | None = None, environ=None, transport=None) -> dict:
    """One look: take the spool in, and post one batch if one is due and the limits allow it.
    Returns what it did."""
    now = time.time() if now is None else now
    if not _owns(home):
        return {"sent": 0, "why": "another home's reports wait in this process: not sent"}
    eff = local.effective(home, environ)
    if eff.mode not in local.SENDING or not eff.endpoint:
        forget(home)
        return {"sent": 0, "why": f"{eff.mode}: nothing is sent" if eff.endpoint else
                "no endpoint is set: nothing is sent"}
    taken = take_spool(home)
    with _lock:
        for e in taken:
            _merge(e)
        entries = [dict(e) for e in _pending.values()]
    if taken:
        _save_pending(home)
    st = read_state(home)
    ready = due(entries, st, now)
    out: dict = {"sent": 0, "waiting": len(entries)}
    if not ready or now - ready[0]["first"] < GATHER_S:
        return out
    n = room(st, now)
    if not n:
        out["why"] = "the limits: the rest waits"
        return out
    take = ready[:n]
    res, ok = build(home, take, eff.mode, environ)
    refused = {e["signature"] for e in take} - {e["signature"] for e in ok}
    if refused:
        with _lock:
            for sig in refused:
                _pending.pop(sig, None)
    if not ok:
        _save_pending(home)
        return out
    body = wire(res, ok)
    try:
        status = send.post(eff.endpoint, body, transport=transport)
    except send.Unreached as exc:
        st["retry_at"] = now + RETRY_S
        write_state(home, st)
        out["unreached"] = str(exc)
        return out
    batch = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H%M%S")
    _keep(home, batch, body, {"id": batch, "at": datetime.fromtimestamp(now, UTC).isoformat(
        timespec="seconds"), "status": status, "bytes": len(body),
        "gzip_bytes": len(gzip.compress(body, 6, mtime=0)), "endpoint": eff.endpoint,
        "tier": eff.mode, "reports": len(ok)})
    with _lock:
        for e in ok:                     # what happened during the post stays, counted
            have = _pending.get(e["signature"])
            if have is not None and have["count"] > e["count"]:
                have["count"] -= e["count"]
                have["first"] = now
            else:
                _pending.pop(e["signature"], None)
    sent_at = st.get("sent") or {}
    for e in ok:
        sent_at[e["signature"]] = now
    st["sent"] = {k: v for k, v in sent_at.items() if now - float(v) < 7 * 86400}
    st["batches"] = [t for t in st.get("batches") or () if now - t < 3600] + [now]
    today = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    st["day_n"] = (int(st.get("day_n") or 0) if st.get("day") == today else 0) + len(ok)
    st["day"] = today
    st.pop("retry_at", None)
    write_state(home, st)
    _save_pending(home)
    out.update(sent=len(ok), status=status, batch=batch)
    return out


class Flusher:
    """The server's thread: ``flush`` every ``TICK_S``; what waits is saved when it stops."""

    def __init__(self, home: Path, tick_s: float = TICK_S) -> None:
        self.home, self.tick_s = Path(home), tick_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        _load_pending(self.home)
        self._thread = threading.Thread(target=self._run, name="kranto-error-reports",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        from . import assistant
        while not self._stop.wait(self.tick_s):
            if _flusher is not self:     # replaced, or let go of: this thread is no one's
                return
            try:
                flush(self.home)
                if _dirty:
                    _save_pending(self.home)
            except Exception:  # noqa: BLE001 - the reports never stop the server
                log.debug("error reports: a flush failed", exc_info=True)
            try:
                assistant.flush(self.home)
            except Exception:  # noqa: BLE001 - nor do the assistant's events
                log.debug("assistant events: a flush failed", exc_info=True)

    def stop(self) -> None:
        from . import assistant
        self._stop.set()
        assistant.stop(self.home)
        try:
            if _pending and _sending(self.home):
                _save_pending(self.home)
        except Exception:  # noqa: BLE001
            log.debug("error reports: what waits was not saved", exc_info=True)


def start(home: Path) -> Flusher:
    """Start this process's flusher (``kranto serve``): from now on ``report`` keeps reports in
    memory here and this thread sends them."""
    global _flusher
    if _flusher is not None:
        return _flusher
    from . import assistant
    assistant.start(home)
    fl = Flusher(home)
    fl.start()
    _flusher = fl
    atexit.register(fl.stop)
    return fl
