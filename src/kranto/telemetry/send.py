"""Sending (sections 4.4, 4.7): the report as one OTLP/JSON log record, gzipped,
posted once with a 5 s connect and 10 s read timeout; the exact bytes kept in
``<home>/telemetry/sent/<day>.json`` with what the server said.

Nothing is sent unless the mode is ``basic`` or ``detailed``: unanswered, ``local`` and ``off``
never reach the code that posts. The endpoint is ``$KRANTO_TELEMETRY_ENDPOINT``, else
``telemetry.endpoint``, else ``local.DEFAULT_ENDPOINT`` (the controller's relay). A day is sent
only if it began after the answer (so nothing is sent in the first day after it), and only
once: a payload is queued (``queue/<day>.json``, at most 30 or 2 MB, oldest dropped), and
taken off the queue after one attempt that reached the server, whatever it answered; only a
connection that never opened leaves it queued for the next hourly run. A lost answer is
therefore a missing day, never a day counted twice.

The OTLP shape: the resource's fields as resource attributes (``service.name``,
``service.version``, ``os.type``, ``host.arch`` by the OpenTelemetry names, the rest as
``kranto.<field>``), one log record with ``event.name: kranto.daily`` and each report key as an
attribute ``kranto.<key>``. ``x-amz-content-sha256`` carries the body's SHA-256, which an AWS
relay behind CloudFront needs to sign the request on to its function."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from .. import activity
from ..stored import runs as stored_runs
from . import local, report

log = logging.getLogger("kranto.telemetry")

QUEUE_MAX = 30
QUEUE_BYTES = 2_000_000
SENT_DAYS = 90
SEND_FROM_UTC = 2                       # the report goes between 02:00 and 05:00 UTC
SEND_WINDOW_MIN = 180
TIMEOUT = {"connect": 5.0, "read": 10.0, "write": 10.0, "pool": 5.0}
OTEL_NAMES = {"version": "service.version", "os": "os.type", "arch": "host.arch"}


def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def envelope(payload: dict, ts: datetime) -> dict:
    res = payload["resource"]
    attrs = [_attr("service.name", "kranto")]
    attrs += [_attr(OTEL_NAMES.get(k, f"kranto.{k}"), v) for k, v in sorted(res.items())]
    record = {"timeUnixNano": str(int(ts.timestamp()) * 10**9), "severityNumber": 9,
              "severityText": "INFO", "body": {"stringValue": "kranto.daily"},
              "attributes": [_attr("event.name", "kranto.daily")]
              + [_attr(f"kranto.{k}", v) for k, v in sorted(payload["report"].items())]}
    return {"resourceLogs": [{"resource": {"attributes": attrs}, "scopeLogs": [
        {"scope": {"name": "kranto.telemetry", "version": "1"}, "logRecords": [record]}]}]}


def wire(payload: dict) -> bytes:
    """The exact bytes that would be posted (before gzip). The record's time is the day's
    start: no time finer than the day leaves."""
    day = datetime.strptime(payload["report"]["day"], "%Y-%m-%d").replace(tzinfo=UTC)
    return json.dumps(envelope(payload, day), separators=(",", ":"), sort_keys=True).encode()


# -- the queue and the sent log --------------------------------------------------------------

def qdir(home: Path) -> Path:
    return local.tdir(home) / "queue"


def sdir(home: Path) -> Path:
    return local.tdir(home) / "sent"


def queue(home: Path, day: str, body: bytes) -> list[str]:
    """Queue ``day``'s bytes; returns the days dropped to keep the bounds."""
    d = qdir(home)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / f"{day}.json").write_bytes(body)
    files = sorted(d.glob("*.json"))
    dropped = []
    while files and (len(files) > QUEUE_MAX or sum(f.stat().st_size for f in files) > QUEUE_BYTES):
        dropped.append(files[0].stem)
        files.pop(0).unlink()
    return dropped


