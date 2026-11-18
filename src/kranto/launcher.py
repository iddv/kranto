"""The ``kranto`` command: one app, one runtime (PLAN.md sections 1.1 to 1.7).

``kranto`` is what the ``kranto`` distribution (``packages/kranto``) installs. A kranto home
(``--home``, else ``$KRANTO_HOME``, else the one ``kranto up`` or ``kranto adopt`` recorded in
``~/.config/kranto/home``, else ``~/.kranto``) is a workspace whose config is
``kranto.yaml``
with the ``brb`` section on, plus the loop's home and the task folder:

    ~/.kranto/
      kranto.yaml    the server's config plus brb: {enabled, loop_home, root}
      .env          the model key (written by onboarding; never read by this launcher)
      data/         kranto.db, secrets/, locks
      loop/         loop.db, loop.yaml (the loop's settings store), inbox/, term/, PAUSE
      tasks/        one folder per build

Commands:

- ``up``: make the home if there is none, install and start ``kranto.service`` (a systemd
  user unit) where systemd is usable, else serve in the foreground; open the browser;
- ``serve``: ``kranto serve`` with the scheduler on (what the unit runs);
``--no-scheduler``
  stays for cron users;
- ``down``, ``status``, ``logs``: the unit, a one-screen status, its journal;
- ``doctor``: ``kranto doctor`` plus the prerequisites nobody can install for you (the
  Claude Code CLI and its login, ``gh`` and its login, ``bwrap``), the unit's PATH, whether
  the console is ready, pending migrations;
- ``adopt``: switch an existing installation (``~/kranto-kb``, ``~/kranto-loop``,
  ``~/tasks``) to Kranto in place: back up, write the ``brb`` section, migrate, mark setup
  done, and with a yes replace ``kranto.service`` and its drop-in with ``kranto.service``.
  Nothing moves.

``afk`` and ``brb`` keep working on their own.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pwd
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import config as config_mod
from . import legacy, memory, paths, product
from .config import KRANTO_CONFIG_FILENAME, KRANTO_HOME_ENV, ConfigError
from .update.apply import tool_env_of

DEFAULT_PORT = 8765
DEFAULT_UNIT = paths.DEFAULT_UNIT
# $KRANTO_UNIT names another unit (a second, scratch instance beside the real one: the update's
# end-to-end test uses kranto-test.service); its home pointer is then ~/.config/kranto/home.<name>.
UNIT = paths.unit_name()
# Passed into the unit when set, so the service (and an update it starts) uses the same tool
# environment and command folder as Kranto that installed it.
UNIT_PASS_ENV = ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR")
OLD_UNIT = legacy.ADOPT_UNIT
OLD_DROPIN = "calibration.conf"
SETUP_DONE_KEY = "setup.done"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
OK, WARN, FAIL = "ok", "warn", "FAIL"


class KrantoError(Exception):
    """Something the person can fix; printed without a traceback."""


# -- the host: commands, PATH and systemd, injectable for tests -------------------------------


@dataclass
class Host:
    """What ``kranto`` asks of the machine. Tests pass fakes; nothing here is a model or
    the network, except ``http_get``, which only ever asks 127.0.0.1."""

    run: Callable[..., subprocess.CompletedProcess] = field(default=None)  # type: ignore[assignment]
    which: Callable[..., str | None] = shutil.which
    home: Path = field(default_factory=Path.home)
    login_home: Path | None = None
    http_get: Callable[[str, float], tuple[int, bytes]] | None = None
    stdin_tty: bool | None = None
    tty: Callable[..., int] | None = None              # a command on the person's terminal

    def __post_init__(self) -> None:
        if self.run is None:
            self.run = _run
        if self.tty is None:
            self.tty = _tty
        if self.login_home is None:
            try:
                self.login_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
            except KeyError:
                self.login_home = self.home
        if self.http_get is None:
            self.http_get = _http_get
        if self.stdin_tty is None:
            self.stdin_tty = sys.stdin.isatty()

    def sh(self, *cmd: str, timeout: float = 30) -> subprocess.CompletedProcess:
        try:
            return self.run(list(cmd), timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(list(cmd), 127, "", str(exc))

    @property
    def unit_dir(self) -> Path:
        return self.home / ".config" / "systemd" / "user"

    def systemd(self) -> str | None:
        """None when ``systemctl --user`` can manage this HOME's units, else why not."""
        if Path(self.home).resolve() != Path(self.login_home).resolve():
            return (f"HOME is {self.home}, not the login home {self.login_home}: the user "
                    "manager would not see a unit written there")
        if not self.which("systemctl"):
            return "systemctl is not on PATH"
        r = self.sh("systemctl", "--user", "show-environment", timeout=10)
        if r.returncode != 0:
            return "no systemd user manager here (" + (r.stderr or r.stdout).strip()[:120] + ")"
        return None


def _run(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _tty(cmd: list[str], timeout: float = 900) -> int:
    """``cmd`` on the person's own terminal (``claude setup-token``: it opens a browser and
    prints what it prints there, never to Kranto)."""
    try:
        return subprocess.run(cmd, timeout=timeout, check=False).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 127


def _http_get(url: str, timeout: float) -> tuple[int, bytes]:
    import httpx

    r = httpx.get(url, timeout=timeout, follow_redirects=False)
    return r.status_code, r.content


# -- the home and its files ---------------------------------------------------------------------


def pointer_path(user_home: Path) -> Path:
    """Where ``kranto up`` and ``kranto adopt`` record the home they set up, so every ``kranto``
    command finds it without ``--home`` (an adopted install lives in ~/kranto-kb). Another
    unit (``$KRANTO_UNIT``) keeps its own pointer, so it never moves the real one."""
    return paths.pointer_path(user_home, UNIT)


def host_unit(host: Host) -> str:
    """The unit this install runs as on ``host``: ``UNIT`` when ``$KRANTO_UNIT`` names another;
    else an install made before the rename keeps its old unit (``legacy.UNIT``) when only that
    one is installed here, so no ``kranto.service`` is ever made beside it."""
    if UNIT != DEFAULT_UNIT:
        return UNIT
    if not (host.unit_dir / DEFAULT_UNIT).exists() and (host.unit_dir / legacy.UNIT).exists():
        return legacy.UNIT
    return DEFAULT_UNIT


def private_config_dir(user_home: Path) -> Path:
    """``~/.config/kranto``, made (or tightened) to 0700: it holds the tokens, the GitHub App's
    key and the GitHub connection, and is documented as never printed."""
    folder = pointer_path(user_home).parent
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        os.chmod(folder, 0o700)
    return folder


def remember_home(home: Path, user_home: Path) -> Path:
    path = pointer_path(user_home)
    private_config_dir(user_home)
    tmp = path.with_name(f".home.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{Path(home).resolve()}\n")
    os.replace(tmp, path)
    return path


def recorded_home(user_home: Path, unit_dir: Path | None = None) -> Path | None:
    """The home ``kranto up`` or ``kranto adopt`` recorded, else the installed unit's
    ``KRANTO_HOME``; None when there is neither."""
    return paths.recorded_home(user_home, unit_dir, UNIT)


def kranto_home(explicit: str | None = None, host: Host | None = None) -> Path:
    """``--home``, else ``$KRANTO_HOME``, else the home recorded by ``kranto up`` or ``kranto
    adopt`` (or the installed unit's), else ``~/.kranto``."""
    return paths.kranto_home(explicit, user_home=host.home if host is not None else None,
                            units=host.unit_dir if host is not None else None,
                            unit=host_unit(host) if host is not None else UNIT)


def tilde(path: Path, home: Path) -> str:
    """``path`` as ``~/...`` when it is under ``home`` (portable in YAML), else absolute."""
    try:
        return "~/" + str(Path(path).resolve().relative_to(Path(home).resolve()))
    except ValueError:
        return str(Path(path).resolve())


def _section_span(lines: list[str], name: str) -> tuple[int, int] | None:
    """Line range of a top-level YAML section ``name:`` (to the next top-level key)."""
    start = next((i for i, line in enumerate(lines) if re.match(rf"{re.escape(name)}:\s*(#.*)?$",
                                                              line)), None)
    if start is None:
        return None
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in (" ", "\t", "#")):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1  # blank lines before the next section stay with it
    return start, end


def brb_block(loop_home: str, root: str | None = None, harness: str = "claude-code") -> str:
    """The ``brb:`` section: ``root`` only for an adopted install (its earlier builds' task
    folder, which ``kranto paths`` lists); a new home has none."""
    return ("brb:\n"
            "  # the page: Kranto's web UI with its console, written by kranto up or kranto\n"
            "  # adopt. Served only when the server is bound to loopback (enabled: false serves\n"
            "  # the server alone, with no console). loop_home is the page's own folder: its\n"
            "  # settings file loop.yaml, its database and its console sessions."
            + (" root is the\n  # task folder of an earlier release's builds.\n" if root else "\n")
            + "  enabled: true\n"
            f"  loop_home: {json.dumps(loop_home)}\n"
            + (f"  root: {json.dumps(root)}\n" if root else "")
            + (f"  harness: {harness}\n" if harness != "claude-code" else ""))


def set_section(text: str, name: str, block: str) -> str:
    """Replace the top-level section ``name`` with ``block`` (or append it), keeping every
    other line, comment included."""
    lines = text.splitlines()
    span = _section_span(lines, name)
    new = block.rstrip("\n").splitlines()
    if span is None:
        out = lines + ([""] if lines and lines[-1].strip() else []) + new
    else:
        out = lines[:span[0]] + new + lines[span[1]:]
    return "\n".join(out) + "\n"


def set_in_section(text: str, name: str, key: str, value: str) -> str:
    """Set ``key: value`` inside the top-level section ``name`` (two-space indent)."""
    lines = text.splitlines()
    span = _section_span(lines, name)
    if span is None:
        return set_section(text, name, f"{name}:\n  {key}: {value}\n")
    for i in range(span[0] + 1, span[1]):
        if re.match(rf"\s+{re.escape(key)}:", lines[i]):
            lines[i] = f"  {key}: {value}"
            break
    else:
        lines.insert(span[1], f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def home_config_text(home: Path, port: int, user_home: Path) -> str:
    """kranto.yaml for a new home: the server's default config with the brb section on."""
    text = config_mod.DEFAULT_CONFIG_YAML.replace(
        "# The server workspace configuration.",
        "# Kranto configuration: the server's settings, then the brb section (the page and\n"
        "# its console). The page keeps its own settings in loop/loop.yaml.", 1)
    text = set_section(text, "brb", brb_block(tilde(home / "loop", user_home)))
    return set_in_section(text, "notify", "base_url", f"http://127.0.0.1:{port}")


def loop_seed_text(home: Path, port: int, user_home: Path) -> str:
    """The page's settings for a new home: where it reaches this server (its API, so the page
    never opens the server's database). The builds' keys an earlier release wrote here
    (``tasks_dir``, ``concurrency``, ``intake``, ``feed.ui_url``) are left out. The console's
    lines (``console.NEW_HOME_YAML``): a new home's does not open by itself and asks first."""
    try:
        from kranto.page.host_api import console_new_home_yaml
    except ImportError:          # a page without these lines: the console keeps its defaults
        console_new_home_yaml = ""
    return ("# The page's own settings (any subset of its DEFAULTS), written once by kranto up:\n"
            "# kranto.url is where the page reaches this server. kranto setup writes some keys\n"
            "# here; the rest are edited by hand (no Settings page lists this file).\n"
            "kranto:\n"
            f"  url: {json.dumps(f'http://127.0.0.1:{port}')}\n"
            + console_new_home_yaml)


def make_home(home: Path, port: int, user_home: Path) -> list[str]:
    """Create what is missing of a kranto home. Returns what was written. Refuses a folder
    that holds a different config."""
    written = []
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    if config_mod.config_path(home) is None:
        (home / KRANTO_CONFIG_FILENAME).write_text(home_config_text(home, port, user_home))
        written.append(str(home / KRANTO_CONFIG_FILENAME))
    # The loop's home is seeded inside the home only when its config puts it there: a home
    # whose brb section points elsewhere (an adopted ~/kranto-kb with ~/kranto-loop) gets no
    # decoy loop/ (review D-5). The task folder was the builds'; they left, and nothing reads
    # it, so no tasks/ is made (the config keeps its key, for a version from before).
    lay = paths.Layout(home)
    loop_at = lay.loop
    try:
        cfg = config_mod.load(home, dotenv=False)
        if cfg.brb.loop_home:
            loop_at = Path(cfg.brb.loop_home).expanduser()
    except Exception:  # noqa: BLE001 - an unreadable config: seed as before
        pass
    subs = [lay.data] + ([lay.loop] if loop_at.resolve() == lay.loop.resolve() else [])
    for d in subs:
        if not d.is_dir():
            d.mkdir(parents=True)
            written.append(str(d) + "/")
    seed = paths.LoopLayout(lay.loop).settings
    if lay.loop in subs and not seed.exists():
        seed.write_text(loop_seed_text(home, port, user_home))
        written.append(str(seed))
    return written


def move_port(home: Path, old: int, new: int, user_home: Path) -> list[str]:
    """Write port ``new`` into the home's ``notify.base_url`` (and the loop settings' own
    addresses of this server, when that file is there). Returns what was written."""
    written = []
    path = config_mod.config_path(home)
    if path is not None:
        path.write_text(set_in_section(path.read_text(), "notify", "base_url",
                                       f"http://127.0.0.1:{new}"))
        written.append(f"{path} (port {new})")
    seed = paths.LoopLayout(paths.Layout(home).loop).settings
    if seed.exists():
        text = seed.read_text()
        moved = text.replace(f"http://127.0.0.1:{old}", f"http://127.0.0.1:{new}")
        if moved != text:
            seed.write_text(moved)
            written.append(f"{seed} (port {new})")
    return written


def port_of(cfg: config_mod.Config) -> int:
    """The port this home is served on: the one in ``notify.base_url`` (kranto up writes it)."""
    m = re.match(r"https?://[^/:]+:(\d+)", cfg.notify.base_url)
    return int(m.group(1)) if m else DEFAULT_PORT


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def serves_this_home(host: Host, port: int, home: Path) -> bool | None:
    """Whether what answers on 127.0.0.1:``port`` is Kranto serving ``home``: None when nothing
    answers as Kranto there, else True only when every run the server lists is in this home's
    library (read-only) and, for a server with no runs yet, the two hold as many observations.
    /api/status names no home, so the runs it reads are how it is told apart."""
    get = host.http_get or _http_get
    try:
        code, body = get(f"http://127.0.0.1:{port}/api/status", 3)
        server = json.loads(body) if code == 200 else None
    except Exception:  # noqa: BLE001 - not Kranto, or not answering
        server = None
    if not isinstance(server, dict) or "version" not in server:
        return None
    try:
        cfg = config_mod.load(home, dotenv=False)
        con = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True, timeout=5)
        try:
            ours = {r[0] for r in con.execute("SELECT run_uuid FROM runs") if r[0]}
            count = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        finally:
            con.close()
    except (ConfigError, OSError, sqlite3.Error):
        return False
    theirs = {r.get("run_uuid") for r in server.get("runs") or [] if isinstance(r, dict)}
    theirs.discard(None)
    if theirs:
        return theirs <= ours
    return server.get("observations") == count


