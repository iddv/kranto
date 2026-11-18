"""What Kranto (the host, the server) may use of the page: exactly these names, nothing else
(S-12; CR-REVIEW A-8). The server imports from here only, so the page's modules can move
without breaking the host; a test in each repo pins the set.

Each name is imported when it is first read (PEP 562), so ``import kranto.page.host_api`` costs
nothing and a missing optional part (the MCP SDK) raises ``ImportError`` only where it is
used, as the direct import did. Change a name's meaning: bump ``HOST_API_VERSION``.
"""
from __future__ import annotations

import importlib

HOST_API_VERSION = 2            # 2: the factory left (cut 3): no loop, builds,
                                # registry, capabilities, plugins, GitHub or maintenance names

_NAMES = {
    # the /brb mount (the server web/brb.py)
    "API_VERSION": ("kranto.page.ui.api", "API_VERSION"),
    "configure": ("kranto.page.ui.api", "configure"),
    "handle": ("kranto.page.ui.api", "handle"),
    "handle_with_headers": ("kranto.page.ui.api", "handle_with_headers"),
    "stream": ("kranto.page.ui.api", "stream"),               # the live feed (/api/stream)
    # the post-update self-check's reads of the mount (the server's web/selfcheck_api.py)
    "selfcheck_paths": ("kranto.page.ui.api", "selfcheck_paths"),
    # The page's settings file, loop.yaml (the console's term and ask sections): read and one
    # key written (the server setup.py, wizard.py, web/verbs_api.py)
    "Config": ("kranto.page.settings.store", "Config"),
    "write_setting": ("kranto.page.settings.write", "write"),
    # kranto mcp
    "mcp_available": ("kranto.page.mcp.server", "available"),
    "mcp_main": ("kranto.page.mcp.server", "main"),
    # Open in Claude Code and the console: the terminal's WebSocket (the server web/brb.py) and
    # `kranto term …` / `kranto mcp --term <tid>` (the server kranto.py), and kranto doctor's lines
    "term_ws": ("kranto.page.term.asgi", "endpoint"),
    "term_ws_served": ("kranto.page.term.asgi", "mark_served"),
    "term_cli": ("kranto.page.term.cli", "main"),
    "term_mcp_main": ("kranto.page.mcp.server", "term_session_main"),
    "term_doctor": ("kranto.page.term.launch", "doctor_lines"),
    # kranto trace: the command group Kranto runs in-process
    "add_trace_group": ("kranto.page.trace.cli", "add_trace_group"),
    # the watcher's Claude Code provider (the server providers/claude_code.py, 4.5): one
    # claude -p that can only answer, the token by pipe
    "claude_print": ("kranto.page.box.print_call", "claude_print"),
    "ClaudePrintError": ("kranto.page.box.print_call", "PrintError"),
    # usage reports: kranto serve hands the page its recorder; the daily report reads
    # the page's part of the allow-list and the page's few numbers
    "telemetry_sink": ("kranto.page.telemetry", "set_sink"),
    "telemetry_schema": ("kranto.page.telemetry", "schema"),
    "telemetry_facts": ("kranto.page.telemetry", "facts"),
    # The server's stop (the server stopping.py): the detached jobs it leaves running
    "detached_jobs": ("kranto.page.proc", "detached"),
    # ... and the terminals it ends: their records say "ended: restart" before the signal
    "term_shutdown": ("kranto.page.ui.api", "stop_terms"),
}

__all__ = ["HOST_API_VERSION", *_NAMES]


def __getattr__(name: str):
    try:
        module, attr = _NAMES[name]
    except KeyError:
        raise AttributeError(f"kranto.page.host_api has no {name!r}: the host may use only "
                             f"{', '.join(sorted(_NAMES))}") from None
    value = getattr(importlib.import_module(module), attr)
    globals()[name] = value                       # read once
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
