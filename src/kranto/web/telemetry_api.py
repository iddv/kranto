"""Usage reports over HTTP (sections 3.1, 3.2, 4.2).

| Method and path                    | Does                                                  |
|------------------------------------|-------------------------------------------------------|
| GET  /api/settings/telemetry       | the mode and why, what each mode means, the two       |
|                                    | sentences, what was sent, what is next                |
| POST /api/settings/telemetry       | {mode}: the one setter (Welcome, Settings › Privacy)  |
|                                    | {dismiss: true}: Today's reminder goes for good       |
| GET  /api/settings/telemetry/page  | the notice and the field list (Markdown)              |
| GET  /api/settings/telemetry/report| today's report as it stands (``?day=`` another day),  |
|                                    | ``?sent=DAY``: the exact bytes sent that day          |
| POST /api/telemetry/view           | {views: [{node, ms}]}: page views from the app, kept  |
|                                    | through the allow-list (the node's pattern only)      |
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import telemetry
from ..telemetry import errors, report, send

DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
BATCH = re.compile(r"\d{4}-\d{2}-\d{2}T\d{6}")
MAX_VIEWS = 50


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class TelemetryAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def home(self):
        return self.app.rt.cfg.root

    def _status(self) -> dict:
        st = telemetry.status(self.home)
        return {**st, "modes": [{"mode": m, "meaning": telemetry.MEANING[m]}
                                for m in telemetry.MODES],
                "summary": telemetry.SUMMARY, "sent": send.sent(self.home)[:90],
                "error_batches": errors.sent(self.home)[:90], "docs": telemetry.DOCS_LINK,
                "remind": telemetry.remind(self.home, st)}

    async def get(self, request: Request):
        return JSONResponse(await run_in_threadpool(self._status))

    async def set(self, request: Request):
        """{mode} sets the mode; {dismiss: true} ends Today's one reminder."""
        from .app import _json_body

        body = await _json_body(request) or {}
        if body.get("dismiss") is True:
            await run_in_threadpool(telemetry.dismiss, self.home)
            return JSONResponse(await run_in_threadpool(self._status))
        mode = body.get("mode")
        if mode not in telemetry.MODES:
            return _error(f"mode is one of {', '.join(telemetry.MODES)}")
        try:
            await run_in_threadpool(telemetry.set_mode, self.home, mode)
        except telemetry.TelemetryError as exc:
            return _error(f"could not save: {exc}", 500)
        return JSONResponse(await run_in_threadpool(self._status))

    async def page(self, request: Request):
        """The notice and the field list, as Markdown (``kranto telemetry docs``)."""
        from ..telemetry import docs

        return JSONResponse({"markdown": await run_in_threadpool(docs.page)})

    def _report(self, day: str | None, sent_day: str | None, errs: bool = False) -> dict:
        if sent_day:
            body = send.sent_body(self.home, sent_day) if DAY.fullmatch(sent_day) else \
                errors.sent_body(self.home, sent_day)
            return {"day": sent_day, "sent": body.decode() if body is not None else None}
        day = day or datetime.now(UTC).strftime("%Y-%m-%d")
        mode = telemetry.effective(self.home).mode
        if mode == "off":
            return {"day": day, "report": None}
        tier = mode if mode in telemetry.SENDING else "basic"
        if errs:
            if mode not in telemetry.SENDING:
                return {"day": day, "errors": None}
            pv = errors.preview(self.home, tier)
            return {"day": day, "errors": pv["reports"], "resource": pv["resource"],
                    "bytes": pv["bytes"]}
        payload = report.build(self.home, day, store=self.app.rt.store, cfg=self.app.rt.cfg,
                               tier=tier)
        return {"day": day, **payload, "bytes": len(send.wire(payload))}

    async def report(self, request: Request):
        day, sent_day = request.query_params.get("day"), request.query_params.get("sent")
        if day is not None and not DAY.fullmatch(day):
            return _error("a day is YYYY-MM-DD")
        if sent_day is not None and not (DAY.fullmatch(sent_day) or BATCH.fullmatch(sent_day)):
            return _error("sent is a day (YYYY-MM-DD) or an error batch (YYYY-MM-DDTHHMMSS)")
        errs = request.query_params.get("errors") == "1"
        return JSONResponse(await run_in_threadpool(self._report, day, sent_day, errs))

    async def view(self, request: Request):
        from .app import _json_body

        body = await _json_body(request)
        views = (body or {}).get("views")
        if not isinstance(views, list) or len(views) > MAX_VIEWS:  # stored-shape: isinstance first
            return _error(f"views is a list of at most {MAX_VIEWS} {{node, ms}}")
        for v in views:
            if isinstance(v, dict):
                telemetry.record("view", **{k: v[k] for k in ("node", "ms") if k in v})
        return Response(status_code=204)

    def routes(self) -> list[Route]:
        return [
            Route("/api/settings/telemetry", self.get),
            Route("/api/settings/telemetry", self.set, methods=["POST"]),
            Route("/api/settings/telemetry/report", self.report),
            Route("/api/settings/telemetry/page", self.page),
            Route("/api/telemetry/view", self.view, methods=["POST"]),
        ]