def pending_migrations(db: Path) -> list[int]:
    """Migrations this version knows that ``db`` has not applied; read-only (opening the
    store would apply them, and the handover asks for a backup first)."""
    from .store import Store

    known = Store.migration_numbers()
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT key FROM schema_meta WHERE key LIKE 'migration:%'")
        applied = {int(r[0].split(":", 1)[1]) for r in rows}
    except sqlite3.OperationalError:
        applied = set()
    finally:
        conn.close()
    return [n for n in known if n not in applied]


def backup_sqlite(src: Path, dest: Path) -> Path:
    """A consistent copy of a live SQLite database (the backup API, safe while it is being
    written). Never overwrites: a second backup the same day gets ``-2``, ``-3``..."""
    dest = _free_path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    os.chmod(dest, 0o600)
    return dest


def _free_path(path: Path) -> Path:
    n, out = 2, path
    while out.exists():
        out = path.with_name(f"{path.name}-{n}")
        n += 1
    return out


# -- the unit -------------------------------------------------------------------------------------


def unit_path_dirs(user_home: Path, exe: Path | None = None,
                   extra: Sequence[Path] = ()) -> list[str]:
    """The unit's PATH: ~/.local/bin, Kranto script's folder, ``extra`` (the configured
    Claude Code's folder), the system's, then Kranto's own gh folder when ``--fetch-gh`` filled
    it (last: a distribution's gh installed later wins)."""
    from .ghfetch import bin_dir

    dirs = ["%h/.local/bin", "/usr/local/bin", "/usr/bin", "/bin"]
    at = 1
    for p in ([exe] if exe is not None else []) + [Path(e) / "_" for e in extra]:
        d = _h(p.parent, user_home)
        if d not in dirs:
            dirs.insert(at, d)
            at += 1
    if (bin_dir(user_home) / "gh").is_file():
        dirs.append(_h(bin_dir(user_home), user_home))
    return dirs


def configured_claude(home: Path) -> str | None:
    """``build.claude_command`` in this home's loop.yaml (``kranto setup --claude PATH``, or
    found off PATH by the wizard); None: ``claude`` on PATH."""
    import yaml

    try:
        cfg = config_mod.load(home, dotenv=False)
        if not cfg.brb.enabled:
            return None
        data = yaml.safe_load(paths.LoopLayout(paths.loop_home(cfg.brb.loop_home)).settings
                              .read_text()) or {}
    except (OSError, ConfigError, yaml.YAMLError):
        return None
    got =(data.get("build") or {}).get("claude_command") if isinstance(data, dict) else None
    return str(got) if got else None


def unit_extra_dirs(home: Path, user_home: Path) -> list[Path]:
    """The configured Claude Code's folder, for the unit's PATH (an npm or nvm install also
    needs its node there)."""
    claude = configured_claude(home)
    return [Path(claude).parent] if claude else []


def _h(path: Path, user_home: Path) -> str:
    """A path in unit syntax: ``%h/...`` under the home, else absolute."""
    try:
        rel = Path(path).relative_to(user_home)
    except ValueError:
        return str(path)
    return "%h" if str(rel) == "." else f"%h/{rel}"


UNIT_DESCRIPTION = f"{product.NAME}: news in, ideas out, posts when you say"


def render_unit(home: Path, exe: Path, port: int, user_home: Path) -> str:
    """``kranto.service`` (PLAN.md section 1.2). ``KillMode=process``: stopping the unit ends
    the server, which ends its own children; detached builds keep running and the next start
    adopts them by pid. ``TimeoutStopSec``: the server stops within 10 s of SIGTERM and its
    watchdog exits at 12 s (``stopping.py``), so systemd's kill at 15 s is only the last
    resort. PATH carries ``~/.local/bin`` so the Claude Code CLI, ``gh`` and ``uv`` are found.
    ``MemoryHigh``/``MemoryMax``/``OOMPolicy``: ``memory.unit_lines`` (a drop-in overrides)."""
    from .memory import unit_lines
    from .stopping import UNIT_STOP_S

    port_arg = f" --port {port}" if port != DEFAULT_PORT else ""
    extra = "".join(f"Environment={k}={os.environ[k]}\n" for k in UNIT_PASS_ENV
                    if os.environ.get(k))
    if not legacy.is_default_unit(UNIT):
        extra += f"Environment=KRANTO_UNIT={UNIT}\n"
    return f"""\
[Unit]
Description={UNIT_DESCRIPTION}
After=network-online.target

[Service]
Type=simple
Environment=KRANTO_HOME={_h(home, user_home)}
Environment=PATH={':'.join(unit_path_dirs(user_home, exe, unit_extra_dirs(home, user_home)))}
{extra}ExecStart={_h(exe, user_home)} serve --host 127.0.0.1{port_arg}
Restart=on-failure
RestartSec=15
KillMode=process
TimeoutStopSec={UNIT_STOP_S}
{unit_lines()}
[Install]
WantedBy=default.target
"""


def unit_env(text: str, user_home: Path) -> dict[str, str]:
    """``Environment=`` values of a unit, ``%h`` expanded (``paths.unit_env``)."""
    return paths.unit_env(text, user_home)


def kranto_exe(host: Host) -> Path:
    """The installed ``kranto`` script: in ``$UV_TOOL_BIN_DIR`` when that is set (a tool
    installed elsewhere than ~/.local/bin), else on PATH, else the one running, else where
    ``uv tool install`` puts it."""
    bin_dir = os.environ.get("UV_TOOL_BIN_DIR")
    if bin_dir and (Path(bin_dir) / "kranto").exists():
        return Path(bin_dir) / "kranto"
    found = host.which("kranto")
    if found:
        return Path(found)
    argv0 = Path(sys.argv[0])
    if argv0.name == "kranto" and argv0.exists():
        return argv0.resolve()
    return host.home / ".local" / "bin" / "kranto"


# -- serve ----------------------------------------------------------------------------------------


def cmd_serve(args, host: Host) -> int:
    from . import cli

    home = kranto_home(args.home, host)
    if config_mod.config_path(home) is None:
        raise KrantoError(f"{home} is not a Kranto home yet: run 'kranto up' first")
    memory.enter_scope("kranto serve")
    cfg = config_mod.load(home, dotenv=False)
    from . import preview
    if preview.enabled(home):
        why = preview.refusal(home, Path(cfg.brb.loop_home) if cfg.brb.loop_home else None,
                              args.port or port_of(cfg), host.home)
        if why:
            raise KrantoError(why)
        preview.enter(home)
    if cfg.brb.loop_home:
        # The page's own commands, run by the builds UI, must see the same loop home
        os.environ.setdefault("KRANTO_LOOP_HOME", str(Path(cfg.brb.loop_home).expanduser()))
    ns = argparse.Namespace(
        workspace=str(home), host=args.host, port=args.port or port_of(cfg),
        allow_host=args.allow_host, no_scheduler=args.no_scheduler,
        banner="kranto", update_job=True)
    if getattr(args, "runtime_factory", None):
        ns.runtime_factory = args.runtime_factory
    return cli.cmd_serve(ns)


# -- up / down / logs -------------------------------------------------------------------------


def _wait_up(host: Host, port: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            status, _ = host.http_get(f"http://127.0.0.1:{port}/api/status", 3)
            if status == 200:
                return True
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(1)
    return False


def _can_open(no_browser: bool) -> bool:
    return not no_browser and bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                                   or sys.platform == "darwin")


def offer_signin(home: Path, host: Host, then: str, no_browser: bool) -> None:
    """Open, or print to a terminal, a one-time link that signs a browser in. Never into a log:
    with no terminal and no browser (the update's helper runs 'kranto up'), it says how to get
    one instead. Flushed: an agent reading 'kranto up' through a pipe sees it while Kranto
    serves, not at exit."""
    if not _can_open(no_browser) and not sys.stdout.isatty():
        print("Sign a browser in with 'kranto open': it prints a one-time link.", flush=True)
        return
    print("This link signs one browser in (once, within 10 minutes; 'kranto open' makes "
          "another):")
    _open_browser(signin_link(home, host, then), no_browser)
    sys.stdout.flush()


def _open_browser(url: str, no_browser: bool) -> None:
    if no_browser or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
                          or sys.platform == "darwin"):
        print(f"open {url}")
        return
    import webbrowser

    if not webbrowser.open(url):
        print(f"open {url}")


def keep_old_unit(path: Path) -> bool:
    """An install made before the rename keeps its unit file as it is: only the
    ``Description=`` line is rewritten to the new name; ``ExecStart``, every ``Environment``
    (``adopt_env`` reads the old variables) and the drop-ins stay byte for byte. True when it
    changed."""
    text = path.read_bytes()
    new = re.sub(rb"(?m)^Description=[^\r\n]*", b"Description=" + UNIT_DESCRIPTION.encode(),
                 text, count=1)
    if new != text:
        path.write_bytes(new)
    return new != text


_EXEC_PREFIXES = "-@:+!"      # systemd's ExecStart= prefixes before the command


def unit_command(path: Path, user_home: Path) -> str | None:
    """The command a unit file starts: its last ``ExecStart=`` (drop-ins included, an empty one
    resets it, as systemd reads them), ``%h`` expanded; None when there is no unit or none."""
    files = [path] + sorted((path.parent / f"{path.name}.d").glob("*.conf"))
    command = None
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == "ExecStart":
                words = value.split()
                command = words[0].lstrip(_EXEC_PREFIXES).replace("%h", str(user_home)) \
                    if words else None
    return command


def unit_of_another_tool(path: Path, exe: Path, user_home: Path) -> str | None:
    """The command of the unit at ``path`` when ``up`` with this tool (``exe``) did not write
    it: it starts something other than this tool's own command folder's ``kranto`` (or the old
    command beside it, which the same tool carries). None when it is this tool's, or there is
    no unit. A checkout or a scratch tool must not take over the installed tool's unit."""
    command = unit_command(path, user_home)
    if command is None:
        return None
    ran = Path(command).expanduser()
    if ran.name in (product.COMMAND, legacy.COMMAND):
        try:
            if ran.parent.resolve() == Path(exe).parent.resolve():
                return None
        except OSError:
            pass
    return command


def install_unit(host: Host, text: str) -> tuple[Path, bool]:
    """Write ``kranto.service``; True when it changed. On an install made before the rename,
    its old unit (the old name, or any unit whose text the old version wrote:
    ``legacy.is_old_unit``) is kept (``keep_old_unit``) and no new one is written beside it."""
    host.unit_dir.mkdir(parents=True, exist_ok=True)
    path = host.unit_dir / host_unit(host)
    if path.exists() and (path.name == legacy.UNIT
                          or legacy.is_old_unit(path.read_text(errors="replace"))):
        return path, keep_old_unit(path)
    old = path.read_text() if path.exists() else None
    if old != text:
        path.write_text(text)
    return path, old != text


def cmd_up(args, host: Host) -> int:
    home = kranto_home(args.home, host)
    why_not = "--foreground" if args.foreground else host.systemd()
    unit_path, exe, other = host.unit_dir / host_unit(host), kranto_exe(host), None
    if why_not is None:
        # before anything is written: a unit another tool's command runs (the installed one,
        # while this is a checkout or a scratch tool) is not this up's to rewrite or restart
        other = unit_of_another_tool(unit_path, exe, host.home)
        if other and not getattr(args, "adopt", False):
            raise KrantoError(
                f"{unit_path.name} runs {other}, not this {product.COMMAND} ({exe}): it is left "
                f"as it is and not restarted. Run that command's 'up' instead, or "
                f"'{product.COMMAND} up --adopt' to make this one the unit's command.")
    existing = config_mod.config_path(home) is not None
    port = args.port or DEFAULT_PORT
    written = make_home(home, port, host.home)
    remember_home(home, host.home)  # so 'kranto status' and the rest find it without --home
    cfg = config_mod.load(home, dotenv=False)
    if existing and not args.port:
        port = port_of(cfg)
    elif existing and port != port_of(cfg):
        # a later 'up --port N' moves the home to N: 'kranto open', doctor and the links
        # Kranto sends read the port from notify.base_url, so it is written there too
        written += move_port(home, port_of(cfg), port, host.home)
        cfg = config_mod.load(home, dotenv=False)
    print(f"kranto home: {home}" + (" (new)" if not existing else ""))
    for w in written:
        print(f"  wrote {w}")
    if not cfg.brb.enabled:
        print("  note: brb.enabled is false in the config: no console "
              "(kranto adopt turns it on)")
    made = token_store(host).ensure_doors()
    if made:
        print(f"  made the {', '.join(made)} token(s) in {token_store(host).root}")
    then = "/#/welcome" if not existing else "/"
    if why_not is None:
        text = render_unit(home, exe, port, host.home)
        if other:          # --adopt: this tool's unit replaces the one another tool wrote
            changed = not unit_path.exists() or unit_path.read_text(errors="replace") != text
            unit_path.parent.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(text)
            unit = unit_path
            print(f"  adopted {unit_path.name}: it ran {other}")
        else:
            unit, changed = install_unit(host, text)
        name = unit.name
        active = host.sh("systemctl", "--user", "is-active", name).stdout.strip() == "active"
        if not active and port_in_use(port):
            raise KrantoError(f"port {port} is already in use (kranto.service? then run "
                             "'kranto adopt'); or choose another with --port")
        print(f"  {'wrote' if changed else 'kept'} {unit}")
        for cmd in (["daemon-reload"], ["enable", "--now", name]) + \
                ((["restart", name],) if changed and active else ()):
            r = host.sh("systemctl", "--user", *cmd, timeout=120)
            if r.returncode != 0:
                raise KrantoError(f"systemctl --user {' '.join(cmd)} failed: "
                                 f"{(r.stderr or r.stdout).strip()}")
        linger = host.sh("loginctl", "enable-linger", pwd.getpwuid(os.getuid()).pw_name)
        if linger.returncode != 0:
            print("  note: loginctl enable-linger failed; Kranto stops when you log out")
        if not _wait_up(host, port, 90):
            print(f"{name} started but http://127.0.0.1:{port}/ is not answering yet; "
                  "see 'kranto logs'")
            return 1
        print(f"Kranto is running: http://127.0.0.1:{port}/  ('kranto status', 'kranto logs')")
        offer_signin(home, host, then, args.no_browser)
        return 0
    print(f"  not using systemd: {why_not}; serving in the foreground (Ctrl-C stops it)",
          flush=True)
    memory.enter_scope("kranto up")
    if port_in_use(port):
        raise KrantoError(f"port {port} is already in use; choose another with --port")

    def announce():
        if _wait_up(host, port, 120):
            offer_signin(home, host, then, args.no_browser)
    threading.Thread(target=announce, daemon=True).start()
    serve = argparse.Namespace(home=str(home), host="127.0.0.1", port=port, allow_host=None,
                               no_scheduler=False)
    return cmd_serve(serve, host)


