"""What Kranto is doing: the server's half of the activity read, the Stop
of a run and the Dismiss of a failure. The page's ``GET api/activity`` merges this with the
loop's runs, the builds and the sessions; the page reads that, never this file.

| Method and path                  | Does                                                          |
|----------------------------------|---------------------------------------------------------------|
| GET /api/activity                | running, waiting, next, recent, folded, failing, counts,      |
|                                  | health (the status bar's word and why,), the             |
|                                  | quiet words; ``subject=topic:12``, ``kind=``, ``limit=``,     |
|                                  | ``all=1`` (unfolded), ``hours=`` (recent's window);           |
|                                  | ``run=<uuid>``: one run with its marks (the live trace)       |
| POST /api/activity/{uuid}/stop   | the owner's Stop: the run ends at its next step               |
| POST /api/activity/dismiss       | ``{kind}``: put a failing kind's Fix row away until it fails  |
|                                  | again                                                         |
| GET, POST /api/settings/activity | ``activity.keep_days``, ``activity.max_rows``                 |

The read carries words, times, counts and ids, never a prompt, an answer or a payload; every
word was scrubbed when it was written. No model call."""
from __future__ import annotations

import math
from dataclasses import replace

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import activity, health
from .. import config as config_mod
from ..activity import read as activity_read
from .runs_api import UUID


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class ActivityAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def reader(self) -> activity_read.Reader:
        from ..core import registry
        titles, cub_kinds, off_kinds = {}, set(), set()
        try:
            for f in registry.features():
                titles[f.id] = f.title
                if registry.is_cub(f):
                    cub_kinds |= {j.kind for j in f.jobs}
                if not registry.enabled(self.rt.cfg, f):
                    off_kinds |= {j.kind for j in f.jobs}
        except Exception:  # noqa: BLE001 - the words fall back to the kinds' own
            pass
        return activity_read.Reader(self.rt.store, self.app.scheduler, titles=titles,
                                    cub_kinds=cub_kinds, cfg=self.rt.cfg, off_kinds=off_kinds)

    def _read(self, q) -> dict:
        r = self.reader()
        if q.get("run"):
            out = r.one(q["run"])
            return out if out is not None else {"error": "no such run"}
        try:
            limit = max(1, min(int(q.get("limit") or activity_read.LIMIT),
                               activity_read.LIMIT_MAX))
            hours = max(1.0, min(float(q.get("hours") or activity_read.RECENT_HOURS),
                                 24.0 * float(self.rt.cfg.activity.keep_days)))
        except ValueError:
            raise ValueError("limit and hours are numbers") from None
        out = r.read(subject=q.get("subject") or None, kind=q.get("kind") or None,
                     limit=limit, unfold=q.get("all") == "1", hours=hours)
        # the status bar's word and why, as /api/today serves it: the console's
        # kranto_incidents answers "why is Kranto degraded?" from here
        out["health"] = health.served(self.app)
        return out

    async def index(self, request: Request):
        q = request.query_params
        if q.get("run") and not UUID.match(q["run"]):
            return _error("no such run", 404)
        try:
            out = await run_in_threadpool(self._read, q)
        except ValueError as exc:
            return _error(str(exc))
        if out.get("error"):
            return _error(out["error"], 404)
        return JSONResponse(out)

    async def stop(self, request: Request):
        uuid = request.path_params["uuid"]
        if not UUID.match(uuid):
            return _error("no such run", 404)
        r = activity.find(uuid)
        if r is None:
            return _error("this run is not running here (it may have ended)", 409)
        r.request_stop("owner")
        return JSONResponse({"ok": True, "stopping": True, "words": STOP_WORDS.get(
            r.kind, "It stops at its next step; what it did so far stays.")})

    async def dismiss(self, request: Request):
        from .app import _json_body
        body = await _json_body(request)
        iid = str((body or {}).get("incident") or "")
        if iid:
            # an incident is put away by the owner until it happens again (#488: one that
            # nothing had cleared could not be put away at all)
            found = {i["id"] for i in await run_in_threadpool(self.reader().incidents)}
            if iid not in found:
                return _error("no such incident now (it may have cleared)", 404)
            activity.write_mark(self.rt.store, run_uuid_=f"dismiss-{iid}", kind=iid,
                                mark="dismissed", words="put away by you until it happens again")
            return JSONResponse({"ok": True, "incident": iid})
        kind = str((body or {}).get("kind") or "")
        if not kind or len(kind) > 80:
            return _error("which failing run: send its kind")
        failing = {f["kind"] for f in await run_in_threadpool(self.reader().failing)}
        if kind not in failing:
            return _error("nothing of that kind is failing", 404)
        activity.write_mark(self.rt.store, run_uuid_=f"dismiss-{kind}", kind=kind,
                            mark="dismissed", words="put away by you until it fails again")
        return JSONResponse({"ok": True, "kind": kind})

    # -- the two settings -------------------------------------------------------------------------

    def _settings(self) -> dict:
        a = self.rt.cfg.activity
        return {"keep_days": a.keep_days, "max_rows": a.max_rows,
                "rows": self.rt.store.query_one("SELECT COUNT(*) AS n FROM run_marks")["n"],
                "keep_days_range": list(config_mod.ACTIVITY_KEEP_DAYS),
                "max_rows_range": list(config_mod.ACTIVITY_MAX_ROWS), "effect": "compaction"}

    async def settings(self, request: Request):
        return JSONResponse(await run_in_threadpool(self._settings))

    def _set(self, values: dict) -> dict:
        from .. import setup
        path = config_mod.config_path(self.rt.cfg.root)
        if path is None:
            raise setup.SetupError("no config file to write")
        setup.write_config_values(path, {("activity", k): v for k, v in values.items()})
        cfg = self.rt.cfg
        self.rt.cfg = replace(cfg, activity=replace(cfg.activity, **values))
        return self._settings()

    async def set_settings(self, request: Request):
        from .. import setup
        from .app import _json_body
        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object")
        values = {}
        if "keep_days" in body:
            d, (lo, hi) = body["keep_days"], config_mod.ACTIVITY_KEEP_DAYS
            if isinstance(d, bool) or not isinstance(d, int | float) or not math.isfinite(d) \
                    or not lo <= d <= hi:
                return _error(f"keep_days is a number of days from {lo} to {hi}")
            values["keep_days"] = int(d) if float(d).is_integer() else round(float(d), 2)
        if "max_rows" in body:
            n, (lo, hi) = body["max_rows"], config_mod.ACTIVITY_MAX_ROWS
            if isinstance(n, bool) or not isinstance(n, int) or not lo <= n <= hi:
                return _error(f"max_rows is a whole number from {lo:,} to {hi:,}")
            values["max_rows"] = n
        if not values:
            return _error("nothing to set: send keep_days or max_rows")
        try:
            return JSONResponse(await run_in_threadpool(self._set, values))
        except (OSError, setup.SetupError, config_mod.ConfigError) as exc:
            return _error(f"could not save: {exc}", 500)

    def routes(self) -> list[Route]:
        return [Route("/api/activity", self.index),
                Route("/api/activity/dismiss", self.dismiss, methods=["POST"]),
                Route("/api/activity/{uuid}/stop", self.stop, methods=["POST"]),
                Route("/api/settings/activity", self.settings),
                Route("/api/settings/activity", self.set_settings, methods=["POST"])]


# what stopping means, by kind (the trace's Stop says it before the flag is set)
STOP_WORDS = {
    "ingest": "Stopping after this source: what was kept stays; the rest at the next read.",
    "news.brief": "Stopping after this brief: the others are written at the next hour.",
}
