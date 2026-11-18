"""Kranto's contract with the page.

- Always: the server imports the page through ``kranto.page.host_api`` only.
- With the page installed (CI's test job installs the page's main for these): every name Kranto
  imports is one the page's host API exports, and the page's read-only reader of this
  database (its ``IdeasFile``, used when it runs without Kranto serving) reads cards and their
  latest grade from a real the server store, with every migration applied."""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "kranto"


def _imports() -> list[tuple[str, str, str]]:
    """``(file, module, name)`` of every import of the page in the server's source."""
    out = []
    for f in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("kranto.page"):
                out += [(f.name, node.module, a.name) for a in node.names]
            elif isinstance(node, ast.Import):
                out += [
                    (f.name, a.name, "") for a in node.names if a.name.startswith("kranto.page")
                ]
    return out


def test_kranto_imports_page_through_its_host_api_only():
    found = _imports()
    assert found, "Kranto imports the page somewhere"
    other = [
        x
        for x in found
        if x[1] != "kranto.page.host_api" and not (x[1] == "kranto.page" and x[2] == "host_api")
    ]
    assert other == []


def _real_host_api():
    api = pytest.importorskip("kranto.page.host_api")
    if getattr(api, "_stand_in", False) or not hasattr(api, "_NAMES"):
        pytest.skip("the page is a stand-in here")
    return api


# The page's host API version 2 (CUT,): the names it keeps once the factory left.
# ``Config`` and ``write_setting`` stay for the page's own settings in loop.yaml: the wizard's
# ``build.claude_command`` (the console's launcher reads it) and verbs_api's ``mcp.actions``.
HOST_API_V2 = frozenset(
    {
        "API_VERSION",
        "configure",
        "handle",
        "handle_with_headers",
        "stream",
        "selfcheck_paths",
        "term_ws",
        "term_ws_served",
        "term_cli",
        "term_mcp_main",
        "term_doctor",
        "console_new_home_yaml",
        "console_doctor_line",
        "mcp_available",
        "mcp_main",
        "add_trace_group",
        "claude_print",
        "ClaudePrintError",
        "telemetry_sink",
        "telemetry_schema",
        "telemetry_facts",
        "term_shutdown",
        "detached_jobs",
        "Config",
        "write_setting",
    }
)
# kranto.py and doctor.py had their own cut (the phase-2 patch): nothing of theirs is left
UNTIL_PHASE_2: frozenset[str] = frozenset()
# core/verbs.py's b.* rows are the track, until its own cut: the one name they still read
PHASE_2_FILES = ("verbs.py",)
VERBS_UNTIL_ITS_CUT = frozenset({"verb_rows"})


def test_kranto_uses_only_host_api_version_2s_names():
    """No module outside core/verbs.py's b.* rows reaches for a name version 2
    drops."""
    names = {(f, n) for f, mod, n in _imports() if mod == "kranto.page.host_api"}
    outside = {n for f, n in names if f not in PHASE_2_FILES}
    assert outside <= HOST_API_V2, sorted(outside - HOST_API_V2)
    inside = {n for f, n in names if f in PHASE_2_FILES}
    allowed = HOST_API_V2 | UNTIL_PHASE_2 | VERBS_UNTIL_ITS_CUT
    assert inside <= allowed, sorted(inside - allowed)


def test_every_name_kranto_uses_is_in_the_host_api():
    api = _real_host_api()
    assert api.HOST_API_VERSION >= 1
    names = {n for _, mod, n in _imports() if mod == "kranto.page.host_api"}
    names |= {
        "API_VERSION",
        "configure",
        "handle",
        "handle_with_headers",  # web/brb.py's
        "stream",
    }  # api.* reads
    # core.verbs.brb_verbs reads the page's actions when a page has them (none since builds
    # left; without the name it falls back to the core's verbs)
    names -= {"verb_rows"}
    assert names <= set(api._NAMES), sorted(names - set(api._NAMES))
    for n in names - {"mcp_available", "mcp_main"}:  # the MCP SDK is optional
        assert getattr(api, n) is not None, n
