"""The assistant's usage (TEL, 2026-10-27): how Kranto's verbs are called and how assistant
sessions go, sent in the ``detailed`` tier only, hour by hour, under the consent Kranto already
has.

**The rule.** These events go with ``detailed`` (and an endpoint) and nothing else: with
``basic``, ``local``, ``off``, unanswered or ``DO_NOT_TRACK`` none is kept and none is sent,
and choosing anything but ``detailed`` deletes what was waiting. Why ``detailed``: the
choice's words promised "sessions ... in a later release" to the detailed tier only, and
``basic`` was described as the daily report and error reports; widening ``basic`` would be a
second consent nobody was asked. The console's own errors (a Kranto tool call failing or timing
out) are error reports (``errors.py``, ``where: console``) and follow the error reports' rule
(basic and detailed).

**The events** (``schema.json``'s ``assistant``), none with an id, a name, a path or a word
typed:

- ``kranto.verb``: one per hour, verb, surface (``ui``, ``console``, ``mcp``, ``cli``,
  ``agent``), client (``claude-code``, ``codex``, ``other``, ``none``), outcome (``ok``,
  ``refused`` with the refusal's kind, ``failed``, ``prepared``, ``confirmed``, ``dismissed``)
  and the ladder's rung: how many calls, the median and slowest milliseconds. Recorded by the
  server itself (``note_verb``), so Codex and any client without hooks are covered.
- ``kranto.session``: one per ended session, from the plugin's hooks: the assistant, the
  model, console or outside, the tool profile, how it started and ended, its minutes, turns,
  Kranto tool calls, failures and slash commands used.
- ``kranto.command``: one per hour, slash command (``/kranto:status``, by name only) and
  assistant: how often.

**How.** The server keeps the hour's counts in memory (``note_verb``); another process (``kranto
telemetry event``, which the hooks run) writes a spool line the server takes in. A session's
start and end are paired in ``sessions.json`` by a hash of the assistant's session id, kept on
this machine only and never sent; a session idle for ``IDLE_S`` is closed at its last event.
The server's flusher (``errors.Flusher``'s thread) sends the hours that have ended, at most
``MAX_RECORDS`` records a batch and ``MAX_BATCHES_HOUR`` batches an hour: one request an hour
for a normal day, however long the session. Every record is checked against the list and the
personal-data patterns before it leaves, posted like the daily report, and its exact bytes are
kept in ``assistant/sent/`` (``kranto telemetry show --sent``)."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from . import local, send
from . import schema as schema_mod

log = logging.getLogger("kranto.telemetry")

TIER = "detailed"
EVENTS = {"verb": "kranto.verb", "session": "kranto.session", "command": "kranto.command"}
MAX_RECORDS = 200
MAX_BATCHES_HOUR = 3
MAX_SAMPLES = 200
MAX_PENDING = 5000
MAX_SESSIONS = 200
IDLE_S = 12 * 3600
SPOOL_BYTES = 512_000
SENT_KEEP = 200
RETRY_S = 300.0

_lock = threading.Lock()
_verbs: dict[tuple, dict] = {}
_commands: dict[tuple, int] = {}
_sessions: list[dict] = []
_server_home: Path | None = None


def adir(home: Path) -> Path:
    return local.tdir(home) / "assistant"


def sending(home: Path | None, environ=None) -> bool:
    """Whether these events may be kept: ``detailed`` chosen, and somewhere to send."""
    if home is None:
        return False
    try:
        eff = local.effective(Path(home), environ)
    except Exception:  # noqa: BLE001 - a broken config keeps nothing
        return False
    return eff.mode == TIER and bool(eff.endpoint)


def _sending_here(home: Path | None) -> bool:
    if home is not None and local.configured() is not None and Path(home) == local.configured():
        return local.current_mode() == TIER
    return sending(home)


def hour_of(ts: float) -> int:
    return int(ts // 3600 * 3600)


# -- values -----------------------------------------------------------------------------------

def enum_or(name: str, value, fallback: str = "other") -> str:
    vals = schema_mod.union()["enums"].get(name) or ()
    return value if value in vals else fallback


def client_of(by: str | None) -> str:
    """The assistant behind a caller (``verbs.by_of``'s words): ``console:claude`` and
    ``mcp:claude-code`` are claude-code, anything with codex is codex; the page and the command
    line are none."""
    door, _, who = str(by or "").partition(":")
    if door in ("ui", "cli", ""):
        return "none"
    who = who.lower()
    if "codex" in who:
        return "codex"
    if who.startswith("claude"):
        return "claude-code"
    return "other"


def assistant_of(name: str | None) -> str:
    n = str(name or "").lower()
    return "codex" if "codex" in n else "claude-code" if n.startswith("claude") else "other"


def model_of(name) -> str:
    from .report import _model
    return _model(str(name or "")) if name else "other"


# -- verbs, in the server ----------------------------------------------------------------------

def note_verb(verb: str, surface: str, client: str, outcome: str, rung: str, ms: float, *,
              refusal: str | None = None, home: Path | None = None,
              now: float | None = None) -> None:
    """One verb call, if the person chose ``detailed``. Never raises."""
    try:
        home = Path(home) if home is not None else local.configured()
        if not _sending_here(home):
            return
        rec = {"verb": enum_or("verb", verb), "surface": enum_or("surface", surface, "ui"),
               "client": enum_or("client", client), "outcome": outcome, "rung": rung,
               "refusal": refusal if outcome == "refused" else None,
               "ms": max(0, min(int(ms), 600000))}
        if rec["outcome"] not in schema_mod.union()["enums"]["verb_outcome"] or \
                rec["rung"] not in schema_mod.union()["enums"]["rung"]:
            return
        if rec["refusal"] is not None:
            rec["refusal"] = enum_or("refusal", rec["refusal"], "door")
        _add_verb(rec, time.time() if now is None else now, home)
    except Exception:  # noqa: BLE001 - counting never breaks what it counts
        log.debug("a verb call was not counted", exc_info=True)


_ROUTES: tuple[float, dict[tuple[str, str], str]] = (0.0, {})
# counted where they are handled; the build loop's page actions (``/brb/api/act``) carry their
# kind in the body, so they stay in the daily report's ``actions.<action>``
OWN_DOORS = ("/api/verbs/", "/api/prepared/", "/brb")


def verb_of_route(method: str, pattern: str) -> str | None:
    """The verb a page's own write performs (its route's pattern): the registry's first verb
    on that route (a route several verbs share, such as a topic's status, is named by the
    first). The map is made again every five minutes (a cub's actions come and go)."""
    global _ROUTES
    at, m = _ROUTES
    if time.monotonic() - at > 300 or not m:
        from ..core import verbs
        m = {}
        for v in verbs.all_verbs():
            for meth, path in verbs.routes_of(v):
                m.setdefault((meth, path), v.kind)
        _ROUTES = (time.monotonic(), m)
    return m.get((method, pattern))


def note_request(scope: dict, pattern: str, status: int, ms: float) -> None:
    """A page's (or the command line's) own write to a verb's route, from the timing
    middleware: the verb, the door, ``owner`` (the ladder does not apply). An assistant's
    token reaching a write route other than the verbs' is refused there: counted as refused
    at the door. Never raises."""
    try:
        method = scope.get("method") or "GET"
        if method in ("GET", "HEAD", "OPTIONS") or pattern.startswith(OWN_DOORS) or \
                not _sending_here(local.configured()):
            return
        verb = verb_of_route(method, pattern)
        if verb is None:
            return
        from ..core import verbs
        ident = scope.get("kranto.identity")
        door = verbs.door_of(ident) or "ui"
        by = verbs.by_of(ident)
        if status < 400:
            outcome, refusal = "ok", None
        elif status >= 500:
            outcome, refusal = "failed", None
        else:
            outcome = "refused"
            refusal = {401: "signed_out", 403: "door"}.get(status, "fields")
        rung = "owner" if door in verbs.OWNER_DOORS else "never"
        note_verb(verb, door, client_of(by), outcome, rung, ms, refusal=refusal)
    except Exception:  # noqa: BLE001
        log.debug("a page's click was not counted", exc_info=True)


def _add_verb(rec: dict, now: float, home: Path | None) -> None:
    if _server_home is not None and home == _server_home:
        with _lock:
            _merge_verb(hour_of(now), rec, [rec["ms"]])
        return
    _spool(home, {"k": "verb", "hour": hour_of(now), **rec})


def _merge_verb(hour: int, rec: dict, samples: list[int], count: int = 1) -> None:
    key = (hour, rec["verb"], rec["surface"], rec["client"], rec["outcome"],
           rec.get("refusal"), rec["rung"])
    have = _verbs.get(key)
    if have is None:
        if len(_verbs) >= MAX_PENDING:
            return
        have = _verbs[key] = {"count": 0, "ms": []}
    have["count"] = min(have["count"] + count, 1_000_000)
    have["ms"] = (have["ms"] + samples)[-MAX_SAMPLES:]


def _merge_command(hour: int, command: str, assistant: str, count: int = 1) -> None:
    key = (hour, command, assistant)
    if key in _commands or len(_commands) < MAX_PENDING:
        _commands[key] = min(_commands.get(key, 0) + count, 100_000)


# -- the spool (other processes) ---------------------------------------------------------------

def _spool(home: Path | None, line: dict) -> None:
    if home is None:
        return
    p = adir(home) / "spool.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if p.stat().st_size > SPOOL_BYTES:
            return
    except OSError:
        pass
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"v": 1, **line}, separators=(",", ":")) + "\n")


