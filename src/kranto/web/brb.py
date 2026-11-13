"""Kranto's page (the page's server: the page, its console and trace), mounted at ``/brb/``
(approach (a)).

the page exports one plain function through its host API, ``handle(method, path, query,
body) -> (status, content_type, body)``. When ``brb.enabled`` is set in kranto.yaml and that
import works, ``afk serve`` routes ``/brb/...`` to it, in Starlette's thread pool. The host's
guard (allowed Host names, same-origin writes, the content policy) covers the mount like
every other route.

It is refused, with a log line, when:

- the server is bound to anything but loopback: the page runs the owner's console, and its
  reads need no token;
- the page is too old (``API_VERSION`` below ``REQUIRED_API``): ``/brb/`` then says so
  instead of failing.

Without the page, or with ``brb.enabled`` off, nothing is mounted and the pages show
the server's own header.

Mounted, the page is told this server's URL (``kranto_url``) when it accepts one, and
reads idea cards from ``/api/ideas`` there instead of opening the server's database.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from .auth import IDENTITY

log = logging.getLogger(__name__)

REQUIRED_API = 1
LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_BODY_BYTES = 1_000_000


@dataclass
class Brb:
    """What ``load`` found: ``state`` is ``mounted``, ``off``, ``missing``, ``too_old`` or
    ``not_loopback``; ``api`` is the page's API module when mounted."""

    state: str
    message: str = ""
    api: Any = None

    @property
    def mounted(self) -> bool:
        return self.state == "mounted"

    def call(self, method: str, path: str, query: str = "", body: Any = None,
             identity: dict | None = None) -> tuple[int, str, bytes]:
        """One request to the page. ``identity``: the caller the host's token check found
        (OI); the page acts as that caller and ignores the body's ``origin``."""
        if identity is not None and "identity" in _params(self.api.handle):
            return self.api.handle(method, path, query, body, identity=identity)
        return self.api.handle(method, path, query, body)

    def call_with_headers(self, method: str, path: str, query: str = "", body: Any = None,
                          identity: dict | None = None) -> tuple[int, str, bytes, dict]:
        """``call``, plus the headers the page asks the host to add (``handle_with_headers``:
        its versioned static files may be cached for good). An older the page gives none."""
        fn = getattr(self.api, "handle_with_headers", None)
        if fn is None:
            return (*self.call(method, path, query, body, identity), {})
        if identity is not None:
            return fn(method, path, query, body, identity=identity)
        return fn(method, path, query, body)


def self_url(bind_host: str | None, port: int | None) -> str | None:
    """This server's own base URL on loopback, or None when the port is not known."""
    if not port:
        return None
    host = (bind_host or "127.0.0.1").strip("[]")
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def load(cfg, bind_host: str | None, port: int | None = None,
         data_dir: Path | None = None) -> Brb:
    """Decide whether to mount the page. ``cfg`` is ``Config.brb``; ``bind_host`` is the
    address the server is bound to (None: loopback, as in tests); ``port`` the one it
    listens on; ``data_dir`` the server's data folder, whose ``activity.json`` the page's live
    feed watches (ACT: a the page that does not take it is mounted as before). A the page from
    before the cut that still takes ``builds`` is told False: it serves the page without its
    builds, projects and repos, and never opens the loop's ledger."""
    if not cfg.enabled:
        return Brb("off")
    host = (bind_host or "127.0.0.1").strip("[]").lower()
    if host not in LOOPBACK_BINDS:
        msg = (f"brb.enabled is set but the server is bound to {host}: the page is not "
               "mounted (it is only mounted on loopback)")
        log.warning(msg)
        return Brb("not_loopback", msg)
    try:
        from kranto.page import host_api as api
        from kranto.page.host_api import handle  # noqa: F401  (the mount's module, now)
    except ImportError as exc:
        msg = f"brb.enabled is set but the page is not installed here ({exc})"
        log.warning(msg)
        return Brb("missing", msg)
    version = getattr(api, "API_VERSION", 0)
    if not isinstance(version, int) or version < REQUIRED_API:
        msg = (f"the page is too old: its API version is {version}, and this the server needs "
               f"{REQUIRED_API}. Update the page in this environment.")
        log.warning(msg)
        return Brb("too_old", msg, api)
    kwargs: dict[str, Any] = {}
    url = self_url(bind_host, port)
    params = inspect.signature(api.configure).parameters
    if url and "kranto_url" in params:
        kwargs["kranto_url"] = url
    if data_dir is not None and "kranto_data" in params:
        kwargs["kranto_data"] = str(data_dir)
    if "builds" in params:
        kwargs["builds"] = False
    api.configure(cfg.root, cfg.harness, cfg.loop_home, **kwargs)
    log.info("the page mounted at /brb/ (API version %s)", version)
    return Brb("mounted", api=api)


