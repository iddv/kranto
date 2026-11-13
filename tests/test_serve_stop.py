"""``kranto serve`` stops on SIGTERM while a page holds a request open (finding 2).

uvicorn waits for every open response before it stops, and the page's live feed
(``/brb/api/stream``) and Open in Claude Code's terminal socket never end by themselves: from
0.3.65 every live stop waited for systemd's SIGKILL at 90 s. Here the real ``cmd_serve`` runs
in a process of its own, on loopback, with an app whose one route is a feed like the page's (a
generator that blocks in the thread pool and never ends); a client holds it open; SIGTERM must
end the process within seconds."""
from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time

import pytest

DRIVER = textwrap.dedent("""
    import argparse, sys, threading
    from starlette.applications import Starlette
    from starlette.concurrency import iterate_in_threadpool
    from starlette.responses import StreamingResponse
    from starlette.routing import Route
    from kranto import cli
    import kranto.web.app as web_app

    def feed():
        yield b"retry: 3000\\n\\n"
        while True:                       # like the page's live feed: a wait in a worker thread
            threading.Event().wait(15)
            yield b": ping\\n\\n"

    async def stream(request):
        return StreamingResponse(iterate_in_threadpool(feed()), media_type="text/event-stream")

    class Rt:
        def close(self):
            pass

    web_app.create_app = lambda *a, **k: Starlette(routes=[Route("/stream", stream)])
    cli._runtime = lambda args: Rt()
    sys.exit(cli.cmd_serve(argparse.Namespace(host="127.0.0.1", port=int(sys.argv[1]),
                                              allow_host=None, no_scheduler=True)))
""")


# STOP: the server as ``cmd_serve`` runs it (``cli._serve``: uvicorn, its signal handler beginning
# the stop; the lifespan's end running ``stopping.stop_server``) with a real scheduler, put in
# the states live is often in. ``argv``: port, states (comma separated), a folder for the pids.
STATES = textwrap.dedent("""
    import contextlib, logging, os, subprocess, sys, threading
    from pathlib import Path
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from kranto import cli, stopping
    from kranto.scheduler import Job, Scheduler
    from kranto.store import Store

    port, states, out = int(sys.argv[1]), set(sys.argv[2].split(",")), Path(sys.argv[3])
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        stream=sys.stdout)
    never = threading.Event()

    def note(name, pid):
        (out / name).write_text(str(pid))

    def ingest():                   # a job in a model call that does not answer
        if "child" in states:       # ... made by a child process (the claude -p provider)
            p = subprocess.Popen(["sleep", "300"])
            note("child", p.pid)
            p.wait()
        else:
            note("job", os.getpid())
            never.wait()

    class Lane:                     # the loop lane, its tick in a step that ignores the stop
        name = "loop"
        def run(self, stop):
            note("lane", os.getpid())
            never.wait()
        def request_stop(self):
            pass
        def status(self):
            return {}

    class Cubs:                     # a cub host whose stop never returns: the watchdog's case
        def stop_all(self, why, budget_s):
            never.wait()

    jobs = [Job("ingest", 1, ingest)] if states & {"job", "child"} else []
    lanes = [Lane()] if "lane" in states else []
    scheduler = Scheduler(Store.open(out / "db.sqlite"), jobs, lanes=lanes)
    stop = stopping.Stop()
    stop.on_begin.append(scheduler.request_stop)

    @contextlib.asynccontextmanager
    async def lifespan(_):
        scheduler.start()
        if "terminal" in states:    # Open in Claude Code: a program on a pty, its own session
            from kranto.page import proc
            master, slave = os.openpty()
            note("terminal", proc.spawn_terminal(["sleep", "300"], terminal=slave).pid)
        if "detached" in states:    # a build: detached, adopted by the next start
            from kranto.page import proc
            note("detached", proc.spawn_detached(["sleep", "300"]).pid)
        if "deaf" in states:        # a child that ignores SIGTERM
            p = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal("
                                  "signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True);"
                                  " time.sleep(300)"], stdout=subprocess.PIPE, text=True)
            p.stdout.readline()
            note("deaf", p.pid)
        note("ready", os.getpid())
        try:
            yield
        finally:
            stopping.stop_server(stop, Cubs() if "hang" in states else None, scheduler)

    app = Starlette(routes=[Route("/", lambda r: JSONResponse({}))], lifespan=lifespan)
    cli._serve(app, stop, host="127.0.0.1", port=port)
""")


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _gone(pid: int, s: float = 5.0) -> bool:
    end = time.monotonic() + s
    while time.monotonic() < end and _alive(pid):
        time.sleep(0.05)
    return not _alive(pid)