def take_spool(home: Path) -> list[dict]:
    spool = adir(home) / "spool.jsonl"
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
            if isinstance(d, dict) and d.get("v") == 1 and d.get("k") in EVENTS:
                d.pop("v")
                out.append(d)
    finally:
        taking.unlink(missing_ok=True)
    return out


def _take_in(lines: list[dict]) -> None:
    with _lock:
        for d in lines:
            try:
                hour = int(d.get("hour") or 0)
                if d["k"] == "verb":
                    _merge_verb(hour, d, [int(d.get("ms") or 0)])
                elif d["k"] == "command":
                    _merge_command(hour, str(d["command"]), str(d["assistant"]))
                elif d["k"] == "session" and len(_sessions) < MAX_SESSIONS:
                    _sessions.append({k: v for k, v in d.items() if k != "k"})
            except (KeyError, TypeError, ValueError):
                continue


# -- the hooks' events (``kranto telemetry event``) ---------------------------------------------

HOOK_EVENTS = ("start", "end", "prompt", "tool", "tool_failed", "stop")


def session_key(raw) -> str | None:
    """A hash of the assistant's session id: pairs a start with its end on this machine; the
    id itself is never kept, and the hash is never sent."""
    if not isinstance(raw, str) or not raw:
        return None
    return hashlib.sha256(("kranto-session:" + raw).encode()).hexdigest()[:20]


