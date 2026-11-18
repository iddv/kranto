"""The ``kranto`` command (PLAN.md sections 1.1 to 1.7), offline: the home and its config,
the unit file, up/serve/status, doctor's prerequisite checks, and adopt's plan (dry run and
real, against a scratch copy of the pre-kranto layout). systemctl, claude, gh, bwrap and tmux
are fakes; nothing here starts a service, calls a model or touches the network."""

import io
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import time
import types
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import yaml

from kranto import config as config_mod
from kranto import launcher, memory
from kranto import legacy as legacy_mod
from kranto import store as store_mod
from kranto.launcher import FAIL, OK, WARN, Host
from kranto.store import Store

from . import brbfake


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")  # the frozen test clock (conftest)


class FakeMachine:
    """systemctl --user, loginctl, tmux, claude, gh and bwrap, recorded."""

    def __init__(self, *, systemd=True, active=None, tools=None, rc=None, tmux=False):
        self.calls: list[list[str]] = []
        self.systemd = systemd
        self.active = dict(active or {})
        self.enabled: dict[str, str] = {}
        self.tools = tools if tools is not None else {
            n: f"/usr/bin/{n}" for n in ("claude", "gh", "bwrap", "uv", "systemctl", "tmux")}
        self.rc = rc or {}
        self.tmux = tmux
        self.which_paths: list = []

    def run(self, cmd, timeout=30):
        self.calls.append(list(cmd))
        name = Path(cmd[0]).name
        if name == "systemctl":
            sub, rest = cmd[2], cmd[3:]
            if sub == "show-environment":
                return _cp(0 if self.systemd else 1, "", "Failed to connect to bus")
            if sub == "is-active":
                return _cp(0, self.active.get(rest[0], "inactive") + "\n")
            if sub == "is-enabled":
                return _cp(0, self.enabled.get(rest[0], "disabled") + "\n")
            if sub == "enable":
                self.active[rest[-1]] = "active"
                self.enabled[rest[-1]] = "enabled"
            if sub == "disable":
                self.active[rest[-1]] = "inactive"
                self.enabled[rest[-1]] = "disabled"
            return _cp(0)
        if name == "tmux":
            return _cp(0 if self.tmux else 1)
        return _cp(self.rc.get(name, 0), "", f"{name} says no" if self.rc.get(name) else "")

    def which(self, name, path=None):
        self.which_paths.append(path)
        return self.tools.get(name)


def _cp(rc, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def make_host(home, machine=None, *, login_home=None, status=None):
    machine = machine or FakeMachine()
    status = status if status is not None else {"version": "0.1.0", "scheduler": True,
                                                "paused": None, "lanes": {}}

    def http_get(url, timeout):
        return (200, json.dumps(status).encode()) if status != "down" else (503, b"")
    host = Host(run=machine.run, which=machine.which, home=home,
                login_home=login_home or home, http_get=http_get, stdin_tty=False,
                tty=lambda cmd, timeout=900: machine.calls.append(["tty", *cmd]) or 0)
    host.machine = machine
    return host


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    home = tmp_path / "u"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KRANTO_LOOP_HOME", raising=False)
    monkeypatch.delenv("KRANTO_HOME", raising=False)
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": False)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    return home


# -- the home, the config and the unit ----------------------------------------------------------


def test_a_new_home_is_a_workspace_with_the_loop_on(user_home):
    home = user_home / ".kranto"
    written = launcher.make_home(home, 8800, user_home)
    assert {Path(w).name for w in written} >= {"kranto.yaml", "loop.yaml"}
    cfg = config_mod.load(home, dotenv=False)
    assert cfg.brb.enabled and cfg.brb.loop_home == "~/.kranto/loop"
    assert cfg.brb.root is None                      # the builds' task folder: not for a new home
    assert cfg.notify.base_url == "http://127.0.0.1:8800" and launcher.port_of(cfg) == 8800
    assert cfg.llm.base_url == "https://openrouter.ai/api/v1"  # the llm section kept its own
    seed = yaml.safe_load((home / "loop" / "loop.yaml").read_text())
    # cards through the API, never the file (handover rule 4); no key of the builds
    assert seed == {"kranto": {"url": "http://127.0.0.1:8800"}}
    assert (home / "data").is_dir()
    # the task folder was the builds'; they left, and nothing reads it: no empty tasks/
    assert not (home / "tasks").exists()
    assert oct(home.stat().st_mode & 0o777) == "0o700"
    assert launcher.make_home(home, 8800, user_home) == []  # idempotent


def test_a_home_whose_loop_lives_elsewhere_gets_no_decoy_loop_or_tasks(user_home, tmp_path):
    """Review D-5: an adopted home (its brb section points at ~/kranto-loop and ~/tasks) was
    still given an empty loop/ with a loop.yaml nobody reads, and an empty tasks/."""
    home = user_home / "kb"
    config_mod.init_workspace(home)
    cfg_file = config_mod.config_path(home)
    cfg_file.write_text(cfg_file.read_text() + "\n" + launcher.brb_block(
        str(tmp_path / "kranto-loop"), str(tmp_path / "tasks")))
    written = launcher.make_home(home, 8765, user_home)
    assert not (home / "loop").exists() and not (home / "tasks").exists()
    assert (home / "data").is_dir() and not any("loop" in w for w in written)


def test_a_home_with_an_old_settings_file_is_not_given_a_second_one(user_home):
    """A home made before the rename keeps its settings file's name (legacy.HOME_FILES)."""
    home = user_home / "kb"
    config_mod.init_workspace(home)
    old = home / legacy_mod.HOME_FILES[-1]
    (home / "kranto.yaml").rename(old)
    launcher.make_home(home, 8765, user_home)
    assert not (home / "kranto.yaml").exists()
    assert config_mod.config_path(home) == old


def test_kranto_yaml_wins_and_kranto_home_is_a_workspace(tmp_path, monkeypatch):
    config_mod.init_workspace(tmp_path)
    (tmp_path / "kranto.yaml").write_text(
        config_mod.DEFAULT_CONFIG_YAML.replace("monthly_usd: null", "monthly_usd: 3.0"))
    assert config_mod.load(tmp_path).budget.monthly_usd == 3.0
    monkeypatch.delenv("KRANTO_HOME", raising=False)
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path.parent)
    assert config_mod.find_workspace() == tmp_path