def _stop_in(tmp_path, states: str, wait: tuple[str, ...] = ()) -> tuple[float, int, str, dict]:
    """Start the server in ``states``, wait until each of ``wait`` has its pid written, send
    SIGTERM; returns the seconds to exit, the exit status, the output and the pids."""
    port = free_port()
    (tmp_path / "states.py").write_text(STATES)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KRANTO_", "BRB_"))}
    p = subprocess.Popen([sys.executable, str(tmp_path / "states.py"), str(port), states,
                          str(tmp_path)], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 30
        while not all((tmp_path / w).exists() for w in ("ready", *wait)):
            assert p.poll() is None and time.monotonic() < deadline, p.stdout.read()
            time.sleep(0.05)
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            raise AssertionError("still running 30 s after SIGTERM") from None
        took = time.monotonic() - t0
        pids = {f.name: int(f.read_text()) for f in tmp_path.iterdir()
                if f.name in ("child", "terminal", "detached", "deaf")}
        return took, p.returncode, p.stdout.read(), pids
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_sigterm_when_idle_stops_at_once_and_clean(tmp_path):
    took, code, out, _ = _stop_in(tmp_path, "idle")
    assert took < 3, (took, out)
    assert code == -signal.SIGTERM                       # uvicorn re-raises it: systemd's success
    assert "stop: SIGTERM; ending within 10 s" in out and "stop: done in" in out
    assert ", clean" in out


def test_sigterm_during_a_job_in_a_model_call_ends_within_the_budget(tmp_path):
    # the 0.4.9 update: an ingest in a model call held the old server 91 s, until SIGKILL
    took, code, out, _ = _stop_in(tmp_path, "job,lane", wait=("job", "lane"))
    assert took < 11, (took, out)                        # the budget is 10 s; systemd waits 15
    assert code == -signal.SIGTERM
    assert "cut off (resumes after the start): the ingest job; the loop lane's tick" in out


def test_sigterm_ends_the_servers_children_and_leaves_its_detached_jobs(tmp_path):
    pytest.importorskip("kranto.page.proc")
    from kranto.page import host_api
    if "detached_jobs" not in getattr(host_api, "_NAMES", {}):
        pytest.skip("a the page from before STOP")
    took, code, out, pids = _stop_in(tmp_path, "child,terminal,detached,deaf",
                                     wait=("child", "terminal", "detached", "deaf"))
    try:
        assert took < 11, (took, out)
        assert code == -signal.SIGTERM
        for k in ("child", "terminal", "deaf"):         # nothing orphaned
            assert _gone(pids[k]), (k, out)
        assert _alive(pids["detached"])                  # a build keeps running
        assert "child processes (" in out and "cut off" in out
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pids["detached"], signal.SIGKILL)


def test_a_stop_that_hangs_is_ended_by_the_watchdog_before_systemd(tmp_path):
    took, code, out, pids = _stop_in(tmp_path, "hang,child", wait=("child",))
    assert 11 < took < 14, (took, out)                   # HARD_EXIT_S 12, TimeoutStopSec 15
    assert code == 0
    assert "stop: forced exit after 12" in out and "(phase: cubs)" in out
    assert _gone(pids["child"])                          # SIGKILLed before the exit


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_sigterm_ends_the_server_while_a_live_feed_is_open(tmp_path):
    port = free_port()
    (tmp_path / "driver.py").write_text(DRIVER)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("KRANTO_", "BRB_"))}
    p = subprocess.Popen([sys.executable, str(tmp_path / "driver.py"), str(port)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                c = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                assert p.poll() is None and time.monotonic() < deadline, p.stdout.read()
                time.sleep(0.2)
        c.sendall(f"GET /stream HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
        c.settimeout(10)
        assert c.recv(200).startswith(b"HTTP/1.1 200")       # the feed is open and held
        t0 = time.monotonic()
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(20)
        except subprocess.TimeoutExpired:
            raise AssertionError("still running 20 s after SIGTERM with a feed open") from None
        took = time.monotonic() - t0
        assert took < 10, took
        assert p.returncode in (0, -signal.SIGTERM)
        c.close()
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
