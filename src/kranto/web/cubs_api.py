"""The cubs over HTTP: the list, one cub, fetch jobs, install, update,
remove, the owner's switches and the log.

| Method and path                          | Class                                            |
|------------------------------------------|--------------------------------------------------|
| GET  /api/cubs, /api/cubs/{id}           | read                                             |
| GET  /api/cubs/jobs, /api/cubs/jobs/{job}| read                                             |
| GET  /api/cubs/{id}/log                  | read                                             |
| POST /api/cubs/fetch                     | click, the page or the command line              |
| POST /api/cubs/jobs/{job}/cancel         | click                                            |
| POST /api/cubs/{id}/install              | house: ``{job, confirm: true, topics?}``, page   |
| POST /api/cubs/{id}/update               | click                                            |
| POST /api/cubs/{id}/apply_update         | house when the delta grew or the cub sends;      |
|                                          | else confirm                                     |
| POST /api/cubs/{id}/enable, /disable     | click, page or command line                      |
| POST /api/cubs/{id}/stop, /resume        | click, page or command line                      |
| POST /api/cubs/{id}/dry                  | click, page or command line: ``{kind}``          |
| POST /api/cubs/{id}/live                 | house: ``{kind, confirm: true}``, page only      |
| POST /api/cubs/{id}/remove               | house: ``{confirm: true, purge?}``, page only    |
| POST /api/cubs/{id}/run                  | click: ``{job, topic_id?}``                      |
| POST /api/cubs/settings                  | ``{key, value}``: house for ``cubs.enabled``,    |
|                                          | confirm for a cap, click else; never ``live``    |

**house** is ``{confirm: true}`` from the ``ui`` door (the page's session cookie) only: the
command line's token, ``kranto mcp``, an agent token and the UI's token sent as a bearer are
refused (403). Every state change says ``cub.<verb>`` on the bus.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..core import events, tickets
from ..core.cubs import install, logs, views
from ..core.cubs import settings as cub_settings
from ..core.cubs.runtime import CubUnavailable
from ..core.manifest import ID
from .auth import IDENTITY

DOORS = ("ui", "ui-token", "cli")


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class CubsAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def _body(self, request: Request) -> dict | None:
        from .app import _json_body
        return await _json_body(request)

    def _door(self, request: Request) -> str | None:
        return tickets.door_of(request.scope.get(IDENTITY))

    def _click(self, request: Request) -> JSONResponse | None:
        door = self._door(request)
        if door not in DOORS:
            return _error(f"this is done on the page or from the command line (not "
                          f"{door or 'here'})", 403)
        return None

    def _house(self, request: Request, body: dict | None, what: str) -> JSONResponse | None:
        if self._door(request) != "ui":
            return _error(f"{what} is done on the page only, with its confirm dialog", 403)
        if body is None or body.get("confirm") is not True:
            return _error(f"{what} needs the confirm dialog's answer (confirm: true)")
        return None

    def _cid(self, request: Request) -> str:
        """The cub a path's id means: ``blog`` reaches the owner's site cub while it stands in
        for Kranto's blog writer (``registry.resolve``; its rows are never rewritten)."""
        from ..core.cubs import registry
        return registry.resolve(self.rt.store, request.path_params["id"])

    def _row(self, request: Request, cid: str):
        """The cub's line, under the id the page asked by (``views.as_alias``)."""
        return views.as_alias(views.row(self.rt, cid), request.path_params["id"], cid)

    async def _run(self, fn, *args, **kw):
        try:
            return await run_in_threadpool(fn, *args, **kw), None
        except install.InstallError as exc:
            return None, _error(exc.words, exc.code)
        except CubUnavailable as exc:
            return None, _error(str(exc), exc.code)
        except ValueError as exc:
            return None, _error(str(exc))

    # -- reads ----------------------------------------------------------------------------------

    async def listing(self, request: Request):
        removed = request.query_params.get("all") in ("1", "true")
        return JSONResponse(await run_in_threadpool(views.listing, self.rt, removed=removed))

    async def one(self, request: Request):
        out = await run_in_threadpool(views.detail, self.rt, request.path_params["id"])
        return JSONResponse(out) if out is not None else _error("not found", 404)

    async def jobs(self, request: Request):
        return JSONResponse({"jobs": await run_in_threadpool(
            lambda: install.jobs(self.rt.store, self.rt.cfg, unreadable=True))})

    async def job(self, request: Request):
        out = await run_in_threadpool(install.job, self.rt.store, self.rt.cfg,
                                      request.path_params["job"])
        return JSONResponse(out) if out is not None else _error("not found", 404)

    async def log(self, request: Request):
        if not ID.fullmatch(request.path_params["id"]):   # a cub's id names its folder
            return _error("not found", 404)
        cid = self._cid(request)
        q = request.query_params
        try:
            limit = max(1, min(int(q.get("limit") or 200), 2000))
        except ValueError:
            return _error("limit is a number")
        from ..core.cubs.cli import since_of
        try:
            since = since_of(q.get("since"))
        except install.InstallError as exc:
            return _error(exc.words)
        lines = await run_in_threadpool(logs.read, self.rt.cfg, cid, since=since,
                                        run=q.get("run") or None, limit=limit)
        calls = [dict(r) for r in self.rt.store.query(
            "SELECT service, op, status, ticket_id, run_uuid, ms, bytes_in, bytes_out, detail, "
            "created_at FROM cub_calls WHERE cub = ? ORDER BY id DESC LIMIT ?", (cid, limit))]
        return JSONResponse({"lines": lines, "calls": calls})

    # -- install, update, remove ----------------------------------------------------------------

    async def fetch(self, request: Request):
        refused = self._click(request)
        if refused:
            return refused
        body = await self._body(request)
        if body is None or not isinstance(body.get("source", body.get("id")), str):
            return _error("expected {source, ref?} or {kind: update, id}")
        kind = body.get("kind") or "add"
        if kind not in ("add", "update"):
            return _error("kind is add or update")
        out, err = await self._run(install.start, self.rt, body.get("source"),
                                   ref=body.get("ref"), kind=kind, cid=body.get("id"))
        return err or JSONResponse({"job": out}, status_code=202)

    async def cancel(self, request: Request):
        refused = self._click(request)
        if refused:
            return refused
        out, err = await self._run(install.cancel, self.rt.store, self.rt.cfg,
                                   request.path_params["job"])
        return err or JSONResponse({"state": out["state"]})

    async def install(self, request: Request):
        body = await self._body(request)
        refused = self._house(request, body, "Installing a cub")
        if refused:
            return refused
        cid = request.path_params["id"]
        j = install.job(self.rt.store, self.rt.cfg, str(body.get("job") or ""))
        if j is None or (j.get("cub") or {}).get("id") != cid:
            return _error(f"no install of {cid} waits for your confirm", 409)
        out, err = await self._run(install.install, self.rt, j["id"], door="ui",
                                   topics=body.get("topics"))
        if err:
            return err
        return JSONResponse({"cub": await run_in_threadpool(views.row, self.rt, cid)})

    async def update(self, request: Request):
        refused = self._click(request)
        if refused:
            return refused
        out, err = await self._run(install.start, self.rt, kind="update",
                                   cid=self._cid(request))
        return err or JSONResponse({"job": out}, status_code=202)

    async def apply_update(self, request: Request):
        body = await self._body(request) or {}
        cid = self._cid(request)
        j = install.job(self.rt.store, self.rt.cfg, str(body.get("job") or ""))
        if j is None or j["kind"] != "update" or (j.get("cub") or {}).get("id") != cid:
            return _error(f"no update of {cid} waits for your confirm", 409)
        if j.get("needs") == "house":
            refused = self._house(request, body, "This update")
        else:
            refused = self._click(request) or (
                None if body.get("confirm") is True
                else _error("this update needs the confirm dialog's answer (confirm: true)"))
        if refused:
            return refused
        out, err = await self._run(install.apply_update, self.rt, j["id"], cid,
                                   door=self._door(request))
        if err:
            return err
        return JSONResponse({"cub": await run_in_threadpool(self._row, request, cid)})

    async def remove(self, request: Request):
        body = await self._body(request)
        refused = self._house(request, body, "Removing a cub")
        if refused:
            return refused
        out, err = await self._run(install.remove, self.rt, self._cid(request),
                                   purge=bool(body.get("purge")))
        return err or JSONResponse(out)

    # -- the owner's switches -------------------------------------------------------------------

    async def _switch(self, request: Request, fn, *args, **kw):
        refused = self._click(request)
        if refused:
            return refused
        cid = self._cid(request)
        out, err = await self._run(fn, self.rt, cid, *args, **kw)
        if err:
            return err
        return JSONResponse({"cub": await run_in_threadpool(self._row, request, cid)})

    async def enable(self, request: Request):
        return await self._switch(request, install.set_enabled, True)

    async def disable(self, request: Request):
        return await self._switch(request, install.set_enabled, False)

    async def stop(self, request: Request):
        body = await self._body(request) or {}
        note = str(body.get("note") or "")[:200] or None
        return await self._switch(request, install.stop, note)

    async def resume(self, request: Request):
        return await self._switch(request, install.resume)

    async def dry(self, request: Request):
        body = await self._body(request) or {}
        if not isinstance(body.get("kind"), str):
            return _error("expected {kind}")
        return await self._switch(request, install.set_mode, body["kind"], False)

    async def live(self, request: Request):
        body = await self._body(request)
        refused = self._house(request, body, "Turning a kind live")
        if refused:
            return refused
        if not isinstance(body.get("kind"), str):
            return _error("expected {kind, confirm: true}")
        cid = self._cid(request)
        out, err = await self._run(install.set_mode, self.rt, cid, body["kind"], True)
        if err:
            return err
        return JSONResponse({"cub": await run_in_threadpool(self._row, request, cid)})

    async def run(self, request: Request):
        refused = self._click(request)
        if refused:
            return refused
        body = await self._body(request) or {}
        cid = self._cid(request)
        cubs = self.rt.cubs
        cub = cubs.installed.get(cid) if cubs is not None else None
        job = next((j for j in (cub.manifest.get("jobs", []) if cub else [])
                    if j["kind"] == body.get("job")), None)
        if job is None:
            return _error(f"{cid} has no job {body.get('job')}", 404)
        scheduler = self.app.scheduler
        if scheduler is None:
            return _error("the scheduler is not running here", 409)
        if scheduler.trigger(job["kind"]):
            return JSONResponse({"started": True})
        return JSONResponse({"started": False, "why": "busy: another job is running, or an "
                                                      "update is draining"})

    async def settings(self, request: Request):
        body = await self._body(request)
        if body is None or not isinstance(body.get("key"), str):
            return _error("expected {key, value}")
        key, value = body["key"], body.get("value")
        parts = key.split(".")
        if len(parts) == 3:
            # cubs.blog.<name> while the site cub stands in for the blog: its own key, the one
            # it runs by (registry.resolve)
            from ..core.cubs import registry
            parts[1] = registry.resolve(self.rt.store, parts[1])
            key = ".".join(parts)
        if len(parts) == 3 and parts[2] == "live":
            return _error("a kind goes live on the cub's page (POST /api/cubs/<id>/live) and "
                          "back to practice with /dry", 400)
        if key == "cubs.enabled":
            refused = self._house(request, body, "cubs.enabled")
        elif len(parts) == 3 and parts[2] == "monthly_usd":
            refused = self._click(request) or (
                None if body.get("confirm") is True
                else _error(f"{key} needs the confirm dialog's answer (confirm: true)"))
        else:
            refused = self._click(request)
        if refused:
            return refused
        trust = None
        if len(parts) == 3:
            from ..core.cubs import registry
            r = registry.latest(self.rt.store, parts[1])
            trust = r["trust"] if r else None
        out, err = await self._run(cub_settings.write, self.rt.cfg, key, value, trust=trust)
        if err:
            return err
        events.core_publish(self.rt.store, "settings.changed", {"feature": "cubs", "key": key},
                            origin=(request.scope.get(IDENTITY) or {}).get("origin"))
        if len(parts) == 3 and parts[2] == "enabled":
            events.core_publish(self.rt.store, "cub.enabled" if value else "cub.disabled",
                                {"cub": parts[1]})
        return JSONResponse({"cubs": cub_settings.describe(self.rt.cfg)})

    def _shop(self, fn):
        """The cub shop's writes (a cub from outside fetched or installed, an update checked or
        applied by hand, a cub removed): 404 without ``cubs.developer``. The
        daily update of the installed cubs is not one of them and runs as before."""
        async def endpoint(request: Request):
            if not cub_settings.developer(self.rt.cfg):
                return _error("the cub shop is off here (cubs.developer)", 404)
            return await fn(request)
        return endpoint

    def routes(self) -> list[Route]:
        return [Route("/api/cubs", self.listing),
                Route("/api/cubs/jobs", self.jobs),
                Route("/api/cubs/jobs/{job}", self.job),
                Route("/api/cubs/jobs/{job}/cancel", self.cancel, methods=["POST"]),
                Route("/api/cubs/fetch", self._shop(self.fetch), methods=["POST"]),
                Route("/api/cubs/settings", self.settings, methods=["POST"]),
                Route("/api/cubs/{id}", self.one),
                Route("/api/cubs/{id}/log", self.log),
                Route("/api/cubs/{id}/install", self._shop(self.install), methods=["POST"]),
                Route("/api/cubs/{id}/update", self._shop(self.update), methods=["POST"]),
                Route("/api/cubs/{id}/apply_update", self._shop(self.apply_update),
                      methods=["POST"]),
                Route("/api/cubs/{id}/remove", self._shop(self.remove), methods=["POST"]),
                Route("/api/cubs/{id}/enable", self.enable, methods=["POST"]),
                Route("/api/cubs/{id}/disable", self.disable, methods=["POST"]),
                Route("/api/cubs/{id}/stop", self.stop, methods=["POST"]),
                Route("/api/cubs/{id}/resume", self.resume, methods=["POST"]),
                Route("/api/cubs/{id}/dry", self.dry, methods=["POST"]),
                Route("/api/cubs/{id}/live", self.live, methods=["POST"]),
                Route("/api/cubs/{id}/run", self.run, methods=["POST"])]
