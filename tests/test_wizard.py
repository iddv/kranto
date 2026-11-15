"""``kranto setup`` in a scratch HOME with a fake machine: the
non-interactive run CI and the rc check drive, idempotence, precedence, uncapped defaults, the
secrets' one place, one section at a time, Ctrl-C, and preflight's per-distribution fixes."""

from __future__ import annotations

import builtins
import json
import os
import secrets
import stat
import sys
import types
from pathlib import Path

import httpx
import pytest
import yaml

from kranto import launcher, preflight, wizard
from kranto.launcher import FAIL, OK, WARN

from .test_kranto import FakeMachine, make_host, user_home  # noqa: F401


def setup(host, *argv, capsys=None):
    code = launcher.main(["setup", *argv], host)
    out = capsys.readouterr() if capsys else None
    return code, out


def as_json(out) -> dict:
    return json.loads(out.out)


def test_where_things_are_names_the_unit_only_when_one_was_written(user_home, tmp_path):  # noqa: F811
    host = make_host(user_home)
    run = types.SimpleNamespace(host=host, home=user_home / ".kranto")
    assert not any("kranto.service" in w for w in wizard.where(run))   # served in the foreground
    host.unit_dir.mkdir(parents=True, exist_ok=True)
    (host.unit_dir / launcher.UNIT).write_text("[Service]\n")
    assert any(w.endswith("kranto.service") for w in wizard.where(run))


def test_yes_on_a_fresh_home_writes_the_home_then_nothing_more(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--port", "9023", "--json", capsys=capsys)
    assert code == 0, out.err
    got = as_json(out)
    home = user_home / ".kranto"
    assert got["home"] == str(home) and got["port"] == 9023 and not got["started"]
    assert any(w.endswith("kranto.yaml") for w in got["written"])
    assert any(w.endswith("setup.json") for w in got["written"])
    assert "code=" not in out.out + out.err                 # never a sign-in link in --json
    assert (home / "kranto.yaml").read_text().count("http://127.0.0.1:9023") == 1
    cfg = yaml.safe_load((home / "kranto.yaml").read_text())
    assert (cfg.get("budget") or {}).get("monthly_usd") is None      # uncapped by default
    # builds off (a fresh install): watching's cap only, with what Kranto costs
    assert "No spend cap is set" in out.err and "About $5 to $8 a month" in out.err
    mtimes = {p: p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()}
    code, out = setup(host, "--yes", "--no-start", "--port", "9023", "--json", capsys=capsys)
    again = as_json(out)
    assert code == 0 and again["written"] == [] and again["kept"]
    assert "Done; nothing changed." in out.err
    assert {p: p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()} == mtimes


def test_the_answers_file_is_below_a_flag_and_above_the_default(user_home, capsys, tmp_path):  # noqa: F811
    answers = tmp_path / "answers.yaml"
    answers.write_text("port: 9024\nservice: foreground\nstart: false\nwatch: {provider: later}\n"
                       "github: later\ncaps: {watch_monthly_usd: 12}\n")
    host = make_host(user_home)
    code, out = setup(host, "--answers", str(answers), "--json", capsys=capsys)
    got = as_json(out)
    assert code == 0 and got["port"] == 9024 and got["service"] == "foreground"
    assert got["answers"]["caps"]["watch_monthly_usd"] == 12
    code, out = setup(host, "--answers", str(answers), "--port", "9025", "--json", capsys=capsys)
    assert as_json(out)["port"] == 9025


def test_a_cap_is_written_only_when_typed_and_the_build_caps_are_ignored(user_home, capsys,  # noqa: F811
                                                                         monkeypatch):
    """CUT: the build loop's caps (--cap-daily, --cap-build) left with builds; a script that
    still passes them runs, says one line, and nothing reaches the loop's loop.yaml."""
    wrote = []
    host_api = types.ModuleType("kranto.page.host_api")
    host_api.Config = lambda home: {}
    host_api.write_setting = lambda path, keys, value: wrote.append((Path(path).name, keys, value))
    monkeypatch.setitem(sys.modules, "kranto.page.host_api", host_api)
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", "--json", capsys=capsys)
    code, out = setup(host, "--yes", "--no-start", "--cap-daily", "25", "--cap-build", "$15",
                      "--cap-watch", "10", "--json", capsys=capsys)
    assert code == 0
    assert not [w for w in wrote if w[1] != ("build", "claude_command")]
    assert "ignored: --cap-daily, --cap-build (builds are not part of Kranto any more)" in out.err
    cfg = yaml.safe_load((user_home / ".kranto" / "kranto.yaml").read_text())
    assert cfg["budget"]["monthly_usd"] == 10.0
    code, out = setup(host, "--yes", "--no-start", "--cap-watch", "lots", capsys=capsys)
    assert code == 2 and "not a number of dollars" in out.out


def test_the_builds_sections_left_and_their_flags_are_ignored(user_home, capsys, tmp_path):  # noqa: F811
    """CUT: building, GitHub and repositories are no sections any more; their flags (an older
    install.sh passes --github-token-file) still run, each said once and ignored; the login
    install.sh left is removed unread, never kept."""
    left = tmp_path / "install-login.env"
    left.touch(mode=0o600)
    code, out = setup(make_host(user_home), "--yes", "--no-start", "--github-token-file",
                      str(left), "--github", "later", "--adopt", "ann/a", "--json",
                      capsys=capsys)
    assert code == 0, out.err
    assert not left.exists()
    assert "ignored: --github, --adopt" in out.err and "was not kept" in out.err
    assert not {"github", "repos"} & set(wizard.SECTIONS)
    assert not {"building", "publishing"} & set(wizard.PAGES)
    assert wizard.PAGES["assistant"] == ("claude",)          # the console's login token stays
    for gone in ("building", "github", "repos"):
        with pytest.raises(SystemExit):
            launcher.build_parser().parse_args(["setup", gone])


@pytest.mark.parametrize("flag", ["--watch-key", "--claude-token"])
def test_a_secret_on_the_command_line_is_refused(user_home, capsys, flag):  # noqa: F811
    code, out = setup(make_host(user_home), "--yes", flag, "x" * 20, capsys=capsys)
    assert code == 2 and "shell history" in out.err
    assert not (user_home / ".kranto").exists()


def test_the_model_key_goes_to_env_at_0600_and_nowhere_else(user_home, capsys, tmp_path,  # noqa: F811
                                                            monkeypatch):
    key = "sk-or-v1-" + secrets.token_hex(24)
    loose = tmp_path / "key.txt"
    loose.write_text(key + "\n")
    loose.chmod(0o644)
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--watch", "openrouter", "--watch-key-file",
                      str(loose), capsys=capsys)
    assert code == 2 and "chmod 600" in out.out
    loose.chmod(0o600)
    seen = []

    def transport_fn(request):
        seen.append(request.url.host)
        return httpx.Response(200, json={"data": {}})
    from kranto import setup as su
    real = su.try_key
    monkeypatch.setattr(su, "try_key", lambda base, k, transport=None: real(
        base, k, transport=httpx.MockTransport(transport_fn)))
    code, out = setup(host, "--yes", "--no-start", "--watch", "openrouter", "--watch-key-file",
                      str(loose), "--json", capsys=capsys)
    assert code == 0 and seen == ["openrouter.ai"]
    env = user_home / ".kranto" / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600 and key in env.read_text()
    assert key not in out.out + out.err
    assert key not in (user_home / ".kranto" / "setup.json").read_text()
    assert key not in (user_home / ".kranto" / "kranto.yaml").read_text()


