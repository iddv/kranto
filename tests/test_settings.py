"""Settings › Models and Settings › Spend, the judge's reply ceilings, an uncapped budget,
and the kranto home that ``kranto status`` finds without ``--home`` (the 2026-10-08
follow-ups). No test reaches a model or the network."""

import json
import os

import pytest
import yaml

from kranto import config as config_mod
from kranto import launcher, setup
from kranto.config import BudgetConfig, Config, ConfigError, IngestConfig, MapConfig
from kranto.intern import judge
from kranto.llm import TruncatedCompletion
from kranto.runtime import open_runtime
from kranto.sources import Item
from kranto.web.app import create_app

from .conftest import FIXED_NOW, chat_response, llm_config, web_client
from .test_kranto import FakeMachine, make_host

LIVE_LIKE = """\
llm:
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  cost_source: provider
  models:
    judge: anthropic/claude-haiku-4.5     # tier 1: judges every item
    reason: anthropic/claude-sonnet-5     # tier 2: scout, explain, idea cards
  pricing: {}
  timeout_seconds: 60

budget:
  # raised for the week of reading
  monthly_usd: 40.0
  alarm_fraction: 0.8

ingest:
  every_hours: 3
"""


def kept_fields() -> str:
    return json.dumps({"kind": "beat", "summary": "s", "why_it_matters": "w",
                       "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9})


def item() -> Item:
    return Item(id="1", title="t", body="b", url="https://example.org/1",
                published_at=FIXED_NOW)


# -- the judge's ceilings and one retry ------------------------------------------------------


def test_the_judge_has_room_and_a_cut_off_reply_is_asked_again_with_twice_as_much(
        make_client, store):
    replies = [chat_response('{"kind": "beat", "summ', completion=3000, finish_reason="length"),
               chat_response(kept_fields(), finish_reason="stop")]
    client = make_client(lambda body: replies.pop(0))
    verdict = judge(client, item(), source_label="hn", topics=["x"], threshold=0.2)
    assert verdict.outcome == "contributed"
    sent = [r["max_tokens"] for r in client.fake.requests]
    assert sent == [config_mod.MAX_TOKENS["judge"], 2 * config_mod.MAX_TOKENS["judge"]]
    assert sent[0] > 800                       # cut 6 live replies off on 2026-10-07
    rows = store.query("SELECT status, error FROM llm_calls ORDER BY id")
    assert [r["status"] for r in rows] == ["error", "ok"]  # both recorded, both paid for
    assert f"cut off at max_tokens={sent[0]}" in rows[0]["error"]


def test_the_judge_tier_ceilings_fit_haiku_5_5s_reasoning():
    # 2026-10-08, Haiku 5.5 with its reasoning counted: screen p99 517 and max 620 (128
    # replays), cluster names up to 372, judge replies up to 1418. The first ask has room.
    measured = {"screen": 620, "name": 372, "judge": 1418, "judge_gathered": 1418}
    for call, longest in measured.items():
        assert config_mod.MAX_TOKENS[call] >= 1.5 * longest, call


def test_a_reply_cut_off_twice_is_an_error_for_the_item(make_client):
    client = make_client(lambda body: chat_response("{", finish_reason="length"))
    with pytest.raises(TruncatedCompletion):
        judge(client, item(), source_label="hn", topics=["x"], threshold=0.2)
    assert len(client.fake.requests) == 2


def test_calls_that_do_not_ask_are_not_retried(make_client):
    client = make_client(lambda body: chat_response("{", finish_reason="length"))
    with pytest.raises(TruncatedCompletion):
        client.complete(tier="reason", purpose="card", prompt_version="v",
                        messages=[{"role": "user", "content": "x"}], max_tokens=50)
    assert len(client.fake.requests) == 1


def test_ceilings_are_configurable(make_client, tmp_path):
    client = make_client(lambda body: chat_response(kept_fields()),
                         max_tokens={"judge": 3000})
    judge(client, item(), source_label="hn", topics=["x"], threshold=0.2)
    assert client.fake.requests[0]["max_tokens"] == 3000
    assert client.max_tokens("screen") == config_mod.MAX_TOKENS["screen"]
    config_mod.init_workspace(tmp_path)
    path = tmp_path / "kranto.yaml"
    text = path.read_text()
    path.write_text(text.replace("  max_tokens: {}", "  max_tokens: {judge: 2500}"))
    assert config_mod.load(tmp_path, dotenv=False).llm.max_tokens == {"judge": 2500}
    for bad in ("{judgment: 2500}", "{judge: 5}", "{judge: true}", "[2500]"):
        path.write_text(text.replace("  max_tokens: {}", f"  max_tokens: {bad}"))
        with pytest.raises(ConfigError, match="max_tokens"):
            config_mod.load(tmp_path, dotenv=False)


def test_the_default_judge_is_haiku_5_5_through_the_router(tmp_path):
    config_mod.init_workspace(tmp_path)
    cfg = config_mod.load(tmp_path, dotenv=False)
    assert cfg.llm.models["judge"] == "anthropic/claude-haiku-5.5"


# -- no cap ------------------------------------------------------------------------------------


def test_a_budget_of_null_is_no_cap(make_client, store, tmp_path):
    client = make_client(lambda body: chat_response("ok", cost=5.0), budget=None)
    for _ in range(3):
        client.complete(tier="judge", purpose="judge", prompt_version="v",
                        messages=[{"role": "user", "content": "x"}])
    assert store.month_spend() == pytest.approx(15.0)
    assert client.remaining_budget() == float("inf")
    assert not store.query("SELECT 1 FROM messages WHERE kind = 'alarm'")
    budget = BudgetConfig(None)
    assert budget.of() == "(no cap)" and not budget.alarm(1e9)
    assert BudgetConfig(40.0).of() == "of $40.00" and BudgetConfig(40.0).alarm(32.0)
    config_mod.init_workspace(tmp_path)
    path = tmp_path / "kranto.yaml"
    # a new workspace has no cap (#8: a $10 default stopped gathering mid-month)
    assert "  monthly_usd: null" in path.read_text()
    assert config_mod.load(tmp_path, dotenv=False).budget.monthly_usd is None
    for bad in ("-1", "true", '"ten"'):
        path.write_text(path.read_text().replace("monthly_usd: null", f"monthly_usd: {bad}"))
        with pytest.raises(ConfigError, match="monthly_usd"):
            config_mod.load(tmp_path, dotenv=False)
        path.write_text(path.read_text().replace(f"monthly_usd: {bad}", "monthly_usd: null"))


# -- the YAML, edited as text -----------------------------------------------------------------


def test_a_nested_value_is_set_with_its_comment_kept(tmp_path):
    out = setup.set_yaml_nested(LIVE_LIKE, "llm", "models", "judge", "anthropic/claude-haiku-5.5")
    assert '    judge: "anthropic/claude-haiku-5.5"     # tier 1: judges every item\n' in out
    assert "    reason: anthropic/claude-sonnet-5     # tier 2" in out
    assert out.replace('"anthropic/claude-haiku-5.5"', "anthropic/claude-haiku-4.5") == LIVE_LIKE
    # a key not there yet, a flow-style empty mapping, a missing sub-mapping and section
    out = setup.set_yaml_nested(LIVE_LIKE, "llm", "models", "extra", "m")
    assert yaml.safe_load(out)["llm"]["models"] == {
        "judge": "anthropic/claude-haiku-4.5", "reason": "anthropic/claude-sonnet-5",
        "extra": "m"}
    out = setup.set_yaml_nested(LIVE_LIKE, "llm", "pricing", "judge", 1)
    assert yaml.safe_load(out)["llm"]["pricing"] == {"judge": 1}
    out = setup.set_yaml_nested(LIVE_LIKE, "ingest", "by_kind", "rss", 2)
    assert yaml.safe_load(out)["ingest"] == {"every_hours": 3, "by_kind": {"rss": 2}}
    out = setup.set_yaml_nested(LIVE_LIKE, "notify", "x", "y", None)
    assert yaml.safe_load(out)["notify"] == {"x": {"y": None}}
    path = tmp_path / "kranto.yaml"
    path.write_text(LIVE_LIKE)
    setup.write_config_values(path, {("budget", "monthly_usd"): None})
    assert "  monthly_usd: null\n" in path.read_text()
    assert "# raised for the week of reading" in path.read_text()


# -- the settings API -------------------------------------------------------------------------


@pytest.fixture
def served(tmp_path, store, embedder, make_client):
    (tmp_path / "kranto.yaml").write_text(LIVE_LIKE)
    cfg = Config(root=tmp_path, llm=llm_config(models={
        "judge": "anthropic/claude-haiku-4.5", "reason": "anthropic/claude-sonnet-5"}),
        budget=BudgetConfig(monthly_usd=40.0), ingest=IngestConfig(), map=MapConfig())
    client = make_client(lambda body: chat_response("{}"),
                         models=dict(cfg.llm.models), budget=40.0)
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        yield rt, web, tmp_path / "kranto.yaml"


def test_models_round_trip(served):
    rt, web, path = served
    m = web.get("/api/settings/models").json()
    assert [(r["role"], r["model"]) for r in m["roles"]] == [
        ("judge", "anthropic/claude-haiku-4.5"), ("reason", "anthropic/claude-sonnet-5")]
    assert m["routed"] is True and m["config"] == "kranto.yaml"
    assert "judge" in m["roles"][0]["calls"] and m["roles"][0]["max_tokens"]["judge"] == 3000
    r = web.post("/api/settings/models", json={"role": "judge",
                                               "model": "anthropic/claude-haiku-5.5"})
    assert r.status_code == 200, r.text
    assert r.json()["roles"][0]["model"] == "anthropic/claude-haiku-5.5"
    # written to the file (comment kept), loaded back, and used from the next call on
    assert "judge: \"anthropic/claude-haiku-5.5\"     # tier 1" in path.read_text()
    assert config_mod.load(path.parent, dotenv=False).llm.models["judge"] == \
        "anthropic/claude-haiku-5.5"
    rt.llm.complete(tier="judge", purpose="judge", prompt_version="v",
                    messages=[{"role": "user", "content": "x"}])
    assert rt.llm.fake.requests[-1]["model"] == "anthropic/claude-haiku-5.5"
    assert web.get("/api/settings/models").json()["roles"][0]["model"] == \
        "anthropic/claude-haiku-5.5"
    # the judge's gate goes with it, in one write
    judge = web.get("/api/settings/models").json()["roles"][0]
    assert judge["gate"] == 0.03 and "Haiku 5.5" in judge["gate_note"]   # the default
    r = web.post("/api/settings/models", json={"role": "judge", "gate": 0.05,
                                               "model": "anthropic/claude-haiku-5.5"})
    assert r.status_code == 200 and r.json()["roles"][0]["gate"] == 0.05
    assert config_mod.load(path.parent, dotenv=False).ingest.signal_threshold == 0.05
    assert rt.cfg.ingest.signal_threshold == 0.05
    for bad in ({"role": "reason", "model": "m", "gate": 0.1},
                {"role": "judge", "model": "m", "gate": 0},
                {"role": "judge", "model": "m", "gate": 1.5},
                {"role": "judge", "model": "m", "gate": "0.1"}):
        assert web.post("/api/settings/models", json=bad).status_code == 400
    assert config_mod.load(path.parent, dotenv=False).llm.models["reason"] == \
        "anthropic/claude-sonnet-5"


@pytest.mark.parametrize("body, why", [
    ({"role": "scout", "model": "m"}, "no such role"),
    ({"role": "judge", "model": ""}, "a model is a name"),
    ({"role": "judge", "model": "x\ny: 1"}, "a model is a name"),
    ({"role": "judge", "model": "a b"}, "a model is a name"),
])
def test_models_refuses_what_it_cannot_write(served, body, why):
    _, web, path = served
    before = path.read_text()
    r = web.post("/api/settings/models", json=body)
    assert r.status_code == 400 and why in r.json()["error"]
    assert path.read_text() == before


def test_models_needs_the_page_origin(served):
    _, web, path = served
    before = path.read_text()
    r = web.post("/api/settings/models", json={"role": "judge", "model": "m"},
                 headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and path.read_text() == before


def test_spend_round_trip_with_no_cap(served):
    rt, web, path = served
    s = web.get("/api/settings/spend").json()
    assert s["monthly_usd"] == 40.0 and s["spent_usd"] == 0 and s["deep_dive"]["daily_usd"] == 0.05
    r = web.post("/api/settings/spend", json={"monthly_usd": None})
    assert r.status_code == 200, r.text
    assert r.json()["monthly_usd"] is None
    assert "  monthly_usd: null\n" in path.read_text()
    assert config_mod.load(path.parent, dotenv=False).budget.monthly_usd is None
    assert rt.llm.budget.monthly_usd is None and rt.cfg.budget.monthly_usd is None
    assert web.get("/api/status").json()["budget_usd"] is None
    r = web.post("/api/settings/spend", json={"monthly_usd": 25, "deep_dive_daily_usd": None})
    assert r.json()["monthly_usd"] == 25.0 and r.json()["deep_dive"]["daily_usd"] is None
    cfg = config_mod.load(path.parent, dotenv=False)
    assert cfg.budget.monthly_usd == 25.0 and cfg.deep_dive.daily_usd is None
    assert rt.llm.budget.monthly_usd == 25.0
    for bad in ({"monthly_usd": -1}, {"monthly_usd": "10"}, {"monthly_usd": True}, {}):
        assert web.post("/api/settings/spend", json=bad).status_code == 400
    assert config_mod.load(path.parent, dotenv=False).budget.monthly_usd == 25.0


def test_reading_round_trip(served):
    """Settings › Watching › Reading (UP #3): how often sources are read and whether deep dives
    run, once set by hand only, written with a check; the file keeps its comments."""
    rt, web, path = served
    s = web.get("/api/settings/reading").json()
    assert s["every_hours_effect"] == "restart" and s["deep_dive_effect"] == "run"
    comments = [ln for ln in path.read_text().splitlines() if ln.lstrip().startswith("#")]
    r = web.post("/api/settings/reading", json={"every_hours": 6, "deep_dive_enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["every_hours"] == 6 and r.json()["deep_dive"]["enabled"] is True
    cfg = config_mod.load(path.parent, dotenv=False)
    assert cfg.ingest.every_hours == 6 and cfg.deep_dive.enabled is True
    assert rt.cfg.ingest.every_hours == 6 and rt.cfg.deep_dive.enabled is True
    assert [ln for ln in path.read_text().splitlines() if ln.lstrip().startswith("#")] == comments
    assert web.post("/api/settings/reading", json={"every_hours": 0.5}).json()["every_hours"] == 0.5
    for bad in ({"every_hours": 0}, {"every_hours": 200}, {"every_hours": "6"},
                {"every_hours": True}, {"deep_dive_enabled": "yes"}, {}):
        assert web.post("/api/settings/reading", json=bad).status_code == 400, bad
    assert config_mod.load(path.parent, dotenv=False).ingest.every_hours == 0.5
    before = path.read_text()
    r = web.post("/api/settings/reading", json={"every_hours": 2},
                 headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and path.read_text() == before


# -- the kranto home, recorded -----------------------------------------------------------------


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    home = tmp_path / "u"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KRANTO_LOOP_HOME", raising=False)
    monkeypatch.delenv("KRANTO_HOME", raising=False)
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": False)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    return home


def test_an_adopted_home_is_found_without_home(user_home, capsys, monkeypatch):
    from kranto import legacy

    kb = user_home / legacy.WORKSPACE.removeprefix("~/")
    config_mod.init_workspace(kb)
    (user_home / legacy.LOOP_HOME.removeprefix("~/")).mkdir()
    (user_home / "tasks").mkdir()
    host = make_host(user_home, FakeMachine(active={launcher.OLD_UNIT: "active"}))
    assert launcher.kranto_home(None, host) == (user_home / ".kranto").resolve()
    assert launcher.main(["adopt", "--dry-run"], host) == 0
    assert "record" in capsys.readouterr().out
    assert not launcher.pointer_path(user_home).exists()       # a dry run writes nothing
    assert launcher.main(["adopt", "--yes", "--no-service"], host) == 0
    assert launcher.pointer_path(user_home).read_text().strip() == str(kb.resolve())
    assert launcher.kranto_home(None, host) == kb.resolve()
    capsys.readouterr()
    launcher.main(["status"], host)
    out = capsys.readouterr().out
    assert f"home       {kb.resolve()} (kranto.yaml)" in out and "none yet" not in out
    # --home and $KRANTO_HOME still win
    other = user_home / "other"
    assert launcher.kranto_home(str(other), host) == other.resolve()
    monkeypatch.setenv("KRANTO_HOME", str(other))
    assert launcher.kranto_home(None, host) == other.resolve()


def test_without_a_record_the_units_home_is_used(user_home):
    host = make_host(user_home)
    unit = host.unit_dir / launcher.UNIT
    unit.parent.mkdir(parents=True)
    unit.write_text(launcher.render_unit(user_home / "kranto-kb", user_home / ".local/bin/kranto",
                                      8765, user_home))
    assert launcher.kranto_home(None, host) == (user_home / "kranto-kb").resolve()


def test_kranto_up_records_its_home(user_home, monkeypatch):
    monkeypatch.setattr(launcher, "_wait_up", lambda host, port, seconds: True)
    host = make_host(user_home, FakeMachine())
    home = user_home / "somewhere"
    assert launcher.main(["--home", str(home), "up", "--no-browser"], host) == 0
    assert launcher.pointer_path(user_home).read_text().strip() == str(home.resolve())
    assert launcher.kranto_home(None, host) == home.resolve()
    assert os.environ.get("KRANTO_HOME") is None