def test_afk_finds_the_home_kranto_setup_recorded(tmp_path, monkeypatch):
    """After install.sh and kranto setup, plain 'afk' (no -w, no $KRANTO_HOME) finds ~/.kranto."""
    user = tmp_path / "user"
    home = user / ".kranto"
    config_mod.init_workspace(home)
    (user / ".config" / "kranto").mkdir(parents=True)
    (user / ".config" / "kranto" / "home").write_text(str(home) + "\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.delenv("KRANTO_HOME", raising=False)
    monkeypatch.delenv("KRANTO_HOME", raising=False)
    monkeypatch.delenv("KRANTO_UNIT", raising=False)
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.chdir(elsewhere)
    assert config_mod.find_workspace() == home
    config_mod.init_workspace(elsewhere)          # a workspace here still wins
    assert config_mod.find_workspace() == elsewhere


def test_load_without_dotenv_leaves_the_environment_alone(tmp_path, monkeypatch):
    config_mod.init_workspace(tmp_path)
    monkeypatch.delenv("KRANTO_TEST_ONLY", raising=False)
    (tmp_path / ".env").write_text("KRANTO_TEST_ONLY=x\n")
    config_mod.load(tmp_path, dotenv=False)
    import os
    assert "KRANTO_TEST_ONLY" not in os.environ
    config_mod.load(tmp_path)
    assert os.environ["KRANTO_TEST_ONLY"] == "x"
    monkeypatch.delenv("KRANTO_TEST_ONLY")


def test_set_section_replaces_one_block_and_keeps_the_rest():
    live = ("llm:\n  base_url: https://x\n\nbudget:\n  monthly_usd: 10\n\nbrb:\n"
            "  enabled: true\n\nconnections:\n  # keep me\n  enabled: true\n")
    out = launcher.set_section(live, "brb", launcher.brb_block("~/kranto-loop", "~/tasks"))
    data = yaml.safe_load(out)
    assert data["brb"] == {"enabled": True, "loop_home": "~/kranto-loop", "root": "~/tasks"}
    assert data["connections"] == {"enabled": True} and "# keep me" in out
    assert data["llm"] == {"base_url": "https://x"} and data["budget"] == {"monthly_usd": 10}
    appended = launcher.set_section("llm:\n  base_url: https://x\n", "brb",
                                 launcher.brb_block("/a", "/b", harness="fake"))
    assert yaml.safe_load(appended)["brb"]["harness"] == "fake"
    nested = launcher.set_in_section(live, "llm", "base_url", "https://y")
    assert yaml.safe_load(nested)["llm"]["base_url"] == "https://y"


def test_unit_file(user_home):
    exe = user_home / ".local" / "bin" / "kranto"
    text = launcher.render_unit(user_home / ".kranto", exe, 8765, user_home)
    assert "Environment=KRANTO_HOME=%h/.kranto\n" in text
    assert "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin\n" in text
    assert "ExecStart=%h/.local/bin/kranto serve --host 127.0.0.1\n" in text
    assert "Description=Kranto: news in, ideas out, posts when you say\n" in text
    assert "build" not in text.split("[Service]")[0] and "--no-loop" not in text
    # The server stops within 10 s and its watchdog exits at 12 (STOP): systemd's kill at 15
    for line in ("KillMode=process", "TimeoutStopSec=15", "Restart=on-failure",
                 "WantedBy=default.target", "Type=simple", "OOMPolicy=continue"):
        assert line in text.splitlines()
    high, cap = memory.default_caps()
    assert f"MemoryHigh={high >> 20}M\nMemoryMax={cap >> 20}M\n" in text
    assert "calibration" not in text and "--no-scheduler" not in text
    env = launcher.unit_env(text, user_home)
    assert env["KRANTO_HOME"] == f"{user_home}/.kranto"
    assert env["PATH"].split(":")[0] == f"{user_home}/.local/bin"
    venv = launcher.render_unit(user_home / "kb", Path("/opt/kranto/bin/kranto"), 8899, user_home)
    assert "ExecStart=/opt/kranto/bin/kranto serve --host 127.0.0.1 --port 8899" in venv
    assert "Environment=PATH=%h/.local/bin:/opt/kranto/bin:/usr/local/bin" in venv


# -- up, serve, down, status --------------------------------------------------------------------


def test_up_installs_and_starts_the_unit(user_home, capsys, monkeypatch):
    host = make_host(user_home)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)      # a person at a terminal
    rc = launcher.main(["up", "--no-browser"], host)
    out = capsys.readouterr().out
    assert rc == 0, out
    unit = user_home / ".config" / "systemd" / "user" / "kranto.service"
    assert "Environment=KRANTO_HOME=%h/.kranto" in unit.read_text()
    calls = [c[2:] for c in host.machine.calls if c[0] == "systemctl"]
    assert ["daemon-reload"] in calls and ["enable", "--now", "kranto.service"] in calls
    assert any(c[:2] == ["loginctl", "enable-linger"] for c in host.machine.calls)
    # the browser opens a one-time sign-in link (OI), which then lands on #/welcome
    assert re.search(r"open http://127\.0\.0\.1:8765/auth/open\?code=[\w-]+&next=/#/welcome\n",
                     out), out
    assert (user_home / ".kranto" / "kranto.yaml").exists()
    # a second up keeps the unit, does not restart, and lands on the app, not #/welcome
    host.machine.calls.clear()
    assert launcher.main(["up", "--no-browser"], host) == 0
    assert ["restart", "kranto.service"] not in [c[2:] for c in host.machine.calls]
    assert re.search(r"open http://127\.0\.0\.1:8765/auth/open\?code=[\w-]+\n",
                     capsys.readouterr().out)
    # with no terminal and no browser (the update's helper runs kranto up), no code is printed
    # into a log: it says how to get one
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert launcher.main(["up", "--no-browser"], host) == 0
    out = capsys.readouterr().out
    assert "auth/open" not in out and "Sign a browser in with 'kranto open'" in out


def test_the_signin_line_reaches_a_pipe_while_kranto_serves(user_home, monkeypatch):
    """An agent reads 'kranto up' through a pipe, which Python block-buffers: the sign-in line
    is flushed, so it arrives while the foreground server runs, not at exit."""
    class Pipe(io.StringIO):
        tty = False
        seen = ""

        def isatty(self):
            return self.tty

        def flush(self):
            self.seen = self.getvalue()

    host = make_host(user_home)
    launcher.make_home(user_home / ".kranto", 8765, user_home)
    for tty in (False, True):
        pipe = Pipe()
        pipe.tty = tty
        monkeypatch.setattr(sys, "stdout", pipe)
        launcher.offer_signin(user_home / ".kranto", host, "/", True)
        monkeypatch.undo()
        assert pipe.seen and pipe.seen == pipe.getvalue(), (tty, pipe.getvalue())
        assert ("auth/open" in pipe.seen) is tty