def cmd_down(args, host: Host) -> int:
    why_not = host.systemd()
    if why_not:
        print(f"Kranto is not managed by systemd here ({why_not}); stop 'kranto serve' with "
              "Ctrl-C")
        return 1
    unit = host_unit(host)
    r = host.sh("systemctl", "--user", "stop", unit, timeout=120)
    if r.returncode != 0:
        print((r.stderr or r.stdout).strip())
        return 1
    if getattr(args, "disable", False):
        r = host.sh("systemctl", "--user", "disable", unit, timeout=120)
        if r.returncode != 0:
            print((r.stderr or r.stdout).strip())
            return 1
        print("kranto stopped and will not start at boot ('kranto up' turns it back on)")
        return 0
    print("kranto stopped (running builds keep going; the next start adopts them). It starts "
          "again at boot: 'kranto down --disable' stops that")
    return 0


def install_paths(home: Path, host: Host) -> list[tuple[str, Path]]:
    """Every place a kranto install keeps something: what ``kranto paths``
    prints and ``kranto uninstall`` reads."""
    out = [("home", Path(home))]
    try:
        cfg = config_mod.load(home, dotenv=False) if config_mod.config_path(home) else None
    except ConfigError:
        cfg = None
    if cfg is not None and cfg.brb.enabled:
        loop = paths.loop_home(cfg.brb.loop_home)
        if not loop.is_relative_to(Path(home).resolve()):
            out.append(("build loop", loop))
        if cfg.brb.root:
            tasks = Path(cfg.brb.root).expanduser().resolve()
            if not tasks.is_relative_to(Path(home).resolve()):
                out.append(("builds", tasks))
    tool_dir = Path(os.environ.get("UV_TOOL_DIR") or host.home / ".local" / "share" / "uv" /
                    "tools")
    out += [("config", pointer_path(host.home).parent),
            ("service", host.unit_dir / host_unit(host)),
            ("program", tool_env_of(tool_dir)),
            ("commands", Path(os.environ.get("UV_TOOL_BIN_DIR") or host.home / ".local" / "bin")),
            ("cache", host.home / ".cache" / "kranto")]
    return out


def _size(path: Path) -> int:
    total = 0
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
        for root, _, files in os.walk(path):
            for f in files:
                with contextlib.suppress(OSError):
                    total += (Path(root) / f).lstat().st_size
    except OSError:
        return 0
    return total


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def cmd_paths(args, host: Host) -> int:
    """``kranto paths``: where this install keeps things, with sizes. ``kranto paths examples``:
    the reference cubs' folder alone, for ``kranto cub add``."""
    if getattr(args, "which", None) == "examples":
        from .cubs import examples_dir
        print(examples_dir())
        return 0
    if getattr(args, "which", None) == "plugin":
        from .assistant import PLUGIN_DIR
        print(PLUGIN_DIR)
        return 0
    home = kranto_home(args.home, host)
    for label, path in install_paths(home, host):
        if label == "commands":
            names = [n for n in ("kranto", "afk", "brb") if (path / n).exists()]
            print(f"{label:<11} {tilde(path, host.home)}/{{{','.join(names)}}}" if names else
                  f"{label:<11} {tilde(path, host.home)} (no Kranto commands)")
            continue
        there = path.exists()
        print(f"{label:<11} {tilde(path, host.home)}"
              + (f"  {_human(_size(path))}" if there else "  (none)"))
    return 0


def cmd_archive(args, host: Host) -> int:
    """``kranto archive [--out DIR] [--json]``: the record of the features that left Kranto
    (builds, projects, Invest, the trend radar, deep dives, the browser extension), written to
    ``<home>/archive/`` as one page and a JSON file each. Read-only on every database."""
    from . import archive

    home = kranto_home(args.home, host)
    try:
        cfg = config_mod.load(home, dotenv=False)
    except ConfigError as exc:
        print(f"kranto archive: {exc}", file=sys.stderr)
        return 2
    from .paths import LoopLayout, loop_home
    loop_db = LoopLayout(loop_home(cfg.brb.loop_home)).db
    done = archive.write(home, cfg.db_path, loop_db,
                         Path(args.out).expanduser() if args.out else None)
    if args.json:
        print(json.dumps(done.summary(), indent=1))
        return 0
    for name, counts in done.counts.items():
        rows = ", ".join(f"{t} {n}" for t, n in counts.items()) or "nothing"
        print(f"{name:<10} {rows}")
    for line in done.missing:
        print(f"note       {line}")
    print(f"\nWritten: {tilde(done.out / 'index.html', host.home)} (open it in a browser)")
    return 0


GITHUB_PAGES = ("Kranto's GitHub connection: revoke it at https://github.com/settings/applications",
                "Kranto's GitHub App, if you made one: delete it at "
                "https://github.com/settings/apps (the app's Advanced tab)")


def remove_data(home: Path, host: Host) -> list[str]:
    """Delete the home, a loop home or task folder outside it, ``~/.config/kranto`` and the
    cache. Refuses anything that is not a Kranto home, or is the user's home itself."""
    home = Path(home).resolve()
    if config_mod.config_path(home) is None:
        raise KrantoError(f"{home} is not a Kranto home (no kranto.yaml); nothing "
                         "was removed")
    if home in (Path("/"), Path(host.home).resolve(), Path(host.login_home).resolve()):
        raise KrantoError(f"{home} is your home directory itself; nothing was removed")
    removed = []
    for label, path in install_paths(home, host):
        if label in ("program", "commands", "service"):
            continue
        p = Path(path)
        if p.resolve() in (Path("/"), Path(host.home).resolve()):
            continue
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(str(p))
        elif p.exists():
            p.unlink()
            removed.append(str(p))
    return removed


def cmd_uninstall(args, host: Host) -> int:
    """Undo what ``kranto up`` did to the machine: stop and disable the service, remove its
    unit and drop-ins, optionally turn lingering off. ``--program`` also removes the program
    (``uv tool uninstall kranto``); ``--data`` also deletes the data, after the home's path is
    typed (or given as ``--confirm PATH``). Nothing on GitHub is deleted: the last lines say
    which two pages to visit."""
    home = kranto_home(args.home, host)
    if getattr(args, "data", False):
        typed = getattr(args, "confirm", None)
        if typed is None and host.stdin_tty:
            typed = input(f"This deletes {home} and everything listed by 'kranto paths' except "
                          "the program. Type the home's path to go ahead: ").strip()
        if not typed or Path(typed).expanduser().resolve() != Path(home).resolve():
            raise KrantoError("the path typed is not this home's; nothing was removed (--confirm "
                             f"{home} in a script)")
    why_not = host.systemd()
    removed = []
    if why_not is None:
        unit = host_unit(host)
        host.sh("systemctl", "--user", "disable", "--now", unit, timeout=120)
        for p in (host.unit_dir / unit, host.unit_dir / f"{unit}.d"):
            if p.is_dir():
                shutil.rmtree(p)
                removed.append(str(p))
            elif p.exists():
                p.unlink()
                removed.append(str(p))
        host.sh("systemctl", "--user", "daemon-reload", timeout=60)
        if args.linger_off:
            r = host.sh("loginctl", "disable-linger", pwd.getpwuid(os.getuid()).pw_name)
            print("  lingering is off" if r.returncode == 0
                  else "  note: loginctl disable-linger failed")
    else:
        print(f"  no systemd user manager to change ({why_not})")
    for p in removed:
        print(f"  removed {p}")
    try:
        cfg = config_mod.load(home, dotenv=False) if config_mod.config_path(home) else None
    except config_mod.ConfigError:
        cfg = None
    port = port_of(cfg) if cfg is not None else DEFAULT_PORT
    if why_not is None:
        print("Kranto is stopped and will not start again.")
    elif port_in_use(port) and serves_this_home(host, port, home):
        print(f"Kranto still runs in the foreground on 127.0.0.1:{port}: stop it with Ctrl-C "
              "where it runs. Nothing starts it again by itself.")
    else:
        print("Kranto is not running, and nothing starts it by itself here.")
    where = [f"the home {home}", f"the tokens {token_store(host).root}"]
    if cfg is not None and cfg.brb.enabled:
        loop = paths.loop_home(cfg.brb.loop_home)
        if not loop.is_relative_to(Path(home).resolve()):
            where.append(f"the page's folder {loop}")
    uninstall = f"uv tool uninstall {product.DIST}"
    if getattr(args, "program", False):
        uv = host.which("uv")
        r = host.sh(uv, "tool", "uninstall", product.DIST, timeout=120) if uv else None
        print(f"  removed the program ({uninstall})" if r is not None and r.returncode == 0
              else f"  note: '{uninstall}' did not run; run it yourself")
    if getattr(args, "data", False):
        for p in remove_data(home, host):
            print(f"  removed {p}")
        print("Your data is deleted.")
    else:
        print("Your data is kept: " + ", ".join(where) + ".")
    if not getattr(args, "program", False):
        print(f"Remove the program with: {uninstall} (or kranto uninstall --program)")
    for line in GITHUB_PAGES:
        print(f"On GitHub, if you want: {line}")
    return 0


def cmd_logs(args, host: Host) -> int:
    why_not = host.systemd()
    if why_not:
        print(f"no journal for Kranto here ({why_not}); 'kranto serve' logs to its terminal")
        return 1
    cmd = ["journalctl", "--user", "-u", host_unit(host), "-n", str(args.lines)]
    if not args.no_follow:
        cmd.append("-f")
    with contextlib.suppress(KeyboardInterrupt):
        return subprocess.call(cmd)
    return 0


# -- status ---------------------------------------------------------------------------------------


def _ago(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    s = max(0, int((datetime.now(UTC) - then).total_seconds()))
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60}m ago"
    if s < 172800:
        return f"{s // 3600}h {s % 3600 // 60}m ago"
    return f"{s // 86400}d ago"


def latest_runs(db: Path) -> dict[str, dict]:
    if not db.exists():
        return {}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT r.kind, r.status, r.finished_at FROM runs r JOIN (SELECT kind, "
            "MAX(finished_at) AS f FROM runs GROUP BY kind) m ON r.kind = m.kind AND "
            "r.finished_at = m.f").fetchall()
        spend = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE created_at >= ?",
            (datetime.now(UTC).strftime("%Y-%m-01"),)).fetchone()[0]
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    out = {r["kind"]: dict(r) for r in rows}
    out["_spend"] = {"month": float(spend or 0)}
    return out


def activity_read(host: Host, port: int) -> dict | None:
    """The activity read (``/api/activity``), or None when the server has no such read."""
    try:
        code, body = host.http_get(f"http://127.0.0.1:{port}/api/activity?limit=1", 5)
        a = json.loads(body) if code == 200 else None
    except Exception:  # noqa: BLE001 - the line is left out
        return None
    return a if isinstance(a, dict) and "counts" in a else None


def _band(i: dict) -> bool:
    """Kranto's own incident (the band's; ``activity.incidents.band``): the read's word, or the
    class's for a server before it (one naming no class is a model key's, as all were then)."""
    if "band" in i:
        return bool(i["band"])
    cls = str(i.get("class") or i.get("id") or "")
    return not cls or cls.startswith(("auth:", "core:"))


def incident_lines(a: dict | None) -> list[str]:
    """The incidents, said first in ``kranto status`` as the pages say them: Kranto's own (a refused
    model key) as INCIDENT, the band's; a feature's (Invest's broker) as NEEDS YOU, one row there,
    with the press that fixes it."""
    out, rows = [], []
    for i in (a or {}).get("incidents") or []:
        if not isinstance(i, dict) or not i.get("words"):
            continue
        if _band(i):
            out.append(f"INCIDENT   {i['words']} ({i.get('verb') or 'Renew the key'})")
        else:
            rows.append(f"NEEDS YOU  {i.get('title') or i['words']} ({i.get('verb') or 'Open'})")
    return out + rows


def activity_line(host: Host, port: int, a: dict | None = None) -> str | None:
    """What the top bar's indicator says, from the same read (``/api/activity``): what runs,
    what waits on you, what is failing; None when the server has no such read (older)."""
    if a is None:
        a = activity_read(host, port)
    if a is None:
        return None
    parts = []
    incs = [i for i in a.get("incidents") or [] if isinstance(i, dict)]
    own = [i for i in incs if _band(i)]
    if own:                                       # Kranto's own: the band's and the top bar's red
        parts.append("blocked: " + ", ".join(
            f"{i.get('title') or 'a model key is refused'}" for i in own[:3]))
    if len(own) < len(incs):                      # a feature's: Needs you rows
        parts.append("needs you: " + ", ".join(
            f"{i.get('title')}" for i in incs if not _band(i))[:200])
    if a["running"]:
        first = a["running"][0]
        what = first.get("title") or first.get("kind")
        if first.get("words"):
            what += f" · {first['words']}"
        parts.append(f"{len(a['running'])} running: {what}")
    else:
        # the read's sentence ends with its full stop; the line joins its parts with "; "
        parts.append((a.get("quiet") or "nothing is running").rstrip("."))
    if a["waiting"]:
        parts.append(f"{len(a['waiting'])} waiting on you ({a['waiting'][0]['title']})")
    if a.get("failing"):
        parts.append("failing: " + ", ".join(
            f"{f['title']} ({f['tries']} {'try' if f['tries'] == 1 else 'tries'})"
            for f in a["failing"][:3]))
    return "; ".join(parts)


