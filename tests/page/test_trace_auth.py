"""A trace is the owner's to read (decision D-4): unlike the other reads, a GET
of a trace needs the signed-in page's cookie or a token, and only the owner's (the UI's or the
CLI's): an agent's, MCP's or a build's own token is refused. Against ``brb ui``'s own server;
Kranto's host does the same in the server (``web/auth.py``)."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from kranto.page.tokens import Store
from kranto.page.ui import api
from kranto.page.ui.server import make_server

from .auth_common import bearer, ui_bearer
from .test_trace_session import TID as SESSION
from .test_trace_session import make_session

TID = f"session:{SESSION}"


@pytest.fixture
def base(tmp_path):
    from kranto.page.trace import service
    service._TRACES.clear()
    root = tmp_path / "tasks"
    root.mkdir()
    (tmp_path / "loop").mkdir()
    make_session(tmp_path / "loop")
    srv = make_server(root, port=0, harness="fake", loop_home=tmp_path / "loop", require=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def call(url: str, headers: dict | None = None, method: str = "GET") -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read()
        return e.code, json.loads(body) if body else {}


PATHS = ["/api/traces", f"/api/trace?trace={TID}", f"/api/trace/spans?trace={TID}",
         f"/api/trace/download?trace={TID}"]


@pytest.mark.parametrize("path", PATHS)
def test_without_a_token_a_trace_is_not_read(base, path):
    code, body = call(base + path)
    assert code == 401 and "not signed in" in body["error"]


@pytest.mark.parametrize("path", PATHS)
def test_the_owner_reads_it(base, path):
    code, _ = call(base + path, ui_bearer())
    assert code == 200


@pytest.mark.parametrize("who", ["agent:RC", "mcp"])
def test_another_token_is_refused(base, who):
    if who.startswith("agent:"):
        Store().add(who)
    code, body = call(base + "/api/traces", bearer(who))
    assert code == 403 and "the owner's" in body["error"]


def test_head_does_not_get_round_it(base):
    code, _ = call(base + f"/api/trace?trace={TID}", method="HEAD")
    assert code == 405


def test_the_other_reads_are_as_they_were(base):
    code, _ = call(base + "/api/header")
    assert code == 200


def test_the_host_is_told_which_reads_need_an_identity():
    for p in ("/api/traces", "/api/trace", "/api/trace/", "/api/trace/spans",
              "/api/trace/payload"):
        assert api.read_needs_identity(p), p
    for p in ("/api/tracer", "/api/info", "/api/kranto", "/api/build"):
        assert not api.read_needs_identity(p), p