def test_up_refuses_a_port_in_use(user_home, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": True)
    host = make_host(user_home)
    assert launcher.main(["up", "--no-browser"], host) == 2
    assert "port 8765 is already in use" in capsys.readouterr().err
    assert ["enable", "--now", "kranto.service"] not in [c[2:] for c in host.machine.calls]


def test_a_later_up_with_another_port_moves_the_home_to_it(user_home, monkeypatch, capsys):
    """The first 'up' finds 8765 taken after it wrote the home; 'up --port N' then serves on N,
    and 'kranto open' (and every reader of notify.base_url) must point at N, not 8765."""
    taken = {8765}
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": port in taken)
    host = make_host(user_home)
    assert launcher.main(["up", "--no-browser"], host) == 2
    capsys.readouterr()
    assert launcher.main(["up", "--no-browser", "--port", "8790"], host) == 0
    out = capsys.readouterr().out
    assert "(port 8790)" in out, out
    cfg = config_mod.load(user_home / ".kranto", dotenv=False)
    assert launcher.port_of(cfg) == 8790
    assert "--port 8790" in (user_home / ".config/systemd/user/kranto.service").read_text()
    assert "127.0.0.1:8765" not in (user_home / ".kranto/loop/loop.yaml").read_text()
    # and a plain 'up' afterwards keeps 8790
    assert launcher.main(["up", "--no-browser"], host) == 0
    assert "127.0.0.1:8790" in capsys.readouterr().out


def test_up_in_a_scratch_home_serves_in_the_foreground(user_home, tmp_path, monkeypatch, capsys):
    served = []
    monkeypatch.setattr(launcher, "cmd_serve", lambda args, host: served.append(args) or 0)
    host = make_host(user_home, login_home=tmp_path / "real-home")
    assert launcher.main(["up", "--no-browser", "--port", "8811"], host) == 0
    assert "not the login home" in capsys.readouterr().out
    assert not (user_home / ".config" / "systemd" / "user" / "kranto.service").exists()
    assert not [c for c in host.machine.calls if c[0] == "systemctl" and c[2] != "is-active"]
    assert served[0].port == 8811 and served[0].no_scheduler is False


def test_serve_is_afk_serve(user_home, monkeypatch):
    from kranto import cli

    seen = []
    monkeypatch.setattr(cli, "cmd_serve", lambda ns: seen.append(ns) or 0)
    host = make_host(user_home)
    launcher.make_home(user_home / ".kranto", 8822, user_home)
    assert launcher.main(["serve"], host) == 0
    ns = seen[-1]
    assert ns.workspace == str(user_home / ".kranto") and ns.port == 8822
    assert ns.no_scheduler is False and ns.host == "127.0.0.1"
    assert ns.banner == "kranto" and not hasattr(ns, "loop_lane")
    # --no-loop: still accepted (hidden), and means nothing since builds left
    assert launcher.main(["serve", "--no-scheduler", "--no-loop", "--port", "9000"], host) == 0
    assert seen[-1].no_scheduler and seen[-1].port == 9000


def test_serve_without_a_home_says_run_up(user_home, capsys):
    assert launcher.main(["serve"], make_host(user_home)) == 2
    assert "run 'kranto up' first" in capsys.readouterr().err


def test_down_and_logs_without_systemd(user_home, tmp_path, capsys):
    host = make_host(user_home, FakeMachine(systemd=False))
    assert launcher.main(["down"], host) == 1
    assert "Ctrl-C" in capsys.readouterr().out
    host = make_host(user_home)
    assert launcher.main(["down"], host) == 0
    assert ["systemctl", "--user", "stop", "kranto.service"] in host.machine.calls


def test_status_one_screen(user_home, monkeypatch, capsys):
    """Builds left Kranto (CUT): no lane, loop, build spend or build login line, and still well;
    even a server that still reports a loop lane (an older one) is not said."""
    launcher.make_home(user_home / ".kranto", 8765, user_home)
    lane = {"state": "waiting", "ticks": 12, "errors": 0, "detail": "a brb loop run holds it",
            "last_tick": "2026-10-07T10:00:00Z", "paused": False}
    status = {"version": "0.1.0", "scheduler": True, "paused": None, "lanes": {"loop": lane}}
    host = make_host(user_home, FakeMachine(active={"kranto.service": "active"}),
                     status=status)
    host.machine.enabled["kranto.service"] = "enabled"
    assert launcher.main(["status"], host) == 0
    out = capsys.readouterr().out
    assert "kranto.service: active, enabled" in out
    assert "jobs       ingest never" in out
    assert "spend      watching $0.00 this month, no cap" in out
    for gone in ("loop lane", "loop ", "builds $", "daemon pid", "a day", "claude     ",
                 "brb loop run"):
        assert gone not in out, gone
    # the old unit still up is not well
    host.machine.active[launcher.OLD_UNIT] = "active"
    assert launcher.main(["status"], host) == 1
    assert f"{launcher.OLD_UNIT} is also active" in capsys.readouterr().out


def test_the_written_configs_never_say_build_rules_writes_loop_yaml(user_home):
    # Settings › Build rules is read-only and says "edit loop.yaml": the seeds agree with it
    home = user_home / ".kranto"
    seed = launcher.loop_seed_text(home, 8765, user_home)
    config = launcher.home_config_text(home, 8765, user_home)
    for text in (seed, config):
        assert "written by the Build rules page" not in text and "hand-edit" not in text
    assert "the rest are edited by hand" in seed


def test_the_written_configs_name_no_page_that_left(user_home):
    """kranto.yaml's header and its brb section, and the page's seed, say what they are now:
    no Settings › Building (gone), no build loop or builds UI; the keys are as they were."""
    home = user_home / ".kranto"
    seed = launcher.loop_seed_text(home, 8765, user_home)
    config = launcher.home_config_text(home, 8765, user_home)
    block = launcher.brb_block("~/kranto-loop", "~/tasks")
    for text in (seed, config, block):
        comments = "\n".join(ln for ln in text.splitlines() if ln.lstrip().startswith("#"))
        for gone in ("Settings › Building", "build loop", "builds UI", "plus the brb section"):
            assert gone not in comments, gone
    assert "Projects" not in seed and "Maintenance" not in seed
    assert "the page and\n# its console" in config and "loop/loop.yaml" in config
    assert yaml.safe_load(block)["brb"] == {"enabled": True, "loop_home": "~/kranto-loop",
                                            "root": "~/tasks"}
    # a new home: no task folder of the builds, in either file, and no section of a feature
    # that left (they are still read from an older file: config.FOR_OLD_FILES)
    assert yaml.safe_load(config)["brb"] == {"enabled": True, "loop_home": "~/.kranto/loop"}
    assert set(yaml.safe_load(seed)) == {"kranto"}
    assert not set(config_mod.FOR_OLD_FILES) & set(yaml.safe_load(config))


def test_status_when_the_server_is_down(user_home, monkeypatch, capsys):
    launcher.make_home(user_home / ".kranto", 8765, user_home)
    host = make_host(user_home, status="down")
    assert launcher.main(["status"], host) == 1
    assert "is not answering" in capsys.readouterr().out


# -- doctor -------------------------------------------------------------------------------------


def by_name(checks):
    return {c.name: c for c in checks}


def test_prerequisites_all_present(user_home):
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home)))
    assert {checks[n].status for n in ("claude", "gh", "bwrap", "uv")} == {OK}
    assert "signed in" in checks["claude"].detail and "logged in" in checks["gh"].detail