def status_lines(home: Path, host: Host) -> tuple[list[str], bool]:
    """The one-screen status, and whether it is all well."""
    good = True
    path = config_mod.config_path(home)
    if path is None:
        return [f"kranto home {home}: none yet (run 'kranto up')"], False
    cfg = config_mod.load(home, dotenv=False)
    port = port_of(cfg)
    lines = [f"home       {home} ({path.name})"]
    why_not = host.systemd()
    if why_not:
        lines.append(f"service    not managed by systemd here: {why_not}")
    else:
        unit = host_unit(host)
        active = host.sh("systemctl", "--user", "is-active", unit).stdout.strip() or "unknown"
        enabled = host.sh("systemctl", "--user", "is-enabled", unit).stdout.strip() or "unknown"
        lines.append(f"service    {unit}: {active}, {enabled}")
        old = host.sh("systemctl", "--user", "is-active", OLD_UNIT).stdout.strip()
        if old == "active":
            lines.append(f"           {OLD_UNIT} is also active: run 'kranto adopt' to retire it")
            good = False
    server = None
    try:
        code, body = host.http_get(f"http://127.0.0.1:{port}/api/status", 5)
        server = json.loads(body) if code == 200 else None
    except Exception:  # noqa: BLE001 - reported as not answering
        server = None
    if server is None:
        lines.append(f"server     http://127.0.0.1:{port}/ is not answering")
        good = False
    else:
        lines.append(f"server     http://127.0.0.1:{port}/ answering ({product.NAME} "
                     f"{server.get('version')}, scheduler "
                     f"{'on' if server.get('scheduler', True) else 'off'})")
        if server.get("paused"):
            lines.append(f"           watching paused: {server['paused']}")
    runs = latest_runs(cfg.db_path)
    every = {"ingest": cfg.ingest.every_hours, "snapshot": cfg.map.every_hours,
             "ideas": cfg.ideas.every_hours, "compact": cfg.retention.every_hours}
    jobs = []
    for kind, hours in every.items():
        r = runs.get(kind)
        jobs.append(f"{kind} {r['status']} {_ago(r['finished_at'])}" if r else f"{kind} never"
                    + ("" if hours else " (off)"))
    news = runs.get("news.brief")        # the core's fifth: the topics' briefs, once News has run
    if news:
        jobs.insert(3, f"news {news['status']} {_ago(news['finished_at'])}")
    lines.append("jobs       " + "; ".join(jobs))
    if server is not None:
        a = activity_read(host, port)
        act = activity_line(host, port, a) if a is not None else None
        if act:
            lines.append(f"activity   {act}")
        said = incident_lines(a)
        if said:                     # a refused key stops everything: it is the first line
            lines[:0] = said
            # degraded only for what the band says (Kranto's own); a feature's is a Needs you row
            if any(x.startswith("INCIDENT") for x in said):
                good = False
    # builds left Kranto (CUT): no loop lane, loop, build spend or build login line
    lines.append("spend      watching "
                 f"${runs.get('_spend', {}).get('month', 0):.2f} "
                 + (f"{cfg.budget.of()} this month" if cfg.budget.capped
                    else "this month, no cap"))
    try:
        from .update.check import apply_state, status_line

        lines.append(f"update     {status_line(home)}")
        if apply_state(home).get("state") in ("rolled_back", "failed"):
            good = False
    except Exception as exc:  # noqa: BLE001 - a status line, never a crash
        lines.append(f"update     unknown: {exc}")
    ev = evals_line(home)
    if ev:
        lines.append(f"evals      {ev}")
    try:
        from .core.cubs import status as cubs_status

        cubs = cubs_status.status_line(cfg)
        lines.append(f"features   {cubs}")
        good = good and "STOPPED" not in cubs
    except Exception as exc:  # noqa: BLE001 - a status line, never a crash
        lines.append(f"features   unknown: {exc}")
    return lines, good


def evals_line(home: Path) -> str | None:
    """``kranto status``'s evals line: the last scorecard and its flags; None before any
    run (then the line is left out)."""
    from .evals import scorecard
    try:
        hist = scorecard.history(home)
    except OSError:
        return None
    if not hist:
        return None
    c = hist[-1]
    head = next((m for m in c.get("metrics") or [] if m.get("kind") == "rate"), None)
    flags = sorted({m["flag"] for m in c.get("metrics") or [] if m.get("flag")
                    and m["flag"] != "within noise"})
    return (f"last run {c.get('date')}: {c.get('stage')} on set {c.get('set')} with "
            f"{c.get('model')}" + (f", {head['label']} {head['num']}/{head['den']}" if head
                                   else "") + (f"; {', '.join(flags)}" if flags else
                                               "; nothing flagged")
            + f" ({len(hist)} scorecards)")


def cmd_telemetry(args, host: Host) -> int:
    """``kranto telemetry …``; opens no network connection."""
    from .telemetry import cli as telemetry_cli

    return telemetry_cli.main(kranto_home(args.home, host), list(args.rest or []))


def cmd_settings(args, host: Host) -> int:
    """``kranto settings stable-defaults [--json]``: Kranto's own settings whose stable default
    keeps the old behaviour (``Setting(default_stable=)``,): what stays off on
    stable until the owner turns it on, as a promotion's notes and its row name it."""
    import json as json_mod

    from .core import settings as settings_mod

    rest = list(args.rest or [])
    if rest[:1] != ["stable-defaults"]:
        print("usage: kranto settings stable-defaults [--json]", file=sys.stderr)
        return 2
    rows = settings_mod.stable_defaults()
    if "--json" in rest:
        print(json_mod.dumps(rows, default=str))
        return 0
    if not rows:
        print("every setting has the same default on stable and nightly")
    for r in rows:
        print(f"{r['key']}: stable keeps {r['default_stable']!r} (nightly: {r['default']!r})")
    return 0


def cmd_status(args, host: Host) -> int:
    lines, good = status_lines(kranto_home(args.home, host), host)
    print("\n".join([PITCH, "", *lines]))
    return 0 if good else 1


# -- doctor ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str


TOKEN_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
SET = "set"                                # a variable's value, as service_env keeps it


def _env_names(pairs) -> dict[str, str]:
    """``KEY=VALUE`` pairs as ``service_env`` keeps them: PATH's value, every other name
    with ``SET`` (or "" when empty), so no secret is held."""
    out = {}
    for k, v in pairs:
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        if k:
            v = v.strip().strip("'\"")
            out[k] = v if k == "PATH" else (SET if v else "")
    return out


def _service_unit(host: Host) -> str:
    """The unit ``service_env`` reads (``host_unit``)."""
    return host_unit(host)


def service_env(host: Host) -> tuple[dict[str, str], str]:
    """What Kranto's service runs with, for the checks that depend on it: ``kranto doctor`` run
    from a plain ``ssh`` shell has another PATH and none of the unit's EnvironmentFile. The
    running service's own environment (``/proc/<MainPID>/environ``), else the unit's
    ``Environment=`` and ``EnvironmentFile=`` lines (its drop-ins included), else this shell.
    Only PATH keeps its value; every other variable is a name (``_env_names``). Returns
    ``(env, where)``, ``where`` saying which was checked. The running service is asked for
    only when this HOME's units are the user manager's (``host.systemd()``): from a scratch
    HOME, ``systemctl --user`` would describe the login home's kranto.service, another
    instance. ``$KRANTO_UNIT`` names the unit (``UNIT``); the default is never read for it.
    Without ``$KRANTO_UNIT``, an install made before the rename runs as its old unit
    (``legacy.UNIT``): that one is asked when ``kranto.service`` is neither running nor
    installed."""
    UNIT = _service_unit(host)  # noqa: N806 - the name every line below says
    pid = ""
    if host.systemd() is None:
        r = host.sh("systemctl", "--user", "show", "-p", "MainPID", "--value", UNIT, timeout=10)
        pid = (r.stdout or "").strip() if r.returncode == 0 else ""
    if pid.isdigit() and int(pid) > 0:
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            raw = None
        if raw is not None:
            pairs = (e.decode(errors="replace").partition("=")[::2] for e in raw.split(b"\0") if e)
            return _env_names(pairs), f"the running {UNIT} (pid {pid})"
    unit = host.unit_dir / UNIT
    if unit.exists():
        dropins = host.unit_dir / f"{UNIT}.d"
        texts = [unit.read_text(errors="replace")] + [
            c.read_text(errors="replace") for c in sorted(dropins.glob("*.conf"))
            if dropins.is_dir()]
        env: dict[str, str] = {}
        for text in texts:
            env.update(_env_names(unit_env(text, host.home).items()))
            for line in text.splitlines():
                m = re.match(r"\s*EnvironmentFile\s*=\s*-?(.+?)\s*$", line)
                f = Path(m.group(1).replace("%h", str(host.home))).expanduser() if m else None
                if f is not None and f.is_file():
                    env.update(_env_names(ln.partition("=")[::2] for ln in
                                          f.read_text(errors="replace").splitlines()
                                          if "=" in ln and not ln.lstrip().startswith("#")))
        return env, f"{UNIT}'s unit and the files it loads (not running)"
    return _env_names(os.environ.items()), f"this shell (no {UNIT} installed)"


def dotenv_tokens(home: Path | None) -> set[str]:
    """The Claude token variables Kranto's ``.env`` sets (by name): the server adds them to its
    environment after its start, so ``service_env`` does not list them. An
    ``ANTHROPIC_API_KEY`` there is the watcher's key (Settings › Watching writes it)."""
    from .providers import _dotenv_names
    return _dotenv_names(home) & set(TOKEN_VARS)


CLAUDE_LOGIN = "login.env"             # CLAUDE_CODE_OAUTH_TOKEN=… at 0600


def claude_store(host: Host) -> Path:
    """Kranto's store for the Claude login token the console uses: ``$KRANTO_CLAUDE_DIR``, else
    ``~/.config/kranto/claude`` (``claude.<unit>`` for another ``$KRANTO_UNIT``). The page's
    ``claude_login`` reads it at each launch and pipes the token to claude; the path and the
    format are pinned by a test in each repository."""
    if os.environ.get("KRANTO_CLAUDE_DIR"):
        return Path(os.environ["KRANTO_CLAUDE_DIR"]).expanduser()
    return legacy.unit_store("claude", user_home=host.home)


def keep_claude_login(host: Host, token: str, how: str = "setup") -> Path:
    """Keep ``token`` (a Claude login token, one line) in ``claude_store`` at 0600 in a 0700
    folder, as the page's ``claude_login.Store.keep`` does; returns the file. Never printed."""
    d = claude_store(host)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    for name, text in ((CLAUDE_LOGIN, f"CLAUDE_CODE_OAUTH_TOKEN={token}\n"),
                       ("login.json", json.dumps({"kept": time.time(), "how": how}) + "\n")):
        tmp = d / f".{name}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / name)
    return d / CLAUDE_LOGIN


def claude_kept(host: Host) -> bool:
    """Kranto keeps a Claude login token in its store (``claude_store``), at 0600: by the file's
    mode and size, never its content."""
    try:
        st = (claude_store(host) / CLAUDE_LOGIN).stat()
    except OSError:
        return False
    return not st.st_mode & 0o077 and st.st_size > len("CLAUDE_CODE_OAUTH_TOKEN=\n")


CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
# The sandbox's own namespaces (the console's and the post writers'): a check that passes here
# means a sandbox can start, not only that bwrap runs.
BWRAP_PROBE = ("--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc",
               "--dev", "/dev", "true")


def userns_reason(proc_sys: Path = Path("/proc/sys")) -> str:
    """Why unprivileged user namespaces may be refused here, in words."""
    def read(rel: str) -> str | None:
        try:
            return (proc_sys / rel).read_text().strip()
        except OSError:
            return None
    if read("kernel/unprivileged_userns_clone") == "0":
        return "user namespaces are off: kernel.unprivileged_userns_clone is 0"
    if read("user/max_user_namespaces") == "0":
        return "user namespaces are off: user.max_user_namespaces is 0"
    if read("kernel/apparmor_restrict_unprivileged_userns") == "1":
        return ("AppArmor restricts unprivileged user namespaces and bwrap has no profile; "
                "on Ubuntu the bubblewrap package installs one")
    return "unprivileged user namespaces refused; in a container, run Kranto on the host"


GH_NOT_LOGGED_IN = "gh is not logged in: 'File a Kranto issue' needs it (gh auth login)"


def prerequisite_checks(home: Path, host: Host) -> list[Check]:
    """What cannot be installed for the customer (PLAN.md section 1.7), and the unit's PATH.
    Commands are looked up on the unit's PATH when a unit is installed, since that is the
    PATH the console runs with."""
    out: list[Check] = []
    unit = host.unit_dir / host_unit(host)
    path = None
    if unit.exists():
        env = unit_env(unit.read_text(), host.home)
        path = env.get("PATH")
        local = str(host.home / ".local" / "bin")
        if not path:
            out.append(Check(FAIL, "unit PATH", f"{unit} sets no PATH; claude, gh and uv in "
                                                f"{local} will not be found"))
        elif local not in path.split(":"):
            out.append(Check(FAIL, "unit PATH", f"{unit}'s PATH lacks {local}: {path}"))
        else:
            out.append(Check(OK, "unit PATH", path))
    else:
        out.append(Check(OK, "unit", f"no {unit.name} installed (kranto up installs it; checking "
                                     "this shell's PATH)"))

    def which(name):
        return host.which(name, path=path) if path else host.which(name)

    configured = configured_claude(home)
    claude = configured or which("claude")
    if configured and not (Path(configured).is_file() and os.access(configured, os.X_OK)):
        out.append(Check(FAIL, "claude", f"build.claude_command is {configured}, which is not an "
                                         "executable file: 'kranto setup machine --claude PATH' "
                                         "points Kranto at Claude Code again"))
    elif not claude:
        # Claude Code is the console's alone, and Kranto works without it
        out.append(Check(WARN, "claude", "Claude Code is not installed; Kranto works without it. "
                                         f"For the console: {CLAUDE_INSTALL}, then run 'claude' "
                                         "once to sign in"))
    else:
        from .preflight import _version
        named = f"{claude} ({_version(host, claude) or 'version unknown'}"
        named += ", build.claude_command)" if configured else ")"
        r = host.sh(claude, "auth", "status", timeout=30)
        out.append(Check(OK, "claude", f"{named}: signed in") if r.returncode == 0 else
                   Check(WARN, "claude", f"{named} is not signed in: run 'claude' and log in "
                                         "(the console uses it)"))
    out.append(_bwrap_check(which, "the sandbox of Open in Claude Code and of the post writers",
                            host))
    out += gh_checks(which, host)
    uv = which("uv")
    out.append(Check(OK, "uv", uv) if uv else
               Check(WARN, "uv", f"uv is not on PATH ('kranto update' installs releases with "
                                 f"it: uv tool upgrade {product.DIST})"))
    return out


def gh_checks(which, host: Host) -> list[Check]:
    """``gh``: 'File a Kranto issue' files through it. A warning at most: Kranto works without."""
    gh = which("gh")
    if not gh:
        return [Check(WARN, "gh", "gh is not installed: 'File a Kranto issue' needs it (install "
                                  "the GitHub CLI, then gh auth login)")]
    r = host.sh(gh, "auth", "status", timeout=30)
    out = [Check(OK, "gh", f"{gh}: logged in") if r.returncode == 0 else
           Check(WARN, "gh", GH_NOT_LOGGED_IN)]
    from .ghfetch import age_note, bin_dir
    if Path(gh).parent == bin_dir(host.home):
        note = age_note(host.sh(gh, "--version", timeout=15).stdout or "")
        if note:
            out.append(Check(WARN, "gh age", note))
    return out


def _bwrap_check(which, what: str, host: Host) -> Check:
    """Whether bubblewrap starts a sandbox with its own /proc (``what`` names whose)."""
    bwrap = which("bwrap")
    if not bwrap:
        from .preflight import family, install_command
        how = install_command("bwrap", family()) or "install the bubblewrap package"
        return Check(FAIL, "bwrap", f"bubblewrap is not installed ({what}): {how}")
    r = host.sh(bwrap, *BWRAP_PROBE, timeout=20)
    return (Check(OK, "bwrap", f"{bwrap}: a sandbox with its own /proc starts")
            if r.returncode == 0 else
            Check(WARN, "bwrap", f"{bwrap} is installed but cannot start a sandbox "
                                 f"here ({userns_reason()}): "
                                 + " ".join((r.stderr or "").split())[:120]))


