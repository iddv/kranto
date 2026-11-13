"""``kranto cub …`` and ``afk cub …``: the same functions as the page's API,
from a terminal. Every command prints words (``--json``: the record) and exits 0, 2 when Kranto
refused it (with why), 1 on an error.

The command line acts on this home's database and ``kranto.yaml`` itself, as the page's API
does; the running server sees the change at its next call (the cub runtime reloads when the
registry changes and re-reads the ``cubs:`` section when the file changes), and its reaper
stops a stopped or removed cub's process within ten seconds. ``run`` asks the running server
(its scheduler runs jobs), with the command line's door token.

House-confirm actions are the page's: ``live`` prints the page's address and exits 2; ``add``,
``update --apply`` and ``remove`` ask on the terminal (``y/N``) unless ``--yes``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ... import config as config_mod
from .. import tickets
from . import files, inspect, install, logs, views

REFUSED, ERROR = 2, 1


def add_parser(sub) -> argparse.ArgumentParser:
    """``cub`` and its commands on ``sub`` (an argparse subparsers object)."""
    p = sub.add_parser("cub", help="cubs: add, list, inspect, update, stop, remove, …")
    cs = p.add_subparsers(dest="cub_cmd", required=True)

    def sp(name: str, **kw) -> argparse.ArgumentParser:
        s = cs.add_parser(name, **kw)
        s.add_argument("--json", action="store_true", help="the record as JSON")
        return s

    a = sp("add", help="add a cub from a folder or a git URL (in practice first)")
    a.add_argument("source", help="a folder, or a git URL; URL#subdirectory=path/in/it names "
                                  "one cub of a repository that holds several")
    a.add_argument("--ref", help="a tag, a branch or a commit (git)")
    a.add_argument("--name", help="refused unless the cub.yaml's id is this")
    a.add_argument("--topics", help="narrow it to these topic ids: 1,3")
    a.add_argument("--yes", action="store_true", help="no y/N question")
    sp("list", help="the installed cubs").add_argument(
        "--all", action="store_true", help="removed ones too")
    i = sp("inspect", help="one cub: its source, grants in words, limits, runs")
    i.add_argument("id")
    i.add_argument("--manifest", action="store_true", help="its cub.yaml as approved")
    i.add_argument("--grants", action="store_true", help="its grants as stored")
    i.add_argument("--kv", action="store_true", help="the keys of its store")
    for name, words in (("enable", "turn it on (cubs.<id>.enabled)"),
                        ("disable", "turn it off; what it asks you stays open"),
                        ("stop", "kill its process, pause it, close what it asks you"),
                        ("resume", "resume a paused or stopped cub")):
        s = sp(name, help=words)
        s.add_argument("id")
    for name, words in (("dry", "a kind back to practice: nothing is sent"),
                        ("live", "a kind for real: on the page")):
        s = sp(name, help=words)
        s.add_argument("id")
        s.add_argument("kind")
    u = sp("update", help="fetch its source again and show the change")
    u.add_argument("id")
    u.add_argument("--apply", metavar="SHA_OR_JOB", help="apply the staged update")
    u.add_argument("--yes", action="store_true")
    so = sp("source", help="where its updates are read from now (its folder moved or is gone); "
                           "the installed copy stays")
    so.add_argument("id")
    so.add_argument("source", help="a folder, or a git URL (URL#subdirectory=path/in/it)")
    so.add_argument("--ref", help="a tag, a branch or a commit (git)")
    r = sp("remove", help="remove it (its history stays)")
    r.add_argument("id")
    r.add_argument("--yes", action="store_true")
    r.add_argument("--purge", action="store_true", help="its stored data and folder too")
    lg = sp("log", help="its log")
    lg.add_argument("id")
    lg.add_argument("--run", help="one run's uuid")
    lg.add_argument("--since", help="an ISO time")
    lg.add_argument("-n", type=int, default=200)
    lg.add_argument("--calls", action="store_true", help="its calls instead of its log")
    rn = sp("run", help="run one of its jobs now (Kranto must be running)")
    rn.add_argument("id")
    rn.add_argument("job", help="the job's kind, e.g. newsletter.weekly")
    ac = sp("act", help="run one of its actions now, as its page's form does (Kranto must be "
                        "running)")
    ac.add_argument("id")
    ac.add_argument("action", help="the action, e.g. draft_markdown or blog.draft_markdown")
    ac.add_argument("--field", action="append", default=[], metavar="KEY=VALUE",
                    help="a field; KEY=@path reads the value from a file on this machine")
    ck = sp("check", help="check a cub's folder; nothing is installed")
    ck.add_argument("path")
    sf = sp("stopfile", help="the cubs.STOP file: every cub stopped while it exists")
    g = sf.add_mutually_exclusive_group()
    g.add_argument("--set", action="store_true")
    g.add_argument("--clear", action="store_true")
    ev = sp("eval", help="run a cub's own tests and the standard fixtures (your own cubs)")
    ev.add_argument("id")
    sp("jobs", help="fetch jobs and their states")
    nw = sp("new", help="Kranto builds a cub from a sentence (0.6)")
    nw.add_argument("description", nargs="?")
    return p


def main(home: Path, argv: list[str], *, ask=input, out=None, rt=None) -> int:
    """``kranto cub …`` for the home ``home`` (``rt``: an open runtime, for tests)."""
    parser = argparse.ArgumentParser(prog="kranto")
    add_parser(parser.add_subparsers(dest="cmd", required=True))
    args = parser.parse_args(["cub", *argv])
    return run(args, home, ask=ask, out=out, rt=rt)


def run(args, home: Path, *, ask=input, out=None, rt=None) -> int:
    from ...runtime import open_runtime
    out = out or sys.stdout
    try:
        if rt is None:
            cfg = config_mod.load(home)
            rt = open_runtime(cfg)
        return COMMANDS[args.cub_cmd](rt, args, ask, out)
    except install.InstallError as exc:
        print(f"kranto cub: {exc.words}", file=sys.stderr)
        return REFUSED if exc.code in (400, 403, 404, 409) else ERROR
    except (ValueError, config_mod.ConfigError) as exc:
        print(f"kranto cub: {exc}", file=sys.stderr)
        return REFUSED


def _say(out, args, record, words: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(record, indent=2, default=str), file=out)
    else:
        print(words, file=out)


def _yes(args, ask, question: str) -> bool:
    if getattr(args, "yes", False):
        return True
    try:
        return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def since_of(text: str | None):
    """``2h``, ``30m``, ``3d`` ago, or an ISO time; None for none."""
    import re
    from datetime import datetime, timedelta

    from ...store import utcnow
    if not text:
        return None
    m = re.fullmatch(r"(\d{1,4})([mhd])", text.strip())
    if m:
        n = int(m.group(1))
        return utcnow() - {"m": timedelta(minutes=n), "h": timedelta(hours=n),
                           "d": timedelta(days=n)}[m.group(2)]
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise install.InstallError("--since is 30m, 2h, 3d or an ISO time") from None
    if at.tzinfo is None:
        from datetime import UTC
        at = at.replace(tzinfo=UTC)
    return at


def _words(lines: list[list[str]]) -> str:
    width = max((len(k) for k, _ in lines), default=0)
    return "\n".join(f"  {k.ljust(width)}  {v}" for k, v in lines)


# -- the commands ---------------------------------------------------------------------------------


def c_add(rt, args, ask, out) -> int:
    topics = None
    if args.topics:
        try:
            topics = [int(t) for t in args.topics.split(",") if t.strip()]
        except ValueError:
            raise install.InstallError("--topics is topic ids: 1,3") from None
    j = install.start(rt, args.source, ref=args.ref, background=False)
    if j["state"] != "awaiting_confirm":
        raise install.InstallError(j.get("error") or f"the fetch is {j['state']}", 409)
    c = j["cub"]
    if args.name and args.name != c["id"]:
        install.cancel(rt.store, rt.cfg, j["id"])
        raise install.InstallError(f"its cub.yaml says {c['id']}, not {args.name}: a cub is "
                                   "never renamed")
    findings = c["inventory"]["findings"]
    print(_words(c["words"]), file=out)
    for f in findings:
        print(f"  ! {f['text']}", file=out)
    if not _yes(args, ask, f"Install {c['title']} {c['version']} ({c['trust']}) in practice?"):
        install.cancel(rt.store, rt.cfg, j["id"])
        print("not installed", file=out)
        return REFUSED
    row = install.install(rt, j["id"], door="cli", topics=topics)
    _say(out, args, row, f"installed {c['id']} {c['version']} ({c['trust']}) in practice")
    return 0


def c_list(rt, args, ask, out) -> int:
    data = views.listing(rt, removed=args.all)
    if args.json:
        print(json.dumps(data, indent=2, default=str), file=out)
        return 0
    if not data["cubs"]:
        print("no cubs installed (kranto cub add FOLDER-OR-GIT-URL)", file=out)
    for c in data["cubs"]:
        if c.get("unreadable"):
            u = c["unreadable"]
            print(f"{c['id']:<16} {u['words']} (error {u['error_id']}: kranto report "
                  f"{u['error_id']})", file=out)
            continue
        last = c["last_run"]["status"] if c["last_run"] else "no run yet"
        spend = c["spend"]
        cap = "no cap" if spend["cap_usd"] is None else f"${spend['cap_usd']:g}"
        print(f"{c['id']:<16} {c['version']:<9} {c['trust']:<10} {c['state']:<9} "
              f"{c['mode']:<12} last: {last}; {c.get('asks', c['tickets_open'])} waiting; "
              f"${spend['month_usd']:.2f} of {cap} this month", file=out)
    if data["stop_file"]:
        print(f"cubs.STOP exists ({tickets.stop_file()}): no cub runs", file=out)
    if not data["enabled"]:
        print("cubs are off (cubs.enabled: false)", file=out)
    return 0


def c_inspect(rt, args, ask, out) -> int:
    d = views.detail(rt, args.id)
    if d is None:
        raise install.InstallError(f"no cub {args.id}", 404)
    if args.manifest:
        try:
            print((files.cub_dir(rt.cfg, args.id) / "src" / "cub.yaml").read_text(),
                  file=out, end="")
        except OSError:
            raise install.InstallError(f"{args.id}'s folder is missing") from None
        return 0
    if args.grants:
        print(json.dumps(d["grants"], indent=2, sort_keys=True), file=out)
        return 0
    if args.kv:
        from . import kv
        keys = kv.listing(rt.store, args.id, limit=500)["keys"]
        for k in keys:
            print(f"{k['key']}  {k['bytes']} bytes  {k['updated_at']}", file=out)
        return 0
    if args.json:
        print(json.dumps(d, indent=2, default=str), file=out)
        return 0
    src = d["source"]
    print(f"{d['title']} ({d['id']}) {d['version']}, {d['trust']}, {d['state']}, {d['mode']}",
          file=out)
    sub = f"#subdirectory={src['subdirectory']}" if src.get("subdirectory") else ""
    print(f"  source   {src['kind']} {src.get('path') or src.get('url') or ''}{sub}"
          f"{' @ ' + src['sha'][:12] if src.get('sha') else ''}", file=out)
    if d.get("source_gone"):
        print(f"           source gone: {d['source_gone']['words']}", file=out)
    print(f"  pinned   {'yes' if d['pinned'] else 'NO'}; its files "
          f"{'match' if d['tree_ok'] else 'DO NOT match'} the pin", file=out)
    if d["paused"]:
        print(f"  paused   {d['paused']['note']}", file=out)
    print(f"  live     {', '.join(d['live']) or 'nothing (practice)'}", file=out)
    up = d.get("update")
    if up:
        from ...launcher import port_of
        where = (f"on the page, http://127.0.0.1:{port_of(rt.cfg)}/brb/#/cub/{args.id}"
                 if up.get("needs") == "house"
                 else f"kranto cub update {args.id} --apply {up['job']}")
        print(f"  update   {up.get('version')} is staged (job {up['job']}); apply it {where}"
              + "".join(f"\n           it may now: {a}" for a in up.get("adds") or []), file=out)
    lim = d["limits"]
    print(f"  limits   {lim['memory_mb']} MiB, {lim['pids']} processes, {lim['cpu_pct']}% CPU, "
          f"{lim['tmp_mb']} MiB /tmp, {lim['kv_mb']} MiB stored", file=out)
    print(_words(d["words"]), file=out)
    for f in (d.get("inventory") or {}).get("findings", []):
        print(f"  ! {f['text']}", file=out)
    for r in d["runs"][:5]:
        print(f"  run {r['finished_at'][:16]} {r['kind']} {r['status']}"
              f"{': ' + r['error'] if r['error'] else ''}", file=out)
    return 0


def c_source(rt, args, ask, out) -> int:
    install.set_source(rt, args.id, args.source, args.ref)
    _say(out, args, views.row(rt, args.id),
         f"{args.id} reads its updates from {args.source} now; the installed copy is unchanged "
         f"(kranto cub update {args.id} looks there)")
    return 0


def _switched(rt, args, out, words: str) -> int:
    _say(out, args, views.row(rt, args.id), words)
    return 0


def c_enable(rt, args, ask, out) -> int:
    install.set_enabled(rt, args.id, True)
    return _switched(rt, args, out, f"{args.id} is on")


def c_disable(rt, args, ask, out) -> int:
    install.set_enabled(rt, args.id, False)
    return _switched(rt, args, out, f"{args.id} is off; what it asks you stays open")


def c_stop(rt, args, ask, out) -> int:
    install.stop(rt, args.id)
    return _switched(rt, args, out, f"{args.id} is stopped (its process ends within 10 s); "
                                    f"what it asked you is closed. kranto cub resume {args.id}")


def c_resume(rt, args, ask, out) -> int:
    install.resume(rt, args.id)
    return _switched(rt, args, out, f"{args.id} is running again")


def c_dry(rt, args, ask, out) -> int:
    install.set_mode(rt, args.id, args.kind, False)
    return _switched(rt, args, out, f"{args.kind} is practice for {args.id}: nothing is sent")


def c_live(rt, args, ask, out) -> int:
    from ...launcher import port_of
    url = f"http://127.0.0.1:{port_of(rt.cfg)}/brb/#/cub/{args.id}?sel=settings"
    print(f"a kind goes live on the page, with its confirm: {url}", file=out)
    return REFUSED


def c_update(rt, args, ask, out) -> int:
    if args.apply:
        j = next((x for x in install.jobs(rt.store, rt.cfg, limit=50)
                  if x["kind"] == "update" and x["state"] == "awaiting_confirm"
                  and (x.get("cub") or {}).get("id") == args.id
                  and args.apply in (x["id"], (x["cub"].get("sha") or "")[:len(args.apply)])),
                 None)
        if j is None:
            raise install.InstallError(f"no staged update of {args.id} is {args.apply}", 404)
        if j["needs"] == "house":
            from ...launcher import port_of
            print(f"this update adds a permission or the cub may send: apply it on the page, "
                  f"http://127.0.0.1:{port_of(rt.cfg)}/brb/#/cub/{args.id}", file=out)
            return REFUSED
        if not _yes(args, ask, f"Apply {args.id} {j['cub']['version']}?"):
            return REFUSED
        install.apply_update(rt, j["id"], args.id, door="cli")
        _say(out, args, views.row(rt, args.id), f"updated {args.id} to {j['cub']['version']}")
        return 0
    j = install.start(rt, kind="update", cid=args.id, background=False)
    if j["state"] == "cancelled":
        _say(out, args, j, f"{args.id} is up to date")
        return 0
    if j["state"] != "awaiting_confirm":
        raise install.InstallError(j.get("error") or f"the fetch is {j['state']}", 409)
    c = j["cub"]
    d, diff = c["delta"], c["diff"]
    lines = [f"{args.id} {c['version']} is staged (job {j['id']})",
             f"  files: {diff['counts']['added']} added, {diff['counts']['removed']} removed, "
             f"{diff['counts']['changed']} changed"]
    for block, items in d["added"].items():
        lines.append(f"  + {block}: {', '.join(items)}")
    for block, items in d["removed"].items():
        lines.append(f"  - {block}: {', '.join(items)}")
    lines.append(f"  apply: kranto cub update {args.id} --apply {j['id']}"
                 + (" (on the page: it adds a permission or may send)"
                    if j["needs"] == "house" else ""))
    _say(out, args, j, "\n".join(lines))
    return 0


def c_remove(rt, args, ask, out) -> int:
    if not _yes(args, ask, f"Remove {args.id}? What it asks you closes; its history stays."):
        return REFUSED
    res = install.remove(rt, args.id, purge=args.purge)
    _say(out, args, res, f"removed {args.id}" + (" and its data" if args.purge else
                                                 f"; its folder is kept 30 days: {res['kept']}"))
    return 0


def c_log(rt, args, ask, out) -> int:
    if args.calls:
        rows = [dict(r) for r in rt.store.query(
            "SELECT service, op, status, ticket_id, run_uuid, ms, detail, created_at FROM "
            "cub_calls WHERE cub = ? ORDER BY id DESC LIMIT ?", (args.id, args.n))]
        if args.json:
            print(json.dumps(rows, indent=2), file=out)
        for r in reversed(rows) if not args.json else ():
            print(f"{r['created_at'][:19]} {r['service']} {r['op']} {r['status']}"
                  f"{' ' + r['detail'] if r['detail'] else ''}", file=out)
        return 0
    lines = logs.read(rt.cfg, args.id, run=args.run, since=since_of(args.since),
                      limit=max(1, min(args.n, 2000)))
    if args.json:
        print(json.dumps(lines, indent=2), file=out)
        return 0
    for x in lines:
        print(f"{str(x.get('ts', ''))[:19]} {x.get('src', '')} {x.get('level', '')} "
              f"{x.get('msg', '')}", file=out)
    return 0


def c_run(rt, args, ask, out) -> int:
    import httpx

    from ...launcher import port_of
    from ...tokens import Store, tokens_dir
    token = Store(tokens_dir()).value("cli")
    url = f"http://127.0.0.1:{port_of(rt.cfg)}/api/cubs/{args.id}/run"
    try:
        r = httpx.post(url, json={"job": args.job}, timeout=10,
                       headers={"Authorization": f"Bearer {token}"} if token else {})
    except httpx.HTTPError:
        raise install.InstallError("Kranto is not running here: kranto up, then try again",
                                   409) from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400:
        raise install.InstallError(body.get("error") or f"Kranto answered {r.status_code}",
                                   r.status_code if r.status_code in (403, 404, 409) else 400)
    if not body.get("started"):
        raise install.InstallError(body.get("why") or "not started", 409)
    _say(out, args, body, f"{args.job} started: kranto cub log {args.id} to follow it")
    return 0


FIELD_FILE_MAX = 60_000          # under the page API's 64 KB body


def fields_of(pairs: list[str]) -> dict[str, str]:
    """``--field key=value`` pairs as the action's fields; ``key=@path`` reads a file (the
    command line's own read: the cub never sees a path)."""
    fields: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"--field {pair!r}: write it as key=value")
        if value.startswith("@"):
            path = Path(value[1:]).expanduser()
            try:
                value = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ValueError(f"--field {key}: cannot read {path} ({exc.__class__.__name__})"
                                 ) from None
            if len(value.encode()) > FIELD_FILE_MAX:
                raise ValueError(f"--field {key}: {path} is over {FIELD_FILE_MAX:,} bytes")
        fields[key.strip()] = value
    return fields