def test_prerequisites_name_what_to_do(user_home):
    machine = FakeMachine(rc={"claude": 1, "gh": 1, "bwrap": 1})
    machine.tools.pop("uv")
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home, machine)))
    assert checks["claude"].status == WARN and "run 'claude' and log in" in checks["claude"].detail
    assert (checks["gh"].status, checks["gh"].detail) == (
        WARN, "gh is not logged in: 'File a Kranto issue' needs it (gh auth login)")
    assert checks["bwrap"].status == WARN and "cannot start a sandbox" in checks["bwrap"].detail
    assert checks["uv"].status == WARN
    assert "github" not in checks and not any(
        "kranto setup github" in c.detail for c in checks.values())
    machine = FakeMachine()
    for n in ("claude", "gh", "bwrap"):
        machine.tools.pop(n)
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home, machine)))
    assert {checks[n].status for n in ("claude", "gh")} == {WARN}     # Kranto works without
    assert checks["bwrap"].status == FAIL
    assert "Claude Code is not installed" in checks["claude"].detail
    assert "'File a Kranto issue' needs it" in checks["gh"].detail


def test_doctor_looks_on_the_units_path(user_home):
    unit_dir = user_home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "kranto.service").write_text(
        launcher.render_unit(user_home / ".kranto", user_home / ".local/bin/kranto", 8765,
                             user_home))
    host = make_host(user_home)
    checks = by_name(launcher.prerequisite_checks(user_home, host))
    assert checks["unit PATH"].status == OK
    assert f"{user_home}/.local/bin" in host.machine.which_paths[0]
    (unit_dir / "kranto.service").write_text("[Service]\nEnvironment=PATH=/usr/bin:/bin\n")
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home)))
    assert checks["unit PATH"].status == FAIL and ".local/bin" in checks["unit PATH"].detail


def _older_library(db: Path, monkeypatch) -> int:
    """A library one migration behind this version, as after an upgrade."""
    last = store_mod.Store.migration_numbers()[-1]
    with monkeypatch.context() as m:
        m.setattr(store_mod, "_MIGRATIONS", [x for x in store_mod._MIGRATIONS if x[0] != last])
        Store.open(db).close()
    return last


def test_doctor_reports_pending_migrations_without_applying_them(user_home, monkeypatch):
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    last = _older_library(home / "data" / "kranto.db", monkeypatch)
    checks = by_name(launcher.doctor_checks(home, make_host(user_home)))
    assert checks["migrations"].status == FAIL and str(last) in checks["migrations"].detail
    assert launcher.pending_migrations(home / "data" / "kranto.db") == [last]  # untouched


def test_doctor_says_the_console_is_ready(user_home, monkeypatch):
    """The console's line, from the page's term_doctor: "ready" when it is ok, else "not ready"
    and what is missing; no build line (loop home, tasks, build policy, loop lock, maintain,
    capabilities) is left, and loop.yaml is never named."""
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    cfg = config_mod.load(home, dotenv=False)
    said = {
        "line": (
            "ok",
            "Open in Claude Code: sandboxed, its Claude login token by pipe, ptrace_scope 1",
        )
    }
    brbfake.install(
        monkeypatch,
        API_VERSION=99,
        term_doctor=lambda loop_home, environ=None, dotenv=(): said["line"],
    )
    checks = by_name(launcher.console_checks(cfg))
    assert set(checks) == {"kranto.page", "open in claude code"}
    assert checks["kranto.page"].status == OK
    term = checks["open in claude code"]
    assert (term.status, term.detail) == (
        OK,
        "ready: sandboxed, its Claude login token by pipe, ptrace_scope 1",
    )
    said["line"] = (
        "warn",
        "Open in Claude Code turns on by itself where Kranto has bubblewrap "
        "and a Claude token; this install lacks a Claude token ('kranto setup "
        "claude' adds a token), or set term.enabled: true in loop.yaml.",
    )
    c = by_name(launcher.console_checks(cfg))["open in claude code"]
    assert (
        c.status == WARN
        and c.detail.startswith("not ready: ")
        and "lacks a Claude token" in c.detail
        and "loop.yaml" not in c.detail
    )
    # the line is Open in Claude Code's: the console beside every page may well be running
    assert "the console" not in c.detail and "Open in Claude Code" in c.detail
    said["line"] = (
        "warn",
        "Open in Claude Code is off: set term.enabled: true in loop.yaml "
        "and restart Kranto.",
    )
    c = by_name(launcher.console_checks(cfg))["open in claude code"]
    assert c.detail == "not ready: off: set term.enabled: true and restart Kranto."
    said["line"] = ("ok", "Open in Claude Code is off (term.enabled)")
    assert by_name(launcher.console_checks(cfg))["open in claude code"].detail == \
        "off (term.enabled is false)"
    brbfake.missing(monkeypatch)  # no page at all
    assert [(c.status, c.name) for c in launcher.console_checks(cfg)] == [(FAIL, "kranto.page")]


