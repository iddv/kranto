"""The provider seam (PR-A): today's endpoint byte for byte, the price table,
migration 25, per-tier providers, and a provider's pause."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from kranto import pricing
from kranto.config import ConfigError, ModelPrice, _parse_llm
from kranto.llm import (
    WATCH_PAUSE_KEY,
    Paused,
    ProviderPaused,
    watch_pause,
)
from kranto.providers.base import ProviderError, Reply

from .conftest import FIXED_NOW, chat_response

MSG = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]


def call(client, tier="judge", **kw):
    return client.complete(tier=tier, purpose=tier, messages=MSG, prompt_version="t1", **kw)


# -- today's request, unchanged ------------------------------------------------------------

def test_the_request_body_is_todays_for_both_tiers(make_client):
    client = make_client(lambda body: chat_response("ok"))
    call(client, "judge", max_tokens=300, temperature=0.0)
    call(client, "reason", max_tokens=900, temperature=0.4)
    assert client.fake.requests == [
        {"model": "judge-model", "messages": MSG, "max_tokens": 300, "temperature": 0.0,
         "usage": {"include": True}},
        {"model": "reason-model", "messages": MSG, "max_tokens": 900, "temperature": 0.4,
         "usage": {"include": True}},
    ]


def test_a_table_priced_endpoint_sends_no_usage_flag(make_client):
    client = make_client(lambda body: chat_response("ok", cost=None), cost_source="table",
                         pricing={"judge-model": ModelPrice(1.0, 2.0)})
    call(client, temperature=0.2, max_tokens=50)
    assert client.fake.requests == [
        {"model": "judge-model", "messages": MSG, "max_tokens": 50, "temperature": 0.2}]


def test_the_request_goes_to_the_endpoint_with_the_key_as_bearer(store):
    from kranto.config import BudgetConfig
    from kranto.llm import LLMClient

    from .conftest import llm_config
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("authorization"),
                     request.headers.get("x-title")))
        return chat_response("ok")
    client = LLMClient(store, llm_config(), BudgetConfig(monthly_usd=None), api_key="the-key",
                       transport=httpx.MockTransport(handler))
    call(client)
    assert seen == [("https://llm.test/v1/chat/completions", "Bearer the-key", "kranto")]


def test_anthropics_own_endpoint_gets_no_temperature(make_client):
    client = make_client(lambda body: chat_response("ok"),
                         base_url="https://api.anthropic.com/v1", cost_source="table",
                         pricing={"judge-model": ModelPrice(1.0, 2.0)})
    call(client, temperature=0.3)
    assert "temperature" not in client.fake.requests[0]


def test_each_row_says_which_provider_served_it(make_client, store):
    client = make_client(lambda body: chat_response("ok"))
    call(client)
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["provider"] == "openai_compat"
    assert row["cache_read_tokens"] == 0 and row["cache_write_tokens"] == 0
    assert row["equiv_usd"] is None


# -- config ----------------------------------------------------------------------------------

BASE = {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
        "models": {"judge": "a/j", "reason": "a/r"}}


def test_no_provider_is_todays_endpoint():
    cfg = _parse_llm(dict(BASE))
    assert cfg.provider is None and cfg.provider_name == "openai_compat"
    assert cfg.providers_in_use() == ["openai_compat"]
    assert cfg.model_for("judge") == "a/j"


def test_a_tier_can_use_another_provider_and_model():
    cfg = _parse_llm({**BASE, "provider": "openrouter",
                      "tiers": {"reason": {"provider": "openai_compat", "model": "x"}}})
    assert cfg.provider_for("judge") == "openrouter"
    assert cfg.provider_for("reason") == "openai_compat"
    assert cfg.model_for("reason") == "x" and cfg.model_for("judge") == "a/j"
    assert cfg.providers_in_use() == ["openrouter", "openai_compat"]


@pytest.mark.parametrize("raw", [
    {"provider": "nope"},
    {"tiers": {"other": {"provider": "openrouter", "model": "m"}}},
    {"tiers": {"reason": {"provider": "nope", "model": "m"}}},
    {"tiers": {"reason": {"provider": "openrouter"}}},
    {"tiers": {"reason": {"provider": "openrouter", "model": "m", "extra": 1}}},
    {"tiers": ["reason"]},
])
def test_bad_provider_settings_are_refused(raw):
    with pytest.raises(ConfigError):
        _parse_llm({**BASE, **raw})


def test_a_tier_override_sends_its_own_model(make_client):
    client = make_client(lambda body: chat_response("ok"),
                         tiers={"reason": {"provider": "openrouter", "model": "other-model"}})
    call(client, "reason")
    assert client.fake.requests[0]["model"] == "other-model"


# -- the price table -----------------------------------------------------------------------

def test_list_prices_worked_examples():
    # 100k in (Haiku 5.5's long-prompt line is above it) and 100k out at list prices.
    for model, total in [("claude-haiku-5-5", 0.06), ("claude-sonnet-5-5", 1.2),
                         ("claude-opus-5-5", 2.4), ("claude-fable-5-1", 6.0),
                         ("claude-sonnet-5", 1.2), ("claude-haiku-4-5-20251001", 0.6)]:
        assert pricing.cost(model, input_tokens=100_000, output_tokens=100_000) == \
            pytest.approx(total)


def test_a_judge_with_a_cached_system_prompt_costs_what_the_design_says():
    # 3.1: 5,081 input of which about 4,000 is a cache read, 670 output.
    usd = pricing.cost("claude-haiku-5-5", input_tokens=5081, output_tokens=670,
                       cache_read_tokens=4000)
    assert usd == pytest.approx((1081 * 0.10 + 4000 * 0.01 + 670 * 0.50) / 1e6)
    assert usd == pytest.approx(0.000483, abs=2e-6)


def test_cache_writes_cost_a_quarter_more_than_input():
    usd = pricing.cost("claude-sonnet-5-5", input_tokens=2000, output_tokens=0,
                       cache_write_tokens=2000)
    assert usd == pytest.approx(2000 * 2.50 / 1e6)


def test_haiku_5_5_prompts_over_100k_pay_the_long_prompt_price():
    usd = pricing.cost("claude-haiku-5-5", input_tokens=100_001, output_tokens=1000,
                       cache_read_tokens=50_000)
    assert usd == pytest.approx((50_001 * 0.50 + 50_000 * 0.05 + 1000 * 2.50) / 1e6)


def test_batch_halves_and_an_unknown_model_has_no_price():
    full = pricing.cost("claude-opus-5-5", input_tokens=1000, output_tokens=1000)
    assert pricing.cost("claude-opus-5-5", input_tokens=1000, output_tokens=1000,
                        batch=True) == pytest.approx(full / 2)
    assert pricing.cost("some-model", input_tokens=1, output_tokens=1) is None
    assert pricing.cost("claude-opus-5-5", input_tokens=None, output_tokens=1) is None


def test_a_users_own_price_wins_and_prices_cache_tokens_as_input():
    own = {"claude-opus-5-5": ModelPrice(1.0, 3.0)}
    assert pricing.cost("claude-opus-5-5", input_tokens=1000, output_tokens=1000,
                        cache_read_tokens=500, table=own) == pytest.approx(4000 / 1e6)


# The ids in the page's models.CATALOG: every model the app offers has a list price.
CATALOG_IDS = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1",
               "claude-sonnet-5", "claude-haiku-4-5-20251001")


def test_every_catalog_model_has_a_list_price():
    assert all(pricing.PRICES.get(m) for m in CATALOG_IDS)


def test_the_table_goes_stale_after_90_days():
    from datetime import date
    assert not pricing.stale(date(2026, 10, 17) + timedelta(days=90))
    assert pricing.stale(date(2026, 10, 17) + timedelta(days=91))


# -- migration 25 --------------------------------------------------------------------------

def test_migration_25_adds_the_provider_columns(tmp_path):
    from kranto.store import Store
    s = Store.open(tmp_path / "db.sqlite")
    cols = {r["name"] for r in s.query("PRAGMA table_info(llm_calls)")}
    assert {"provider", "cache_read_tokens", "cache_write_tokens", "equiv_usd"} <= cols
    s.close()


# -- a provider's pause --------------------------------------------------------------------

class PausingProvider:
    """A provider whose every call hits a spend limit until ``until``."""

    name, billing, cost_source, label, key_env = "fake", "dollars", "provider", "fake", None

    def __init__(self, until):
        self.until = until
        self.sent = 0

    def build(self, req):
        return {"model": req.model}

    def send(self, body):
        self.sent += 1
        raise ProviderError("You have reached your specified API usage limits", kind="paused",
                            status=400, resume_at=self.until)

    def close(self):
        pass


class ServingProvider(PausingProvider):
    def send(self, body):
        self.sent += 1
        return Reply(text="ok", model="m", input_tokens=10, output_tokens=2,
                     reported_cost_usd=0.001, http_status=200)


def test_a_paused_provider_halts_and_nothing_is_sent_until_it_ends(make_client, store):
    clock = [FIXED_NOW]
    client = make_client(lambda body: chat_response("ok"))
    client._clock = lambda: clock[0]
    until = FIXED_NOW + timedelta(hours=5)
    fake = PausingProvider(until)
    client._providers = {"openai_compat": fake}

    with pytest.raises(ProviderPaused) as info:
        call(client)
    assert isinstance(info.value, Paused)          # every caller's Paused path takes it
    assert info.value.resume_at == until
    assert fake.sent == 1
    assert "usage limits" in str(info.value) and "until 2026-09-24 17:00 UTC" in str(info.value)
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["status"] == "error" and row["cost_usd"] == 0 and row["provider"] == "fake"
    assert watch_pause(store, FIXED_NOW)["provider"] == "fake"

    with pytest.raises(ProviderPaused):
        client.check_can_spend()
    with pytest.raises(ProviderPaused):
        call(client)
    assert fake.sent == 1                           # refused before any request

    clock[0] = until + timedelta(seconds=1)
    served = ServingProvider(None)
    client._providers = {"openai_compat": served}
    assert call(client).text == "ok"
    assert served.sent == 1
    assert store.get_setting(WATCH_PAUSE_KEY) is None


def test_a_pause_is_not_retried(make_client):
    sleeps: list[float] = []
    client = make_client(lambda body: chat_response("ok"), sleeps=sleeps)
    fake = PausingProvider(FIXED_NOW + timedelta(days=3))
    client._providers = {"openai_compat": fake}
    with pytest.raises(ProviderPaused):
        call(client)
    assert fake.sent == 1 and sleeps == []


def test_an_unreadable_pause_row_is_ignored(store):
    store.set_setting(WATCH_PAUSE_KEY, "not json")
    assert watch_pause(store, FIXED_NOW) is None
    store.set_setting(WATCH_PAUSE_KEY, json.dumps({"until": "2026-09-24T11:00:00Z"}))
    assert watch_pause(store, FIXED_NOW) is None

