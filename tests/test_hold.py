"""The update's drain (section 4.2): ``POST /api/hold`` starts no job and holds
every lane, whose next tick then starts nothing long; ``DELETE`` undoes it; ``stop_builds``
asks each lane that can to stop what it runs. Kranto runs no loop lane since the cut (CUT), so
the lane here is a stand-in for any second lane: no the page, no model."""

from __future__ import annotations

import threading
import time

from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.scheduler import Job, Scheduler
from kranto.web.app import create_app

from .conftest import llm_config, web_client


class FakeLane:
    """A second scheduler lane: ``record`` gets whether each tick ran held."""

    name = "loop"

    def __init__(self, home, record):
        self.home, self.record = home, record
        self.hold: str | None = None
        self.ticks = 0
        self.last_result: dict | None = None

    def tick(self) -> None:
        self.record.append(bool(self.hold))
        self.ticks += 1
        self.last_result = {"watched": 0, "paused": True} if self.hold else {"watched": 0}

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.tick()
            stop.wait(60)

    def request_stop(self) -> None:
        pass

    def stop_builds(self) -> list[str]:
        return ["idea-1"]

    def status(self) -> dict:
        return {"ticks": self.ticks, "held": self.hold, "last_result": self.last_result}


def lane_of(tmp_path, record):
    return FakeLane(tmp_path / "loop", record)


def wait_for(cond, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_a_hold_starts_no_job_and_holds_the_lane(store, tmp_path):
    ran, record = [], []
    lane = lane_of(tmp_path, record)
    sched = Scheduler(store, [Job("ingest", 1, lambda: ran.append(1))], lanes=[lane])
    hold = sched.set_hold("update")
    assert hold["reason"] == "update" and lane.hold == "update"
    assert sched.run_due() == [] and ran == []
    assert sched.trigger("ingest") is False
    lane.tick()
    assert record == [True]                              # the tick ran with the stop flag
    assert lane.status()["held"] == "update"
    assert lane.status()["last_result"] == {"watched": 0, "paused": True}
    assert sched.release_hold() is True and sched.release_hold() is False
    lane.tick()
    assert record == [True, False] and lane.status()["held"] is None
    assert sched.run_due() == ["ingest"]


def test_stop_builds_asks_the_lane_and_keeps_it(store, tmp_path):
    lane = lane_of(tmp_path, [])
    sched = Scheduler(store, [], lanes=[lane])
    hold = sched.set_hold("update", stop_builds=True)
    assert hold["stopped"] == ["idea-1"] and lane.hold == "update"


def test_hold_over_the_api(tmp_path, store, embedder, make_client):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    record = []
    lane = lane_of(tmp_path, record)
    sched = Scheduler(store, [], tick_seconds=60, lanes=[lane])
    with web_client(create_app(rt, sched), "http://127.0.0.1:8765") as web:
        assert wait_for(lambda: lane.status()["ticks"] >= 1)
        r = web.post("/api/hold", json={"reason": "update to 0.2.0"})
        assert r.status_code == 200 and r.json()["hold"]["reason"] == "update to 0.2.0"
        status = web.get("/api/status").json()
        assert status["hold"]["reason"] == "update to 0.2.0"
        assert status["lanes"]["loop"]["held"] == "update to 0.2.0"
        assert status["update"]["state"] == "idle"
        lane.tick()
        assert record[-1] is True
        assert web.get("/api/update").json()["busy"]["hold"]["reason"] == "update to 0.2.0"
        r = web.delete("/api/hold")
        assert r.status_code == 200 and r.json()["released"] is True
        assert web.get("/api/status").json()["hold"] is None
        lane.tick()
        assert record[-1] is False


def test_a_hold_needs_the_same_origin(tmp_path, store, embedder, make_client):
    from starlette.testclient import TestClient

    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    sched = Scheduler(store, [], tick_seconds=60)
    client = TestClient(create_app(rt, sched), base_url="http://127.0.0.1:8765")
    r = client.post("/api/hold", json={"reason": "x"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and sched.hold is None


def test_restart_to_update_over_the_api(tmp_path, store, embedder, make_client, monkeypatch):
    from kranto.update import apply, check, launch

    from .test_update_check import write_set

    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    started = []
    monkeypatch.setattr(launch, "launch", lambda home, to, **kw: started.append((to, kw)) or
                        {"unit": "kranto-update", "to": to, "when": kw["when"]})
    with web_client(create_app(rt, None, port=8765), "http://127.0.0.1:8765") as web:
        monkeypatch.setattr(check, "can_apply", lambda: False)
        r = web.post("/api/update", json={"to": "v0.2.0"})
        assert r.status_code == 409 and "cannot restart itself" in r.json()["error"]
        monkeypatch.setattr(check, "can_apply", lambda: True)
        assert web.post("/api/update", json={}).status_code == 409        # nothing staged
        assert web.post("/api/update", json={"to": "0.2"}).status_code == 400
        assert web.post("/api/update", json={"to": "v0.2.0", "when": "soon"}).status_code == 400
        write_set(apply.releases_dir(tmp_path) / "v0.2.0", "0.2.0")
        r = web.post("/api/update", json={"to": "v0.2.0", "when": "now"})
        assert r.status_code == 202 and r.json()["state"] == "requested"
        assert started[-1][0] == "v0.2.0" and started[-1][1]["when"] == "now"
        assert started[-1][1]["port"] == 8765
        # a nightly build's staged set (Restart to update on the nightly line)
        write_set(apply.releases_dir(tmp_path) / "v0.3.0-dev2", "0.3.0.dev2")
        r = web.post("/api/update", json={"to": "v0.3.0-dev2"})
        assert r.status_code == 202 and started[-1][0] == "v0.3.0-dev2"
        (apply.releases_dir(tmp_path) / "v0.2.0" / "SHA256SUMS").write_text("x  y\n")
        r = web.post("/api/update", json={"to": "v0.2.0"})
        assert r.status_code == 409 and "cannot be installed" in r.json()["error"]
        # cancel only while it waits; roll back only with a previous version
        assert web.post("/api/update/cancel", json={}).status_code == 409
        apply.write_json(apply.state_path(tmp_path), {"state": "draining", "pid": None})
        assert web.post("/api/update/cancel", json={}).status_code == 200
        assert apply.cancel_path(tmp_path).exists()
        assert web.post("/api/update/rollback", json={}).status_code == 409
        apply.write_json(apply.previous_path(tmp_path), {"kind": "git", "commits": {}})
        assert web.post("/api/update/rollback", json={}).status_code == 202
        assert started[-1][0] == "previous"


def test_update_settings_write_the_config(tmp_path, store, embedder, make_client):
    (tmp_path / "kranto.yaml").write_text("# mine\nllm: {}\nupdate:\n  repo: iddv/kranto\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    with web_client(create_app(rt, None), "http://127.0.0.1:8765") as web:
        r = web.post("/api/update/settings", json={"auto": "idle", "channel": "nightly",
                                                   "quiet_window": "02:00-05:00"})
        assert r.status_code == 200, r.text
        s = r.json()["settings"]
        assert (s["auto"], s["channel"], s["quiet_window"]) == ("idle", "nightly",
                                                                "02:00-05:00")
        text = (tmp_path / "kranto.yaml").read_text()
        assert text.startswith("# mine\n") and 'auto: "idle"' in text
        assert web.post("/api/update/settings", json={"channel": "beta"}).status_code == 400
        assert web.post("/api/update/settings", json={}).status_code == 400
        assert "channel: \"nightly\"" in (tmp_path / "kranto.yaml").read_text()