def test_doctor_runs_afk_doctor_and_the_console_checks(user_home, monkeypatch):
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    Store.open(home / "data" / "kranto.db").close()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-" + secrets.token_hex(4))
    cfg = config_mod.load(home, dotenv=False)
    models = {"data": [{"id": m} for m in cfg.llm.models.values()]}

    def answer(request):
        return httpx.Response(
            200, json=models if request.url.path.endswith("/models") else {"data": {}}
        )

    brbfake.missing(monkeypatch)
    checks = by_name(
        launcher.doctor_checks(home, make_host(user_home), transport=httpx.MockTransport(answer))
    )
    assert checks["migrations"].status == OK
    assert checks["library"].status == OK and checks["api key"].status == OK
    assert checks["judge model"].status == OK
    assert checks["kranto.page"].status == FAIL  # Kranto needs both halves
    assert checks["claude"].status == OK
    for gone in (
        "build login",
        "claude token",
        "github",
        "maintain",
        "loop home",
        "tasks",
        "build policy",
        "loop lock",
        "builds",
    ):
        assert gone not in checks, gone


def test_doctor_says_builds_are_retired_once(user_home, monkeypatch):
    """builds.enabled: true in the settings: exactly one line says the feature left and its
    settings are ignored, with or without a library (doctor.run says it when it runs)."""
    from kranto import doctor

    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    cfg_file = home / "kranto.yaml"
    cfg_file.write_text(launcher.set_in_section(cfg_file.read_text(), "builds", "enabled", "true"))
    want = (WARN, "builds", "this feature is not part of Kranto any more; its settings are ignored")
    brbfake.missing(monkeypatch)
    for library in (False, True):
        if library:
            Store.open(home / "data" / "kranto.db").close()
        lines = [
            (c.status, c.name, c.detail)
            for c in launcher.doctor_checks(home, make_host(user_home))
            if c.name == "builds"
        ]
        assert lines == [want], library
    cfg_file.write_text(launcher.home_config_text(home, 8765, user_home))  # builds.enabled: false
    assert doctor.retired_builds(config_mod.load(home, dotenv=False)) == []


def test_load_dotenv_names_what_it_added_never_a_value(tmp_path, monkeypatch):
    """BL: a process Kranto starts (a build, a fix) inherits the watcher's key with the server's
    environment; $KRANTO_DOTENV_VARS names it, so the page still knows whose it is."""
    from kranto import config as config_mod

    key = "k-" + secrets.token_hex(8)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(config_mod.DOTENV_VARS, raising=False)
    monkeypatch.setenv("XAI_API_KEY", "already")
    env = tmp_path / ".env"
    env.write_text(f"ANTHROPIC_API_KEY={key}\nXAI_API_KEY=other\n")
    config_mod.load_dotenv(env)
    assert os.environ["ANTHROPIC_API_KEY"] == key and os.environ["XAI_API_KEY"] == "already"
    assert os.environ[config_mod.DOTENV_VARS] == "ANTHROPIC_API_KEY"  # what it added, by name
    config_mod.load_dotenv(env)  # again: the same
    assert os.environ[config_mod.DOTENV_VARS] == "ANTHROPIC_API_KEY"


def test_the_login_token_kranto_keeps_for_the_console(user_home, monkeypatch):
    """The login token 'kranto setup claude' keeps (the console pipes it to claude): at 0600 in
    a 0700 folder, known by its file's mode and size, never its content."""
    for k in launcher.TOKEN_VARS:
        monkeypatch.delenv(k, raising=False)
    host = make_host(user_home)
    tok = "t-" + secrets.token_hex(16)
    assert not launcher.claude_kept(host)
    at = launcher.keep_claude_login(host, tok)
    assert at == user_home / ".config" / "kranto" / "claude" / "login.env"  # the page's store
    assert at.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN={tok}\n"
    assert stat.S_IMODE(at.stat().st_mode) == 0o600
    assert stat.S_IMODE(at.parent.stat().st_mode) == 0o700
    assert launcher.claude_kept(host)
    at.chmod(0o644)  # others can read it: not used
    assert not launcher.claude_kept(host)


def test_doctor_without_a_home(user_home, capsys):
    assert launcher.main(["doctor"], make_host(user_home)) == 1
    assert "kranto up" in capsys.readouterr().out


# -- adopt --------------------------------------------------------------------------------------


@pytest.fixture
def legacy(user_home, monkeypatch):
    """A scratch copy of the layout from before Kranto (adopt's defaults): ~/kranto-kb
    (brb.enabled only), ~/kranto-loop with a ledger and loop.yaml, ~/tasks, and
    kranto.service with its calibration drop-in."""
    kb = user_home / legacy_mod.WORKSPACE.removeprefix("~/")
    config_mod.init_workspace(kb)
    text = (
        (kb / "kranto.yaml")
        .read_text()
        .replace("  enabled: false\n\nconnections:", "  enabled: true\n\nconnections:")
    )
    (kb / "kranto.yaml").write_text(text)
    assert config_mod.load(kb, dotenv=False).brb.enabled
    last = _older_library(kb / "data" / legacy_mod.DB_FILE, monkeypatch)
    loop = user_home / legacy_mod.LOOP_HOME.removeprefix("~/")
    loop.mkdir()
    (loop / "loop.yaml").write_text("concurrency: 1\nintake:\n  auto:\n    mode: manual\n")
    c = sqlite3.connect(loop / "loop.db")
    c.execute("CREATE TABLE ideas (id TEXT)")
    c.execute("INSERT INTO ideas VALUES ('i1')")
    c.commit()
    c.close()
    (user_home / "tasks").mkdir()
    d = user_home / ".config" / "systemd" / "user" / f"{launcher.OLD_UNIT}.d"
    d.mkdir(parents=True)
    (d.parent / launcher.OLD_UNIT).write_text("[Service]\nExecStart=afk serve --no-scheduler\n")
    (d / "calibration.conf").write_text("[Service]\nExecStart=\nExecStart=afk serve\n")
    return {"kb": kb, "loop": loop, "dropin": d / "calibration.conf", "last": last}


def snapshot(root: Path) -> dict:
    return {
        str(p): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.endswith(("-shm", "-wal"))
    }


def test_adopt_dry_run_plans_and_changes_nothing(user_home, legacy, capsys):
    machine = FakeMachine(active={launcher.OLD_UNIT: "active"}, tmux=True)
    host = make_host(user_home, machine)
    before = snapshot(user_home)
    assert launcher.main(["adopt", "--dry-run"], host) == 0
    out = capsys.readouterr().out
    assert snapshot(user_home) == before
    assert not (user_home / f"{legacy['kb'].name}-backups").exists()
    assert f"workspace   {legacy['kb']} (kranto.yaml)" in out
    assert f"loop home   {legacy['loop']}" in out and f"tasks       {user_home}/tasks" in out
    assert (
        f"{legacy_mod.DB_FILE}.{today()}-pre-kranto" in out
        and f"loop.db.{today()}-pre-kranto" in out
    )
    assert f'loop_home: "{legacy_mod.LOOP_HOME}"' in out and 'root: "~/tasks"' in out
    assert f"apply {legacy['last']} (after the backup)" in out
    assert "setup.done" in out
    assert f"systemctl --user disable --now {launcher.OLD_UNIT} (now active)" in out
    assert f"move {legacy['dropin']}" in out
    assert "systemctl --user enable --now kranto.service" in out
    # builds left Kranto (CUT): no word of the old loop daemon or its tmux session
    assert "tmux" not in out and "loop daemon" not in out and "Afterwards" not in out
    changes = [
        c
        for c in machine.calls
        if c[0] == "systemctl" and c[2] in ("enable", "disable", "daemon-reload", "stop", "start")
    ]
    assert changes == []


