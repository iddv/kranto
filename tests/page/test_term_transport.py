"""Open in Claude Code's transport: the routes, and the terminal's
WebSocket as plain ASGI. The WebSocket checks Host, Origin, the owner and a one-time ticket
itself (Starlette's guard middleware never sees a WebSocket); every refusal happens before the
upgrade and spends no ticket. Kranto's own route in front of it is tested in the server."""
from __future__ import annotations

import asyncio
import json

import pytest

from kranto.page.term import asgi

from .term_common import canary, make_repo, make_term

OWNER = {"origin": "ui"}


@pytest.fixture
def term(tmp_path, monkeypatch):
    t = make_term(tmp_path, monkeypatch, token=canary("claude"),
                  source=make_repo(tmp_path / "source"), sandboxed=False)
    monkeypatch.setattr(asgi, "_SERVED", [True])
    yield t
    for tid in list(t.live):
        t.end(tid, remove=False)


class App:
    """What ``asgi.endpoint`` needs of the app: its ``term``."""

    def __init__(self, term):
        self.term = term


def ws(term, tid, ticket, host="127.0.0.1:8765", origin="same", identity=OWNER,
       frames=(), until=None, timeout=10.0):
    """One WebSocket session against the endpoint: sends ``frames`` (text) after the accept,
    collects what comes back until ``until(out)`` or the close. A string among the frames is a
    gate: the frames after it go once the screen shows it."""
    origin = f"http://{host}" if origin == "same" else origin
    headers = [(b"host", host.encode())] + ([(b"origin", origin.encode())] if origin else [])
    scope = {"type": "websocket", "path": f"/brb/term/ws/{tid}",
             "query_string": f"ticket={ticket}".encode(), "headers": headers}
    out = []

    async def main():
        inbox: asyncio.Queue = asyncio.Queue()
        await inbox.put({"type": "websocket.connect"})
        done = asyncio.Event()
        pending, gate = list(frames), [None]

        async def feed():
            while pending:
                f = pending.pop(0)
                if isinstance(f, str):
                    gate[0] = f
                    return
                await inbox.put({"type": "websocket.receive", "text": json.dumps(f)})
            gate[0] = None

        async def receive():
            return await inbox.get()

        async def send(m):
            out.append(m)
            if m["type"] == "websocket.accept" or (gate[0] and gate[0] in screen(out)):
                await feed()
            if m["type"] == "websocket.close" or (until and until(out)):
                done.set()
        task = asyncio.ensure_future(asgi.endpoint(scope, receive, send, identity=identity,
                                                   app=App(term)))
        try:
            await asyncio.wait_for(done.wait(), timeout)
        finally:
            await inbox.put({"type": "websocket.disconnect"})
            await asyncio.wait_for(task, 5)
    asyncio.run(main())
    return out


def screen(out) -> str:
    return b"".join(m.get("bytes") or b"" for m in out if m["type"] == "websocket.send").decode(
        errors="replace")


def opened(term):
    return term.open({"kind": "project", "id": "p1"})


@pytest.mark.parametrize("host,origin,identity,why", [
    ("evil.example:8765", "same", OWNER, "unknown host"),             # DNS rebinding
    ("192.168.1.5:8765", "same", OWNER, "unknown host"),              # a LAN address
    ("127.0.0.1:8765", "http://evil.example", OWNER, "cross-origin"),  # another site's page
    ("127.0.0.1:8765", "http://127.0.0.1:9999", OWNER, "cross-origin"),  # another port
    ("127.0.0.1:8765", None, OWNER, "cross-origin"),                  # no Origin at all
    ("127.0.0.1:8765", "same", None, "not signed in"),                # no cookie
    ("127.0.0.1:8765", "same", {"origin": "mcp"}, "not signed in"),   # a token, not the owner
])
def test_a_foreign_or_unsigned_handshake_is_refused_and_spends_no_ticket(term, host, origin,
                                                                       identity, why):
    o = opened(term)
    out = ws(term, o["tid"], o["ticket"], host=host, origin=origin, identity=identity)
    assert [m["type"] for m in out] == ["websocket.close"] and out[0]["reason"] == why
    assert term.redeem(o["tid"], o["ticket"]) is not None              # still unspent


