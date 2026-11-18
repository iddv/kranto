"""The newsletter platform over HTTP: which platform the newsletter goes out through,
and whether it is ready. Connecting one is the Connections flow (``POST
/api/connections/<platform>/credentials``, Save and test); this is what Settings › Accounts ›
Newsletter reads and presses around it.

| Method and path               | Does                                                          |
|-------------------------------|---------------------------------------------------------------|
| GET  /api/newsletter          | the platform in use (none until one is connected), the ones   |
|                               | offered, the connection, from, audience, ready, what is       |
|                               | missing; Kranto's own rows only, no request leaves the machine  |
| POST /api/newsletter/check    | Check again: reads only, at the platform (its key's           |
|                               | permission, the domain, the audience), and says what is       |
|                               | missing in plain words                                        |
| POST /api/newsletter/audience | ``{confirm: true, name}``, the page only: make the audience   |
|                               | at a platform that has them (an owner's press, never a cub's) |

None of these sends an issue: that is a ticket's confirm (``/api/tickets/<id>/confirm``).
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import newsletter
from ..connections import OAuthError
from ..core import tickets
from ..sources.base import SourceError
from .auth import IDENTITY

BASE = "/api/newsletter"


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class NewsletterAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def status(self, request: Request):
        return JSONResponse(await run_in_threadpool(newsletter.status, self.rt))

    async def check(self, request: Request):
        found = await run_in_threadpool(newsletter.check, self.rt)
        out = await run_in_threadpool(newsletter.status, self.rt)
        return JSONResponse({**out, "ok": found.ok, "said": found.said,
                             "missing": found.missing or out["missing"],
                             "message": found.words()})

    async def audience(self, request: Request):
        if tickets.door_of(request.scope.get(IDENTITY)) != "ui":
            return _error("an audience is made on the Accounts page only, with its confirm", 403)
        from .app import _json_body
        body = await _json_body(request) or {}
        name = str(body.get("name") or "").strip()
        if body.get("confirm") is not True:
            return _error("this needs confirm: true (the page's confirm)")
        if not name or len(name) > 80:
            return _error("the audience's name is 1 to 80 characters")
        p = newsletter.named(self.rt.store)
        if p is None or not hasattr(p, "create_audience"):
            return _error("the newsletter platform in use has no audiences to make here", 409)
        conns = self.rt.connections
        try:
            http = conns.http_for(p.id, None, self.rt.http)
            made = await run_in_threadpool(p.create_audience, http, name)
        except (OAuthError, SourceError) as exc:
            return _error(f"{p.name} did not make it: {exc}"[:300])
        snd = newsletter.sender(self.rt.store)
        newsletter.keep_sender(self.rt.store, p, {**snd, **made})
        found = await run_in_threadpool(newsletter.check, self.rt)
        return JSONResponse({**newsletter.status(self.rt), "ok": True,
                             "message": f"Made the audience {name} at {p.name}. "
                                        + found.words()})

    def routes(self) -> list[Route]:
        return [Route(BASE, self.status),
                Route(f"{BASE}/check", self.check, methods=["POST"]),
                Route(f"{BASE}/audience", self.audience, methods=["POST"])]
