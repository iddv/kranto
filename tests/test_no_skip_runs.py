"""A job that had nothing to do is not a run: no ``runs`` row for a
scheduled run's skip (the update check's still is one: its skip with an error is how a failing
check is seen; a press, the CLI, a run the owner stopped part way and a refusal keep theirs); the
scheduler's hourly recheck reads the store's note instead; the run's ended mark keeps its reason,
and a quiet skip still ends a failing streak; a job that is off has no row in ``next_runs``. No
model call, no network."""

from __future__ import annotations

from datetime import timedelta

from kranto import activity
from kranto.scheduler import Job, Scheduler, is_due, next_due
from kranto.store import iso, utcnow


def _run(store, kind, status, error=None, at=None, origin="schedule", summary="{}"):
    at = at or utcnow()
    with activity.run(store, kind, origin=origin) as r:
        return store.insert("runs", {"run_uuid": r.uuid, "kind": kind,
                                     "status": status, "started_at": iso(at),
                                     "finished_at": iso(at), "error": error, "summary": summary})


def test_a_skip_is_no_row_and_the_update_checks_still_is(store):
    before = store.query_one("SELECT COUNT(*) AS n FROM runs")["n"]
    assert _run(store, "ideas", "skipped", "no new map") == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM runs")["n"] == before
    assert store.skipped_at("ideas") is not None and store.skips["ideas"]["error"] == "no new map"
    assert _run(store, "update", "skipped", "GitHub said 502") > 0
    assert store.query_one("SELECT COUNT(*) AS n FROM runs WHERE kind = 'update'")["n"] == 1
    assert _run(store, "ideas", "ok") > 0


def test_what_somebody_asked_for_or_stopped_is_still_a_row(store):
    assert _run(store, "ideas", "skipped", "no theme", origin="press") > 0
    assert _run(store, "ingest", "skipped", "stopped by you after source 2 of 5") > 0
    assert _run(store, "radar", "skipped", summary='{"stopped_by": "owner"}') > 0
    assert _run(store, "verb", "skipped", "off", summary='{"refused": true}') > 0
    # outside any run (a job called directly, as the CLI's do): a row, as before
    assert store.insert("runs", {"run_uuid": "direct", "kind": "ideas", "status": "skipped",
                                 "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                                 "error": "no new map", "summary": "{}"}) > 0


def test_the_recheck_waits_on_the_stores_note(store):
    job = Job("ideas", 24, lambda: None)
    now = utcnow()
    _run(store, "ideas", "ok", at=now - timedelta(days=2))
    assert is_due(store, job, now)
    _run(store, "ideas", "skipped", "no new map", at=now)
    assert not is_due(store, job, now + timedelta(minutes=30))
    assert is_due(store, job, now + timedelta(hours=1, minutes=1))
    assert abs((next_due(store, job, now) - (now + timedelta(hours=1))).total_seconds()) < 1


def test_the_ended_mark_keeps_a_skips_reason(store):
    with activity.run(store, "ideas") as r:
        store.insert("runs", {"run_uuid": r.uuid, "kind": "ideas", "status": "skipped",
                              "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                              "error": "no new map", "summary": "{}"})
    activity.flush(5)
    m = store.query_one("SELECT state, error FROM run_marks WHERE run_uuid = ? AND mark = "
                        "'ended'", (r.uuid,))
    assert (m["state"], m["error"]) == ("skipped", "no new map")
    assert store.query_one("SELECT COUNT(*) AS n FROM runs WHERE run_uuid = ?", (r.uuid,))["n"] == 0


def test_a_quiet_skip_still_ends_a_failing_streak(store):
    from kranto.activity.read import Reader
    for h in (3, 2):                                  # failing twice in a row: a Fix row
        _run(store, "toot.week", "failed", "ValueError: boom", at=utcnow() - timedelta(hours=h))
    assert [f["kind"] for f in Reader(store).failing()] == ["toot.week"]
    with activity.run(store, "toot.week"):
        pass                                  # it ran, found nothing to do, recorded nothing
    activity.flush(5)
    assert [f["kind"] for f in Reader(store).failing()] == []


def test_a_job_that_is_off_has_no_row(store):
    on, off = Job("ingest", 6, lambda: None), Job("invest.mark", 0, lambda: None)
    s = Scheduler(store, [on, off])
    assert set(s.next_runs()) == {"ingest"}
