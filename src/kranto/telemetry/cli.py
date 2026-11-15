"""``kranto telemetry`` (section 3.3).

    kranto telemetry [status] [--json]   the mode and why, what was sent, what is next
    kranto telemetry show [DAY] [--wire] today's report as it stands (or DAY's), then the error
                                        reports waiting; --wire: the exact bytes that would be
                                        posted
    kranto telemetry show --errors [--wire]  the error reports waiting, as they would be sent
    kranto telemetry show --assistant [--wire]  the assistant's events waiting (detailed only)
    kranto telemetry show --sent [ID]    what was sent: the days, the error and assistant
                                        batches, or one day's or batch's exact bytes
    kranto telemetry off | local | basic | detailed
    kranto telemetry event               one event from Kranto's plugin hooks, as JSON on stdin
                                        (kept only as the choice allows; prints at most the
                                        one-time line)
    kranto telemetry docs                the field list (docs/privacy/what-kranto-sends.md)
    kranto telemetry schema              the whole allow-list as JSON (the relay's copy)

``off`` and ``local`` switch at once; ``basic`` and ``detailed`` print what they mean first,
and are refused inside an assistant's session (``KRANTO_MCP_CONSOLE``, ``CLAUDECODE``): consent
is given by the person, in their own terminal or on the page. None of these opens a network
connection."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import (
    DOCS_LINK,
    MEANING,
    MODES,
    SUMMARY,
    TelemetryError,
    errors,
    report,
    send,
    set_mode,
    status,
)
from . import docs as docs_mod

DOCS_URL = "docs/privacy/what-kranto-sends.md"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kranto telemetry", description="usage reports: what "
                                "Kranto counts and sends, and whether it sends")
    p.add_argument("cmd", nargs="?", default="status",
                   choices=("status", "show", "docs", "schema", "event", *MODES))
    p.add_argument("day", nargs="?", help="show: a day (YYYY-MM-DD)")
    p.add_argument("--json", action="store_true", help="status: as JSON")
    p.add_argument("--sent", action="store_true", help="show: what was sent")
    p.add_argument("--wire", action="store_true", help="show: the exact bytes (OTLP/JSON)")
    p.add_argument("--errors", action="store_true", help="show: the error reports waiting")
    p.add_argument("--assistant", action="store_true",
                   help="show: the assistant's events waiting (detailed only)")
    return p


# set in the environment of an assistant's session: Kranto's console, any Claude Code
ASSISTANT_ENV = ("KRANTO_MCP_CONSOLE", "CLAUDECODE")
CONSENT_REFUSED = (
    "kranto telemetry {mode}: not from inside an assistant's session. Sending "
    "usage reports is your consent: choose it in your own terminal (Kranto "
    "telemetry {mode}) or on the page, Settings › Privacy & access "
    "(#/settings/privacy). Turning them off needs no approval: kranto telemetry off."
)


def in_assistant(environ=None) -> bool:
    import os

    env = os.environ if environ is None else environ
    return any(env.get(k) for k in ASSISTANT_ENV)


def event(home: Path, stdin) -> int:
    """``kranto telemetry event``: one hook's event (already reduced to the listed fields by
    the hook). Prints the one-time line's JSON for a start when it is due, else nothing;
    always exit 0."""
    from . import assistant

    try:
        ev = json.loads(stdin.read(20_000) or "{}")
    except (ValueError, OSError):
        return 0
    if not isinstance(ev, dict):
        return 0
    line = assistant.hook_event(home, ev)
    if line:
        print(json.dumps({"systemMessage": line}))
    return 0


@contextmanager
def _store_and_config(home: Path):
    """The library and the config, read as they are (no migration is applied here)."""
    from .. import config as config_mod
    from ..launcher import pending_migrations
    from ..store import Store

    try:
        cfg = config_mod.load(Path(home), dotenv=False)
    except config_mod.ConfigError:
        yield None, None
        return
    if not cfg.db_path.exists() or pending_migrations(cfg.db_path):
        yield None, cfg
        return
    store = Store.open(cfg.db_path)
    try:
        yield store, cfg
    finally:
        store.close()


def _n(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _status_text(st: dict) -> str:
    lines = [f"mode       {st['mode']}: {st['meaning']}"]
    if st["why"] == "DO_NOT_TRACK":
        lines.append(
            "           DO_NOT_TRACK is set: nothing is counted or sent, whatever the config says"
        )
    elif st["why"] == "KRANTO_TELEMETRY":
        lines.append("           set by KRANTO_TELEMETRY in the environment")
    elif not st["answered"]:
        lines.append(
            "           not answered yet: kranto setup, Welcome or Settings › Privacy & "
            "access ask once; until then nothing is sent"
        )
    lines.append("sending    " + ("on" if st["sending"] else f"no: {st['why_not']}"))
    if st["endpoint"]:
        lines.append(f"endpoint   {st['endpoint']} ({st['endpoint_from']})")
    last = st["last_sent"]
    lines.append(
        "last sent  "
        + (
            f"{last['day']} at {last['at']}, {last['bytes']} bytes "
            f"({last['gzip_bytes']} gzipped), HTTP {last['status']}"
            if last
            else "nothing has been sent from this install"
        )
    )
    if st["next"]:
        lines.append(f"next       {st['next']} UTC")
    lines.append(
        f"today      {st['bytes_today']} bytes of counters on this machine (kranto telemetry show)"
    )
    e = st.get("errors") or {}
    if st["sending"]:
        last = e.get("last_sent")
        lines.append(
            f"errors     {e.get('waiting', 0)} waiting (sent within minutes); "
            + (
                f"last batch {last['at']}, {_n(last['reports'], 'report')}, HTTP {last['status']}"
                if last
                else "none sent yet"
            )
            + " (kranto telemetry show --errors)"
        )
    else:
        lines.append("errors     error reports follow this choice: none is kept or sent")
    a = st.get("assistant") or {}
    if a.get("sending"):
        last = a.get("last_sent")
        lines.append(
            f"assistant  {_n(a.get('waiting', 0), 'record')} waiting (sent hour by "
            "hour); "
            + (
                f"last batch {last['at']}, {_n(last['records'], 'record')}, HTTP {last['status']}"
                if last
                else "none sent yet"
            )
            + " (kranto telemetry show --assistant)"
        )
    else:
        lines.append(
            "assistant  verb calls and sessions go with detailed only: none is kept or sent"
        )
    return "\n".join(lines)


def main(home: Path, argv: list[str]) -> int:
    args = parser().parse_intermixed_args(argv)  # show --sent DAY, as well as show DAY --sent
    home = Path(home)
    if args.cmd == "status":
        st = status(home)
        print(json.dumps(st, indent=1) if args.json else _status_text(st))
        return 0
    if args.cmd == "docs":
        print(docs_mod.page(), end="")
        return 0
    if args.cmd == "schema":  # the whole list, for the relay (ops/telemetry)
        from . import schema as schema_mod

        print(json.dumps(schema_mod.union(), indent=1, sort_keys=True))
        return 0
    if args.cmd == "show":
        return _show(home, args)
    if args.cmd == "event":
        return event(home, sys.stdin)
    if args.cmd in ("basic", "detailed") and in_assistant():
        print(CONSENT_REFUSED.format(mode=args.cmd), file=sys.stderr)
        return 3
    if args.cmd in ("basic", "detailed"):
        print(SUMMARY)
        print(
            f"\n{args.cmd}: {MEANING[args.cmd]}.\nWhat Kranto sends: {DOCS_LINK} "
            "(kranto telemetry docs)\n"
        )
    try:
        st = set_mode(home, args.cmd)
    except TelemetryError as exc:
        print(f"kranto telemetry: {exc}")
        return 2
    print(_status_text(st))
    return 0


def _show_errors(home: Path, st: dict, tier: str, wire: bool) -> None:
    if not st["sending"]:
        print(f"error reports: none is kept or sent ({st['why_not']})")
        return
    pv = errors.preview(home, tier)
    if not pv["reports"]:
        print("error reports: none waiting")
        return
    if wire:
        print(pv["wire"])
        return
    print(
        f"error reports waiting ({len(pv['reports'])}, {pv['bytes']} bytes; sent within minutes):"
    )
    print(report.pretty({"resource": pv["resource"], "reports": pv["reports"]}))


def _show_assistant(home: Path, st: dict, wire: bool) -> None:
    from . import assistant

    if not (st.get("assistant") or {}).get("sending"):
        print(
            "assistant events (verb calls, sessions, slash commands): sent with detailed "
            "only; none is kept or sent now"
        )
        return
    pv = assistant.preview(home)
    if not pv["records"]:
        print("assistant events: none waiting")
        return
    if wire:
        print(pv["wire"])
        return
    print(
        f"assistant events waiting ({len(pv['records'])}, {pv['bytes']} bytes; the hours "
        "that have ended go hour by hour):"
    )
    print(report.pretty({"resource": pv["resource"], "records": pv["records"]}))


def _show(home: Path, args) -> int:
    if args.sent:
        if args.day:
            from . import assistant

            body = (
                send.sent_body(home, args.day)
                or errors.sent_body(home, args.day)
                or assistant.sent_body(home, args.day)
            )
            if body is None:
                print(f"nothing was sent for {args.day}")
                return 1
            print(body.decode())
            return 0
        rows = send.sent(home)
        batches = errors.sent(home)
        from . import assistant

        abatches = assistant.sent(home)
        if not rows and not batches and not abatches:
            print("nothing has been sent from this install")
        for r in rows:
            print(f"{r['day']}  {r['at']}  {r['bytes']} bytes  HTTP {r['status']}  {r['endpoint']}")
        for b in batches:
            print(
                f"{b['id']}  {b['at']}  {_n(b['reports'], 'error report')}, "
                f"{b['bytes']} bytes  HTTP {b['status']}  {b['endpoint']}"
            )
        for b in abatches:
            print(
                f"{b['id']}  {b['at']}  {_n(b['records'], 'assistant record')}, "
                f"{b['bytes']} bytes  HTTP {b['status']}  {b['endpoint']}"
            )
        return 0
    day = args.day or datetime.now(UTC).strftime("%Y-%m-%d")
    st = status(home)
    if st["mode"] == "off":
        print("off: nothing is counted, so there is no report to show")
        return 0
    tier = st["mode"] if st["mode"] in ("basic", "detailed") else "basic"
    if args.errors:
        _show_errors(home, st, tier, args.wire)
        return 0
    if args.assistant:
        _show_assistant(home, st, args.wire)
        return 0
    with _store_and_config(home) as (store, cfg):
        payload = report.build(home, day, store=store, cfg=cfg, tier=tier)
    if args.wire:
        print(send.wire(payload).decode())
    else:
        print(report.pretty(payload))
        print()
        _show_errors(home, st, tier, False)
        print()
        _show_assistant(home, st, False)
    if not st["sending"]:  # stderr: --wire's stdout is the bytes alone
        print(f"\n(not sent: {st['why_not']})", file=sys.stderr)
    return 0
