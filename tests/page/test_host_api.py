"""kranto.page.host_api: the names Kranto (the host) may use, each resolving to the
thing it always was, none imported before it is read."""
import subprocess
import sys

import pytest

from kranto.page import host_api

# The host's contract. A change here is a change the server must make in the same release; a
# change of meaning bumps HOST_API_VERSION (2: the factory left, cut 3).
CONTRACT = {
    "API_VERSION", "configure", "handle", "handle_with_headers", "stream",
    "selfcheck_paths",    # the post-update self-check's reads of the mount (RCA D1)
    "Config", "write_setting", "mcp_available", "mcp_main",
    "term_ws", "term_ws_served", "term_cli", "term_mcp_main", "term_doctor",
    "add_trace_group", "claude_print", "ClaudePrintError",
    "telemetry_sink", "telemetry_schema", "telemetry_facts", "detached_jobs", "term_shutdown"}


def test_the_names_are_the_contract_and_the_version_is_two():
    assert set(host_api._NAMES) == CONTRACT
    assert host_api.HOST_API_VERSION == 2
    assert set(dir(host_api)) == CONTRACT | {"HOST_API_VERSION"}


def test_each_name_is_the_thing_it_always_was():
    from kranto.page.box import print_call
    from kranto.page.settings import store, write
    from kranto.page.ui import api
    assert host_api.handle is api.handle and host_api.configure is api.configure
    assert host_api.API_VERSION == api.API_VERSION and host_api.Config is store.Config
    assert host_api.write_setting is write.write and host_api.stream is api.stream
    assert host_api.claude_print is print_call.claude_print
    for name in CONTRACT - {"mcp_available", "mcp_main"}:      # the MCP SDK is optional
        assert getattr(host_api, name) is not None, name


def test_anything_else_is_refused_in_words():
    with pytest.raises(AttributeError, match="the host may use only"):
        host_api.daemon                                       # noqa: B018


def test_importing_it_imports_nothing_else():
    code = ("import sys, kranto.page.host_api; "
            "print(sorted(m for m in sys.modules if m.startswith('kranto.page')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=60, check=True).stdout
    assert out.strip() == "['kranto.page', 'kranto.page.host_api']"
