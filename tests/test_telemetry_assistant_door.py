"""The assistant's usage events at the verbs' door (TEL, 2026-10-27), through the real app:
granting or raising the telemetry consent is a lock for the ``console`` and ``mcp`` tokens under
every ladder setting (prepared for the owner's press, never applied), turning it off is done
directly, and every call is counted by door, client, outcome, refusal kind and rung, the
prepared press again when it is confirmed or dismissed, and the page's own press by its route."""

from dataclasses import replace

import pytest

from kranto import config as config_mod
from kranto import telemetry
from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.core import verbs
from kranto.runtime import open_runtime
from kranto.telemetry import assistant as A
from kranto.telemetry import local
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, web_client
from .test_brb_mount import FakeApi
from .test_verbs import BASE, bare, bearer


@pytest.fixture
def rt(tmp_path, store, embedder, make_client, monkeypatch):
    brbfake.install(monkeypatch, FakeApi())
    (tmp_path / "kranto.yaml").write_text("llm:\n  models:\n    judge: m\n    reason: m\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(),
                 builds=BuildsConfig(enabled=True),
                 brb=BrbConfig(enabled=True, root=str(tmp_path / "tasks")))
    return open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))


@pytest.fixture
def app(rt):
    return create_app(rt, port=8765)

LADDERS = [None, {"kinds": {"outward": "do"}}, {"kinds": {"outward": "never"}},
           {"kinds": {"outward": "ask"}},
           {"kinds": {k: "do" for k in verbs.LADDER_KINDS if k not in verbs.LOCKS}}]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (local.DNT, local.ENV_MODE):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(local.ENV_ENDPOINT, "http://127.0.0.1:9/v1/logs")
    A._clear()
    yield
    A._clear()
    A._server_home = None
    telemetry.configure(None)


def counting(rt, mode="detailed"):
    telemetry.set_mode(rt.cfg.root, mode)
    telemetry.configure(rt.cfg.root)
    A._server_home = rt.cfg.root


def ladder(rt, value):
    rt.cfg = replace(rt.cfg, ask=config_mod.AskConfig(ladder=value or {}))


def rows():
    return [r for k, r, _h in A.records() if k == "verb"]


@pytest.mark.parametrize("door", ["console", "mcp"])
@pytest.mark.parametrize("lad", LADDERS)
@pytest.mark.parametrize("mode", ["basic", "detailed"])
def test_raising_consent_is_a_lock_under_every_ladder(rt, app, door, lad, mode):
    telemetry.set_mode(rt.cfg.root, "local")
    ladder(rt, lad)
    with bare(app) as web:
        r = web.post("/api/verbs/settings.telemetry", headers=bearer(door),
                     json={"fields": {"mode": mode}, "client": "claude"})
    out = r.json()
    assert r.status_code == 200 and out["prepared"] and not out["ok"], out
    assert "consent" in out["why"]
    assert local.effective(rt.cfg.root).mode == "local"          # nothing was applied


@pytest.mark.parametrize("choice", ["do", "never", "ask"])
def test_the_lock_cannot_be_turned_by_a_setting(choice):
    with pytest.raises(ValueError, match="cannot be changed"):
        verbs.check_ladder({"verbs": {"settings.telemetry": choice if choice != "ask" else
                                      "do"}})
    c = verbs.choice_for(None, verbs.get("settings.telemetry"))
    assert c.choice == "ask" and c.locked


def test_the_owners_press_applies_what_was_prepared(rt, app):
    telemetry.set_mode(rt.cfg.root, "local")
    with bare(app) as web:
        pid = web.post("/api/verbs/settings.telemetry", headers=bearer("console"),
                       json={"fields": {"mode": "detailed"}}).json()["prepared"]
        assert web.post(f"/api/prepared/{pid}/press", headers=bearer("console"),
                        json={}).status_code == 403
    assert local.effective(rt.cfg.root).mode == "local"
    with web_client(app, BASE) as page:
        assert page.post(f"/api/prepared/{pid}/press", json={}).status_code == 200
    assert local.effective(rt.cfg.root).mode == "detailed"


@pytest.mark.parametrize("door", ["console", "mcp"])
def test_turning_reports_off_is_done_directly(rt, app, door):
    telemetry.set_mode(rt.cfg.root, "detailed")
    with bare(app) as web:
        r = web.post("/api/verbs/telemetry.off", headers=bearer(door), json={})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert local.effective(rt.cfg.root).mode == "off"


def test_every_call_is_counted_with_its_outcome_and_rung(rt, app):
    counting(rt)
    with bare(app) as web:
        web.post("/api/verbs/topic.add", headers=bearer("console"),
                 json={"fields": {"name": "Tidal power", "description": "d."},
                       "client": "claude"})
        web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                 json={"fields": {"nope": 1}, "client": "codex"})
        web.post("/api/verbs/setup.provider", headers=bearer("console"), json={"client": "claude"})
        web.post("/api/verbs/setup.provider", headers=bearer("console"), json={})   # no name
        # (pressing a mode other than detailed would delete what waits: leaving detailed)
        pid = web.post("/api/verbs/settings.telemetry", headers=bearer("console"),
                       json={"fields": {"mode": "detailed"},
                             "client": "claude"}).json()["prepared"]
        pid2 = web.post("/api/verbs/settings.telemetry", headers=bearer("mcp"),
                        json={"fields": {"mode": "basic"}, "client": "codex"}).json()["prepared"]
    with web_client(app, BASE) as page:
        page.post(f"/api/prepared/{pid2}/dismiss", json={})
        page.post(f"/api/prepared/{pid}/press", json={})
    got = {(r["verb"], r["surface"], r["client"], r["outcome"], r.get("refusal"), r["rung"])
           for r in rows()}
    assert ("topic.add", "console", "claude-code", "ok", None, "do") in got
    assert ("topic.add", "mcp", "codex", "refused", "fields", "do") in got
    assert ("setup.provider", "console", "claude-code", "refused", "door", "lock") in got
    assert ("setup.provider", "console", "other", "refused", "door", "lock") in got
    assert ("settings.telemetry", "console", "claude-code", "prepared", None, "lock") in got
    assert ("settings.telemetry", "mcp", "codex", "dismissed", None, "lock") in got
    assert ("settings.telemetry", "console", "claude-code", "confirmed", None, "lock") in got
    # the press itself was the owner's: it ran inside the door, not as a page request
    assert not any(r["surface"] == "ui" and r["verb"] == "settings.telemetry" for r in rows())
    assert all(r["ms_p50"] >= 0 for r in rows())


def test_the_pages_own_press_is_counted_by_its_route(rt, app):
    counting(rt)
    with web_client(app, BASE) as page:
        r = page.post("/api/topics", json={"name": "Kelp farming", "description": "d."})
        assert r.status_code < 400, r.text
    got = [(r["verb"], r["surface"], r["client"], r["outcome"], r["rung"]) for r in rows()]
    assert ("topic.add", "ui", "none", "ok", "owner") in got


def test_nothing_is_counted_without_detailed(rt, app):
    counting(rt, "basic")
    with bare(app) as web:
        web.post("/api/verbs/topic.add", headers=bearer("console"),
                 json={"fields": {"name": "Tidal power", "description": "d."}})
    with web_client(app, BASE) as page:
        page.post("/api/topics", json={"name": "Kelp farming", "description": "d."})
    assert A.records() == []
