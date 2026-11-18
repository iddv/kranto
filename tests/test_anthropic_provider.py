"""The Claude API provider (PR-B), against a fake Claude API on loopback
(``fake_anthropic.py``): what is sent (the system prompt cached, never a temperature), how
each reply and error is read, what a call costs, the key test, and choosing a provider."""

from __future__ import annotations

import json
import os
import secrets
import stat
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kranto import config as config_mod
from kranto import doctor, providers, setup
from kranto.config import AnthropicConfig, BudgetConfig
from kranto.llm import (
    FatalLLMError,
    LLMClient,
    LLMError,
    ProviderPaused,
    RefusedReply,
    TransientLLMError,
    TruncatedCompletion,
    watch_pause,
)

from .conftest import FIXED_NOW, llm_config
from .fake_anthropic import FakeAnthropic, error, message

SYSTEM = "You screen items. " * 40
MSG = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "an item"}]


def test_key() -> str:
    # built at run time: no key-shaped literal in the repository
    return "test-anthropic-" + secrets.token_hex(12)


test_key.__test__ = False


@pytest.fixture
def api():
    fake = FakeAnthropic()
    yield fake
    fake.close()


def anthropic_config(api, **overrides):
    a = AnthropicConfig(base_url=api.url, **overrides)
    return llm_config(provider="anthropic", anthropic=a,
                      models={"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"})


@pytest.fixture
def client(api, store):
    made = []

    def make(key=None, sleeps=None, **overrides):
        c = LLMClient(store, anthropic_config(api, **overrides), BudgetConfig(monthly_usd=None),
                      api_key=key or test_key(),
                      sleep=(sleeps.append if sleeps is not None else lambda s: None),
                      clock=lambda: FIXED_NOW)
        made.append(c)
        return c
    yield make
    for c in made:
        c.close()


def call(c, tier="judge", purpose="screen", **kw):
    return c.complete(tier=tier, purpose=purpose, messages=MSG, prompt_version="t1",
                      temperature=0.2, **kw)


# -- what is sent ----------------------------------------------------------------------------

def test_a_call_is_a_native_messages_request_with_the_system_prompt_cached(api, client, store):
    key = test_key()
    result = call(client(key), max_tokens=700)
    [(method, path, headers, body)] = api.requests
    assert (method, path) == ("POST", "/v1/messages")
    assert headers["x-api-key"] == key and headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers
    assert body == {
        "model": "claude-haiku-5-5", "max_tokens": 700,
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "an item"}],
    }
    assert "temperature" not in body
    assert result.text == '{"pass": true, "reason": "ok"}'
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["provider"] == "anthropic" and row["status"] == "ok"
    assert key not in row["request"] and key not in (row["response"] or "")


def test_cache_off_sends_no_breakpoint(api, client):
    call(client(cache=False))
    assert api.posts[0]["system"] == [{"type": "text", "text": SYSTEM}]


def test_tokens_and_cost_come_from_usage_and_the_price_table(api, client, store):
    api.reply(200, message(input_tokens=1081, output_tokens=670, cache_read=4000))
    api.reply(200, message(input_tokens=1081, output_tokens=670, cache_write=4000))
    first, second = call(client()), call(client())
    assert first.prompt_tokens == 5081 and first.completion_tokens == 670
    assert first.cost_usd == pytest.approx((1081 * 0.10 + 4000 * 0.01 + 670 * 0.50) / 1e6)
    assert second.cost_usd == pytest.approx((1081 * 0.10 + 4000 * 0.125 + 670 * 0.50) / 1e6)
    rows = store.query("SELECT * FROM llm_calls ORDER BY id")
    assert [(r["cache_read_tokens"], r["cache_write_tokens"]) for r in rows] == \
        [(4000, 0), (0, 4000)]
    assert rows[0]["prompt_tokens"] == 5081 and rows[0]["equiv_usd"] is None


def test_the_reason_tier_uses_its_model_and_thinking_is_not_the_answer(api, client):
    api.reply(200, message("a card", model="claude-sonnet-5-5"))
    result = call(client(), tier="reason", purpose="card")
    assert api.posts[0]["model"] == "claude-sonnet-5-5" and result.text == "a card"


