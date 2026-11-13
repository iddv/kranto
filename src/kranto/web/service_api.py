"""Settings › System › Service: ``service.memory``, the memory Kranto's service runs under.

| Method and path           | Does                                                               |
|---------------------------|--------------------------------------------------------------------|
| GET /api/settings/service | ``memory``: the setting (``auto`` or GB), the caps in force, the   |
|                           | use now, this machine's memory and its default                     |
| POST /api/settings/service| ``{memory: <GB> | "auto"}``: the drop-in written, reloaded and     |
|                           | applied to the running service at once (``memory.set_service_...``)|

Refused (409) when this server is not Kranto's own service (a scratch copy, a server started by
hand): only the service's caps are Kranto's to change. No model call."""
from __future__ import annotations

import math

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import memory


def _error(error: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


class ServiceAPI:
    def __init__(self, app):
        self.app = app

    async def settings(self, request: Request):
        """Kranto's service: the memory it runs under (``service.memory``) and its use now."""
        return JSONResponse({"memory": await run_in_threadpool(memory.service_memory)})

    async def set_settings(self, request: Request):
        from .app import _json_body
        body = await _json_body(request)
        if not isinstance(body, dict) or "memory" not in body:
            return _error('send {memory: <GB> or "auto"}')
        v = body["memory"]
        if v == "auto" or v is None:
            gb = None
        elif isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            return _error('memory is a number of GB, or "auto"')
        else:
            gb = float(v)
        try:
            await run_in_threadpool(memory.set_service_memory, gb)
        except memory.ServiceMemoryError as exc:
            return _error(str(exc), 409 if "not running as" in str(exc) else 400)
        except OSError as exc:
            return _error(f"could not write the setting: {exc}", 500)
        return JSONResponse({"ok": True,
                             "memory": await run_in_threadpool(memory.service_memory)})

    def routes(self) -> list[Route]:
        return [Route("/api/settings/service", self.settings),
                Route("/api/settings/service", self.set_settings, methods=["POST"])]
