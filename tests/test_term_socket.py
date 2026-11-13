"""Open in Claude Code's terminal socket on Kranto's app (the page's).

The host's guard is HTTP middleware and never sees a WebSocket, so ``/brb/term/ws/<tid>``
checks for itself: an allowed Host, the Host's own Origin, the signed-in owner's cookie. Only
then does the page's ``term_ws`` run (here a stand-in that records the call and echoes). The
one route that starts a session is a POST, which the guard keeps to the owner's same-origin
requests: another site's form, no-cors fetch or CORS fetch starts nothing."""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from kranto.web.app import create_app

from . import brbfake
from .test_auth import IdentityApi, runtime

BASE = "http://127.0.0.1:8765"


class Calls(list):
    pass


@pytest.fixture
def setup(tmp_path, store, embedder, make_client, monkeypatch):
    api = IdentityApi()
    calls = Calls()
    served = []

    async def term_ws(scope, receive, send, identity=None):
        calls.append((scope["path"], identity))
        await receive()                                  # websocket.connect
        await send({"type": "websocket.accept"})
        m = await receive()
        await send({"type": "websocket.send", "text": json.dumps({"echo": m.get("text")})})
        await send({"type": "websocket.close", "code": 1000})

    brbfake.install(monkeypatch, api, term_ws=term_ws, term_ws_served=lambda: served.append(1))
    rt = runtime(tmp_path, store, embedder, make_client)
    app = create_app(rt, port=8765)
    return app, api, calls, served


def client(app, host="127.0.0.1:8765", signed_in=True):
    from starlette.testclient import TestClient
    c = TestClient(app, base_url=f"http://{host}")
    if signed_in:
        auth = app.state.app.auth
        c.cookies.set(auth.cookie, auth.store.value("ui"))
    return c


def handshake(c, host="127.0.0.1:8765", origin="same", extra=None):
    origin = f"http://{host}" if origin == "same" else origin
    headers = {"host": host, **({"origin": origin} if origin else {}), **(extra or {})}
    return c.websocket_connect("/brb/term/ws/c3f1a9e2?ticket=t", headers=headers)


def test_the_owners_page_reaches_page_with_who_it_is(setup):
    app, _, calls, served = setup
    assert served == [1]
    with client(app) as c, handshake(c) as ws:
        ws.send_text("hello")
        assert json.loads(ws.receive_text()) == {"echo": "hello"}
    assert calls[0][0] == "/brb/term/ws/c3f1a9e2"
    assert calls[0][1]["origin"] == "ui" and calls[0][1]["via"] == "cookie"


@pytest.mark.parametrize("host,origin,signed_in,extra", [
    ("evil.example:8765", "same", True, None),               # DNS rebinding
    ("192.168.1.5:8765", "same", True, None),                # a LAN address
    ("127.0.0.1:8765", "http://evil.example", True, None),   # another site's page
    ("127.0.0.1:8765", "http://127.0.0.1:9999", True, None),  # another local port
    ("127.0.0.1:8765", None, True, None),                    # no Origin
    ("127.0.0.1:8765", "same", False, None),                 # no cookie
])
def test_a_foreign_or_unsigned_handshake_never_reaches_page(setup, host, origin, signed_in,
                                                               extra):
    app, _, calls, _ = setup
    with client(app, signed_in=signed_in) as c, pytest.raises(WebSocketDisconnect) as e, \
            handshake(c, host, origin, extra):
        pass
    assert e.value.code == 4403 and calls == []


def test_a_bearer_token_is_not_the_owners_page(setup):
    app, _, calls, _ = setup
    from kranto import tokens
    hdr = {"authorization": "Bearer " + tokens.Store().value("cli")}
    with client(app, signed_in=False) as c, pytest.raises(WebSocketDisconnect), \
            handshake(c, extra=hdr):
        pass
    assert calls == []


def test_through_a_tunnel_to_another_local_port_the_page_still_connects(setup):
    app, _, calls, _ = setup
    with client(app, host="localhost:18765") as c, handshake(c, host="localhost:18765") as ws:
        ws.send_text("x")
        ws.receive_text()
    assert len(calls) == 1


def test_another_site_cannot_start_a_session(setup):
    app, api, _, _ = setup
    body = json.dumps({"subject": {"kind": "build", "id": "b"}})
    with client(app) as c:                               # the owner's browser, its cookie set
        # a form POST from another site (text/plain or urlencoded), a no-cors fetch (no
        # Origin it controls), a CORS fetch with its own Origin
        for headers in ({"origin": "http://evil.example",
                         "content-type": "application/x-www-form-urlencoded"},
                        {"origin": "http://evil.example", "content-type": "text/plain"},
                        {"origin": "null", "content-type": "text/plain"},
                        {"content-type": "application/json"},
                        {"origin": "http://127.0.0.1:9999",
                         "content-type": "application/json"}):
            r = c.post("/brb/api/term/open", content=body, headers=headers)
            assert r.status_code == 403, headers
    assert not [x for x in api.calls if x[1] == "/api/term/open"]
    with client(app) as c:                               # the page itself
        r = c.post("/brb/api/term/open", content=body,
                   headers={"origin": BASE, "content-type": "application/json"})
    assert r.status_code not in (401, 403)              # the guard let it through to the page
    assert "/api/term/open" in [x[1] for x in api.calls]


def test_an_older_page_has_no_terminal_route(tmp_path, store, embedder, make_client,
                                                monkeypatch):
    brbfake.install(monkeypatch, IdentityApi())
    brbfake.drop(monkeypatch, "term_ws")
    app = create_app(runtime(tmp_path, store, embedder, make_client), port=8765)
    assert not [r for r in app.routes if getattr(r, "path", "") == "/brb/term/ws/{tid}"]