def test_the_claude_login_token_is_kept_in_kranto_store_and_never_shown(user_home, capsys,  # noqa: F811
                                                                       tmp_path):
    """BL: kranto setup claude (the console's) keeps the token claude setup-token printed in
    Kranto's own store (0600 in a 0700 folder, read at each launch, by pipe): no drop-in, no
    restart."""
    token = "sk-ant-oat01-" + secrets.token_hex(20)
    f = tmp_path / "claude.txt"
    f.touch(mode=0o600)
    f.write_text(f"CLAUDE_CODE_OAUTH_TOKEN={token}\n")
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--service", "systemd", "--claude-token-file",
                      str(f), "--json", capsys=capsys)
    assert code == 0, out.err
    kept = user_home / ".config" / "kranto" / "claude" / "login.env"
    assert kept.read_text() == f"CLAUDE_CODE_OAUTH_TOKEN={token}\n"
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert stat.S_IMODE(kept.parent.stat().st_mode) == 0o700
    dropin = user_home / ".config" / "systemd" / "user" / "kranto.service.d" / wizard.CLAUDE_DROPIN
    assert not dropin.exists() and not (user_home / ".config" / "kranto" / "claude.env").exists()
    assert token not in out.out + out.err
    assert token not in (user_home / ".kranto" / "setup.json").read_text()
    assert launcher.claude_kept(host)                    # what the console pipes to claude
    # the second run keeps it
    code, out = setup(host, "claude", "--yes", capsys=capsys)
    assert code == 0 and "your Claude plan: the Claude login token Kranto keeps" in out.out


