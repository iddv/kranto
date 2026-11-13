"""Restart to update (kranto.update.apply, launch; section 4): the helper's
steps against a fake world (systemctl, uv, Kranto, the local server, /proc). The happy path,
waiting for a build, Update now, each failure rolling back, the double failure, the lock,
cancel, the stop guard, a rollback to the previous version, the idle rules, the launch."""

from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kranto import config as config_mod
from kranto.update import apply, check, launch

from .test_update_check import write_set

GIT = {"kranto": "1" * 40, "kranto.page": "2" * 40}


class World:
    """The machine as the helper sees it."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        (self.home / "data").mkdir(parents=True)
        self.tools = tmp / "tools"
        self.bin = tmp / "bin"
        self.env = {"HOME": str(tmp), "PATH": "/usr/bin", "UV_TOOL_DIR": str(self.tools),
                    "UV_TOOL_BIN_DIR": str(self.bin)}
        self.active = True
        self.hold = None
        self.hold_bodies = []
        self.deleted_hold = 0
        self.builds = []          # builds running, one per GET /api/update read: [2, 1, 0]
        self.procs_seq = []       # what the /proc guard sees, one list per call
        self.uv_fails = 0         # how many uv installs fail
        self.up_fails = False
        self.lane = {"state": "idle", "ticks": 1, "errors": 0}
        self.calls = []
        self.now = 0.0
        self.on_sleep = None
        # how the old server ended: a clean SIGTERM exit (systemd counts it a success)
        self.stopped = "Result=success\nExecMainCode=2\nExecMainStatus=15\n"
        self.stop_s = 0.4
        self.journal = ""         # what the old server logged while it stopped
        self.set_git(GIT, "0.1.0")

    # -- the tool environment ------------------------------------------------------------

    def _write(self, name, version, url):
        sp = self.tools / "kranto" / "lib" / "python3.12" / "site-packages"
        for d in sp.glob(f"{name}-*.dist-info"):
            if d.name.split("-")[0] == name:
                shutil.rmtree(d)
        d = sp / f"{name}-{version}.dist-info"
        d.mkdir(parents=True)
        (d / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n\n")
        (d / "direct_url.json").write_text(json.dumps(url))

    def set_git(self, commits, version):
        for n in apply.NAMES:
            self._write(n, version, {"url": "https://github.com/octo-owner/x",
                                     "vcs_info": {"vcs": "git", "commit_id": commits[n]}})

    def set_wheels(self, folder, version):
        for n in apply.NAMES:
            self._write(n, version, {"url": f"file://{folder}/{n}-{version}-py3-none-any.whl",
                                     "archive_info": {}})

    @property
    def version(self):
        return apply.installed(self.tools / "kranto")["version"]

    # -- the fakes ---------------------------------------------------------------------------

    def run(self, cmd, env=None, timeout=None):
        self.calls.append(cmd)
        ok = subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["systemctl", "--user"]:
            verb = cmd[2]
            if verb == "is-active":
                return subprocess.CompletedProcess(cmd, 0, "active" if self.active
                                                   else "inactive", "")
            if verb == "show" and "Result" in cmd:
                return subprocess.CompletedProcess(cmd, 0, self.stopped, "")
            if verb == "show":
                return subprocess.CompletedProcess(cmd, 0, "100\n" if self.active else "0\n",
                                                   "")
            if verb == "stop":
                self.now += self.stop_s
                self.active = False
            if verb == "start":
                self.active = True
            return ok
        if cmd[0] == "journalctl":
            assert cmd[1:4] == ["--user", "-u", "kranto.service"] and cmd[4] == "--since"
            return subprocess.CompletedProcess(cmd, 0, self.journal, "")
        if cmd[:3] == ["uv", "tool", "install"]:
            if self.uv_fails:
                self.uv_fails -= 1
                return subprocess.CompletedProcess(cmd, 1, "", "network is unreachable")
            last = cmd[-1]
            self.installed_target = last
            if last.endswith(".whl"):
                path = Path(last.split("file://", 1)[1]) if "file://" in last else Path(last)
                v = path.name.split("-")[1]
                self.set_wheels(path.parent, v)
            else:
                # the meta-package's own git deps are replaced by the overrides file's pins
                assert "--with" not in cmd and "--overrides" in cmd
                lines = Path(cmd[cmd.index("--overrides") + 1]).read_text().splitlines()
                commits = {"kranto": lines[0].rsplit("@", 1)[1],
                           "kranto.page": lines[1].rsplit("@", 1)[1]}
                self.set_git(commits, "0.1.0")
            return ok
        if cmd[0] == str(self.bin / "kranto"):
            if cmd[1] == "backup":
                dest = Path(cmd[2])
                dest.mkdir(parents=True, exist_ok=True)   # the clock is frozen in tests
                db = self.home / "data" / "kranto.db"
                import sqlite3
                c = sqlite3.connect(db)
                c.execute("CREATE TABLE IF NOT EXISTS t (x)")
                c.execute("INSERT INTO t VALUES (1)")
                c.commit()
                c.close()
                (dest / "counts-before.json").write_text(json.dumps({"afk": {"t": 1}}))
                (dest / "backup.json").write_text(json.dumps(
                    {"databases": {"kranto.db": {"from": str(db)}}}))
                return ok
            if cmd[1] == "up":
                if self.up_fails:
                    return subprocess.CompletedProcess(cmd, 1, "", "port in use")
                self.active = True
                return ok
            if cmd[1] == "--version":
                v = self.version
                return subprocess.CompletedProcess(cmd, 0, f"Kranto {v} (the server {v}, "
                                                   f"the page {v})\n", "")
        raise AssertionError(cmd)

    def http(self, method, url, body=None, timeout=10):
        path = url.split(":8765", 1)[1]
        self.calls.append((method, path))
        if path == "/api/hold":
            if method == "POST":
                self.hold = body
                self.hold_bodies.append(body)
            else:
                self.hold = None
                self.deleted_hold += 1
            return 200, {}
        if not self.active:
            return 0, None
        if path == "/api/update":
            n = self.builds.pop(0) if self.builds else 0
            return 200, {"busy": {"job": None, "builds": n, "fixes": 0}}
        if path == "/api/status":
            return 200, {"version": self.version, "lanes": {"loop": self.lane}}
        if path == "/brb/api/header":
            return 200, {}
        raise AssertionError(path)

    def procs(self, roots, ignore):
        return self.procs_seq.pop(0) if self.procs_seq else []

    def sleep(self, s):
        self.now += s
        if self.on_sleep:
            self.on_sleep()

    def helper(self, to="v0.2.0", **kw):
        # the self-check reads the new version's pages (never a real port here): every one
        # answers unless a test says otherwise (self.routes_said)
        kw.setdefault("check_routes", lambda base: dict(self.routes_said, base=base))
        return apply.Helper(self.home, to, env={**self.env, **kw.pop("env", {})},
                            run=self.run, http=self.http, procs=self.procs, sleep=self.sleep,
                            clock=lambda: self.now, which=lambda n, path=None: "/usr/bin/" + n,
                            free_bytes=lambda p: 10 * 2 ** 30, **kw)

    routes_said = {"ok": True, "checked": 40, "of": 40, "failed": [], "unchecked": 0,
                   "seconds": 3.2}

    def stage(self, tag="v0.2.0"):
        write_set(apply.releases_dir(self.home) / tag, apply.tag_version(tag))


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.stage()
    return w


def states(w):
    log = Path(json.loads(apply.state_path(w.home).read_text())["log"]).read_text()
    return [line.split("state ", 1)[1].split(":")[0] for line in log.splitlines()
            if " state " in line]


# -- the happy path --------------------------------------------------------------------------


def test_update_from_git_to_a_release(world):
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["state"] == "done" and st["from"] == "0.1.0" and st["to"] == "0.2.0"
    assert states(world) == ["requested", "draining", "backing_up", "stopping", "installing",
                             "starting", "verifying", "done"]
    assert world.version == "0.2.0" and world.active
    prev = json.loads(apply.previous_path(world.home).read_text())
    assert prev["kind"] == "git" and prev["commits"] == GIT and prev["version"] == "0.1.0"
    assert world.hold_bodies == [{"reason": "update to 0.2.0", "stop_builds": False}]
    backups = list((world.home / "backups").glob("update-*-from-0.1.0"))
    assert len(backups) == 1 and (backups[0] / "counts-after.json").exists()
    hist = apply.history(world.home)
    assert hist[0]["state"] == "done" and hist[0]["to"] == "0.2.0"
    install = next(c for c in world.calls if c[:3] == ["uv", "tool", "install"])
    assert install[3:6] == ["--force", "--python", "3.12"] and "--with-executables-from" in install
    assert install[-1].endswith("kranto-0.2.0-py3-none-any.whl")


def test_a_clean_stop_is_recorded_as_one(world):
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["stop"] == {"seconds": 0.4, "result": "success", "killed": False}
    assert not st.get("warning") and st["detail"] == "0.2.0 is running"
    assert apply.history(world.home)[0]["stop"]["result"] == "success"


def test_a_stop_that_needed_sigkill_is_a_warning_not_done_as_usual(world):
    # live, 2026-10-16 19:55:32 -> 19:57:02 (0.3.71 -> 0.3.72), and every update since 0.3.65:
    # "State 'stop-sigterm' timed out. Killing. ... status=9/KILL ... Failed with result
    # 'timeout'"; the helper said "done, 0.3.72 is running"
    world.stopped = "Result=timeout\nExecMainCode=2\nExecMainStatus=9\n"
    world.stop_s = 90.0
    assert world.helper().run_all() == "done"          # the new version runs: no rollback
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["stop"] == {"seconds": 90.0, "result": "timeout", "killed": True}
    assert st["warning"] == ("the old server did not stop on SIGTERM: systemd killed it after "
                             "90 s (result timeout)")
    assert st["detail"] == f"0.2.0 is running; warning: {st['warning']}"
    row = apply.history(world.home)[0]
    assert row["warning"] == st["warning"] and row["stop"]["killed"]
    log = Path(st["log"]).read_text()
    assert "stopped in 90.0 s, systemd result timeout" in log and "WARNING: the old" in log


def test_the_servers_own_stop_line_is_kept_with_a_clean_stop(world):
    # a server since STOP says how its stop went; the update keeps its last line
    world.journal = ("2026-10-20 08:00:00,100 kranto.stop stop: SIGTERM; ending within 10 s\n"
                     "2026-10-20 08:00:01,300 kranto.stop stop: done in 1.2 s, clean\n")
    world.stop_s = 1.3
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["stop"] == {"seconds": 1.3, "result": "success", "killed": False,
                          "said": "done in 1.2 s, clean"}
    assert not st.get("warning")
    assert "the server said: done in 1.2 s, clean" in Path(st["log"]).read_text()


def test_a_slow_stop_is_a_warning_that_says_what_the_server_waited_for(world):
    # not killed, but past the 12 s a stop takes at most: said, with what was cut off
    world.journal = ("x kranto.stop stop: done in 9.9 s; cut off (resumes after the start): "
                     "the ingest job\n")
    world.stop_s = 14.0
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert not st["stop"]["killed"]
    assert st["warning"] == ("the old server was slow to stop: 14 s (a stop takes at most 12 s); "
                             "it said: done in 9.9 s; cut off (resumes after the start): the "
                             "ingest job")
    assert apply.history(world.home)[0]["warning"] == st["warning"]


def test_a_forced_exit_is_a_warning_even_inside_the_time(world):
    world.journal = ("x kranto.stop stop: forced exit after 12.0 s (phase: scheduler); "
                     "threads: a\n")
    world.stop_s = 12.1
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["warning"].startswith("the old server was slow to stop: 12 s")
    assert st["warning"].endswith("it said: forced exit after 12.0 s (phase: scheduler); "
                                  "threads: a")


def test_the_extras_kranto_was_installed_with_are_kept(world):
    # installed as "kranto[mcp] @ git+…" (uv's receipt says so): the update, the previous spec
    # and the rollback all keep the mcp extra, and the git pin keeps the page's own mcp extra
    (world.tools / "kranto" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [\n    { name = "kranto", extras = ["mcp"], git = "https://x" },\n'
        '    { name = "kranto" },\n]\n')
    assert world.helper().run_all() == "done"
    assert world.installed_target.startswith("kranto[mcp] @ file://")
    assert world.installed_target.endswith("/v0.2.0/kranto-0.2.0-py3-none-any.whl")
    prev = json.loads(apply.previous_path(world.home).read_text())
    assert prev["kranto_extras"] == ["mcp"]
    assert world.helper(to="previous").run_all() == "done"
    assert world.installed_target.startswith("kranto[mcp] @ git+https://github.com/iddv/kranto@")
    overrides = (apply.update_dir(world.home) / "git-overrides.txt").read_text()
    want = "kranto.page[mcp] @ git+https://github.com/iddv/kranto@" + GIT["kranto.page"]
    assert want in overrides


def test_the_receipt_is_read_without_tomllib_too(tmp_path, monkeypatch):
    import builtins

    (tmp_path / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [\n    { name = "kranto", extras = ["mcp", "x"], git = "g" },\n]\n'
    )
    assert apply.receipt_extras(tmp_path) == ["mcp", "x"]
    real = builtins.__import__
    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda n, *a, **k: (
            (_ for _ in ()).throw(ImportError(n)) if n == "tomllib" else real(n, *a, **k)
        ),
    )
    assert apply.receipt_extras(tmp_path) == ["mcp", "x"]
    assert apply.receipt_extras(tmp_path / "none") == []


def test_it_waits_for_a_running_build(world):
    world.builds = [2, 1, 0]
    assert world.helper().run_all() == "done"
    log = Path(json.loads(apply.state_path(world.home).read_text())["log"]).read_text()
    assert "waiting for 2 builds" in log and "waiting for 1 build" in log
    assert world.now >= 2 * apply.POLL_S


def test_the_proc_guard_holds_the_update(world):
    # nothing in the ledger, but a process still runs from the tool (not the server, pid 100)
    world.procs_seq = [
        [(100, "python kranto serve"), (4242, "python -m kranto.page.cli build")],
        [(100, "python kranto serve")],
        [],
        [],
    ]
    assert world.helper().run_all() == "done"
    log = Path(json.loads(apply.state_path(world.home).read_text())["log"]).read_text()
    assert "1 process from the tool (python -m kranto.page.cli build)" in log


def test_the_consoles_own_processes_do_not_hold_the_update(world):
    """Live, 2026-10-27: the console's Claude Code (a child of the server, pid 100) runs `kranto
    mcp` from the tool; the drain waited for it, held every new run and never finished while
    the console was open. The server's own descendants go down with its unit at the stop (whose
    guard still waits for anything from the tool), so the drain passes them; an outside client's
    `kranto mcp` (not the server's) is still waited for."""
    parents = {7001: 7000, 7000: 100, 8001: 900, 900: 1}  # 7001: kranto mcp under the console
    console = [(100, "python kranto serve"), (7001, "python kranto mcp")]
    world.procs_seq = [console, [], []]
    h = world.helper(ppid=parents.get)
    assert h.run_all() == "done"
    log = Path(json.loads(apply.state_path(world.home).read_text())["log"]).read_text()
    assert "process from the tool" not in log
    # an outside terminal's kranto mcp is not the server's: it is waited for, as before
    world.stage()
    world.procs_seq = [[(100, "python kranto serve"), (8001, "python kranto mcp")], [], [], []]
    assert world.helper(ppid=parents.get).run_all() == "done"
    log = Path(json.loads(apply.state_path(world.home).read_text())["log"]).read_text()
    assert "1 process from the tool (python kranto mcp)" in log
    assert apply.descends(7001, 100, parents.get) and not apply.descends(8001, 100, parents.get)
    # the real /proc: this test's process descends from its parent
    import os

    assert apply.ppid_of(os.getpid()) == os.getppid()
    assert apply.descends(os.getpid(), os.getppid()) and apply.ppid_of(2**30) is None


def test_update_now_stops_the_builds(world):
    assert world.helper(when="now").run_all() == "done"
    assert world.hold_bodies[0]["stop_builds"] is True


def test_roll_back_to_the_previous_version(world):
    assert world.helper().run_all() == "done"
    assert world.helper(to="previous").run_all() == "done"
    assert world.version == "0.1.0"
    assert (
        apply.installed(world.tools / "kranto")["spec"]["commits"]["kranto.page"]
        == GIT["kranto.page"]
    )
    prev = json.loads(apply.previous_path(world.home).read_text())
    assert prev["kind"] == "wheels" and prev["version"] == "0.2.0"


# -- failures roll back ----------------------------------------------------------------------


@pytest.mark.parametrize("fail", ["install", "start", "verify"])
def test_a_forced_failure_rolls_back(world, fail):
    assert world.helper(env={"KRANTO_UPDATE_FAIL": fail}).run_all() == "rolled_back"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["reason"] == f"forced: {fail}"
    assert world.version == "0.1.0" and world.active
    assert "rolling_back" in states(world)
    # the previous spec is as it was before the attempt (none), so nothing claims a rollback
    assert not apply.previous_path(world.home).exists()
    assert apply.history(world.home)[0]["state"] == "rolled_back"


def test_a_version_that_breaks_on_this_installs_data_rolls_back(world):
    """the new version answers as itself, but one of its pages answers 500
    on this install's own data: it is rolled back, the reason says which page and the error's
    id, and the history keeps what the self-check found."""
    world.routes_said = {
        "ok": False,
        "checked": 40,
        "of": 41,
        "unchecked": 1,
        "seconds": 9.0,
        "failed": [
            {
                "path": "/api/topics/7",
                "status": 500,
                "error_id": "1a2b3c4d",
                "exception": "TypeError",
            },
            {
                "path": "/api/topics/9",
                "status": 500,
                "error_id": "1a2b3c4d",
                "exception": "TypeError",
            },
        ],
    }
    assert world.helper().run_all() == "rolled_back"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["reason"] == (
        "0.2.0 broke on your data: GET /api/topics/7 answered 500 (error 1a2b3c4d); 1 more"
    )
    assert world.version == "0.1.0" and world.active
    assert st["selfcheck"]["failed"][0]["error_id"] == "1a2b3c4d"
    row = apply.history(world.home)[0]
    assert row["state"] == "rolled_back" and row["selfcheck"]["checked"] == 40
    log = Path(st["log"]).read_text()
    assert "self-check: 40 of 41 reads in 9.0 s, 1 past the budget" in log
    assert "FAIL GET /api/topics/7: 500 (error 1a2b3c4d)" in log
    # the page's summary says it broke, and the error Send this error files; the server it put
    # back reports it once to the error reports (if the person chose to send; ERR, B1)
    from kranto.telemetry import errors
    from kranto.update import check

    said = []
    real = errors.report_failure
    errors.report_failure = lambda *a, **k: said.append((a, k))
    try:
        s = check.summary(world.home)
        check.summary(world.home)
    finally:
        errors.report_failure = real
    assert s["state"] == "rolled_back" and s["broke"] == {"pages": 2, "error_id": "1a2b3c4d"}
    assert [(a, k["message"]) for a, k in said] == [
        (("UpdateSelfCheck", "update"), "the new version answered 500 on a page of the self-check")
    ]


def test_a_version_that_passes_its_self_check_is_kept_and_says_so(world):
    assert world.helper().run_all() == "done"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["selfcheck"]["ok"] and st["selfcheck"]["checked"] == 40
    assert "self-check: 40 of 40 reads in 3.2 s" in Path(st["log"]).read_text()
    from kranto.update import check

    assert check.summary(world.home)["broke"] is None


def test_a_page_that_does_not_answer_rolls_back_too(world):
    world.routes_said = {
        "ok": False,
        "checked": 3,
        "of": 3,
        "unchecked": 0,
        "seconds": 30.0,
        "failed": [{"path": "/api/home", "status": 0, "error_id": None}],
    }
    assert world.helper().run_all() == "rolled_back"
    assert (
        json.loads(apply.state_path(world.home).read_text())["reason"]
        == "0.2.0 broke on your data: GET /api/home did not answer"
    )


def test_route_check_reads_every_listed_page_and_names_what_failed():
    pages = {
        "/api/selfcheck/paths": (200, {"paths": ["/api/a", "/api/b", "/api/c", "x"]}),
        "/api/a": (200, {}),
        "/api/b": (500, {"error_id": "1a2b3c4d", "exception": "TypeError"}),
        "/api/c": (0, None),
    }
    asked = []

    def get(url, timeout):
        asked.append((url, timeout))
        return pages[url.removeprefix("http://h")]

    res = apply.route_check("http://h", get=get, clock=lambda: 0.0)
    assert [u for u, _ in asked] == [
        "http://h/api/selfcheck/paths",
        "http://h/api/a",
        "http://h/api/b",
        "http://h/api/c",
    ]
    assert not res["ok"] and res["checked"] == 3 and res["of"] == 4
    assert res["failed"] == [
        {"path": "/api/b", "status": 500, "error_id": "1a2b3c4d", "exception": "TypeError"},
        {"path": "/api/c", "status": 0, "error_id": None, "exception": None},
    ]
    # a version without the list is not checked; a list that fails is a failure
    assert apply.route_check("h", get=lambda u, t: (404, None))["skipped"]
    bad = apply.route_check("h", get=lambda u, t: (500, {"error_id": "0000beef"}))
    assert not bad["ok"] and bad["failed"][0]["error_id"] == "0000beef"


def test_route_check_stops_at_its_budget_without_failing():
    t = [0.0]

    def get(url, timeout):
        t[0] += 50.0
        return (
            (200, {"paths": [f"/api/{n}" for n in range(10)]})
            if url.endswith("paths")
            else (200, {})
        )

    res = apply.route_check("h", get=get, clock=lambda: t[0], budget_s=180)
    assert res["ok"] and res["checked"] == 3 and res["unchecked"] == 7


def test_a_failing_install_rolls_back(world):
    world.uv_fails = 1
    assert world.helper().run_all() == "rolled_back"
    st = json.loads(apply.state_path(world.home).read_text())
    assert "uv tool install failed: network is unreachable" in st["reason"]


def test_a_lane_with_errors_rolls_back(world):
    world.lane = {"state": "idle", "ticks": 1, "errors": 1, "last_error": "no such column"}
    assert world.helper().run_all() == "rolled_back"
    assert (
        "the loop lane failed: no such column"
        in json.loads(apply.state_path(world.home).read_text())["reason"]
    )


def test_the_double_failure_is_failed_with_the_way_back_by_hand(world):
    world.uv_fails = 10
    assert world.helper().run_all() == "failed"
    st = json.loads(apply.state_path(world.home).read_text())
    assert "the rollback failed too" in st["reason"]
    assert st["detail"].startswith(
        "by hand: systemctl --user stop kranto.service; uv tool install --force"
    )
    overrides = apply.update_dir(world.home) / "git-overrides.txt"
    assert f"--overrides {overrides}" in st["detail"]
    assert overrides.read_text().splitlines() == [
        "kranto[connections,notify] @ git+https://github.com/iddv/kranto@" + GIT["kranto"],
        "kranto.page @ git+https://github.com/iddv/kranto@" + GIT["kranto.page"],
    ]


def test_a_rollback_that_fails_too_is_failed(world):
    assert world.helper(env={"KRANTO_UPDATE_FAIL": "verify,rollback"}).run_all() == "failed"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["reason"] == "forced: verify; the rollback failed too: forced: rollback"
    assert "restore the databases from" in st["detail"]


# -- nothing changes ---------------------------------------------------------------------------


def test_cancel_while_waiting_changes_nothing(world):
    world.builds = [1] * 50
    n = {"sleeps": 0}

    def sleeping():
        n["sleeps"] += 1
        if n["sleeps"] == 3:
            apply.cancel_path(world.home).touch()

    world.on_sleep = sleeping
    assert world.helper().run_all() == "cancelled"
    st = json.loads(apply.state_path(world.home).read_text())
    assert st["reason"] == "cancelled while waiting" and st["detail"] == "nothing was changed"
    assert world.deleted_hold == 1 and world.version == "0.1.0"
    assert not any(c[:3] == ["uv", "tool", "install"] for c in world.calls if isinstance(c, list))


def test_an_inactive_service_or_a_bad_set_is_refused(world):
    world.active = False
    assert world.helper().run_all() == "cancelled"
    assert (
        "kranto.service is inactive"
        in json.loads(apply.state_path(world.home).read_text())["reason"]
    )
    world.active = True
    (apply.releases_dir(world.home) / "v0.2.0" / "kranto-0.2.0-py3-none-any.whl").write_bytes(b"x")
    assert world.helper().run_all() == "cancelled"
    assert "does not verify" in json.loads(apply.state_path(world.home).read_text())["reason"]
    assert world.helper(to="previous").run_all() == "cancelled"


def test_a_process_that_outlives_the_stop_restarts_the_old_version(world):
    world.procs_seq = [[]] + [[(77, "python -m kranto.page.cli build")]] * 100
    assert world.helper().run_all() == "cancelled"
    st = json.loads(apply.state_path(world.home).read_text())
    assert "still runs from the tool after the stop" in st["reason"]
    assert world.active and world.version == "0.1.0"
    assert ["systemctl", "--user", "start", "kranto.service"] in world.calls


def test_one_update_at_a_time(world):
    apply.update_dir(world.home).mkdir(parents=True, exist_ok=True)
    with open(apply.lock_path(world.home), "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert world.helper().run_all() == "busy"


def test_prune_keeps_the_running_and_previous_sets(world):
    for tag in ("v0.1.7", "v0.1.8", "v0.1.9"):
        world.stage(tag)
    for i in range(5):
        (world.home / "backups" / f"update-2026100{i}T000000Z-from-x").mkdir(parents=True)
    assert world.helper(keep=2).run_all() == "done"
    sets = sorted(p.name for p in apply.releases_dir(world.home).iterdir())
    assert "v0.2.0" in sets and len(sets) == 2
    assert len(list((world.home / "backups").glob("update-*"))) == 2


# -- the idle rules ----------------------------------------------------------------------------


def idle_cache(version="0.2.0", staged=True):
    return {
        "ok": True,
        "latest": {"version": version, "tag": "v" + version},
        "staged": {"version": version, "tag": "v" + version} if staged else None,
        "installed": {"version": "0.1.0"},
    }


LOCAL = timezone(timedelta(hours=2))


def test_idle_updates_only_inside_the_quiet_window(tmp_path):
    ucfg = config_mod.UpdateConfig(auto="idle", quiet_window="03:00-06:00")
    inside = datetime(2026, 10, 11, 4, 0, tzinfo=LOCAL)
    outside = datetime(2026, 10, 11, 12, 0, tzinfo=LOCAL)
    assert check.idle_blockers(tmp_path, ucfg, idle_cache(), now=inside, can=True) == []
    assert check.idle_blockers(tmp_path, ucfg, idle_cache(), now=outside, can=True) == [
        "outside the quiet window 03:00-06:00"
    ]
    assert check.in_window("23:00-02:00", datetime(2026, 10, 11, 1, 0))
    assert not check.in_window("23:00-02:00", datetime(2026, 10, 11, 3, 0))


def test_idle_never_takes_a_release_candidate_or_an_unstaged_set(tmp_path):
    ucfg = config_mod.UpdateConfig(auto="idle")
    now = datetime(2026, 10, 11, 4, 0, tzinfo=LOCAL)
    got = check.idle_blockers(
        tmp_path, ucfg, idle_cache("0.2.0rc1", staged=False), now=now, can=True
    )
    assert "only a stable release updates by itself" in got and "0.2.0rc1 is not staged" in got
    assert check.idle_blockers(tmp_path, config_mod.UpdateConfig(), idle_cache(), now=now) == [
        "auto is off"
    ]


def test_idle_waits_for_builds_a_claude_code_session_pause_and_history(tmp_path):
    ucfg = config_mod.UpdateConfig(auto="idle")
    now = datetime.now(LOCAL).replace(hour=4)
    loop = tmp_path / "loop"
    (loop / "chat").mkdir(parents=True)  # an old chat thread (the page): no blocker
    (loop / "chat" / "t1.json").write_text("{}")
    (loop / "term" / "c3f1a9e2").mkdir(parents=True)
    (loop / "term" / "c3f1a9e2" / "session.json").write_text(json.dumps({"state": "ended"}))
    (loop / "PAUSE").write_text("paused")
    got = check.idle_blockers(tmp_path, ucfg, idle_cache(), now=now, loop_home=loop, can=True)
    assert "Kranto is paused" in got and not any("chat" in g or "Claude Code" in g for g in got)
    (loop / "term" / "c3f1a9e2" / "session.json").write_text(json.dumps({"state": "running"}))
    got = check.idle_blockers(tmp_path, ucfg, idle_cache(), now=now, loop_home=loop, can=True)
    assert "a Claude Code session is open (an update would end it)" in got
    home = tmp_path / "home"
    apply.update_dir(home).mkdir(parents=True)
    done = (now - timedelta(hours=3)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    apply.history_path(home).write_text(json.dumps({"state": "done", "finished": done}) + "\n")
    assert "an update ran in the last 24 hours" in check.idle_blockers(
        home, ucfg, idle_cache(), now=now, can=True
    )
    apply.history_path(home).write_text(
        json.dumps({"state": "rolled_back", "to": "0.2.0", "finished": done}) + "\n"
    )
    assert "0.2.0 was rolled back this week (Try again is in Needs you)" in check.idle_blockers(
        home, ucfg, idle_cache(), now=now, can=True
    )


# -- the launch --------------------------------------------------------------------------------


def test_launch_runs_the_helper_as_a_transient_unit(tmp_path):
    home = tmp_path / "home"
    seen = []

    def run(cmd, timeout=60):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "inactive\n" if "is-active" in cmd else "", "")

    out = launch.launch(
        home,
        "v0.2.0",
        when="now",
        port=8766,
        unit="kranto-test.service",
        keep=3,
        ignore_pids=(4321,),
        run=run,
        which=lambda n: "/usr/bin/" + n,
        env={
            "HOME": str(tmp_path),
            "PATH": "/usr/bin",
            "UV_TOOL_DIR": "/t",
            "KRANTO_UPDATE_FAIL": "verify",
        },
    )
    assert out == {"unit": "kranto-test-update", "to": "v0.2.0", "when": "now"}
    cmd = seen[-1]
    assert cmd[:5] == [
        "systemd-run",
        "--user",
        "--unit=kranto-test-update",
        "--collect",
        "--description=kranto update to v0.2.0",
    ]
    assert (
        f"--setenv=KRANTO_HOME={home}" in cmd and "--setenv=KRANTO_UNIT=kranto-test.service" in cmd
    )
    assert "--setenv=UV_TOOL_DIR=/t" in cmd and "--setenv=KRANTO_UPDATE_FAIL=verify" in cmd
    i = cmd.index(str(home / "update" / "apply.py"))
    assert cmd[i - 1] == "/usr/bin/python3"
    assert cmd[i + 1 :] == [
        "--home",
        str(home),
        "--to",
        "v0.2.0",
        "--when",
        "now",
        "--port",
        "8766",
        "--unit",
        "kranto-test.service",
        "--keep",
        "3",
        "--ignore-pid",
        "4321",
    ]
    assert (home / "update" / "apply.py").read_text() == Path(apply.__file__).read_text()
    st = json.loads(apply.state_path(home).read_text())
    assert st["state"] == "requested"
    with pytest.raises(launch.LaunchError, match="already running"):
        launch.launch(home, "v0.2.0", run=run, which=lambda n: "/usr/bin/" + n, env={})


def test_launch_refuses_without_systemd_run(tmp_path):
    with pytest.raises(launch.LaunchError, match="systemd-run"):
        launch.launch(tmp_path, "v0.2.0", which=lambda n: None, env={})


def test_a_helper_that_died_reads_as_failed(tmp_path):
    apply.write_json(
        apply.state_path(tmp_path), {"state": "installing", "pid": 2**22 + 7, "log": "/x.log"}
    )
    st = check.apply_state(tmp_path)
    assert st["state"] == "failed" and "stopped while installing" in st["reason"]


def test_the_helper_needs_only_the_standard_library():
    src = Path(apply.__file__).read_text()
    imports = {
        line.split()[1].split(".")[0]
        for line in src.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    }
    assert not imports & {"kranto", "httpx", "yaml", "starlette"}, imports
    assert "from ." not in src


# -- kranto update's side -----------------------------------------------------------------------


def test_another_unit_has_its_own_pointer_and_passes_its_tool_dirs(tmp_path, monkeypatch):
    from kranto import launcher

    assert launcher.pointer_path(tmp_path).name == "home"
    monkeypatch.setattr(launcher, "UNIT", "kranto-test.service")
    monkeypatch.setenv("UV_TOOL_DIR", "/scratch/uv-tools")
    monkeypatch.setenv("UV_TOOL_BIN_DIR", "/scratch/bin")
    assert launcher.pointer_path(tmp_path).name == "home.kranto-test"
    text = launcher.render_unit(tmp_path / "kb", Path("/scratch/bin/kranto"), 8766, tmp_path)
    assert "Environment=UV_TOOL_DIR=/scratch/uv-tools\n" in text
    assert "Environment=UV_TOOL_BIN_DIR=/scratch/bin\n" in text
    assert "Environment=KRANTO_UNIT=kranto-test.service\n" in text
    assert "ExecStart=/scratch/bin/kranto serve --host 127.0.0.1 --port 8766" in text


def test_the_default_unit_is_unchanged(tmp_path, monkeypatch):
    from kranto import launcher

    for k in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR"):
        monkeypatch.delenv(k, raising=False)
    text = launcher.render_unit(tmp_path / "kb", tmp_path / ".local/bin/kranto", 8765, tmp_path)
    assert "UV_TOOL" not in text and "KRANTO_UNIT" not in text


def test_tags_are_normalised():
    from kranto.launcher import _tag

    assert _tag("0.2.0") == "v0.2.0"
    assert _tag("0.2.0rc1") == "v0.2.0-rc1"
    assert _tag("v0.2.0-rc2") == "v0.2.0-rc2"
    assert _tag("0.7.0.dev12") == _tag("v0.7.0-dev12") == "v0.7.0-dev12"


def test_tail_prints_each_step_until_final(tmp_path, monkeypatch):
    from kranto import launcher

    steps = iter(
        [
            {"state": "draining", "detail": "waiting for 1 build", "pid": None},
            {"state": "installing", "detail": "uv tool install 0.2.0", "pid": None},
            {"state": "rolled_back", "reason": "forced: verify", "detail": "x"},
        ]
    )
    seen = []

    def sleep(s):
        apply.write_json(apply.state_path(tmp_path), next(steps))

    apply.write_json(apply.state_path(tmp_path), {"state": "requested", "detail": "starting"})
    monkeypatch.setattr(launcher.time, "sleep", sleep)
    assert launcher.tail_update(tmp_path, out=seen.append) == "rolled_back"
    assert seen == [
        "  requested: starting",
        "  draining: waiting for 1 build",
        "  installing: uv tool install 0.2.0",
        "  rolled_back: x",
        "  reason: forced: verify",
    ]
    assert launcher.UPDATE_EXIT["rolled_back"] == 3
