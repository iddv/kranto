"""A process that must outlive the request asking for it survives that request's thread.

PR_SET_PDEATHSIG (bubblewrap's ``--die-with-parent``) fires when the *thread* that forked the
child exits. On live, an Open in Claude Code session forked by a server's worker thread was
SIGKILLed when that thread retired (code -9, 27 s in). ``proc``'s spawner forks such children
from one thread that never exits. These children set PDEATHSIG themselves, as bwrap does, so
the test needs no bubblewrap (the real-bwrap case is in ``test_term_sandbox.py``)."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from kranto.page import proc
from kranto.page.term.pty import Pty

# set PDEATHSIG = SIGKILL, say so, then idle (what bwrap --die-with-parent does first)
CHILD = ("import ctypes, sys, time; ctypes.CDLL(None, use_errno=True).prctl(1, 9); "
         "open(sys.argv[1], 'w').write('ready'); time.sleep(300)")


def from_a_short_lived_thread(start, ready: Path):
    """``start()`` on a thread that lives until the child is ready (its PDEATHSIG set while
    the thread still runs, as with a request thread), then exits."""
    got = {}

    def request():
        got["p"] = start()
        end = time.time() + 20
        while not ready.exists() and time.time() < end:
            time.sleep(0.05)
    t = threading.Thread(target=request, name="request")
    t.start()
    t.join()
    assert ready.exists(), "the child never got going"
    return got["p"]


@pytest.mark.slow
def test_children_forked_for_a_request_outlive_its_thread(tmp_path):
    cmd = [sys.executable, "-c", CHILD]
    # the bug, as it was: forked on the request's thread, the child dies with it
    bare = from_a_short_lived_thread(
        lambda: subprocess.Popen([*cmd, str(tmp_path / "bare")], start_new_session=True),
        tmp_path / "bare")
    try:
        assert bare.wait(10) == -9
    finally:
        if bare.poll() is None:
            bare.kill()
    # the fix: a detached job and a terminal session, both forked by the spawner
    job = from_a_short_lived_thread(
        lambda: proc.spawn_detached([*cmd, str(tmp_path / "job")]), tmp_path / "job")
    pty = from_a_short_lived_thread(
        lambda: Pty([*cmd, str(tmp_path / "pty")], env=None, cwd=tmp_path).start(),
        tmp_path / "pty")
    try:
        time.sleep(31)
        assert job.poll() is None, f"the detached job died: {job.returncode}"
        assert pty.alive, f"the terminal's program died: {pty.code}"
    finally:
        job.kill()
        job.wait(5)
        pty.kill(grace_s=1)


def test_the_spawner_runs_on_one_thread_and_hands_back_results_and_errors():
    names = {proc.on_spawner(lambda: threading.current_thread().name) for _ in range(3)}
    assert names == {"kranto-spawner"}
    assert proc.on_spawner(lambda a, b=0: a + b, 2, b=3) == 5
    with pytest.raises(FileNotFoundError):
        proc.on_spawner(subprocess.Popen, ["/nonexistent/kranto-test-binary"])
    # a call made on the spawner itself runs at once (no wait on its own queue)
    assert proc.on_spawner(lambda: proc.on_spawner(lambda: "inner")) == "inner"
