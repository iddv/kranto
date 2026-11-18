"""``kranto setup``: the install wizard (the owner's decisions of 2026-10-17).

Sections, in order: **machine** (the checks, ``preflight``), **home** (the home, the port, the
service mode), **caps** (offered, never set unless typed: no spend cap is the default),
**watching** (the model key), **usage** (usage reports: asked once, Enter sends nothing;),
**start**, **topics**, **sources** (X's own app, the one source that needs
something of the person's first; 5.1), **ready** (Claude Code for the
console, what Kranto costs, the usage answer; then the first read), **finish**: the three things
are the model key, the first topic and ready, as Welcome asks them. The builds' sections
(GitHub, repositories, the build caps) left with builds (CUT); their flags are still accepted,
and ignored with one line. **claude** (the console's long-lived Claude login token, once
"building") is asked by its own name, ``kranto setup claude`` or ``assistant``.
``kranto setup <section>`` runs one. Each question has a default (the current value, else the
code's), a flag and an answers-file key; precedence is flag > answers file > the last run's
``setup.json`` > default. ``--yes`` (or no terminal) asks nothing.

Every write goes through the writer that already owns the file: ``kranto.make_home``,
``kranto.remember_home``, ``tokens.Store.ensure_doors``, ``kranto.install_unit``,
``setup.write_config_values`` (kranto.yaml), the page's ``write_setting`` (loop.yaml: only
``build.claude_command``, which the console's launcher reads), ``setup.write_env_key`` (the
key), and the running server's ``POST /api/topics`` (the cli door token). This module holds
no YAML of its own. A section writes at its end, never mid-question; a re-run with Enter
everywhere writes nothing and says ``kept``. Secrets are read with getpass, from stdin or from
a file, never from a flag's value, and never reach ``setup.json``, ``--json`` or an error line.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import platform
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from . import config as config_mod
from . import launcher, legacy, preflight, product
from .launcher import FAIL, OK, WARN, Host, KrantoError

SECTIONS = ("machine", "home", "claude", "caps", "watching", "search", "usage",
            "start", "topics", "sources", "ready", "finish")
# the Settings pages: `kranto setup <page>` runs that page's parts, in SECTIONS'
# order; each part's own name stays a section of its own (kranto setup caps, usage...).
# topics is the app's Topics, not a Settings page: `kranto setup topics`, as before
PAGES = {"watching": ("watching", "search"), "sources": ("sources",), "assistant": ("claude",),
         "spend": ("caps",), "privacy": ("usage",), "system": ("machine", "home", "start")}
ALIASES = {"service": "home"}
# asked by its own name only, never in a full run (the console's login token: Welcome's Ready
# says how Claude Code signs in); a token flag (--claude-token-file) runs it in a full run too
BY_NAME_ONLY = ("claude",)
# the builds' flags (CUT): accepted so a script or an older install.sh that passes them still
# runs, and ignored with one line
RETIRED_FLAGS = ("cap_daily", "cap_build", "github", "adopt", "adopt_org")
RETIRED_WORDS = "builds are not part of Kranto any more"
SETUP_FILE = "setup.json"
CLAUDE_ENV = "claude.env"
CLAUDE_DROPIN = "20-claude-token.conf"
# what the wizard may show as a suggestion for a cap; never written unless
# the person types it (the owner, 2026-10-17: uncapped is the default)
SUGGESTED = {"watch_monthly_usd": 10, "x_monthly_usd": 50}
# the watcher's model, in the order offered (MP D12): Claude Code's login is never the default
WATCH = ("anthropic", "openrouter", "endpoint", "claude_code", "later")
PROVIDER_OF = {"anthropic": "anthropic", "openrouter": "openrouter", "endpoint": "openai_compat",
               "claude_code": "claude_code"}
WATCH_OF = {v: k for k, v in PROVIDER_OF.items()}
EXIT_OK, EXIT_CHECK, EXIT_ANSWER, EXIT_DOWN = 0, 1, 2, 3
# D12: macOS is watcher-only, served in the foreground. A launchd agent is not written: nobody
# here can test one on a Mac, and an agent that fails at login says nothing, where a printed
# command does.
MACOS_SERVICE = "macOS has no systemd, and Kranto does not write a launchd agent yet"
MACOS_NOTE = ("macOS: Kranto installs the watcher only. Watching your topics works here; the "
              "console (Open in Claude Code) needs Linux's bubblewrap sandbox, so it stays off "
              "(brb.enabled: false), and bwrap, Claude Code and systemd are not checked. Kranto "
              "serves in the foreground.")


def this_system() -> str:
    return platform.system()


class AnswerError(KrantoError):
    """An answer the wizard cannot use (exit 2)."""


# -- input and output ---------------------------------------------------------------------------


@dataclass
class IO:
    """The terminal, replaceable in tests: ``ask`` and ``secret`` read a line, ``say`` prints.
    ``interactive`` False: nothing is asked, every answer is its default."""
    interactive: bool
    quiet: bool = False                       # --json: the lines go to stderr
    ask_fn: object = None                     # None: input() and getpass.getpass()
    secret_fn: object = None
    lines: list = field(default_factory=list)

    def say(self, text: str = "") -> None:
        self.lines.append(text)
        print(text, file=sys.stderr if self.quiet else sys.stdout, flush=True)

    def ask(self, prompt: str, default: str = "") -> str:
        if not self.interactive:
            return default
        got = (self.ask_fn or input)(f"  {prompt} [{default}]: ").strip()
        return got or default

    def secret(self, prompt: str) -> str:
        return (self.secret_fn or getpass.getpass)(f"  {prompt}: ").strip() \
            if self.interactive else ""


@dataclass
class Run:
    """One run's state: what the sections decided, wrote and kept."""
    host: Host
    args: argparse.Namespace
    io: IO
    answers: dict
    last: dict
    home: Path | None = None
    port: int = launcher.DEFAULT_PORT
    service: str = "foreground"
    written: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    decided: dict = field(default_factory=dict)
    started: bool = False
    answering: bool = False
    child: subprocess.Popen | None = None
    new_home: bool = False
    doctor: dict | None = None
    system: str = "Linux"                     # platform.system(); Darwin: watcher only (D12)

    @property
    def macos(self) -> bool:
        return self.system == "Darwin"

    def wrote(self, what: str) -> None:
        self.written.append(what)
        self.io.say(f"  wrote {what}")

    def keep(self, what: str) -> None:
        self.kept.append(what)
        self.io.say(f"  kept  {what}")

    def pick(self, key: str, flag, default):
        """flag > answers file > the last run's answer > default."""
        if flag is not None:
            return flag
        node = self.answers
        for k in key.split("."):
            node = node.get(k) if isinstance(node, dict) else None
        if node is not None:
            return node
        node = self.last
        for k in key.split("."):
            node = node.get(k) if isinstance(node, dict) else None
        return default if node is None else node