def sent(home: Path) -> list[dict]:
    """What was sent, newest first: ``{day, at, status, bytes, gzip_bytes, endpoint}``."""
    out = []
    for meta in sorted(sdir(home).glob("*.meta.json"), reverse=True):
        try:
            out.append(json.loads(meta.read_text()))
        except (OSError, ValueError):
            continue
    return out


def sent_body(home: Path, day: str) -> bytes | None:
    try:
        return (sdir(home) / f"{day}.json").read_bytes()
    except OSError:
        return None


def _keep(home: Path, day: str, body: bytes, meta: dict) -> None:
    d = sdir(home)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / f"{day}.json").write_bytes(body)
    (d / f"{day}.meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")


class Unreached(Exception):
    """The connection never opened: the payload stays queued."""


def post(endpoint: str, body: bytes, *, transport=None) -> int:
    """POST ``body`` (gzipped) to ``endpoint``; the HTTP status. ``file://`` writes the
    payload into that directory instead. Raises ``Unreached`` when nothing reached it."""
    gz = gzip.compress(body, 6, mtime=0)
    u = urlparse(endpoint)
    if u.scheme == "file":
        d = Path(u.path)
        d.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(gz).hexdigest()[:16]
        (d / f"{name}.json").write_bytes(body)
        return 204
    import httpx

    headers = {"Content-Type": "application/json", "Content-Encoding": "gzip",
               "x-amz-content-sha256": hashlib.sha256(gz).hexdigest(),
               "User-Agent": "kranto-telemetry/1"}
    try:
        with httpx.Client(timeout=httpx.Timeout(**TIMEOUT), transport=transport,
                          follow_redirects=False, trust_env=False) as c:
            r = c.post(endpoint, content=gz, headers=headers)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.UnsupportedProtocol) as exc:
        raise Unreached(type(exc).__name__) from exc
    except httpx.HTTPError as exc:     # it may have arrived: never sent again
        log.info("telemetry post ended without an answer: %s", type(exc).__name__)
        return 0
    return r.status_code


# -- the hourly job ---------------------------------------------------------------------------

def send_minute(home: Path) -> int:
    """This install's minute after 02:00 UTC, drawn once and kept (the relay's load is flat)."""
    st = local.read_state(home)
    m = st.get("minute")
    if not isinstance(m, int) or not 0 <= m < SEND_WINDOW_MIN:  # stored-shape: isinstance first
        m = random.randrange(SEND_WINDOW_MIN)
        st["minute"] = m
        local.write_state(home, st)
    return m


def prune(home: Path, today: datetime) -> None:
    for sub, keep in (("local", local.LOCAL_DAYS), ("sent", SENT_DAYS)):
        cut = (today - timedelta(days=keep)).strftime("%Y-%m-%d")
        for f in (local.tdir(home) / sub).glob("*"):
            if f.name[:10] < cut:
                f.unlink(missing_ok=True)


