"""Needs you is calm and plain (the owner, 2026-10-29: "There is way too much shit going on in
Needs you … No idea what Press means as well").

- ``kranto_incidents`` answers "why does Needs you say my key is refused" in one call: what raised
  it, when, the error, whether later calls worked, and what clears it (the console read Kranto's
  databases and logs about a dozen times to answer it).
- No word "press" in what the owner reads from the page: help, the docs, the MCP tools' words and
  answers, and every string the code serves (a model's prompt aside: no person reads it). "press"
  stays a word of the code (a route's ``/press``, comments, docstrings); a real word of content
  ("press release") is allowed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from kranto.page.mcp import server as S
from kranto.page.mcp import tools as T

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "kranto" / "page"
WORD = re.compile(r"\bpress(es|ed|ing)?\b", re.I)
ALLOW = re.compile(r"press (release|kit)s?|/api/prepared/[^ ]*/press|`press`|aria-pressed", re.I)
PROMPTS = {"loop/pitch.py"}      # a model's prompt (prompts.lock.json): no person reads it


def said(text: str) -> bool:
    return bool(WORD.search(ALLOW.sub("", str(text))))


# live's own incident on 2026-10-29 (dev14), as the server #407 answers it
LIVE = {"id": "auth:openrouter", "title": "OpenRouter credit is low: calls wait and try again",
        "cause": "low credit", "blocking": False, "since": "2026-10-28T20:44:46Z",
        "last": "2026-10-28T20:44:46Z", "tries": 1,
        "kinds": [{"kind": "ideas", "title": "Writing idea cards", "noun": "idea cards"}],
        "error": "HTTP 402 from https://openrouter.ai/api/v1: This request would exceed your "
                 "available credits given your current in-flight requests.",
        "verb": "Check the key", "href": "#/settings/watching?sel=ekey",
        "clears": "It goes by itself when a call to OpenRouter works (the next run), or when you "
                  "dismiss it.", "runs": []}


def client(body):
    seen = []
    c = T.Client(get=lambda p, q=None: (seen.append(p), (200, body))[1], post=lambda p, b: (404, {}))
    return c, seen


def test_kranto_incidents_says_what_raised_it_when_the_error_the_later_calls_and_what_clears_it():
    c, seen = client({"incidents": [LIVE], "failing": [{"kind": "toot.weekly", "title": "Toot",
                                                        "since": "2026-10-27", "tries": 2,
                                                        "error": "crashed", "trace": "#/x"}]})
    got = T.call(c, "kranto_incidents", {})
    assert seen == ["/api/activity"]                              # one read, no file
    s = got["said"]
    assert s.startswith("OpenRouter credit is low: calls wait and try again. Raised by 1 failed "
                        "run of idea cards, first at 2026-10-28T20:44:46Z.")
    assert "would exceed your available credits" in s and "The key works" in s
    assert "goes by itself when a call to OpenRouter works" in s
    assert "Toot is failing (2 runs in a row since 2026-10-27): crashed." in s
    assert got["incidents"][0]["clears"] and got["incidents"][0]["cause"] == "low credit"
    refused = {**LIVE, "title": "Your OpenRouter key is refused (expired)", "cause": "expired",
               "blocking": True, "clears": ""}
    one = T.call(client({"incidents": [refused, {"id": "broker:unapproved", "title": "x"}]})[0],
                 "kranto_incidents", {"id": "auth:openrouter"})
    assert "No call to that provider has worked since that failure" in one["said"]
    assert "What fixes it: Check the key (#/settings/watching?sel=ekey)." in one["said"]
    assert [i["id"] for i in one["incidents"]] == ["auth:openrouter"]
    gone = T.call(client({"incidents": [], "failing": []})[0], "kranto_incidents",
                  {"id": "auth:openrouter"})
    assert gone["said"].startswith("No incident auth:openrouter now: it has cleared")
    assert "kranto_incidents" in T.COMPACT and T.READS["kranto_incidents"][2]["properties"]["id"]


def test_help_and_the_docs_say_approve_never_press():
    files = [PKG / "ui" / "help.md", ROOT / "README.md", *PAGE_DOCS]
    bad = [f"{p.relative_to(ROOT)}:{i}" for p in files
           for i, line in enumerate(p.read_text().splitlines(), 1) if said(line)]
    assert bad == []


def test_no_mcp_tool_and_no_action_says_press():
    words = [S.INSTRUCTIONS if hasattr(S, "INSTRUCTIONS") else "", *T.CHOICE_WORDS.values()]
    for name, (_, d, schema) in {**T.READS, **T.GENERIC}.items():
        words += [d, *(str(p.get("description") or "") for p in schema["properties"].values())]
    for t in T.tools(None):
        words += [t["description"]]
    assert [w[:80] for w in words if said(w)] == []
    # the answers' own words
    assert not said(T.kranto_outcomes(client({"outcomes": [], "now": []})[0])["said"])
    assert not said(T.CHOICE_WORDS["ask"])


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            b = n.body
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                out.add(id(b[0].value))
    return out


def test_no_string_page_serves_says_press():
    bad = []
    for p in sorted(PKG.rglob("*.py")):
        rel = str(p.relative_to(PKG))
        if rel in PROMPTS or rel.startswith("plugins/preload"):
            continue
        tree = ast.parse(p.read_text())
        docs = _docstrings(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in docs:
                continue
            v = n.value
            if re.fullmatch(r"[a-z_./:{}-]+", v.strip()):
                continue
            if said(v):
                bad.append(f"{rel}:{n.lineno}: {v.strip()[:80]}")
    assert bad == []


# -- "ticket" and "dry" (SEND; the owner, 2026-10-29: "Not sure what 'ticket #1 is expired' means,
# I just wanted to post the newsletter") -------------------------------------------------------
#
# The owner reads what a cub asks and its practice mode, never a ticket or dry: help, the docs, the
# MCP tools' words, every string the page serves. Allowed: a back-quoted name, a route, `--dry-run`
# and another feature's own dry run (the weekly editor's), the console socket's one-time ticket
# (`term/asgi.py`, never shown), the maintenance comment's marker (`maintain/revise.py`).
# the docs of what a person reads on the page (the cub protocol's docs say "ticket" on purpose)
PAGE_DOCS = [Path(__file__).resolve().parents[2] / "docs" / n for n in ("ui.md", "mcp.md", "traces.md")]
JARGON = re.compile(r"\b(tickets?|dry)\b", re.I)
JARGON_OK = re.compile(r"`[^`]*`|--dry-run|DRY-RUN|/api/(tickets|requests)\S*|kranto:ticket|(^|,)dry,|"
                       r"(a|the|with a|one) dry run|\(a dry run[^)]*\)|, dry run", re.I)
CODE = {"term/asgi.py", "maintain/revise.py"}


def jargon(text: str) -> bool:
    return bool(JARGON.search(JARGON_OK.sub("", str(text))))


def test_help_and_the_docs_say_neither_ticket_nor_dry():
    files = [PKG / "ui" / "help.md", ROOT / "README.md", *PAGE_DOCS]
    bad = [f"{p.relative_to(ROOT)}:{i}" for p in files
           for i, line in enumerate(p.read_text().splitlines(), 1) if jargon(line)]
    assert bad == []


def test_no_mcp_tool_and_no_string_page_serves_says_ticket_or_dry():
    words = [S.INSTRUCTIONS if hasattr(S, "INSTRUCTIONS") else "", *T.CHOICE_WORDS.values()]
    for name, (_, d, schema) in {**T.READS, **T.GENERIC}.items():
        words += [d, *(str(p.get("description") or "") for p in schema["properties"].values())]
    for t in T.tools(None):
        words += [t["description"]]
    assert [w[:80] for w in words if jargon(w)] == []
    bad = []
    for p in sorted(PKG.rglob("*.py")):
        rel = str(p.relative_to(PKG))
        if rel in PROMPTS or rel in CODE or rel.startswith("plugins/preload"):
            continue
        tree = ast.parse(p.read_text())
        docs = _docstrings(tree)
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and isinstance(n.value, str)) or id(n) in docs:
                continue
            v = n.value
            if re.fullmatch(r"[a-z_./:{}-]+", v.strip()):
                continue
            if jargon(v):
                bad.append(f"{rel}:{n.lineno}: {v.strip()[:80]}")
    assert bad == []


# -- "cub" in the MCP tools (CUT): a cub is the cub developer's word. The default tool set says it
# nowhere, neither in a tool's name nor in its words; a cub's own verbs (kranto_cub_*) are tools
# only with cubs.developer on (test_mcp_verbs.py).
CUB = re.compile(r"\bcubs?\b|_cub_|\bcub[_.]", re.I)


def test_no_default_mcp_tool_says_cub():
    from .test_mcp_verbs import Fake
    for c in (None, Fake().client(), Fake().client(door="console")):
        for t in [*T.tools(c), *T.tools(c, compact=True)]:
            words = [t["name"], t["description"],
                     *(str(p.get("description") or "") for p in t["schema"]["properties"].values())]
            assert [w for w in words if CUB.search(w)] == [], t["name"]
    for name, (_, d, schema) in {**T.READS, **T.GENERIC, **T.TERM_TOOLS}.items():
        assert not CUB.search(name) and not CUB.search(d), name
    dev = {t["name"] for t in T.tools(Fake(developer=True).client())}
    assert [n for n in dev if CUB.search(n)]              # the check would catch them


def test_the_check_would_catch_them():
    assert jargon("Ticket #1 is expired.") and jargon("dry: confirming it sends nothing")
    assert not jargon("brb loop editor start [--dry-run]") and not jargon("(a dry run)")
    assert not jargon("Practice: nothing is sent")