def load_answers(path: str | None) -> dict:
    """An answers file, JSON or YAML (read, never written here). Secrets are never in it: a
    key or a token is a file path."""
    if not path:
        return {}
    p = Path(path).expanduser()
    try:
        text = p.read_text()
    except OSError as exc:
        raise AnswerError(f"cannot read the answers file {p}: {exc.strerror}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AnswerError(f"{p} is not JSON or YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise AnswerError(f"{p} is not a mapping of answers")
    return data


def read_last(home: Path) -> dict:
    try:
        return (json.loads((home / SETUP_FILE).read_text()) or {}).get("answers") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def secret_from(run: Run, file_flag: str | None, stdin_flag: bool, what: str) -> str:
    """A secret from a file (mode 0600 checked), stdin, or getpass; "" when none was given."""
    if file_flag:
        p = Path(file_flag).expanduser()
        try:
            if p.stat().st_mode & 0o077:
                raise AnswerError(f"{p} is readable by other users: chmod 600 it first")
            text = p.read_text()
        except OSError as exc:
            raise AnswerError(f"cannot read {p}: {exc.strerror}") from exc
        import re
        lines = [ln.strip() for ln in text.splitlines()
                 if ln.strip() and not ln.lstrip().startswith("#")]
        first = lines[0].removeprefix("export ").strip() if lines else ""
        m = re.fullmatch(r"[A-Z_][A-Z0-9_]*=(.+)", first)
        return (m.group(1) if m else first).strip().strip("'\"")
    if stdin_flag:
        return sys.stdin.readline().strip()
    return run.io.secret(what)


def _usd(text) -> float | None:
    """A cap as typed: a number of dollars, or none."""
    if text is None:
        return None
    s = str(text).strip().lstrip("$").lower()
    if s in ("", "none", "no", "null", "off"):
        return None
    try:
        v = float(s)
    except ValueError as exc:
        raise AnswerError(f"'{text}' is not a number of dollars (or none)") from exc
    if v <= 0:
        raise AnswerError("a cap is more than $0 (none means no cap)")
    return v


def _money(v: float | None) -> str:
    return "none" if v is None else f"{v:g}"


# -- the sections ---------------------------------------------------------------------------------


def machine(run: Run) -> int:
    run.io.say("System › This machine")
    try:
        run.port = int(run.pick("port", run.args.port, run.port))
    except (TypeError, ValueError) as exc:
        raise AnswerError("the port is a number") from exc
    given = run.pick("claude", run.args.claude, None)

    def check() -> list:
        got = preflight.run(run.host, port=run.port, claude=given, system=run.system)
        run.checks = [i.as_dict() for i in got]
        return got

    items = check()
    skip = set(run.pick("skip", run.args.skip, []) or [])
    for i in items:
        run.io.say(f"{i.status:<5} {i.name:<14} {i.detail}")
        if i.fix and i.status != OK:
            run.io.say(f"{'':<20}  {i.fix}")
    # gh files "File a Kranto issue": fetched only when asked for by --fetch-gh
    if run.args.fetch_gh and fetch_gh(run, items):
        items = check()
    if not run.macos:
        exe, how = preflight.find_claude(run.host, given)
        if exe and how in ("given", "found"):
            run.decided["claude"] = exe
            if config_mod.config_path(launcher.kranto_home(run.args.home, run.host)) is not None:
                claude_command(run, launcher.kranto_home(run.args.home, run.host))
    missing = [i for i in items if i.status == FAIL and i.name not in skip]
    if not missing:
        return EXIT_OK
    if not run.io.interactive:
        for i in missing:
            off = f"off until it is there: {i.needs}" if i.needs else ""
            run.io.say(f"skip  {i.name:<14} {off}".rstrip())
        return EXIT_OK
    while missing:
        run.io.say(f"{len(missing)} missing. Kranto never runs sudo itself.")
        run.io.say("  1 I ran the commands in another terminal, check again")
        run.io.say("  2 skip for now (what needs it stays off until 'kranto setup machine' "
                   "finds it)")
        run.io.say("  3 stop here")
        choice = run.io.ask("choice", "1")
        if choice == "2":
            return EXIT_OK
        if choice == "3":
            return EXIT_CHECK
        items = check()
        missing = [i for i in items if i.status == FAIL and i.name not in skip]
        for i in items:
            run.io.say(f"{i.status:<5} {i.name:<14} {i.detail}")
    return EXIT_OK


def fetch_gh(run: Run, items: list) -> bool:
    """``--fetch-gh`` (D4): when gh is missing, a pinned, checksum-checked gh into Kranto's own
    folder. The distribution's command is printed first (machine's list); this is asked after
    it, unless ``--yes``; ``--no-fetch-gh`` never asks. True when gh was installed."""
    from . import ghfetch

    gh = next((i for i in items if i.name == "gh"), None)
    missing = gh is not None and gh.detail.startswith("not installed")
    own = ghfetch.bin_dir(run.host.home) / "gh"
    stale = bool(run.args.fetch_gh) and own.is_file() and \
        ghfetch.VERSION not in (run.host.sh(str(own), "--version").stdout or "")
    if not missing and not stale:       # gh is there; --fetch-gh replaces an older own copy
        return False
    want = run.pick("fetch_gh", run.args.fetch_gh, None)
    if want is False:
        return False
    if not run.io.interactive and not want:
        run.io.say(f"{'':<20}  or 'kranto setup machine --fetch-gh': gh {ghfetch.VERSION} from "
                   "github.com/cli/cli into Kranto's own folder, checksum-checked")
        return False
    if run.io.interactive:
        yes = run.io.ask(f"fetch gh {ghfetch.VERSION} from github.com/cli/cli into "
                         f"{launcher.tilde(ghfetch.bin_dir(run.host.home), run.host.home)} instead "
                         "(its checksum checked; your package manager's gh updates with the "
                         "system, this one does not)? (y/n)", "y" if want else "n")
        if not yes.lower().startswith("y"):
            run.decided["fetch_gh"] = False
            return False
    try:
        path = ghfetch.fetch(run.host.home)
    except ghfetch.FetchError as exc:
        run.io.say(f"{FAIL:<5} {'gh':<14} {exc}")
        return False
    os.environ["PATH"] = f"{os.environ.get('PATH', '')}{os.pathsep}{path.parent}"
    run.decided["fetch_gh"] = True
    run.wrote(f"{launcher.tilde(path, run.host.home)} (gh {ghfetch.VERSION}, SHA-256 checked "
              "against the release and Kranto's pin)")
    return True


def claude_command(run: Run, the_home: Path) -> None:
    """``build.claude_command`` in loop.yaml: the Claude Code binary Kranto runs when PATH has
    none (``--claude PATH``, or found where an installer put it). The console (the page's
    ``claude_cli``) reads it, under its old name; the unit's PATH gets its folder."""
    want = run.decided.get("claude")
    found = _loop_file(the_home)
    if not want or found is None:
        return
    loop_file, LoopConfig, write_setting = found
    current = (LoopConfig(loop_file.parent).get("build") or {}).get("claude_command")
    if current == want:
        run.keep(f"build.claude_command {want}")
        return
    write_setting(loop_file, ("build", "claude_command"), want)
    run.wrote(f"{loop_file} (build.claude_command {want})")


def _loop_file(the_home: Path):
    """``(loop.yaml, Config, write_setting)`` for this home's page; None when the page is off
    or the page is not installed (or has no settings writer)."""
    try:
        from kranto.page.host_api import Config as LoopConfig
        from kranto.page.host_api import write_setting
    except ImportError:
        return None
    cfg = config_mod.load(the_home, dotenv=False)
    if not cfg.brb.enabled:
        return None
    from . import paths
    return paths.LoopLayout(paths.loop_home(cfg.brb.loop_home)).settings, LoopConfig, \
        write_setting


def home(run: Run) -> int:
    run.io.say("System › Where Kranto lives")
    host = run.host
    recorded = launcher.kranto_home(run.args.home, host)
    where = run.pick("home", run.args.home, str(recorded))
    shown = launcher.tilde(Path(where).expanduser(), host.home)
    where = Path(run.io.ask("home (settings, library)", shown))
    the_home = where.expanduser().resolve() if not str(where).startswith("~/") else \
        (host.home / str(where)[2:]).resolve()
    existing = config_mod.config_path(the_home) is not None
    current = launcher.DEFAULT_PORT
    if existing:
        try:
            current = launcher.port_of(config_mod.load(the_home, dotenv=False))
        except config_mod.ConfigError as exc:
            raise AnswerError(f"{the_home}'s config does not load: {exc}") from exc
    try:
        port = int(run.io.ask("port (127.0.0.1 only)", str(run.pick("port", run.args.port,
                                                                    current))))
    except ValueError as exc:
        raise AnswerError("the port is a number") from exc
    if not 1024 <= port <= 65535:
        raise AnswerError("the port is a number from 1024 to 65535")
    why_not = MACOS_SERVICE if run.macos else host.systemd()
    want = run.pick("service", run.args.service, "systemd" if why_not is None else "foreground")
    if want == "systemd" and why_not is not None:
        run.io.say(f"  systemd is not usable here ({why_not}): serving in the foreground")
        want = "foreground"
    if why_not is None and run.args.service is None:
        yes = run.io.ask("run as a service that starts at boot and keeps running after you log "
                         "out? (y/n)", "y" if want == "systemd" else "n").lower()
        want = "systemd" if yes.startswith("y") else "foreground"
    if want not in ("systemd", "foreground"):
        raise AnswerError("service is systemd or foreground")
    run.home, run.port, run.service, run.new_home = the_home, port, want, not existing
    run.decided.update(home=launcher.tilde(the_home, host.home), port=port, service=want)
    for w in launcher.make_home(the_home, port, host.home):
        run.wrote(w)
    if existing and port != current:
        from .setup import write_config_values
        cfg_path = config_mod.config_path(the_home)
        write_config_values(cfg_path, {("notify", "base_url"): f"http://127.0.0.1:{port}"})
        run.wrote(f"{cfg_path} (notify.base_url port {current} -> {port})")
    pointer = launcher.pointer_path(host.home)
    before = pointer.read_text().strip() if pointer.exists() else None
    folder_loose = pointer.parent.exists() and pointer.parent.stat().st_mode & 0o077
    if before != str(the_home) or folder_loose:
        launcher.remember_home(the_home, host.home)
        run.wrote(f"{pointer} (this home)")
    else:
        run.keep(f"home {launcher.tilde(the_home, host.home)} · port {port} · service {want}")
    made = launcher.token_store(host).ensure_doors()
    if made:
        run.wrote(f"the {', '.join(made)} tokens in {launcher.token_store(host).root}")
    if run.macos:
        cfg_path = config_mod.config_path(the_home)
        if config_mod.load(the_home, dotenv=False).brb.enabled:
            from .setup import write_config_values
            write_config_values(cfg_path, {("brb", "enabled"): False})
            run.wrote(f"{cfg_path} (brb.enabled false: no console sandbox on macOS)")
        else:
            run.keep("brb.enabled false (watching only on macOS)")
    else:
        claude_command(run, the_home)
    return EXIT_OK


def claude(run: Run) -> int:
    """Your Claude plan for the console (BL; setup.md, "Open in Claude Code"): the long-lived
    Claude login token ``claude setup-token`` prints, kept in Kranto's own store at 0600
    (the page's ``claude_login``) and handed to each console session by pipe, never in an
    environment. No drop-in and no restart: every launch reads it. An API key pasted here goes,
    as before, to a 0600 file the unit loads (a key you give the unit on purpose). The token is
    never printed. Builds left (CUT); the console keeps this, so it is asked by its own name
    (``kranto setup claude`` or ``assistant``), never in a full run."""
    run.io.say("Assistant › Your Claude plan for the console")
    host = run.host
    conf_dir = launcher.private_config_dir(host.home)
    env_file = conf_dir / CLAUDE_ENV
    dropin = host.unit_dir / f"{launcher.UNIT}.d" / CLAUDE_DROPIN
    if run.macos:
        run.io.say("  skipped on macOS: the console needs Linux's sandbox")
        return EXIT_OK
    if run.args.no_claude_token:
        run.keep("no Claude login token (the console uses Claude Code's own sign-in)")
        return EXIT_OK
    kept = launcher.claude_kept(host)
    given = run.args.claude_token_file or run.args.claude_token_stdin
    if (kept or (env_file.exists() and dropin.exists())) and not given:
        run.keep("your Claude plan: the Claude login token Kranto keeps" if kept else
                 f"the long-lived Claude token ({env_file}, loaded by {dropin.name})")
        return EXIT_OK
    if not given:
        run.io.say("  The console runs on your Claude plan: a long-lived login token from "
                   "'claude setup-token'. Kranto keeps it at mode 600 and hands it to each "
                   "session by pipe. Without it, the console uses Claude Code's own sign-in.")
        yes = run.io.interactive and run.io.ask(
            "use your Claude plan now? Kranto runs 'claude setup-token' here: sign in in the "
            "browser it opens, then paste the token it prints (y/n)", "y").lower().startswith("y")
        if not yes:
            run.io.say("  skipped: 'kranto setup claude' asks again")
            return EXIT_OK
        exe = launcher.configured_claude(run.home) if run.home else None
        exe = exe or host.which("claude")
        if not exe:
            raise AnswerError("Claude Code is not installed: install it, then run 'kranto setup "
                              "claude' again")
        if host.tty([exe, "setup-token"]) != 0:
            run.io.say("  'claude setup-token' did not finish; paste a token if it printed one")
    token = secret_from(run, run.args.claude_token_file, run.args.claude_token_stdin,
                        "the token it printed (not shown)")
    if not token.strip() and not given:
        run.io.say("  no token pasted: skipped ('kranto setup claude' asks again)")
        return EXIT_OK
    from .setup import SetupError, check_key_shape
    try:
        token = check_key_shape(token)
    except SetupError as exc:
        raise AnswerError(f"the Claude token: {exc}") from exc
    var = "ANTHROPIC_API_KEY" if token.startswith("sk-ant-api") else "CLAUDE_CODE_OAUTH_TOKEN"
    if var == "CLAUDE_CODE_OAUTH_TOKEN":
        at = launcher.keep_claude_login(host, token)
        run.wrote(f"{at} (mode 600: the console runs on your Claude plan, by pipe)")
        return EXIT_OK
    if run.service != "systemd":
        raise AnswerError("an API key for the console goes into Kranto's unit, which runs only as "
                          "a service; for your Claude plan, paste the token 'claude "
                          "setup-token' prints")
    tmp = env_file.with_name(f".{env_file.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{var}={token}\n")
    os.replace(tmp, env_file)
    run.wrote(f"{env_file} (mode 600)")
    at = launcher._h(env_file, host.home)
    text = ("[Service]\n# the long-lived Claude token, written by kranto setup; the console gets "
            f"it by pipe, never in its environment\nEnvironmentFile=-{at}\n")
    dropin.parent.mkdir(parents=True, exist_ok=True)
    if not dropin.exists() or dropin.read_text() != text:
        dropin.write_text(text)
        run.wrote(str(dropin))
        run.decided["unit_changed"] = True
    return EXIT_OK


def caps(run: Run) -> int:
    """Offered, never set unless typed (the owner, 2026-10-17)."""
    run.io.say("Spend › Caps")
    cfg = config_mod.load(run.home, dotenv=False)
    current = {"watch_monthly_usd": cfg.budget.monthly_usd}
    if current["watch_monthly_usd"] is None:
        from . import setup as su
        run.io.say("  No spend cap is set: Kranto spends what watching costs, with no limit. "
                   + su.COST + " A cap stops watching's model calls when it is reached; set "
                   "one here if you want it (suggested: $10 a month), or leave it empty for none.")
    flags = {"watch_monthly_usd": run.args.cap_watch, "x_monthly_usd": run.args.cap_x}
    words = {"watch_monthly_usd": "watching a month, USD",
             "x_monthly_usd": "X reads a month, USD (X bills your developer account)"}
    # the X cap only once X is connected (or asked for by flag); never set unless typed
    offer_x = run.args.cap_x is not None or _x_connected(cfg)
    current["x_monthly_usd"] = cfg.x.monthly_usd
    want = {}
    for k in ("watch_monthly_usd", "x_monthly_usd"):
        if k == "x_monthly_usd" and not offer_x:
            continue
        dflt = _money(_usd(run.pick(f"caps.{k}", flags[k], _money(current[k]))))
        hint = "" if current[k] is not None else f" (none, or e.g. {SUGGESTED[k]})"
        want[k] = _usd(run.io.ask(words[k] + hint, dflt))
    run.decided["caps"] = {k: v for k, v in want.items()}
    if want["watch_monthly_usd"] != current["watch_monthly_usd"]:
        from .setup import write_config_values
        path = config_mod.config_path(run.home)
        write_config_values(path, {("budget", "monthly_usd"): want["watch_monthly_usd"]})
        run.wrote(f"{path} (budget.monthly_usd {_money(current['watch_monthly_usd'])} -> "
                  f"{_money(want['watch_monthly_usd'])})")
    if "x_monthly_usd" in want and want["x_monthly_usd"] != current["x_monthly_usd"]:
        from .setup import write_config_values
        path = config_mod.config_path(run.home)
        write_config_values(path, {("x", "monthly_usd"): want["x_monthly_usd"]})
        run.wrote(f"{path} (x.monthly_usd {_money(current['x_monthly_usd'])} -> "
                  f"{_money(want['x_monthly_usd'])})")
    unchanged = [k for k in want if want[k] == current[k]]
    if unchanged:
        run.keep("caps " + ", ".join(f"{k} {_money(want[k])}" for k in unchanged))
    return EXIT_OK


def _sh_run(run: Run):
    """``providers.detect``'s ``run``: a command through the host, as (exit code, stdout)."""
    def go(cmd):
        r = run.host.sh(*cmd, timeout=15)
        return r.returncode, r.stdout or ""
    return go


def _watch_answer(run: Run, key: str):
    node = run.answers.get("watch")
    return node.get(key) if isinstance(node, dict) else None


def watching(run: Run) -> int:
    """The watcher's model through ``providers.detect``, ``test`` and ``choose``, offered in this
    order: an Anthropic key (the Claude API),
    OpenRouter, another OpenAI-compatible endpoint, Claude Code's login (an explicit choice,
    never the default, its terms said and agreed to here), later. What the config names now
    is the default, above the last run's answer: a choice made since in the browser stays."""
    run.io.say("Watching › Provider and key")
    from . import providers
    from . import setup as su
    menu = run.io.interactive and run.args.watch is None
    # Claude Code is looked at only for the menu (its row says its state); choosing it tests it
    found = providers.detect(run.home, run=_sh_run(run) if menu else lambda cmd: (127, ""))
    cur = found["current"]
    now = WATCH_OF.get(cur["choice"], "endpoint")
    cc = found["claude_code"]
    has = {w: found[PROVIDER_OF[w]]["key_set"] for w in ("anthropic", "openrouter", "endpoint")}
    working = now == "claude_code" or cur["key_set"]
    key_file = run.args.watch_key_file or _watch_answer(run, "key_file")
    key = ""
    if key_file or run.args.watch_key_stdin:
        key = secret_from(run, key_file and str(key_file), run.args.watch_key_stdin,
                          "the model key")
        try:
            key = su.check_key_shape(key)
        except su.SetupError as exc:
            raise AnswerError(f"the model key: {exc}") from exc
    if working:
        dflt = now
    elif key:
        dflt = "anthropic" if key.startswith("sk-ant-") else "openrouter"
    elif run.io.interactive:            # offered first; --yes with no key stays later
        dflt = next((w for w in ("anthropic", "openrouter", "endpoint") if has[w]), "anthropic")
    else:
        dflt = "later"
    answered = run.args.watch if run.args.watch is not None else _watch_answer(run, "provider")
    if answered is None:
        answered = now if working else run.pick("watch.provider", None, dflt)
    choice = str(answered)
    if menu:
        def tag(w):
            bits = ["now"] if w == now and working else []
            if w in has and has[w] and not (w == now and working):
                bits.append(f"${found[PROVIDER_OF[w]]['env']} found")
            return f" ({', '.join(bits)})" if bits else ""
        who = ("not installed" if not cc["installed"] else
               f"Claude Code {cc['version'] or ''}".strip()
               + (", signed in" if cc["logged_in"] else ", not signed in"))
        run.io.say(f"  1 Claude API: an Anthropic key{tag('anthropic')}")
        run.io.say(f"  2 OpenRouter: one key, every cheap model{tag('openrouter')}")
        run.io.say(f"  3 another OpenAI-compatible endpoint{tag('endpoint')}")
        run.io.say(f"  4 Claude Code's login ({who}){tag('claude_code')} *")
        run.io.say("  5 later: no key now (Kranto reads nothing until one is set)")
        for line in _wrap("* " + providers.CLAUDE_CODE_TERMS, 84):
            run.io.say("    " + line)
        n = str(WATCH.index(choice) + 1) if choice in WATCH else "5"
        got = run.io.ask("choice", n)
        choice = WATCH[int(got) - 1] if got in ("1", "2", "3", "4", "5") else got
    if choice not in WATCH:
        raise AnswerError(f"watch is one of {', '.join(WATCH)}")
    run.decided["watch"] = {"provider": choice}
    if choice == "later":
        run.keep("watching later: no model chosen (" + (
            f"{cur['label']} is set up" if working else "no key set")
            + "); 'kranto setup watching' chooses one")
        return EXIT_OK
    name = PROVIDER_OF[choice]
    label = providers.LABELS[name]
    if choice == "claude_code":
        return _watch_claude_code(run, now)
    base = None
    if choice == "endpoint":
        here = cur["endpoint"] if now == "endpoint" else ""
        given = run.pick("watch.base_url", run.args.watch_url, None)
        if given is None:
            given = run.io.ask("the endpoint's base URL (https://…/v1)", here or "")
        if not given:
            raise AnswerError("another endpoint needs its base URL (--watch-url or "
                              "watch.base_url)")
        try:
            base = su.check_base_url(str(given))
        except su.SetupError as exc:
            raise AnswerError(str(exc)) from exc
        run.decided["watch"]["base_url"] = base
    env = found[name]["env"]
    in_file = _env_has(run.home / ".env", env)
    if not key and has.get(choice) and in_file and run.io.interactive and run.io.ask(
            f"replace the key in ${env}? (y/n)", "n").lower().startswith("y"):
        key = run.io.secret("the new key (not shown)")
        try:
            key = su.check_key_shape(key) if key else ""
        except su.SetupError as exc:
            raise AnswerError(str(exc)) from exc
    same_base = base is None or (cur["endpoint"] or "").rstrip("/") == base.rstrip("/")
    if not key and choice == now and working and same_base and in_file:
        run.keep(f"watching: {label} (${env} in {run.home / '.env'})")
        return EXIT_OK
    if not key and has.get(choice) and not in_file:
        key = os.environ.get(env, "").strip()     # the shell's: the service reads only .env
    if not key:
        page = {"anthropic": "; https://console.anthropic.com/settings/keys",
                "openrouter": "; https://openrouter.ai/keys"}.get(choice, "")
        key = run.io.secret(f"{label} key (not shown{page})")
        if not key:
            run.io.say(f"  no key given: watching stays {cur['label'] if working else 'off'} "
                       "('kranto setup watching')")
            return EXIT_OK
        try:
            key = su.check_key_shape(key)
        except su.SetupError as exc:
            raise AnswerError(str(exc)) from exc
    result = providers.choose(run.home, name, key=key, base_url=base,
                              keep_failed=not run.io.interactive)
    run.io.say(f"{OK if result['ok'] else WARN:<5} {label:<14} {result['test']['detail']}")
    if not result["ok"] and result["models"] is None:
        if not run.io.ask("keep it anyway? (y/n)", "n").lower().startswith("y"):
            run.io.say("  nothing written: 'kranto setup watching' tries again")
            return EXIT_OK
        result = providers.choose(run.home, name, key=key, base_url=base, keep_failed=True)
    return _chose(run, name, result, wrote_key=True)


def _watch_claude_code(run: Run, now: str) -> int:
    """Claude Code's login, only when its terms were agreed to: asked in a terminal, or
    ``--watch-accept-terms`` / ``watch.terms: true`` (the owner's D2)."""
    from . import providers
    from . import setup as su
    if now == "claude_code":
        run.keep("watching: Claude Code's login (billed to your Claude plan)")
        return EXIT_OK
    for line in _wrap(providers.CLAUDE_CODE_TERMS, 86):
        run.io.say("  " + line)
    agreed = bool(run.args.watch_accept_terms) or _watch_answer(run, "terms") is True
    if not agreed and run.io.interactive:
        agreed = run.io.ask("use your Claude Code login for watching anyway? (y/n)",
                            "n").lower().startswith("y")
    if not agreed:
        if run.io.interactive:
            run.io.say("  not chosen: watching stays as it is ('kranto setup watching')")
            return EXIT_OK
        raise AnswerError("Claude Code's login is chosen only with its terms agreed to: "
                          "--watch-accept-terms (or watch.terms: true in the answers file)")
    run.decided["watch"]["terms"] = True
    try:
        result = providers.choose(run.home, "claude_code", terms=True)
    except su.SetupError as exc:
        raise AnswerError(str(exc)) from exc
    run.io.say(f"{OK if result['ok'] else WARN:<5} {'Claude Code':<14} "
               f"{result['test']['detail']}")
    if not result["ok"]:
        run.io.say("  nothing written: 'kranto setup watching' tries again")
        return EXIT_OK
    return _chose(run, "claude_code", result, wrote_key=False)


def _chose(run: Run, name: str, result: dict, *, wrote_key: bool) -> int:
    """What ``providers.choose`` wrote, said; a running Kranto takes it at its next start."""
    from . import providers
    if not result["changed"]:
        run.keep(f"watching: {providers.LABELS[name]} (nothing changed)")
        return EXIT_OK
    if wrote_key and result["env"]:
        run.wrote(f"{run.home / '.env'} (${result['env']}, mode 600)")
    m = result["models"]
    run.wrote(f"{config_mod.config_path(run.home)} (llm.provider {name}, judge {m['judge']}, "
              f"reason {m['reason']}" + (f", llm.base_url {result['base_url']}"
                                         if result["base_url"] else "") + ")")
    if launcher.port_in_use(run.port):
        run.io.say("  Kranto is running: it watches with this from its next start "
                   "('kranto down', then 'kranto up'); Settings › Watching switches a running "
                   "Kranto at once")
    return EXIT_OK


SEARCH_WORDS = ("Live search for the scout, idea cards and the weekly editor: they propose and "
                "judge from dated web results, not from a model's memory. Exa's free mode works "
                "with no account; a key (a free Exa account has $10 of credit a month) gives you "
                "your own limits. None: every caller says its results are from model memory "
                "and may be stale.")


def search(run: Run) -> int:
    """Live search: ``search.provider`` and its key. Enter, ``--yes`` and the
    answers file without ``search`` keep what is set (Exa's free mode on a new home, with
    nothing written). ``--search`` and ``--search-key-file|-stdin`` answer without asking."""
    from . import setup as su
    from .websearch import KEY_ENV
    from .websearch import setup as wsetup

    run.io.say("Live search")
    cfg = config_mod.load(run.home, dotenv=True)
    current = cfg.search.provider
    flag = getattr(run.args, "search", None)
    picked = run.pick("search", flag, current)
    if run.io.interactive and flag is None and "search" not in run.answers:
        for line in _wrap(SEARCH_WORDS):
            run.io.say("  " + line)
        for c in wsetup.CHOICES:
            run.io.say(f"    {c:<10} {wsetup.CHOICE_LABELS[c]}")
        picked = run.io.ask("Live search", current).strip().lower()
    if picked not in wsetup.CHOICES:
        raise AnswerError(f"search is one of {', '.join(wsetup.CHOICES)}")
    key = None
    env = KEY_ENV.get(picked)
    if env:
        has = bool(os.environ.get(env)) or _env_has(run.home / ".env", env)
        if getattr(run.args, "search_key_file", None) or getattr(run.args, "search_key_stdin",
                                                                  False):
            key = secret_from(run, run.args.search_key_file, run.args.search_key_stdin,
                              f"{env}") or None
        elif run.io.interactive and not has:
            optional = " (Enter: Exa's free mode, no key)" if picked == "exa" else ""
            key = run.io.secret(f"{env}{optional}") or None
        if picked in ("brave", "tavily") and key is None and not has:
            raise AnswerError(f"{wsetup.CHOICE_LABELS[picked]} needs ${env}: give it with "
                              "--search-key-file or --search-key-stdin")
    run.decided["search"] = picked
    if picked == current and key is None:
        run.keep(f"live search: {wsetup.CHOICE_LABELS[picked]}"
                 + (" in its free mode (no key)" if picked == "exa" and not (
                     os.environ.get(KEY_ENV["exa"]) or _env_has(run.home / ".env",
                                                               KEY_ENV["exa"])) else ""))
        return EXIT_OK
    try:
        result = wsetup.choose(run.home, picked, key=key, keep_failed=True)
    except su.SetupError as exc:
        raise AnswerError(str(exc)) from exc
    run.io.say(f"{OK if result['test']['ok'] else WARN:<5} {'live search':<14} "
               f"{result['test']['detail']}")
    if key is not None and env:
        run.wrote(f"{run.home / '.env'} (${env}, mode 600)")
    if result["changed"]:
        run.wrote(f"{config_mod.config_path(run.home)} (search.provider {picked})")
    if launcher.port_in_use(run.port):
        run.io.say("  Kranto is running: it searches with this from its next start "
                   "('kranto down', then 'kranto up'); Settings switches a running Kranto at once")
    return EXIT_OK


def _env_has(path: Path, var: str) -> bool:
    try:
        return any(ln.strip().removeprefix("export ").partition("=")[0].strip() == var
                   and ln.partition("=")[2].strip() for ln in path.read_text().splitlines())
    except OSError:
        return False


USAGE_CHOICES = {"1": "basic", "2": "detailed", "3": "off"}


def usage(run: Run) -> int:
    """Usage reports, asked once (the owner's D1: opt-in, Enter sends nothing).
    Unanswered stays ``local``: counted on this machine, never sent. ``--telemetry`` and the
    answers file's ``telemetry`` answer it without asking; ``--yes`` leaves it unanswered."""
    from . import telemetry

    run.io.say("Privacy & access › Usage reports")
    eff = telemetry.effective(run.home)
    if eff.why in (telemetry.DNT, telemetry.ENV_MODE):
        run.decided["telemetry"] = eff.mode
        run.keep(f"usage reports {eff.mode}: set by {eff.why} in the environment")
        return EXIT_OK
    # flag > answers file > the file's own answer: never the last run's, which a later choice
    # in Settings › Privacy & access or 'kranto telemetry' has replaced
    flag = getattr(run.args, "telemetry", None)
    picked = flag if flag is not None else run.answers.get("telemetry")
    if picked is None and run.io.interactive and not eff.answered:
        for line in _wrap(telemetry.SUMMARY):
            run.io.say("  " + line)
        run.io.say("    1  basic: the daily report and error reports (recommended)")
        run.io.say("    2  detailed: also a random id you can reset")
        run.io.say("    3  nothing: count nothing")
        run.io.say(f"  What Kranto sends: {telemetry.DOCS_LINK}")
        run.io.say("  (also kranto telemetry docs, and Settings › Privacy & access)")
        got = run.io.ask("Send usage reports? 1/2/3, Enter sends nothing until you decide", "")
        picked = USAGE_CHOICES.get(got.strip(), got.strip() or None)
    if picked in (None, "") and not eff.answered:
        run.keep("usage reports: not answered, so nothing is sent (counted on this machine "
                 "only; 'kranto telemetry' or Settings › Privacy & access to choose)")
        return EXIT_OK
    picked = picked or eff.mode
    if picked not in telemetry.MODES:
        raise AnswerError(f"telemetry is one of {', '.join(telemetry.MODES)}")
    run.decided["telemetry"] = picked
    if eff.answered and picked == eff.mode:
        run.keep(f"usage reports {picked}: {telemetry.MEANING[picked]}")
        return EXIT_OK
    try:
        telemetry.set_mode(run.home, picked)
    except telemetry.TelemetryError as exc:
        raise AnswerError(str(exc)) from exc
    run.wrote(f"{config_mod.config_path(run.home)} (telemetry.mode {picked}: "
              f"{telemetry.MEANING[picked]})")
    return EXIT_OK


def _wrap(text: str, width: int = 88) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width)


