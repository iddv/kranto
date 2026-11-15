"""the server's runs as the material of an agent trace (the page): the
analyst's, News's, the radar's and the cubs' runs, read by the page's trace reader through
this API, never through the database file.

| Method and path      | Does                                                                    |
|----------------------|-------------------------------------------------------------------------|
| GET /api/runs        | the runs, newest first (``kind``, ``since``, ``limit``): each with its  |
|                      | status, times, calls and their cost                                     |
| GET /api/runs/{uuid} | one run whole: its model calls (request and response, where retention  |
|                      | kept them), its cubs' host calls (the op, never a payload), its events  |
|                      | (kind and subject, never a payload)                                     |

A run's calls carry prompts and answers, so both reads are the owner's only (the guard's
``OWNER_READS``, as a trace's are). the page redacts on read; nothing here is sent anywhere.
No model call; nothing is written."""
from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LIMIT = 50
LIMIT_MAX = 500
UUID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CALL_COLS = ("id", "purpose", "tier", "model", "prompt_version", "request", "response",
             "status", "error", "http_status", "attempts", "prompt_tokens", "completion_tokens",
             "cost_usd", "latency_ms", "created_at")


def runs(store, kind: str | None = None, since: str | None = None, limit: int = LIMIT) -> list:
    where, args = [], []
    if kind:
        where.append("r.kind = ?")
        args.append(kind)
    if since:
        where.append("r.started_at >= ?")
        args.append(since)
    sql = ("SELECT r.run_uuid, r.kind, r.status, r.started_at, r.finished_at, r.summary, "
           "r.error, (SELECT COUNT(*) FROM llm_calls l WHERE l.run_uuid = r.run_uuid) AS calls, "
           "(SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls l WHERE l.run_uuid = r.run_uuid) "
           "AS cost_usd FROM runs r" + (f" WHERE {' AND '.join(where)}" if where else "")
           + " ORDER BY r.started_at DESC LIMIT ?")
    out = []
    for r in store.query(sql, (*args, int(limit))):
        row = dict(r)
        row["summary"] = str(row.get("summary") or "")[:400]
        out.append(row)
    return out


def run(store, uuid: str) -> dict | None:
    r = store.query_one("SELECT * FROM runs WHERE run_uuid = ?", (uuid,))
    calls = [dict(c) for c in store.query(
        f"SELECT {', '.join(CALL_COLS)} FROM llm_calls WHERE run_uuid = ? ORDER BY id", (uuid,))]
    if r is None and not calls:
        return None
    cubs = [dict(c) for c in store.query(
        "SELECT cub, service, op, status, ms, bytes_in, bytes_out, created_at FROM cub_calls "
        "WHERE run_uuid = ? ORDER BY id", (uuid,))]
    events = [dict(e) for e in store.query(
        "SELECT id, ts, kind, feature, subject_kind, subject_id FROM events WHERE run_uuid = ? "
        "ORDER BY id LIMIT 500", (uuid,))]
    for c in calls:                     # retention removed the payload: say so, never guess
        if c.get("request") in (None, "") and c.get("response") in (None, ""):
            c["expired"] = True
    return {"run": dict(r) if r is not None else {"run_uuid": uuid, "kind": None},
            "calls": calls, "cub_calls": cubs, "events": events}


class RunsAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def index(self, request: Request):
        q = request.query_params
        try:
            limit = max(1, min(int(q.get("limit") or LIMIT), LIMIT_MAX))
        except ValueError:
            return JSONResponse({"error": "limit must be a number"}, status_code=400)
        return JSONResponse({"runs": runs(self.rt.store, q.get("kind") or None,
                                          q.get("since") or None, limit)})

    def one(self, request: Request):
        uuid = request.path_params["uuid"]
        if not UUID.match(uuid):
            return JSONResponse({"error": "no such run"}, status_code=404)
        out = run(self.rt.store, uuid)
        if out is None:
            return JSONResponse({"error": "no such run"}, status_code=404)
        return JSONResponse(out)

    def routes(self) -> list[Route]:
        return [Route("/api/runs", self.index), Route("/api/runs/{uuid}", self.one)]