def test_use_your_claude_plan_runs_claude_setup_token_and_asks_for_the_paste(user_home, capsys,  # noqa: F811
                                                                             monkeypatch):
    token = "sk-ant-oat01-" + secrets.token_hex(20)
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", "--service", "systemd", capsys=capsys)
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt: asked.append(prompt) or token)
    code, out = setup(host, "claude", capsys=capsys)
    assert code == 0, out.out
    assert any("use your Claude plan now?" in p for p in asked)
    assert [c for c in host.machine.calls if c[0] == "tty"] == [["tty", host.which("claude"),
                                                                 "setup-token"]]
    kept = user_home / ".config" / "kranto" / "claude" / "login.env"
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600 and token in kept.read_text()
    assert token not in out.out + out.err


def test_an_api_key_for_the_console_still_goes_to_the_units_file(user_home, capsys, tmp_path):  # noqa: F811
    key = "sk-ant-api03-" + secrets.token_hex(20)
    f = tmp_path / "key.txt"
    f.touch(mode=0o600)
    f.write_text(key + "\n")
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--service", "systemd", "--claude-token-file",
                      str(f), capsys=capsys)
    assert code == 0, out.out
    kept = user_home / ".config" / "kranto" / "claude.env"
    assert kept.read_text() == f"ANTHROPIC_API_KEY={key}\n"
    dropin = user_home / ".config" / "systemd" / "user" / "kranto.service.d" / wizard.CLAUDE_DROPIN
    assert "EnvironmentFile=-%h/.config/kranto/claude.env" in dropin.read_text()
    assert key not in out.out + out.err + dropin.read_text()
    assert not launcher.claude_kept(host)                # an API key is not a login token


def test_one_section_runs_alone(user_home, capsys, monkeypatch):  # noqa: F811
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    code, out = setup(host, "caps", "--cap-watch", "20", capsys=capsys)
    assert code == 0
    assert "This machine" not in out.out and "Where Kranto lives" not in out.out
    assert "budget.monthly_usd none -> 20" in out.out
    monkeypatch.setenv("HOME", str(user_home / "other"))
    code, out = setup(make_host(user_home / "other"), "caps", capsys=capsys)
    assert code == 2 and "run 'kranto setup' first" in out.out


def test_a_settings_page_runs_its_parts_and_the_old_names_stay(user_home, capsys):  # noqa: F811
    """kranto setup's sections are the Settings pages; every part is one
    page's, and its own name (caps, usage, github…) still runs it alone."""
    parts = [x for page in wizard.PAGES.values() for x in page]
    assert sorted([*parts, "topics", "ready"]) == sorted(wizard.SECTIONS[:-1])
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    code, out = setup(host, "spend", "--cap-watch", "20", capsys=capsys)
    assert code == 0 and "Spend › Caps" in out.out and "System ›" not in out.out
    assert "budget.monthly_usd none -> 20" in out.out
    code, out = setup(host, "privacy", "--telemetry", "local", capsys=capsys)
    assert code == 0 and "Privacy & access › Usage reports" in out.out and "Spend ›" not in out.out
    code, out = setup(host, "caps", capsys=capsys)              # the old name: the same part
    assert code == 0 and "Spend › Caps" in out.out


def test_with_builds_off_a_full_run_skips_publishing(user_home, capsys):  # noqa: F811
    """.1: publishing (GitHub, your repositories) is builds'; with builds off a
    full run asks neither."""
    code, out = setup(make_host(user_home), "--yes", "--no-start", "--json", capsys=capsys)
    assert code == 0 and "github" not in as_json(out)["answers"]
    assert "Publishing" not in out.out


def test_ctrl_c_mid_section_leaves_its_files_as_they_were(user_home, capsys, monkeypatch):  # noqa: F811
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    before = (user_home / ".kranto" / "kranto.yaml").read_text()
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    answers = iter(["1"])

    def ask(prompt):
        if "watching a month" in prompt:
            raise KeyboardInterrupt
        return next(answers, "")
    monkeypatch.setattr(builtins, "input", ask)
    code, out = setup(host, "caps", capsys=capsys)
    assert code == 130 and "stopped" in out.out
    assert (user_home / ".kranto" / "kranto.yaml").read_text() == before


