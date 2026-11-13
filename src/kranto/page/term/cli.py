"""``kranto term …``: Open in Claude Code's sessions from your own terminal (the
owner's D3).

    kranto term list                 the sessions, newest first
    kranto term open <tid>           continue one here, with exactly the page's limits
    kranto term end <tid>            end it for good (its copy goes, unless a proposal uses it)

``open`` builds the command with the page's own function (``Term.spec`` and ``launch.argv``:
a test asserts they are equal), starts it on a terminal of its own and relays your keys to it,
so the sandbox never holds your real terminal. Its token comes from your environment or your
own ``~/.config/kranto/claude.env`` (the file Kranto's unit reads), handed over through a pipe as
in the page. Kranto's tools in it reach the running service; with Kranto stopped they say so.
A session open in the page is not opened here too: End it there, or use Continue outside."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..box import handoff
from . import launch


def _term(loop_home=None):
    from ..ui import api
    app = api.App(Path(os.environ.get("TMPDIR") or "/tmp"), loop_home=loop_home) \
        if loop_home else api.default_app()
    app.term.serves = False                      # the running Kranto serves the sockets
    return app.term


def env_files(home: Path, unit: str | None = None) -> list[Path]:
    """The files Kranto's unit loads (``EnvironmentFile=`` in its drop-ins), then
    ``~/.config/kranto/claude.env``: where the unit's token is."""
    unit = unit or os.environ.get("KRANTO_UNIT") or "kranto.service"
    out = []
    d = home / ".config" / "systemd" / "user" / f"{unit}.d"
    for conf in sorted(d.glob("*.conf")) if d.is_dir() else []:
        try:
            lines = conf.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            k, _, v = ln.strip().partition("=")
            if k.strip() == "EnvironmentFile" and v.strip():
                out.append(Path(v.strip().lstrip("-").replace("%h", str(home))).expanduser())
    out.append(home / ".config" / "kranto" / "claude.env")
    return list(dict.fromkeys(out))


def token_env(environ=None, home: Path | None = None) -> dict:
    """The token variables: your environment's, else those of the files Kranto's unit loads
    (yours: the token is used, never copied)."""
    environ = dict(os.environ if environ is None else environ)
    if launch.token_source(environ):
        return environ
    for f in env_files(Path(home or Path.home())):
        try:
            for ln in f.read_text().splitlines():
                k, _, v = ln.strip().partition("=")
                if k.strip() in launch.TOKEN_ENV and v.strip():
                    environ[k.strip()] = v.strip().strip("'\"")
        except OSError:
            continue
        if launch.token_source(environ):
            break
    return environ


def started(environ: dict, home: Path | None = None) -> set:
    """The names that are the owner's, not Kranto's ``.env``'s: this process's start and the
    files Kranto's unit loads (``handoff.credential``)."""
    names = set(handoff.started_names() or ())
    for f in env_files(Path(home or Path.home())):
        try:
            names |= {ln.strip().partition("=")[0].strip() for ln in f.read_text().splitlines()
                      if "=" in ln}
        except OSError:
            continue
    return names & set(environ)


def command(term, tid: str, environ: dict, fd: int, proxy_dir=None, cred=None
            ) -> tuple[list, dict]:
    """The argv and environment ``kranto term open`` runs: the page's own."""
    rec = term.store.get(tid)
    cred = cred or launch.login(term.cfg(), environ, set(environ))[0]
    spec = term.prepare(rec, serve=False, cred=cred)   # Kranto serves the session's socket
    return launch.argv(spec, proxy_dir), launch.env(spec, cred.var, fd, environ)


def cmd_list(term) -> int:
    rows = term.list()["sessions"]
    if not rows:
        print("no sessions")
    for r in rows:
        s = r.get("subject") or {}
        print(f"{r['tid']}  {r['words']:<26} {s.get('kind')}:{s.get('id')}  {r.get('title') or ''}"
              f"  ${r.get('usd') or 0:.2f}")
    return 0


