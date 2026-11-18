"""Grades, the review queue and the learning summary as JSON (LEARNING.md 2.4, track L1).

Kranto UI grades through these; the page never writes this database (it posts here).

| Method and path                 | Does                                                        |
|---------------------------------|-------------------------------------------------------------|
| POST /api/feedback              | one row: {target, target_id, value, kind, reasons, pair,    |
|                                 | note, origin, context}; kind defaults to grade, origin ui   |
| GET  /api/feedback              | ``target`` and ``target_id``: that target's history;        |
|                                 | ``target`` and ``ids`` (comma-separated): the latest grade  |
|                                 | of each, cleared grades left out                            |
| GET  /api/feedback/vocabulary   | targets, values, origins and the "why" chips per target     |
| GET  /api/review/queue          | this week's ungraded cards; ``size`` overrides the default  |
| GET  /api/grades/summary        | what the owner's grades did (``taste.summary``, Your        |
|                                 | grades): counts, the cards they moved, the next ideas       |
|                                 | run's themes, the sources (``source_rule.summary``)         |

A grade read back through ``grades.latest`` (every page that shows a grade, and /api/ideas,
which the loop's intake reads) reflects these rows. Writes go through the same guard as every
route (an allowed Host, a same-origin ``Origin``); bodies are JSON objects under
``MAX_JSON_BYTES``. No model call.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import feedback, grades
from .ideas_api import read_ideas

IDS_MAX = 500


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class FeedbackAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def _body(self, request: Request):
        from .app import MAX_JSON_BYTES, _json_body

        body = await _json_body(request)
        if body is None:
            return None, _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        return body, None

    async def add(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        try:
            row_id = await run_in_threadpool(feedback.add, self.rt.store, body)
        except ValueError as exc:
            return _error(str(exc))
        row = feedback.history_row(self.rt.store, row_id)
        return JSONResponse({**row, "label": feedback.LABELS.get(row["value"], row["value"])})

    def read(self, request: Request):
        q = request.query_params
        target = q.get("target") or ""
        if target in feedback.RETIRED_TARGETS:
            # a build's, a project's or a theme's rows (gone with builds): skipped, never an
            # error for a page that still asks
            if q.get("target_id"):
                return JSONResponse({"target": target, "target_id": q["target_id"],
                                     "history": []})
            return JSONResponse({"target": target, "grades": {}})
        if target not in feedback.TARGETS:
            return _error(f"target must be one of {', '.join(feedback.TARGETS)}")
        store = self.rt.store
        if q.get("target_id"):
            return JSONResponse({"target": target, "target_id": q["target_id"],
                                 "history": feedback.history(store, target, q["target_id"])})
        ids = [i.strip() for i in (q.get("ids") or "").split(",") if i.strip()][:IDS_MAX]
        # the union with the older grades table, so a grade given on a server page shows too
        latest = grades.latest(store, target, ids)
        return JSONResponse({"target": target, "grades": {
            k: {"value": v["grade"], "reasons": v.get("reasons") or [],
                "created_at": v["created_at"]} for k, v in latest.items()}})

    def vocabulary(self, request: Request):
        return JSONResponse(feedback.vocabulary())

    def queue(self, request: Request):
        from .app import _int

        q = request.query_params

        def n(key: str, default: int, lo: int, hi: int) -> int:
            return max(lo, min(hi, _int(q.get(key), default)))

        store = self.rt.store
        return JSONResponse(feedback.build_queue(
            store, [c for c in read_ideas(store, "shown") if not c.get("unreadable")],
            size=n("size", feedback.QUEUE_SIZE, 1, 50)))

    def summary(self, request: Request):
        from .. import source_rule, taste

        cfg = getattr(self.rt.cfg, "grading", None)
        return JSONResponse({**taste.summary(self.rt.store, cfg=cfg),
                             "sources": source_rule.summary(self.rt.store, cfg)})

    def routes(self) -> list[Route]:
        return [
            Route("/api/feedback", self.add, methods=["POST"]),
            Route("/api/feedback", self.read),
            Route("/api/feedback/vocabulary", self.vocabulary),
            Route("/api/review/queue", self.queue),
            Route("/api/grades/summary", self.summary),
        ]
