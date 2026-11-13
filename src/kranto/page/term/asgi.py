"""The terminal's WebSocket, ``/brb/term/ws/<tid>?ticket=…`` on Kranto's Starlette app
. Plain ASGI (the page has no web framework); Kranto's host routes the
WebSocket scope here after its own checks, and this checks again, because Starlette's guard
middleware never sees a WebSocket:

- the Host's hostname is loopback (any port: an ``ssh -L`` tunnel arrives as
  ``localhost:<laptop port>``), so a DNS-rebinding page is refused;
- the Origin is exactly ``http://<Host>`` (or https), so another site's page is refused;
- the caller is the owner (``identity``: the host found the owner's session cookie);
- the ticket is the one ``POST api/term/open`` gave for this session, unused and under 30 s old.

Frames: binary out (the terminal's raw bytes); text in, JSON: ``{"t": "in", "d": text}``,
``{"t": "resize", "cols", "rows"}``; text out: ``{"t": "exit", "code"}`` when the program
ends, ``{"t": "dropped"}`` when this viewer fell more than ``BEHIND`` bytes behind (the page
reattaches and gets the screen again; the program never waits for a viewer)."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs

LOOPBACK = ("127.0.0.1", "localhost", "::1")
BEHIND = 2 * 1024 * 1024
MAX_IN = 64 * 1024
_SERVED = [False]


def served() -> bool:
    """Whether a host serves this endpoint in this process (Kranto does; ``brb ui`` doesn't)."""
    return _SERVED[0]


def mark_served() -> None:
    _SERVED[0] = True


def _hostname(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def refusal(headers: dict, identity: dict | None) -> str | None:
    """Why this handshake is refused, or None."""
    host = headers.get("host", "")
    if _hostname(host) not in LOOPBACK:
        return "unknown host"
    origin = headers.get("origin", "")
    if origin not in (f"http://{host}", f"https://{host}"):
        return "cross-origin"
    if not identity or identity.get("origin") != "ui":
        return "not signed in"
    return None


async def endpoint(scope, receive, send, identity: dict | None = None, app=None) -> None:
    """One viewer of one session, for as long as the socket is open."""
    if scope.get("type") != "websocket":
        return
    headers = {k.decode("latin-1").lower(): v.decode("latin-1")
               for k, v in scope.get("headers") or []}
    msg = await receive()
    if msg.get("type") != "websocket.connect":
        return
    why = refusal(headers, identity)
    tid = (scope.get("path") or "").rstrip("/").rsplit("/", 1)[-1]
    q = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    ticket = (q.get("ticket") or [""])[0]
    if app is None:
        from ..ui import api
        app = api.default_app()
    live = None if why else app.term.redeem(tid, ticket)
    if live is None:
        # refused before the upgrade: the browser sees a failed handshake (HTTP 403)
        await send({"type": "websocket.close", "code": 4403,
                    "reason": why or "no such running session, or the ticket is spent"})
        return
    await send({"type": "websocket.accept"})
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    pending = [0]
    state = {"dropped": False}

    def sink(data):                           # on the terminal's reader thread
        if state["dropped"]:
            return False
        if data is not None:
            if pending[0] + len(data) > BEHIND:
                state["dropped"] = True
                loop.call_soon_threadsafe(queue.put_nowait, ("dropped", None))
                return False
            pending[0] += len(data)
        loop.call_soon_threadsafe(queue.put_nowait, ("out", data))
        return True

    key = live.pty.attach(sink)
    asyncio.ensure_future(asyncio.to_thread(live.pty.redraw))      # a whole screen, not just the ring

    async def pump_out():
        while True:
            kind, data = await queue.get()
            if kind == "dropped":
                await send({"type": "websocket.send", "text": '{"t":"dropped"}'})
                return
            if data is None:
                await send({"type": "websocket.send",
                            "text": json.dumps({"t": "exit", "code": live.pty.code})})
                return
            pending[0] -= len(data)
            await send({"type": "websocket.send", "bytes": bytes(data)})

    async def pump_in():
        while True:
            m = await receive()
            if m.get("type") == "websocket.disconnect":
                return
            text = m.get("text")
            if not text or len(text) > MAX_IN:  # stored-shape: not text first
                continue
            try:
                f = json.loads(text)
            except ValueError:
                continue
            if not isinstance(f, dict):
                continue
            if f.get("t") == "in" and isinstance(f.get("d"), str):
                await asyncio.to_thread(live.pty.write, f["d"].encode())
            elif f.get("t") == "resize":
                try:
                    live.pty.resize(int(f.get("cols")), int(f.get("rows")))
                except (TypeError, ValueError):
                    pass

    out_task = asyncio.ensure_future(pump_out())
    in_task = asyncio.ensure_future(pump_in())
    try:
        await asyncio.wait({out_task, in_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        live.pty.detach(key)
        for t in (out_task, in_task):
            t.cancel()
        try:
            await send({"type": "websocket.close", "code": 1000})
        except Exception:                      # noqa: BLE001 - the client is gone already
            pass
