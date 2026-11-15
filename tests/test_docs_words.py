"""The docs say where things are with the doors: the places the doors
retired (Today, Library, Desk, Work, Maintenance as a place, Connections, Home and feed, the
side bar) appear only in the history and design notes. A doc that names one sends a stranger
to a page that is no longer there."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY = {"docs/design/DESIGN.md", "docs/design/DECISIONS.md", "docs/OPERATING.md"}

RETIRED = re.compile("|".join((
    r"Settings › Sources", r"Settings › Connections", r"^#+ Connections\b", r"Home and feed",
    r"\bWork ›", r"\bDesk ›", r"\bLibrary ›", r"\bMaintenance ›", r"\bthe Today page",
    r"\bToday's Needs you", r"\bon Today\b", r"\bin the side bar\b", r"!\[Today\b")), re.M)


def _docs():
    yield ROOT / "README.md"
    for p in sorted((ROOT / "docs").rglob("*.md")):
        if p.relative_to(ROOT).as_posix() not in HISTORY:
            yield p


def test_no_doc_sends_you_to_a_retired_place():
    found = []
    for p in _docs():
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if RETIRED.search(line):
                found.append(f"{p.relative_to(ROOT).as_posix()}:{n}: {line.strip()[:100]}")
    assert found == [], "a retired place in the docs:\n" + "\n".join(found)


def test_the_check_would_catch_one():
    for line in ("Open **Work › Ideas**", "Settings › Sources › Accounts › X", "## Connections",
                 "Settings › Home and feed", "on Today or in Health"):
        assert RETIRED.search(line), line
    for line in ("News › Today", "Settings › Accounts › X", "Watch › Evidence", "Needs you",
                 "maintained repositories", "the library"):
        assert not RETIRED.search(line), line


def test_setup_names_needs_you_where_you_land():
    text = (ROOT / "docs/setup.md").read_text(encoding="utf-8")
    seen = [line for line in text.splitlines() if line.startswith("**You should see:** the home")]
    assert seen and "Needs you" in seen[0]
