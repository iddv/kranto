"""The docs describe Kranto as it is: no page, route, setting or sentence of what left the product.

Building software (builds, projects, repository maintenance, pitches, the weekly editor and the
build loop that ran them), Invest and the trend radar left Kranto. Their pages redirect
(``src/kranto/page/ui/web/src/lib/nodes.json``: ``build``, ``builds``, ``projects``, ``invest``,
``settings/building``, ``settings/publishing``, ``settings/projects``, ``settings/tools``,
``welcome/building``, ``topics/:id/builds``; Health moved under Settings › System, Models into
Settings › Watching). A doc that still sends a reader to one of them, or describes the build loop
as running, is out of date.

A paragraph, list item or table row may name one of them when it says that it left (``left``,
``retired``, ``not part of Kranto``, ``gone``, ``from before``, ``any more``, ``no longer``): that
is the record of what left, not a description of the product. Not read: the design notes and
release notes (history, kept as written) and the usage-report field list (generated from the
code's allow-list, ``tests/test_telemetry.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONT = ("README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md",
         "src/kranto/page/ui/help.md")
NOT_READ = ("docs/design/", "docs/releases/", "docs/privacy/")

RETIRED = re.compile("|".join((
    # pages that left, by the names the page gave them
    r"Settings › (Building|Publishing|Build tools|Projects|Maintenance|Health|Models|Learning)\b",
    r"Settings › Watching › Models", r"\bBuild ›", r"\bthe Health page\b", r"\bthe Map page\b",
    # their addresses (nodes.json redirects every one)
    r"#/(build|builds|projects|invest)\b", r"#/settings/(building|publishing|projects|tools)\b",
    r"#/welcome/(building|publishing|repos)\b", r"#/topics/[^/\s]+/builds\b",
    # what served building
    r"\bthe build loop\b", r"\bbuilds UI\b", r"\bKranto's GitHub App\b",
    r"From the next (build|publish)\b", r"\bNew idea from this\b",
)), re.I)
SAYS_IT_LEFT = re.compile(r"\b(left|retired|not part of Kranto|gone|from before|any more|"
                          r"no longer)\b", re.I)
_BLOCK_START = re.compile(r"^(\||#|\s*([-*]|\d+\.)\s)")


def blocks(text: str) -> list[tuple[int, str]]:
    """``(first line, text)`` of each paragraph, list item, table row and heading."""
    out: list[tuple[int, list[str]]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            out.append((n + 1, []))
        elif _BLOCK_START.match(line) or not out:
            out.append((n, [line]))
        else:
            out[-1][1].append(line)
    return [(n, "\n".join(lines)) for n, lines in out if lines]


def stale(text: str) -> list[tuple[int, str]]:
    return [(n, RETIRED.search(b).group(0)) for n, b in blocks(text)  # type: ignore[union-attr]
            if RETIRED.search(b) and not SAYS_IT_LEFT.search(b)]


def _docs() -> list[Path]:
    pages = [ROOT / p for p in FRONT]
    for p in sorted((ROOT / "docs").rglob("*.md")):
        if not p.relative_to(ROOT).as_posix().startswith(NOT_READ):
            pages.append(p)
    return pages


def test_no_doc_describes_what_left_as_part_of_kranto():
    found = [f"{p.relative_to(ROOT).as_posix()}:{n}: {what}" for p in _docs()
             for n, what in stale(p.read_text(encoding="utf-8"))]
    assert found == [], "a doc describes what left Kranto:\n" + "\n".join(found)


def test_the_check_would_catch_one():
    for text in ("Paused: watching paused, or the build loop paused.",
                 "Both are set under Settings › Watching › Models.",
                 "Check the Health page for which runs spent it.",
                 "Open #/builds to see them.", "Then **Settings › Building**.",
                 "- **When**: \"From the next build.\" or \"Applies at once.\""):
        assert stale(text), text


def test_the_record_of_what_left_is_allowed():
    for text in ("Builds left Kranto: #/builds lands on the home.",
                 "**What left.** Building software (builds and the build loop\nthat ran them).",
                 "Settings › System › Health shows the runs.", "Watch › Map says how many."):
        assert stale(text) == [], text
    # one block's word does not excuse the next block
    assert stale("Builds left Kranto.\n\nThe build loop runs every minute.")
