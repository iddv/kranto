"""Kranto's own repositories are named in one place (``src/kranto/page/upstream.py``), so moving the
project changes one line."""
import re
from pathlib import Path

from kranto.page.settings.store import DEFAULTS
from kranto.page.upstream import REPOS

PKG = Path(__file__).resolve().parents[2] / "src" / "kranto" / "page"


def test_kranto_own_repositories_are_named_once():
    literal = re.compile(r"[\"'][\w-]+/kranto(brb|afk)[\"']")
    hits = [f"{p.relative_to(PKG)}:{n}" for p in sorted(PKG.rglob("*.py"))
            if p.name != "upstream.py"
            for n, line in enumerate(p.read_text().splitlines(), 1) if literal.search(line)]
    assert hits == []
    assert DEFAULTS["feedback"]["repo"] == REPOS["watcher"]

