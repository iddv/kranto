"""What the install walk found in ``kranto doctor`` and ``kranto status``:
another home's service described as this one's, raw gh stderr, a world-readable config
folder, a bwrap check weaker than the sandbox, and a claude FAIL that named no installer."""

from __future__ import annotations

from pathlib import Path

from kranto import launcher
from kranto.launcher import WARN

from .test_kranto import FakeMachine, ServiceMachine, by_name, make_host, user_home  # noqa: F401

GH_NO_LOGIN = ("To get started with GitHub CLI, please run:  gh auth login\nAlternatively, "
               "populate the GH_TOKEN environment variable with a GitHub API authentication "
               "token.")


def test_service_env_never_reads_another_homes_service(user_home, monkeypatch):  # noqa: F811
    """From a HOME the user manager does not see (the rc check's scratch home, the install
    walk), systemctl --user describes the login home's kranto.service: never ask it."""
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    host = make_host(user_home, ServiceMachine(1), login_home=user_home / "login")
    env, where = launcher.service_env(host)
    assert where.startswith("this shell")
    assert not any(c[:3] == ["systemctl", "--user", "show"] for c in host.machine.calls)
    assert "running" not in where


def test_service_env_asks_for_the_named_unit(user_home, monkeypatch):  # noqa: F811
    monkeypatch.setattr(launcher, "UNIT", "kranto-test.service")
    host = make_host(user_home, ServiceMachine(0))
    launcher.service_env(host)
    shows = [c for c in host.machine.calls if c[:3] == ["systemctl", "--user", "show"]]
    assert shows and all(c[-1] == "kranto-test.service" for c in shows)


def test_service_env_asks_for_an_old_installs_unit_when_only_it_is_installed(
        user_home, monkeypatch):  # noqa: F811
    """An install made before the rename keeps running as its old unit: with no unit named,
    the doctor reads that one (the console's token is in its environment), not this shell."""
    from kranto import legacy

    monkeypatch.setattr(launcher, "UNIT", launcher.DEFAULT_UNIT)
    host = make_host(user_home, ServiceMachine(0))
    host.unit_dir.mkdir(parents=True, exist_ok=True)
    (host.unit_dir / legacy.UNIT).write_text("[Service]\nEnvironment=CLAUDE_CODE_OAUTH_TOKEN=x\n")
    env, where = launcher.service_env(host)
    shows = [c for c in host.machine.calls if c[:3] == ["systemctl", "--user", "show"]]
    assert shows and all(c[-1] == legacy.UNIT for c in shows)
    assert legacy.UNIT in where
    (host.unit_dir / launcher.DEFAULT_UNIT).write_text("[Service]\n")   # both: the new one
    launcher.service_env(host)
    assert host.machine.calls[-1][-1] == launcher.DEFAULT_UNIT or any(
        c[-1] == launcher.DEFAULT_UNIT for c in host.machine.calls
        if c[:3] == ["systemctl", "--user", "show"])


def test_the_config_folder_and_pointer_are_private(user_home):  # noqa: F811
    folder = user_home / ".config" / "kranto"
    folder.mkdir(parents=True)
    folder.chmod(0o775)                               # as remember_home used to leave it
    pointer = launcher.remember_home(user_home / ".kranto", user_home)
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    assert oct(pointer.stat().st_mode & 0o777) == "0o600"
    launcher.remember_home(user_home / ".kranto", user_home)
    assert oct(pointer.stat().st_mode & 0o777) == "0o600"


def test_the_bwrap_check_is_the_sandboxs_own_invocation(user_home, monkeypatch):  # noqa: F811
    host = make_host(user_home)
    launcher.prerequisite_checks(user_home, host)
    probe = next(c for c in host.machine.calls if Path(c[0]).name == "bwrap")
    assert "--unshare-all" in probe and probe[probe.index("--proc") + 1] == "/proc"
    machine = FakeMachine(rc={"bwrap": 1})
    monkeypatch.setattr(launcher, "userns_reason", lambda: "AppArmor restricts it")
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home, machine)))
    assert checks["bwrap"].status == WARN and "AppArmor restricts it" in checks["bwrap"].detail


def test_userns_reason_reads_the_kernel_knobs(tmp_path):
    (tmp_path / "kernel").mkdir()
    (tmp_path / "kernel" / "apparmor_restrict_unprivileged_userns").write_text("1\n")
    assert "AppArmor" in launcher.userns_reason(tmp_path)
    (tmp_path / "kernel" / "unprivileged_userns_clone").write_text("0\n")
    assert "unprivileged_userns_clone" in launcher.userns_reason(tmp_path)
    assert "container" in launcher.userns_reason(tmp_path / "none")


def test_the_claude_warning_names_the_installer(user_home, monkeypatch):  # noqa: F811
    machine = FakeMachine()
    machine.tools.pop("claude")
    # a warn, Kranto works without it, the console's line
    checks = by_name(launcher.prerequisite_checks(user_home, make_host(user_home, machine)))
    assert checks["claude"].status == launcher.WARN
    assert "Kranto works without it" in checks["claude"].detail
    assert launcher.CLAUDE_INSTALL in checks["claude"].detail
    # one installer, the one Ready names: no "or npm install -g" beside it
    assert "npm" not in checks["claude"].detail


def test_raw_gh_stderr_is_one_line(user_home, monkeypatch):  # noqa: F811
    from kranto.update.sources import gh_error

    assert gh_error(f"gh api: {GH_NO_LOGIN}") == "gh api: gh is not logged in (gh auth login)"
    assert gh_error("HTTP 404: Not Found. More text here") == "HTTP 404: Not Found"
    # the doctor's gh line never prints gh's own words: one line of Kranto's (a warn)
    machine = FakeMachine(rc={"gh": 1})
    c = by_name(launcher.prerequisite_checks(user_home, make_host(user_home, machine)))["gh"]
    assert (c.status, c.detail) == (WARN, launcher.GH_NOT_LOGGED_IN)


def test_the_update_line_is_one_line(tmp_path, monkeypatch):
    from kranto.update import check

    monkeypatch.setattr(check, "read_json", lambda p, d=None: {
        "checked_at": "2026-10-17T00:00:00Z", "ok": False, "error": f"gh api: {GH_NO_LOGIN}"})
    monkeypatch.setattr(check, "installed_here", lambda: {"version": "0.3.80",
                                                          "channel": "stable"})
    monkeypatch.setattr(check, "apply_state", lambda home: {"state": "idle"})
    line = check.status_line(tmp_path)
    assert "\n" not in line and line.endswith("gh api: gh is not logged in (gh auth login)")