def test_an_interactive_run_asks_and_enter_keeps(user_home, capsys, monkeypatch):  # noqa: F811
    host = make_host(user_home)
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt: asked.append(prompt) or "")
    code, out = setup(host, "--no-start", capsys=capsys)
    assert code == 0
    assert any(p.startswith("  home (settings, library) [~/.kranto]") for p in asked)
    assert any(p.startswith("  port (127.0.0.1 only) [8765]") for p in asked)
    assert any("builds a day, USD (none, or e.g. 25) [none]" in p for p in asked) or \
        any("watching a month, USD (none, or e.g. 10) [none]" in p for p in asked)
    # watching: the Claude API is offered first; Enter at its key leaves watching off
    assert "  choice [1]: " in asked and any("Claude API key (not shown" in p for p in asked)
    assert "no key given: watching stays off" in out.out


def test_the_wizard_holds_no_writer_of_its_own():
    src = Path(wizard.__file__).read_text()
    assert "yaml.dump" not in src and "safe_dump" not in src
    assert ".write_text(" in src.split("def claude(")[1].split("def caps(")[0]   # the drop-in
    assert src.count(".write_text(") == 1


def test_ci_a_bare_machine_still_sets_up_and_says_what_is_missing(user_home, capsys):  # noqa: F811
    """PATH without claude, gh or bwrap; --yes skips what is missing (the
    checks say so) and exits 0; nothing listens (no start)."""
    machine = FakeMachine(tools={"systemctl": "/usr/bin/systemctl"})
    code, out = setup(make_host(user_home, machine), "--yes", "--no-start", "--service",
                      "foreground", "--port", "9027", "--watch", "later", "--github", "later",
                      "--json", capsys=capsys)
    got = as_json(out)
    assert code == 0 and not got["started"] and not got["answering"]
    red = {c["name"] for c in got["checks"] if c["status"] == FAIL}
    # builds off: Claude Code is the console's, a warn ("Kranto works without it"); no gh line
    assert "bwrap" in red and "claude" not in red
    claude = next(c for c in got["checks"] if c["name"] == "claude")
    assert claude["status"] == WARN and "Kranto works without it" in claude["detail"]
    assert "gh" not in {c["name"] for c in got["checks"]}
    assert "skip  bwrap" in out.err
    assert not launcher.port_in_use(9027)


# -- preflight ------------------------------------------------------------------------------------


@pytest.mark.parametrize("osr,fam,cmd", [
    ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian", "sudo apt install bubblewrap"),
    ({"ID": "fedora"}, "fedora", "sudo dnf install bubblewrap"),
    ({"ID": "rocky", "ID_LIKE": "rhel centos fedora"}, "fedora", "sudo dnf install bubblewrap"),
    ({"ID": "arch"}, "arch", "sudo pacman -S bubblewrap"),
    ({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}, "suse",
     "sudo zypper install bubblewrap"),
    ({"ID": "nixos"}, None, None)])
def test_each_distribution_gets_its_own_command(osr, fam, cmd):
    assert preflight.family(osr, "Linux") == fam
    assert preflight.install_command("bwrap", fam) == cmd
    assert preflight.family({}, "Darwin") == "darwin"
    assert preflight.install_command("gh", "darwin") == "brew install gh"


def test_claudes_install_is_recognised_from_where_it_resolves(tmp_path):
    h = tmp_path
    assert preflight.claude_layout(str(h / ".local/share/claude/versions/2.1.300"), h) == \
        "native install"
    assert preflight.claude_layout(
        "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", h) == "npm install"
    assert preflight.claude_layout(str(h / ".claude/local/claude"), h) == "local install"
    assert preflight.shell_only(str(h / ".nvm/versions/node/v22/bin/claude"), h)


def test_preflight_names_what_is_missing_and_how_to_get_it(user_home):  # noqa: F811
    machine = FakeMachine()
    for n in ("bwrap", "claude", "gh"):
        machine.tools.pop(n)
    def run(builds):
        return {i.name: i for i in preflight.run(make_host(user_home, machine), port=9026,
                                                 port_check=lambda p: None, system="Linux",
                                                 osr={"ID": "ubuntu", "ID_LIKE": "debian",
                                                      "PRETTY_NAME": "Ubuntu 24.04"},
                                                 builds=builds)}
    items = run(True)
    assert items["linux"].detail.startswith("Ubuntu 24.04")
    assert items["bwrap"].status == FAIL and items["bwrap"].fix == "sudo apt install bubblewrap"
    assert items["claude"].fix == preflight.CLAUDE_INSTALL and items["claude"].status == FAIL
    assert items["gh"].fix == "sudo apt install gh" and items["port 9026"].status == OK
    # builds off: Claude Code is the console's (a warn, how to install it), no gh
    core = run(False)
    assert core["claude"].status == WARN and core["claude"].fix == preflight.CONSOLE_FIX
    assert "Kranto works without it" in core["claude"].detail and "gh" not in core
    assert os.environ.get("HOME") == str(user_home)


