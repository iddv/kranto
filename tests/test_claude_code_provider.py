"""Claude Code's login as the watcher's model (PR-D): the provider over the page's
``host_api.claude_print``, here a recording stand-in (no claude, no model, no network). What it
sends, what a call costs (nothing in dollars; its list-price equivalent kept), a closed usage
window as a pause until the time it names, an expired login as a stop, and the explicit
choice with its terms."""

from __future__ import annotations

import json
import sys
import types
from datetime import UTC, datetime, timedelta

import pytest

from kranto import config as config_mod
from kranto import doctor, providers, setup
from kranto.config import BudgetConfig, ClaudeCodeConfig
from kranto.llm import (
    FatalLLMError,
    LLMClient,
    LLMError,
    ProviderPaused,
    TransientLLMError,
    watch_pause,
)
from kranto.providers import claude_code

from .conftest import FIXED_NOW, llm_config

SYSTEM = "You screen items."
MSG = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "an item"}]
SCHEMA = {"type": "object", "properties": {"pass": {"type": "boolean"}},
          "required": ["pass"], "additionalProperties": False}


class PrintError(RuntimeError):
    def __init__(self, message, *, kind, text="", exit_code=None):
        super().__init__(message)
        self.kind, self.text, self.exit_code = kind, text, exit_code


def result(**over) -> dict:
    out = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
           "result": '{"pass": true, "reason": "ok"}', "session_id": "s1",
           "total_cost_usd": 0.00048, "exit_code": 0,
           "usage": {"input_tokens": 1235, "output_tokens": 414, "cache_read_input_tokens": 2330,
                     "cache_creation_input_tokens": 0},
           "modelUsage": {"claude-haiku-5-5": {"costUSD": 0.00048}},
           "init": {"tools": [], "mcp_servers": [], "model": "claude-haiku-5-5"}}
    out.update(over)
    return out


