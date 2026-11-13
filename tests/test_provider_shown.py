"""What the watcher really uses is what every page says (the owner's report of 2026-10-17): an
OpenRouter key given in ``kranto setup``, then an Anthropic key in the browser's Welcome step.
The watcher used the Claude API, but Settings › Models still said OpenRouter: it showed
``llm.base_url``, which is the OpenAI-style endpoint's and stays OpenRouter's. The replay
below does exactly that sequence, against a fake OpenRouter and a fake Claude API, and checks
Settings › Models and Keys, ``kranto doctor`` and ``afk provider show`` against ``llm.py``'s
client and the ledger's provider column."""

from __future__ import annotations

import secrets

import httpx

from kranto import cli, doctor, launcher, providers, setup
from kranto import config as config_mod
from kranto.config import BudgetConfig
from kranto.llm import LLMClient
from kranto.store import Store

from .test_anthropic_provider import MSG, api, test_key  # noqa: F401
from .test_kranto import make_host, user_home  # noqa: F401


def _openrouter(monkeypatch, seen):
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(200, json={"data": {}})
    real = setup.try_key
    monkeypatch.setattr(setup, "try_key", lambda base, k, transport=None: real(
        base, k, transport=httpx.MockTransport(handler)))


def test_setups_openrouter_then_welcomes_anthropic_key_shows_the_claude_api_everywhere(
        api, user_home, embedder, monkeypatch, tmp_path, capsys):  # noqa: F811
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import web_client
    from .test_setup import FakeScheduler
    for env in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(setup, "RUN", lambda cmd: (127, ""))
    monkeypatch.setattr(setup, "_logins", None)
    seen: list = []
    _openrouter(monkeypatch, seen)

    # 1. kranto setup, with an OpenRouter key
    router_key = "sk-or-v1-" + secrets.token_hex(24)
    key_file = tmp_path / "key.txt"
    key_file.write_text(router_key + "\n")
    key_file.chmod(0o600)
    host = make_host(user_home)
    assert launcher.main(["setup", "--yes", "--no-start", "--watch", "openrouter",
                       "--watch-key-file", str(key_file)], host) == 0
    assert seen == ["openrouter.ai"]
    home = user_home / ".kranto"
    path = config_mod.config_path(home)
    setup.write_config_values(path, {("llm", "anthropic", "base_url"): api.url})
    cfg = config_mod.load(home)
    assert providers.in_use(cfg.llm)["choice"] == "openrouter"

    # 2. Kranto serves; Welcome's key step chooses the Claude API with an Anthropic key
    store = Store.open(cfg.db_path)
    client = LLMClient(store, cfg.llm, BudgetConfig(monthly_usd=None))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client)
    anthropic_key = test_key()
    api.key = anthropic_key
    try:
        with web_client(create_app(rt, FakeScheduler()), "http://127.0.0.1:8765") as web:
            r = web.post("/api/setup/provider", json={"provider": "anthropic",
                                                      "key": anthropic_key})
            assert r.status_code == 200, r.text
            # the watcher's next call goes to the Claude API, and the ledger says so
            rt.llm.complete(tier="judge", purpose="screen", messages=MSG, prompt_version="t")
            assert api.requests[-1][1] == "/v1/messages"
            ledger = store.query_one("SELECT provider, model FROM llm_calls "
                                     "ORDER BY id DESC LIMIT 1")
            assert dict(ledger) == {"provider": "anthropic", "model": "claude-haiku-5-5"}

            # Settings › Models: the Claude API at its own URL, not OpenRouter's
            models = web.get("/api/settings/models").json()
            assert models["provider"] == ledger["provider"] == rt.llm.config.provider_name
            assert models["label"] == "Claude API" and models["choice"] == "anthropic"
            assert models["base_url"] == models["endpoint"] == api.url
            assert "openrouter" not in models["base_url"] and models["routed"] is False
            assert models["last_call"]["provider"] == "anthropic"
            assert [r["model"] for r in models["roles"]] == ["claude-haiku-5-5",
                                                            "claude-sonnet-5-5"]
            # Settings › Keys and Welcome
            key = web.get("/api/setup").json()["key"]
            assert (key["provider"], key["choice"], key["label"], key["endpoint"]) == \
                ("anthropic", "anthropic", "Claude API", api.url)
            assert web.get("/api/setup/provider").json()["current"]["choice"] == "anthropic"
            # Spend
            assert web.get("/api/settings/spend").json()["provider"] == "anthropic"
    finally:
        rt.llm.close()

    # kranto doctor reads the file the server wrote: the same provider, and the ledger agrees
    on_disk = config_mod.load(home, dotenv=False)
    assert doctor.provider_line(on_disk).detail == "Claude API (anthropic)"
    last = doctor.ledger_line(on_disk, store)
    assert last.detail.startswith("anthropic (claude-haiku-5-5) at ") and "before" not in \
        last.detail
    store.close()

    # afk provider show: the same words and the same ledger row
    capsys.readouterr()
    assert cli.main(["-w", str(home), "provider", "show"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"watching with: Claude API (anthropic at {api.url}); judge "
                          "claude-haiku-5-5, reason claude-sonnet-5-5; key set")
    assert "last call: anthropic (claude-haiku-5-5)" in out

    # 3. kranto setup again, Enter everywhere: the browser's choice stays (the last run's
    # answer was openrouter; the config's current provider is above it)
    before = path.read_text()
    code = launcher.main(["setup", "--yes", "--no-start"], host)
    out = capsys.readouterr().out
    assert code == 0 and "kept  watching: Claude API" in out
    assert path.read_text() == before
    for secret in (router_key, anthropic_key):
        assert secret not in out and secret not in before