def routes(brb: Brb) -> list[Route]:
    if brb.state == "too_old":
        async def too_old(request: Request):
            return HTMLResponse(f"<!doctype html><title>Kranto</title><p>{_esc(brb.message)}</p>",
                                status_code=503)
        return [Route("/brb", too_old), Route("/brb/{path:path}", too_old)]
    if not brb.mounted:
        return []

    async def endpoint(request: Request):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return Response("request body too large", status_code=413)
        body = await request.body() if request.method == "POST" else b""
        if len(body) > MAX_BODY_BYTES:
            return Response("request body too large", status_code=413)
        path = "/" + request.path_params.get("path", "")
        if request.method == "GET":
            live = await _stream(brb, request, path)
            if live is not None:
                return live
        # the caller the guard found: every write's, and an owner-only read's (a trace)
        status, ctype, data, extra = await run_in_threadpool(
            brb.call_with_headers, request.method, path, request.url.query, body,
            request.scope.get(IDENTITY))
        headers = {"content-type": ctype, "cache-control": "no-store"}
        immutable = "immutable" in str(extra.get("cache-control", ""))
        if immutable:
            headers["cache-control"] = extra["cache-control"]
            headers["vary"] = "accept-encoding"
            if "gzip" in request.headers.get("accept-encoding", "") and len(data) > 1024:
                data = _gzipped(path, data)
                headers["content-encoding"] = "gzip"
        return Response(data, status_code=status, headers=headers)

    return [Route("/brb", lambda r: RedirectResponse("/brb/", status_code=307)),
            Route("/brb/{path:path}", endpoint, methods=["GET", "HEAD", "POST"])]


TERM_WS = "/brb/term/ws/{tid}"


def _hostname(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def term_routes(brb: Brb, auth, allowed_hosts) -> list:
    """Open in Claude Code's terminal, ``/brb/term/ws/<tid>``: a WebSocket, served by
    the page's ``term_ws``. The host's guard is HTTP middleware and never sees a WebSocket, so
    this route checks for itself before the page does again: the Host is one of the allowed
    names, the Origin is exactly this Host's, and the caller is the signed-in owner (the
    session cookie; a browser cannot send a bearer token). the page then checks the one-time
    ticket that ``POST /brb/api/term/open`` gave."""
    if not brb.mounted:
        return []
    try:
        from kranto.page.host_api import term_ws, term_ws_served
    except ImportError:
        return []
    term_ws_served()
    hosts = frozenset(h.lower() for h in allowed_hosts)

    async def endpoint(websocket: WebSocket):
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin", "")
        ident, _ = auth.identify(websocket) if auth is not None else (None, None)
        if _hostname(host) not in hosts:
            why = "unknown host"
        elif origin not in (f"http://{host}", f"https://{host}"):
            why = "cross-origin"
        elif not ident or ident.get("origin") != "ui" or ident.get("via") != "cookie":
            why = "not signed in"
        else:
            why = None
        if why:
            log.warning("refused the terminal's socket: %s", why)
            await websocket.close(code=4403, reason=why)
            return
        await term_ws(websocket.scope, websocket.receive, websocket.send, identity=ident)

    return [WebSocketRoute(TERM_WS, endpoint)]


async def _stream(brb: Brb, request: Request, path: str) -> Response | None:
    """the page's live feed (``/brb/api/stream``, its ``api.stream``): server-sent events
    written as they come, each wait in the thread pool. None for every other path, and for a
    the page without the feed (the page then polls, as before). A GET like every read: the
    host's guard has already checked the Host; no token, no secret."""
    fn = getattr(brb.api, "stream", None)
    if fn is None or path.rstrip("/") != "/api/stream":
        return None
    try:
        events = await run_in_threadpool(fn, path, request.url.query,
                                         last=request.headers.get("last-event-id"))
    except Exception as exc:  # noqa: BLE001 - every place taken (503), or a broken feed
        code = getattr(exc, "code", 500)
        return JSONResponse({"error": str(exc) if code == 503 else "the live feed failed"},
                            status_code=503 if code == 503 else 500)
    if events is None:
        return None
    return StreamingResponse(iterate_in_threadpool(events), media_type="text/event-stream",
                             headers={"cache-control": "no-store"},
                             background=BackgroundTask(events.close))


_GZ: dict[tuple[str, int, int], bytes] = {}       # an immutable file, compressed once


def _gzipped(path: str, data: bytes) -> bytes:
    """``data`` gzipped, cached by path, size and hash: a versioned file never changes."""
    import gzip
    key = (path, len(data), hash(data))
    out = _GZ.get(key)
    if out is None:
        if len(_GZ) > 64:
            _GZ.clear()
        out = _GZ[key] = gzip.compress(data, compresslevel=6, mtime=0)
    return out


def _params(fn) -> set[str]:
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
