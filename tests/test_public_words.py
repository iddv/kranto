"""The first screen a stranger reads says what Kranto does in plain words.

The README's first screen (everything before its second ``##`` heading) and each top-level
``docs/*.md`` page's first screen (everything before its second heading) carry none of the
words below, and no exclamation mark. The words are marketing, the vocabulary of other kinds of
product (each invites a comparison that was never run), or names the page no longer uses.
Text in code (fenced blocks and inline spans) is not read. Further down a page these words may
be the right ones, for example in the archive of features that left.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

AVOID = (
    "autonomous", "agentic", "agent", "agents", "AI-powered", "second brain", "10x",
    "supercharge", "supercharges", "supercharged", "factory", "builds", "news radar",
    "AI news digest", "AI RSS reader", "Claude Code UI", "Claude Code for the web",
    "newsletter tool", "social scheduler", "open-source alternative", "open source alternative",
    "cubs", "tickets",
)

# A page whose subject is one of the words, and why it may say it on its first screen.
ALLOWED: dict[str, dict[str, str]] = {
    "docs/archive.md": {"builds": "the record of the features that left, builds among them"},
    "docs/cubs.md": {"cubs": "the extension's technical name (kranto cub, the cub SDK)"},
    "docs/cub-protocol.md": {"cubs": "the protocol between Kranto and a cub's process"},
    "docs/features.md": {"cubs": "how Kranto is extended, cubs among the ways"},
    "docs/newsletter.md": {"cubs": "the newsletter is sent by a cub"},
}

# Pages this test does not read.
SKIP = {
    "docs/posting.md": "owned by the posting work",
}

_FENCE = re.compile(r"^(```|~~~)")
_HEADING = re.compile(r"^(#{1,6}) ")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_IMAGE = re.compile(r"!\[")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _word_re(word: str) -> re.Pattern[str]:
    body = r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", word))
    return re.compile(r"(?<![\w-])" + body + r"(?![\w-])", re.I)


_AVOID_RE = {w: _word_re(w) for w in AVOID}


def first_screen(text: str, level2_only: bool) -> str:
    """The lines before the second heading (of level 2 only, for the README), outside code
    fences."""
    out: list[str] = []
    seen = 0
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line.lstrip()):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING.match(line)
        if m and (not level2_only or len(m.group(1)) == 2):
            seen += 1
            if seen == 2:
                break
        out.append(line)
    return _CODE_SPAN.sub("", _HTML_COMMENT.sub("", "\n".join(out)))


def problems(rel: str, screen: str) -> list[str]:
    allowed = ALLOWED.get(rel, {})
    found = [f"{rel}: '{w}'" for w, rx in _AVOID_RE.items()
             if w not in allowed and rx.search(screen)]
    if "!" in _IMAGE.sub("", screen).replace("!=", ""):
        found.append(f"{rel}: an exclamation mark")
    return found


def _pages() -> list:
    pages = [pytest.param("README.md", True, id="README.md")]
    for p in sorted((ROOT / "docs").glob("*.md")):
        rel = p.relative_to(ROOT).as_posix()
        if rel not in SKIP:
            pages.append(pytest.param(rel, False, id=rel))
    return pages


@pytest.mark.parametrize("rel,level2_only", _pages())
def test_first_screen_words(rel, level2_only):
    text = (ROOT / rel).read_text(encoding="utf-8")
    found = problems(rel, first_screen(text, level2_only))
    assert found == [], "words to avoid on a first screen:\n" + "\n".join(found)


def test_the_check_would_catch_one():
    page = "# T\n\nAn AI-powered second brain! Agents run it.\n\n## Next\n\nautonomous\n"
    found = problems("docs/x.md", first_screen(page, False))
    assert any("AI-powered" in f for f in found)
    assert any("second brain" in f for f in found)
    assert any("'agents'" in f for f in found)
    assert any("exclamation" in f for f in found)
    assert not any("autonomous" in f for f in found)  # past the second heading


def test_code_and_allowed_forms_are_quiet():
    page = ("# T\n\nRun `kranto builds --agent` here. The agenda, a buildstep, an image:\n"
            "![the mark](mark.svg)\n\n```\necho hi!\n```\n## Next\n")
    assert problems("docs/x.md", first_screen(page, False)) == []
    readme = "# K\n\nIntro.\n\n### Small\n\nStill the first screen.\n\n## Two\n\n## Three agentic\n"
    screen = first_screen(readme, True)
    assert "Still the first screen" in screen and "agentic" not in screen