def first_day(start) -> datetime | None:
    """The first day sent after the answer at ``start``: the next whole day (the answer's own
    day only when it was given at midnight)."""
    try:
        since = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    except ValueError:
        return None
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    first = (since + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if since == since.replace(hour=0, minute=0, second=0, microsecond=0):
        first = since
    return first


def next_send(home: Path, eff: local.Effective, now: datetime) -> datetime:
    """When the next report goes: the install's minute in the window, and never before the
    morning after the first day that is sent."""
    minute = timedelta(hours=SEND_FROM_UTC, minutes=send_minute(home))
    at = now.replace(hour=0, minute=0, second=0, microsecond=0) + minute
    if at <= now:
        at += timedelta(days=1)
    first = first_day(eff.answered_at or local.read_state(home).get("sending_since") or now)
    if first is not None:
        at = max(at, first + timedelta(days=1) + minute)
    return at


def due_days(home: Path, eff: local.Effective, now: datetime) -> list[str]:
    """The days to build now: from the day after the answer (or the first sending day this
    install saw) up to yesterday, each once, at most the queue's length back."""
    st = local.read_state(home)
    start = eff.answered_at or st.get("sending_since")
    if not start:
        st["sending_since"] = now.isoformat(timespec="seconds")
        local.write_state(home, st)
        return []
    first = first_day(start)
    if first is None:
        return []
    at = now.replace(hour=SEND_FROM_UTC, minute=0, second=0, microsecond=0) + \
        timedelta(minutes=send_minute(home))
    last = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    if now < at:
        last -= timedelta(days=1)
    built = set(st.get("built") or ())
    days, d = [], max(first, last - timedelta(days=QUEUE_MAX - 1))
    while d <= last:
        day = d.strftime("%Y-%m-%d")
        if day not in built:
            days.append(day)
        d += timedelta(days=1)
    return days


def run(home: Path, *, store=None, cfg=None, now: datetime | None = None, environ=None,
        transport=None) -> dict:
    """One run of the job: prune; with ``off``, delete the counters; when sending is on,
    build the days that are due, queue them, and post the queue oldest first. Returns what it
    did (the runs row's summary)."""
    now = now or datetime.now(UTC)
    eff = local.effective(home, environ)
    out: dict = {"mode": eff.mode, "built": [], "posted": [], "queued": 0}
    if eff.mode == "off":
        import shutil
        shutil.rmtree(local.tdir(home) / "local", ignore_errors=True)
        return out
    prune(home, now)
    if eff.mode not in local.SENDING or not eff.endpoint:
        out["why"] = ("no endpoint is set: nothing is sent" if eff.mode in local.SENDING
                      else f"{eff.mode}: nothing is sent")
        return out
    st = local.read_state(home)
    for day in due_days(home, eff, now):
        try:
            payload = report.build(home, day, store=store, cfg=cfg, tier=eff.mode,
                                   environ=environ)
        except Exception as exc:  # noqa: BLE001 - a report that fails the list is never sent
            log.warning("telemetry: the report for %s was not built: %s", day, exc)
            out.setdefault("refused", []).append(day)
            continue
        out["dropped"] = queue(home, day, wire(payload)) or None
        st = local.read_state(home)
        st["built"] = sorted({*(st.get("built") or ()), day})[-120:]
        local.write_state(home, st)
        out["built"].append(day)
    for f in sorted(qdir(home).glob("*.json")):
        body = f.read_bytes()
        try:
            status = post(eff.endpoint, body, transport=transport)
        except Unreached as exc:
            out["unreached"] = str(exc)
            break
        _keep(home, f.stem, body, {"day": f.stem, "at": now.isoformat(timespec="seconds"),
                                   "status": status, "bytes": len(body),
                                   "gzip_bytes": len(gzip.compress(body, 6, mtime=0)),
                                   "endpoint": eff.endpoint, "tier": eff.mode})
        f.unlink(missing_ok=True)
        out["posted"].append([f.stem, status])
    out["queued"] = len(list(qdir(home).glob("*.json")))
    return out


def make_job(home: Path, store, cfg_of, every_hours: float = 1.0):
    """The scheduler's ``telemetry`` job: ``run`` and a runs row (ok, with what it did; a run
    with nothing to send is ok too; skipped only when it raised). ``cfg_of``: the runtime's
    config now (it changes under Settings)."""

    from ..scheduler import Job
    from ..store import iso, utcnow
    from . import timing

    def job():
        started = utcnow()
        timing.flush()
        try:
            summary = run(home, store=store, cfg=cfg_of())
            status, error = "ok", None
        except Exception as exc:  # noqa: BLE001 - telemetry never stops the scheduler
            summary, status, error = {}, "skipped", type(exc).__name__
        store.insert("runs", {"run_uuid": activity.run_uuid("telemetry"), "kind": "telemetry",
                              "status": status, "started_at": iso(started),
                              "finished_at": iso(utcnow()),
                              "summary": stored_runs.text_for("telemetry", summary),
                              "error": error})
    return Job("telemetry", every_hours, job)
