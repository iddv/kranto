"""The cub runtime's failure modes (the second table): a cub runs a job inside
bubblewrap and its rows are written; crashes, deadlines and refused hellos are counted and
three in a row pause the cub; a changed tree or a missing folder pauses it; the update's drain
sees a running cub; the shutdown interrupts a job; a poison delivery batch is skipped after 8
failures; the scheduler runs a cub's job at its slot; a cub's settings come from its section."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kranto.core import events, registry
from kranto.core.cubs import files, logs, schedule
from kranto.core.cubs.process import CubFailed
from kranto.core.cubs.runtime import CubUnavailable

from .cubhelp import install, needs_bwrap, runtime
from .test_web import rt  # noqa: F401 - fixture


@pytest.fixture
def cubs(rt, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    r = runtime(rt)
    r.load()
    yield r
    r.stop_all("host")


@needs_bwrap
def test_a_cub_runs_a_job_in_its_sandbox_and_its_rows_are_written(rt, cubs):  # noqa: F811
    install(rt, "echo")
    out = cubs.run_job("echo", "echo.tick", "tick")
    assert out["status"] == "ok" and out["topics"] == 1 and out["line"] == "ticked"
    run = rt.store.query_one("SELECT status, summary FROM runs WHERE kind = 'echo.tick'")
    assert run["status"] == "ok" and json.loads(run["summary"])["topics"] == 1
    calls = [(r["service"], r["op"], r["status"]) for r in rt.store.query(
        "SELECT service, op, status FROM cub_calls WHERE cub = 'echo' ORDER BY id")]
    assert ("reads", "topics.list", "ok") in calls and ("kv", "put", "ok") in calls
    assert ("events", "publish", "ok") in calls
    [ev] = events.read(rt.store, kinds=["echo.said"])
    assert ev["feature"] == "echo" and ev["trust"] == "owner" and ev["origin"] == "cub"
    assert [e["payload"]["kind"] for e in events.read(rt.store, kinds=["job.finished"])] == \
        ["echo.tick"]
    lines = logs.read(rt.cfg, "echo")
    assert any(x["msg"] == "hello" for x in lines)
    assert oct(os.stat(files.cub_dir(rt.cfg, "echo") / "log").st_mode)[-3:] == "700"
    assert cubs.read("echo", "count", {}) == {"count": 1}
    assert cubs.action("echo", "echo.say", "say", {"text": "hi"}, door="ui")["say"] == \
        "you said hi"


@needs_bwrap
def test_the_process_is_reused_and_stopped_when_idle(rt, cubs, monkeypatch):  # noqa: F811
    install(rt, "echo")
    cubs.run_job("echo", "echo.tick", "tick")
    first = cubs.processes["echo"].proc.pid
    cubs.run_job("echo", "echo.tick", "tick")
    assert cubs.processes["echo"].proc.pid == first          # kept up, pinged, reused
    from dataclasses import replace

    from kranto.core.cubs import settings as cs
    rt.cfg = replace(rt.cfg, cubs=cs.parse({"idle_s": 0}))
    cubs.processes["echo"].last_used -= 5
    cubs.reap()
    time.sleep(0.5)
    assert "echo" not in cubs.processes or not cubs.processes["echo"].alive


@needs_bwrap
def test_a_handler_that_raises_fails_the_run_and_three_failures_pause(rt, cubs):  # noqa: F811
    install(rt, "echo")
    with pytest.raises(RuntimeError, match="the handler raised ValueError"):
        cubs.run_job("echo", "echo.boom", "boom")
    assert rt.store.query_one("SELECT status FROM runs WHERE kind = 'echo.boom'")["status"] \
        == "failed"
    assert cubs.installed["echo"].state == "installed"          # a handler's own bug: no pause

    def logged():
        return any("ValueError: the handler's own bug" in x["msg"]
                   for x in logs.read(rt.cfg, "echo") if x["src"] == "stderr")
    for _ in range(50):                    # stderr is read by its own thread
        if logged():
            break
        time.sleep(0.05)
    assert logged()


@needs_bwrap
def test_a_changed_tree_pauses_the_cub_before_it_runs(rt, cubs):  # noqa: F811
    install(rt, "echo")
    main = files.cub_dir(rt.cfg, "echo") / "src" / "main.py"
    os.chmod(main, 0o600)
    main.write_text(main.read_text() + "\n# one byte more\n")
    with pytest.raises(CubUnavailable, match="files changed since you approved them"):
        cubs.request("echo", "job.run", {"kind": "echo.tick", "method": "tick"}, kind="job",
                     deadline_s=60)
    assert cubs.installed["echo"].state == "paused"
    assert registry.refused(rt.store, cubs.installed["echo"].feature).startswith("paused")
    assert events.read(rt.store, kinds=["cub.paused"])


def test_a_missing_folder_pauses_the_cub_at_start(rt, cubs):  # noqa: F811
    install(rt, "echo")
    d = files.cub_dir(rt.cfg, "echo")
    files.make_writable(d)
    import shutil
    shutil.rmtree(d)
    cubs.start()
    row = rt.store.query_one("SELECT state, note FROM cubs WHERE cub = 'echo' ORDER BY id DESC")
    assert row["state"] == "paused" and row["note"] == "its folder is missing"


def test_an_orphan_folder_is_quarantined(rt, cubs):  # noqa: F811
    files.ensure_root(rt.cfg)
    (files.root(rt.cfg) / "stray" / "src").mkdir(parents=True)
    cubs.recover()
    assert not (files.root(rt.cfg) / "stray").exists()
    assert any(p.name.startswith("orphan-stray-") for p in (files.root(rt.cfg) / ".work")
               .iterdir())


@needs_bwrap
def test_a_refused_hello_pauses_with_why(rt, cubs):  # noqa: F811
    install(rt, "echo")
    row = rt.store.query_one("SELECT * FROM cubs WHERE cub = 'echo'")
    from kranto.core.cubs import registry as cub_registry
    cub_registry.append(rt.store, dict(row), manifest_hash="0" * 64)   # not the file's
    rt.store.insert("cub_pins", {"cub": "echo", "version": "1.0.0", "trust": "owner",
                                 "manifest_hash": "0" * 64, "tree_hash": row["tree_hash"],
                                 "created_at": row["created_at"]})
    cubs.load()
    with pytest.raises(RuntimeError, match="hello refused: the cub.yaml this process read"):
        cubs.run_job("echo", "echo.tick", "tick")
    assert cubs.installed["echo"].state == "paused"
    assert cubs.installed["echo"].note == "the cub.yaml this process read is not the one " \
                                         "approved"


@needs_bwrap
def test_disable_and_the_global_switch_stop_it_running(rt, cubs):  # noqa: F811
    from dataclasses import replace

    from kranto.core.cubs import settings as cs
    install(rt, "echo")
    rt.cfg = replace(rt.cfg, cubs=cs.parse({"echo": {"enabled": False}}))
    with pytest.raises(CubUnavailable, match="echo is off"):
        cubs.request("echo", "read.run", {"name": "count", "params": {}}, kind="read",
                     deadline_s=10)
    assert [j for j in cubs.jobs() if j.kind == "echo.tick"][0].every_hours == 0
    rt.cfg = replace(rt.cfg, cubs=cs.parse({"enabled": False}))
    assert cubs.mode_word("echo") == "off"


@needs_bwrap
def test_the_drain_sees_a_running_cub_and_stop_all_interrupts_it(rt, cubs):  # noqa: F811
    import threading
    install(rt, "echo")
    errors = []

    def slow():
        try:
            cubs.run_job("echo", "echo.slow", "slow")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=slow)
    t.start()
    for _ in range(100):
        if cubs.busy():
            break
        time.sleep(0.05)
    assert cubs.busy() == ["echo"]
    cubs.stop_all("host")
    t.join(timeout=30)
    assert not t.is_alive() and cubs.busy() == []
    row = rt.store.query_one("SELECT status, error FROM runs WHERE kind = 'echo.slow'")
    assert row["status"] == "failed" and "interrupted" in row["error"]   # due again after
    assert [str(e) for e in errors] == ["failed: interrupted (Kranto was stopping)"]


@needs_bwrap
def test_the_servers_stop_ends_a_hung_cub_and_its_scope_within_its_share(rt, cubs):  # noqa: F811
    # STOP: a cub that ignores cancel and shutdown no longer holds the server's stop for 20 s
    # and more: stop_all keeps to the budget the stop gives it, and leaves no scope behind
    import contextlib
    import threading

    from kranto import stopping
    from kranto.core.cubs import process
    install(rt, "hostile")
    def hang():
        with contextlib.suppress(Exception):     # the run fails: interrupted by the stop
            cubs.run_job("hostile", "hostile.hang", "hang")

    t = threading.Thread(target=hang, daemon=True)
    t.start()
    for _ in range(200):
        if cubs.busy():
            break
        time.sleep(0.05)
    assert cubs.busy() == ["hostile"]
    [proc] = cubs.processes.values()
    started = time.monotonic()
    left = cubs.stop_all("host", budget_s=stopping.CUBS_S)
    assert time.monotonic() - started < stopping.CUBS_S + 0.5
    assert left == [] and not proc.alive
    t.join(timeout=10)
    assert not t.is_alive()
    if cubs.limits_mode == "scope":
        for _ in range(50):
            if not [u for u in process.leftover_units() if u.startswith("kranto-cub-hostile")]:
                break
            time.sleep(0.1)
        assert [u for u in process.leftover_units() if u.startswith("kranto-cub-hostile")] == []


@needs_bwrap
def test_a_scope_left_behind_is_killed_by_the_reaper(rt, cubs):  # noqa: F811
    import subprocess

    from kranto.core.cubs import process, sandbox
    if cubs.limits_mode != "scope":
        pytest.skip("limits_mode is rlimits here: no scopes to leave behind")
    unit = f"{cubs.scope_prefix}leak-test0001"
    other = f"{process.scope_prefix(Path(rt.cfg.root) / 'another')}leak-test0001"   # another Kranto
    started = [subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect",
                                 "--unit", u, "--", "sleep", "120"], env=sandbox.scope_env())
               for u in (unit, other)]
    for _ in range(50):
        if {unit, other} <= set(process.leftover_units()):
            break
        time.sleep(0.1)
    assert {unit, other} <= set(process.leftover_units())
    try:
        cubs.reap()
        started[0].wait(timeout=10)
        assert unit not in process.leftover_units()
        assert other in process.leftover_units()                  # not this home's to kill
    finally:
        process.kill_unit(other)
        started[1].wait(timeout=10)


@needs_bwrap
def test_the_reaper_leaves_a_cub_that_is_still_saying_hello(rt, cubs, monkeypatch):  # noqa: F811
    """Seen on live: the scheduler's first run of a new cub was SIGKILLed 50 ms after its
    spawn, because the reaper ticked before the process was in the table."""
    from kranto.core.cubs import process
    if cubs.limits_mode != "scope":
        pytest.skip("limits_mode is rlimits here: no scopes for the reaper to kill")
    install(rt, "echo")
    hello, seen = cubs._hello, []

    def reaping_hello(cub, run_uuid):
        check = hello(cub, run_uuid)

        def reap_then_check(p):
            seen.extend(process.leftover_units(cubs.scope_prefix))
            cubs.reap()                     # a reaper tick while the cub waits for its answer
            return check(p)
        return reap_then_check

    monkeypatch.setattr(cubs, "_hello", reaping_hello)
    out = cubs.run_job("echo", "echo.tick", "tick")
    assert seen and out["status"] == "ok"


def test_rlimits_mode_caps_the_address_space():
    import subprocess
    import sys

    from kranto.core.cubs import sandbox
    limits = sandbox.Limits(memory_mb=256)
    code = "import resource; print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         preexec_fn=sandbox.rlimits(limits, "rlimits"), timeout=30)
    assert int(out.stdout) == 256 * 1024 * 1024
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         preexec_fn=sandbox.rlimits(limits, "scope"), timeout=30)
    assert int(out.stdout) == -1                        # under a scope the cgroup counts it


def test_a_stderr_line_with_no_end_is_read_in_bounded_pieces():
    """32 MiB on stderr with no newline: the host's memory grows by under 8 MiB, the log takes
    the line's first 4,000 characters once, and the next line is read as usual. Measured in a
    fresh interpreter by its own ``VmHWM`` (``ru_maxrss`` keeps the parent's across exec)."""
    import subprocess
    import sys
    code = r"""
import json, sys, time
from pathlib import Path
from kranto.core.cubs.process import CubProcess

def hwm():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1])

fake = ("import json, os, time\n"
        "os.write(1, (json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'hello', "
        "'params': {}}) + '\\n').encode())\n"
        "chunk = b'x' * 1048576\n"
        "for _ in range(32):\n"
        "    os.write(2, chunk)\n"
        "os.write(2, b'\\nafter\\n')\n"
        "time.sleep(30)\n")
seen = []
proc = CubProcess(cid="fake", argv=[sys.executable, "-c", fake], env={}, preexec=None,
                  unit=None, mode="rlimits", hello=lambda p: {}, stderr=seen.append)
before = hwm()
proc.start()
for _ in range(300):
    if "after" in seen:
        break
    time.sleep(0.1)
grew = hwm() - before
proc.kill()
print(json.dumps({"grew_kib": grew, "lens": [len(s) for s in seen], "last": seen[-1:]}))
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=120)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["grew_kib"] < 8 * 1024
    assert got["lens"] == [4000, 5] and got["last"] == ["after"]


def test_a_cub_may_not_make_user_namespaces_where_bwrap_can_say_so(monkeypatch, tmp_path):
    from kranto.core.cubs import sandbox
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    lim = sandbox.Limits(memory_mb=256)

    def cmd(flags):
        monkeypatch.setattr(sandbox, "userns_flags", lambda: flags)
        return sandbox.argv(src=tmp_path, entry="main", venv=None, unit="u", limits=lim,
                            mode="rlimits")
    on = cmd(["--unshare-user", "--disable-userns"])
    assert on[1:5] == ["--unshare-all", "--unshare-user", "--disable-userns",
                       "--die-with-parent"]
    assert "--disable-userns" not in cmd([])            # an older bwrap: the rest unchanged


def fake_python(tmp_path):
    """A uv-managed Python's shape under a home: uv writes the root into sysconfig's data."""
    root = tmp_path / "home" / "someone" / ".local" / "share" / "uv" / "python" / "cpython-3.12"
    lib = root / "lib" / "python3.12"
    (lib / "__pycache__").mkdir(parents=True)
    (root / "bin").mkdir()
    exe = root / "bin" / "python3.12"
    exe.write_bytes(b"\x7fELF\0no path here")
    (lib / "os.py").write_text("# the stdlib\n")
    (lib / "_sysconfigdata_x.py").write_text(f"build_time_vars = {{'prefix': '{root}'}}\n")
    (lib / "__pycache__" / "_sysconfigdata_x.cpython-312.pyc").write_bytes(
        b"\x00\x01" + str(root).encode() + b"\x00")
    (lib / "_native.so").write_bytes(b"\x7fELF\0" + str(root).encode() + b"\0tail")
    return root, exe


def test_a_python_from_the_home_is_shown_at_a_neutral_path(monkeypatch, tmp_path):
    from kranto.core.cubs import sandbox
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root, exe = fake_python(tmp_path)
    assert sandbox.python_root(str(exe)) == str(root)
    assert sandbox.python_inside(str(exe)) == f"{sandbox.PYTHON_AT}/bin/python3.12"
    assert sandbox.python_root("/usr/bin/python3") is None
    assert sandbox.python_inside("/usr/bin/python3") == "/usr/bin/python3"
    view = dict((inside, Path(copy)) for copy, inside in sandbox.python_view(str(root)))
    at = sandbox.PYTHON_AT + "/lib/python3.12/"
    assert set(view) == {at + "_sysconfigdata_x.py", at + "_native.so",
                         at + "__pycache__/_sysconfigdata_x.cpython-312.pyc"}
    assert view[at + "_sysconfigdata_x.py"].read_text() == \
        f"build_time_vars = {{'prefix': '{sandbox.PYTHON_AT}'}}\n"
    assert view[at + "__pycache__/_sysconfigdata_x.cpython-312.pyc"].read_bytes() == b""
    native = view[at + "_native.so"].read_bytes()
    assert str(root).encode() not in native
    assert len(native) == (root / "lib" / "python3.12" / "_native.so").stat().st_size
    assert all(str(tmp_path / "cache") in str(p) for p in view.values())


def test_the_sandbox_binds_no_host_path_where_a_cub_can_name_it(monkeypatch, tmp_path):
    """The interpreter at PYTHON_AT with its rewritten files over it, the venv's packages
    only (its pyvenv.cfg and scripts name host paths), and no /proc (its mountinfo names the
    host path of every bind)."""
    from kranto.core.cubs import sandbox
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    root, exe = fake_python(tmp_path)
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox, "userns_flags", lambda: [])
    monkeypatch.setattr(sandbox, "base_python", lambda: str(exe))
    venv = tmp_path / "venv"
    site = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / \
        "site-packages"
    site.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text(f"home = {root}/bin\n")
    (site / "pkg" / "__pycache__").mkdir(parents=True)
    sdk = {n: tmp_path / "sdk" / n for n in ("bears_cub", "yaml")}
    for d in sdk.values():
        (d / "__pycache__").mkdir(parents=True)
    monkeypatch.setattr(sandbox, "sdk_dirs", lambda: {n: str(d) for n, d in sdk.items()})
    cmd = sandbox.argv(src=tmp_path / "src", entry="main", venv=venv, unit="u",
                       limits=sandbox.Limits(), mode="rlimits")
    binds = {cmd[i + 2]: cmd[i + 1] for i, a in enumerate(cmd) if a == "--ro-bind"}
    assert binds[sandbox.PYTHON_AT] == str(root)
    assert binds[sandbox.venv_site(venv)] == str(site)
    assert not any(d.startswith(str(tmp_path)) for d in binds)       # nothing at its own path
    assert "/cub/venv" not in binds and "--proc" not in cmd
    assert f"{sandbox.PYTHON_AT}/bin/python3.12" in cmd
    assert sandbox.PYTHON_AT + "/lib/python3.12/_sysconfigdata_x.py" in binds
    # bytecode records the host path of its source: an empty folder over each __pycache__
    empty = str(tmp_path / "cache" / "kranto" / "sandbox" / "empty")
    for inside in (f"{sandbox.SDK_AT}/bears_cub/__pycache__", f"{sandbox.SDK_AT}/yaml/__pycache__",
                   f"{sandbox.venv_site(venv)}/pkg/__pycache__"):
        assert binds[inside] == empty


def test_where_only_rlimits_apply_a_strangers_cub_waits_for_the_owners_word(rt, cubs):  # noqa: F811
    from dataclasses import replace

    from kranto.core.cubs import sandbox
    from kranto.core.cubs import settings as cs
    cubs.limits_mode = "rlimits"
    install(rt, "echo", trust="unreviewed")
    cubs.load()
    out = cubs.run_job("echo", "echo.tick", "tick")             # left due, not failed
    assert out["status"] == "skipped" and "cannot cap a cub's processes" in out["line"]
    with pytest.raises(CubUnavailable, match="cubs.allow_rlimits: true"):
        cubs.preflight("echo", "action")
    assert rt.store.query_one("SELECT 1 FROM runs WHERE kind = 'echo.tick'") is None
    # the scheduler does not try it once a minute meanwhile: its jobs are off until the word
    assert {j.kind: j.every_hours for j in cubs.jobs()}["echo.tick"] == 0
    rt.cfg = replace(rt.cfg, cubs=cs.parse({"allow_rlimits": True}))
    assert {j.kind: j.every_hours for j in cubs.jobs()}["echo.tick"] > 0
    if sandbox.sandboxed():
        assert cubs.run_job("echo", "echo.tick", "tick")["status"] == "ok"
    else:
        assert cubs.weak_limits(cubs.installed["echo"]) is None


def test_where_only_rlimits_apply_the_owners_cub_runs(rt, cubs):  # noqa: F811
    cubs.limits_mode = "rlimits"
    install(rt, "echo", trust="owner")
    cubs.load()
    assert cubs.weak_limits(cubs.installed["echo"]) is None


def test_the_host_and_the_sdk_check_grants_with_one_function():
    import bears_cub.grants
    from kranto.core.cubs import host
    assert host.grant_table is bears_cub.grants
    assert host.grant_table.allow is bears_cub.grants.allow


@needs_bwrap
def test_a_secret_in_a_call_or_on_stderr_is_scrubbed_before_it_is_written(rt, cubs):  # noqa: F811
    from kranto.scrub import secret_shaped
    install(rt, "echo")
    cubs.run_job("echo", "echo.leak", "leak")
    details = [r["detail"] or "" for r in rt.store.query(
        "SELECT detail FROM cub_calls WHERE cub = 'echo'")]
    assert any("[secret]" in d for d in details)
    assert not any(secret_shaped(d) for d in details)
    lines = logs.read(rt.cfg, "echo", limit=5000)
    for _ in range(50):
        if any("[secret]" in x["msg"] for x in lines if x["src"] == "stderr"):
            break
        time.sleep(0.05)
        lines = logs.read(rt.cfg, "echo", limit=5000)
    assert any("[secret]" in x["msg"] for x in lines if x["src"] == "stderr")
    assert not any(secret_shaped(json.dumps(x)) for x in lines)


def test_a_job_at_a_time_of_day_is_due_once_a_slot(rt):  # noqa: F811
    store = rt.store
    mon = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)            # a Monday
    assert schedule.at_due(store, "x.weekly", "08:00", ["mon"], mon, "UTC")
    store.insert("runs", {"run_uuid": "r1", "kind": "x.weekly", "status": "ok",
                          "started_at": "2026-10-19T09:00:00Z",
                          "finished_at": "2026-10-19T09:00:05Z", "summary": "{}"})
    later = datetime(2026, 10, 19, 22, 0, tzinfo=UTC)
    assert not schedule.at_due(store, "x.weekly", "08:00", ["mon"], later, "UTC")
    tue = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    assert not schedule.at_due(store, "x.weekly", "08:00", ["mon"], tue, "UTC")
    next_mon = datetime(2026, 10, 26, 8, 0, 1, tzinfo=UTC)
    assert schedule.at_due(store, "x.weekly", "08:00", ["mon"], next_mon, "UTC")
    assert schedule.next_slot("08:00", ["mon"], tue, "UTC") == datetime(
        2026, 10, 26, 8, 0, tzinfo=UTC)


def test_a_missed_slot_runs_once_when_kranto_is_back(rt):  # noqa: F811
    tue = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    assert schedule.last_slot("08:00", ["mon"], tue, "UTC") == datetime(
        2026, 10, 19, 8, 0, tzinfo=UTC)
    assert schedule.at_due(rt.store, "y.weekly", "08:00", ["mon"], tue, "UTC")


def test_a_failed_weekly_run_is_not_tried_again_on_every_start(rt):  # noqa: F811
    """The scheduler's back-off lives in memory, so after a failed weekly run every restart
    tried it again at once (a model call per start). The stored failures now set the wait;
    a run cut short by Kranto stopping does not count."""
    store = rt.store

    def failed(n, at, error="failed: the model did not answer"):
        store.insert("runs", {"run_uuid": f"f{n}", "kind": "z.weekly", "status": "failed",
                              "started_at": at, "finished_at": at, "summary": "{}",
                              "error": error})
    failed(1, "2026-10-19T09:00:00Z")
    soon = datetime(2026, 10, 19, 9, 1, tzinfo=UTC)         # a restart a minute later
    assert not schedule.at_due(store, "z.weekly", "08:00", ["mon"], soon, "UTC")
    assert schedule.at_next(store, "z.weekly", "08:00", ["mon"], soon, "UTC") == datetime(
        2026, 10, 19, 9, 5, tzinfo=UTC)
    assert schedule.at_due(store, "z.weekly", "08:00", ["mon"],
                           datetime(2026, 10, 19, 9, 5, tzinfo=UTC), "UTC")
    failed(2, "2026-10-19T09:05:00Z")                        # the wait doubles
    assert not schedule.at_due(store, "z.weekly", "08:00", ["mon"],
                               datetime(2026, 10, 19, 9, 14, tzinfo=UTC), "UTC")
    assert schedule.at_due(store, "z.weekly", "08:00", ["mon"],
                           datetime(2026, 10, 19, 9, 15, tzinfo=UTC), "UTC")
    # cut short by an update's stop: tried again straight after the restart
    failed(3, "2026-10-26T08:00:30Z", "failed: interrupted (Kranto was stopping)")
    assert schedule.at_due(store, "z.weekly", "08:00", ["mon"],
                           datetime(2026, 10, 26, 8, 1, tzinfo=UTC), "UTC")


def test_a_failed_run_raises_to_the_scheduler_for_its_back_off(rt, cubs, monkeypatch):  # noqa: F811
    install(rt, "echo")

    def boom(*a, **k):
        raise CubFailed("crashed", "failed: crashed (exit 1)")
    monkeypatch.setattr(cubs, "request", boom)
    with pytest.raises(RuntimeError, match="crashed"):
        cubs.run_job("echo", "echo.tick", "tick")
    assert rt.store.query_one("SELECT status, error FROM runs WHERE kind = 'echo.tick'")[
        "error"] == "failed: crashed (exit 1)"


def test_three_counted_failures_in_a_row_pause(rt, cubs):  # noqa: F811
    install(rt, "echo")
    cub = cubs.installed["echo"]
    for _ in range(2):
        cubs._failed(cub, CubFailed("deadline", "failed: deadline (10 s)"))
    assert cubs.installed["echo"].state == "installed"
    cubs._failed(cub, CubFailed("handler", "failed: the handler raised X"))   # not counted
    cubs._failed(cub, CubFailed("protocol", "failed: protocol (x)"))
    assert cubs.installed["echo"].state == "paused"
    assert "3 runs in a row failed" in cubs.installed["echo"].note
    with pytest.raises(CubUnavailable, match="paused"):
        cubs.preflight("echo", "job")
    cubs.resume("echo")
    assert cubs.installed["echo"].state == "installed"


def test_a_poison_batch_is_skipped_after_eight_failures(rt, cubs, monkeypatch):  # noqa: F811
    install(rt, "echo")

    def fail(*a, **k):
        raise CubFailed("handler", "failed: the handler raised KeyError")
    monkeypatch.setattr(cubs, "request", fail)
    eid = events.core_publish(rt.store, "ticket.resolved", {"ticket_id": 1, "kind": "k",
                                                            "cub": "echo", "state": "dry"})
    for _ in range(7):
        cubs.deliver_all()
        assert events.cursor(rt.store, "echo", "ticket.resolved") == 0
    cubs.deliver_all()
    assert events.cursor(rt.store, "echo", "ticket.resolved") == eid
    row = rt.store.query_one("SELECT detail FROM cub_calls WHERE status = 'skipped'")
    assert "skipped after 8 failures" in row["detail"]


def test_a_cubs_section_of_kranto_yaml_is_its_settings(rt, cubs, tmp_path):  # noqa: F811
    from kranto import config as config_mod
    from kranto.core import settings
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML
                                         + "\nnewsy:\n  mood: calm\n")
    folder = tmp_path / "newsy"
    folder.mkdir()
    (folder / "cub.yaml").write_text(
        "schema: 1\napi: cub/1\nid: newsy\nversion: 1.0.0\ntitle: N\nsays: N.\n"
        "settings:\n  keys:\n    newsy.mood: {type: str, default: plain}\n"
        "    newsy.key: {type: str, default: none}\n")
    (folder / "main.py").write_text("from bears_cub import Cub\ncub = Cub()\n")
    install(rt, "newsy", folder=folder)
    assert settings.section(rt.cfg, "newsy")["newsy.mood"] == "calm"
    token = "ghp_" + "A1b2C3d4" * 5
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML
                                         + f"\nnewsy:\n  key: {token}\n")
    assert settings.section(rt.cfg, "newsy")["newsy.key"] is None     # never a key
    with pytest.raises(settings.SettingError, match="shaped like a key"):
        settings.write(rt.cfg, "newsy", "newsy.key", token)
    assert any(f.id == "newsy" for f in registry.features())


def test_the_scheduler_reads_a_cubs_jobs_as_they_come(rt, cubs):  # noqa: F811
    from kranto.scheduler import Scheduler
    s = Scheduler(rt.store, [], job_source=cubs.jobs)
    assert [j.kind for j in s.jobs] == []
    install(rt, "echo")
    kinds = [j.kind for j in s.jobs]
    assert "echo.tick" in kinds and "echo.boom" in kinds
    assert s.next_runs()["echo.tick"] is not None


def test_status_line_doctor_and_the_drain(rt, cubs, tmp_path):  # noqa: F811
    from kranto.core.cubs import status
    from kranto.web.app import create_app

    from .conftest import web_client
    assert status.status_line(rt.cfg, rt.store).startswith("none installed; ")
    install(rt, "echo")
    assert status.status_line(rt.cfg, rt.store).startswith(
        "1 installed, 0 in practice, 0 paused; ")
    rows = {name: (s, d) for s, name, d in status.doctor(rt.cfg, rt.store)}
    assert rows["cub echo"] == ("ok", "1.0.0, pinned")
    (tmp_path / "cubs.STOP").touch()
    assert "STOPPED" in status.status_line(rt.cfg, rt.store)
    assert status.doctor(rt.cfg, rt.store)[2][0] == "FAIL"
    (tmp_path / "cubs.STOP").unlink()
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        assert web.get("/api/update").json()["busy"]["cubs"] == []
        row = next(f for f in web.get("/api/features").json()["features"] if f["id"] == "echo")
        assert row["cub"]["state"] == "installed" and row["trust"] == "owner"
        assert row["manifest"]["api"] == "cub/1" and row["pinned"] is True
