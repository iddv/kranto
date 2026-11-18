"""The trace view's place in the page: its routes, its registration, the
keys, ⌘K, and the API's href landing on the route (the build pane's Trace fold left with the
builds, CUT). The page itself is tested in Vitest
(pages/trace/trace.svelte.test.ts: the tree, folds, the inspector, unsafe text)."""
from __future__ import annotations

import json
import re

from kranto.page.trace.service import _href

from .webui import SRC, src

NODES = json.loads((SRC / "lib" / "nodes.json").read_text())
KEYS = json.loads((SRC / "lib" / "keys.json").read_text())


def route(r: str) -> dict:
    return next(n for n in NODES if n["route"] == r)


def test_the_trace_is_a_full_page_route_and_a_builds_trace_says_it_left():
    for r in ("sessions/:tid/trace", "research/:id/trace", "afk/:id/trace"):
        assert route(r) == {"route": r, "node": "trace", "stage": True}
    for r in ("builds/:key/trace", "builds/:key/trace/:n", "loop/:id/trace"):
        assert route(r)["redirect"] == "home" and "not part of Kranto" in route(r)["said"]


def test_a_sessions_trace_has_its_route_and_its_panel_link():
    assert route("sessions/:tid/trace") == {"route": "sessions/:tid/trace", "node": "trace",
                                            "stage": True}
    assert _href("c3f1a9e2", None, "session") == "#/sessions/c3f1a9e2/trace"
    assert route("research/:id/trace")["node"] == "trace"
    assert _href("1792000000-loop", None, "research") == "#/research/1792000000-loop/trace"
    panel = src("term/TerminalPanel.svelte")
    assert 'id="term-trace"' in panel and '"/trace"' in panel


def test_the_page_is_registered_lazily():
    idx = src("pages/index.ts")
    assert 'register("trace", { list: lazy(() => import("./trace/TracePage.svelte")) });' in idx


def test_the_apis_href_is_the_route():
    assert _href("a/b", None, "session") == "#/sessions/a%2Fb/trace"   # one segment
    assert _href("u-1", None, "afk") == "#/afk/u-1/trace"
    # the build loop's old rows open nowhere: their pages left with it
    assert _href("sample-r1", 1) is None and _href("fix-1", 1, "maint") is None


def test_the_link_targets_resolve_on_the_page():
    """A stage (?stage=), a held check (?hold=), a finding (?check=): resolved from the trace's own
    links, the Output tab open on a check; a check the trace cannot place says so."""
    t = src("pages/trace/TracePage.svelte")
    for part in ("rq.stage", 'kind = rq.check ? "check" : rq.hold ? "hold" : null', 'tab = "output"',
                 "The trace does not link this check to a span", 'id="open-verify"'):
        assert part in t, part


def test_the_keys_and_the_palette():
    rows = {r["keys"]: r for r in KEYS["KEYMAP"] if r["group"] == "Trace"}
    assert set(rows) == {"t", "e", "← →", "1–6", "f"} and all(r.get("page") for r in rows.values())
    cmds = src("lib/app/commands.ts")
    assert "title: `Trace of ${x.title}`" in cmds and 'go: x.trace + "?follow=1"' in cmds


def test_no_dollars_in_the_trace_view():
    """The owner's ruling (2026-10-09): tokens where a thing used some, dollars only on Spend."""
    for f in ("TracePage", "Inspector", "ChatView", "DiffView", "TextOut"):
        text = src(f"pages/trace/{f}.svelte")
        assert not re.search(r"\$\d|usd|money\(", text), f


def test_the_docs_page_names_every_trace_setting_and_command():
    """ 5: docs/traces.md is in the index, has no internal reference, and stays in step with
    the settings and the command line it documents."""
    from pathlib import Path

    from kranto.page.settings.store import DEFAULTS

    from .test_no_internal_refs import offending
    root = Path(__file__).resolve().parents[2]
    page = (root / "docs" / "traces.md").read_text()
    assert [ln for ln in page.splitlines() if offending(ln)] == []
    assert "(traces.md)" in (root / "docs" / "README.md").read_text()

    def keys(d, pre="trace"):
        for k, v in d.items():
            yield from keys(v, f"{pre}.{k}") if isinstance(v, dict) else [f"{pre}.{k}"]
    for k in keys(DEFAULTS["trace"]):
        assert f"`{k}`" in page, k
    for cmd in ("list", "show", "follow", "export"):
        assert f"kranto trace {cmd} " in page, cmd


def test_untrusted_text_goes_through_safe_text():
    for f in ("Inspector", "ChatView", "DiffView", "TextOut", "TracePage"):
        assert "safeText(" in src(f"pages/trace/{f}.svelte"), f
