"""What a user reads carries no internal references: no private plan citations (``X-PLAN``,
``§``), no track codes (``track OI``, ``(OI)``), no "example-host" and no personal paths. Checked:
every ``brb`` help text, the page's strings (``app.js``), the help page (``help.md``) and the
files Kranto writes into a product's repo (``maintain/templates``)."""
import argparse
import re
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "src" / "kranto" / "page"
# ~/kranto-loop is the loop's documented default home, not a personal path
INTERNAL = re.compile(r"\b[A-Z][A-Z0-9]*-PLAN\b|§|\btrack [A-Z]{1,3}\b|\((?!USD\))[A-Z]{1,3}\)"
                      r"|homelab|/home/|~/brb-(?!loop\b)")
# Help texts allowed to match, and why: the research commands' own default folders (they move
# with the research code).
ALLOWED = {"default: $KRANTO_BENCH or ~/brb-bench",
           "default: ~/work/v3/scratch/prompteval"}


def offending(text: str) -> list[str]:
    return [m.group(0) for m in INTERNAL.finditer(text or "") if text not in ALLOWED]


def js_strings(src: str) -> list[str]:
    """The string and template literals of a script, comments skipped (a small scanner: enough
    for app.js, which has no regex literal containing a quote)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
        elif src.startswith("/*", i):
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif c in "'\"`":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            i += 1
    return out


class _Captured(Exception):
    def __init__(self, parser):
        self.parser = parser


def brb_parser(monkeypatch) -> argparse.ArgumentParser:
    from kranto.page import cli

    def capture(self, *a, **k):
        raise _Captured(self)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    with pytest.raises(_Captured) as e:
        cli.main(["--help"])
    return e.value.parser


def help_texts(p: argparse.ArgumentParser, where: str = "brb"):
    for t in (p.description, p.epilog):
        if t:
            yield where, t
    for a in p._actions:
        if a.help and a.help != argparse.SUPPRESS:
            yield f"{where} {'/'.join(a.option_strings) or a.dest}", str(a.help)
        if isinstance(a, argparse._SubParsersAction):
            for ch in a._choices_actions:
                if ch.help:
                    yield f"{where} {ch.dest}", ch.help
            for name, sp in a.choices.items():
                yield from help_texts(sp, f"{where} {name}")


def test_brb_help_has_no_internal_references(monkeypatch):
    bad = [(w, t[:120]) for w, t in help_texts(brb_parser(monkeypatch)) if offending(t)]
    assert bad == []


def svelte_text(src: str) -> list[str]:
    """What a component shows: its markup's text and attributes, comments out, then its
    script's string literals."""
    script = "".join(re.findall(r"<script[^>]*>(.*?)</script>", src, re.S))
    markup = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>|<!--.*?-->", "", src, flags=re.S)
    return [markup, *js_strings(script)]


def test_the_page_and_the_help_page_have_no_internal_references():
    # the scripts' literals (the .ts modules and the tips' words); a component's text below
    src = PKG / "ui" / "web" / "src"
    scripts = [src / "ui" / "tips.json", *(p for p in sorted(src.rglob("*.ts"))
                                          if not p.name.endswith((".test.ts", ".gen.ts", ".d.ts")))]
    strings = js_strings("\n".join(p.read_text() for p in scripts))
    assert len(strings) > 1000                        # the scanner read the page
    assert [s[:120] for s in strings if offending(s)] == []
    shown = [t for f in sorted((PKG / "ui" / "web" / "src").rglob("*.svelte")) for t in svelte_text(f.read_text())]
    assert len(shown) > 50
    assert [t[:120] for t in shown if offending(t)] == []
    help_md = (PKG / "ui" / "help.md").read_text()
    assert [ln[:120] for ln in help_md.splitlines() if offending(ln)] == []


ROOT = PKG.parents[2]


def test_no_tracked_file_carries_the_owners_home():
    """Not even the research record: paths there are written /home/user."""
    import subprocess
    home = "/home/" + "jo-example"
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True,
                           text=True, check=True).stdout.split()
    bad = [f for f in files if (ROOT / f).is_file()
           and home.encode() in (ROOT / f).read_bytes()]
    assert bad == []


def test_the_front_doors_have_no_internal_references():
    front = ["README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "docs/README.md"]
    bad = [f"{f}:{n}: {ln.strip()[:100]}" for f in front
           for n, ln in enumerate((ROOT / f).read_text().splitlines(), 1)
           if offending(ln) or "-notes" in ln]
    assert bad == []


def test_every_docs_page_is_in_the_index():
    index = (ROOT / "docs" / "README.md").read_text()
    pages = [p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs").rglob("*.md")
             if p != ROOT / "docs" / "README.md"]
    missing = [p for p in pages if f"({p})" not in index
               and f"({p.rsplit('/', 1)[0]}/README.md)" not in index]
    assert missing == []


def test_the_files_kranto_writes_into_a_repo_have_no_internal_references():
    bad = [f"{p.relative_to(PKG)}:{n}: {ln.strip()[:100]}"
           for p in sorted((PKG / "maintain" / "templates").rglob("*")) if p.is_file()
           for n, ln in enumerate(p.read_text(errors="replace").splitlines(), 1)
           if offending(ln)]
    assert bad == []


# The places the doors retired: Today, Library, Desk, Work, Maintenance
# as a place, Connections, Home and feed, the side bar. A doc that names one sends a stranger to
# a page that is no longer there. The research and design records keep their history.
RETIRED = re.compile("|".join((
    r"Settings › Sources", r"Settings › Connections", r"^#+ Connections\b", r"Home and feed",
    r"\bWork ›", r"\bDesk ›", r"\bLibrary ›", r"\bMaintenance ›", r"\bthe Today page",
    r"\bToday's Needs you", r"\bToday › ", r"\bon Today\b", r"\bin the side bar\b",
    r"\(Today[,)]", r"\bThen Today\b", r"\bToday's Try again")), re.M)


def retired_places() -> list[str]:
    # The page's own docs (the server's record its history in its words)
    docs = [PKG / "ui" / "help.md", ROOT / "README.md",
            *(ROOT / "docs" / n for n in ("ui.md", "mcp.md", "traces.md"))]
    return [f"{p.relative_to(ROOT)}:{n}: {ln.strip()[:100]}" for p in docs
            for n, ln in enumerate(p.read_text().splitlines(), 1) if RETIRED.search(ln)]


def test_no_doc_sends_you_to_a_retired_place():
    assert retired_places() == []


def test_the_retired_places_check_would_catch_one():
    for ln in ("**Work › Ideas › + New idea**", "## Connections {#connections}",
               "turn the home off under Settings › Home and feed", "- **Today › Needs you** lists",
               "a row in Today's Needs you", "the repo gets one row (Today, Settings ›"):
        assert RETIRED.search(ln), ln
    for ln in ("## Accounts {#connections}", "News › Today", "Build › Repos", "Needs you",
               "**Today's** (`v5`, the default)", "today's keys"):
        assert not RETIRED.search(ln), ln