def start(run: Run) -> int:
    run.io.say("System › Starting")
    host = run.host
    want = bool(run.pick("start", False if run.args.no_start else None, True))
    run.decided["start"] = want
    if not want:
        run.keep("not started ('kranto up' or 'kranto setup start' starts it)")
        return EXIT_OK
    port = run.port
    if run.service == "systemd":
        unit, changed = launcher.install_unit(
            host, launcher.render_unit(run.home, launcher.kranto_exe(host), port, host.home)
        )
        (run.wrote if changed else run.keep)(str(unit))
        active = (
            host.sh("systemctl", "--user", "is-active", launcher.UNIT).stdout.strip() == "active"
        )
        if not active and launcher.port_in_use(port):
            raise AnswerError(f"port {port} is already in use; choose another with --port")
        restart = (changed or run.decided.get("unit_changed")) and active
        cmds = (["daemon-reload"],) if changed or run.decided.get("unit_changed") else ()
        cmds += (["enable", "--now", launcher.UNIT],) if not active else ()
        cmds += (["restart", launcher.UNIT],) if restart else ()
        for cmd in cmds:
            r = host.sh("systemctl", "--user", *cmd, timeout=120)
            if r.returncode != 0:
                raise KrantoError(
                    f"systemctl --user {' '.join(cmd)} failed: {(r.stderr or r.stdout).strip()}"
                )
        if not run.args.no_linger and not active:
            import pwd

            if (
                host.sh("loginctl", "enable-linger", pwd.getpwuid(os.getuid()).pw_name).returncode
                != 0
            ):
                run.io.say("  note: loginctl enable-linger failed; Kranto stops when you log out")
        run.started = True
    else:
        if launcher.port_in_use(port):
            home = Path(run.home or launcher.kranto_home(None, host))
            if not launcher.serves_this_home(host, port, home):
                raise AnswerError(
                    f"127.0.0.1:{port} already answers, but not as Kranto serving "
                    f"{launcher.tilde(home, host.home)} (another program, or another Kranto "
                    "home); choose another port with --port"
                )
            run.io.say(f"  127.0.0.1:{port} already answers as this home's Kranto: using it")
        else:
            log = run.home / "serve.log"
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            run.child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "kranto.launcher",
                    "--home",
                    str(run.home),
                    "serve",
                    "--port",
                    str(port),
                ],
                stdout=fd,
                stderr=fd,
                stdin=subprocess.DEVNULL,
            )
            os.close(fd)
            signal.signal(signal.SIGTERM, _stop)  # from here SIGTERM stops the server too
            run.started = True
            run.io.say(f"  serving in the foreground (its log: {log})")
        run.io.say(
            "  Kranto runs while this terminal does; to start it again later: "
            f"kranto --home {launcher.tilde(run.home, host.home)} serve --port {port}"
        )
    run.answering = launcher._wait_up(host, port, 90)
    if not run.answering:
        run.io.say(
            f"  Kranto started but http://127.0.0.1:{port}/ is not answering yet; see "
            + ("'kranto logs'" if run.service == "systemd" else str(run.home / "serve.log"))
        )
        return EXIT_DOWN
    run.io.say(f"  Kranto is running: http://127.0.0.1:{port}/")
    return EXIT_OK