def test_structured_output_and_effort_are_sent_only_when_turned_on(api, client):
    schema = {"type": "object", "properties": {"pass": {"type": "boolean"}},
              "required": ["pass"], "additionalProperties": False}
    call(client(), purpose="judge", schema=schema)
    assert "output_config" not in api.posts[-1]
    c = client(structured={"judge": True}, effort={"screen": "low"})
    api.reply(200, message('{"pass": false}'))
    result = call(c, purpose="deep_dive", schema=schema)
    assert api.posts[-1]["output_config"] == {"format": {"type": "json_schema",
                                                         "schema": schema}}
    assert result.structured == {"pass": False}
    call(c, purpose="screen", schema=schema)
    assert api.posts[-1]["output_config"] == {"effort": "low"}


def test_a_writers_schema_is_always_sent(api, client):
    """ fix 1: a writer's call (a blog post in a schema) has its schema
    enforced with no setting; the watcher's calls keep theirs (above)."""
    schema = {"type": "object", "properties": {"body": {"type": "string"}},
              "required": ["body"], "additionalProperties": False}
    api.reply(200, message('{"body": "A post."}'))
    result = call(client(), tier="reason", purpose="blog_post", schema=schema)
    assert api.posts[-1]["output_config"] == {"format": {"type": "json_schema",
                                                         "schema": schema}}
    assert result.structured == {"body": "A post."}


def test_a_reply_cut_off_at_max_tokens_is_truncated_and_retried_with_more_room(api, client):
    api.reply(200, message("partial", stop="max_tokens"))
    result = call(client(), max_tokens=500, retry_truncated=True)
    assert [b["max_tokens"] for b in api.posts] == [500, 1000]
    assert result.text.startswith("{")
    api.reply(200, message("partial", stop="max_tokens"))
    with pytest.raises(TruncatedCompletion):
        call(client())


# -- errors ----------------------------------------------------------------------------------

@pytest.mark.parametrize("status,body", [
    (401, error("authentication_error", "invalid x-api-key")),
    (403, error("permission_error", "not allowed")),
    (404, error("not_found_error", "model: claude-nope")),
    (400, error("invalid_request_error", "Your credit balance is too low to access the "
                                         "Anthropic API.")),
])
def test_a_dead_key_a_missing_model_or_no_credit_is_fatal(api, client, store, status, body):
    api.reply(status, body)
    with pytest.raises(FatalLLMError) as info:
        call(client())
    assert info.value.status == status and len(api.posts) == 1
    assert body["error"]["message"][:20] in str(info.value)
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["status"] == "error" and row["cost_usd"] == 0 and row["provider"] == "anthropic"


def test_the_spend_limit_set_in_the_console_pauses_until_next_month(api, client, store):
    api.reply(400, error("invalid_request_error", "You have reached your specified API "
                                                  "usage limits. You will regain access on "
                                                  "2026-10-01 at 00:00 UTC."))
    c = client()
    with pytest.raises(ProviderPaused) as info:
        call(c)
    assert info.value.resume_at == datetime(2026, 10, 1, tzinfo=UTC)
    pause = watch_pause(store, FIXED_NOW)
    assert pause["provider"] == "anthropic" and "spend limit" in pause["reason"]
    with pytest.raises(ProviderPaused):
        call(c)
    assert len(api.posts) == 1


def test_the_organisations_monthly_cap_without_retry_after_pauses(api, client, store):
    api.reply(429, error("rate_limit_error", "This request would exceed your organization's "
                                             "monthly spend limit.",
                         error_code="enforced_spend_limit_reached"))
    sleeps: list[float] = []
    with pytest.raises(ProviderPaused) as info:
        call(client(sleeps=sleeps))
    assert info.value.resume_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert sleeps == [] and len(api.posts) == 1


def test_a_rate_limit_with_retry_after_is_waited_out(api, client):
    api.reply(429, error("rate_limit_error", "slow down"), {"retry-after": "7"})
    api.reply(529, error("overloaded_error", "Overloaded"))
    sleeps: list[float] = []
    assert call(client(sleeps=sleeps)).text
    assert len(api.posts) == 3 and sleeps[0] == 7.0 and len(sleeps) == 2


def test_overloaded_until_the_retries_run_out_is_transient(api, client):
    for _ in range(4):
        api.reply(529, error("overloaded_error", "Overloaded"))
    with pytest.raises(TransientLLMError):
        call(client())
    assert len(api.posts) == 4


def test_another_bad_request_or_a_refusal_is_the_items_alone(api, client):
    api.reply(400, error("invalid_request_error", "prompt is too long"))
    with pytest.raises(LLMError) as info:
        call(client())
    assert type(info.value) is LLMError and info.value.status == 400
    api.reply(200, message("", stop="refusal"))
    with pytest.raises(LLMError) as info:
        call(client())
    assert type(info.value) is RefusedReply and "declined" in str(info.value)


