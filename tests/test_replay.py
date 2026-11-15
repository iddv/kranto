"""The reply schemas beside the prompts and ``afk provider replay`` (PR-E, 6),
against a fake Claude API on loopback: what each variant sends, the agreement it reports,
the cap checked before anything is sent, and that every call is recorded."""

from __future__ import annotations

import json
import secrets
from dataclasses import replace

import pytest

from kranto import config as config_mod
from kranto import prompts
from kranto.config import AnthropicConfig, BudgetConfig, Config, IngestConfig, MapConfig
from kranto.llm import LLMClient
from kranto.providers import replay

from .conftest import llm_config
from .fake_anthropic import FakeAnthropic, message

KEPT = json.dumps({"skip": False, "kind": "mild_signal", "summary": "s", "why_it_matters": "w",
                   "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9})


@pytest.fixture
def api():
    fake = FakeAnthropic()
    yield fake
    fake.close()


def record(store, purpose, reply_text, i):
    body = {"model": "anthropic/claude-haiku-5.5", "max_tokens": 900, "temperature": 0.2,
            "messages": [{"role": "system", "content": f"{purpose} prompt"},
                         {"role": "user", "content": f"item {i}"}], "usage": {"include": True}}
    resp = {"model": "anthropic/claude-haiku-5.5",
            "choices": [{"message": {"content": reply_text}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 200, "cost": 0.0003}}
    store.insert("llm_calls", {"purpose": purpose, "tier": "judge", "model": body["model"],
                               "prompt_version": "v1", "request": json.dumps(body),
                               "response": json.dumps(resp), "status": "ok", "attempts": 1,
                               "prompt_tokens": 2000, "completion_tokens": 200,
                               "cost_usd": 0.0003, "created_at": "2026-09-24T10:00:00Z"})


def test_each_stage_has_a_closed_schema_its_reader_accepts():
    for name in ("screen", "judge", "name"):
        s = prompts.schema(name)
        assert s["type"] == "object" and s["additionalProperties"] is False
    judge = prompts.schema("judge")
    assert judge["properties"]["children"]["items"]["additionalProperties"] is False
    assert prompts.schema("card") is None


def test_the_stages_pass_their_schema_and_only_a_structured_provider_sends_it(make_client):
    from kranto.intern import screen
    from kranto.sources import Item

    from .conftest import chat_response
    client = make_client(lambda body: chat_response('{"pass": true, "reason": "ok"}'))
    screen(client, Item(id="1", title="t", body="b", url="https://example.org/x"),
           source_label="s", topics=["t"])
    assert "output_config" not in client.fake.requests[0]            # OpenRouter: never


def test_replay_asks_three_ways_and_says_what_agrees(api, store):
    key = "test-anthropic-" + secrets.token_hex(12)
    for i in range(3):
        record(store, "screen", '{"pass": false, "reason": "no"}', i)
    record(store, "judge", KEPT, 9)
    # every replayed screen passes (one disagreement each), the judge keeps the item again
    for _variant in replay.VARIANTS:
        for _ in range(3):
            api.reply(200, message('{"pass": true, "reason": "yes"}', cache_read=1200))
        api.reply(200, message(KEPT, cache_read=3000, output_tokens=300))
    cfg = Config(root=store.path.parent if store.path else None,
                 llm=llm_config(anthropic=AnthropicConfig(base_url=api.url)),
                 budget=BudgetConfig(monthly_usd=None), ingest=IngestConfig(), map=MapConfig())
    samples = replay.sample(store, 24, 16)
    assert [s.purpose for s in samples] == ["screen"] * 3 + ["judge"]
    assert samples[0].messages[0] == {"role": "system", "content": "screen prompt"}
    assert replay.estimate(samples, "claude-haiku-5-5") < 0.05

    def client_for(llm_cfg):
        return LLMClient(store, llm_cfg, cfg.budget, api_key=key)
    out = replay.summary(replay.run(cfg, store, samples, client_for=client_for))
    posts = api.posts
    assert len(posts) == 12 and all("temperature" not in p for p in posts)
    plain, cached, structured = posts[0:4], posts[4:8], posts[8:12]
    assert "cache_control" not in plain[0]["system"][0]
    assert cached[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "output_config" not in cached[0]
    assert structured[0]["output_config"] == {"format": {"type": "json_schema",
                                                         "schema": prompts.schema("screen")},
                                              "effort": "low"}
    assert structured[3]["output_config"] == {"format": {"type": "json_schema",
                                                         "schema": prompts.schema("judge")}}
    assert all(p["model"] == "claude-haiku-5-5" for p in posts)
    v = out["variants"]
    assert v["cache"]["screens_agree"] == [0, 3] and v["cache"]["judges_agree"] == [1, 1]
    assert v["structured"]["cache_read_per_call"] == pytest.approx((1200 * 3 + 3000) / 4)
    assert v["plain"]["usd_per_call"] > 0 and v["plain"]["errors"] == 0
    rows = store.query("SELECT purpose, run_uuid, provider FROM llm_calls WHERE purpose LIKE "
                       "'replay_%'")
    assert len(rows) == 12 and {r["provider"] for r in rows} == {"anthropic"}
    assert len({r["run_uuid"] for r in rows}) == 1


def test_the_cli_refuses_over_the_cap_before_sending(api, tmp_path, monkeypatch, capsys):
    from kranto import cli
    from kranto.store import Store
    config_mod.init_workspace(tmp_path)
    s = Store.open(config_mod.load(tmp_path, dotenv=False).db_path)
    for i in range(10):
        record(s, "judge", KEPT, i)
    s.close()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-" + secrets.token_hex(12))
    code = cli.main(["-w", str(tmp_path), "provider", "replay", "--max-usd", "0.0001", "--yes"])
    assert code == 2 and "over the cap" in capsys.readouterr().err
    assert api.requests == []


def test_variant_configs_move_the_models_to_the_apis_names():
    cfg = Config(root=None, llm=replace(llm_config(), models={
        "judge": "anthropic/claude-haiku-5.5", "reason": "anthropic/claude-sonnet-5.5"}),
        budget=BudgetConfig(monthly_usd=None), ingest=IngestConfig(), map=MapConfig())
    for v in replay.VARIANTS:
        llm = replay.variant_config(cfg, v)
        assert llm.provider == "anthropic" and llm.models["judge"] == "claude-haiku-5-5"
    assert replay.variant_config(cfg, "plain").anthropic.cache is False
    assert replay.variant_config(cfg, "structured").anthropic.effort == {"screen": "low"}