def test_a_guessed_reused_or_other_sessions_ticket_is_refused(term):
    o = opened(term)
    assert ws(term, o["tid"], canary("guess"))[0]["type"] == "websocket.close"
    other = term.open({"kind": "project", "id": "p2"})
    assert ws(term, o["tid"], other["ticket"])[0]["type"] == "websocket.close"
    t = term.ticket(o["tid"])
    first = ws(term, o["tid"], t, until=lambda out: "> " in screen(out))
    assert first[0]["type"] == "websocket.accept"
    assert ws(term, o["tid"], t)[0]["type"] == "websocket.close"        # spent


def test_through_a_tunnel_to_another_port_the_same_origin_is_accepted(term):
    o = opened(term)
    out = ws(term, o["tid"], o["ticket"], host="localhost:18765",
             until=lambda out: "> " in screen(out))
    assert out[0]["type"] == "websocket.accept"


def test_keys_resize_and_the_end_travel_over_the_socket(term):
    from .term_common import Screen
    o = opened(term)
    first = Screen()
    term.live[o["tid"]].pty.attach(first)
    first.wait("\n> ")                                         # the program is up
    # the keys wait for the new size on screen: the attach's redraw steps the size too, and
    # SIGWINCHes that arrive together are one signal
    out = ws(term, o["tid"], o["ticket"],
             frames=[{"t": "resize", "cols": 77, "rows": 21}, "[size 77x21]",
                     {"t": "in", "d": "hello\n"}, {"t": "in", "d": "exit\n"}],
             until=lambda out: any('"exit"' in (m.get("text") or "") for m in out))
    s = screen(out)
    assert "[size 77x21]" in s and "you said: hello" in s and "bye" in s
    assert json.loads([m for m in out if m.get("text")][-1]["text"]) == {"t": "exit", "code": 0}


def test_a_viewers_resize_during_the_attach_redraw_is_never_undone(term, monkeypatch):
    """The redraw steps one column and back; a viewer's resize in between wins, even to the
    stepped size itself (the step back once put the old size back over it)."""
    import time
    import types

    from kranto.page.term import pty as pty_mod
    p = term.live[opened(term)["tid"]].pty
    cols, rows = p.cols, p.rows
    p.redraw()                                                         # nobody resized: back
    assert (p.cols, p.rows) == (cols, rows)
    monkeypatch.setattr(pty_mod, "time", types.SimpleNamespace(
        time=time.time, sleep=lambda s: p.resize(cols - 1, rows)))      # the viewer, mid-step
    p.redraw()
    assert (p.cols, p.rows) == (cols - 1, rows)


def test_a_viewer_that_falls_behind_is_told_to_reattach(term, monkeypatch):
    monkeypatch.setattr(asgi, "BEHIND", 64)
    o = opened(term)
    out = ws(term, o["tid"], o["ticket"], frames=[{"t": "in", "d": "say " + "x" * 300 + "\n"}],
             until=lambda out: any((m.get("text") or "") == '{"t":"dropped"}' for m in out))
    assert any((m.get("text") or "") == '{"t":"dropped"}' for m in out)
    assert term.live[o["tid"]].pty.alive                               # the program goes on


def test_the_routes_open_list_end_and_say_when_there_is_no_socket(term, monkeypatch):
    from kranto.page.ui import api
    app = term.app
    app.term_ = term

    def call(method, path, body=None, query=None):
        monkeypatch.setattr(api.App, "term", property(lambda self: term), raising=False)
        code, _, data = api.handle(method, path, query, json.dumps(body or {}).encode(),
                                   app=api.App(None, "fake", term.app.loop_home))
        return code, json.loads(data)
    code, body = call("POST", "/api/term/open", {"subject": {"kind": "project", "id": "p1"}})
    assert code == 200 and body["ticket"] and body["state"] == "running"
    code, lst = call("GET", "/api/term")
    assert code == 200 and lst["socket"] is True and [s["tid"] for s in lst["sessions"]] == \
        [body["tid"]]
    assert "ticket" not in json.dumps(lst)                             # a GET never hands one out
    code, _ = call("POST", "/api/term/end", {"tid": body["tid"]})
    assert code == 200
    monkeypatch.setattr(asgi, "_SERVED", [False])
    code, err = call("POST", "/api/term/open", {"subject": {"kind": "project", "id": "p1"}})
    assert code == 503 and "kranto up" in err["error"]