def test_a_reply_that_is_not_a_message_is_retried(api, client):
    api.reply(200, {"html": "gateway"})
    assert call(client()).text and len(api.posts) == 2


def test_the_key_is_scrubbed_from_a_stored_and_raised_error(api, client, store):
    key = test_key()
    api.reply(401, error("authentication_error", f"invalid x-api-key {key}"))
    with pytest.raises(FatalLLMError) as info:
        call(client(key))
    assert key not in str(info.value) and "[redacted]" in str(info.value)
    row = store.query_one("SELECT * FROM llm_calls")
    assert key not in row["error"] and "[redacted]" in row["error"]


def test_no_key_is_refused_before_any_request(api, store, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = LLMClient(store, anthropic_config(api), BudgetConfig(monthly_usd=None))
    with pytest.raises(FatalLLMError) as info:
        call(c)
    assert "ANTHROPIC_API_KEY" in str(info.value) and api.requests == []
    c.close()


def test_an_unpriced_model_is_refused_before_the_call(api, store):
    cfg = replace(anthropic_config(api), models={"judge": "claude-unknown", "reason": "x"})
    c = LLMClient(store, cfg, BudgetConfig(monthly_usd=None), api_key=test_key())
    from kranto.llm import UnpricedModel
    with pytest.raises(UnpricedModel):
        call(c)
    assert api.requests == []
    c.close()


# -- config ----------------------------------------------------------------------------------

BASE = {"base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
        "models": {"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}}


def test_the_anthropic_section_has_defaults_and_is_checked():
    cfg = config_mod._parse_llm({**BASE, "provider": "anthropic"})
    assert cfg.anthropic == AnthropicConfig() and cfg.anthropic.cache is True
    assert cfg.key_env == "ANTHROPIC_API_KEY" and cfg.anthropic.structured == {}
    for bad in ({"cache": "yes"}, {"structured": {"card": True}}, {"effort": {"screen": "max"}},
                {"api_key_env": "not a name"}, {"other": 1}, {"base_url": "ftp://x"}):
        with pytest.raises(config_mod.ConfigError):
            config_mod._parse_llm({**BASE, "anthropic": bad})


# -- the key test ------------------------------------------------------------------------------

def test_the_key_test_lists_models_and_spends_nothing(api, tmp_path):
    key = test_key()
    api.key = key
    result = providers.test("anthropic", key=key, base_url=api.url)
    assert result.ok and "claude-haiku-5-5 and claude-sonnet-5-5 are offered" in result.detail
    [(method, path, headers, _)] = api.requests
    assert method == "GET" and path.startswith("/v1/models")
    assert headers["x-api-key"] == key
    api.models = ["claude-haiku-5-5"]
    assert "claude-sonnet-5-5 is not offered" in providers.test(
        "anthropic", key=key, base_url=api.url).detail
    refused = providers.test("anthropic", key="wrong-" + secrets.token_hex(8), base_url=api.url)
    assert not refused.ok and "refused the key (HTTP 401)" in refused.detail
    assert not any(m == "POST" for m, *_ in api.requests)


# -- choose and detect -------------------------------------------------------------------------

@pytest.fixture
def home(tmp_path, api, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config_mod.init_workspace(tmp_path)
    path = config_mod.config_path(tmp_path)
    setup.write_config_values(path, {("llm", "models", "judge"): "anthropic/claude-haiku-5.5",
                                     ("llm", "models", "reason"): "anthropic/claude-sonnet-5.5"})
    text = path.read_text().replace("llm:\n", f"llm:\n  anthropic:\n    base_url: {api.url}\n", 1)
    path.write_text(text)
    assert config_mod.load(tmp_path, dotenv=False).llm.anthropic.base_url == api.url
    return tmp_path


def test_choose_tests_then_writes_the_key_and_the_provider_and_renames_the_models(api, home):
    key = test_key()
    api.key = key
    result = providers.choose(home, "anthropic", key=key)
    assert result == {"ok": True, "provider": "anthropic", "env": "ANTHROPIC_API_KEY",
                      "test": {"ok": True, "detail": result["test"]["detail"]},
                      "changed": True, "base_url": None,
                      "models": {"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}}
    assert key not in json.dumps(result)
    env = home / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert env.read_text().splitlines() == [f"ANTHROPIC_API_KEY={key}"]
    llm = config_mod.load(home, dotenv=False).llm
    assert llm.provider == "anthropic" and llm.models == result["models"]
    assert key not in config_mod.config_path(home).read_text()
    again = providers.choose(home, "anthropic", key=key)
    assert again["ok"] and again["changed"] is False


def test_a_key_that_fails_its_test_writes_nothing(api, home):
    api.key = test_key()
    before = config_mod.config_path(home).read_text()
    result = providers.choose(home, "anthropic", key=test_key())
    assert result["ok"] is False and result["models"] is None
    assert not (home / ".env").exists()
    assert config_mod.config_path(home).read_text() == before


def test_going_back_to_openrouter_renames_the_models_back(api, home, monkeypatch):
    from . import test_setup
    key = test_key()
    api.key = key
    providers.choose(home, "anthropic", key=key)
    monkeypatch.setattr(setup, "try_key", lambda base, k, transport=None: setup.KeyTest(
        True, "OpenRouter accepted the key"))
    result = providers.choose(home, "openrouter", key=test_setup.fake_key())
    assert result["ok"] and result["models"] == {"judge": "anthropic/claude-haiku-5.5",
                                                 "reason": "anthropic/claude-sonnet-5.5"}
    llm = config_mod.load(home, dotenv=False).llm
    assert llm.provider == "openrouter" and llm.base_url == providers.OPENROUTER_URL


def test_a_model_with_no_pair_becomes_the_default(api, home):
    path = config_mod.config_path(home)
    setup.write_config_values(path, {("llm", "models", "reason"): "some/other-model"})
    key = test_key()
    api.key = key
    result = providers.choose(home, "anthropic", key=key)
    assert result["models"] == {"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}


def test_detect_finds_keys_by_name_and_claude_code_without_reading_secrets(home):
    (home / ".env").write_text("ANTHROPIC_API_KEY=" + test_key() + "\n")
    ran = []

    def run(cmd):
        ran.append(cmd)
        if cmd[1:] == ["--version"]:
            return 0, "2.1.300 (Claude Code)\n"
        return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                              "subscriptionType": "max", "email": "someone@example.org"})
    found = providers.detect(home, environ={"OPENROUTER_API_KEY": "x"}, run=run)
    assert found["choices"] == ["anthropic", "openrouter", "openai_compat", "claude_code"]
    assert found["anthropic"] == {"key_set": True, "env": "ANTHROPIC_API_KEY",
                                  "label": "Claude API"}
    assert found["openrouter"]["key_set"] is True and found["openai_compat"]["key_set"] is False
    assert found["current"] == {
        "provider": "openai_compat", "choice": "openrouter", "label": "OpenRouter",
        "endpoint": providers.OPENROUTER_URL, "key_env": "OPENROUTER_API_KEY", "key_set": True,
        "models": {"judge": "anthropic/claude-haiku-5.5", "reason": "anthropic/claude-sonnet-5.5"},
        "tiers": {"judge": "openai_compat", "reason": "openai_compat"}}
    assert found["claude_code"] == {"installed": True, "version": "2.1.300", "logged_in": True,
                                    "auth_method": "claude.ai", "subscription": "max",
                                    "token_in_service": False, "offered": True,
                                    "label": "Claude Code", "terms": providers.CLAUDE_CODE_TERMS}
    assert "someone@" not in json.dumps(found)
    assert ["claude", "auth", "status"] in ran


# -- the setup route ---------------------------------------------------------------------------

def test_the_route_chooses_the_provider_and_the_running_server_uses_it(api, home, store,
                                                                       embedder, monkeypatch):
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import web_client
    from .test_setup import FakeScheduler, everything_written
    monkeypatch.setattr(setup, "RUN", lambda cmd: (127, ""))
    monkeypatch.setattr(setup, "_logins", None)
    cfg = config_mod.load(home, dotenv=False)
    c = LLMClient(store, cfg.llm, BudgetConfig(monthly_usd=None), api_key="")
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=c)
    key = test_key()
    api.key = key
    with web_client(create_app(rt, FakeScheduler()), "http://127.0.0.1:8765") as web:
        found = web.get("/api/setup/provider").json()
        assert found["anthropic"]["key_set"] is False and found["claude_code"]["offered"]
        bad = web.post("/api/setup/provider", json={"provider": "anthropic",
                                                    "key": "wrong-" + secrets.token_hex(8)})
        assert bad.status_code == 400 and "refused" in bad.json()["error"]
        r = web.post("/api/setup/provider", json={"provider": "anthropic", "key": key})
        assert r.status_code == 200, r.text
        assert key not in r.text and r.json()["models"]["judge"] == "claude-haiku-5-5"
        assert rt.cfg.llm.provider == "anthropic" and rt.llm.config.provider == "anthropic"
        assert os.environ["ANTHROPIC_API_KEY"] == key
        state = web.get("/api/setup").json()
        assert state["key"] == {**state["key"], "set": True, "env": "ANTHROPIC_API_KEY",
                                "provider": "anthropic"}
        # the running client now calls the Claude API with that key
        rt.llm.complete(tier="judge", purpose="screen", messages=MSG, prompt_version="t")
        assert api.requests[-1][1] == "/v1/messages" and api.requests[-1][2]["x-api-key"] == key
        assert key not in everything_written(rt)
    os.environ.pop("ANTHROPIC_API_KEY", None)


# -- the doctor --------------------------------------------------------------------------------

def test_the_doctor_tests_the_key_the_models_and_the_prices(api, home, store, monkeypatch):
    key = test_key()
    api.key = key
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    setup.write_config_values(config_mod.config_path(home), {
        ("llm", "provider"): "anthropic", ("llm", "models", "judge"): "claude-haiku-5-5",
        ("llm", "models", "reason"): "claude-opus-5-5"})
    cfg = config_mod.load(home, dotenv=False)
    checks = {c.name: c for c in doctor.run(cfg, store, check_embedder=False)}
    assert checks["provider"].detail == "Claude API (anthropic)"
    assert checks["api key"].status == doctor.OK and key not in checks["api key"].detail
    assert checks["judge model"].status == doctor.OK
    assert checks["reason model"].status == doctor.OK
    assert checks["pricing"].status == doctor.OK and "2026-10-17" in checks["pricing"].detail
    api.models = ["claude-haiku-5-5"]
    checks = {c.name: c for c in doctor.run(cfg, store, check_embedder=False)}
    assert checks["reason model"].status == doctor.FAIL


def test_the_doctor_says_when_the_console_would_bill_the_anthropic_key(home, monkeypatch):
    cfg = config_mod.load(home, dotenv=False)
    # the claude Kranto starts is the console's, whatever builds.enabled says
    monkeypatch.setattr(config_mod, "builds_on", lambda c: True)
    line = doctor.watch_login(cfg, {"ANTHROPIC_API_KEY"})
    assert line.name == "claude login" and "build" not in line.detail
    assert line.status == doctor.WARN and "the console bills ANTHROPIC_API_KEY" in line.detail
    assert doctor.watch_login(cfg, set()) is None
    assert "the watcher does not use it" in line.detail
    cfg = replace(cfg, llm=replace(cfg.llm, provider="anthropic"))
    line = doctor.watch_login(cfg, {"ANTHROPIC_API_KEY"})
    assert line.status == doctor.WARN and "the watcher uses it too" in line.detail
    line = doctor.watch_login(cfg, {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"})
    assert line.status == doctor.OK and "CLAUDE_CODE_OAUTH_TOKEN" in line.detail
    (home / ".env").write_text("ANTHROPIC_API_KEY=" + test_key() + "\n")
    assert doctor.watch_login(cfg, set()).status == doctor.WARN


def test_resuming_by_hand_ends_a_providers_pause(api, client, store):
    api.reply(400, error("invalid_request_error", "You have reached your specified API usage "
                                                  "limits."))
    c = client()
    with pytest.raises(ProviderPaused):
        call(c)
    store.resume()
    assert watch_pause(store, FIXED_NOW) is None
    assert call(c).text and len(api.posts) == 2


@pytest.fixture
def workspace_web(home, store, embedder, monkeypatch):
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import web_client
    from .test_setup import FakeScheduler
    monkeypatch.setattr(setup, "RUN", lambda cmd: (127, ""))
    cfg = config_mod.load(home, dotenv=False)
    c = LLMClient(store, cfg.llm, BudgetConfig(monthly_usd=None), api_key="")
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=c)
    with web_client(create_app(rt, FakeScheduler()), "http://127.0.0.1:8765") as web:
        yield web


def test_the_route_ends_a_providers_pause(workspace_web, store):
    from kranto.llm import WATCH_PAUSE_KEY
    store.set_setting(WATCH_PAUSE_KEY, json.dumps({"until": "2026-10-01T00:00:00Z",
                                                   "reason": "spend limit",
                                                   "provider": "anthropic"}))
    r = workspace_web.post("/api/watch/resume", json={})
    assert r.status_code == 200 and r.json() == {"ok": True, "was_paused": True}
    assert store.get_setting(WATCH_PAUSE_KEY) is None
