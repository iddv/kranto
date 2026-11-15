"""No "press" in what the owner reads (the owner on 2026-10-29: "No idea what Press means").

Kranto called an approval a "press": a button said Press, a prepared item waited "for your
press", the console's skills told the assistant to say so. The owner reads none of it now: the
plugin's skills, agents, hooks and manifest, every verb's words (what the MCP tools say), the
docs, and every string the server's code serves. "press" stays a word of the code (a route's
``/press``, a stored state ``pressed``, comments and docstrings); a real word of content
("press release") is allowed."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from kranto.core import verbs

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "kranto"
WORD = re.compile(r"\bpress(es|ed|ing)?\b", re.I)
ALLOW = re.compile(r"press (release|kit)s?|/api/prepared/[^ ]*/press|`press`", re.I)


def said(text: str) -> bool:
    return bool(WORD.search(ALLOW.sub("", text)))


def test_the_plugin_says_approve_never_press():
    files = [p for p in (SRC / "plugin").rglob("*") if p.suffix in (".md", ".json", ".toml")]
    assert files
    bad = [f"{p.relative_to(SRC)}:{i}" for p in files
           for i, line in enumerate(p.read_text().splitlines(), 1) if said(line)]
    assert bad == []


def test_no_verb_says_press():
    words = [verbs.CONSENT_WHY, verbs.HOUSE_WHY, *verbs.CHOICE_WORDS.values(),
             *verbs.KIND_WORDS.values(), *(why for _, why in verbs.LOCKS.values())]
    for v in [*verbs.CORE, *verbs.feature_verbs()]:
        words += [v.title, v.says, *(f.says for f in v.fields)]
    assert [w for w in words if said(w)] == []


def test_the_docs_say_approve_never_press():
    files = [*(ROOT / "docs").rglob("*.md"), ROOT / "README.md",
             *(ROOT / "packages").rglob("README.md"), *(SRC / "cubs").rglob("*.md"),
             *(SRC / "cubs").rglob("cub.yaml"), SRC / "telemetry" / "notice.md"]
    bad = [f"{p.relative_to(ROOT)}:{i}" for p in files
           for i, line in enumerate(p.read_text().splitlines(), 1) if said(line)]
    assert bad == []


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                out.add(id(b[0].value))
    return out


def test_no_string_kranto_serves_says_press():
    """Every string literal of the code (a reply, a row's words, a setup step, a config
    comment), not a docstring, an identifier or a path, and not a table's schema."""
    bad = []
    for p in sorted(SRC.rglob("*.py")):
        tree = ast.parse(p.read_text())
        docs = _docstrings(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in docs:
                continue
            v = n.value
            # a name, a path, a table's schema or a pattern (\b…) is no word a person reads
            if re.fullmatch(r"[a-z_./:{}-]+", v.strip()) or "CREATE TABLE" in v or "\\b" in v:
                continue
            if said(v):
                bad.append(f"{p.relative_to(SRC)}:{n.lineno}: {v.strip()[:80]}")
    assert bad == []


# -- "ticket" and "dry" (SEND; the owner, 2026-10-29: "Not sure what 'ticket #1 is expired'
# means, I just wanted to post the newsletter") -------------------------------------------------
#
# The owner reads an ask ("Send", "Post toot", "Send to Sanity") and its practice mode
# ("Practice: nothing is sent"), never a ticket or dry. Both stay words of the code: the
# `cub_tickets` table, the `/api/tickets` routes, the `ticket.resolved` event, the `dry` mode,
# `kranto cub dry` and `--dry-run`. Allowed as content: a back-quoted name, a route, the CLI's
# command names, "(in the code, …)" glossing the old word, and another feature's dry run
# (`kranto adopt --dry-run`'s plan). The cub protocol's own errors (`core/cubs/host.py`) are read by
# a cub's author, not the owner; the cub authors' guides (`docs/cubs.md`, `docs/cub-protocol.md`,
# `docs/features.md`) and the operator's (`docs/OPERATING.md`) name the API as it is.
JARGON = re.compile(r"\b(tickets?|dry)\b", re.I)
JARGON_OK = re.compile(r"`[^`]*`|--dry-run|/dry\b|/api/(tickets|requests)\S*|ticket\.[a-z_]+|"
                       r"\(in the code, [^)]*\)|dry run: nothing is changed|kranto cub dry|"
                       r"dry ID KIND|remove, dry, log", re.I)
OWNER_DOCS = ("docs/newsletter.md", "docs/GLOSSARY.md", "docs/activity.md", "docs/assistant.md",
              "docs/verbs.md", "README.md")
STATES = {"dry run"}         # an earlier cub version's stored state, read back as practice
PROTOCOL = {"core/cubs/host.py"}


def jargon(text: str) -> bool:
    return bool(JARGON.search(JARGON_OK.sub("", text)))


def test_the_owners_docs_say_neither_ticket_nor_dry():
    files = [ROOT / p for p in OWNER_DOCS] + [*(SRC / "cubs").rglob("README.md")]
    bad = [f"{p.relative_to(ROOT)}:{i}: {line.strip()[:80]}" for p in files
           for i, line in enumerate(p.read_text().splitlines(), 1) if jargon(line)]
    # a cub's manifest: what its page and its jobs say, not its comments or its event names
    for p in (SRC / "cubs").rglob("cub.yaml"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            said_part = line.split(" #", 1)[0]
            if not line.lstrip().startswith("#") and jargon(said_part):
                bad.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()[:80]}")
    assert bad == []


def test_no_string_kranto_serves_says_ticket_or_dry():
    bad = []
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        # The page's strings have their own check (tests/page/test_nyu_words.py)
        if rel in PROTOCOL or "/tests/" in f"/{rel}" or rel.startswith("page/"):
            continue
        tree = ast.parse(p.read_text())
        docs = _docstrings(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in docs:
                continue
            v = n.value
            if re.fullmatch(r"[a-z_./:{}-]+", v.strip()) or "CREATE TABLE" in v or "\\b" in v \
                    or v.strip() in STATES or re.match(r"\s*(SELECT|INSERT|UPDATE)\b", v):
                continue
            if jargon(v):
                bad.append(f"{rel}:{n.lineno}: {v.strip()[:80]}")
    assert bad == []


def test_the_check_would_catch_them():
    assert jargon("Ticket #1 is expired.") and jargon("dry: confirming it sends nothing")
    assert not jargon("kranto cub dry newsletter send.newsletter") and not jargon("`dry`")
    assert not jargon("Practice: nothing is sent") and not jargon("(in the code, a *ticket*)")