def cmd_open(term, tid: str) -> int:
    from .. import proc
    rec = term.store.get(tid) if len(tid) == 8 else None
    if rec is None or rec.get("removed"):
        print(f"kranto term: no session {tid} (kranto term list)", file=sys.stderr)
        return 2
    run = rec.get("runner") or {}
    if rec.get("state") == "running" and run and proc.running(run.get("pid"), run.get("start")):
        print(f"kranto term: {tid} is open in the page; End it there or use Continue outside",
              file=sys.stderr)
        return 2
    environ = token_env()
    cred, held = launch.login(term.cfg(), environ, started(environ))
    if cred is None:
        from .service import NO_TOKEN
        print(f"kranto term: {launch.WATCHERS_KEY if held else NO_TOKEN}", file=sys.stderr)
        return 2
    proxy = term._proxy(tid) if term.sandboxed() else None
    r, w = os.pipe()
    os.write(w, cred.value.encode())
    os.close(w)
    try:
        argv, env = command(term, tid, environ, r, proxy.dir if proxy else None, cred)
        term.store.update(tid, state="running", reason=None, runner=proc.me())
        code = relay(argv, env, Path(rec["cwd"]), (r,))
    finally:
        os.close(r)
        if proxy is not None:
            proxy.__exit__(None, None, None)
        term.store.update(tid, state="ended", reason="exit", runner=None)
    return code or 0


def relay(argv: list, env: dict, cwd: Path, pass_fds) -> int:
    """Run ``argv`` on a terminal of its own, relaying this terminal's keys, output and size."""
    import select
    import shutil
    import signal
    import termios
    import tty

    from .pty import Pty
    size = shutil.get_terminal_size((100, 30))
    out = sys.stdout.buffer

    def sink(data):
        if data is not None:
            out.write(data)
            out.flush()
        return True
    p = Pty(argv, env=env, cwd=cwd, pass_fds=pass_fds, cols=size.columns, rows=size.lines)
    p.attach(sink)
    p.start()
    stdin = sys.stdin.fileno()
    saved = termios.tcgetattr(stdin) if os.isatty(stdin) else None
    old = signal.signal(signal.SIGWINCH, lambda *_: p.resize(*shutil.get_terminal_size()))
    try:
        if saved:
            tty.setraw(stdin)
        while p.alive:
            ready, _, _ = select.select([stdin], [], [], 0.2)
            if ready:
                data = os.read(stdin, 4096)
                if not data:
                    break
                p.write(data)
    finally:
        if saved:
            termios.tcsetattr(stdin, termios.TCSADRAIN, saved)
        signal.signal(signal.SIGWINCH, old)
    return p.wait(10) or 0


def main(argv=None, loop_home=None) -> int:
    ap = argparse.ArgumentParser(prog="kranto term", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the sessions, newest first")
    o = sub.add_parser("open", help="continue a session here, with the page's limits")
    o.add_argument("tid")
    e = sub.add_parser("end", help="end a session for good (its copy goes unless a proposal "
                                   "uses it)")
    e.add_argument("tid")
    a = ap.parse_args(argv)
    term = _term(loop_home)
    if a.cmd == "list":
        return cmd_list(term)
    if a.cmd == "open":
        return cmd_open(term, a.tid)
    return cmd_end(term, a.tid)


def cmd_end(term, tid: str, url: str | None = None) -> int:
    """End through the running Kranto (it owns the session's process and socket), as the
    command line's own token; with Kranto stopped, here."""
    from ..mcp import tools as T
    from ..tokens import Store
    try:
        c = T.http_client(url, token=Store().value("cli"))
        status, body = c.post("/api/term/end", {"tid": tid})
    except Exception:                            # noqa: BLE001 - Kranto is not running
        status, body = None, None
    if status is None:
        from .service import TermError
        try:
            term.end(tid)
        except TermError as err:
            print(f"kranto term: {err}", file=sys.stderr)
            return 2
    elif status >= 400:
        print(f"kranto term: {(body or {}).get('error') if isinstance(body, dict) else body}",
              file=sys.stderr)
        return 2
    print(f"ended {tid}")
    return 0
