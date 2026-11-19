"""Every scheduled job, run once as the scheduler runs it, is not due again a minute later.

A job that records no run, or whose run the due check does not read, is due at every tick:
the scheduler starts it once a minute, all day. The daily job that reads back sent posts'
numbers did that until it recorded its run; the short posts' daily job did it whenever it had
nothing to do, because a scheduled run with nothing to do is kept as the store's note, not a
row, and the time-of-day check read only rows. These tests walk every job Kranto schedules
(the server's own, every feature's) and every job of the features Kranto ships, so a new job
cannot be left out. Nothing touches a model or the network."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from kranto import activity
from kranto.cli import server_jobs
from kranto.core import registry
from kranto.scheduler import Scheduler, is_due, next_due
from kranto.store import utcnow

from .cubhelp import install, runtime
from .test_web import rt  # noqa: F401 - fixture

SHIPPED = Path(__file__).parents[1] / "src" / "kranto" / "cubs" / "examples"
MINUTE = timedelta(minutes=1)


@pytest.fixture(autouse=True)
def _writers_stopped():
    from kranto.telemetry import assistant, errors
    yield
    activity.shutdown()
    # server_jobs(update_job=True) starts the error reports' flusher, as the server does
    if isinstance(errors._flusher, errors.Flusher):
        errors._flusher.stop()
    errors._flusher = None
    assistant._server_home = None


@pytest.fixture
def quiet(monkeypatch):
    """The two jobs that would reach out are answered here: the update check, the reports."""
    from kranto.telemetry import send
    from kranto.update import check
    monkeypatch.setattr(check, "run_check", lambda home: {"ok": True, "latest": {
        "version": "9.9.9"}})
    monkeypatch.setattr(send, "run", lambda home, **kw: {"mode": "off", "built": [],
                                                         "posted": [], "queued": 0})


def _moves(sched: Scheduler, job) -> str | None:
    """Run ``job`` once as the scheduler does; what is wrong with its next due time, or None.
    A failed run is retried after the scheduler's back-off, which is not every tick either."""
    sched._run_one(job)
    now = utcnow()
    if job.kind in sched._retry_at:
        return None if sched._retry_at[job.kind] > now + MINUTE else "its back-off is a tick"
    if is_due(sched.store, job, now + MINUTE):
        return "due again a minute after its run"
    at = next_due(sched.store, job, now)
    if at is None or at <= now + MINUTE:
        return f"its next due time does not move ({at})"
    return None


def test_every_job_the_server_schedules_is_not_due_again_after_its_run(rt, quiet):  # noqa: F811
    jobs = server_jobs(rt, update_job=True, port=8765)
    kinds = {j.kind for j in jobs}
    assert {"ingest", "snapshot", "compact", "ideas", "heartbeat", "update", "telemetry",
            "cubs.gc", "cubs.updates", "post.reach"} <= kinds
    assert {j.kind for f in registry.first_party() for j in f.jobs} <= kinds
    sched = Scheduler(rt.store, jobs)
    walked, wrong = [], {}
    for job in jobs:
        if job.every_hours <= 0:                  # off in this home: never due
            assert next_due(rt.store, job, utcnow()) is None, job.kind
            continue
        walked.append(job.kind)
        why = _moves(sched, job)
        if why:
            wrong[job.kind] = why
    assert not wrong
    assert {"ingest", "snapshot", "compact", "ideas", "post.reach", "cubs.gc"} <= set(walked)


def _shipped_jobs() -> list[tuple[str, str]]:
    out = []
    for yml in sorted(SHIPPED.glob("*/cub.yaml")):
        data = yaml.safe_load(yml.read_text())
        out += [(yml.parent.name, j["kind"]) for j in data.get("jobs") or []]
    return out


def test_the_walk_holds_every_job_of_the_features_kranto_ships():
    kinds = {k for _, k in _shipped_jobs()}
    assert {"toot.weekly", "newsletter.weekly"} <= kinds


@pytest.mark.parametrize("status", ["skipped", "ok", "degraded", "failed"])
@pytest.mark.parametrize(("folder", "kind"), _shipped_jobs())
def test_a_shipped_features_job_is_not_due_again_after_its_run(rt, tmp_path, monkeypatch,  # noqa: F811
                                                                folder, kind, status):
    """The feature's process is answered here (no sandbox needed): it says what its job did,
    as a real one does. ``skipped`` is the job with nothing to do: no row, the store's note."""
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    cubs = runtime(rt)
    cubs.load()
    try:
        cid = install(rt, folder, folder=SHIPPED / folder)

        def answer(cid_, method, params, **kw):
            if status == "failed":
                from kranto.core.cubs.process import CubFailed
                raise CubFailed("crashed", "failed: crashed (exit 1)")
            return {"status": status, "summary": {}}, params["run_uuid"], 1
        monkeypatch.setattr(cubs, "request", answer)
        [job] = [j for j in cubs.jobs() if j.cid == cid and j.kind == kind]
        assert job.every_hours > 0, "on by default"
        sched = Scheduler(rt.store, [job])
        assert is_due(rt.store, job, utcnow()) or job.job.get("at")
        assert _moves(sched, job) is None
    finally:
        cubs.stop_all("host")