def console_checks(cfg: config_mod.Config, svc: tuple[dict, str] | None = None) -> list[Check]:
    """The console's half (the page): its API version, then whether the console is ready
    (``term_check``)."""
    if not cfg.brb.enabled:
        return [Check(WARN, "console", "not ready: brb.enabled is false in the config (Kranto "
                                       "adopt turns it on)")]
    from .web.brb import REQUIRED_API

    try:
        from kranto.page.host_api import API_VERSION as version
    except ImportError as exc:
        return [Check(FAIL, "kranto.page", f"not installed, and the console needs it: {exc} "
                                        "(reinstall Kranto)")]
    return [Check(OK if version >= REQUIRED_API else FAIL, "kranto.page",
                  f"API version {version} (needs {REQUIRED_API})"),
            term_check(paths.loop_home(cfg.brb.loop_home), svc, dotenv_tokens(cfg.root)),
            *console_line(paths.loop_home(cfg.brb.loop_home))]


def console_line(loop_home: Path) -> list[Check]:
    """Doctor's line for the console (your own Claude Code or Codex beside every page): whether
    it opens by itself and whether it asks before an edit or a command, from this home's
    loop.yaml as written (``console.doctor_line``); none from a page that cannot say."""
    try:
        from kranto.page.host_api import console_doctor_line
    except ImportError:
        return []
    try:
        return [Check(OK, "console", console_doctor_line(loop_home))]
    except Exception as exc:  # noqa: BLE001 - doctor never fails on one line
        return [Check(WARN, "console", f"its settings could not be read: {exc}")]


TERM_CHECK = "open in claude code"    # doctor's line for the page's term (its sandboxed sessions)


def console_words(status: str, detail: str) -> str:
    """The page's ``term_doctor`` line as the doctor's Open in Claude Code line says it:
    "ready: …" when it is ok, else "not ready: …" with what is missing; where its switch lives
    is said without the page's file (loop.yaml). It is about Open in Claude Code's sandboxed
    sessions, not the console beside every page (which needs no Claude token of Kranto's)."""
    if detail.endswith("(term.enabled)"):                 # off on purpose: ok, and not ready
        return "off (term.enabled is false)"
    text = re.sub(r"^Open in Claude Code(: | is )", "", detail.strip())
    text = re.sub(r"\s+in loop\.yaml(\s*\(Settings › Building lists it\))?", "", text)
    return ("ready: " if status == "ok" else "not ready: ") + text


def term_check(loop_home: Path, svc: tuple[dict, str] | None = None,
               dotenv: set[str] | frozenset[str] = frozenset()) -> Check:
    """Whether the console (the page's ``term``, Open in Claude Code) is ready: the page's
    ``term_doctor`` says ``(ok|warn|fail, text)``: off, or on with its sandbox, the kernel's
    ptrace scope, and the claude CLI and a Claude token in Kranto's service's environment
    (``svc``, from ``service_env``: by name, its value is never read out; default this
    process's) or Kranto's ``.env`` (``dotenv``: the watcher's API key, which a session uses only
    once the owner chose it); the line names the token's kind (``console_words``)."""
    try:
        from kranto.page.host_api import term_doctor
    except ImportError:
        return Check(WARN, TERM_CHECK,
                     "not ready: this version of Kranto does not have it; update Kranto")
    env, where = svc or (None, "")
    try:
        try:
            status, detail = term_doctor(loop_home, environ=env, dotenv=dotenv)
        except TypeError:                                   # a version of the page before TK
            status, detail = term_doctor(loop_home, environ=env)
    except Exception as exc:  # noqa: BLE001 - a doctor line, never a crash
        return Check(WARN, TERM_CHECK, f"not ready: could not check it: {exc}")
    words = console_words(status, detail)
    if where and not detail.endswith("(term.enabled)"):
        words += f" (checked: {where})"
    return Check({"ok": OK, "warn": WARN, "fail": FAIL}.get(status, WARN), TERM_CHECK, words)


def service_checks(host: Host) -> list[Check]:
    if host.systemd():
        return []
    out = []
    old = host.sh("systemctl", "--user", "is-active", OLD_UNIT).stdout.strip()
    unit = host_unit(host)
    new = host.sh("systemctl", "--user", "is-active", unit).stdout.strip()
    if old == "active" and new == "active":
        out.append(Check(FAIL, "service", f"both {OLD_UNIT} and {unit} are active"))
    elif new == "active":
        out.append(Check(OK, "service", f"{unit} active"))
    elif old == "active":
        out.append(Check(WARN, "service", f"{OLD_UNIT} is still the running service; "
                                          "'kranto adopt' switches to kranto.service"))
    dropin = host.unit_dir / f"{OLD_UNIT}.d" / OLD_DROPIN
    if dropin.exists():
        out.append(Check(WARN, "drop-in", f"{dropin} is retired: kranto serve runs the "
                                          "scheduler by default ('kranto adopt' removes it)"))
    return out


def doctor_checks(home: Path, host: Host, *, check_embedder: bool = False,
                  transport=None) -> list[Check]:
    from . import doctor
    from .store import Store

    path = config_mod.config_path(home)
    if path is None:
        return [Check(FAIL, "home", f"{home} has no kranto.yaml: run "
                                    "'kranto up' (new) or 'kranto adopt' (existing)")]
    try:
        cfg = config_mod.load(home)  # as afk doctor: the key check needs the .env
    except ConfigError as exc:
        return [Check(FAIL, "config", str(exc))]
    checks: list[Check] = []
    pending = pending_migrations(cfg.db_path)
    if pending:
        numbers = ", ".join(map(str, pending))
        checks.append(Check(FAIL, "migrations", f"{len(pending)} pending ({numbers}); back up "
                            "first: 'kranto adopt' does, then applies them"))
        checks.append(Check(WARN, "library", "not opened, so the pending migrations are not "
                                             "applied without a backup"))
    else:
        checks.append(Check(OK, "migrations", "current" if cfg.db_path.exists()
                            else "no library yet (made on first start)"))
        if cfg.db_path.exists():
            store = Store.open(cfg.db_path)
            try:
                checks += [Check(c.status, c.name, c.detail) for c in
                           doctor.run(cfg, store, transport=transport,
                                      check_embedder=check_embedder)]
            finally:
                store.close()
    if not (cfg.db_path.exists() and not pending):        # doctor.run, which says it, did not run
        checks += [Check(c.status, c.name, c.detail) for c in doctor.retired_builds(cfg)]
    svc = service_env(host)                    # what Kranto's service has, not this shell
    login = doctor.watch_login(cfg, set(svc[0]))
    if login is not None:
        checks.append(Check(login.status, login.name, login.detail))
    checks += console_checks(cfg, svc)
    checks.append(token_check(host, cfg))
    checks.append(mcp_check())
    checks.append(assistant_check(host, home))
    checks += prerequisite_checks(home, host)
    checks += service_checks(host)
    return checks


MCP_INSTALL = ("install kranto[mcp] from the release's wheels: "
               "https://github.com/iddv/kranto/blob/main/docs/setup.md#2-install")


def mcp_check() -> Check:
    """Whether ``kranto mcp`` can run: the optional MCP extra (the SDK) is installed."""
    try:
        from kranto.page.host_api import mcp_available
    except ImportError:
        return Check(OK, "mcp", "kranto mcp is not in this version of Kranto (optional)")
    if mcp_available():
        return Check(OK, "mcp", "the MCP extra is installed: claude mcp add kranto -- kranto mcp")
    return Check(OK, "mcp", f"the MCP extra is not installed (optional; {MCP_INSTALL})")


def assistant_check(host: Host, home: Path) -> Check:
    """The Assistant line: Claude Code and Codex on PATH, the plugin in this install, Kranto's
    files in its home (``kranto assistant``)."""
    from .assistant import doctor_line
    try:
        return Check(OK, "assistant", doctor_line(host.which, home))
    except OSError as exc:
        return Check(OK, "assistant", f"Kranto's assistant files could not be read: {exc}")


def mcp_url(home: Path) -> str:
    """The service this home is served on, for ``kranto mcp`` (loopback)."""
    try:
        cfg = config_mod.load(home, dotenv=False)
        return f"http://127.0.0.1:{port_of(cfg)}"
    except (ConfigError, OSError):
        return f"http://127.0.0.1:{DEFAULT_PORT}"


def cmd_mcp(args, host: Host) -> int:
    """``kranto mcp [--url URL]``: the local MCP server on stdio (kranto.page.mcp). It never starts
    Kranto; it talks to the running service on loopback."""
    try:
        from kranto.page.host_api import mcp_main
    except ImportError:
        print("kranto mcp: this version of Kranto has no MCP server; update Kranto",
              file=sys.stderr)
        return 2
    if getattr(args, "term", None):
        try:
            from kranto.page.host_api import term_mcp_main
        except ImportError:
            print("kranto mcp: this version of Kranto has no Open in Claude Code; update Kranto",
                  file=sys.stderr)
            return 2
        _loop_home_env(args, host)
        return term_mcp_main(args.term)
    url = args.url
    if not url:
        home = kranto_home(args.home, host)
        url = mcp_url(home) if config_mod.config_path(home) else \
            f"http://127.0.0.1:{DEFAULT_PORT}"
    console, compact = getattr(args, "console", None), bool(getattr(args, "compact", False))
    if console or compact:
        import inspect
        if "console" not in inspect.signature(mcp_main).parameters:
            print("kranto mcp: this version of Kranto has no --console or --compact; update Kranto",
                  file=sys.stderr)
            return 2
        return mcp_main(url, console=console, compact=compact)
    return mcp_main(url)


def cmd_assistant(args, host: Host) -> int:
    """``kranto assistant [show|setup|global claude|codex]``: your own Claude Code or Codex
    with Kranto (``assistant.py``). ``setup`` writes inside Kranto's home only; ``global`` shows
    the exact change to your harness's own configuration and makes it with ``--yes``."""
    from . import assistant as A
    home = kranto_home(args.home, host)
    if args.cmd == "show":
        print(f"plugin      {tilde(A.PLUGIN_DIR, host.home)}")
        print(f"assistant   {A.doctor_line(host.which, home)}")
        for c in A.plan(home):
            print(f"  {c.state:<6} {tilde(c.path, host.home)}")
        print("install it in your own client (kranto assistant global claude|codex does it):")
        for line in A.install_lines():
            print(f"  {line}")
        return 0
    if args.cmd == "setup":
        changes = A.plan(home)
        for c in changes:
            word = {"new": "writes", "update": "updates", "same": "keeps",
                    "theirs": "leaves yours"}[c.state]
            print(f"{word:<12} {tilde(c.path, host.home)}")
        if args.dry_run:
            return 0
        done = A.apply(changes)
        print(f"kranto assistant: {len(done)} file(s) written in {tilde(home, host.home)}; "
              "nothing outside it")
        return 0
    if not args.harness:
        print("kranto assistant global: say which: claude or codex", file=sys.stderr)
        return 2
    steps = A.global_steps(args.harness, host.which)
    files = A.codex_global_skills(host.home) if args.harness == "codex" else []
    print("This changes your own configuration, outside Kranto's home:")
    for s in steps:
        print("  $ " + " ".join(s))
    for c in files:
        print(f"  {c.state:<6} {tilde(c.path, host.home)}")
    if not args.yes:
        print("Nothing was changed: run it again with --yes to make this change.")
        return 0
    for s in steps:
        r = host.run(s, timeout=120)
        if getattr(r, "returncode", 1) != 0:
            print(f"kranto assistant: {' '.join(s)} failed; nothing more was changed",
                  file=sys.stderr)
            return 1
    A.apply(files)
    print("kranto assistant: done. Restart your client to load Kranto.")
    return 0


def _loop_home_env(args, host: Host) -> None:
    """This home's loop home in ``KRANTO_LOOP_HOME``, for the page commands run in-process."""
    home = kranto_home(args.home, host)
    os.environ[KRANTO_HOME_ENV] = str(home)
    if config_mod.config_path(home):
        os.environ.setdefault("KRANTO_LOOP_HOME", str(paths.loop_home(
            config_mod.load(home, dotenv=False).brb.loop_home)))


def cmd_term(args, host: Host) -> int:
    """``kranto term list|open|end``: Open in Claude Code's sessions from your own terminal
    (the page's ``term.cli``): ``open`` continues one here with exactly the page's limits."""
    try:
        from kranto.page.host_api import term_cli
    except ImportError:
        print("kranto term: this version of Kranto has no Open in Claude Code; update Kranto",
              file=sys.stderr)
        return 2
    _loop_home_env(args, host)
    return term_cli(list(args.rest or []))


def cmd_cub(args, host: Host) -> int:
    """``kranto cub …``: the cubs of this home."""
    from .core.cubs import cli as cubs_cli
    home = kranto_home(args.home, host)
    if not config_mod.config_path(home):
        print(f"kranto cub: no kranto home at {home} (kranto up first)", file=sys.stderr)
        return 2
    return cubs_cli.main(home, list(args.rest or []))


WATCH = "watch"


def cmd_watch(args, host: Host) -> int:
    """``kranto watch …``: the watcher's own commands (``kranto.cli``: topics, sources, run,
    search, ideas, provider, news, …) on this home. The same parser ``python -m kranto`` runs;
    this home is its workspace unless ``-w`` names another."""
    from . import cli

    rest = list(args.rest or [])
    if not any(w in ("-w", "--workspace") or w.startswith("--workspace=") for w in rest):
        rest = ["-w", str(kranto_home(args.home, host)), *rest]
    return cli.main(rest)


def _split_watch(argv: Sequence[str]) -> tuple[list[str], list[str]] | None:
    """``kranto [--home H] watch REST``: (the words up to ``watch``, REST); None for any other
    command. REST goes to the watcher's parser whole (``--help`` included), never to ours."""
    words = list(argv)
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--home":
            i += 2
            continue
        if w.startswith("--home="):
            i += 1
            continue
        if w.startswith("-"):
            return None  # --help, --version: ours
        return (words[: i + 1], words[i + 1:]) if w == WATCH else None
    return None


def cmd_trace(args, host: Host) -> int:
    """``kranto trace list|show``: an assistant session's agent trace for this home
    (turns, tool calls, cost, the failure point), read from its files, redacted."""
    try:
        from kranto.page.host_api import add_trace_group
    except ImportError:
        print("kranto trace: this version of Kranto has no traces; update Kranto", file=sys.stderr)
        return 2
    _loop_home_env(args, host)
    p = argparse.ArgumentParser(prog="kranto")
    add_trace_group(p.add_subparsers(dest="cmd", required=True))
    ns = p.parse_args(["trace", *list(args.rest or [])])
    try:
        ns.fn(ns)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return 0