def topics(run: Run) -> int:
    run.io.say("Sources › Topics")
    given = [t for t in (run.args.topic or [])]
    planned = []
    for t in given:
        name, _, text = t.partition(":")
        planned.append({"name": name.strip(), "text": text.strip()})
    if not given:
        for t in run.answers.get("topics") or []:
            if isinstance(t, dict) and t.get("name"):
                planned.append({"name": str(t["name"]), "text": str(t.get("text") or "")})
    if run.io.interactive and not given:
        run.io.say(
            "  A topic is a name and one sentence in your own words. Sources are proposed "
            "and ticked in the browser."
        )
        while True:
            name = run.io.ask("topic name (empty to stop)", "")
            if not name:
                break
            planned.append({"name": name, "text": run.io.ask("one sentence", "")})
    if not planned:
        run.keep("topics: none added here (Welcome › Topics in the browser)")
        return EXIT_OK
    if not run.answering:
        run.io.say(
            "  topics are added through the running Kranto: start it, then 'kranto setup topics'"
        )
        return EXIT_OK
    have = {
        t.get("name", "").strip().lower()
        for t in _api(run, "GET", "/api/topics").get("topics", [])
        if isinstance(t, dict)
    }
    for t in planned:
        if t["name"].strip().lower() in have:
            run.keep(f'topic "{t["name"]}"')
            continue
        _api(run, "POST", "/api/topics", {"name": t["name"], "description": t["text"]})
        run.wrote(f'topic "{t["name"]}"')
    return EXIT_OK