@contextlib.contextmanager
def _sessions_file(home: Path):
    import fcntl
    d = adir(home)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = d / "sessions.json"
    with open(d / ".sessions.lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            st = json.loads(p.read_text())
            st = st if isinstance(st, dict) else {}
        except (OSError, ValueError):
            st = {}
        yield st
        tmp = d / f".sessions.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(st, sort_keys=True))
        os.replace(tmp, p)


def _close(home: Path, entry: dict, end: str, at: float) -> None:
    rec = {"k": "session", "hour": hour_of(entry["start_ts"]),
           "assistant": entry.get("assistant", "other"), "place": entry.get("place", "outside"),
           "minutes": max(0, min(int((at - entry["start_ts"]) // 60), 100000)), "end": end}
    for k in ("model", "profile", "start"):
        if entry.get(k):
            rec[k] = entry[k]
    for k in ("turns", "tool_calls", "tool_failures", "commands"):
        rec[k] = min(int(entry.get(k) or 0), 100000)
    _spool(home, rec)


def close_idle(home: Path, st: dict, now: float) -> None:
    for key in [k for k, e in st.items() if now - float(e.get("last_ts") or 0) > IDLE_S]:
        e = st.pop(key)
        _close(home, e, "idle", float(e.get("last_ts") or e["start_ts"]))


def hook_event(home: Path, ev: dict, *, now: float | None = None, environ=None) -> str | None:
    """One event from a hook (``kranto telemetry event``): ``{event, session, assistant, model,
    place, profile, source, reason, command, verb, failure, message}``, each already reduced
    by the hook. Dropped unless the person chose ``detailed`` (the console error inside a
    failure follows the error reports' rule). Returns the one-time line for ``start``, else
    None. Never raises."""
    try:
        return _hook_event(Path(home), ev, time.time() if now is None else now, environ)
    except Exception:  # noqa: BLE001 - a hook never breaks a session
        log.debug("a hook event was not kept", exc_info=True)
        return None


def verb_of_tool(tool) -> str | None:
    """The verb behind one of Kranto's MCP tools (``kranto_topic_add`` is ``topic.add``;
    ``kranto_publish``, a build-loop action, is ``b.publish``), or None (a read, a generic
    tool)."""
    if not isinstance(tool, str):
        return None
    vals = schema_mod.union()["enums"].get("verb") or ()
    for v in vals:
        if v.replace(".", "_").replace("-", "_") == tool:
            return v
    return f"b.{tool}" if f"b.{tool}" in vals else None


def _hook_event(home: Path, ev: dict, now: float, environ) -> str | None:
    kind = ev.get("event")
    if kind not in HOOK_EVENTS:
        return None
    if kind in ("tool", "tool_failed") and not ev.get("verb"):
        ev = {**ev, "verb": verb_of_tool(ev.get("tool"))}
    line = notice_line(home, environ) if kind == "start" else None
    if kind == "tool_failed":
        _console_error(home, ev)
    if not sending(home, environ):
        return line
    key = session_key(ev.get("session"))
    assistant = enum_or("assistant", assistant_of(ev.get("assistant")))
    if kind == "prompt":
        cmd = ev.get("command")
        if cmd not in schema_mod.union()["enums"]["command"]:
            return None
        _spool(home, {"k": "command", "hour": hour_of(now), "command": cmd,
                      "assistant": assistant})
    if key is None:
        return line
    with _sessions_file(home) as st:
        close_idle(home, st, now)
        e = st.get(key)
        if kind == "start":
            if e is None and len(st) < MAX_SESSIONS:
                st[key] = {"start_ts": now, "last_ts": now, "assistant": assistant,
                           "model": model_of(ev.get("model")) if ev.get("model") else None,
                           "place": enum_or("place", ev.get("place"), "outside"),
                           "profile": enum_or("profile", ev.get("profile"), "full"),
                           "start": enum_or("session_start", ev.get("source"))}
            elif e is not None:
                e["last_ts"] = now
            return line
        if e is None:
            return None
        e["last_ts"] = now
        if kind == "end":
            st.pop(key)
            _close(home, e, enum_or("session_end", ev.get("reason")), now)
        elif kind == "prompt":
            e["commands"] = int(e.get("commands") or 0) + 1
        elif kind == "tool":
            e["tool_calls"] = int(e.get("tool_calls") or 0) + 1
        elif kind == "tool_failed":
            e["tool_calls"] = int(e.get("tool_calls") or 0) + 1
            e["tool_failures"] = int(e.get("tool_failures") or 0) + 1
        elif kind == "stop":
            e["turns"] = int(e.get("turns") or 0) + 1
    return None


def _console_error(home: Path, ev: dict) -> None:
    """A Kranto tool call that failed or timed out, as an error report (ERR's fast path, its
    scrubber: only listed words survive the message)."""
    from . import errors
    typ = "ToolTimeout" if ev.get("failure") == "timeout" else "ToolFailed"
    raw = ev.get("message")
    msg = raw if isinstance(raw, str) else ""
    errors.report_failure(typ, "console", message=msg[:2000], home=home,
                          verb=enum_or("verb", ev.get("verb")) if ev.get("verb") else None)


# -- the one-time line -------------------------------------------------------------------------

NOTICE = ("Kranto: usage reports are not chosen yet, and nothing is sent until you choose. "
          "/kranto:telemetry says what would be sent; choose in Kranto's page, Settings › "
          "Privacy & access (#/settings/privacy). This line is shown once.")


def notice_line(home: Path, environ=None) -> str | None:
    """The line a session's start shows **once** to an install that never answered Kranto's
    telemetry question; after that, None for ever (``state.json``'s
    ``assistant_notice_shown``)."""
    try:
        if local.effective(home, environ).answered:
            return None
        st = local.read_state(home)
        if st.get("assistant_notice_shown"):
            return None
        import fcntl
        d = local.tdir(home)
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(d / ".notice.lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            st = local.read_state(home)
            if st.get("assistant_notice_shown"):
                return None
            st["assistant_notice_shown"] = datetime.now(UTC).isoformat(timespec="seconds")
            local.write_state(home, st)
        return NOTICE
    except Exception:  # noqa: BLE001 - no line rather than a broken start
        return None


# -- the batch ---------------------------------------------------------------------------------

def records(*, before: int | None = None) -> list[tuple[str, dict, int]]:
    """``(event, fields, hour)`` for every pending record (of the hours before ``before``)."""
    out = []
    with _lock:
        for key, v in _verbs.items():
            hour, verb, surface, client, outcome, refusal, rung = key
            if before is not None and hour >= before:
                continue
            ms = sorted(v["ms"])
            rec = {"verb": verb, "surface": surface, "client": client, "outcome": outcome,
                   "rung": rung, "count": v["count"]}
            if refusal:
                rec["refusal"] = refusal
            if ms:
                rec["ms_p50"] = ms[(len(ms) - 1) // 2]
                rec["ms_max"] = ms[-1]
            out.append(("verb", rec, hour))
        for (hour, command, assistant), n in _commands.items():
            if before is None or hour < before:
                out.append(("command", {"command": command, "assistant": assistant,
                                        "count": n}, hour))
        for s in _sessions:
            hour = int(s.get("hour") or 0)
            if before is None or hour < before:
                out.append(("session", {k: v for k, v in s.items()
                                        if k != "hour" and v is not None}, hour))
    return sorted(out, key=lambda r: (r[2], r[0]))


def check(kind: str, rec: dict, schema: dict | None = None) -> None:
    """Raise ``SchemaError`` unless one record's every key and value is allowed."""
    schema = schema or schema_mod.union()
    spec = schema["assistant"][kind]
    for k, v in rec.items():
        s = spec.get(k)
        if s is None:
            raise schema_mod.SchemaError(f"{kind}.{k} is not in the list")
        if not schema_mod.value_ok(s, v, schema):
            raise schema_mod.SchemaError(f"{kind}.{k} has a value the list does not allow")
    for k, s in spec.items():
        if s.get("required") and k not in rec:
            raise schema_mod.SchemaError(f"{kind}.{k} is missing")


def build(home: Path, recs: list[tuple[str, dict, int]], environ=None):
    """``(resource, the records that pass)``."""
    from collections import Counter

    from ..scrub import scrub
    from .report import resource as resource_of

    res = resource_of(home, TIER, environ)
    schema_mod.check_resource(res)
    ok = []
    for kind, rec, hour in recs:
        try:
            check(kind, rec)
        except schema_mod.SchemaError as exc:
            log.warning("telemetry: an assistant record was not sent: %s", exc)
            continue
        hits: Counter = Counter()
        for v in rec.values():
            if isinstance(v, str):
                scrub(v, hits)
        if hits:
            log.warning("telemetry: an assistant record matched a personal-data pattern")
            continue
        ok.append((kind, rec, hour))
    return res, ok


def envelope(resource: dict, recs: list[tuple[str, dict, int]]) -> dict:
    attrs = [send._attr("service.name", "kranto")]
    attrs += [send._attr(send.OTEL_NAMES.get(k, f"kranto.{k}"), v)
              for k, v in sorted(resource.items())]
    out = []
    for kind, rec, hour in recs:
        out.append({"timeUnixNano": str(hour * 10**9), "severityNumber": 9,
                    "severityText": "INFO", "body": {"stringValue": EVENTS[kind]},
                    "attributes": [send._attr("event.name", EVENTS[kind])]
                    + [send._attr(f"kranto.{k}", v) for k, v in sorted(rec.items())]})
    return {"resourceLogs": [{"resource": {"attributes": attrs}, "scopeLogs": [
        {"scope": {"name": "kranto.telemetry", "version": "1"}, "logRecords": out}]}]}


def wire(resource: dict, recs) -> bytes:
    return json.dumps(envelope(resource, recs), separators=(",", ":"), sort_keys=True).encode()


def preview(home: Path, environ=None) -> dict:
    """Everything waiting, as it would be sent: ``{resource, records, bytes, wire}``."""
    if _server_home is None or Path(home) != _server_home:
        _load_pending(Path(home), merge_spool=False)
    recs = records()
    res, ok = build(home, recs, environ)
    body = wire(res, ok) if ok else b""
    return {"resource": res, "records": [{"event": EVENTS[k], "hour": datetime.fromtimestamp(
        h, UTC).isoformat(timespec="minutes"), **r} for k, r, h in ok],
        "bytes": len(body), "wire": body.decode()}


# -- state, what waits, what was sent ----------------------------------------------------------

def _save_pending(home: Path) -> None:
    with _lock:
        data = {"verbs": [[list(k), v] for k, v in _verbs.items()],
                "commands": [[list(k), n] for k, n in _commands.items()],
                "sessions": list(_sessions)}
    p = adir(home) / "pending.json"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(f".pending.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, sort_keys=True))
    os.replace(tmp, p)


def _load_pending(home: Path, merge_spool: bool = True) -> None:
    """What waited, back in memory (the server's start; ``preview`` from another process
    reads it, and the spool too, without taking it)."""
    _clear()
    try:
        data = json.loads((adir(home) / "pending.json").read_text())
    except (OSError, ValueError):
        data = {}
    with _lock:
        for k, v in (data.get("verbs") or []) if isinstance(data, dict) else ():
            try:
                hour, verb, surface, client, outcome, refusal, rung = k
                _merge_verb(int(hour), {"verb": verb, "surface": surface, "client": client,
                                        "outcome": outcome, "refusal": refusal, "rung": rung},
                            list(v.get("ms") or []), int(v.get("count") or 1))
            except (TypeError, ValueError, AttributeError):
                continue
        for k, n in (data.get("commands") or []) if isinstance(data, dict) else ():
            try:
                _merge_command(int(k[0]), str(k[1]), str(k[2]), int(n))
            except (TypeError, ValueError, IndexError):
                continue
        for s in (data.get("sessions") or []) if isinstance(data, dict) else ():
            if isinstance(s, dict) and len(_sessions) < MAX_SESSIONS:
                _sessions.append(s)
    if merge_spool:
        _take_in(take_spool(home))
    else:
        try:
            raw = (adir(home) / "spool.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            raw = []
        lines = []
        for r in raw:
            try:
                d = json.loads(r)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("k") in EVENTS:
                lines.append(d)
        _take_in(lines)


def _clear() -> None:
    with _lock:
        _verbs.clear()
        _commands.clear()
        _sessions.clear()


def forget(home: Path) -> None:
    """Delete everything waiting, the open sessions and the spool (any choice but
    ``detailed``)."""
    _clear()
    for name in ("spool.jsonl", "pending.json", "sessions.json"):
        (adir(home) / name).unlink(missing_ok=True)


def read_state(home: Path) -> dict:
    try:
        st = json.loads((adir(home) / "state.json").read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(home: Path, st: dict) -> None:
    p = adir(home) / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(f".state.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, sort_keys=True) + "\n")
    os.replace(tmp, p)


def sent(home: Path) -> list[dict]:
    out = []
    for meta in sorted((adir(home) / "sent").glob("*.meta.json"), reverse=True):
        try:
            out.append(json.loads(meta.read_text()))
        except (OSError, ValueError):
            continue
    return out


def sent_body(home: Path, batch: str) -> bytes | None:
    if not batch.replace("-", "").replace("T", "").replace("a", "").isalnum():
        return None
    try:
        return (adir(home) / "sent" / f"{batch}.json").read_bytes()
    except OSError:
        return None


def _keep(home: Path, batch: str, body: bytes, meta: dict) -> None:
    d = adir(home) / "sent"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / f"{batch}.json").write_bytes(body)
    (d / f"{batch}.meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    for old in sorted(d.glob("*.meta.json"))[:-SENT_KEEP]:
        old.unlink(missing_ok=True)
        (d / old.name.replace(".meta.json", ".json")).unlink(missing_ok=True)


def waiting_count(home: Path) -> int:
    if _server_home is not None and Path(home) == _server_home:
        return len(records())
    _load_pending(Path(home), merge_spool=False)
    n = len(records())
    _clear()
    return n


# -- the flusher (in errors.Flusher's thread) --------------------------------------------------

def _drop(sent_recs: list[tuple[str, dict, int]]) -> None:
    with _lock:
        for kind, rec, hour in sent_recs:
            if kind == "verb":
                _verbs.pop((hour, rec["verb"], rec["surface"], rec["client"], rec["outcome"],
                            rec.get("refusal"), rec["rung"]), None)
            elif kind == "command":
                _commands.pop((hour, rec["command"], rec["assistant"]), None)
        if any(k == "session" for k, _r, _h in sent_recs):
            gone = [r for k, r, _h in sent_recs if k == "session"]
            for r in gone:
                for s in list(_sessions):
                    if all(s.get(k) == v for k, v in r.items()):
                        _sessions.remove(s)
                        break


def flush(home: Path, *, now: float | None = None, environ=None, transport=None) -> dict:
    """One look: take the spool in, close idle sessions, and post the hours that have ended
    when the limits allow it. Returns what it did."""
    now = time.time() if now is None else now
    if not sending(home, environ):
        forget(home)
        return {"sent": 0, "why": "assistant events go with detailed only"}
    eff = local.effective(home, environ)
    try:
        with _sessions_file(home) as sessions:
            close_idle(home, sessions, now)          # into the spool, taken in just below
    except OSError:
        pass
    taken = take_spool(home)
    if taken:
        _take_in(taken)
        _save_pending(home)
    st = read_state(home)
    ready = records(before=hour_of(now))
    out: dict = {"sent": 0, "waiting": len(records())}
    if not ready:
        return out
    if now < float(st.get("retry_at") or 0):
        return out
    batches = [t for t in st.get("batches") or () if now - t < 3600]
    if len(batches) >= MAX_BATCHES_HOUR:
        out["why"] = "the limits: the rest waits"
        return out
    take = ready[:MAX_RECORDS]
    res, ok = build(home, take, environ)
    refused = [r for r in take if r not in ok]
    if refused:
        _drop(refused)
    if not ok:
        _save_pending(home)
        return out
    body = wire(res, ok)
    try:
        status = send.post(str(eff.endpoint), body, transport=transport)
    except send.Unreached as exc:
        st["retry_at"] = now + RETRY_S
        write_state(home, st)
        out["unreached"] = str(exc)
        return out
    batch = "a" + datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H%M%S")
    _keep(home, batch, body, {"id": batch, "at": datetime.fromtimestamp(now, UTC).isoformat(
        timespec="seconds"), "status": status, "bytes": len(body),
        "gzip_bytes": len(gzip.compress(body, 6, mtime=0)), "endpoint": eff.endpoint,
        "tier": TIER, "records": len(ok)})
    _drop(ok)
    st["batches"] = [*batches, now]
    st.pop("retry_at", None)
    write_state(home, st)
    _save_pending(home)
    out.update(sent=len(ok), status=status, batch=batch)
    return out


def start(home: Path) -> None:
    """The server (``errors.start``): from now on ``note_verb`` counts in memory here."""
    global _server_home
    _server_home = Path(home)
    if sending(home):
        _load_pending(Path(home))


def stop(home: Path) -> None:
    try:
        if sending(home):
            _save_pending(Path(home))
    except Exception:  # noqa: BLE001
        log.debug("assistant events: what waits was not saved", exc_info=True)