def cmd_eval(args, host: Host) -> int:
    """``kranto eval ...`` (``kranto.evals.cli``) for this home."""
    from .evals import cli as evals_cli
    home = kranto_home(args.home, host)
    threshold = None
    if config_mod.config_path(home):
        with contextlib.suppress(ConfigError, OSError):
            threshold = config_mod.load(home, dotenv=False).ingest.signal_threshold
    return evals_cli.main(list(args.rest or []), home, threshold=threshold)


# -- tokens and signing in (OI) -------------------------------------------------------------------


def token_store(host: Host):
    """This unit's token store (``~/.config/kranto/tokens``; ``tokens.<unit>`` for another
    ``$KRANTO_UNIT``)."""
    from . import tokens

    return tokens.Store(tokens.tokens_dir(home=host.home))


def signin_link(home: Path, host: Host, then: str = "/") -> str:
    """A link that signs one browser in (a one-time code, 10 minutes), then goes to ``then``."""
    from urllib.parse import quote

    try:
        port = port_of(config_mod.load(home, dotenv=False))
    except (ConfigError, OSError):
        port = DEFAULT_PORT
    code = token_store(host).mint_code()
    return f"http://127.0.0.1:{port}/auth/open?code={code}" + \
        (f"&next={quote(then, safe='/#')}" if then != "/" else "")


def token_check(host: Host, cfg: config_mod.Config) -> Check:
    if not cfg.api.require_token:
        return Check(WARN, "tokens", "api.require_token is off: a request says who it is, so "
                                     "any local process can act as you (the old behaviour)")
    from . import tokens

    store = token_store(host)
    missing = [d for d in tokens.DOORS if store.value(d) is None]
    if missing:
        return Check(WARN, "tokens", f"no {', '.join(missing)} token in {store.root}: 'kranto up' "
                                     "or a restart of Kranto makes them")
    loose = [p.name for p in [store.root, *store.root.glob("*.token")]
             if p.exists() and p.stat().st_mode & 0o077]
    if loose:
        return Check(WARN, "tokens", f"readable by others: {', '.join(loose)} (chmod 700 the "
                                     "folder, 600 the files)")
    agents = [t["name"] for t in store.list() if t["name"] not in tokens.DOORS]
    return Check(OK, "tokens", "writes need a token (ui, mcp, cli" +
                 (f"; agents: {', '.join(agents)}" if agents else "; no agent tokens") + ")")


def cmd_open(args, host: Host) -> int:
    """``kranto open``: sign a browser in to this Kranto (a one-time link)."""
    home = kranto_home(args.home, host)
    if config_mod.config_path(home) is None:
        raise KrantoError(f"{home} is not a Kranto home yet: run 'kranto up' first")
    print("This link signs one browser in to Kranto (once, within 10 minutes):")
    _open_browser(signin_link(home, host), args.no_browser)
    return 0


def cmd_token(args, host: Host) -> int:
    """``kranto token list|add|rotate|revoke|actions|path``: the local tokens (OI). Values are
    never printed: each lives in its own file at mode 600."""
    from . import tokens

    store = token_store(host)
    store.ensure_doors()
    name = args.name or ""
    if name and ":" not in name and name not in tokens.DOORS:
        name = "agent:" + name
    try:
        if args.cmd == "list":
            for t in store.list():
                acts = "default" if t["actions"] is None else ",".join(t["actions"]) or "none"
                made = datetime.fromtimestamp(t["created"] or 0, UTC).strftime("%Y-%m-%d %H:%M")
                kind = "door" if t["name"] in tokens.DOORS else \
                    "captures only" if t["name"].startswith("browser:") else f"actions: {acts}"
                # a browser's value lives in its extension: no file here
                print(f"{t['name']:<22} {made} UTC  {kind:<28} {t['file'] or 'in the browser'}")
            return 0
        if not name:
            raise KrantoError(f"kranto token {args.cmd} needs a name (agent:<name>)")
        if args.cmd == "add":
            path = store.add(name, _actions_arg(args.actions), args.note or "")
            print(f"added {name}; its token is in {path} (mode 600). The agent sends it as\n"
                  f"  Authorization: Bearer $(cat {tilde(path, host.home)})")
        elif args.cmd == "rotate":
            path = store.rotate(name)
            print(f"rotated {name}; the new token is in {path}"
                  + ("; every browser signs in again (kranto open)" if name == "ui" else ""))
        elif args.cmd == "revoke":
            if not store.revoke(name):
                raise KrantoError(f"no token {name}")
            print(f"revoked {name}: it no longer works")
        elif args.cmd == "actions":
            store.set_actions(name, _actions_arg(args.actions))
            print(f"{name}: actions {args.actions or 'default'}")
        elif args.cmd == "path":
            if name not in {t["name"] for t in store.list()}:
                raise KrantoError(f"no token {name}")
            print(store.path(name))
    except tokens.TokenError as exc:
        raise KrantoError(str(exc)) from exc
    return 0


def _actions_arg(text: str | None) -> list[str] | None:
    """``--actions a,b`` (``default``: null, kranto mcp's set), checked against the page's
    registry when it is installed."""
    from .web.auth import check_actions

    if text in (None, "", "default"):
        return None
    return check_actions([x.strip() for x in text.split(",") if x.strip()])


def cmd_doctor(args, host: Host) -> int:
    home = kranto_home(args.home, host)
    if getattr(args, "routes", False):
        return doctor_routes(home, args)
    checks = doctor_checks(home, host, check_embedder=args.embedder)
    print(PITCH + "\n")
    for c in checks:
        print(f"{c.status:<5} {c.name:<14} {c.detail}")
    from . import rowsafe  # its summary goes into Send this error's reports
    rowsafe.keep_doctor(home / "data", checks)
    return 1 if any(c.status == FAIL for c in checks) else 0


def doctor_routes(home: Path, args) -> int:
    """``kranto doctor --routes``: the post-update self-check on the running server (RCA D1,
    ``update/apply.py``'s ``route_check``): every page it serves, read once, read-only, on this
    install's own data. Exit 1 when one answers 500 or above, or does not answer."""
    from .update.apply import route_check, selfcheck_words

    port = args.port
    if port is None:
        try:
            port = port_of(config_mod.load(home, dotenv=False))
        except (ConfigError, OSError) as exc:
            print(f"FAIL  routes         {home} has no readable config: {exc}")
            return 1
    res = route_check(f"http://127.0.0.1:{port}")
    if getattr(args, "json", False):
        print(json.dumps(res, indent=1))
    elif res.get("skipped"):
        print(f"warn  routes         not checked: {res['skipped']} (127.0.0.1:{port})")
    elif res["ok"]:
        print(f"ok    routes         {res['checked']} of {res['of']} reads answered on your "
              f"data in {res['seconds']} s" + (f"; {res['unchecked']} past the time budget"
                                               if res.get("unchecked") else ""))
    else:
        print(f"FAIL  routes         {selfcheck_words(res, None).split(': ', 1)[1]}")
        for f in res["failed"]:
            print(f"      GET {f['path']}: {f['status'] or 'no answer'}"
                  + (f" (error {f['error_id']}: kranto report {f['error_id']})"
                     if f.get("error_id") else ""))
    return 0 if res["ok"] else 1


def cmd_report(args, host: Host) -> int:
    """``kranto report [ID]``: the report Send this error files, for one kept error (default:
    the newest), as one file under ``<home>/reports/``; prints its path. Nothing is sent."""
    from . import rowsafe
    from .store import utcnow

    home = kranto_home(args.home, host)
    data = home / "data"
    if not args.no_doctor:
        rowsafe.keep_doctor(data, doctor_checks(home, host))
    path = data / rowsafe.FILE
    if args.error_id:
        rec = rowsafe.find(args.error_id, path)
        if rec is None:
            print(f"no error {args.error_id} is kept in {path}", file=sys.stderr)
            return 1
    else:
        kept = rowsafe.kept(path)
        rec = kept[-1] if kept else None
    if rec is None:
        rec = {"id": "none", "exception": "no error", "where": "nothing kept", "kind": "-",
               "frames": [], "at": None}
    rep = rowsafe.report(rec, data)
    out = home / "reports" / f"kranto-report-{rep['id']}-{utcnow():%Y%m%dT%H%M%SZ}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# {rep['title']}\n\n{rep['body']}\nFile it: "
                   f"https://github.com/{rowsafe.REPO}/issues/new?template={rowsafe.TEMPLATE}"
                   " (paste this file's text), or click Send this error on the page.\n")
    print(out)
    return 0


# -- adopt ----------------------------------------------------------------------------------------


@dataclass
class Step:
    title: str
    lines: list[str]
    action: Callable[[], list[str]] | None = None
    service: bool = False  # a change to the running services: needs the owner's yes


@dataclass
class Found:
    workspace: Path
    config: Path
    loop_home: Path
    tasks: Path
    backups: Path
    old_unit: str          # active, inactive, ... or "" when systemd is not usable
    dropin: Path | None
    systemd: str | None    # None: usable, else why not


def old_tasks_dir(loop_home: Path) -> Path:
    """Where the old loop at ``loop_home`` kept its task folders (``tasks_dir`` in its
    ``loop.yaml``, else ``~/tasks``), for adopt's ``brb.root``. Reads only; a file of any shape
    reads as empty."""
    import yaml

    f = paths.LoopLayout(Path(loop_home)).settings
    try:
        data = (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}
    except (OSError, yaml.YAMLError):
        data = {}
    tasks = data.get("tasks_dir") if isinstance(data, dict) else None
    return Path(tasks if isinstance(tasks, str) and tasks else "~/tasks").expanduser()


def find_layout(args, host: Host) -> Found:
    # The defaults are the layout the server and the page were installed in before Kranto
    # (legacy.WORKSPACE, legacy.LOOP_HOME, ~/tasks): adopt is the documented way off it. -w and
    # --loop-home cover any other layout; a new install uses 'kranto up' instead.
    old_ws = host.home / legacy.WORKSPACE.removeprefix("~/")
    ws = Path(args.workspace or old_ws).expanduser().resolve()
    cfg_path = config_mod.config_path(ws)
    if cfg_path is None:
        raise KrantoError(f"no workspace at {ws} (no kranto.yaml); pass -w")
    lh = paths.loop_home(args.loop_home or os.environ.get(paths.LOOP_HOME_ENV) or legacy.LOOP_HOME)
    tasks = old_tasks_dir(lh)
    why_not = host.systemd()
    old = "" if why_not else host.sh("systemctl", "--user", "is-active", OLD_UNIT).stdout.strip()
    dropin = host.unit_dir / f"{OLD_UNIT}.d" / OLD_DROPIN
    return Found(
        workspace=ws,
        config=cfg_path,
        loop_home=lh,
        tasks=tasks,
        backups=Path(args.backups).expanduser().resolve()
        if args.backups
        else ws.parent / f"{ws.name}-backups",
        old_unit=old,
        dropin=dropin if dropin.exists() else None,
        systemd=why_not,
    )


