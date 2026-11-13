"""Health, clusters and grades as JSON, for Kranto UI (the page's ``app.js``).

Kranto UI draws Settings (Health) and the Library inside one page at ``/brb/``.
These endpoints hand it what the server's own pages rendered until (``/health``,
``/clusters``, now redirects to Kranto UI): each one names the page it mirrored.
(Watches, ``/api/watches``, were retired: the saved questions are gone, and their
tables are kept one release unread.)

| Method and path               | Does                                                  |
|-------------------------------|-------------------------------------------------------|
| GET  /api/health              | runs, spend and budget, errors, intake, messages, gate |
| GET  /api/clusters            | the latest map's clusters, as on /clusters            |
| POST /api/grades              | {target, target_id, grade, note}: POST /grade as JSON |

Writes go through the same guard as every route (an allowed Host, a same-origin
``Origin``), and the bodies are JSON objects under ``MAX_JSON_BYTES``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import delivery, gate, grades, library, memory, notify, rowsafe
from ..llm import watch_pause
from ..map import read as map_read
from ..progress import library_progress
from ..store import iso, month_start, utcnow
from ..stored.cards import SynthesisInputIds
from ..stored.map import SnapshotQuality
from ..stored.runs import summary_of
from ..tick import current_progress


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _brief(row) -> dict:
    """An observation as a list row: enough to draw it and link to it."""
    return {"id": row["id"], "title": row["title"], "summary": row["summary"],
            "signal": row["signal"], "kind": row["kind"], "source_label": row["source_label"],
            "created_at": row["created_at"]}


def _synthesis(row) -> dict | None:
    return ({"text": row["text"], "input_ids": SynthesisInputIds.load(row["input_ids"]).items}
            if row else None)


class KrantoAPI:
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

    # -- health (as /health) ---------------------------------------------------------------

    def health(self, request: Request):
        app, store, cfg = self.app, self.rt.store, self.rt.cfg
        now = utcnow()
        since = iso(now - timedelta(days=7))
        runs: list[dict] = []
        recent = library.recent_runs(store, 30)
        tokens = store.run_tokens([r["run_uuid"] for r in recent])
        for r in recent:
            with rowsafe.row(runs, "run", r["run_uuid"], kind=r["kind"], status=r["status"],
                             started_at=r["started_at"]):
                d = dict(r)
                d["summary"] = summary_of(d.get("kind"), d.get("summary")).to_dict(nulls=True)
                # The run's model calls, in tokens (None: no call, or none left with counts).
                d["tokens"] = tokens.get(d["run_uuid"])
                runs.append(d)
        spent = store.month_spend(now)
        budget = cfg.budget
        messages = notify.recent_messages(store, 20)
        message_ids = [m["id"] for m in messages]
        deliveries = {str(k): {**v, "sent": sorted(v["sent"])}
                      for k, v in delivery.delivery_summary(store, message_ids).items()}
        retention = app._retention_status()
        retention["removed"] = [dict(r) for r in retention["removed"]]
        return JSONResponse({
            "memory": memory.use().as_dict(),
            "month": iso(month_start(now))[:7],
            "spent_usd": round(spent, 6),
            "tokens_month": store.tokens_since(month_start(now)),
            "budget": {"monthly_usd": budget.monthly_usd, "alarm_fraction": budget.alarm_fraction},
            "alarm": budget.alarm(spent),
            "paused": store.pause_reason(),
            "watch_paused": watch_pause(store, now),
            "busy": app.scheduler.busy if app.scheduler else False,
            "can_run": app.scheduler is not None,
            "running": app.scheduler.running if app.scheduler else None,
            "ingest_progress": current_progress(),
            "next_run": app.scheduler.next_runs() if app.scheduler else {},
            "lanes": app.scheduler.lane_status() if app.scheduler else {},
            "api_key": bool(cfg.llm.api_key()),
            "models": dict(cfg.llm.models),
            "outcomes": library.outcome_counts(store, since),
            "exploration": library.exploration_yield(store),
            "errors": [dict(r) for r in library.llm_error_summary(store, since)],
            "runs": runs,
            "messages": messages,
            "deliveries": deliveries,
            "delivery_status": delivery.describe(cfg),
            "decisions": gate.recent_decisions(store, limit=20),
            "strike": asdict(cfg.strike),
            "grade_labels": grades.LABELS,
            "retention": retention,
        })

    # -- clusters (as /clusters) ------------------------------------------------------------

    def clusters(self, request: Request):
        from ..ideate.explain import cached as cached_synthesis
        from .app import _moving_key

        store = self.rt.store
        snap = map_read.latest(store)
        if snap is None:
            return JSONResponse({"snapshot": None, "clusters": [],
                                 "progress": library_progress(store).map_message})
        clusters = map_read.clusters(store, snap["id"])
        sort = request.query_params.get("sort", "size")
        if sort == "moving":
            clusters.sort(key=_moving_key)
        elif sort == "cross":
            clusters.sort(key=lambda c: (not c["cross_source"], c["max_source_share"]))
        rep_ids = [i for c in clusters for i in c["representatives"][:3]]
        reps = library.observations_by_id(store, rep_ids)
        cluster_grades = grades.latest(store, "cluster", [c["lineage_id"] for c in clusters])
        out: list[dict] = []
        for c in clusters:
            # one theme that cannot be read is listed as such (RCA A3)
            with rowsafe.row(out, "theme", c.get("cluster"), label=c.get("label"),
                             lineage_id=c.get("lineage_id")):
                c["synthesis"] = _synthesis(cached_synthesis(store,
                                                             f"cluster:{c['lineage_id']}"))
                c["grade"] = cluster_grades.get(str(c["lineage_id"]))
                c["examples"] = [_brief(reps[i]) for i in c["representatives"][:3] if i in reps]
                out.append(c)
        return JSONResponse({
            "snapshot": {"id": snap["id"], "created_at": snap["created_at"], "n": snap["n"],
                         "k": snap["k"]},
            "quality": SnapshotQuality.load(snap["quality"]).extra, "sort": sort,
            "clusters": out,
            "grade_labels": grades.LABELS, "grade_choices": [],   # a theme has no grade
        })

    def routes(self) -> list[Route]:
        return [
            Route("/api/health", self.health),
            Route("/api/clusters", self.clusters),
        ]
