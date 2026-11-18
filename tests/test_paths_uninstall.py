"""``kranto paths`` and ``kranto uninstall --program --data`` (the owner's D11), in
a scratch HOME with a fake machine: the data goes only after the home's path is typed, never
the user's home, and nothing on GitHub is touched."""

from __future__ import annotations

import sqlite3

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
    assert "Your data is deleted." in out
    assert "github.com" not in out          # this home never connected GitHub
    assert user_home.is_dir()


def test_githubs_pages_only_for_a_home_that_connected_it(user_home, installed, capsys):  # noqa: F811
    from kranto.store import Store

    host = make_host(user_home)
    db = installed / "data" / "kranto.db"
    Store.open(db).close()
    assert launcher.main(["uninstall"], host) == 0
    assert "github.com" not in capsys.readouterr().out
    with sqlite3.connect(db) as con:           # a GitHub connection made once (rows stay)
        con.execute("INSERT INTO connections (provider, instance, account, scopes, created_at) "
                    "VALUES ('github', 'github.com', 'someone', '', '2026-11-18T00:00:00Z')")
    con.close()
    assert launcher.main(["uninstall"], host) == 0
    out = capsys.readouterr().out
    assert "On GitHub, if you want: Kranto's GitHub connection: revoke it at " \
           "https://github.com/settings/applications" in out


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
