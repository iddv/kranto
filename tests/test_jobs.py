"""web/jobs.py: model-backed work a request starts and the page polls, kept across a restart;
proc.py: a recorded process is the one that was started (its pid and start time)."""
import json
import os
import subprocess
import sys
import threading
import time

from kranto import proc
from kranto.web.jobs import Jobs


def wait_done(jobs, key, s=5.0):
    end = time.time() + s
    while time.time() < end and jobs.get(key)["state"] == "running":
        time.sleep(0.02)
    return jobs.get(key)


def test_one_job_per_key_and_its_result(tmp_path):
    jobs = Jobs(tmp_path / "jobs")
    gate = threading.Event()
    calls = []

    def fn():
        calls.append(1)
        gate.wait(5)
        return {"text": "done"}
    first = jobs.start("scout:1", fn)
    again = jobs.start("scout:1", fn)                    # a second press while it runs
    assert first["state"] == again["state"] == "running"
    gate.set()
    assert wait_done(jobs, "scout:1")["result"] == {"text": "done"}
    assert calls == [1]


def test_a_finished_job_is_answered_by_the_next_server(tmp_path):
    Jobs(tmp_path).start("explain:cluster:7", lambda: {"text": "why"})
    time.sleep(0.2)
    later = Jobs(tmp_path)                               # a restart: nothing in memory
    assert later.get("explain:cluster:7")["result"] == {"text": "why"}
    assert later.get("explain:cluster:8") is None


def test_a_job_a_restart_cut_off_reads_failed_not_running(tmp_path):
    jobs = Jobs(tmp_path)
    gate = threading.Event()
    jobs.start("scout:2", lambda: gate.wait(5))
    rec = json.loads((tmp_path / "scout_2.json").read_text())
    assert rec["state"] == "running" and rec["pid"] == os.getpid()
    rec["start"] += 1                                    # another server's, gone
    (tmp_path / "scout_2.json").write_text(json.dumps(rec))
    got = Jobs(tmp_path).get("scout:2")
    assert got["state"] == "failed" and "restarted" in got["error"]
    gate.set()


def test_a_failed_job_says_why(tmp_path):
    jobs = Jobs()                                        # no directory: memory only, as before

    def boom():
        raise RuntimeError("the model refused")
    jobs.start("explain:neighbourhood:3", boom)
    got = wait_done(jobs, "explain:neighbourhood:3")
    assert got["state"] == "failed" and got["error"] == "the model refused"


def test_running_is_the_same_process_not_just_the_same_pid():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        start = proc.start_time(p.pid)
        assert proc.running(p.pid) and proc.running(p.pid, start)
        assert not proc.running(p.pid, start + 1)        # a recycled pid has another start
    finally:
        p.kill()
        p.wait()
    assert not proc.running(p.pid) and not proc.running(None)
    assert proc.me() == {"pid": os.getpid(), "start": proc.start_time(os.getpid())}
