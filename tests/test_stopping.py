"""The server's stop (stopping.py, STOP): one budget from SIGTERM to exit, the scheduler told
at once, the cub host and the scheduler inside the budget, the server's own children ended
(SIGTERM, then SIGKILL) and its detached jobs left running, a watchdog when something hangs, and
the work cut off left to resume after the start. ``test_serve_stop.py`` does the same through a
real SIGTERM to a real server process."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kranto import scheduler as sched_mod
from kranto import stopping

from .test_web import BASE, rt  # noqa: F401 - fixture


def gone(pid: int, s: float = 5.0) -> bool:
    """``pid`` has ended (no process, or a zombie its parent has not reaped yet)."""
    end = time.monotonic() + s
    while time.monotonic() < end:
        st = stopping._stat(pid)
        if st is None or st[3] == "Z":
            return True
        time.sleep(0.05)
    return False


# A stand-in server: its children are the kinds a real one has, and it prints their pids. The
# tests end *its* children (``root``), never pytest's own.
FAMILY = """
import json, subprocess, sys, time
deaf = [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM,"
        " signal.SIG_IGN); print('ready', flush=True); time.sleep(300)"]
kids = {
    "attached": subprocess.Popen(["sleep", "300"]),                       # a claude -p, a git
    "tree": subprocess.Popen(["bash", "-c", "sleep 300 & echo $! >&2; wait"],
                             stderr=subprocess.PIPE, text=True),          # one with its own
    "deaf": subprocess.Popen(deaf, stdout=subprocess.PIPE, text=True),    # ignores SIGTERM
    "leader": subprocess.Popen(["sleep", "300"], start_new_session=True), # a terminal
    "job": subprocess.Popen(["sleep", "300"], start_new_session=True),    # a detached build
}
out = {k: p.pid for k, p in kids.items()}
out["grandchild"] = int(kids["tree"].stderr.readline())
assert kids["deaf"].stdout.readline().strip() == "ready"
print(json.dumps(out), flush=True)
time.sleep(300)
"""


@pytest.fixture
def family():
    p = subprocess.Popen([sys.executable, "-c", FAMILY], stdout=subprocess.PIPE, text=True)
    pids = json.loads(p.stdout.readline())
    yield p.pid, pids
    stopping.end_children(0.0, root=p.pid)        # what a test left running, then the family
    p.kill()
    p.wait()


# -- the children -----------------------------------------------------------------------------

def test_the_servers_children_end_and_its_detached_jobs_are_left(family):
    root, kid = family
    t0 = time.monotonic()
    ended = {p["pid"] for p in stopping.end_children(grace_s=1.0, keep=[kid["job"]],
                                                    root=root)}
    took = time.monotonic() - t0
    assert 1.0 <= took < 3                        # the deaf one held it to the grace, no more
    assert {kid[k] for k in ("attached", "tree", "grandchild", "deaf", "leader")} <= ended
    assert kid["job"] not in ended
    for k in ("attached", "tree", "grandchild", "deaf", "leader"):
        assert gone(kid[k]), k                    # the deaf one SIGKILLed after its grace
    assert not gone(kid["job"], 0.2)              # left running: the next start adopts it


def test_with_the_jobs_unknown_every_session_leader_is_kept(family):
    # a page version that cannot say which children are its detached jobs: keep every child that
    # leads a session of its own (each detached job does), end the rest
    root, kid = family
    ended = {p["pid"] for p in stopping.end_children(grace_s=1.0, keep=None, root=root)}
    assert kid["attached"] in ended and kid["grandchild"] in ended
    assert kid["leader"] not in ended and kid["job"] not in ended
    assert gone(kid["attached"]) and not gone(kid["leader"], 0.2)


def test_pages_detached_jobs_are_what_is_kept():
    pytest.importorskip("kranto.page.host_api")
    from kranto.page import host_api
    if "detached_jobs" not in getattr(host_api, "_NAMES", {}):
        pytest.skip("a version of the page from before STOP")
    from kranto.page import proc as bproc
    job = bproc.spawn_detached(["sleep", "300"])
    try:
        assert job.pid in stopping.detached_jobs()
        assert job.pid in stopping.Stop().keep()
    finally:
        bproc.stop(job.pid, grace_s=2)


# -- the scheduler ----------------------------------------------------------------------------

def test_a_job_cut_off_by_the_stop_is_still_due_at_the_next_start(store):
    started, release = threading.Event(), threading.Event()

    def ingest():
        started.set()
        release.wait(30)                          # a model call that does not answer

    job = sched_mod.Job("ingest", 1, ingest)
    s = sched_mod.Scheduler(store, [job])
    s.start()
    assert started.wait(5)
    s.request_stop()
    assert not s.trigger("ingest")                # nothing starts once the stop has begun
    t0 = time.monotonic()
    assert s.stop(timeout=0.5) is False
    assert time.monotonic() - t0 < 1.5
    assert s.still_running() == ["the ingest job"]
    # no run was recorded, so the next server runs it again
    assert sched_mod.is_due(store, job, sched_mod.utcnow())
    release.set()


# -- the whole stop -----------------------------------------------------------------------------

class Cubs:
    def __init__(self, hang: bool = False):
        self.asked, self.hang = [], hang

    def stop_all(self, why, budget_s):
        self.asked.append((why, budget_s))
        if self.hang:
            threading.Event().wait()             # a stop that never returns: the watchdog's case
        return ["slowpoke"]


def test_the_stop_keeps_to_its_budget_and_says_what_it_cut_off(store, caplog):
    release = threading.Event()
    s = sched_mod.Scheduler(store, [sched_mod.Job("ingest", 1, lambda: release.wait(30))])
    s.start()
    end = time.monotonic() + 5
    while not s.busy:
        assert time.monotonic() < end
        time.sleep(0.01)
    stop = stopping.Stop(budget_s=2.0, hard_exit_s=None, own_children=False)
    stop.on_begin.append(s.request_stop)
    cubs = Cubs()
    caplog.set_level(logging.INFO, "kranto.stop")
    assert stop.begin("SIGTERM")
    assert not stop.begin("SIGTERM")              # once
    t0 = time.monotonic()
    still = stopping.stop_server(stop, cubs, s)
    assert time.monotonic() - t0 < 2.5
    [(why, budget)] = cubs.asked
    assert why == "host" and budget <= 2.0 - stopping.CHILDREN_S + 0.01
    assert still == ["cub slowpoke", "the ingest job"]
    assert "stop: done in" in caplog.text and "cut off (resumes after the start): cub " \
        "slowpoke; the ingest job" in caplog.text
    release.set()


def test_a_cub_left_is_named_and_a_clean_stop_says_so():
    stop = stopping.Stop(hard_exit_s=None, own_children=False)
    assert stopping.stop_server(stop, Cubs(), None) == ["cub slowpoke"]
    stop2 = stopping.Stop(hard_exit_s=None, own_children=False)
    assert stopping.stop_server(stop2, None, None) == [] and stop2.done.is_set()


def test_the_terminals_end_with_their_reason_before_the_children_are_signalled(monkeypatch):
    """STOP's follow-up: the page writes "ended: restart" on each terminal session, then the
    children (the terminals' programs among them) are ended."""
    order = []
    monkeypatch.setattr(stopping, "end_terminals", lambda: order.append("terminals") or ["t1"])
    stop = stopping.Stop(hard_exit_s=None, own_children=False)
    monkeypatch.setattr(stop, "end_children", lambda grace_s: order.append("children") or [])
    assert stopping.stop_server(stop, None, None) == []
    assert order == ["terminals", "children"]
    monkeypatch.setattr(stopping, "end_terminals", lambda: 1 / 0)    # a page version that raises
    stop2 = stopping.Stop(hard_exit_s=None, own_children=False)
    monkeypatch.setattr(stop2, "end_children", lambda grace_s: order.append("children") or [])
    stopping.stop_server(stop2, None, None)
    assert order[-1] == "children" and stop2.done.is_set()


def test_pages_terminals_are_asked_to_end_with_restart(monkeypatch):
    pytest.importorskip("kranto.page.host_api")
    from kranto.page import host_api
    if "term_shutdown" not in getattr(host_api, "_NAMES", {}):
        pytest.skip("a version of the page from before its terminals said why they ended")
    from kranto.page.ui import api
    asked = []
    monkeypatch.setattr(api, "stop_terms", lambda reason: asked.append(reason) or ["t1"])
    monkeypatch.setattr(host_api, "term_shutdown", api.stop_terms, raising=False)
    assert stopping.end_terminals() == ["t1"] and asked == ["restart"]


def test_the_cub_host_gets_its_share_and_never_more_than_the_budget():
    cubs = Cubs()
    stopping.stop_server(stopping.Stop(hard_exit_s=None, own_children=False), cubs, None)
    assert cubs.asked == [("host", stopping.CUBS_S)]
    late = stopping.Stop(budget_s=3.0, hard_exit_s=None, own_children=False)
    cubs = Cubs()
    stopping.stop_server(late, cubs, None)        # 3 s, less the children's 2: 1 s for cubs
    assert cubs.asked[0][1] == pytest.approx(1.0, abs=0.1)


def test_the_watchdog_exits_when_the_stop_hangs_and_ends_the_children_first(family):
    root, kid = family
    exits = []
    stop = stopping.Stop(budget_s=0.3, hard_exit_s=0.6, exit=exits.append)
    stop.root, stop.keep = root, lambda: [kid["job"]]
    stop.begin("SIGTERM")
    threading.Thread(target=stopping.stop_server, args=(stop, Cubs(hang=True), None),
                     daemon=True).start()
    end = time.monotonic() + 5
    while not exits:
        assert time.monotonic() < end, "the watchdog did not exit"
        time.sleep(0.02)
    assert exits == [0] and stop.elapsed() < 2
    assert gone(kid["deaf"]) and gone(kid["attached"])     # SIGKILLed before the exit
    assert not gone(kid["job"], 0.2)


def test_the_watchdog_stays_quiet_after_a_stop_that_finished():
    exits = []
    stop = stopping.Stop(budget_s=0.2, hard_exit_s=0.3, exit=exits.append, own_children=False)
    stop.begin()
    stopping.stop_server(stop, None, None)
    time.sleep(0.6)
    assert exits == []


def test_the_apps_lifespan_runs_the_stop_without_touching_this_processs_children(
        rt, caplog):  # noqa: F811
    # an app in a test (no SIGTERM, inside pytest's process): the stop runs, but the children of
    # the process are not the server's to end
    from starlette.testclient import TestClient

    from kranto.web.app import create_app
    other = subprocess.Popen(["sleep", "300"])
    try:
        caplog.set_level(logging.INFO, "kranto.stop")
        with TestClient(create_app(rt), base_url=BASE) as c:
            assert c.get("/api/status").status_code == 200
        assert "stop: done in" in caplog.text
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


def test_the_unit_waits_longer_than_the_watchdog():
    from kranto import launcher
    from kranto.update import apply
    assert stopping.STOP_BUDGET_S < stopping.HARD_EXIT_S < stopping.UNIT_STOP_S
    assert stopping.HTTP_GRACE_S + stopping.CUBS_S + stopping.CHILDREN_S < stopping.STOP_BUDGET_S
    assert apply.SLOW_STOP_S == stopping.HARD_EXIT_S
    unit = launcher.render_unit(Path("/h/.kranto"), Path("/h/.local/bin/kranto"), 8765, Path("/h"))
    assert f"TimeoutStopSec={stopping.UNIT_STOP_S}" in unit.splitlines()
