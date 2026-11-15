"""The marker: a run's marks as it goes, through one buffered writer that never
slows the work; the mirror file; the stop's flush; a crash's runs; the retention caps. Nothing
touches a model or the network."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from datetime import timedelta

import pytest

from kranto import activity, proc, stopping
from kranto.activity import words
from kranto.store import Store, iso, utcnow


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


@pytest.fixture
def fstore(tmp_path):
    s = Store.open(tmp_path / "data" / "kranto.db")
    yield s
    activity.shutdown()
    s.close()


def marks(store, uuid=None):
    activity.settle(store, 5)
    sql = "SELECT * FROM run_marks" + (" WHERE run_uuid = ?" if uuid else "") + " ORDER BY id"
    return [dict(r) for r in store.query(sql, (uuid,) if uuid else ())]


def test_a_run_marks_started_and_ended_and_its_state_is_its_runs_row(store):
    with activity.run(store, "ingest", origin="press", by="ui") as r:
        # started is committed while the job runs (the writer is told to commit it at once),
        # and this process knows the run is running without it
        assert activity.find(r.uuid) is r and r in activity.open_runs()
        [m] = marks(store, r.uuid)
        assert m["mark"] == "started" and m["trigger"] == "press" and m["by"] == "ui"
        assert m["pid"] == os.getpid() and m["pstart"]
        assert activity.run_uuid("ingest") == r.uuid          # the report takes the run's id
        assert activity.run_uuid("ingest") != r.uuid          # a second report: its own
        store.insert("runs", {"run_uuid": r.uuid, "kind": "ingest", "status": "degraded",
                              "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                              "summary": "{}", "error": None})
    ended = marks(store, r.uuid)[-1]
    assert ended["mark"] == "ended" and ended["state"] == "degraded"
    assert activity.current() is None and activity.find(r.uuid) is None


def test_a_run_that_raises_ends_failed_with_the_reason_and_the_error_goes_on(store):
    with pytest.raises(RuntimeError), activity.run(store, "toot.weekly") as r:
        raise RuntimeError("crashed before hello (exit 137, memory)")
    ended = marks(store, r.uuid)[-1]
    assert ended["state"] == "failed" and "exit 137" in ended["error"]


def test_a_job_that_recorded_nothing_ended_skipped_and_a_nested_run_of_its_kind_is_the_same(
        store):
    with activity.run(store, "toot.weekly") as outer, \
            activity.run(store, "toot.weekly", origin="press") as inner:
        assert inner is outer                                 # the cub runtime inside a job
    assert [m["mark"] for m in marks(store, outer.uuid)] == ["started", "ended"]
    assert marks(store, outer.uuid)[-1]["state"] == "skipped"


def test_progress_marks_are_queued_coalesced_and_cost_the_work_a_queue_put(store):
    with activity.run(store, "ingest") as r:
        t = time.perf_counter()
        for i in range(500):
            activity.progress(f"source {i} of 500", step=i, steps=500)
        took = time.perf_counter() - t
        assert activity.writer_for(store).flush(5)
    assert took < 0.5                    # 500 marks in well under a millisecond each
    prog = [m for m in marks(store, r.uuid) if m["mark"] == "progress"]
    assert 1 <= len(prog) < 50 and prog[-1]["words"] == "source 499 of 500"
    assert prog[-1]["step"] == 499 and prog[-1]["steps"] == 500


def test_a_long_queue_drops_progress_first_never_a_waiting_or_a_stop(store, monkeypatch):
    gate = threading.Event()
    w = activity.writer_for(store)
    real = activity.Writer._commit

    def held(self, rows, conn):
        gate.wait(5)
        return real(self, rows, conn)

    monkeypatch.setattr(activity.Writer, "_commit", held)
    monkeypatch.setattr(activity, "QUEUE_MAX", 20)
    with activity.run(store, "radar.run") as r:
        for i in range(200):
            r.progress(f"request {i}")
        r.waiting("The radar proposed 3 trends from Robotics", {"verb": "Review"})
        r.request_stop()
        assert w.dropped > 0
        gate.set()
        assert w.flush(5)
    got = marks(store, r.uuid)
    kinds = [m["mark"] for m in got]
    assert "waiting" in kinds and "stopping" in kinds and kinds[0] == "started"
    assert len([k for k in kinds if k == "progress"]) < 200
    [ended] = [m for m in got if m["mark"] == "ended"]
    assert ended["state"] == "stopped"


def test_the_mirror_lists_what_runs_and_is_the_owners_only(fstore):
    path = activity.mirror_path(fstore)
    with activity.run(fstore, "radar.run", title="The trend radar") as r:
        r.progress("Collecting Robotics' history · arXiv")
        assert activity.writer_for(fstore).flush(5)
        body = json.loads(path.read_text())
        [running] = body["running"]
        assert running["uuid"] == r.uuid and running["words"].startswith("Collecting")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        seq = body["seq"]
    assert activity.writer_for(fstore).flush(5)
    after = json.loads(path.read_text())
    assert after["running"] == [] and after["seq"] > seq


def test_the_writer_commits_on_its_own_connection_and_ends_when_idle(fstore, monkeypatch):
    monkeypatch.setattr(activity, "IDLE_EXIT_S", 0.2)
    with activity.run(fstore, "ingest") as r:
        r.progress("source 1 of 2")
        w = activity.writer_for(fstore)
        assert w.flush(5)
    time.sleep(1.6)
    assert w._closed and not w._thread.is_alive()
    with activity.run(fstore, "ingest") as r2:                # a later run starts another
        r2.progress("source 1 of 2")
        assert activity.writer_for(fstore) is not w
        assert activity.writer_for(fstore).flush(5)
    assert [m["mark"] for m in marks(fstore, r2.uuid)] == ["started", "progress", "ended"]


def test_the_servers_stop_flushes_the_marks_inside_its_budget(fstore, monkeypatch):
    gate = threading.Event()
    real = activity.Writer._commit

    def slow(self, rows, conn):
        gate.wait(0.2)
        return real(self, rows, conn)

    monkeypatch.setattr(activity.Writer, "_commit", slow)
    with activity.run(fstore, "ingest") as r:
        r.progress("source 3 of 8")
        stop = stopping.Stop(hard_exit_s=None, own_children=False)
        t = time.monotonic()
        stopping.stop_server(stop)
        assert time.monotonic() - t < stopping.STOP_BUDGET_S
        assert [m["mark"] for m in marks(fstore, r.uuid)][-1] == "progress"


def test_a_run_a_dead_process_left_is_cut_off_at_the_next_start(store):
    store.insert("run_marks", {"run_uuid": "a" * 32, "kind": "ingest", "ts": iso(utcnow()),
                               "mark": "started", "pid": 999999, "pstart": 1})
    store.insert("run_marks", {"run_uuid": "b" * 32, "kind": "ingest", "ts": iso(utcnow()),
                               "mark": "started", "pid": os.getpid(),
                               "pstart": proc.me()["start"]})
    assert activity.recover(store) == 1
    [ended] = [m for m in marks(store, "a" * 32) if m["mark"] == "ended"]
    assert ended["state"] == "stopped" and "cut off" in ended["words"]
    assert not [m for m in marks(store, "b" * 32) if m["mark"] == "ended"]   # it still runs
    assert activity.recover(store) == 0


def test_the_retention_caps_hold_with_a_purge_record(store):
    old, new = iso(utcnow() - timedelta(days=40)), iso(utcnow())
    for i in range(30):
        store.insert("run_marks", {"run_uuid": f"old{i}", "kind": "ingest", "ts": old,
                                   "mark": "ended", "state": "ok"})
    for i in range(1200):
        store.insert("run_marks", {"run_uuid": f"new{i}", "kind": "ingest", "ts": new,
                                   "mark": "ended", "state": "ok"})
    with activity.run(store, "ingest") as live:              # a run in progress keeps its marks
        n = activity.prune(store, keep_days=30, max_rows=1000, run_uuid_="compact-run")
        assert n == 30 + 201
        left = store.query_one("SELECT COUNT(*) AS n FROM run_marks")["n"]
        assert left == 1000 and marks(store, live.uuid)
    purges = store.query("SELECT * FROM purges WHERE table_name = 'run_marks' ORDER BY id")
    assert [p["row_count"] for p in purges] == [30, 201]
    assert "older than 30 days" in purges[0]["reason"] and "oldest first" in purges[1]["reason"]
    with pytest.raises(Exception, match="append-only"):
        store.query("DELETE FROM run_marks")


def test_compaction_prunes_the_marks_with_its_own_run(store):
    from kranto.config import ActivityConfig, RetentionConfig
    from kranto.retention import compact
    store.insert("run_marks", {"run_uuid": "x", "kind": "ingest", "mark": "ended",
                               "ts": iso(utcnow() - timedelta(days=9))})
    report = compact(store, RetentionConfig(), None,
                     activity_cfg=ActivityConfig(keep_days=7, max_rows=20000))
    assert report.removed.get("run_marks") == 1
    p = store.query_one("SELECT * FROM purges WHERE table_name = 'run_marks'")
    assert p["run_uuid"] == report.run_uuid


def test_a_name_that_ends_in_s_takes_an_apostrophe_alone():
    assert words.possessive("Robotics") == "Robotics'"
    assert words.possessive("Newsletter") == "Newsletter's"
    assert words.humanize("news.brief", "News") == "News' brief run"
    assert words.humanize("toot.weekly", "Toot the pick") == "Toot the pick's weekly run"