# -- --fetch-gh, --claude PATH, macOS ------------------------------------------------------


def _fake_loop(monkeypatch):
    """the page's loop settings, recorded: ``(store, wrote)``."""
    store: dict = {}
    wrote = []
    host_api = types.ModuleType("kranto.page.host_api")
    host_api.Config = lambda home: store
    host_api.write_setting = lambda path, keys, value: wrote.append((Path(path).name, keys, value))
    monkeypatch.setitem(sys.modules, "kranto.page.host_api", host_api)
    return store, wrote


def _exe(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


def _no_gh(user_home, monkeypatch, fetched):  # noqa: F811
    from kranto import ghfetch

    machine = FakeMachine()
    machine.tools.pop("gh")

    def fetch(home):
        p = _exe(ghfetch.bin_dir(home) / "gh")
        machine.tools["gh"] = str(p)
        fetched.append(home)
        return p
    monkeypatch.setattr(ghfetch, "fetch", fetch)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))      # the wizard appends to it
    return make_host(user_home, machine)


def test_claude_path_is_kept_as_build_claude_command(user_home, capsys, monkeypatch, tmp_path):  # noqa: F811
    """The console reads it (the page's claude_cli), so it stays after the cut."""
    store, wrote = _fake_loop(monkeypatch)
    exe = _exe(tmp_path / "opt" / "claude-code" / "claude")
    machine = FakeMachine()
    machine.tools.pop("claude")
    host = make_host(user_home, machine)
    code, out = setup(host, "--yes", "--no-start", "--claude", str(exe), "--json", capsys=capsys)
    got = as_json(out)
    assert code == 0, out.err
    assert wrote == [("loop.yaml", ("build", "claude_command"), str(exe))]
    claude = next(c for c in got["checks"] if c["name"] == "claude")
    assert claude["status"] == OK and "build.claude_command" in claude["detail"]
    assert [str(exe), "auth", "status"] in machine.calls
    store["build"] = {"claude_command": str(exe)}
    wrote.clear()
    code, out = setup(host, "--yes", "--no-start", "--json", capsys=capsys)   # setup.json keeps it
    assert code == 0 and wrote == []
    code, out = setup(host, "--yes", "--no-start", "--claude", str(tmp_path / "nope"),
                      "--json", capsys=capsys)
    claude = next(c for c in as_json(out)["checks"] if c["name"] == "claude")
    # the console's (builds left): a warning, Kranto works without it
    assert claude["status"] == WARN and "not an executable file" in claude["detail"]


def test_claude_off_path_is_found_where_the_installers_put_it(user_home):  # noqa: F811
    machine = FakeMachine()
    machine.tools.pop("claude")
    host = make_host(user_home, machine)
    assert preflight.find_claude(host) == (None, "missing")
    versions = user_home / ".local" / "share" / "claude" / "versions"
    _exe(versions / "2.1.9")
    newest = _exe(versions / "2.1.300")
    assert preflight.find_claude(host) == (str(newest), "found")        # no symlink: the newest
    link = user_home / ".local" / "bin" / "claude"
    link.parent.mkdir(parents=True)
    link.symlink_to(newest)
    assert preflight.find_claude(host) == (str(link), "found")
    machine.tools["claude"] = "/usr/bin/claude"
    assert preflight.find_claude(host) == ("/usr/bin/claude", "PATH")


def test_claude_from_npms_global_folder(user_home, tmp_path):  # noqa: F811
    prefix = tmp_path / "npm-global"
    exe = _exe(prefix / "bin" / "claude")
    machine = FakeMachine()
    machine.tools.pop("claude")
    machine.tools["npm"] = "/usr/bin/npm"
    real_run = machine.run

    def run(cmd, timeout=30):
        if Path(cmd[0]).name == "npm":
            machine.calls.append(list(cmd))
            return types.SimpleNamespace(returncode=0, stdout=f"{prefix}\n", stderr="")
        return real_run(cmd, timeout)
    machine.run = run
    host = make_host(user_home, machine)
    assert preflight.find_claude(host) == (str(exe), "found")
    assert ["/usr/bin/npm", "prefix", "-g"] in machine.calls


