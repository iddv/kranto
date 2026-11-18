"""What the command line says reads as Kranto now: no damage left by the rename, no feature that
left, in any string literal Kranto's server code holds (not only comments). And the update
check says what GitHub's rate limit is, when it lifts and the way round it."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from kranto import legacy
from kranto.update import sources

SRC = Path(__file__).resolve().parents[1] / "src" / "kranto"

# the rename's damage, each as a stranger met it (a case-sensitive regex)
DAMAGE = {
    r"uninstall Kranto\b": "the tool is 'kranto', lower case",
    r"Kranto's needs": "garbled possessive",
    r"\{Kranto,afk,brb\}": "programs that are not installed",
    r"\bthe server \d": "the product's version reads as 'the server 0.7.0'",
    r"\bthe kranto (?:read|watch)": "an old plural noun renamed",
    r"next promotion": "nothing is promoted; a stable release is published",
    r"; limits: (?:scope|rlimits)\b": "an internal word",
    r"[Bb]uilds and Open in Claude Code": "builds left Kranto",
    r"builds need Linux": "builds left Kranto",
    r"kranto restart\b": "no such command",
}
# where the page's source keeps its own words (another test's), and data kept verbatim
SKIP = ("page/ui/web/", "prompts/")


def _literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(v.value if isinstance(v, ast.Constant) else "{}"
                                       for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def test_no_string_literal_carries_the_renames_damage():
    bad = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(SKIP):
            continue
        for n, text in _literals(path):
            for pattern, why in DAMAGE.items():
                if re.search(pattern, text):
                    bad.append(f"{rel}:{n}: {pattern!r} ({why}): {text[:100]!r}")
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("text,found", [
    ("removed the program (uv tool uninstall Kranto)", True),
    ("uv tool upgrade Kranto's needs it", True),
    ("answering (the server 0.7.0.dev2, scheduler on)", True),
    ("answering (Kranto 0.7.0.dev2, scheduler on)", False),
    ("uv tool uninstall kranto", False),
])
def test_the_damage_patterns_themselves(text, found):
    assert any(re.search(p, text) for p in DAMAGE) is found


def test_the_old_cli_module_docstring_names_the_command():
    from kranto import cli
    assert "kranto watch" in (cli.__doc__ or "")
    assert legacy.COMMANDS[1] not in (cli.__doc__ or "").split()


# -- S13: GitHub's rate limit --------------------------------------------------------------------

def test_an_anonymous_rate_limit_says_what_when_and_the_way_round():
    said = sources.rate_limited(403, {"X-RateLimit-Remaining": "0",
                                      "X-RateLimit-Reset": "1800000000"}, False)
    assert "limit on requests without a login" in said and "60 an hour" in said
    assert re.search(r"lifts at \d\d:\d\d", said) and "gh auth login" in said


def test_a_signed_in_rate_limit_and_a_retry_after():
    said = sources.rate_limited(429, {"retry-after": "120"}, True, now=0)
    assert "rate limit for this login" in said and "lifts at" in said
    assert "within the hour" in sources.rate_limited(403, {"x-ratelimit-remaining": "0"}, False)


def test_another_403_is_not_called_a_rate_limit():
    assert sources.rate_limited(403, {"x-ratelimit-remaining": "42"}, False) == ""
    assert sources.rate_limited(500, {"x-ratelimit-remaining": "0"}, False) == ""


def test_the_release_check_raises_the_rate_limit_words():
    gh = sources.GitHubReleases(
        "o/r", which=lambda n: None,
        http_get=lambda url, headers: (403, {"x-ratelimit-remaining": "0",
                                             "x-ratelimit-reset": "1800000000"}, b"{}"))
    with pytest.raises(sources.SourceError) as e:
        gh.releases()
    assert "limit on requests without a login" in str(e.value)
    assert "GitHub answered 403" not in str(e.value)