def ready(run: Run) -> int:
    """Welcome's Ready, in the terminal: Claude Code for the console (installed and
    signed in, or not installed and how to get it: Kranto works without it), what Kranto costs on
    the person's own key, the usage-reports answer; then, with Kranto answering and a source
    watched, the first read (``POST /run/ingest``, the press Welcome's Start reading makes)."""
    from . import setup as su
    from . import telemetry

    run.io.say("Ready")
    if not run.macos:
        item = next(
            (
                i
                for i in preflight.run(
                    run.host, port=run.port, system=run.system, port_check=lambda _p: None
                )
                if i.name == "claude"
            ),
            None,
        )
        if item is not None and item.status == OK:
            run.io.say(
                "  Claude Code     installed and signed in: the console beside every page uses it"
            )
        elif item is not None and "not installed" in item.detail:
            run.io.say(
                "  Claude Code     not installed; Kranto works without it. For the console: "
                f"{su.CONSOLE_INSTALL}, then run claude once to sign in, then 'kranto setup "
                "ready' checks again"
            )
        else:
            run.io.say(
                "  Claude Code     installed, not signed in; Kranto works without it. For "
                "the console: run claude once to sign in"
            )
    cap = config_mod.load(run.home, dotenv=False).budget.monthly_usd if run.home else None
    run.io.say(f"  What it costs   {su.cost_words(cap)}")
    eff = telemetry.effective(run.home)
    run.io.say(
        "  Usage reports   "
        + (
            f"{eff.mode}: {telemetry.MEANING.get(eff.mode, '')}"
            if eff.answered
            else "nothing is sent unless you choose ('kranto telemetry' or Settings › Privacy)"
        )
    )
    want = bool(run.pick("read", False if getattr(run.args, "no_read", False) else None, True))
    if not want or not run.answering:
        run.keep(
            "first read: at Kranto's next read" if run.answering else "first read: when Kranto runs"
        )
        return EXIT_OK
    try:
        sources = _api(run, "GET", "/api/sources").get("sources") or []
    except KrantoError:
        sources = []
    if not any(isinstance(x, dict) and x.get("review") == "approved" for x in sources):
        run.keep("first read: once a source is watched (tick the proposals in the browser)")
        return EXIT_OK
    try:
        _api(run, "POST", "/run/ingest")
    except KrantoError as exc:
        run.io.say(f"  first read not started: {exc}")
        return EXIT_OK
    run.decided["read"] = True
    run.wrote("the first read: started (its first brief follows it)")
    return EXIT_OK


