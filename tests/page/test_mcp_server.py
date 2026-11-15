"""The MCP SDK wiring of kranto mcp (only with the mcp extra installed)."""
import asyncio

import pytest

pytest.importorskip("mcp")

from kranto.page.mcp import server  # noqa: E402
from kranto.page.mcp import tools as T


def test_the_sdk_server_lists_every_tool_with_its_schema_and_hints():
    srv = server.build_server(T.Client(get=None, post=None))
    res = asyncio.run(srv.kranto_list())
    by = {t.name: t for t in res.tools}
    assert set(by) == {t["name"] for t in T.tools()}

    def attr(o, camel, snake):                       # mcp 1.x camelCase, 2.x snake_case
        return getattr(o, snake) if hasattr(o, snake) else getattr(o, camel)
    assert attr(by["kranto_status"].annotations, "readOnlyHint", "read_only_hint") is True
    # without a host the tools are Kranto's reads only: the factory's action tools left (CUT)
    for name, t in by.items():
        assert attr(t.annotations, "readOnlyHint", "read_only_hint") is True, name
        assert attr(t, "inputSchema", "input_schema")["type"] == "object", name


def test_a_non_loopback_url_never_starts(capsys):
    assert server.main("http://10.0.0.2:8765") == 2
    assert "this machine only" in capsys.readouterr().err