def test_the_doctor_and_the_unit_use_the_configured_claude(user_home, tmp_path):  # noqa: F811
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    exe = _exe(tmp_path / "nvm" / "bin" / "claude")
    loop_yaml = home / "loop" / "loop.yaml"
    data = yaml.safe_load(loop_yaml.read_text()) or {}
    data["build"] = {"claude_command": str(exe)}
    loop_yaml.write_text(yaml.safe_dump(data))
    assert launcher.configured_claude(home) == str(exe)
    machine = FakeMachine()
    machine.tools.pop("claude")
    checks = {c.name: c for c in launcher.prerequisite_checks(home, make_host(user_home, machine))}
    assert checks["claude"].status == OK and "build.claude_command" in checks["claude"].detail
    unit = launcher.render_unit(home, user_home / ".local" / "bin" / "kranto", 8765, user_home)
    path = next(ln for ln in unit.splitlines() if ln.startswith("Environment=PATH="))
    assert str(exe.parent) in path.split("=", 2)[2].split(":")
    exe.unlink()
    checks = {c.name: c for c in launcher.prerequisite_checks(home, make_host(user_home, machine))}
    assert checks["claude"].status == FAIL and "not an executable file" in checks["claude"].detail


def test_the_unit_has_kranto_own_gh_last_and_nothing_new_without_it(user_home):  # noqa: F811
    from kranto import ghfetch

    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    exe = user_home / ".local" / "bin" / "kranto"
    before = launcher.render_unit(home, exe, 8765, user_home)
    assert "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin\n" in before
    _exe(ghfetch.bin_dir(user_home) / "gh")
    after = launcher.render_unit(home, exe, 8765, user_home)
    assert "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin:" \
           "%h/.local/share/kranto/bin\n" in after


def test_macos_installs_the_watcher_only(user_home, capsys, monkeypatch):  # noqa: F811
    """D12, with a faked uname: no bwrap, Claude Code or systemd checks, brb.enabled false, the
    foreground, no repositories. Not run on a real Mac."""
    monkeypatch.setattr(wizard, "this_system", lambda: "Darwin")
    machine = FakeMachine()
    for n in ("bwrap", "claude", "systemctl"):
        machine.tools.pop(n)
    host = make_host(user_home, machine)
    code, out = setup(host, "--yes", "--no-start", "--json", capsys=capsys)
    got = as_json(out)
    assert code == 0, out.err
    assert wizard.MACOS_NOTE in out.err
    names = {c["name"] for c in got["checks"]}
    assert "macos" in names and "builds" in names
    assert not names & {"bwrap", "claude", "systemd", "linux"}
    assert not [c for c in got["checks"] if c["status"] == FAIL]
    assert got["service"] == "foreground"
    cfg = yaml.safe_load((user_home / ".kranto" / "kranto.yaml").read_text())
    assert cfg["brb"]["enabled"] is False
    assert "skipped on macOS" in out.err
    assert not any(Path(c[0]).name in ("bwrap", "claude") for c in machine.calls)
    code, out = setup(host, "--yes", "--no-start", "--service", "systemd", "--json",
                      capsys=capsys)
    again = as_json(out)
    assert code == 0 and again["service"] == "foreground" and again["written"] == []
    assert "launchd" in out.err


