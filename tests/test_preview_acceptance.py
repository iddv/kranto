"""scripts/preview/acceptance.py (the first process change; a review's fix 16): the parts
that need no browser. The script itself runs against a preview, never in the tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preview" / "acceptance.py"


def _module():
    import sys
    spec = importlib.util.spec_from_file_location("preview_acceptance", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m              # a dataclass looks its module up by name
    spec.loader.exec_module(m)
    return m


def test_the_word_test_is_osw1s_with_cub():
    m = _module()
    for said in ("Step 3 asks when Kranto may build", "every feature and cub has its own page",
                 "Your broker", "builds $0.00 · pitches, checks", "Build the map now",
                 "a cub drafts a post"):
        assert m.WORDS.search(said), said
    for fine in ("The first brief is written right after the first read", "Map now", "Post",
                 "Kranto drafts a post"):
        assert not m.WORDS.search(fine), fine


def test_it_plays_every_wave_2_package_and_a_failure_fails():
    m = _module()
    src = SCRIPT.read_text()
    for fn in ("prev_lines", "hour_lines", "post_lines", "shell_lines", "word_test", "counts"):
        assert callable(getattr(m, fn)), fn
    for line in ("PREVIEW-1", "PREVIEW-4", "START-1", "DRAFTS-1", "DRAFTS-2", "SHELL-1", "SHELL-3",
                 "SHELL-5", "SHELL-6", "SHELL-7", "COUNT card"):
        assert f'"{line}' in src, line
    assert m.ok("X", "w", False, "s").state == "fail" and m.skip("X", "w", "why").state == "skip"
    assert "return 1 if n[\"fail\"] else 0" in src


def test_it_plays_the_testers_items_and_the_site_name_test_catches_it():
    """A's items a page shows without a press and B's words (? keys, ⌘K, Prompts, the
    site's name), on the copy and, signed out, on the fresh home"""
    m = _module()
    src = SCRIPT.read_text()
    for fn in ("fixes_lines", "fresh_lines"):
        assert callable(getattr(m, fn)) and f"results += {fn}(" in src, fn
    assert m.SITE.search("Post to example.com asks") and m.SITE.search("by examplecom")
    assert not m.SITE.search("Blog")


def test_the_toot_redirect_is_measured_where_it_lands():
    """#/settings/toot lands on Posting once the features' list is read: the check waits for the
    address instead of reading it the moment the old page drew"""
    m = _module()

    class Page:
        def __init__(self, moves_after: int):
            self.n, self.moves_after = 0, moves_after

        @property
        def url(self) -> str:
            return ("http://127.0.0.1:1/#/settings/posting" if self.n >= self.moves_after
                    else "http://127.0.0.1:1/#/settings/toot")

        def wait_for_timeout(self, ms: int) -> None:
            self.n += 1

    assert m.landed_at(Page(3), "/settings/posting") == "/settings/posting"
    assert m.landed_at(Page(10 ** 9), "/settings/posting", wait_s=0.05) == "/settings/toot"
    src = SCRIPT.read_text()
    assert 'landed = landed_at(pg, "/settings/posting")' in src


def test_it_reads_only():
    """every request but a GET is aborted in the page; nothing is clicked but Write a post's
    question (which asks nothing of the server) and the phone's ✦"""
    src = SCRIPT.read_text()
    assert 'if r.method in ("GET", "HEAD"):' in src and "route.abort()" in src
    assert ".post(" not in src and "request.post" not in src