X_COST = (
    "X is paid: X bills your own developer account $0.005 for each post kranto reads "
    "($0.001 for your bookmarks and likes). A typical install (10 topics, one list of "
    "about 200 accounts) is estimated at about $46 a month at the defaults; Kranto counts "
    "every read on Settings › Spend, and your Developer Console is the bill."
)


def _x_connected(cfg) -> bool:
    """Whether an X account is connected in this home (read from the library, read-only)."""
    import sqlite3

    db = cfg.db_path
    if not db.exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT e.event FROM connections c JOIN connection_events e ON "
                "e.connection_id = c.id WHERE c.provider = 'x' AND e.event IN ('connected', "
                "'needs_login', 'disconnected') ORDER BY e.id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return bool(row) and row[0] in ("connected", "needs_login")


def sources(run: Run) -> int:
    """X, the one source that needs something of the person's own before it can be added
    : their developer app's client id, kept through the running Kranto. X has
     no device flow, so the sign-in itself is finished in the browser, from 127.0.0.1."""
    run.io.say("Sources › X")
    cfg = config_mod.load(run.home, dotenv=False)
    if _x_connected(cfg):
        run.keep("X: connected (Settings › Sources › Accounts › X)")
        return EXIT_OK
    given = run.args.x_client_id or (
        (run.answers.get("sources") or {}).get("x_client_id")
        if isinstance(run.answers.get("sources"), dict)
        else None
    )
    callback = f"http://127.0.0.1:{run.port}/connections/x/callback"
    if not given:
        if not run.io.interactive:
            run.keep(
                "sources: other sources are proposed and ticked in the browser; X is not "
                "connected ('kranto setup sources --x-client-id ID', or Settings › "
                "Connections › X)"
            )
            return EXIT_OK
        run.io.say(
            "  Most sources need nothing from you: they are proposed for your topics "
            "and ticked in the browser."
        )
        for line in _wrap(X_COST):
            run.io.say("  " + line)
        if (
            not run.io.ask("read X with your own X developer app? (y/n)", "n")
            .lower()
            .startswith("y")
        ):
            run.keep("sources: X not connected (Settings › Sources › Accounts › X, any time)")
            return EXIT_OK
        for n, step in enumerate(
            (
                "Sign in at console.x.com with your X account and accept the Developer Agreement.",
                "Buy credits and set a spending limit for the billing cycle.",
                "Create an app named the server (the use-case text is on Settings › Sources › "
                "Accounts › X).",
                f"User authentication settings: type Native App, permissions Read, callback "
                f"{callback}, website https://github.com/iddv/kranto. Save.",
                "Keys and tokens: copy the OAuth 2.0 Client ID (a Native App has no secret).",
            ),
            1,
        ):
            for i, line in enumerate(_wrap(step, 84)):
                run.io.say(f"  {n}. {line}" if i == 0 else f"     {line}")
        given = run.io.ask("Client ID (empty: later)", "").strip()
        if not given:
            run.keep("sources: X not connected (Settings › Sources › Accounts › X, any time)")
            return EXIT_OK
    if not run.answering:
        run.io.say(
            "  X's client id is kept through the running Kranto: start it, then 'Kranto "
            "setup sources'"
        )
        return EXIT_OK
    try:
        _api(run, "POST", "/api/connections/x/credentials", {"client_id": given.strip()})
    except KrantoError as exc:
        raise AnswerError(f"X's client id was not saved: {exc}") from exc
    run.decided["sources"] = {"x": "client saved"}
    run.wrote("X's client id (kept encrypted with the connections, data/secrets/)")
    run.io.say(
        f"  X has no device sign-in. Open http://127.0.0.1:{run.port}/#/settings/"
        "connections/x in your browser (127.0.0.1, not localhost), click Connect and "
        "allow read access. Then add X sources from Add source."
    )
    return EXIT_OK


