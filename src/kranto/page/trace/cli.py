"""``brb trace …`` (and ``kranto trace …``, passed through): a trace of Kranto's own runs as
readable text: a console or Open in Claude Code session (``session:<tid>``), a
kept research run (``research:<stem>``). ``list`` the traces (the build loop's old rows too,
read from ``trace.db`` without writing it), ``show`` one as a tree (``--errors``: only error spans
and their ancestors; ``--span <id>``: one span and its payload; ``--raw``: that span's lines
from the file, unredacted, with the path: the owner's terminal only, never the page),
``follow`` one while it runs. ``--json`` prints the API's records; ``--share`` also hides the
host, the login and the home (redaction rule 4)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .model import parse_trace_id
from .redact import Redactor

GLYPH = {"ok": "●", "error": "✕", "running": "◔", "unset": "○"}


def loop_home(args) -> Path:
    """``--loop-home``, else the loop home ``settings.store`` finds."""
    from ..settings.store import Config
    lh = getattr(args, "loop_home", None)
    return Path(Config(Path(lh).expanduser() if lh else None).home)


def open_trace(tid: str, home: Path):
    """The ``SessionTrace`` of ``session:<tid>`` or the ``FileTrace`` of ``research:<stem>``,
    read; ValueError when there is none (a build's: the build loop left)."""
    src, key, _n = parse_trace_id(tid)
    if src == "session":                         # a console or Open in Claude Code session's
        from .session import SessionTrace
        t = SessionTrace(Path(home) / "term" / key, key)
        t.refresh()
        if not t.rec:
            raise ValueError(f"no session {key!r}")
        return t
    if src == "research":
        from .file import FileTrace, research_file
        f = research_file(Path(home), key)
        if f is None or not f.is_file():
            raise ValueError(f"no research run {key!r}")
        t = FileTrace(f, f"research:{key}", f"Research · {key}")
        t.refresh()
        return t
    if src in ("build", "maint", "loop"):
        raise ValueError(f"{src} traces left with the build loop: 'brb trace list' still "
                         "shows their row")
    raise ValueError(f"{src} traces are not readable here yet")


def sessions(home: Path) -> list:
    """Every session's trace in the loop home's ``term/``, read."""
    from ..term.store import Store
    from .session import SessionTrace
    out = []
    for r in Store(Path(home) / "term").all():
        if not r.get("tid"):
            continue
        t = SessionTrace(Path(home) / "term" / r["tid"], r["tid"])
        try:
            t.refresh()
        except (OSError, ValueError):
            continue
        out.append(t)
    return out


def money(v) -> str:
    return "–" if v is None else f"${v:,.2f}"


def dur(s) -> str:
    if s is None:
        return "–"
    s = float(s)
    if s < 1:
        return f"{int(s * 1000)} ms"
    if s < 60:
        return f"{s:.1f} s" if s < 10 else f"{int(s)} s"
    m = int(round(s / 60))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min"


def when(ts) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "–"


def num(n) -> str:
    n = int(n or 0)
    return f"{n / 1e6:.2f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def cite(rel: str) -> str:
    """``r2/transcripts/verify.transcript.jsonl`` for a file under the task's ``.den/v5/``."""
    return rel.removeprefix(".den/v5/").removeprefix(".den/")


def head_line(t) -> str:
    s = t.summary
    bits = [s["title"], s["state"] + (" (held)" if s.get("outcome") == "held" else ""),
            dur(s.get("wall_s")), f"{money(s.get('usd'))} (exact)" if s.get("usd") is not None
            else "cost not known", f"{s['sessions']} sessions", f"{s['tools']} tool calls",
            f"{s['errors']} errors"]
    return " · ".join(bits)


def span_line(sp, red: Redactor, width: int = 100) -> str:
    g = "⊘" if sp.attrs.get("denied") else GLYPH.get(sp.status, "○")
    if sp.kind == "event":
        g = "⚠" if sp.attrs.get("level") in ("warning", "error") else "ⓘ"
    name = sp.name
    if sp.kind == "session":
        bits = [sp.attrs.get("model"), f"{sp.attrs.get('turns') or 0} turns",
                (sp.attrs.get("session_id") or "")[:8]]
        name = f"session {sp.name} · " + " · ".join(str(b) for b in bits if b)
    elif sp.kind == "call":
        name = sp.name
    text = red.text(sp.preview or "") if sp.kind in ("tool", "subagent", "turn", "event") else ""
    wall = (sp.end - sp.start) if sp.start is not None and sp.end is not None else None
    cost = money(sp.usd) + ("~" if sp.usd_kind == "share" else "") if sp.usd is not None else ""
    left = f"{'  ' * sp.depth}{g} {name}"
    if text:
        left += f"  {text}"
    left = left[:width]
    tail = f"{dur(wall) if sp.kind not in ('event',) else '':>8} {cost:>9}"
    return f"{left:<{width}} {tail}"


def keep_errors(t) -> set[str]:
    """The error spans and their ancestors (Langfuse's level filter)."""
    keep = set()
    for sp in t.spans.values():
        if sp.status == "error" or (sp.kind == "event" and sp.attrs.get("level") == "error"):
            cur, hops = sp, 0
            while cur is not None and cur.id not in keep and hops < 64:
                keep.add(cur.id)
                cur = t.spans.get(cur.parent) if cur.parent else None
                hops += 1
    return keep


def cmd_list(args) -> None:
    from .base import failed_label
    from .index import archived
    home = loop_home(args)
    since = None
    if args.since:
        unit = args.since[-1]
        k = {"d": 86400, "h": 3600, "m": 60}.get(unit)
        try:
            since = time.time() - float(args.since[:-1] if k else args.since) * (k or 86400)
        except ValueError:
            sys.exit("brb trace list: --since is like 7d, 12h or 30m")
    rows: list[tuple[dict, str | None]] = []
    src = args.source or "all"
    if src in ("all", "session"):
        rows += [(t.summary, failed_label(t)) for t in sessions(home)]
    if src in ("build", "maint", "loop"):        # the build loop's rows, read-only, by name
        rows += [({**r, "wall_s": round(r["ended"] - r["started"], 1)
                   if r["ended"] and r["started"] else None,
                   "tokens": {"in": r["tokens_in"] or 0, "out": r["tokens_out"] or 0}},
                  r["failed_label"])
                 for r in archived(Path(home) / "trace.db", source=src, limit=args.limit)]
    rows = [(s, fl) for s, fl in rows if not (since and (s.get("started") or 0) < since)
            and not (args.state and s.get("state") != args.state)]
    rows.sort(key=lambda x: -(x[0].get("started") or 0))
    rows = rows[:args.limit]
    if args.json:
        print(json.dumps([{**s, "failed_label": fl} for s, fl in rows], indent=2, default=str))
        return
    if not rows:
        print("No traces." + (" (none since then)" if since else ""))
        return
    w = max(len(s["id"]) for s, _ in rows)
    print(f"{'TRACE':<{w}}  {'STATE':<8} {'STARTED':<16}  {'WALL':>8} {'COST':>8} "
          f"{'SESSIONS':>8} {'TOOLS':>6} {'ERRORS':>6}  FAILED AT")
    for s, fl in rows:
        state = "held" if s.get("outcome") == "held" and s.get("state") == "ok" \
            else str(s.get("state") or "")
        print(f"{s['id']:<{w}}  {state:<8} {when(s.get('started')):<16}  "
              f"{dur(s.get('wall_s')):>8} {money(s.get('usd')):>8} {s.get('sessions') or 0:>8} "
              f"{s.get('tools') or 0:>6} {s.get('errors') or 0:>6}  {fl or ''}")


def cmd_show(args) -> None:
    try:
        t = open_trace(args.trace, loop_home(args))
    except ValueError as e:
        sys.exit(f"brb trace show: {e}")
    red = Redactor(share=args.share)
    if args.span:
        sp = t.spans.get(args.span) or next(
            (x for x in t.spans.values() if x.id.startswith(args.span)), None)
        if sp is None:
            sys.exit(f"brb trace show: no span {args.span} in {t.id}")
        if args.raw:
            from .payload import raw_lines
            for f, at, text in raw_lines(t, sp):
                print(f"{t.taskdir / f} (byte {at}):")
                print(text)
            return
        from .payload import PayloadError, payload
        out = {"span": red.value(sp.full())}
        for part in ("input", "output"):
            try:
                out[part] = payload(t, sp.id, part, red=red)
            except PayloadError as e:
                out[part] = {"error": str(e)}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return
        print(span_line(sp, red).rstrip())
        f = sp.source or {}
        print(f"  {sp.kind} · {sp.status} · id {sp.id} · {f.get('file')}:{f.get('line')}")
        if sp.error:
            print(f"  error: {red.text(sp.error.get('message') or '')}")
        for part in ("input", "output"):
            p = out[part]
            print(f"\n{part.title()}:")
            if p.get("fields"):
                for fd in p["fields"]:
                    print(f"  {fd['key']}: {fd['value']}")
            elif p.get("text"):
                print("  " + p["text"].replace("\n", "\n  "))
            elif p.get("error"):
                print(f"  ({p['error']})")
        n = sum(r["n"] for r in red.report())
        if n:
            print(f"\n{n} redactions: " + ", ".join(f"{r['n']} {r['kind']}" for r in red.report()))
        return
    if args.json:
        print(json.dumps({"trace": t.summary, "links": t.links,
                          "spans": [red.value(sp.summary()) for sp in
                                    sorted(t.spans.values(), key=lambda s: s.pos)]},
                         indent=2, ensure_ascii=False))
        return
    print(red.text(head_line(t)))
    keep = keep_errors(t) if args.errors else None
    from .base import failed_label
    fl = failed_label(t)
    if fl:
        print(f"failed at: {fl}")
    for sp in sorted(t.spans.values(), key=lambda s: s.pos):
        if sp.kind == "run":
            continue
        if keep is not None and sp.id not in keep:
            continue
        if keep is None and not args.all and sp.kind in ("turn", "hook") or \
                keep is None and not args.all and sp.depth > 3:
            continue
        line = span_line(sp, red).rstrip()
        if sp.id == t.summary.get("failed_at"):
            line += "   ← failed at"
        if sp.status == "error" and sp.source:
            line += f"   {cite(sp.source['file'])}:{sp.source.get('line')}"
        print(line)
        if sp.kind == "stage" and sp.attrs.get("unlisted_usd"):
            left = f"{'  ' * (sp.depth + 1)}○ one-shot calls (no transcript)"
            print(f"{left:<100} {'':>8} {money(sp.attrs['unlisted_usd']):>9}")
        if sp.kind == "stage" and sp.attrs.get("children_usd"):
            print(f"{'  ' * (sp.depth + 1)}the stage's figure says {money(sp.usd)}; "
                  f"its calls and sessions add up to {money(sp.attrs['children_usd'])}")
    for lk in t.links:
        where = "the trace" if lk.get("span") else lk.get("note")
        print(f"{lk['kind']} {lk.get('ref')}: " + (f"span {lk['span']}" if lk.get("span")
                                                    else where))


def cmd_follow(args) -> None:
    """``follow <trace>``: the trace's spans as they land, one line each, indented as the tree;
    a span that was running is printed again when it ends. Each read takes only what the files
    gained (the readers' own place in each file). Ends with the build (or the session), or
    Ctrl-C; ``--max-s`` stops it sooner."""
    try:
        t = open_trace(args.trace, loop_home(args))
    except ValueError as e:
        sys.exit(f"brb trace follow: {e}")
    red = Redactor(share=args.share)
    print(red.text(head_line(t)), flush=True)
    shown: dict[str, str] = {}                       # span id -> the status it was printed with
    stop = time.monotonic() + args.max_s if args.max_s else None
    try:
        while True:
            for sp in sorted(t.spans.values(), key=lambda s: s.pos):
                if sp.kind == "run" or (sp.kind == "hook" and not args.all):
                    continue
                was = shown.get(sp.id)
                if was == sp.status or (was is not None and was != "running"):
                    continue
                shown[sp.id] = sp.status
                print(span_line(sp, red).rstrip() + ("   ← ended" if was else ""), flush=True)
            if not t.running:
                s = t.summary
                print(f"over: {s['state']}" + (" (held)" if s.get("outcome") == "held" else "")
                      + f" · {s['sessions']} sessions · {s['tools']} tool calls", flush=True)
                return
            if stop is not None and time.monotonic() > stop:
                return
            time.sleep(args.every)
            t.refresh()
    except KeyboardInterrupt:
        print(flush=True)


def cmd_export(args) -> None:
    """``export <trace> --otlp <url>``: the trace as OTLP/HTTP JSON to that collector (the
    ``trace.export.otlp_url`` setting when no URL is given); ``--out <file>`` writes the body
    instead, sending nothing. Content only with ``--content`` (or ``trace.export.content``)."""
    from ..settings.store import Config
    from .export_otlp import send, spans, trace_id
    home = loop_home(args)
    ex = (Config(home).get("trace") or {}).get("export") or {}
    url = args.otlp or ex.get("otlp_url") or ""
    if not url and not args.out:
        sys.exit("brb trace export: give --otlp <url> (or set trace.export.otlp_url), or --out")
    if url and not url.startswith(("http://", "https://")):
        sys.exit("brb trace export: --otlp is an http(s) address, like http://127.0.0.1:4318")
    try:
        t = open_trace(args.trace, home)
    except ValueError as e:
        sys.exit(f"brb trace export: {e}")
    body = spans(t, content=bool(args.content or ex.get("content")))
    n = len(body["resourceSpans"][0]["scopeSpans"][0]["spans"])
    if args.out:
        Path(args.out).write_text(json.dumps(body, ensure_ascii=False))
        print(f"{n} spans of {t.id} written to {args.out} (trace id {trace_id(t.id)})")
        return
    try:
        status = send(body, url)
    except OSError as e:
        sys.exit(f"brb trace export: {url} did not take it: {e}")
    print(f"{n} spans of {t.id} sent to {url} ({status}; trace id {trace_id(t.id)})")


def add_trace_group(sub) -> None:
    p = sub.add_parser("trace", help="agent traces: a session's turns and tool calls "
                                     "(list, show, follow, export)")
    p.add_argument("--loop-home", default=None, help="default: $KRANTO_LOOP_HOME, else ~/kranto-loop")
    p.add_argument("--root", default=None, help=argparse.SUPPRESS)   # builds' folder: unused
    g = p.add_subparsers(dest="trace_cmd", required=True)
    s = g.add_parser("list", help="the traces, newest first (sessions; the build loop's old rows)")
    s.add_argument("--source", default="all", choices=["all", "session", "build", "maint", "loop"],
                   help="all: the sessions (default); build, maint, loop: the build loop's old "
                        "rows")
    s.add_argument("--since", default=None, help="7d, 12h, 30m")
    s.add_argument("--state", default=None, choices=["running", "ok", "error", "stopped"])
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_list)
    s = g.add_parser("show", help="one trace as a tree: session:<tid>, research:<stem>")
    s.add_argument("trace")
    s.add_argument("--errors", action="store_true", help="error spans and their ancestors only")
    s.add_argument("--all", action="store_true", help="every span (turns and hooks too)")
    s.add_argument("--span", default=None, help="one span (its id or a prefix) and its payload")
    s.add_argument("--raw", action="store_true",
                   help="with --span: the span's lines from the file, unredacted, and the path")
    s.add_argument("--share", action="store_true", help="also hide the host, login and home")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_show)
    s = g.add_parser("follow", help="one trace while it runs: each span as it lands, until it ends")
    s.add_argument("trace")
    s.add_argument("--all", action="store_true", help="the hooks' rows too")
    s.add_argument("--share", action="store_true", help="also hide the host, login and home")
    s.add_argument("--every", type=float, default=0.5, help=argparse.SUPPRESS)
    s.add_argument("--max-s", type=float, default=0, help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_follow)
    s = g.add_parser("export", help="one trace as OpenTelemetry spans to an OTLP/HTTP collector")
    s.add_argument("trace")
    s.add_argument("--otlp", default=None, help="the collector, like http://127.0.0.1:4318 "
                                                "(default: trace.export.otlp_url)")
    s.add_argument("--content", action="store_true",
                   help="also the turns' messages and the tools' arguments and results, redacted")
    s.add_argument("--out", default=None, help="write the OTLP JSON to this file instead")
    s.set_defaults(fn=cmd_export)