def c_act(rt, args, ask, out) -> int:
    """An action through the running Kranto, with the command line's door token: the same
    route, door check and grants as the page's form (``doors`` must list ``cli``)."""
    import httpx

    from ...launcher import port_of
    from ...tokens import Store, tokens_dir
    fields = fields_of(args.field)
    action = args.action.split(".", 1)[1] if args.action.startswith(f"{args.id}.") \
        else args.action
    token = Store(tokens_dir()).value("cli")
    url = f"http://127.0.0.1:{port_of(rt.cfg)}/api/f/{args.id}/act/{action}"
    try:
        r = httpx.post(url, json={"fields": fields}, timeout=120,
                       headers={"Authorization": f"Bearer {token}"} if token else {})
    except httpx.HTTPError:
        raise install.InstallError("Kranto is not running here: kranto up, then try again",
                                   409) from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 400 or body.get("ok") is False:
        raise install.InstallError(body.get("error") or body.get("say")
                                   or f"Kranto answered {r.status_code}",
                                   r.status_code if r.status_code in (403, 404, 409) else 400)
    _say(out, args, body, body.get("say") or "done")
    return 0


def c_check(rt, args, ask, out) -> int:
    from .. import registry as core_registry
    path = Path(args.path).expanduser()
    if not path.is_dir():
        raise install.InstallError(f"{path} is not a folder", 404)
    paths = inspect.walk(path)
    if "cub.yaml" not in paths:
        raise install.InstallError("no cub.yaml at the top of the folder")
    raw = core_registry.load_cub_yaml((path / "cub.yaml").read_text(encoding="utf-8"))
    m = core_registry.validate_cub(json.loads(json.dumps(raw)), files=set(paths))
    if m.get("requirements"):
        from ..manifest import check_requirements
        check_requirements((path / m["requirements"]).read_text(encoding="utf-8"))
    from ..manifest import grants_of
    inv = inspect.inventory(path, paths)
    words = inspect.words(m, grants_of(m), trust="owner",
                          cap_usd=(m.get("model") or {}).get("monthly_usd"))
    record = {"ok": True, "id": m["id"], "version": m["version"], "words": words,
              "inventory": inv}
    if args.json:
        print(json.dumps(record, indent=2, default=str), file=out)
        return 0
    print(f"{m['id']} {m['version']}: the manifest is valid ({inv['files']} files, "
          f"{inv['bytes']:,} bytes, licence {inv['licence']})", file=out)
    print(_words(words), file=out)
    for f in inv["findings"]:
        print(f"  ! {f['text']}", file=out)
    return 0


