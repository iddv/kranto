"""``brb ui``: the page on its own over HTTP (the builds it once ran left with the factory)."""
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from kranto.page.ui.server import make_server

from .auth_common import ui_bearer


@pytest.fixture
def ui(tmp_path):
    srv = make_server(None, port=0, harness="fake", loop_home=tmp_path / "loop")
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()
    srv.server_close()


def get(base, path, **q):
    url = base + path + ("?" + urllib.parse.urlencode(q) if q else "")
    with urllib.request.urlopen(url, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if "json" in r.headers["Content-Type"] else body


def post(base, path, body, headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Origin": base,
                                  **ui_bearer(), **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def test_page_is_served(ui):           # conftest's stand-in build when the UI is not built
    html = get(ui, "/")
    assert "<title>Kranto</title>" in html and '<script type="module" src="static/v' in html
    assert re.search(r'src="static/v[^/"]+/app/app-[\w-]+\.js"', html)   # this version's address


def test_the_header_and_a_console_setting_over_http(ui):
    assert get(ui, "/api/header")["running"] == 0
    out = post(ui, "/api/term/settings", {"key": "term.allow_api_key", "value": True})
    assert out == {"ok": True, "key": "term.allow_api_key", "value": True}


def test_a_removed_route_is_404_over_http(ui):
    for path in ("/api/kranto", "/api/builds", "/api/info", "/api/events"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(ui, path)
        assert e.value.code == 404, path


def test_cross_origin_post_refused(ui):
    req = urllib.request.Request(ui + "/api/term/settings", b'{"key": "term.enabled"}',
                                 {"Content-Type": "application/json",
                                  "Origin": "http://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403


def test_a_post_without_a_token_is_refused(ui):
    req = urllib.request.Request(ui + "/api/term/settings",
                                 b'{"key": "term.enabled", "value": true}',
                                 {"Content-Type": "application/json", "Origin": ui})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 401


def test_binds_loopback_only():
    from kranto.page.ui.server import HOST
    assert HOST == "127.0.0.1"


def test_busy_port_moves_to_next(tmp_path):
    # Another service (the server, say) may already hold the port: a busy port must not be fatal.
    blocker = make_server(tmp_path, port=0, harness="fake")
    busy = blocker.server_address[1]
    try:
        srv = make_server(tmp_path, port=busy, harness="fake", tries=5)
        assert srv.server_address[1] != busy
        srv.server_close()
        with pytest.raises(OSError):
            make_server(tmp_path, port=busy, harness="fake")      # tries=1: no fallback
    finally:
        blocker.server_close()