def test_a_foreground_start_prints_the_command_and_sigterm_stops_its_server(user_home, capsys,  # noqa: F811
                                                                            monkeypatch):
    import signal

    class Child:
        terminated = False

        def wait(self, timeout=None):
            if not self.terminated:
                signal.raise_signal(signal.SIGTERM)
            return 0

        def terminate(self):
            self.terminated = True

        def poll(self):
            return 0 if self.terminated else None

    child = Child()
    monkeypatch.setattr(wizard.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(launcher, "_wait_up", lambda host, port, s: True)
    monkeypatch.setattr(launcher, "offer_signin", lambda *a, **k: None)
    host = make_host(user_home)
    before = signal.getsignal(signal.SIGTERM)
    code, out = setup(host, "--yes", "--service", "foreground", "--port", "9042", "--no-browser",
                      capsys=capsys)
    assert code == 0 and child.terminated
    assert "to start it again later: kranto --home ~/.kranto serve --port 9042" in out.out
    assert signal.getsignal(signal.SIGTERM) == before


# -- watching: providers.detect, test and choose (MP D12) ---------------------------------------

def _home_on(api_url, user_home, capsys, monkeypatch):  # noqa: F811
    """A home made by --yes, its Claude API pointed at the fake one."""
    from kranto import config as config_mod
    from kranto import setup as su
    for env in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(env, raising=False)
    host = make_host(user_home)
    assert setup(host, "--yes", "--no-start", capsys=capsys)[0] == 0
    path = config_mod.config_path(user_home / ".kranto")
    su.write_config_values(path, {("llm", "anthropic", "base_url"): api_url})
    return host, path


def _key_file(tmp_path, key):
    f = tmp_path / "model.key"
    f.write_text(key + "\n")
    f.chmod(0o600)
    return f


@pytest.mark.parametrize("by", ["flags", "answers"])
def test_the_claude_api_is_chosen_tested_and_kept_and_a_rerun_writes_nothing(
        user_home, capsys, monkeypatch, tmp_path, by):  # noqa: F811
    from kranto import config as config_mod

    from .fake_anthropic import FakeAnthropic
    api = FakeAnthropic()
    try:
        host, path = _home_on(api.url, user_home, capsys, monkeypatch)
        key = "test-anthropic-" + secrets.token_hex(12)
        api.key = key
        f = _key_file(tmp_path, key)
        if by == "flags":
            argv = ["watching", "--yes", "--watch", "anthropic", "--watch-key-file", str(f)]
        else:
            answers = tmp_path / "answers.yaml"
            answers.write_text(yaml.safe_dump({"watch": {"provider": "anthropic",
                                                         "key_file": str(f)}}))
            argv = ["watching", "--answers", str(answers)]
        code, out = setup(host, *argv, capsys=capsys)
        assert code == 0, out.out
        assert "claude-haiku-5-5 and claude-sonnet-5-5 are offered" in out.out
        assert "llm.provider anthropic, judge claude-haiku-5-5, reason claude-sonnet-5-5" \
            in out.out
        llm = config_mod.load(user_home / ".kranto", dotenv=False).llm
        assert llm.provider == "anthropic" and llm.models == {
            "judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}
        env = user_home / ".kranto" / ".env"
        assert stat.S_IMODE(env.stat().st_mode) == 0o600
        assert f"ANTHROPIC_API_KEY={key}" in env.read_text().splitlines()
        assert key not in out.out + out.err and key not in path.read_text()
        assert key not in (user_home / ".kranto" / "setup.json").read_text()
        sent = len(api.requests)
        before = (path.read_text(), env.read_text())
        code, out = setup(host, "--yes", "--no-start", capsys=capsys)
        assert code == 0 and "kept  watching: Claude API" in out.out
        assert (path.read_text(), env.read_text()) == before and len(api.requests) == sent
    finally:
        api.close()


def test_claude_codes_login_needs_its_terms_agreed_and_is_never_the_default(
        user_home, capsys, monkeypatch):  # noqa: F811
    from kranto import config as config_mod
    from kranto import providers
    from kranto import setup as su

    from .test_claude_code_provider import signed_in
    host, path = _home_on("http://127.0.0.1:9", user_home, capsys, monkeypatch)
    monkeypatch.setattr(su, "RUN", signed_in())
    monkeypatch.setitem(sys.modules, "kranto.page.host_api",
                        types.SimpleNamespace(claude_print=lambda *a, **k: None))
    before = path.read_text()
    code, out = setup(host, "watching", "--yes", "--watch", "claude_code", capsys=capsys)
    assert code == 2 and "--watch-accept-terms" in out.out
    assert path.read_text() == before
    code, out = setup(host, "watching", "--yes", "--watch", "claude_code",
                      "--watch-accept-terms", capsys=capsys)
    assert code == 0, out.out
    assert " ".join(providers.CLAUDE_CODE_TERMS.split()[:8]) in " ".join(out.out.split())
    assert "Claude Code 2.1.300, signed in (claude.ai, max)" in out.out
    llm = config_mod.load(user_home / ".kranto", dotenv=False).llm
    assert llm.provider == "claude_code"
    code, out = setup(host, "--yes", "--no-start", capsys=capsys)
    assert code == 0 and "kept  watching: Claude Code's login" in out.out


def test_the_menu_offers_the_claude_api_first_and_claude_code_with_its_terms(
        user_home, capsys, monkeypatch):  # noqa: F811
    from kranto import config as config_mod
    from kranto import providers
    host, path = _home_on("http://127.0.0.1:9", user_home, capsys, monkeypatch)
    (user_home / ".kranto" / "setup.json").unlink()      # no earlier answer: the first offer
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    replies = iter(["4", "n"])
    asked = []
    monkeypatch.setattr(builtins, "input", lambda p: asked.append(p) or next(replies, ""))
    # the Watching page runs live search too: Enter keeps Exa's free mode, no key
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt: asked.append(prompt) or "")
    before = path.read_text()
    code, out = setup(host, "watching", capsys=capsys)
    assert code == 0
    rows = [ln.strip()[:2] for ln in out.out.splitlines()
            if ln.startswith("  ") and ln.strip()[:2] in ("1 ", "2 ", "3 ", "4 ", "5 ")]
    assert rows == ["1 ", "2 ", "3 ", "4 ", "5 "]
    assert "1 Claude API" in out.out and "4 Claude Code's login" in out.out
    assert "  choice [1]: " in asked                        # never Claude Code by default
    assert any("use your Claude Code login for watching anyway? (y/n) [n]" in p for p in asked)
    assert "not chosen: watching stays as it is" in out.out
    assert " ".join(providers.CLAUDE_CODE_TERMS.split()[:8]) in " ".join(out.out.split())
    assert path.read_text() == before
    assert config_mod.load(user_home / ".kranto", dotenv=False).llm.provider is None


# -- sources: X -------------------------------------------------------------------


def _x_running(monkeypatch):
    calls = []

    def api(run, method, path, body=None):
        calls.append((method, path, body))
        return {"ok": True, "message": "Saved. Now click Connect."}
    monkeypatch.setattr(wizard, "_api", api)
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(launcher, "_wait_up", lambda host, port, s: True)
    return calls


def test_sources_with_yes_and_no_client_id_connects_nothing(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--json", capsys=capsys)
    assert code == 0
    assert any("X is not connected" in k for k in as_json(out)["kept"])


def test_the_x_client_id_goes_to_the_running_kranto_and_then_the_browser(user_home,  # noqa: F811
                                                                        capsys, monkeypatch):
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    calls = _x_running(monkeypatch)
    code, out = setup(host, "sources", "--x-client-id", "abcDEF123_-xyz789", capsys=capsys)
    assert code == 0, out.out
    assert calls == [("POST", "/api/connections/x/credentials",
                      {"client_id": "abcDEF123_-xyz789"})]
    assert "/#/settings/connections/x" in out.out and "127.0.0.1, not localhost" in out.out
    saved = json.loads((user_home / ".kranto" / wizard.SETUP_FILE).read_text())
    assert "abcDEF123" not in json.dumps(saved)                # the id is not in setup.json


def test_an_interactive_run_shows_the_cost_and_the_exact_callback(user_home, capsys,  # noqa: F811
                                                                  monkeypatch):
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    calls = _x_running(monkeypatch)
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    typed = iter(["y", "abcDEF123_-xyz789"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(typed, ""))
    code, out = setup(host, "sources", capsys=capsys)
    assert code == 0, out.out
    assert "$0.005" in out.out and "$46 a month" in out.out
    assert "Native App" in out.out and "http://127.0.0.1:8765/connections/x/callback" in out.out
    assert calls and calls[0][2] == {"client_id": "abcDEF123_-xyz789"}


def test_the_x_cap_is_offered_only_with_x_and_set_only_when_typed(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", capsys=capsys)
    cfg = yaml.safe_load((user_home / ".kranto" / "kranto.yaml").read_text())
    assert (cfg.get("x") or {}).get("monthly_usd") is None    # uncapped by default
    code, out = setup(host, "caps", "--cap-x", "40", capsys=capsys)
    assert code == 0 and "x.monthly_usd none -> 40" in out.out
    cfg = yaml.safe_load((user_home / ".kranto" / "kranto.yaml").read_text())
    assert cfg["x"]["monthly_usd"] == 40.0


# -- Ready: the three things, in the terminal ----------------------------------------


def test_a_core_setup_asks_what_welcome_asks_and_ends_with_ready(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", capsys=capsys)
    assert code == 0
    text = out.out
    assert "Ready" in text and "What it costs   About $5 to $8 a month" in text
    assert "No cap is set; set one in Spend." in text
    assert "Claude Code     installed and signed in" in text        # the fake machine has it
    assert "Usage reports   nothing is sent unless you choose" in text
    # no builds' question: the Claude plan for builds is skipped, GitHub and repositories too
    # no builds' question and no build word (the deferred words;)
    words = text.replace(str(user_home), "~")          # the paths are the test's own
    assert "build" not in words.lower() and "Publishing › GitHub" not in words
    assert "Building ›" not in words
    assert "builds a day" not in text and "home (settings, library, builds)" not in text
    assert text.index("Ready") > text.index("Sources › Topics")


def test_ready_says_claude_code_is_not_installed_and_how_and_starts_nothing_without_kranto(
        user_home, capsys):  # noqa: F811
    machine = FakeMachine()
    machine.tools.pop("claude")
    host = make_host(user_home, machine)
    setup(host, "--yes", "--no-start", capsys=capsys)
    code, out = setup(host, "ready", capsys=capsys)
    assert code == 0
    assert "Claude Code     not installed; Kranto works without it" in out.out
    assert "curl -fsSL https://claude.ai/install.sh | bash" in out.out
    assert "first read: when Kranto runs" in out.out