def c_stopfile(rt, args, ask, out) -> int:
    path = tickets.stop_file()
    if args.set:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    elif args.clear:
        path.unlink(missing_ok=True)
    state = path.exists()
    words = "exists: every cub is stopped and every approval is practice" if state \
        else "does not exist"
    _say(out, args, {"path": str(path), "exists": state}, f"{path} {words}")
    return 0


def c_jobs(rt, args, ask, out) -> int:
    rows = install.jobs(rt.store, rt.cfg, limit=50)
    if args.json:
        print(json.dumps(rows, indent=2, default=str), file=out)
        return 0
    for j in rows:
        target = (j.get("cub") or {}).get("id") or j.get("target") or ""
        print(f"{j['id']}  {j['kind']:<6} {j['state']:<17} {target}"
              f"{'  ' + j['error'] if j.get('error') else ''}", file=out)
    return 0


def c_eval(rt, args, ask, out) -> int:
    """The cub's own tests (its ``tests/``) and the standard fixtures, through ``FakeHost``, in
    a child process on a copy of its tree. That runs the cub's code on this machine outside its
    sandbox, so only for the owner's own cubs (installed from a folder)."""
    import importlib.util
    import os
    import shutil
    import subprocess
    import tempfile

    from . import registry
    row = registry.latest(rt.store, args.id)
    if row is None or row["state"] == "removed":
        raise install.InstallError(f"no cub {args.id} is installed", 404)
    if row["trust"] != "owner":
        raise install.InstallError("kranto cub eval runs a cub's code outside its sandbox: only "
                                   "for your own cubs (installed from a folder); test a "
                                   f"{row['trust']} cub's folder with kranto cub check", 403)
    src = files.cub_dir(rt.cfg, args.id) / "src"
    report = {"tests": None, "standard": None}
    with tempfile.TemporaryDirectory(prefix="kranto-cub-eval-") as tmp:
        tree = Path(tmp) / args.id
        shutil.copytree(src, tree, ignore=shutil.ignore_patterns("__pycache__"))
        files.make_writable(tree)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp,
               "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        runs = []
        if (tree / "tests").is_dir() and importlib.util.find_spec("pytest") is None:
            report["tests"] = {"ok": False, "last": "not run: pytest is not installed with this "
                                                    "Kranto (Kranto ships it; for afk alone: pip "
                                                    "install pytest)"}
        elif (tree / "tests").is_dir():
            runs.append(("tests", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                   str(tree / "tests")]))
        runs.append(("standard", [sys.executable, "-m", "bears_cub.standard", str(tree)]))
        for name, argv in runs:
            try:
                p = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, text=True,
                                   timeout=300)
            except subprocess.TimeoutExpired:
                report[name] = {"ok": False, "last": "took longer than 300 s"}
                continue
            lines = (p.stdout or p.stderr).strip().splitlines()
            report[name] = {"ok": p.returncode == 0, "last": lines[-1] if lines else ""}
    if args.json:
        print(json.dumps(report, indent=2), file=out)
    else:
        for name, r in report.items():
            if r is not None:
                print(f"{name:<9} {'ok' if r['ok'] else 'FAILED'}: {r['last']}", file=out)
            else:
                print(f"{name:<9} none (no tests/ folder)", file=out)
    return 0 if all(r is None or r["ok"] for r in report.values()) else ERROR


TEMPLATE_URL = "https://github.com/octo-owner/bearcubs/tree/main/template"


def c_new(rt, args, ask, out) -> int:
    print("Kranto builds a cub from a sentence in 0.6; until then copy the template folder "
          f"({TEMPLATE_URL}), edit it, and kranto cub check it", file=out)
    return REFUSED


COMMANDS = {"add": c_add, "list": c_list, "inspect": c_inspect, "enable": c_enable,
            "disable": c_disable, "stop": c_stop, "resume": c_resume, "dry": c_dry,
            "live": c_live, "update": c_update, "remove": c_remove, "log": c_log, "run": c_run,
            "act": c_act,
            "check": c_check, "stopfile": c_stopfile, "jobs": c_jobs, "new": c_new,
            "eval": c_eval, "source": c_source}
