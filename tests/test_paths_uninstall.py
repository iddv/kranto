"""``kranto paths`` and ``kranto uninstall --program --data`` (the owner's D11), in
a scratch HOME with a fake machine: the data goes only after the home's path is typed, never
the user's home, and nothing on GitHub is touched."""

from __future__ import annotations

import pytest

from kranto import launcher

from .test_kranto import make_host, user_home  # noqa: F401


@pytest.fixture
def installed(user_home):  # noqa: F811
    home = user_home / ".kranto"
    launcher.make_home(home, 8765, user_home)
    launcher.remember_home(home, user_home)
    (user_home / ".cache" / "kranto").mkdir(parents=True)
    (user_home / ".cache" / "kranto" / "x").write_text("cache")
    return home


def test_paths_names_every_place_with_its_size(user_home, installed, capsys):  # noqa: F811
    assert launcher.main(["paths"], make_host(user_home)) == 0
    out = capsys.readouterr().out
    labels = [line.split()[0] for line in out.splitlines()]
    assert labels == ["home", "config", "service", "program", "commands", "cache"]
    assert "~/.kranto" in out and "(none)" in out.splitlines()[2]       # no unit yet


def test_data_goes_only_after_the_home_is_typed(user_home, installed, capsys):  # noqa: F811
    host = make_host(user_home)
    assert launcher.main(["uninstall", "--data", "--confirm", str(user_home / "elsewhere")],
                      host) == 2
    assert installed.is_dir()
    assert launcher.main(["uninstall", "--data", "--confirm", str(installed)], host) == 0
    out = capsys.readouterr().out
    assert not installed.exists() and not (user_home / ".config" / "kranto").exists()
    assert not (user_home / ".cache" / "kranto").exists()
    assert "https://github.com/settings/applications" in out and "Your data is deleted." in out
    assert user_home.is_dir()


def test_the_users_home_is_never_removed(user_home, capsys):  # noqa: F811
    (user_home / "kranto.yaml").write_text("brb:\n  enabled: false\n")
    host = make_host(user_home)
    code = launcher.main(["--home", str(user_home), "uninstall", "--data", "--confirm",
                       str(user_home)], host)
    assert code == 2 and (user_home / "kranto.yaml").exists()


def test_program_runs_uv_tool_uninstall(user_home, installed, capsys):  # noqa: F811
    host = make_host(user_home)
    assert launcher.main(["uninstall", "--program"], host) == 0
    assert ["/usr/bin/uv", "tool", "uninstall", "kranto"] in host.machine.calls
    assert installed.is_dir() and "Your data is kept" in capsys.readouterr().out
