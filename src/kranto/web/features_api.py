"""The feature core over HTTP (to MR-RESEARCH).

| Method and path                         | Does                                                  |
|-----------------------------------------|-------------------------------------------------------|
| GET  /api/features                      | every feature: manifest, trust, mode, pin, last run,  |
|                                         | open tickets, spend, settings rows                    |
| GET  /api/events                        | the bus: ``since`` (an id), ``kind`` (comma-separated),|
|                                         | ``min_trust``, ``limit``                              |
| GET  /api/read/{name}                   | a v1 read (``topics.list``, ``library.observations``…) |
| GET  /api/f/{feature}/{name}            | one of a feature's own reads (its page's JSON)         |
| GET  /api/tickets                       | tickets: ``cub`` (or ``feature``), ``open=1``         |
| GET  /api/tickets/{id}                  | one ticket with its read-back, provenance and history  |
| POST /api/tickets/{id}/confirm          | the owner's press: ``{confirm: true, when?}``, the    |
|                                         | page only (``when``: Schedule's time, if it schedules)|
| GET  /api/tickets/{id}/ask              | the plain dialog, with its audit facts for Details    |
| POST /api/tickets/{id}/again            | a draft offered again: a fresh ticket, the page only  |
| GET  /api/asks                          | what the cubs ask, as rows; ``cub`` adds its history  |
| POST /api/tickets/{id}/decline          | ``{note}``: the page or the command line              |
| (/api/requests…)                        | the same four under their old name, through 0.5.x     |
| POST /api/f/{feature}/settings          | ``{key, value, confirm}``: one of its settings         |
| POST /api/f/{feature}/act/{action}      | ``{fields, confirm}``: one of its actions             |
| POST /api/cubs/check                    | ``{text}``: a cub's cub.yaml checked by the one        |
|                                         | validator, in words for the install dialog; never     |
|                                         | installed (the runtime is 0.5)                        |
| GET  /api/shell                         | the layout and the home's arrangement (``core.shell``):|
|                                         | pins, hidden, caps, each cub's Needs-you and New      |
| POST /api/shell                         | ``{key, value}``, ``{values: {key: value}}`` (several |
|                                         | keys in one write) or ``{reset: true}``: the one writer|
| GET  /api/home                          | the home in one read (``core.home``): the widgets     |
|                                         | resolved, the library, every slot within 2 s;         |
|                                         | ``?slot=<n>`` one slot again                          |

Reads are open on loopback like every read; writes go through the guard (the token is the
caller). A ticket's confirm and a sensitive setting need the page's session cookie (the ``ui``
door), not the command line's token, ``kranto mcp`` or an agent's: ``core.tickets.door_of``.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..core import api as read_api
from ..core import asks as asks_mod
from ..core import home as home_mod
from ..core import registry, settings, tickets
from ..core import shell as shell_mod
from ..core.context import CapReached, PermissionDenied
from ..llm import BudgetExceeded, LLMError, Paused
from .auth import IDENTITY


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class _CoreReader:
    """The v1 reads as the core itself asks them (no feature's grants apply)."""

    feature = None

    def __init__(self, rt) -> None:
        self.store, self.index, self.embedder, self.rt = rt.store, rt.index, rt.embedder, rt


class FeaturesAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def _body(self, request: Request) -> dict | None:
        from .app import _json_body
        return await _json_body(request)

    def _feature(self, fid: str):
        try:
            return registry.by_id(fid)
        except KeyError:
            return None

    async def features(self, request: Request):
        return JSONResponse(await run_in_threadpool(registry.describe, self.rt))

    async def events(self, request: Request):
        q = dict(request.query_params)
        try:
            out = await run_in_threadpool(read_api.events_read, _CoreReader(self.rt), q)
        except read_api.ReadError as exc:
            return _error(str(exc), exc.code)
        return JSONResponse(out)

    async def read(self, request: Request):
        name = request.path_params["name"]
        try:
            out = await run_in_threadpool(read_api.call, _CoreReader(self.rt), name,
                                          dict(request.query_params))
        except read_api.ReadError as exc:
            return _error(str(exc), exc.code)
        except ValueError as exc:          # a read asked without what it needs: a 400, as a
            return _error(str(exc))        # feature's own read answers (feature_read)
        return JSONResponse(out)

    async def feature_read(self, request: Request):
        f = self._feature(request.path_params["feature"])
        name = request.path_params["name"]
        if f is None or name not in f.api:
            return _error("not found", 404)
        ctx = registry.context(self.rt, f)
        try:
            out = await run_in_threadpool(f.api[name], ctx, dict(request.query_params))
        except read_api.ReadError as exc:
            return _error(str(exc), exc.code)
        except ValueError as exc:
            return _error(str(exc))
        return JSONResponse(out)

    async def tickets(self, request: Request):
        """``/api/tickets`` answers ``{tickets}``; its old name ``/api/requests`` answers
        ``{requests}`` with the same rows (each ticket carries ``feature`` beside ``cub``)."""
        q = request.query_params
        rows = await run_in_threadpool(lambda: tickets.listing(
            self.rt.store, cub=q.get("cub") or q.get("feature") or None,
            open_only=q.get("open") in ("1", "true"), unreadable=True))
        key = "requests" if request.url.path.startswith("/api/requests") else "tickets"
        return JSONResponse({key: rows})

    async def ticket(self, request: Request):
        try:
            rid = int(request.path_params["id"])
        except ValueError:
            return _error("not found", 404)
        t = await run_in_threadpool(tickets.get, self.rt.store, rid)
        if t is None:
            return _error("not found", 404)
        return JSONResponse(t)

    async def asks(self, request: Request):
        """``GET /api/asks``: what the cubs ask you, as Needs you's rows (``core.asks``);
        ``?cub=<id>`` adds that cub's history in words."""
        cub = request.query_params.get("cub") or None

        def read():
            out: dict = {"asks": [{**asks_mod.row(self.rt, t), "cub": t["cub"]}
                                  for t in asks_mod.latest(self.rt.store, cub)]}
            if cub:
                out["history"] = asks_mod.history(self.rt.store, cub)
            return out
        return JSONResponse(await run_in_threadpool(read))

    async def ask(self, request: Request):
        """``GET /api/tickets/{id}/ask``: the plain dialog of one ticket, with its audit facts
        (the read-back, who asked and on what, its history) for Details."""
        try:
            rid = int(request.path_params["id"])
        except ValueError:
            return _error("not found", 404)

        def read():
            t = tickets.get(self.rt.store, rid)
            if t is None:
                return None
            return {**{k: t[k] for k in ("id", "cub", "kind", "state", "said", "readback",
                                         "because", "history", "created_at", "expires_at",
                                         "run_uuid")},
                    "ask": asks_mod.ask(self.rt, t)}
        out = await run_in_threadpool(read)
        return JSONResponse(out) if out is not None else _error("not found", 404)

    async def again(self, request: Request):
        """``POST /api/tickets/{id}/again``: the owner's click on a row that offers a draft
        again; the page only."""
        try:
            rid = int(request.path_params["id"])
            t = await run_in_threadpool(asks_mod.again, self.rt, rid,
                                        identity=request.scope.get(IDENTITY))
        except tickets.TicketError as exc:
            return _error(str(exc), exc.code)
        except ValueError:
            return _error("not found", 404)
        return JSONResponse({**t, "ask": await run_in_threadpool(asks_mod.ask, self.rt, t)})

    async def confirm(self, request: Request):
        body = await self._body(request)
        if body is None:
            return _error("expected a JSON object")
        try:
            rid = int(request.path_params["id"])
            out = await run_in_threadpool(tickets.confirm, self.rt.store, rid,
                                          identity=request.scope.get(IDENTITY),
                                          confirm=body.get("confirm"), context=self.rt,
                                          when=body.get("when"))
        except tickets.TicketError as exc:
            return _error(str(exc), exc.code)
        except ValueError:
            return _error("not found", 404)
        return JSONResponse(out)

    async def decline(self, request: Request):
        body = await self._body(request) or {}
        try:
            out = await run_in_threadpool(tickets.decline, self.rt.store,
                                          int(request.path_params["id"]),
                                          identity=request.scope.get(IDENTITY),
                                          note=str(body.get("note") or "")[:300] or None)
        except tickets.TicketError as exc:
            return _error(str(exc), exc.code)
        except ValueError:
            return _error("not found", 404)
        return JSONResponse(out)

    async def set_setting(self, request: Request):
        f = self._feature(request.path_params["feature"])
        if f is None:
            return _error("not found", 404)
        body = await self._body(request)
        if body is None or "key" not in body:
            return _error("expected {key, value}")
        key = str(body["key"])
        if key in f.settings.sensitive:
            if tickets.door_of(request.scope.get(IDENTITY)) != "ui":
                return _error(f"{key} is changed on the page only", 403)
            if body.get("confirm") is not True:
                return _error(f"{key} needs the confirm dialog's answer (confirm: true)")
        try:
            if f.guard is not None:
                ctx = registry.context(self.rt, f)
                ctx.door = tickets.door_of(request.scope.get(IDENTITY))
                f.guard(ctx, key, body.get("value"))
            values = await run_in_threadpool(settings.write, self.rt.cfg, f.id, key,
                                             body.get("value"))
        except PermissionDenied as exc:
            return _error(str(exc), 403)
        except ValueError as exc:
            return _error(str(exc))
        self._reload(f.id, values)
        from ..core import events
        events.core_publish(self.rt.store, "settings.changed", {"feature": f.id, "key": key},
                            origin=(request.scope.get(IDENTITY) or {}).get("origin"))
        return JSONResponse({"feature": f.id, "settings": settings.describe(f, values)})

    def _reload(self, fid: str, values: dict) -> None:
        from dataclasses import replace
        cfg = self.rt.cfg
        self.rt.cfg = replace(cfg, features={**(cfg.features or {}), fid: values})

    async def shell(self, request: Request):
        return JSONResponse(await run_in_threadpool(shell_mod.arrangement, self.rt.cfg,
                                                    registry.features()))

    async def set_shell(self, request: Request):
        """The one writer for the home's arrangement: ``{key, value}`` or ``{reset: true}``."""
        body = await self._body(request)
        if body is None or ("key" not in body and body.get("reset") is not True
                            and not isinstance(body.get("values"), dict)):
            return _error("expected {key, value}, {values: {key: value}} or {reset: true}")
        try:
            if body.get("reset") is True:
                values = await run_in_threadpool(shell_mod.reset, self.rt.cfg)
                key = "shell.reset"
            elif "key" not in body:
                values = await run_in_threadpool(shell_mod.write_many, self.rt.cfg,
                                                 body["values"])
                key = ",".join(sorted(map(str, body["values"])))[:200]
            else:
                key = str(body["key"])
                values = await run_in_threadpool(shell_mod.write, self.rt.cfg, key,
                                                 body.get("value"))
        except ValueError as exc:
            return _error(str(exc))
        from dataclasses import replace

        from ..core import events
        self.rt.cfg = replace(self.rt.cfg, shell=values)
        events.core_publish(self.rt.store, "settings.changed", {"feature": "shell", "key": key},
                            origin=(request.scope.get(IDENTITY) or {}).get("origin"))
        return JSONResponse(await run_in_threadpool(shell_mod.arrangement, self.rt.cfg,
                                                    registry.features()))

    async def home(self, request: Request):
        """The home in one read: the arrangement resolved, the library and
        every kranto-side slot within the 2 s budget; ``?slot=<n>`` asks one slot again."""
        only = request.query_params.get("slot")
        if only is not None and not only.isdigit():
            return _error("slot is a widget's place on the home (a number)")
        sched = getattr(self.app, "scheduler", None)
        out = await run_in_threadpool(home_mod.read, self.rt,
                                      only=int(only) if only is not None else None,
                                      next_run=sched.next_runs() if sched else None)
        return JSONResponse(out)

    async def check_cub(self, request: Request):
        """The Cubs page's install dialog: a pasted cub.yaml, checked and never installed. The
        cub shop's: 404 without ``cubs.developer``."""
        from ..core.cubs.settings import developer
        if not developer(self.rt.cfg):
            return _error("the cub shop is off here (cubs.developer)", 404)
        body = await self._body(request)
        if body is None:
            return _error("expected {text}")
        out = await run_in_threadpool(registry.check_text, body.get("text"))
        return JSONResponse(out, status_code=200 if out["ok"] else 400)

    async def act(self, request: Request):
        f = self._feature(request.path_params["feature"])
        kind = f"{request.path_params['feature']}.{request.path_params['action']}"
        action = next((a for a in f.actions if a.kind == kind), None) if f else None
        if action is None:
            return _error("not found", 404)
        identity = request.scope.get(IDENTITY)
        door = tickets.door_of(identity)
        door = "ui" if door == "ui-token" and "ui" in action.doors else door
        # through the verbs' door (``POST /api/verbs/f.<kind>``): the registry checked the
        # caller's door and the ladder; a cub hears the console as kranto mcp
        if (identity or {}).get("verb") == f"f.{kind}" and door not in action.doors:
            door = "mcp" if door == "console" else door
        elif door not in action.doors:
            return _error(f"{action.title} is not run from {door or 'here'} "
                          f"(doors: {', '.join(action.doors)})", 403)
        body = await self._body(request) or {}
        if action.click in ("confirm", "house") and body.get("confirm") is not True:
            return _error(f"{action.title} needs the confirm dialog's answer (confirm: true)")
        if action.click == "house" and tickets.door_of(identity) != "ui":
            return _error(f"{action.title} is done on the page only", 403)
        if not registry.enabled(self.rt.cfg, f):
            return _error(f"{f.title} is off", 409)
        ctx = registry.context(self.rt, f)
        ctx.door = door
        try:
            out = await run_in_threadpool(action.run, ctx, body.get("fields") or {})
        except (PermissionDenied, tickets.TicketError) as exc:
            return _error(str(exc), 403 if isinstance(exc, PermissionDenied) else exc.code)
        except CapReached as exc:
            return _error(str(exc), 409)
        except ValueError as exc:
            return _error(str(exc))
        except LLMError as exc:
            # the model did not answer (or was paused, or over its cap): said, not a 500 with an
            # error id (PAR: the radar's Fill the terms crashed when the model was down)
            # its words up to the provider's answer, which may be a response body
            why = " ".join(str(exc).split("{", 1)[0].split()).rstrip(" :")[:160]
            return _error(f"{action.title} did not happen: the model did not answer"
                          + (f" ({why})" if why else ""),
                          409 if isinstance(exc, (Paused, BudgetExceeded)) else 503)
        return JSONResponse(out or {"ok": True})

    def routes(self) -> list[Route]:
        return [Route("/api/features", self.features),
                Route("/api/events", self.events),
                Route("/api/read/{name}", self.read),
                Route("/api/f/{feature}/{name}", self.feature_read),
                Route("/api/asks", self.asks),
                Route("/api/tickets", self.tickets),
                Route("/api/tickets/{id}", self.ticket),
                Route("/api/tickets/{id}/ask", self.ask),
                Route("/api/tickets/{id}/again", self.again, methods=["POST"]),
                Route("/api/tickets/{id}/confirm", self.confirm, methods=["POST"]),
                Route("/api/tickets/{id}/decline", self.decline, methods=["POST"]),
                Route("/api/requests", self.tickets),
                Route("/api/requests/{id}", self.ticket),
                Route("/api/requests/{id}/confirm", self.confirm, methods=["POST"]),
                Route("/api/requests/{id}/decline", self.decline, methods=["POST"]),
                Route("/api/f/{feature}/settings", self.set_setting, methods=["POST"]),
                Route("/api/cubs/check", self.check_cub, methods=["POST"]),
                Route("/api/shell", self.shell),
                Route("/api/shell", self.set_shell, methods=["POST"]),
                Route("/api/home", self.home),
                Route("/api/f/{feature}/act/{action}", self.act, methods=["POST"])]
