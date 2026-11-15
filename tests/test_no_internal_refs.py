"""What a user reads carries no internal references: no private plan citations (``X-PLAN``,
``§``), no track codes (``track OI``, ``(OI)``), no "example-host" and no personal paths. Checked:
every ``afk`` and ``kranto`` help text, the page templates and the page's script."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "kranto"
# ~/kranto-loop is the loop's documented default home, not a personal path
INTERNAL = re.compile(r"\b[A-Z][A-Z0-9]*-PLAN\b|§|\btrack [A-Z]{1,3}\b|\((?!USD\))[A-Z]{1,3}\)"
                      r"|homelab|/home/|~/brb-(?!loop\b)")


def help_texts(p: argparse.ArgumentParser, where: str):
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


def test_afk_and_kranto_help_have_no_internal_references():
    from kranto import cli, launcher
    texts = [*help_texts(cli.build_parser(), "afk"), *help_texts(launcher.build_parser(), "kranto")]
    assert len(texts) > 50
    assert [(w, t[:120]) for w, t in texts if INTERNAL.search(t)] == []


ROOT = SRC.parent.parent
# What a stranger reads first: the front doors and the guides they link to.
FRONT = ["README.md", "CONTRIBUTING.md", "SECURITY.md", "SUPPORT.md", "CODE_OF_CONDUCT.md",
         "docs/README.md", "docs/setup.md", "docs/watcher.md", "docs/GLOSSARY.md",
         "sdk/README.md"]
PRIVATE = re.compile(r"-notes\b|/home/\w|iddvilliers|@gmail\.com")


def test_the_front_doors_have_no_internal_references():
    def hit(line):
        line = line.replace("/home/you/", "~/")     # the guides' placeholder for your home
        return INTERNAL.search(line) or PRIVATE.search(line)

    bad = [f"{f}:{n}: {ln.strip()[:100]}" for f in FRONT
           for n, ln in enumerate((ROOT / f).read_text().splitlines(), 1) if hit(ln)]
    assert bad == []


def test_every_docs_page_is_in_the_index():
    index = (ROOT / "docs" / "README.md").read_text()
    # a page in a folder is listed by its folder's README.md
    pages = [p.relative_to(ROOT / "docs").as_posix() for p in (ROOT / "docs").rglob("*.md")
             if p != ROOT / "docs" / "README.md"]
    missing = [p for p in pages if f"({p})" not in index
               and f"({p.rsplit('/', 1)[0]}/README.md)" not in index]
    assert missing == []


def test_the_pages_have_no_internal_references():
    files = [*sorted((SRC / "web" / "templates").rglob("*.html")),
             *sorted((SRC / "web" / "static").rglob("*.js"))]
    assert files
    bad = [f"{p.relative_to(SRC)}:{n}: {ln.strip()[:100]}" for p in files
           for n, ln in enumerate(p.read_text(errors="replace").splitlines(), 1)
           if INTERNAL.search(re.sub(r"\{#.*?#\}|//.*$", "", ln))]
    assert bad == []