def _api(run: Run, method: str, path: str, body: dict | None = None) -> dict:
    """The running Kranto, as the command line (the cli door token): the one writer stays the
    server."""
    import httpx

    token = launcher.token_store(run.host).value("cli")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"http://127.0.0.1:{run.port}{path}"
    try:
        r = httpx.request(method, url, json=body, headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        raise KrantoError(f"Kranto did not answer {method} {path}: {type(exc).__name__}") from exc
    if r.status_code >= 400:
        raise KrantoError(f"Kranto answered {r.status_code} to {method} {path}")
    try:
        out = r.json()
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {"items": out}


def finish(run: Run) -> int:
    host = run.host
    checks = launcher.doctor_checks(run.home, host)
    run.doctor = {
        "ok": sum(c.status == OK for c in checks),
        "warn": sum(c.status == WARN for c in checks),
        "fail": sum(c.status == FAIL for c in checks),
        "failed": [c.name for c in checks if c.status == FAIL],
    }
    d = run.doctor
    run.io.say(
        f"  doctor: {d['ok']} ok, {d['warn']} warn, {d['fail']} FAIL"
        + (f" ({', '.join(d['failed'])})" if d["failed"] else "")
    )
    record(run)
    if run.answering and not run.args.json:
        launcher.offer_signin(
            run.home, host, "/#/welcome" if run.new_home else "/", run.args.no_browser
        )
    run.io.say("")
    run.io.say("Where things are   " + " · ".join(where(run)))
    run.io.say(
        "Next              kranto status · kranto doctor · kranto setup <section> · "
        "kranto uninstall"
    )
    return EXIT_OK


def where(run: Run) -> list[str]:
    h = run.host.home
    unit = run.host.unit_dir / launcher.UNIT
    return [
        f"{launcher.tilde(run.home, h)} (settings, library)",
        f"{launcher.tilde(launcher.pointer_path(h).parent, h)} (tokens)",
        *([launcher.tilde(unit, h)] if unit.is_file() else []),
        f"~/.local/share/uv/tools/{product.DIST} and ~/.local/bin/{product.COMMAND} (the "
        f"program; ~/.local/bin/{legacy.COMMAND} is the same command under its old name)",
    ]


def record(run: Run) -> None:
    """``<home>/setup.json``: the answers (never a secret) and when each changed. Rewritten only
    when an answer changed, so a re-run with Enter everywhere writes nothing."""
    if run.home is None:
        return
    path = run.home / SETUP_FILE
    try:
        old = json.loads(path.read_text())
    except (OSError, ValueError):
        old = {}
    answers = dict(old.get("answers") or {})
    merged = {
        **answers,
        **{
            k: (
                {**answers[k], **v}
                if isinstance(v, dict) and isinstance(answers.get(k), dict)
                else v
            )
            for k, v in run.decided.items()
        },
    }
    merged.pop("unit_changed", None)
    if merged == answers and path.exists():
        return
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = {
        **(old.get("changed") or {}),
        **{k: at for k, v in merged.items() if answers.get(k) != v},
    }
    from .launcher import versions

    text = (
        json.dumps(
            {"version": versions().get("kranto"), "answers": merged, "changed": changed},
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    tmp = path.with_name(f".{SETUP_FILE}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    run.wrote(str(path))


def locate(run: Run) -> None:
    """For one section: the home, port and service the last setup chose, asked of nobody."""
    host = run.host
    the_home = launcher.kranto_home(run.args.home, host)
    if config_mod.config_path(the_home) is None:
        raise AnswerError(f"{the_home} is not a Kranto home yet: run 'kranto setup' first")
    run.home = the_home
    run.port = run.args.port or launcher.port_of(config_mod.load(the_home, dotenv=False))
    unit = host.unit_dir / launcher.UNIT
    run.service = run.pick(
        "service",
        run.args.service,
        "systemd" if unit.exists() and host.systemd() is None else "foreground",
    )
    run.answering = (
        launcher._wait_up(host, run.port, 2) if launcher.port_in_use(run.port) else False
    )


RUNNERS = {
    "machine": machine,
    "home": home,
    "claude": claude,
    "caps": caps,
    "watching": watching,
    "search": search,
    "usage": usage,
    "start": start,
    "topics": topics,
    "sources": sources,
    "ready": ready,
    "finish": finish,
}


def _install_login(args, io: IO) -> None:
    """``--github-token-file``: the GitHub login install.sh's device flow left for Kranto to keep
    as its connection. Kranto keeps no GitHub connection since the cut, so the file is removed
    unread (a token must not stay on disk for nothing); gh's own login is what Kranto uses."""
    f = getattr(args, "github_token_file", None)
    if not f:
        return
    with contextlib.suppress(OSError):
        Path(f).expanduser().unlink()
    io.say(
        "  the GitHub login install.sh left was not kept (Kranto keeps no GitHub connection "
        "any more; gh's own login files Kranto issues); its file was removed"
    )


def cmd_setup(args, host: Host) -> int:
    for flag in ("watch_key", "claude_token", "search_key"):
        if getattr(args, flag, None):
            print(
                f"kranto setup: --{flag.replace('_', '-')} would put a secret in your shell "
                f"history; use --{flag.replace('_', '-')}-file or --{flag.replace('_', '-')}"
                "-stdin",
                file=sys.stderr,
            )
            return EXIT_ANSWER
    interactive = (
        not (args.yes or args.answers or args.json) and bool(host.stdin_tty) and sys.stdout.isatty()
    )
    io = IO(interactive=interactive, quiet=args.json)
    try:
        answers = load_answers(args.answers)
    except AnswerError as exc:
        print(f"kranto setup: {exc}", file=sys.stderr)
        return EXIT_ANSWER
    recorded = launcher.kranto_home(args.home, host)
    run = Run(
        host=host, args=args, io=io, answers=answers, last=read_last(recorded), system=this_system()
    )
    only = ALIASES.get(args.section, args.section)
    todo = (
        [s for s in SECTIONS if s in PAGES[only]]
        if only in PAGES
        else [only]
        if only
        else list(SECTIONS)
    )
    io.say(
        " ".join(x for x in ("kranto", launcher.versions().get("kranto"), "setup") if x)
        + (f": {only}" if only else "")
        + (
            ". Enter keeps the value in [brackets]; Ctrl-C stops (a section writes only at "
            "its end)."
            if interactive
            else " (non-interactive: every answer is the kept value or its default)"
        )
    )
    if run.macos:
        io.say(MACOS_NOTE)
    retired = [f"--{f.replace('_', '-')}" for f in RETIRED_FLAGS if getattr(args, f, None)]
    if retired:
        io.say(f"  ignored: {', '.join(retired)} ({RETIRED_WORDS})")
    _install_login(args, io)
    code = EXIT_OK
    try:
        if only and not {"machine", "home"} & set(todo):
            locate(run)
        for name in todo:
            token = getattr(args, "claude_token_file", None) or getattr(
                args, "claude_token_stdin", None
            )
            if not only and name in BY_NAME_ONLY and not token:
                continue  # the console's login token: asked by its own name
            io.say("")
            got = RUNNERS[name](run)
            if got == EXIT_CHECK:
                code = EXIT_CHECK
                break
            if got == EXIT_DOWN:
                code = EXIT_DOWN
        if only and "finish" not in todo:
            record(run)
    except AnswerError as exc:
        io.say(f"kranto setup: {exc}")
        code = EXIT_ANSWER
    except KeyboardInterrupt:
        io.say("\nstopped: what the finished sections wrote stays; nothing else changed")
        _end_child(run)
        return 130
    if not run.written and code == EXIT_OK:
        io.say("Done; nothing changed.")
    if args.json:
        print(json.dumps(summary(run, code), indent=1))
    if run.child is not None:  # the server this run started stays in the foreground
        io.say("Kranto serves in the foreground: Ctrl-C stops it")
        sys.stdout.flush()
        with contextlib.suppress(KeyboardInterrupt):
            run.child.wait()
        _end_child(run)
    return code


def _stop(*_) -> None:
    """SIGTERM (a closed terminal, a script) stops the wizard as Ctrl-C does."""
    raise KeyboardInterrupt


def _end_child(run: Run) -> None:
    """Stop the foreground server this run started (it gets 90 s, as the unit's stop does),
    and give SIGTERM back its default."""
    if run.child is not None:
        if run.child.poll() is None:
            run.child.terminate()
            try:
                run.child.wait(timeout=90)
            except subprocess.TimeoutExpired:
                run.child.kill()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)


def summary(run: Run, code: int) -> dict:
    """``--json``: an allowlist of fields, never a link, a key or a token."""
    return {
        "exit": code,
        "home": str(run.home) if run.home else None,
        "port": run.port,
        "service": run.service,
        "written": list(run.written),
        "kept": list(run.kept),
        "checks": run.checks,
        "started": run.started,
        "answering": run.answering,
        "doctor": run.doctor,
        "answers": {k: v for k, v in run.decided.items() if k != "unit_changed"},
    }


def add_parser(sub) -> None:
    s = sub.add_parser(
        "setup",
        help="the install wizard: checks this machine, asks what it "
        "cannot find, writes the settings, starts Kranto",
    )
    s.add_argument(
        "section",
        nargs="?",
        choices=(*PAGES, *(x for x in SECTIONS[:-1] if x not in PAGES), *ALIASES),
        help="one Settings page's part: watching (and search, live search), sources "
        "(X's app), assistant (claude: the console's Claude login token), spend "
        "(caps), privacy (usage reports), system (machine, home or service, "
        "start); topics; ready (Claude Code for the console, the cost, the "
        "first read); or one of those parts by its own name",
    )
    s.add_argument(
        "--yes",
        action="store_true",
        help="ask nothing: every answer is the kept value or its default",
    )
    s.add_argument(
        "--answers",
        metavar="FILE",
        help="answers in a file (JSON or YAML; never a secret: keys are file paths)",
    )
    s.add_argument(
        "--json",
        action="store_true",
        help="one JSON object on stdout (never a link or a secret); implies --yes",
    )
    s.add_argument("--port", type=int)
    s.add_argument("--service", choices=("systemd", "foreground"))
    s.add_argument("--no-start", action="store_true", help="write everything, start nothing")
    s.add_argument(
        "--no-read",
        action="store_true",
        help="ready starts no first read (Kranto's next read is its first)",
    )
    s.add_argument("--no-browser", action="store_true", help="print the sign-in link")
    s.add_argument("--no-linger", action="store_true", help="do not turn lingering on")
    s.add_argument(
        "--claude",
        metavar="PATH",
        help="the Claude Code binary, when PATH has none "
        "(kept as build.claude_command; the "
        "console reads it)",
    )
    s.add_argument(
        "--fetch-gh",
        dest="fetch_gh",
        action="store_true",
        default=None,
        help="when gh is missing, fetch a pinned, checksum-checked gh into Kranto's own "
        "folder (asked first, unless --yes)",
    )
    s.add_argument(
        "--no-fetch-gh",
        dest="fetch_gh",
        action="store_false",
        default=None,
        help="never offer to fetch gh",
    )
    s.add_argument(
        "--skip",
        type=lambda v: [x.strip() for x in v.split(",") if x.strip()],
        help="missing checks to skip, e.g. bwrap,claude",
    )
    s.add_argument(
        "--claude-token-file",
        metavar="FILE",
        help="the console's long-lived Claude token (claude setup-token) in a 0600 file",
    )
    s.add_argument("--claude-token-stdin", action="store_true", help="the token on stdin")
    s.add_argument("--no-claude-token", action="store_true")
    s.add_argument("--claude-token", help=argparse.SUPPRESS)  # refused: shell history
    # the builds' flags (RETIRED_FLAGS): accepted, ignored with one line, never shown
    s.add_argument("--cap-daily", metavar="USD", help=argparse.SUPPRESS)
    s.add_argument("--cap-build", metavar="USD", help=argparse.SUPPRESS)
    s.add_argument("--github", help=argparse.SUPPRESS)
    s.add_argument("--adopt", action="append", help=argparse.SUPPRESS)
    s.add_argument("--adopt-org", help=argparse.SUPPRESS)
    s.add_argument(
        "--cap-watch", metavar="USD", help="watching a month; none: no cap (the default)"
    )
    s.add_argument(
        "--cap-x",
        metavar="USD",
        help="X reads a month; none: no cap (the default; offered once X is connected)",
    )
    s.add_argument(
        "--x-client-id",
        metavar="ID",
        help="your X developer app's OAuth 2.0 Client ID (public; a Native App has no secret)",
    )
    s.add_argument(
        "--watch",
        choices=WATCH,
        help="watching's provider: anthropic (Claude API), "
        "openrouter (OpenRouter), endpoint (Another endpoint, OpenAI-compatible), "
        "claude_code (Claude Code: your login; needs --watch-accept-terms), or later",
    )
    s.add_argument("--watch-url", metavar="URL", help="the endpoint (--watch endpoint)")
    s.add_argument(
        "--watch-accept-terms",
        action="store_true",
        help="--watch claude_code: you read its terms (kranto setup watching says "
        "them) and choose it anyway",
    )
    s.add_argument("--watch-key-file", metavar="FILE", help="the provider's key in a 0600 file")
    s.add_argument("--watch-key-stdin", action="store_true", help="the provider's key on stdin")
    s.add_argument("--watch-key", help=argparse.SUPPRESS)  # refused: shell history
    s.add_argument(
        "--search",
        choices=("exa", "brave", "tavily", "anthropic", "none"),
        help="live search for the scout, cards and the editor: exa (the default; "
        "its free mode needs no key), brave, tavily, anthropic (the watcher's "
        "Claude API key) or none",
    )
    s.add_argument(
        "--search-key-file",
        metavar="FILE",
        help="the search backend's key (EXA_API_KEY, BRAVE_API_KEY or "
        "TAVILY_API_KEY) in a 0600 file",
    )
    s.add_argument("--search-key-stdin", action="store_true", help="that key on stdin")
    s.add_argument("--search-key", help=argparse.SUPPRESS)  # refused: shell history
    s.add_argument("--github-token-file", metavar="FILE", help=argparse.SUPPRESS)  # removed
    s.add_argument(
        "--telemetry",
        choices=("off", "local", "basic", "detailed"),
        help="usage reports: off (Nothing), local (Local only), basic (Basic) or "
        "detailed (Detailed), as Settings › Privacy & access says them; left "
        "out: asked once, and Enter sends nothing",
    )
    s.add_argument("--topic", action="append", metavar="'NAME: one sentence'")
    s.set_defaults(func=cmd_setup)
