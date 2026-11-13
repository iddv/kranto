"""Choosing live search: the state Settings shows, a test that spends one
search, the choice and its key written (never returned), the callers' switches, Spend's search
lines and cap, ``kranto setup search``. No network, no model."""

from __future__ import annotations

import json
import stat

import pytest
import yaml

from kranto import config as config_mod
from kranto import launcher, websearch
from kranto.runtime import open_runtime
from kranto.setup import SetupError
from kranto.store import Store
from kranto.websearch import setup as wsetup

from .conftest import chat_response, web_client
from .fake_search import FakeSearch
from .test_kranto import make_host, user_home  # noqa: F401


@pytest.fixture
def home(tmp_path):
    path = config_mod.init_workspace(tmp_path / "home")
    return path.parent


@pytest.fixture(autouse=True)
def no_search_keys(monkeypatch):
    for k in ("EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_the_state_says_exas_free_mode_and_which_keys_are_set(home, monkeypatch):
    cfg = config_mod.load(home, dotenv=False)
    store = Store.memory()
    state = wsetup.detect(cfg, store, environ={"BRAVE_API_KEY": "brave-test-key-not-real"})
    assert state["web"] == "exa" and state["free_mode"] is True
    assert state["web_label"] == websearch.EXA_FREE_LABEL
    assert state["free_mode_words"].startswith("Exa's free mode")
    keys = {c["provider"]: c["key_set"] for c in state["choices"]}
    assert keys == {"exa": False, "brave": True, "tavily": False, "anthropic": None,
                    "none": None}
    assert state["callers"]["scout"] == "on" and state["no_search"] == websearch.NO_SEARCH
    assert "brave-test-key-not-real" not in json.dumps(state)


def test_a_test_spends_one_search_and_says_what_answered(home):
    cfg = config_mod.load(home, dotenv=False)
    fake = FakeSearch()
    got = wsetup.test(cfg, "exa", http=fake.http(), environ={})
    assert got == {"ok": True, "detail": f"{websearch.EXA_FREE_LABEL} answered: 3 results, "
                                         "2 dated", "results": 3}
    assert wsetup.test(cfg, "none")["ok"] is True
    no_key = wsetup.test(cfg, "brave", http=fake.http(), environ={})
    assert not no_key["ok"] and "BRAVE_API_KEY" in no_key["detail"]
    with pytest.raises(ValueError):
        wsetup.test(cfg, "duckduckgo")


def test_choosing_writes_the_provider_and_the_key_and_never_returns_it(home, monkeypatch):
    fake = FakeSearch()
    key = "brave-test-key-" + "x" * 12
    out = wsetup.choose(home, "brave", key=key, http=fake.http(), environ={})
    assert out["ok"] and out["env"] == "BRAVE_API_KEY" and out["changed"]
    assert key not in json.dumps(out)
    assert config_mod.load(home, dotenv=False).search.provider == "brave"
    env = home / ".env"
    assert f"BRAVE_API_KEY={key}" in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    # a test that fails writes nothing, unless kept anyway
    fake.fail["api.search.brave.com"] = 401
    bad = wsetup.choose(home, "tavily", http=fake.http(), environ={})
    assert not bad["ok"] and config_mod.load(home, dotenv=False).search.provider == "brave"
    with pytest.raises(SetupError, match="takes no key"):
        wsetup.choose(home, "none", key="some-key-value-here")


def test_the_callers_switches_are_written_and_checked(home):
    wsetup.set_callers(home, {"cards": "off", "research": "search"}, recent_weeks=8)
    s = config_mod.load(home, dotenv=False).search
    assert s.caller("cards") == "off" and s.caller("research") == "search"
    assert s.recent_weeks == 8
    with pytest.raises(SetupError):
        wsetup.set_callers(home, {"cards": "sometimes"})
    with pytest.raises(SetupError):
        wsetup.set_callers(home, {"judge": "on"})


# -- the API and Spend --------------------------------------------------------------------------


@pytest.fixture
def web(home, store, embedder, make_client):
    cfg = config_mod.load(home, dotenv=False)
    fake = FakeSearch()
    rt = open_runtime(cfg, store=store, embedder=embedder,
                      llm=make_client(lambda body: chat_response("{}")), http=fake.http())
    from kranto.web.app import create_app
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        client.rt = rt
        yield client


def test_the_setup_api_reads_and_switches_live_search_at_once(web):
    from kranto.web.types import RETURNS

    from .test_web_types import problems
    state = web.get("/api/setup/search").json()
    assert problems(state, RETURNS["/api/setup/search"]) == []
    r = web.post("/api/setup/search", json={"provider": "none"})
    assert r.status_code == 200 and r.json()["state"]["web"] is None
    assert web.rt.cfg.search.provider == "none"
    assert websearch.current().web is None              # sources read with the new choice
    r = web.post("/api/setup/search/callers", json={"callers": {"pitch": "off"},
                                                   "recent_weeks": 6})
    assert r.status_code == 200 and r.json()["callers"]["pitch"] == "off"
    assert web.rt.cfg.search.recent_weeks == 6
    assert web.post("/api/setup/search/callers",
                    json={"callers": {"pitch": "maybe"}}).status_code == 400
    assert web.post("/api/setup/search", json={"provider": "kagi"}).status_code == 400


def test_spend_shows_searches_per_backend_and_writes_the_cap(web):
    web.get("/api/websearch?q=sync&kind=discussion")
    spend = web.get("/api/settings/spend").json()["search"]
    assert spend["monthly_usd"] is None and spend["spent_usd"] == 0
    lines = {x["backend"]: x for x in spend["lines"]}
    assert lines["exa"]["label"] == websearch.EXA_FREE_LABEL and lines["exa"]["free"]
    assert lines["hackernews"]["searches"] == 1
    r = web.post("/api/settings/spend", json={"search_monthly_usd": 5})
    assert r.status_code == 200 and r.json()["search"]["monthly_usd"] == 5.0
    assert web.rt.cfg.search.monthly_usd == 5.0
    assert web.post("/api/settings/spend", json={"search_monthly_usd": -1}).status_code == 400


# -- kranto setup search ---------------------------------------------------------------------------


def setup(host, *argv, capsys):
    code = launcher.main(["setup", *argv], host)
    return code, capsys.readouterr()


def test_kranto_setup_search_keeps_exas_free_mode_and_takes_a_choice(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", capsys=capsys)
    the_home = user_home / ".kranto"
    assert code == 0 and "live search: Exa in its free mode (no key)" in out.out
    code, out = setup(host, "search", "--yes", "--search", "none", capsys=capsys)
    assert code == 0
    assert yaml.safe_load((the_home / "kranto.yaml").read_text())["search"]["provider"] == "none"
    code, out = setup(host, "search", "--yes", "--search", "brave", capsys=capsys)
    assert code == 2 and "needs $BRAVE_API_KEY" in out.out
    code, out = setup(host, "search", "--search-key", "x", capsys=capsys)
    assert code == 2 and "shell history" in out.err


def test_kranto_research_left_with_the_build_loop(user_home):  # noqa: F811
    """CUT: the researcher was the build loop's (the page's loop.research); ``kranto research``
    is no command any more."""
    with pytest.raises(SystemExit):
        launcher.main(["research", "what shipped?"], make_host(user_home))

