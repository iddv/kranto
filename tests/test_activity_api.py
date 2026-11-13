"""``GET /api/activity``: every job kind the server schedules produces a
run with its marks and a trace that opens; a press produces a run; a waiting run has its
Needs-you row; a failure surfaces once and goes at the next good run; the served words hold no
setting key and no uuid. Nothing touches a model or the network."""

from __future__ import annotations

import contextlib
import json
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest

from kranto import activity
from kranto.activity import read as activity_read
from kranto.cli import server_jobs
from kranto.core import registry
from kranto.scheduler import Scheduler
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

KEY = re.compile(r"\b[a-z][a-z0-9]*(?:\.[a-z0-9]+)*_[a-z0-9_]+\b")
UUID = re.compile(r"\b[0-9a-f]{32}\b")
ID_FIELDS = {"id", "uuid", "trace", "run_uuid", "kind", "feature", "glyph", "href", "state",
             "mark", "origin", "by", "at", "started", "finished", "since", "last", "first", "ts",
             "now", "verb_href"}


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


def served_words(obj, path=""):
    """Every string the read serves as words (ids, kinds and times aside)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ID_FIELDS:
                continue
            yield from served_words(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from served_words(v, path)
    elif isinstance(obj, str):
        yield path, obj


def test_every_job_kind_the_server_schedules_is_a_run_with_a_trace(rt, quiet):  # noqa: F811
    jobs = server_jobs(rt, update_job=True, port=8765)
    kinds = {j.kind for j in jobs}
    # the walk covers the server's own jobs and every feature's: a new one cannot be left out
    assert {"ingest", "snapshot", "compact", "ideas", "heartbeat", "update", "telemetry",
            "cubs.gc", "xrecheck"} <= kinds
    assert {j.kind for f in registry.first_party() for j in f.jobs} <= kinds
    sched = Scheduler(rt.store, jobs)
    with web_client(create_app(rt, sched), "http://127.0.0.1:8765") as web:
        for job in jobs:
            # a job that raises is a failed run
            with activity.run(rt.store, job.kind, origin="schedule") as r, \
                    contextlib.suppress(Exception):
                job.run()
            activity.settle(rt.store, 5)
            got = [dict(m) for m in rt.store.query(
                "SELECT mark, state FROM run_marks WHERE run_uuid = ? ORDER BY id", (r.uuid,))]
            assert got[0]["mark"] == "started" and got[-1]["mark"] == "ended", job.kind
            row = rt.store.query_one("SELECT status FROM runs WHERE run_uuid = ?", (r.uuid,))
            if row is not None:                   # the job's runs row is the run's
                assert got[-1]["state"] == row["status"], job.kind
                one = web.get(f"/api/runs/{r.uuid}")
                assert one.status_code == 200 and one.json()["run"]["kind"] == job.kind
            trace = web.get("/api/activity", params={"run": r.uuid}).json()
            assert trace["run"]["trace"] == f"#/afk/{r.uuid}/trace" and trace["over"]
            assert [m["mark"] for m in trace["marks"]][0] == "started"
        recorded = {r["kind"] for r in rt.store.query("SELECT DISTINCT kind FROM runs")}
        out = web.get("/api/activity", params={"all": "1", "limit": "500"}).json()
        listed = {r["kind"] for r in out["recent"]}
        assert recorded <= listed


def _run(store, kind, status, error=None, at=None, summary=None):
    at = at or utcnow()
    with activity.run(store, kind) as r:
        store.insert("runs", {"run_uuid": r.uuid, "kind": kind, "status": status,
                              "started_at": iso(at), "finished_at": iso(at),
                              "summary": json.dumps(summary or {}), "error": error})
    return r.uuid


def test_a_failure_surfaces_once_and_goes_at_the_next_good_run(store):
    reader = lambda: activity_read.Reader(store)  # noqa: E731
    _run(store, "toot.weekly", "ok", at=utcnow() - timedelta(hours=3))
    _run(store, "toot.weekly", "failed", "crashed before hello (exit 137, memory)",
         at=utcnow() - timedelta(hours=2))
    out = reader().read()
    assert out["failing"] == []                                   # one failure: Recent only
    assert out["counts"]["failed_recent"] == 1
    [failed] = [r for r in out["recent"] if r["state"] == "failed"]
    assert "exit 137" in failed["error"] and failed["verb"] == "Run again"
    _run(store, "toot.weekly", "failed", "crashed before hello (exit 137, memory)")
    [fix] = reader().failing()
    assert fix["kind"] == "toot.weekly" and fix["tries"] == 2 and fix["verb"] == "Run again"
    assert len(fix["runs"]) == 2 and fix["trace"].startswith("#/afk/")
    # Dismiss puts it away until it fails again
    activity.write_mark(store, run_uuid_="d", kind="toot.weekly", mark="dismissed")
    assert reader().failing() == []
    _run(store, "toot.weekly", "failed", "again")
    assert [f["tries"] for f in reader().failing()] == [3]
    _run(store, "toot.weekly", "ok")
    assert reader().failing() == []                               # gone at the next good run


def test_a_skipped_run_that_ran_ends_a_failing_streak(store):
    """live on dev8: Toot's one failure of 21 Oct stayed a Fix row for a week, though every
    run since ran and ended skipped (no pick to post). A skipped run with no error is a good
    run; a skipped update check with its error is still a failure."""
    reader = lambda: activity_read.Reader(store)  # noqa: E731
    _run(store, "toot.weekly", "failed", "crashed before hello (exit 137, killed)",
         at=utcnow() - timedelta(days=7))
    [fix] = reader().failing()                                     # over two days: Fix
    assert fix["kind"] == "toot.weekly" and fix["tries"] == 1
    _run(store, "toot.weekly", "skipped", at=utcnow() - timedelta(days=6))
    assert reader().failing() == []
    _run(store, "update", "skipped", "GitHub answered 401", at=utcnow() - timedelta(days=3))
    _run(store, "update", "skipped", "GitHub answered 401", at=utcnow() - timedelta(days=2))
    assert [f["kind"] for f in reader().failing()] == ["update"]
    _run(store, "update", "skipped")                               # checked, nothing offered
    assert reader().failing() == []


def test_the_update_check_failing_two_days_reaches_fix_after_one_try(store):
    """The friend on 0.5.5: a failed check is recorded skipped with its error; after two
    days it is one Fix row, said once (D-6 generalized from FAILING_DAYS)."""
    _run(store, "update", "skipped", "GitHub answered 401", at=utcnow() - timedelta(days=3))
    [fix] = activity_read.Reader(store).failing()
    assert fix["title"] == "The update check" and fix["verb"] == "Try again"
    assert "401" in fix["error"]


def test_try_again_on_the_update_check_is_a_run_and_clears_its_fix_row(rt, monkeypatch):  # noqa: F811
    """W3: the check failing for days is one Fix row; the owner's Try again (Settings' Check for
    updates, the same route) is a run of the update check; when it works the row is gone."""
    from kranto.update import check
    store = rt.store
    _run(store, "update", "skipped", "GitHub answered 401", at=utcnow() - timedelta(days=3))
    _run(store, "update", "skipped", "GitHub answered 401", at=utcnow() - timedelta(days=2))
    assert [f["kind"] for f in activity_read.Reader(store).failing()] == ["update"]
    bad = {"ok": False, "error": "GitHub answered 401"}
    good = {"ok": True, "latest": {"version": "9.9.9"}}
    monkeypatch.setattr(check, "run_check", lambda home: bad)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        assert web.post("/api/update/check").status_code == 200
        [f] = activity_read.Reader(store).failing()
        assert f["tries"] == 3                                       # a failed press is a try
        monkeypatch.setattr(check, "run_check", lambda home: good)
        assert web.post("/api/update/check").status_code == 200
    assert activity_read.Reader(store).failing() == []
    row = store.query_one("SELECT * FROM runs WHERE kind = 'update' ORDER BY rowid DESC LIMIT 1")
    assert row["status"] == "ok" and json.loads(row["summary"])["pressed"] is True
    activity.settle(store, 5)
    started = store.query_one("SELECT trigger FROM run_marks WHERE run_uuid = ? "
                              "AND mark = 'started'", (row["run_uuid"],))
    assert started["trigger"] == "press"


def test_on_the_preview_check_for_updates_says_updates_are_off_at_once(rt, monkeypatch):  # noqa: F811
    """ 10 (Gemini 13): on the preview Check for updates hung on "Checking…"."""
    from kranto.update import check
    from kranto.web import update_api

    def never(home):
        raise AssertionError("the preview never checks")
    monkeypatch.setenv("KRANTO_PREVIEW", "1")
    monkeypatch.setattr(check, "run_check", never)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        got = web.post("/api/update/check").json()
    assert got["ok"] is False and got["off"] is True and got["error"] == update_api.PREVIEW_OFF


def _old_skip(store, kind, why):
    """a skipped row as an install before.3 wrote it (new skips write none)"""
    with activity.run(store, kind) as r:
        at = iso(utcnow())
        store._conn.execute(
            "INSERT INTO runs (run_uuid, kind, status, started_at, finished_at, summary) "
            "VALUES (?, ?, 'skipped', ?, ?, ?)", (r.uuid, kind, at, at, json.dumps({"why": why})))
    return r.uuid


def test_skipped_rechecks_and_usage_reports_fold_into_one_line_a_kind(store):
    # rows an older install wrote still fold; a skip now writes no row (PR 1.3)
    for _ in range(5):
        _old_skip(store, "ideas", "the map has not changed")
    _run(store, "ideas", "skipped", summary={"why": "the map has not changed"})
    assert store.query_one("SELECT COUNT(*) AS n FROM runs WHERE kind = 'ideas'")["n"] == 5
    for i in range(3):
        # fix 14: a report counts as sent only when one was posted
        _run(store, "telemetry", "ok", summary={"mode": "basic", "posted": [["2026-11-1", 200]]}
             if i else {"mode": "off", "posted": []})
    _run(store, "ingest", "ok")
    recent, folded = activity_read.Reader(store).recent()
    assert [r["kind"] for r in recent] == ["ingest"]
    lines = {f["kind"]: f["line"] for f in folded}
    assert lines["ideas"] == ("Writing idea cards · skipped 6 times today: "  # 5 rows, 1 mark
                              "the map has not changed")
    assert lines["telemetry"] == "Usage reports · 2 sent today"
    unfolded, _ = activity_read.Reader(store).recent(unfold=True)
    assert len(unfolded) == 10           # six skips, three reports and the read


def test_running_shows_while_it_runs_and_next_says_when(rt):  # noqa: F811
    sched = Scheduler(rt.store, server_jobs(rt))
    with activity.run(rt.store, "ingest") as r:
        r.progress("source 2 of 8, Lobsters · 4 of 10 items · 3 kept so far", step=2, steps=8)
        out = activity_read.Reader(rt.store, sched).read()
        [running] = out["running"]
        assert running["uuid"] == r.uuid and running["stoppable"]
        assert running["words"].startswith("source 2 of 8") and running["progress"]["step"] == 2
        assert out["counts"]["running"] == 1 and out["quiet"] is None
    out = activity_read.Reader(rt.store, sched).read()
    assert out["running"] == [] and out["quiet"].startswith("Nothing is running. Next: ")
    nxt = {n["kind"]: n for n in out["next"]}
    assert nxt["ingest"]["title"] == "Reading your sources" and nxt["ingest"]["at"]
    no_sched = activity_read.Reader(rt.store).read()
    assert no_sched["quiet"].startswith("Nothing is scheduled")


def test_subject_narrows_to_a_topic_and_its_sources_reading(store):
    with activity.run(store, "news.write", subject=("topic", 12, "Robotics")) as a, \
            activity.run(store, "ingest") as b:
        mine = activity_read.Reader(store).read(subject="topic:12")
        assert {r["uuid"] for r in mine["running"]} == {a.uuid, b.uuid}
        other = activity_read.Reader(store).read(subject="topic:13")
        assert {r["uuid"] for r in other["running"]} == {b.uuid}


def test_the_served_words_hold_no_setting_key_and_no_uuid(rt, quiet):  # noqa: F811
    store = rt.store
    _run(store, "ideas", "skipped", summary={"why": "news.run_minutes ran out, not_due"})
    _run(store, "news.brief", "failed", f"run {'a' * 32} failed")
    _run(store, "news.brief", "failed", "news.brief_hour was wrong")
    with activity.run(store, "telemetry_send.weekly_job") as r:
        r.progress("asked news.history_from")
        out = activity_read.Reader(store, Scheduler(store, server_jobs(rt))).read()
    bad = [(p, w) for p, w in served_words(out) if KEY.search(w) or UUID.search(w)]
    assert bad == []


def test_the_api_answers_stop_and_dismiss_at_their_doors(rt):  # noqa: F811
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        assert web.get("/api/activity").json()["counts"]["running"] == 0
        assert web.get("/api/activity", params={"run": "nope!"}).status_code == 404
        assert web.post(f"/api/activity/{'c' * 32}/stop").status_code == 409
        with activity.run(rt.store, "ingest") as r:
            res = web.post(f"/api/activity/{r.uuid}/stop")
            assert res.status_code == 200 and "this source" in res.json()["words"]
            assert r.stop_requested()
        assert web.post("/api/activity/dismiss", json={"kind": "ingest"}).status_code == 404
        s = web.get("/api/settings/activity").json()
        assert s["keep_days"] == 30 and s["max_rows"] == 20000
        assert web.post("/api/settings/activity", json={"keep_days": 0}).status_code == 400


def test_the_settings_are_written_to_the_config(tmp_path, store, embedder, make_client):
    from kranto import config as config_mod
    from kranto.runtime import open_runtime
    config_mod.init_workspace(tmp_path)
    cfg = config_mod.load(tmp_path, dotenv=False)
    runtime = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    with web_client(create_app(runtime), "http://127.0.0.1:8765") as web:
        got = web.post("/api/settings/activity", json={"keep_days": 14, "max_rows": 5000})
        assert got.status_code == 200 and got.json()["keep_days"] == 14
    again = config_mod.load(tmp_path, dotenv=False)
    assert again.activity.keep_days == 14 and again.activity.max_rows == 5000


def test_kranto_status_says_what_runs_waits_and_fails_from_the_same_read():
    from kranto.launcher import activity_line
    answer = {"running": [{"title": "Reading your sources", "words": "source 2 of 8"}],
              "waiting": [{"title": "A cub's update"}],
              "failing": [{"title": "The update check", "tries": 3}], "counts": {}}
    host = SimpleNamespace(http_get=lambda url, t: (200, json.dumps(answer).encode()))
    assert activity_line(host, 8765) == (
        "1 running: Reading your sources · source 2 of 8; 1 waiting on you (A cub's update); "
        "failing: The update check (3 tries)")
    quiet = {"running": [], "waiting": [], "failing": [], "counts": {},
             "quiet": "Nothing is running. Next: reading your sources at 20:23."}
    host.http_get = lambda url, t: (200, json.dumps(quiet).encode())
    assert activity_line(host, 8765) == "Nothing is running. Next: reading your sources at 20:23"
    # live's 0.5.14 said "…at 07:27.; failing: Toot the pick's weekly run (1 tries)"
    quiet["failing"] = [{"title": "Toot the pick's weekly run", "tries": 1}]
    assert activity_line(host, 8765) == ("Nothing is running. Next: reading your sources at 20:23; "
                                         "failing: Toot the pick's weekly run (1 try)")
    host.http_get = lambda url, t: (404, b"")
    assert activity_line(host, 8765) is None


def test_a_feature_job_takes_the_runs_uuid(rt):  # noqa: F811
    job = next(j for j in registry.jobs(lambda: rt) if j.kind == "news.brief")
    with activity.run(rt.store, "news.brief") as r:
        job.run()
    row = rt.store.query_one("SELECT run_uuid FROM runs WHERE kind = 'news.brief'")
    # nothing was due: no row, the skip noted under the run's own uuid
    assert row is None or row["run_uuid"] == r.uuid
    assert row is not None or rt.store.skip_of(r.uuid) is not None