def plan_adopt(
    found: Found,
    host: Host,
    *,
    port: int = DEFAULT_PORT,
    today: str | None = None,
    service: bool = True,
) -> list[Step]:
    """The adoption, as steps that say what they will do. ``kranto adopt --dry-run`` prints
    them; ``kranto adopt`` prints them, asks, and runs them in order."""
    from .store import Store

    today = today or datetime.now().strftime("%Y-%m-%d")
    db = legacy.db_file(found.workspace / "data")
    loop_db = paths.LoopLayout(found.loop_home).db
    steps: list[Step] = []

    # 1. back up
    targets = [(db, found.backups / f"{db.name}.{today}-pre-kranto")]
    if loop_db.exists():
        targets.append((loop_db, found.backups / f"loop.db.{today}-pre-kranto"))

    def backup() -> list[str]:
        out = [
            f"backed up {src} to {backup_sqlite(src, dest)}"
            for src, dest in targets
            if src.exists()
        ]
        found.backups.mkdir(parents=True, exist_ok=True)
        dest = _free_path(found.backups / f"{found.config.name}.{today}-pre-kranto")
        shutil.copy2(found.config, dest)
        out.append(f"copied {found.config} to {dest}")
        return out

    steps.append(
        Step(
            "Back up",
            [f"{s} -> {d}" for s, d in targets if s.exists()]
            + [f"{found.config} -> {found.backups}/{found.config.name}.{today}-pre-kranto"],
            backup,
        )
    )

    # 2. the brb section
    text = found.config.read_text()
    block = brb_block(tilde(found.loop_home, host.home), tilde(found.tasks, host.home))
    new_text = set_section(text, "brb", block)
    current = config_mod.load(found.workspace, dotenv=False).brb
    wanted_same = (
        current.enabled
        and current.loop_home
        and current.root
        and Path(current.loop_home).expanduser().resolve() == found.loop_home
        and Path(current.root).expanduser().resolve() == found.tasks.resolve()
    )
    if wanted_same:
        steps.append(Step("Config", [f"{found.config}: brb section already on, nothing to write"]))
    else:

        def write_config() -> list[str]:
            tmp = found.config.with_name(found.config.name + ".kranto-tmp")
            tmp.write_text(new_text)
            os.chmod(tmp, found.config.stat().st_mode & 0o777)
            os.replace(tmp, found.config)
            try:
                config_mod.load(found.workspace, dotenv=False)
            except ConfigError as exc:  # never leave a config the server cannot load
                found.config.write_text(text)
                raise KrantoError(
                    f"the new config did not load ({exc}); the old one is back"
                ) from exc
            return [f"wrote the brb section into {found.config}"]

        steps.append(
            Step(
                "Config",
                [f"{found.config}: write"]
                + ["  " + line for line in block.splitlines() if not line.strip().startswith("#")],
                write_config,
            )
        )

    # 3. migrations
    pending = pending_migrations(db)
    if pending:

        def migrate() -> list[str]:
            Store.open(db).close()
            left = pending_migrations(db)
            if left:
                raise KrantoError(f"migrations still pending after opening: {left}")
            return [f"applied migrations {', '.join(map(str, pending))}"]

        steps.append(
            Step(
                "Migrations", [f"apply {', '.join(map(str, pending))} (after the backup)"], migrate
            )
        )
    else:
        steps.append(Step("Migrations", ["none pending"]))

    # 4. setup done, so #/welcome does not show for an installation that already runs
    def mark_done() -> list[str]:
        store = Store.open(db)
        try:
            if store.get_setting(SETUP_DONE_KEY):
                return [f"{SETUP_DONE_KEY} already set"]
            store.set_setting(SETUP_DONE_KEY, f"adopted {today}")
            return [f"set {SETUP_DONE_KEY} (onboarding skipped: this installation is set up)"]
        finally:
            store.close()

    steps.append(
        Step(
            "Setup",
            [f"mark setup done ({SETUP_DONE_KEY} in settings) so #/welcome does not show"],
            mark_done,
        )
    )

    # 5. the home, recorded so every Kranto command finds it without --home
    def remember() -> list[str]:
        return [
            f"recorded {found.workspace} as the kranto home in "
            f"{remember_home(found.workspace, host.home)}"
        ]

    steps.append(
        Step(
            "Home",
            [
                f"record {found.workspace} as the kranto home in "
                f"{pointer_path(host.home)} ('kranto status' needs no --home)"
            ],
            remember,
        )
    )

    # 6. the services
    if not service:
        steps.append(Step("Service", ["skipped (--no-service): the units are not touched"]))
    elif found.systemd:
        steps.append(
            Step(
                "Service",
                [
                    f"skipped: {found.systemd}",
                    f"on the real machine this step installs kranto.service and retires {OLD_UNIT}",
                ],
            )
        )
    else:
        unit_text = render_unit(found.workspace, kranto_exe(host), port, host.home)
        unit = host.unit_dir / UNIT
        lines = [f"write {unit} (KRANTO_HOME={_h(found.workspace, host.home)}, port {port})"]
        if found.old_unit:
            lines.append(f"systemctl --user disable --now {OLD_UNIT} (now {found.old_unit})")
        if found.dropin:
            lines.append(
                f"move {found.dropin} to {found.backups}/ (retired: the scheduler is "
                "on by default under kranto serve)"
            )
        lines += [
            "systemctl --user daemon-reload",
            f"systemctl --user enable --now {UNIT}",
            "loginctl enable-linger (so it runs without a login)",
        ]

        moved: list[Path] = []

        def rollback(why: str) -> KrantoError:
            """kranto did not come up: put the old service back as it was."""
            host.sh("systemctl", "--user", "disable", "--now", UNIT, timeout=120)
            for dest in moved:
                found.dropin.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(dest, found.dropin)
            host.sh("systemctl", "--user", "daemon-reload", timeout=120)
            back = ""
            if found.old_unit == "active":
                r = host.sh("systemctl", "--user", "enable", "--now", OLD_UNIT, timeout=120)
                back = f"; {OLD_UNIT} is " + (
                    "back" if r.returncode == 0 else "NOT back: " + (r.stderr or "").strip()
                )
            return KrantoError(
                f"{why}. Rolled back: {UNIT} disabled, the drop-in restored"
                f"{back}. See 'journalctl --user -u {UNIT}'"
            )

        def switch() -> list[str]:
            done = []
            install_unit(host, unit_text)
            done.append(f"wrote {unit}")
            if found.old_unit:
                r = host.sh("systemctl", "--user", "disable", "--now", OLD_UNIT, timeout=120)
                if r.returncode != 0:
                    raise KrantoError(f"could not stop {OLD_UNIT}: {(r.stderr or '').strip()}")
                done.append(f"stopped and disabled {OLD_UNIT}")
            if found.dropin:
                dest = _free_path(found.backups / f"{OLD_UNIT}.d.{OLD_DROPIN}.{today}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(found.dropin, dest)
                moved.append(dest)
                done.append(f"moved {found.dropin} to {dest}")
            for cmd in (["daemon-reload"], ["enable", "--now", UNIT]):
                r = host.sh("systemctl", "--user", *cmd, timeout=120)
                if r.returncode != 0:
                    raise rollback(
                        f"systemctl --user {' '.join(cmd)} failed: {(r.stderr or r.stdout).strip()}"
                    )
                done.append(f"systemctl --user {' '.join(cmd)}")
            host.sh("loginctl", "enable-linger", pwd.getpwuid(os.getuid()).pw_name)
            if not _wait_up(host, port, 120):
                raise rollback(
                    f"{UNIT} started but http://127.0.0.1:{port}/ did not answer within 120 s"
                )
            done.append(f"Kranto is answering on http://127.0.0.1:{port}/")
            return done

        steps.append(Step("Service", lines, switch, service=True))
    return steps


def print_found(found: Found) -> None:
    print("found:")
    print(f"  workspace   {found.workspace} ({found.config.name})")
    print(
        f"  loop home   {found.loop_home}"
        + ("" if paths.LoopLayout(found.loop_home).db.exists() else " (no loop.db yet)")
    )
    print(f"  tasks       {found.tasks}")
    print(f"  backups     {found.backups}")
    if found.systemd:
        print(f"  systemd     not usable here: {found.systemd}")
    else:
        print(
            f"  {OLD_UNIT:<11} {found.old_unit or 'not installed'}"
            + (f"; drop-in {found.dropin}" if found.dropin else "")
        )


def cmd_adopt(args, host: Host) -> int:
    found = find_layout(args, host)
    steps = plan_adopt(found, host, port=args.port or DEFAULT_PORT, service=not args.no_service)
    print_found(found)
    print("\nplan:" if not args.dry_run else "\nplan (dry run: nothing is changed):")
    for i, step in enumerate(steps, 1):
        print(f"  {i}. {step.title}")
        for line in step.lines:
            print(f"       {line}")
    if args.dry_run:
        return 0
    if not args.yes:
        if not host.stdin_tty:
            print("\nnot a terminal: re-run with --yes to go ahead")
            return 1
        if input("\nGo ahead? This restarts the service. [y/N] ").strip().lower() not in (
            "y",
            "yes",
        ):
            print("nothing changed")
            return 1
    for step in steps:
        if step.action is None:
            continue
        try:
            for line in step.action():
                print(f"  {line}")
        except Exception as exc:
            print(f"\n{step.title} failed: {exc}", file=sys.stderr)
            print("the steps before it are done; nothing after it ran", file=sys.stderr)
            return 1
    print("\nadopted. 'kranto status' shows the service; 'kranto doctor' checks the rest.")
    return 0


# -- update and backup ---------------------------------------------------------------------------

UPDATE_AVAILABLE = 10  # kranto update --check: an update is available (scriptable)


def cmd_backup(args, host: Host) -> int:
    from .update.backup import backup

    home = kranto_home(args.home, host)
    dest = (
        Path(args.dir).expanduser()
        if args.dir
        else home / "backups" / f"manual-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    try:
        out = backup(dest, home, unit=host_unit(host), user_home=host.home, versions=versions())
    except RuntimeError as exc:
        raise KrantoError(str(exc)) from exc
    print(f"backed up {home} to {out['dir']}")
    for name, d in out["databases"].items():
        print(f"  {name:<12} integrity {d['integrity']}, {d['bytes']} bytes")
    for f in out["files"]:
        print(f"  copied {f}")
    print(f"  counts {out['counts']} (counts-before.json)")
    return 0


UPDATE_EXIT = {"done": 0, "rolled_back": 3, "failed": 4, "cancelled": 5}


def _tag(to: str) -> str:
    """``0.2.0`` or ``0.2.0rc1`` or ``v0.2.0-rc1`` -> ``v0.2.0-rc1``; a nightly build's
    ``0.7.0.dev12`` (its wheel version) or ``v0.7.0-dev12`` -> ``v0.7.0-dev12``."""
    t = to.strip()
    t = t if t.startswith("v") else "v" + t
    t = re.sub(r"(?<=\d)[.-]dev(\d+)$", r"-dev\1", t)
    return re.sub(r"(?<=\d)-?rc(\d+)$", r"-rc\1", t)


def _busy_line(host: Host, port: int) -> str | None:
    try:
        code, body = host.http_get(f"http://127.0.0.1:{port}/api/update", 5)
        busy = (json.loads(body) or {}).get("busy") or {} if code == 200 else {}
    except Exception:  # noqa: BLE001 - not answering: nothing known to be running
        return None
    parts = [
        f"{busy['builds']} build(s) running" if busy.get("builds") else "",
        f"{busy['fixes']} fix(es) running" if busy.get("fixes") else "",
        f"the server's {busy['job']} run" if busy.get("job") else "",
        f"cub {', '.join(busy['cubs'])} at work" if busy.get("cubs") else "",
    ]
    return ", ".join(p for p in parts if p) or None


def tail_update(home: Path, *, every: float = 2.0, out=print) -> str:
    """Print the helper's steps until it reaches a final state; returns it. Uses only what
    is already imported: the environment it runs from is being replaced underneath it."""
    from .update.apply import FINAL, read_json, state_path
    from .update.launch import running

    seen = None
    started = time.monotonic()
    while True:
        st = read_json(state_path(home), None) or {}
        line = (st.get("state"), st.get("detail"))
        if line != seen and st.get("state"):
            out(f"  {st['state']}" + (f": {st['detail']}" if st.get("detail") else ""))
            seen = line
        if st.get("state") in FINAL:
            if st.get("reason"):
                out(f"  reason: {st['reason']}")
            return st["state"]
        if time.monotonic() - started > 30 and not running(home):
            out(
                "  the helper stopped without finishing; see its log: "
                f"{st.get('log') or 'journalctl --user -u kranto-update'}"
            )
            return "failed"
        time.sleep(every)


def cmd_update(args, host: Host) -> int:
    from dataclasses import replace

    from .update.apply import (
        SetError,
        cancel_path,
        previous_path,
        read_json,
        releases_dir,
        tag_version,
        verify_set,
        vkey,
        wheels_in,
    )
    from .update.check import (
        apply_state,
        available,
        installed_here,
        run_check,
        settings,
        stage_tag,
        status_line,
    )
    from .update.launch import LaunchError, launch
    from .update.sources import SourceError

    home = kranto_home(args.home, host)
    if config_mod.config_path(home) is None:
        raise KrantoError(f"{home} is not a Kranto home yet: run 'kranto up' first")
    from . import preview

    if preview.enabled(home):
        raise KrantoError(
            "this is the preview: it is never updated ('kranto-preview refresh' "
            "builds it again from its branch)"
        )
    with contextlib.suppress(OSError):
        token_store(host).ensure_doors()  # the new version's server makes them too, at start
    if args.cancel:
        st = apply_state(home)
        if st.get("state") not in ("requested", "draining"):
            print(f"nothing to cancel (the update is {st.get('state')})")
            return 1
        cancel_path(home).touch()
        print("asked the update to let go; it changes nothing ('kranto status' shows it)")
        return 0
    ucfg = settings(home)
    if args.channel:
        ucfg = replace(ucfg, channel=args.channel)
    if args.check:
        cache = run_check(home, ucfg)
        print(f"update     {status_line(home)}")
        if not cache.get("ok"):
            return 1
        return UPDATE_AVAILABLE if available(cache) else 0

    inst = installed_here()
    if args.rollback:
        prev = read_json(previous_path(home), None)
        if not prev or prev.get("kind") not in ("wheels", "git"):
            raise KrantoError("there is no previous version recorded to roll back to")
        to, label = "previous", f"{inst.get('version')} -> {prev.get('version')} (roll back)"
    else:
        cache = run_check(home, ucfg)
        if not cache.get("ok"):
            raise KrantoError(f"the check failed: {cache.get('error')}")
        if args.to:
            to = _tag(args.to)
            if not (releases_dir(home) / to).is_dir():
                try:
                    stage_tag(home, to, ucfg)
                except (SetError, SourceError) as exc:
                    raise KrantoError(f"{to}: {exc}") from exc
        else:
            offer = available(cache, inst)
            if not offer:
                print(f"update     {status_line(home)}")
                return 0
            staged = cache.get("staged") or {}
            if staged.get("version") != offer:
                raise KrantoError(
                    f"{offer} is available but not staged: "
                    f"{cache.get('stage_error') or 'run kranto update --check'}"
                )
            to = staged["tag"]
        try:
            verify_set(releases_dir(home) / to, tag_version(to))
        except SetError as exc:
            raise KrantoError(f"{to} does not verify: {exc}") from exc
        version = tag_version(to)
        label = f"{inst.get('version')} -> {version}"
        if vkey(version) < vkey(inst.get("version")) and not args.yes:
            raise KrantoError(
                f"{version} is older than {inst.get('version')}: add --yes to downgrade"
            )
    cfg = config_mod.load(home, dotenv=False)
    port = port_of(cfg)
    why_not = "--foreground" if args.foreground else host.systemd()
    if why_not:
        print(
            f"Update {label}: Kranto is not run by systemd here ({why_not}), so restart it "
            "yourself:"
        )
        if to == "previous":
            print("  stop Kranto; reinstall the previous version (RUNBOOK 6.3); kranto up")
        else:
            w = wheels_in(releases_dir(home) / to, tag_version(to))
            print(
                f"  stop 'kranto serve' (Ctrl-C)\n  uv tool install --force --python 3.12 "
                f"--with-executables-from the server,the page --with {w['kranto']} "
                f"--with {w['kranto.page']} {w['kranto']}\n  kranto up --foreground"
            )
        return 0
    busy = _busy_line(host, port)
    if not args.yes:
        if not host.stdin_tty:
            print(
                f"Update {label}"
                + (f" ({busy})" if busy else "")
                + ": not a terminal, re-run with --yes"
            )
            return 1
        ask = (
            f"Update {label}. {busy}: wait for it, then update? [Y/n] "
            if busy and args.when == "after-build"
            else f"Update {label}" + (f", stopping {busy}" if busy else "") + "? [Y/n] "
        )
        if input(ask).strip().lower() not in ("", "y", "yes"):
            print("nothing changed")
            return 1
    try:
        started = launch(
            home,
            to,
            when=args.when,
            port=port,
            unit=host_unit(host),
            keep=ucfg.keep_backups,
            ignore_pids=(os.getpid(),),
        )
    except LaunchError as exc:
        raise KrantoError(str(exc)) from exc
    print(
        f"Update {label}: the helper runs as {started['unit']} "
        f"(journalctl --user -u {started['unit']})"
    )
    final = tail_update(home)
    return UPDATE_EXIT.get(final, 4)


# -- the command ------------------------------------------------------------------------------


def versions() -> dict[str, str | None]:
    """The installed version (None: not installed), under ``kranto``: one distribution holds
    the server and the page. It is whichever distribution provides the ``kranto`` package (an
    install from before the rename names it otherwise, ``legacy.DISTS``); a git install says
    X.Y.Z+1.devN+g<commit>."""
    from importlib.metadata import PackageNotFoundError, packages_distributions, version

    for dist in (packages_distributions().get("kranto") or [])[:1] + [product.DIST, *legacy.DISTS]:
        try:
            return {"kranto": version(dist)}
        except PackageNotFoundError:
            continue
    return {"kranto": None}


def version_line(v: dict[str, str | None] | None = None) -> str:
    """``kranto 0.7.0``."""
    v = v or versions()
    return f"kranto {v.get('kranto') or 'not installed'}"


# the one line a stranger reads first (B, Codex 10, Gemini 6: "Watch topics,
# build what converges. One app: the watcher, the build loop and the UI.")
PITCH = (
    "Kranto reads the sources you pick, tells you each day what happened and what it "
    "suggests, and drafts the post about it for you to approve."
)
# left out of kranto --help (they still run): a build's traces and the evals are for whoever
# works on Kranto; cub is listed only once the home's config turns cubs.developer on
HIDDEN_COMMANDS = frozenset({"trace", "eval"})
DEVELOPER_COMMANDS = frozenset({"cub"})


class _Sub(argparse._SubParsersAction):
    """Subcommands kranto --help does not list (``hidden``)."""

    hidden: frozenset[str] = frozenset()

    def add_parser(self, name, **kw):
        if name in self.hidden:
            kw.pop("help", None)  # argparse lists a subcommand only when it has help
        return super().add_parser(name, **kw)


def build_parser(developer: bool = False) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kranto", description=PITCH)
    p.add_argument("--version", action="version", version=version_line())
    p.add_argument(
        "--home",
        help=f"the kranto home (default: ${KRANTO_HOME_ENV}, else the one "
        "kranto up or kranto adopt recorded, else ~/.kranto)",
    )
    p.register("action", "parsers", _Sub)
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    hidden = HIDDEN_COMMANDS | (frozenset() if developer else DEVELOPER_COMMANDS)
    setattr(sub, "hidden", hidden)  # noqa: B010 - _Sub's

    s = sub.add_parser(
        "up", help="make the home if needed, install and start the service, open the browser"
    )
    s.add_argument("--port", type=int, help=f"default {DEFAULT_PORT}, or the home's own")
    s.add_argument("--no-browser", action="store_true", help="print the URL instead")
    s.add_argument(
        "--foreground", action="store_true", help="serve here instead of installing kranto.service"
    )
    s.add_argument(
        "--adopt",
        action="store_true",
        help="rewrite and restart the unit even when another install's command runs it "
        "(without it, up from a checkout or a second tool leaves that unit alone)",
    )
    s.set_defaults(func=cmd_up)

    from . import wizard

    wizard.add_parser(sub)

    s = sub.add_parser("serve", help="the server and its scheduler (what the service runs)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument(
        "--port", type=int, help=f"default: the port in notify.base_url, else {DEFAULT_PORT}"
    )
    s.add_argument("--allow-host", action="append", metavar="NAME")
    s.add_argument(
        "--no-scheduler", action="store_true", help="serve only: nothing is read on a schedule"
    )
    s.add_argument("--no-loop", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("down", help="stop the service")
    s.add_argument(
        "--disable",
        action="store_true",
        help="also keep it from starting at boot ('kranto up' turns it back on)",
    )
    s.set_defaults(func=cmd_down)
    s = sub.add_parser("uninstall", help="stop and remove the service; your data stays")
    s.add_argument("--home", help="the kranto home (default: the one kranto up recorded)")
    s.add_argument(
        "--linger-off",
        action="store_true",
        help="also turn off lingering (your user's services stop when you log out)",
    )
    s.add_argument(
        "--program", action="store_true", help="also remove the program (uv tool uninstall kranto)"
    )
    s.add_argument(
        "--data",
        action="store_true",
        help="also delete the data (the home, the page's own folder, "
        "~/.config/kranto, the cache) after "
        "you type the home's path",
    )
    s.add_argument("--confirm", metavar="PATH", help="with --data: the home's path, for a script")
    s.set_defaults(func=cmd_uninstall)
    s = sub.add_parser("paths", help="where this install keeps things, with sizes")
    s.add_argument(
        "which",
        nargs="?",
        choices=["examples", "plugin"],
        help="examples: only the folder of Kranto's own post writers (kranto cub add "
        "$(kranto paths examples)/newsletter); plugin: Kranto's plugin for Claude "
        'Code (claude --plugin-dir "$(kranto paths plugin)")',
    )
    s.set_defaults(func=cmd_paths)
    s = sub.add_parser(
        "archive",
        help="write the record of the features that left Kranto to "
        "<home>/archive: one page and a JSON file each; it "
        "only reads your data",
    )
    s.add_argument("--out", help="write here instead of <home>/archive")
    s.add_argument("--json", action="store_true", help="print what was written as JSON")
    s.set_defaults(func=cmd_archive)
    s = sub.add_parser(
        "assistant",
        help="your own Claude Code or Codex with Kranto: what is set "
        "up, Kranto's files in its home, a global install shown "
        "first",
    )
    s.add_argument(
        "cmd",
        nargs="?",
        choices=["show", "setup", "global"],
        default="show",
        help="show (the default): what is set up and the install lines; setup: "
        "write Kranto's files for Codex into Kranto's home (AGENTS.md, "
        ".agents/skills, .codex); global: your harness's own install, shown "
        "first",
    )
    s.add_argument(
        "harness",
        nargs="?",
        choices=["claude", "codex"],
        help="global's harness: claude (the plugin) or codex (the server and the skills)",
    )
    s.add_argument("--yes", action="store_true", help="global: make the change shown")
    s.add_argument("--dry-run", action="store_true", help="setup: show what it would write")
    s.set_defaults(func=cmd_assistant)
    s = sub.add_parser("status", help="the service, what runs next, spend")
    s.set_defaults(func=cmd_status)
    s = sub.add_parser("logs", help="the service's journal")
    s.add_argument("-n", "--lines", type=int, default=100)
    s.add_argument("--no-follow", action="store_true")
    s.set_defaults(func=cmd_logs)
    s = sub.add_parser(
        "doctor",
        help="check this install: the model key, the service and its "
        "PATH, the assistants, the sandbox, the databases",
    )
    s.add_argument(
        "--embedder",
        action="store_true",
        help="also load the embedding model (slow; downloads it the first time)",
    )
    s.add_argument(
        "--routes",
        action="store_true",
        help="only read every page the running server serves, once, on your data "
        "(read-only; what kranto update checks before it keeps a new version): "
        "exit 1 when one answers 500 or does not answer",
    )
    s.add_argument("--port", type=int, help="--routes: the server's port (default: this home's)")
    s.add_argument("--json", action="store_true", help="--routes: the result as JSON")
    s.set_defaults(func=cmd_doctor)
    s = sub.add_parser(
        "report",
        help="write an error's report (what Send this error sends: its "
        "id, Kranto's own code lines, the version, the OS, the "
        "doctor's summary) to one file and print its path",
    )
    s.add_argument(
        "error_id",
        nargs="?",
        help="the error's id, as the page or the list says it (default: the newest)",
    )
    s.add_argument(
        "--no-doctor",
        action="store_true",
        help="use the last doctor's summary instead of running the doctor now",
    )
    s.set_defaults(func=cmd_report)

    s = sub.add_parser(
        "mcp",
        help="Kranto's own MCP server on stdio, for your Claude Code and other "
        "clients (claude mcp add kranto -- kranto mcp)",
    )
    s.add_argument(
        "--url", help="the running Kranto (default: this home's, on 127.0.0.1); loopback only"
    )
    s.add_argument(
        "--term",
        metavar="SESSION",
        help="an Open in Claude Code session's tools (Kranto's reads and proposals), "
        "for continuing it in your own Claude Code",
    )
    s.add_argument(
        "--compact",
        action="store_true",
        help="only the few generic tools (kranto_read, kranto_verbs, kranto_act, …): "
        "for a client that loads every tool on every turn, as Codex does",
    )
    s.add_argument(
        "--console",
        metavar="HARNESS",
        help="run for the console in Kranto's page (its own token; Activity says "
        "the harness: claude, codex)",
    )
    s.set_defaults(func=cmd_mcp)
    s = sub.add_parser(
        "term",
        help="Open in Claude Code's sessions: list, open one here with the page's limits, end one",
    )
    s.add_argument("rest", nargs=argparse.REMAINDER, help="list | open SESSION | end SESSION")
    s.set_defaults(func=cmd_term)

    s = sub.add_parser("open", help="sign a browser in: prints (or opens) a one-time link")
    s.add_argument("--no-browser", action="store_true", help="print the link instead")
    s.set_defaults(func=cmd_open)

    s = sub.add_parser(
        "token",
        help="who may act: the local tokens of the UI, kranto mcp, the "
        "command line and named agents (values stay in their "
        "files)",
    )
    s.add_argument("cmd", choices=("list", "add", "rotate", "revoke", "actions", "path"))
    s.add_argument("name", nargs="?", help="agent:<name> (or a door: ui, mcp, cli)")
    s.add_argument(
        "--actions",
        help="add/actions: the actions it may run, comma-separated "
        "(default: everything kranto mcp may, confirm-class ones "
        "with confirm)",
    )
    s.add_argument("--note", help="add: a few words on what it is for")
    s.set_defaults(func=cmd_token)

    s = sub.add_parser(
        "cub",
        help="the small programs Kranto runs in a sandbox, such as its post "
        "writers (add, list, inspect, update, stop, resume, remove, "
        "dry, log, run, check)",
    )
    s.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="add FOLDER-OR-GIT-URL [--ref R] | list | inspect ID | enable ID | "
        "disable ID | dry ID KIND | live ID KIND | stop ID | resume ID | "
        "update ID [--apply JOB] | remove ID [--purge] | log ID | run ID JOB | "
        "check PATH | stopfile [--set|--clear] | jobs",
    )
    s.set_defaults(func=cmd_cub)

    s = sub.add_parser(
        WATCH,
        help="the watcher's own commands on this home: topics, sources, run, search, "
        "websearch, ideas, provider, news, … (kranto watch --help lists them)",
        add_help=False,
    )
    s.add_argument("rest", nargs=argparse.REMAINDER, help="COMMAND [ARGS] (kranto watch --help)")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser(
        "trace",
        help="agent traces: an assistant session's turns and tool calls, its cost and "
        "where it failed",
    )
    s.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="list [--since 7d] [--state error] | show session:ID [--errors] "
        "[--span ID [--raw]] [--json] | export session:ID --otlp URL "
        "[--content]",
    )
    s.set_defaults(func=cmd_trace)

    s = sub.add_parser(
        "eval", help="evaluate Kranto: the frozen eval set, its free replay, the scorecards"
    )
    s.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="set build|grow|show [--from DB] | replay | scorecards | baseline CARD",
    )
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("adopt", help="switch an older installation to Kranto, in place")
    s.add_argument(
        "-w", "--workspace", help=f"the older install's workspace (default {legacy.WORKSPACE})"
    )
    s.add_argument(
        "--loop-home",
        help=f"the older install's page folder (default ${paths.LOOP_HOME_ENV}, else "
        f"{legacy.LOOP_HOME})",
    )
    s.add_argument("--backups", help="where backups go (default <workspace>-backups)")
    s.add_argument("--port", type=int, help=f"default {DEFAULT_PORT}")
    s.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    s.add_argument("--yes", action="store_true", help="do not ask")
    s.add_argument("--no-service", action="store_true", help="everything but the systemd units")
    s.set_defaults(func=cmd_adopt)

    s = sub.add_parser(
        "update",
        help="update to the new release: back up, install, restart, check, roll back on failure",
    )
    s.add_argument(
        "--check",
        action="store_true",
        help="only check: stage the new release's wheels, print the status line "
        "(exit 10 when an update is available)",
    )
    s.add_argument("--to", help="a release tag (v0.6.2, a nightly v0.7.0-dev12), even an older one")
    s.add_argument(
        "--when", default="after-build", choices=("after-build", "now"), help=argparse.SUPPRESS
    )
    s.add_argument(
        "--channel",
        choices=("stable", "nightly", "main"),
        help="check this channel instead of the configured one",
    )
    s.add_argument("--rollback", action="store_true", help="go back to the previous version")
    s.add_argument(
        "--cancel", action="store_true", help="let go of an update that is still waiting"
    )
    s.add_argument("--yes", action="store_true", help="do not ask")
    s.add_argument(
        "--foreground",
        action="store_true",
        help="Kranto is not run by systemd: stage and print the steps",
    )
    s.set_defaults(func=cmd_update)
    s = sub.add_parser(
        "telemetry",
        help="usage reports: the mode (off, local, basic, detailed), "
        "today's report, what was sent, the field list",
    )
    s.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="[status [--json]] | show [DAY] [--wire] | show --sent [DAY] | off | "
        "local | basic | detailed | docs | schema",
    )
    s.set_defaults(func=cmd_telemetry)
    s = sub.add_parser(
        "settings",
        help="stable-defaults [--json]: what stays off on stable "
        "(a setting whose stable default keeps the old "
        "behaviour)",
    )
    s.add_argument("rest", nargs=argparse.REMAINDER, help="stable-defaults [--json]")
    s.set_defaults(func=cmd_settings)
    s = sub.add_parser(
        "backup", help="back up both databases, the configs, the unit and the tool's receipt"
    )
    s.add_argument("dir", nargs="?", help="where (default <home>/backups/manual-<time>)")
    s.set_defaults(func=cmd_backup)
    return p


