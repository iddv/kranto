"""What a user reads carries no internal references: no private plan citations (a code ending in
``-PLAN``, ``§``), no track codes (``track`` and a short capital code, or one in parentheses), no
"example-host" and no personal paths. Checked: every ``afk`` and ``kranto`` help text, the page
templates and the page's script; and, tree-wide, none of the builders' own words and codes."""
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


# -- the whole tree ------------------------------------------------------------------------------

def tracked_text() -> list[tuple[str, str]]:
    """Every tracked text file: (path, text). Lock files, generated types and recordings are
    not words anyone wrote."""
    import subprocess
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.split()
    out = []
    for n in names:
        if n.endswith((".lock", ".gen.ts", ".png", ".ico", ".svg", ".woff2", ".jpg", ".gif",
                       ".pdf", ".json")) or n.startswith("tests/fixtures/"):
            continue
        try:
            out.append((n, (ROOT / n).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
    return out


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


# the words of the people who build Kranto, not of the people who read it: their notes file,
# their review codes, their own role in the release (private names and paths: scrub.py)
BUILDERS = re.compile(r"MQ\.NOTES|\bMQ\b|\bTFIX\b|\bHLTH\b|\bUXI\b"
                      r"|\bthe operator's (?:fix|item|note|bake-off)\b|\bthe operator re-reads?\b")


def test_the_tree_holds_none_of_the_builders_own_words():
    me = "tests/test_no_internal_refs.py"
    bad = [f"{n}:{_line(t, m.start())}: {m.group(0)}" for n, t in tracked_text() if n != me
           for m in BUILDERS.finditer(t)]
    assert bad == []


# the builders' private codes: their incident review and its rows, their release steps and gates,
# their design notes and checklists, the maintainer's own install named as "live's", the check
# ids of their acceptance lists, and the work tracks a sentence once cited in parentheses. A
# track code is matched only where it stands alone, so a call such as page(POST) or
# relative_to(SRC) is not one, and the pushed authorization request's "(PAR)" is not either.
_TRACKS = ("CUT|WT|OI|SEND|FB|SRC|TH|MAIL|POST|PROSE|MEM|REL|ONE|STD|BL|W1|ACT|SOCIAL|TS|BG|UF"
           "|SL|PAR")
CODES = re.compile(r"\bRCA\b|UI-v4|MAINTAIN\.md|\b[Ll]ive's|\bK0\b|\bK1\b|\bKREL\b|\bKVAULT\b"
                   r"|\bREVK\b|\bGate [AB]\b|ops/telemetry"
                   r"|\b(?:CUT|PREV|HOUR|POST|ARCH|PROSE|FE|SOC)-\d+\b"
                   r"|WORKSPACE\.md|PLAN\.md|CLICKS-v4|LEARNING\.md|\bQA B\d+|\bS-\d+\b"
                   r"|(?<![-\w])fleet2\b|\bfleet track"
                   rf"|(?<![\w.])(?<!request )\((?:{_TRACKS})\)")


def test_the_tree_holds_none_of_the_builders_codes():
    me = "tests/test_no_internal_refs.py"
    bad = [f"{n}:{_line(t, m.start())}: {m.group(0)}" for n, t in tracked_text() if n != me
           for m in CODES.finditer(t)]
    assert bad == []


def test_the_codes_check_knows_a_code_from_a_call():
    for code in ("the RCA's row", "UI-v4.md 2.4", "see MAINTAIN.md", "live's judge", "K0 then K1",
                 "Gate B", "ops/telemetry", "CUT-3", "PREV-1", "FE-13", "Feedback (FB): the",
                 "watches are retired (WT)", "the press's limit (PAR)", "WORKSPACE.md 2.5",
                 "PLAN.md section 1.5", "CLICKS-v4.md", "LEARNING.md 3.4", "QA B20", "SOC-7",
                 "the page's S-12", "fleet2 track H", "a fleet track"):
        assert CODES.search(code), code
    for fine in ("page.evaluate(CUT)", "relative_to(SRC)", "page(POST)", "run_uuid(ONE)",
                 "A pushed authorization request (PAR) with PKCE", "(USD)", "BSD-2", "BSD-3",
                 "PREVIEW-1", "a live install", "Gateway", "a quiet fleet of watchers",
                 "fleet rentals", "CLICKS = (", "POSTING-7", '"brb" + "-fleet2"'):
        assert not CODES.search(fine), fine


# the rename's broken sentences: an article doubled ("a the page", "this the server"), or "the
# server"/"the page" starting a sentence in lower case (after a sentence's end, at a paragraph or
# a docstring's start, or as a comment's first words)
_X = r"(?:server|page)"
DOUBLED = re.compile(rf"\b(?:[Aa]n?|[Tt]his|[Tt]he|[Yy]our|[Ee]very|[Ee]ach|[Oo]lder|[Nn]ewer"
                     rf"|[Oo]ld|[Nn]ew|[Nn]o) the {_X}\b")
_END = r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)(?<![\w/`]\.\w)[.!?]"
_MARK = r"(?:(?://|#|\*|--)[ \t]*)?"
STARTS = [
    re.compile(rf"{_END}[\"'’”`*)\]]*(?:[ \t]*\n[ \t]*{_MARK}|[ \t]+)the {_X}\b"),
    re.compile(rf"\n[ \t]*{_MARK}\n[ \t]*{_MARK}the {_X}\b"),
    re.compile(rf'(?:"""|/\*\*|<!--)[ \t]*\n?[ \t]*(?:\*[ \t]*)?the {_X}\b'),
]
LONE = re.compile(rf"^[ \t]*(?://|#)[ \t]*the {_X}\b", re.M)


def _starts_a_comment(text: str, at: int) -> bool:
    end = text.rfind("\n", 0, at)
    if end < 0:
        return True
    prev = text[text.rfind("\n", 0, end) + 1:end].strip()
    if not prev.startswith(("#", "//")):
        return True
    body = prev.lstrip("#/ ").rstrip()
    return body == "" or body.endswith((".", "!", "?", ":"))


def test_no_sentence_the_rename_broke():
    bad = []
    for n, t in tracked_text():
        if n == "tests/test_no_internal_refs.py":
            continue
        hits = [*DOUBLED.finditer(t), *(m for p in STARTS for m in p.finditer(t)),
                *(m for m in LONE.finditer(t) if _starts_a_comment(t, m.start()))]
        bad += [f"{n}:{_line(t, m.start())}: {m.group(0).strip()[:60]!r}" for m in hits]
    assert bad == []
