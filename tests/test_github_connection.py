"""Kranto's own GitHub connection left with builds: the update source and Welcome's gh row
read gh's own login (or ``update.token_env_file``), and never ask the page, even one from before
the cut that still has the connection."""

from __future__ import annotations

from kranto import setup
from kranto.update import check, sources

from . import brbfake


def test_no_connection_is_asked_for_even_from_an_old_page(tmp_path, monkeypatch):
    def asked():
        raise AssertionError("the page's GitHub connection was asked")
    brbfake.install(monkeypatch, github_user_file=asked, github_user_status=asked)
    assert sources.connection_file() is None and setup.connection() is None
    assert check.settings(tmp_path).token_env_file is None
    (tmp_path / "kranto.yaml").write_text("update:\n  token_env_file: ~/my.env\n")
    assert check.settings(tmp_path).token_env_file == "~/my.env"     # the owner's choice


def test_welcomes_gh_row_is_gh_s_own_login():
    row = setup._gh(0, "github.com\n  ✓ Logged in to github.com account ann (keyring)")
    assert row["ok"] and "signed in to github.com as ann" in row["detail"]
    assert not setup._gh(1, "You are not logged into any GitHub hosts")["ok"]
    assert not setup._gh(127, "")["ok"]