def test_adopt_without_a_terminal_needs_yes(user_home, legacy, capsys):
    before = snapshot(user_home)
    assert launcher.main(["adopt"], make_host(user_home)) == 1
    assert "--yes" in capsys.readouterr().out
    assert snapshot(user_home) == before


def test_adopt_in_place(user_home, legacy, capsys):
    machine = FakeMachine(active={launcher.OLD_UNIT: "active"})
    host = make_host(user_home, machine)
    db = legacy["kb"] / "data" / legacy_mod.DB_FILE
    assert launcher.main(["adopt", "--yes"], host) == 0, capsys.readouterr()
    backups = user_home / f"{legacy['kb'].name}-backups"
    # the backup was taken before the migration
    assert launcher.pending_migrations(backups / f"{legacy_mod.DB_FILE}.{today()}-pre-kranto") == [
        legacy["last"]
    ]
    assert launcher.pending_migrations(db) == []
    assert (backups / f"loop.db.{today()}-pre-kranto").exists()
    assert (backups / f"kranto.yaml.{today()}-pre-kranto").exists()
    cfg = config_mod.load(legacy["kb"], dotenv=False)
    assert (
        cfg.brb.enabled and cfg.brb.loop_home == legacy_mod.LOOP_HOME and cfg.brb.root == "~/tasks"
    )
    s = Store.open(db)
    try:
        assert s.get_setting("setup.done") == f"adopted {today()}"
    finally:
        s.close()
    # the switch: old unit off, drop-in retired (kept in the backups), Kranto on
    assert not legacy["dropin"].exists()
    assert (backups / f"{launcher.OLD_UNIT}.d.calibration.conf.{today()}").exists()
    unit = (user_home / ".config/systemd/user/kranto.service").read_text()
    assert f"Environment=KRANTO_HOME=%h/{legacy['kb'].name}" in unit
    calls = [
        c[2:]
        for c in machine.calls
        if c[0] == "systemctl" and c[2] in ("disable", "daemon-reload", "enable")
    ]
    assert calls == [
        ["disable", "--now", launcher.OLD_UNIT],
        ["daemon-reload"],
        ["enable", "--now", "kranto.service"],
    ]
    # adopting again changes nothing that is already done
    capsys.readouterr()
    assert launcher.main(["adopt", "--yes", "--no-service"], host) == 0
    out = capsys.readouterr().out
    assert "brb section already on" in out and "none pending" in out
    assert "setup.done already set" in out
    assert (backups / f"{legacy_mod.DB_FILE}.{today()}-pre-kranto-2").exists()  # never overwritten


def test_adopt_rolls_back_when_kranto_does_not_answer(user_home, legacy, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "_wait_up", lambda host, port, seconds: False)
    machine = FakeMachine(active={launcher.OLD_UNIT: "active"})
    assert launcher.main(["adopt", "--yes"], make_host(user_home, machine)) == 1
    err = capsys.readouterr().err
    assert (
        "did not answer" in err and "Rolled back" in err and f"{launcher.OLD_UNIT} is back" in err
    )
    assert legacy["dropin"].exists()  # the drop-in is back where it was
    calls = [
        c[2:]
        for c in machine.calls
        if c[0] == "systemctl" and c[2] in ("disable", "daemon-reload", "enable")
    ]
    assert calls[-3:] == [
        ["disable", "--now", "kranto.service"],
        ["daemon-reload"],
        ["enable", "--now", launcher.OLD_UNIT],
    ]
    assert machine.active[launcher.OLD_UNIT] == "active"


def test_adopt_no_service_leaves_the_units(user_home, legacy):
    machine = FakeMachine(active={launcher.OLD_UNIT: "active"})
    assert launcher.main(["adopt", "--yes", "--no-service"], make_host(user_home, machine)) == 0
    assert legacy["dropin"].exists()
    assert not (user_home / ".config/systemd/user/kranto.service").exists()
    assert [
        c
        for c in machine.calls
        if c[0] == "systemctl" and c[2] in ("enable", "disable", "daemon-reload")
    ] == []


def test_adopt_in_a_scratch_home_skips_the_units(user_home, legacy, tmp_path, capsys):
    host = make_host(user_home, login_home=tmp_path / "elsewhere")
    assert launcher.main(["adopt", "--dry-run"], host) == 0
    out = capsys.readouterr().out
    assert "skipped: HOME is" in out and "not the login home" in out


def test_adopt_needs_a_workspace(user_home, capsys):
    assert launcher.main(["adopt", "--dry-run"], make_host(user_home)) == 2
    assert "no workspace" in capsys.readouterr().err


# -- kranto mcp (the page's) ---------------------------------------------------------
def fake_mcp(monkeypatch, available=True):
    """kranto.page.mcp.server as kranto mcp sees it, without the page or the SDK: the URL each run
    was given."""
    calls = []
    server = types.ModuleType("kranto.page.mcp.server")
    server.available = lambda: available

    def main(url=None):
        calls.append(url)
        if not available:
            print("kranto mcp: install the MCP extra: uv tool install ...", file=sys.stderr)
            return 2
        return 0

    server.main = main
    brbfake.install(monkeypatch, mcp_available=server.available, mcp_main=server.main)
    return calls


def test_kranto_mcp_serves_the_homes_own_url(user_home, monkeypatch):
    home = user_home / ".kranto"
    launcher.make_home(home, 8799, user_home)
    calls = fake_mcp(monkeypatch)
    assert launcher.main(["--home", str(home), "mcp"], make_host(user_home)) == 0
    assert (
        launcher.main(
            ["--home", str(home), "mcp", "--url", "http://localhost:9000"], make_host(user_home)
        )
        == 0
    )
    assert calls == ["http://127.0.0.1:8799", "http://localhost:9000"]
    assert by_name([launcher.mcp_check()])["mcp"].detail.startswith("the MCP extra is installed")