class Runner:
    """``host_api.claude_print`` stand-in: answers from ``replies`` in order (a dict, or an
    exception to raise), recording each call's arguments."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, prompt, **kw):
        self.calls.append({"prompt": prompt, **kw})
        reply = self.replies.pop(0) if self.replies else result()
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def make(store, monkeypatch, tmp_path):
    made = []

    def _make(*replies, budget=None, sleeps=None, **cc):
        runner = Runner(*replies)
        monkeypatch.setattr(claude_code, "_runner", lambda: runner)
        cfg = llm_config(provider="claude_code",
                         models={"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"},
                         claude_code=ClaudeCodeConfig(cwd=str(tmp_path / "cwd"),
                                                      home=str(tmp_path), **cc))
        c = LLMClient(store, cfg, BudgetConfig(monthly_usd=budget),
                      sleep=(sleeps.append if sleeps is not None else lambda s: None),
                      clock=lambda: FIXED_NOW)
        c.runner = runner
        made.append(c)
        return c
    yield _make
    for c in made:
        c.close()


def call(c, purpose="screen", tier="judge", **kw):
    return c.complete(tier=tier, purpose=purpose, messages=MSG, prompt_version="t1",
                      temperature=0.2, **kw)


def test_a_call_is_one_claude_print_with_the_stage_prompt_and_the_item_on_stdin(make, store,
                                                                                tmp_path):
    c = make()
    out = call(c)
    [run] = c.runner.calls
    assert run == {"prompt": "an item", "system": SYSTEM, "model": "claude-haiku-5-5",
                   "schema": None, "timeout": 180.0, "cwd": str(tmp_path / "cwd"),
                   "sandbox": False, "kranto_home": str(tmp_path)}
    assert out.text == '{"pass": true, "reason": "ok"}'
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["provider"] == "claude_code" and row["status"] == "ok"
    assert row["cost_usd"] == 0 and row["equiv_usd"] == pytest.approx(0.00048)
    assert row["prompt_tokens"] == 1235 + 2330 and row["cache_read_tokens"] == 2330
    assert row["completion_tokens"] == 414 and row["model"] == "claude-haiku-5-5"
    assert "temperature" not in json.loads(row["request"])
    assert store.month_spend(FIXED_NOW) == 0


def test_plan_billed_calls_never_meet_a_dollar_cap(make, store):
    c = make(result(total_cost_usd=5.0), result(total_cost_usd=5.0), budget=1.0)
    call(c)
    call(c)
    assert store.month_spend(FIXED_NOW) == 0 and len(c.runner.calls) == 2


def test_a_schema_is_sent_when_structured_is_on_and_its_object_is_the_answer(make):
    c = make(result(result="", structured_output={"pass": False}), structured={"judge": True})
    out = call(c, purpose="judge", schema=SCHEMA)
    assert c.runner.calls[0]["schema"] == SCHEMA
    assert out.structured == {"pass": False} and json.loads(out.text) == {"pass": False}
    call(c, purpose="screen", schema=SCHEMA)
    assert c.runner.calls[1]["schema"] is None


def test_a_writers_schema_always_goes_as_json_schema(make):
    """ fix 1: Write a post wrote nothing on the Claude Code login because the
    writer's schema was not passed on; now a writer's call always passes it."""
    c = make(result(result="", structured_output={"text": "A post."}))
    out = call(c, purpose="toot_caption", schema=SCHEMA)
    assert c.runner.calls[0]["schema"] == SCHEMA and out.structured == {"text": "A post."}
    call(c, purpose="judge", schema=SCHEMA)          # the watcher's: still only when turned on
    assert c.runner.calls[1]["schema"] is None


def test_a_closed_usage_window_pauses_until_it_reopens(make, store, monkeypatch):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC).astimezone()
    c = make(result(is_error=True, exit_code=1,
                    result="You've hit your session limit · resets 3:45pm"))
    c._providers["claude_code"]._clock = lambda: now
    with pytest.raises(ProviderPaused) as info:
        call(c)
    reopens = now.replace(hour=15, minute=45, second=0, microsecond=0)
    if reopens <= now:
        reopens += timedelta(days=1)
    assert info.value.resume_at == reopens
    pause = watch_pause(store, FIXED_NOW)
    assert pause["provider"] == "claude_code" and "usage limit" in pause["reason"]
    with pytest.raises(ProviderPaused):
        call(c)
    assert len(c.runner.calls) == 1
    row = store.query_one("SELECT * FROM llm_calls")
    assert row["status"] == "error" and "hit your session limit" in row["error"]


@pytest.mark.parametrize("words,expect", [
    ("resets 3:45pm", (15, 45, 0)), ("resets 9am", (9, 0, 1)), ("resets 11:30AM", (11, 30, 1)),
    ("hit your weekly limit · resets Mon 12:00am", (0, 0, None)), ("no time here", None)])
def test_the_reset_time_is_read_from_the_words(words, expect):
    now = datetime(2026, 9, 24, 12, 0).astimezone()        # a Thursday, noon, local
    at = claude_code.resume_time(words, now)
    if expect is None:
        assert at == now + timedelta(hours=1)
        return
    hour, minute, days = expect
    assert (at.hour, at.minute) == (hour, minute) and at > now
    if days is not None:
        assert (at.date() - now.date()).days == days
    else:
        assert at.weekday() == 0 and (at - now) < timedelta(days=7)


def test_an_expired_login_stops_the_run_with_what_to_run(make):
    c = make(PrintError("claude exited 1 without a result", kind="exit",
                        text="Login expired · Please run /login", exit_code=1))
    with pytest.raises(FatalLLMError) as info:
        call(c)
    assert "claude /login" in str(info.value) and "setup-token" in str(info.value)


@pytest.mark.parametrize("kind", ["missing", "tools"])
def test_no_claude_or_a_session_with_tools_stops_the_run(make, kind):
    c = make(PrintError(f"it is {kind}", kind=kind))
    with pytest.raises(FatalLLMError):
        call(c)
    assert len(c.runner.calls) == 1


def test_a_timeout_is_retried_then_transient(make):
    c = make(*[PrintError("slow", kind="timeout")] * 4)
    with pytest.raises(TransientLLMError):
        call(c)
    assert len(c.runner.calls) == 4


def test_another_error_result_is_the_items_alone(make):
    c = make(result(is_error=True, result="something else went wrong"))
    with pytest.raises(LLMError) as info:
        call(c)
    assert type(info.value) is LLMError and "something else" in str(info.value)


def test_without_page_it_says_so(monkeypatch, store, tmp_path):
    monkeypatch.setitem(sys.modules, "kranto.page.host_api",
                        types.ModuleType("kranto.page.host_api"))
    cfg = llm_config(provider="claude_code", claude_code=ClaudeCodeConfig(cwd=str(tmp_path)))
    c = LLMClient(store, cfg, BudgetConfig(monthly_usd=None), clock=lambda: FIXED_NOW)
    with pytest.raises(FatalLLMError) as info:
        call(c)
    assert "needs the page" in str(info.value)
    c.close()


def test_the_config_has_defaults_a_home_cwd_and_is_checked(tmp_path):
    config_mod.init_workspace(tmp_path)
    cfg = config_mod.load(tmp_path, dotenv=False).llm
    assert cfg.claude_code.cwd == str(tmp_path.resolve() / "data" / "claude-cwd")
    assert cfg.claude_code.sandbox is False and cfg.claude_code.timeout_seconds == 180
    assert cfg.env_for("claude_code") is None
    base = {"base_url": "x", "api_key_env": "K", "models": {"judge": "a", "reason": "b"}}
    for bad in (
        {"sandbox": "yes"},
        {"timeout_seconds": 5},
        {"structured": {"card": True}},
        {"concurrency": 4},
    ):
        with pytest.raises(config_mod.ConfigError):
            config_mod._parse_llm({**base, "claude_code": bad})


# -- the explicit choice -------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    config_mod.init_workspace(tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "kranto.page.host_api",
        types.SimpleNamespace(claude_print=lambda *a, **k: None),
    )
    return tmp_path


def signed_in(version="2.1.300", logged_in=True):
    def run(cmd):
        if cmd[1:] == ["--version"]:
            return 0, f"{version} (Claude Code)\n"
        return 0, json.dumps(
            {"loggedIn": logged_in, "authMethod": "claude.ai", "subscriptionType": "max"}
        )

    return run


def test_claude_code_is_chosen_only_with_its_terms_and_takes_no_key(home, monkeypatch):
    monkeypatch.setattr(setup, "RUN", signed_in())
    with pytest.raises(setup.SetupError) as info:
        providers.choose(home, "claude_code")
    assert providers.CLAUDE_CODE_TERMS in str(info.value)
    with pytest.raises(setup.SetupError):
        providers.choose(home, "claude_code", key="x" * 20, terms=True)
    out = providers.choose(home, "claude_code", terms=True)
    assert (
        out["ok"]
        and out["env"] is None
        and out["test"]["detail"] == "Claude Code 2.1.300, signed in (claude.ai, max)"
    )
    assert out["models"] == {"judge": "claude-haiku-5-5", "reason": "claude-sonnet-5-5"}
    llm = config_mod.load(home, dotenv=False).llm
    assert llm.provider == "claude_code" and not (home / ".env").exists()


@pytest.mark.parametrize(
    "run,words",
    [
        (lambda cmd: (127, ""), "not installed"),
        (signed_in(version="2.1.299"), "too old"),
        (signed_in(logged_in=False), "not signed in"),
    ],
)
def test_the_test_says_what_is_missing(home, monkeypatch, run, words):
    monkeypatch.setattr(setup, "RUN", run)
    result = providers.test("claude_code")
    assert not result.ok and words in result.detail
    out = providers.choose(home, "claude_code", terms=True)
    assert out["ok"] is False and config_mod.load(home, dotenv=False).llm.provider is None


def test_a_token_in_the_service_counts_as_signed_in(home, monkeypatch):
    monkeypatch.setattr(setup, "RUN", signed_in(logged_in=False))
    result = providers.test("claude_code", environ={"CLAUDE_CODE_OAUTH_TOKEN": "t"})
    assert result.ok and "CLAUDE_CODE_OAUTH_TOKEN" in result.detail


def test_the_doctor_says_the_login_the_plans_usage_and_the_terms(home, store, monkeypatch):
    monkeypatch.setattr(setup, "RUN", signed_in())
    setup.write_config_values(
        config_mod.config_path(home),
        {
            ("llm", "provider"): "claude_code",
            ("llm", "models", "judge"): "claude-haiku-5-5",
            ("llm", "models", "reason"): "claude-sonnet-5-5",
        },
    )
    store.insert(
        "llm_calls",
        {
            "purpose": "screen",
            "tier": "judge",
            "model": "m",
            "prompt_version": "t",
            "request": "{}",
            "status": "ok",
            "attempts": 1,
            "cost_usd": 0.0,
            "equiv_usd": 0.25,
            "provider": "claude_code",
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    cfg = config_mod.load(home, dotenv=False)
    checks = {c.name: c for c in doctor.run(cfg, store, check_embedder=False)}
    assert checks["provider"].detail == "Claude Code (claude_code)"
    assert checks["claude login"].status == doctor.OK
    assert "1 calls this month, about $0.25 at API list prices" in checks["plan usage"].detail
    assert providers.CLAUDE_CODE_TERMS in checks["plan usage"].detail
    assert "api key" not in checks
