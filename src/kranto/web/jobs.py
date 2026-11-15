"""Model-backed work that a request starts and the page polls.

The owner's rule (2026-10-11): no request the UI serves waits on a model call. A step that needs
one (the scout's proposals, an explanation) either is done before its button is shown, or runs
here: the request starts it and answers at once with the job's state, and the page shows that
state ("Scouting… 20 s") and polls until the result arrives. One job per key at a time: a second
press while one runs gets the running one, never a second paid call.

With a directory, each job is also kept in ``<dir>/<key>.json`` (written when it starts and
when it ends), so a restarted server still answers a poll with the result, and a job a restart
cut off reads as ``failed`` (its record names the server's pid and start time, ``proc.me``)
instead of running forever."""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import proc

KEEP = 200              # finished jobs kept for their pages to read, newest first
# the keys whose jobs are runs: ``<kind>:<subject…>``
# Write a post's job (``post:<as>:<about>``) is a run too: a failed one shows on Activity after a
# reload, with its reason (4, Codex 13)
RUN_KINDS = {"scout": "topic", "explain": None, "fromtext": None, "post": None}


class Jobs:
    def __init__(self, root: Path | None = None, store=None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self.root = Path(root) if root is not None else None
        self.store = store              # with one, each job is an activity run and a runs row

    def _tracked(self, key: str, fn: Callable[[], Any]) -> Callable[[], Any]:
        kind, _, rest = key.partition(":")
        if self.store is None or kind not in RUN_KINDS:
            return fn
        sub = (RUN_KINDS[kind], rest, None) if RUN_KINDS[kind] and rest else None
        store = self.store
        from ..core import verbs
        by = verbs.acting_by() or "ui"   # an assistant's verb started it: say who

        def run():
            from .. import activity
            from ..core.context import record_run
            from ..store import utcnow
            started = utcnow()
            with activity.run(store, kind, origin="press", by=by, subject=sub) as r:
                try:
                    out = fn()
                except Exception as exc:
                    record_run(store, kind, "failed", started, {},
                               f"{type(exc).__name__}: {exc}"[:300], run_uuid=r.uuid)
                    raise
                record_run(store, kind, "ok", started, {}, run_uuid=r.uuid)
                return out
        return run

    def start(self, key: str, fn: Callable[[], Any]) -> dict:
        """Run ``fn`` in a thread of its own under ``key``; returns the job's view. A job
        still running under the same key is returned instead of a new one."""
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job["state"] == "running":
                return self._view(job)
            job = {"key": key, "state": "running", "started": time.time(), "finished": None,
                   "result": None, "error": None, **proc.me()}
            self._jobs[key] = job
            self._trim()
            self._keep(job)
        threading.Thread(target=self._run, args=(job, self._tracked(key, fn)), name=f"job {key}",
                         daemon=True).start()
        return self._view(job)

    def remember(self, key: str, result: Any) -> dict:
        """Keep ``result`` under ``key`` as a finished job (a described batch, by its own id,
        so a page can read it again after the next batch replaced the running one)."""
        now = time.time()
        with self._lock:
            job = {"key": key, "state": "done", "started": now, "finished": now,
                   "result": result, "error": None, **proc.me()}
            self._jobs[key] = job
            self._trim()
            self._keep(job)
        return self._view(job)

    def fail(self, key: str, error: str) -> dict:
        """Keep a job under ``key`` that failed before it started (Write a post with no model
        key, 4): its page lists it with its reason, as any job that failed."""
        now = time.time()
        with self._lock:
            job = {"key": key, "state": "failed", "started": now, "finished": now,
                   "result": None, "error": error, **proc.me()}
            self._jobs[key] = job
            self._trim()
            self._keep(job)
        return self._view(job)

    def dismiss(self, key: str) -> bool:
        """The owner put a finished job's line away (Post's failed write); a new job under the
        same key starts without the mark. False when there is no such finished job."""
        with self._lock:
            job = self._jobs.get(key) or self._kept(key)
            if job is None or job["state"] == "running":
                return False
            job["dismissed"] = True
            self._jobs[key] = job
            self._keep(job)
        return True

    def listing(self, prefix: str) -> list[dict]:
        """Every job whose key starts with ``prefix``, in memory or kept on disk (a restart
        keeps a failed write on Post), each view with ``dismissed``; newest first."""
        with self._lock:
            found = {k: j for k, j in self._jobs.items() if k.startswith(prefix)}
        path = self._path(prefix)
        if path is not None and path.parent.is_dir():
            for p in path.parent.glob(f"{path.name[:-len('.json')]}*.json"):
                try:
                    key = json.loads(p.read_text()).get("key")
                except (OSError, ValueError, AttributeError):
                    continue
                if isinstance(key, str) and key.startswith(prefix) and key not in found:
                    job = self._kept(key)
                    if job is not None:
                        found[key] = job
        out = [{**self._view(j), "dismissed": bool(j.get("dismissed"))} for j in found.values()]
        return sorted(out, key=lambda v: v["finished"] or v["started"] or 0, reverse=True)

    def get(self, key: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(key)
            if job is None:
                job = self._kept(key)
            return self._view(job) if job is not None else None

    def _run(self, job: dict, fn: Callable[[], Any]) -> None:
        try:
            result, state, error = fn(), "done", None
        except Exception as exc:                  # noqa: BLE001 - the page shows why
            result, state = None, "failed"
            error = str(exc) or type(exc).__name__
            traceback.print_exc()
        with self._lock:
            job.update(state=state, result=result, error=error, finished=time.time())
            self._keep(job)

    def _trim(self) -> None:
        done = sorted((j for j in self._jobs.values() if j["state"] != "running"),
                      key=lambda j: j["finished"] or 0)
        for j in done[:max(0, len(self._jobs) - KEEP)]:
            self._jobs.pop(j["key"], None)
        if self.root is not None and self.root.is_dir():
            files = sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime)
            for p in files[:max(0, len(files) - KEEP)]:
                p.unlink(missing_ok=True)

    # -- the records on disk ------------------------------------------------------------------
    def _path(self, key: str) -> Path | None:
        if self.root is None:
            return None
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.root / f"{safe}.json"

    def _keep(self, job: dict) -> None:
        path = self._path(job["key"])
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(job, default=str))
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError):
            traceback.print_exc()                 # the job still runs; only its record is lost

    def _kept(self, key: str) -> dict | None:
        path = self._path(key)
        if path is None:
            return None
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(job, dict) or job.get("key") != key:
            return None
        if job.get("state") == "running" and not proc.running(job.get("pid"), job.get("start")):
            job.update(state="failed", finished=job.get("finished") or job.get("started"),
                       error="Kranto restarted before this finished: try it again")
        return job

    @staticmethod
    def _view(job: dict) -> dict:
        end = job["finished"] or time.time()
        return {"key": job["key"], "state": job["state"], "started": job["started"],
                "finished": job["finished"], "elapsed_s": round(end - job["started"], 1),
                "result": job["result"], "error": job["error"]}