def _help_developer(argv: Sequence[str] | None, host: Host | None) -> bool:
    """For --help (and no command): whether this home's config turns ``cubs.developer`` on
    (the cub shop's own gate); any doubt keeps the developer's commands out of the list."""
    words = list(sys.argv[1:] if argv is None else argv)
    explicit = words[words.index("--home") + 1] if "--home" in words[:-1] else None
    command = [w for w in words if not w.startswith("-") and w != explicit]
    if command or (words and not any(w in ("-h", "--help") for w in words)):
        return False  # a command's own parse: listed or not, it runs
    try:
        from .core.cubs import settings as cub_settings

        return cub_settings.developer(config_mod.load(kranto_home(explicit, host), dotenv=False))
    except Exception:  # noqa: BLE001 - help never fails for a home it cannot read
        return False


ALIAS_STAMP = "alias-notice"       # in the config folder: the day the old command last said so


def alias_notice(argv0: str | None = None, *, tty: bool | None = None,
                 user_home: Path | None = None, now: float | None = None) -> bool:
    """Run as the command's name from before the rename (``legacy.COMMAND``, the same program)
    on a terminal: say once a day that it is now this one (``legacy.alias_notice``, on stderr;
    a stamp in the config folder). Silent in scripts and pipes. True when it spoke."""
    argv0 = sys.argv[0] if argv0 is None else argv0
    if Path(argv0 or "").name != legacy.COMMAND:
        return False
    if not (sys.stderr.isatty() if tty is None else tty):
        return False
    folder = legacy.config_dir(Path(user_home or Path.home()))
    stamp = folder / ALIAS_STAMP
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    with contextlib.suppress(OSError):
        if stamp.read_text().strip() == today:
            return False
    print(legacy.alias_notice(), file=sys.stderr)
    with contextlib.suppress(OSError):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        stamp.write_text(today + "\n")
    return True


def main(argv: Sequence[str] | None = None, host: Host | None = None) -> int:
    if argv is None:
        alias_notice(user_home=host.home if host is not None else None)
    words = list(sys.argv[1:] if argv is None else argv)
    watch = _split_watch(words)
    if watch is not None:
        args = build_parser().parse_args(watch[0])
        args.rest = watch[1]
    else:
        args = build_parser(developer=_help_developer(argv, host)).parse_args(argv)
    if host is None:  # Kranto's own gh (--fetch-gh), for this run and its children
        from .ghfetch import bin_dir

        own = bin_dir(Path.home())
        if (own / "gh").is_file() and str(own) not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = f"{os.environ.get('PATH', '')}{os.pathsep}{own}"  # a fallback
    try:
        return args.func(args, host or Host())
    except (KrantoError, ConfigError) as exc:
        print(f"Kranto: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