def test_kranto_mcp_without_the_extra_says_how_to_install_it(user_home, monkeypatch, capsys):
    home = user_home / ".kranto"
    launcher.make_home(home, 8799, user_home)
    fake_mcp(monkeypatch, available=False)
    assert launcher.main(["--home", str(home), "mcp"], make_host(user_home)) == 2
    assert "install the MCP extra" in capsys.readouterr().err
    c = launcher.mcp_check()
    assert c.status == OK and "kranto[mcp]" in c.detail


def _help(argv, host, capsys) -> str:
    with pytest.raises(SystemExit):
        launcher.main(argv, host)
    return " ".join(capsys.readouterr().out.split())  # argparse wraps to the terminal


def test_the_factory_commands_are_gone(user_home, capsys):
    """CUT: tools (cap), plugin, mcp-server, maintain, github, corpus and research left with
    builds: not listed, and not commands any more."""
    host = make_host(user_home)
    out = _help(["--help"], host, capsys)
    assert "Kranto's own MCP server" in out
    for gone in (
        "tools",
        "cap",
        "plugin",
        "mcp-server",
        "maintain",
        "github",
        "corpus",
        "research",
    ):
        assert f"    {gone} " not in out and f"{{{gone}," not in out
        with pytest.raises(SystemExit) as e:
            launcher.main([gone, "list"], host)
        assert e.value.code == 2
        assert "invalid choice" in capsys.readouterr().err


def test_kranto_cub_is_listed_only_for_a_developer(user_home, capsys):
    """kranto cub runs either way; kranto --help lists it once the home's config turns
    cubs.developer on (the cub shop's own gate), and keeps it out on any doubt."""
    home = user_home / ".kranto"
    launcher.make_home(home, 8799, user_home)
    host = make_host(user_home)
    assert "the small programs Kranto runs in a sandbox" not in _help(
        ["--home", str(home), "--help"], host, capsys
    )
    cfg = home / "kranto.yaml"
    cfg.write_text(launcher.set_in_section(cfg.read_text(), "cubs", "developer", "true"))
    assert "the small programs Kranto runs in a sandbox" in _help(
        ["--home", str(home), "--help"], host, capsys
    )
    cfg.write_text("brb: [not, a, section\n")  # unreadable: kept out
    assert "the small programs Kranto runs in a sandbox" not in _help(
        ["--home", str(home), "--help"], host, capsys
    )
    assert "cub" in launcher.build_parser()._subparsers._group_actions[0].choices  # it still runs


def test_kranto_trace_is_brb_trace_for_this_home(user_home, monkeypatch, capsys):
    import os

    home = user_home / ".kranto"
    launcher.make_home(home, 8799, user_home)
    calls = []
    cli = types.ModuleType("kranto.page.trace.cli")

    def show(ns):
        calls.append(("show", ns.trace, ns.errors, os.environ.get("KRANTO_LOOP_HOME")))

    def add_trace_group(sub):
        p = sub.add_parser("trace")
        g = p.add_subparsers(dest="trace_cmd", required=True)
        s = g.add_parser("show")
        s.add_argument("trace")
        s.add_argument("--errors", action="store_true")
        s.set_defaults(fn=show)

    cli.add_trace_group = add_trace_group
    brbfake.install(monkeypatch, add_trace_group=add_trace_group)
    monkeypatch.delenv("KRANTO_LOOP_HOME", raising=False)
    host = make_host(user_home)
    assert launcher.main(["--home", str(home), "trace", "show", "build:x/1", "--errors"], host) == 0
    assert calls[0][:3] == ("show", "build:x/1", True) and calls[0][3]
    brbfake.drop(monkeypatch, "add_trace_group")  # a version of the page without traces
    assert launcher.main(["--home", str(home), "trace", "show", "build:x/1"], host) == 2
    assert "update Kranto" in capsys.readouterr().err


def test_kranto_term_without_the_feature_says_so_in_a_sentence(user_home, monkeypatch, capsys):
    brbfake.drop(monkeypatch, "term_cli")           # a version of the page without it
    host = make_host(user_home)
    assert launcher.main(["term", "list"], host) == 2
    assert capsys.readouterr().err == ("kranto term: this version of Kranto has no Open in "
                                       "Claude Code; update Kranto\n")


def test_down_disable_keeps_it_from_starting_at_boot(user_home, capsys):
    host = make_host(user_home)
    assert launcher.main(["down"], host) == 0
    assert "kranto down --disable" in capsys.readouterr().out
    assert ["systemctl", "--user", "disable", "kranto.service"] not in host.machine.calls
    assert launcher.main(["down", "--disable"], host) == 0
    assert host.machine.calls[-2:] == [
        ["systemctl", "--user", "stop", "kranto.service"],
        ["systemctl", "--user", "disable", "kranto.service"],
    ]


def test_uninstall_removes_the_service_and_keeps_the_data(user_home, capsys):
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    launcher.remember_home(home, user_home)
    host = make_host(user_home)
    unit_dir = user_home / ".config" / "systemd" / "user"
    (unit_dir / "kranto.service.d").mkdir(parents=True)
    (unit_dir / "kranto.service").write_text("[Service]\n")
    (unit_dir / "kranto.service.d" / "10-x.conf").write_text("[Service]\n")
    assert launcher.main(["uninstall", "--linger-off"], host) == 0
    out = capsys.readouterr().out
    calls = host.machine.calls
    assert ["systemctl", "--user", "disable", "--now", "kranto.service"] in calls
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert any(c[:2] == ["loginctl", "disable-linger"] for c in calls)
    assert not (unit_dir / "kranto.service").exists()
    assert not (unit_dir / "kranto.service.d").exists()
    assert (home / "kranto.yaml").is_file() and (home / "loop" / "loop.yaml").is_file()
    assert f"the home {home.resolve()}" in out and "uv tool uninstall kranto" in out
    # without --linger-off lingering is left alone
    host = make_host(user_home)
    assert launcher.main(["uninstall"], host) == 0
    assert not any(c[0] == "loginctl" for c in host.machine.calls)


def test_uninstall_without_systemd_says_so_and_keeps_everything(user_home, capsys):
    host = make_host(user_home, FakeMachine(systemd=False))
    assert launcher.main(["uninstall"], host) == 0
    out = capsys.readouterr().out
    assert "no systemd user manager" in out and "uv tool uninstall kranto" in out
    assert not any(c[:2] == ["systemctl", "--user"] and "disable" in c for c in host.machine.calls)
    assert "is stopped and will not start again" not in out
    assert "Kranto is not running, and nothing starts it by itself here." in out


def test_uninstall_without_systemd_says_a_foreground_kranto_still_runs(
        user_home, capsys, monkeypatch):
    """Without systemd, uninstall said "Kranto is stopped and will not start again" while this
    home's server still answered in the foreground; it says how to stop it now."""
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    launcher.remember_home(home, user_home)
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": port == 8765)
    monkeypatch.setattr(launcher, "serves_this_home", lambda host, port, h: True)
    host = make_host(user_home, FakeMachine(systemd=False))
    assert launcher.main(["uninstall"], host) == 0
    out = capsys.readouterr().out
    assert "still runs in the foreground on 127.0.0.1:8765: stop it with Ctrl-C" in out
    assert "will not start again" not in out


def _status(runs, observations=0):
    return {"version": "0.7.0", "observations": observations,
            "runs": [{"run_uuid": r} for r in runs]}


def test_serves_this_home_tells_this_homes_server_from_another(user_home):
    """kranto setup took any server answering on the home's port for its own; the runs the
    server lists must be this home's (the status answer names no home)."""
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    Store.open(home / "data" / "kranto.db").close()
    with sqlite3.connect(home / "data" / "kranto.db") as con:
        con.execute("INSERT INTO runs (run_uuid, kind, status, started_at, finished_at, "
                    "summary) VALUES ('r1', 'ingest', 'ok', 'x', 'x', '{}')")

    def host_with(answer, code=200):
        h = make_host(user_home)
        h.http_get = lambda url, timeout: (code, json.dumps(answer).encode())
        return h

    assert launcher.serves_this_home(host_with(_status(["r1"])), 8765, home) is True
    assert launcher.serves_this_home(host_with(_status(["r9"])), 8765, home) is False
    assert launcher.serves_this_home(host_with(_status([], 5)), 8765, home) is False
    assert launcher.serves_this_home(host_with({"hello": 1}), 8765, home) is None
    assert launcher.serves_this_home(host_with({}, 404), 8765, home) is None


class ServiceMachine(FakeMachine):
    """A machine whose kranto.service runs as ``pid``."""

    def __init__(self, pid, **kw):
        super().__init__(**kw)
        self.pid = pid

    def run(self, cmd, timeout=30):
        if Path(cmd[0]).name == "systemctl" and cmd[2] == "show":
            self.calls.append(list(cmd))
            return _cp(0, f"{self.pid}\n")
        return super().run(cmd, timeout)


def test_doctor_judges_the_running_service_not_its_own_shell(user_home, monkeypatch):
    """`ssh the server 'kranto doctor'` has another PATH and none of the unit's EnvironmentFile:
    the term and login lines read what the running service has, by name only."""
    tok = "t-" + secrets.token_hex(8)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    svc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        env={"PATH": "/srv/x/bin:/usr/bin", "CLAUDE_CODE_OAUTH_TOKEN": tok},
    )
    try:
        for _ in range(200):  # until it runs (its own environment)
            if b"time.sleep" in Path(f"/proc/{svc.pid}/cmdline").read_bytes():
                break
            time.sleep(0.02)
        host = make_host(user_home, ServiceMachine(svc.pid))
        env, where = launcher.service_env(host)
        assert env["PATH"] == "/srv/x/bin:/usr/bin" and env["CLAUDE_CODE_OAUTH_TOKEN"] == "set"
        assert f"running kranto.service (pid {svc.pid})" in where
        assert tok not in repr((env, where))
        brbfake.install(
            monkeypatch,
            term_doctor=lambda loop_home, environ=None, dotenv=(): (
                ("ok", "Open in Claude Code: sandboxed, its Claude login token by pipe")
                if environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                else ("warn", "no token")
            ),
        )
        check = launcher.term_check(user_home / "loop", (env, where))
        assert check.status == OK and "checked: the running kranto.service" in check.detail
        assert tok not in check.detail
    finally:
        svc.kill()
        svc.wait()


def test_doctor_reads_the_unit_and_its_files_when_the_service_is_not_running(
    user_home, monkeypatch
):
    tok = "t-" + secrets.token_hex(8)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    unit_dir = user_home / ".config" / "systemd" / "user"
    (unit_dir / "kranto.service.d").mkdir(parents=True)
    (unit_dir / "kranto.service").write_text("[Service]\nEnvironment=PATH=%h/.local/bin:/usr/bin\n")
    (unit_dir / "kranto.service.d" / "20-claude-token.conf").write_text(
        "[Service]\nEnvironmentFile=-%h/claude.env\n"
    )
    (user_home / "claude.env").write_text(f"# the token\nCLAUDE_CODE_OAUTH_TOKEN={tok}\n")
    env, where = launcher.service_env(make_host(user_home))
    assert env["PATH"] == f"{user_home}/.local/bin:/usr/bin"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "set" and tok not in repr(env)
    assert "unit" in where and "not running" in where
    # nothing installed: this shell, and it says so
    env, where = launcher.service_env(make_host(user_home / "elsewhere"))
    assert where.startswith("this shell")


def test_the_term_line_is_judged_with_the_services_environment(user_home, monkeypatch):
    seen = {}

    def term_doctor(loop_home, environ=None):
        seen["environ"] = environ
        return "warn", "Open in Claude Code: no Claude token in Kranto's environment"

    fake = types.ModuleType("kranto.page.host_api")
    fake.term_doctor = term_doctor
    monkeypatch.setitem(sys.modules, "kranto.page", types.ModuleType("kranto.page"))
    monkeypatch.setitem(sys.modules, "kranto.page.host_api", fake)
    svc = (
        {"PATH": "/srv/x/bin", "CLAUDE_CODE_OAUTH_TOKEN": "set"},
        "the running kranto.service (pid 7)",
    )
    check = launcher.term_check(user_home / "loop", svc)
    assert seen["environ"] == svc[0]
    assert check.status == WARN
    assert check.detail.endswith("(checked: the running kranto.service (pid 7))")

    def term_doctor_tk(loop_home, environ=None, dotenv=()):
        seen["dotenv"] = set(dotenv)
        return "ok", "Open in Claude Code: sandboxed, its Claude API key (the watcher's) by pipe"

    fake.term_doctor = term_doctor_tk
    check = launcher.term_check(user_home / "loop", svc, {"ANTHROPIC_API_KEY"})
    assert seen["dotenv"] == {"ANTHROPIC_API_KEY"} and "(the watcher's)" in check.detail
