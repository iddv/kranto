"""First-run setup (PLAN.md 1.5): the key is tested, kept in .env (0600) and set for the
running server, and never echoed, logged, stored in the YAML or the library; the logins
are read for a yes or no; finish writes the config and starts the first ingest. No test
reaches the network: the key test runs against a mock transport."""

import json
import logging
import os
import secrets
import stat

import httpx
import pytest
import yaml

from kranto import config as config_mod
from kranto import library, setup
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import chat_response, llm_config, web_client

EVIL = {"origin": "https://evil.example"}
ENV = "KRANTO_TEST_MODEL_KEY"


def fake_key() -> str:
    # built at run time: no key-shaped literal in the repository
    return "sk-" + "or-v1-" + secrets.token_hex(24)


class Accepting:
    """A model endpoint: 200 for the key it knows, 401 for anything else."""

    def __init__(self, good: str | None):
        self.good, self.seen = good, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.url.host, request.url.path,
                          request.headers.get("authorization")))
        if request.headers.get("authorization") == f"Bearer {self.good}":
            return httpx.Response(200, json={"data": {"label": "test"}})
        return httpx.Response(401, json={"error": "invalid key"})


class FakeScheduler:
    busy = False

    def __init__(self):
        self.triggered = []

    def start(self):
        pass

    def stop(self, timeout=None):
        return True

    def wait(self, timeout):
        return True

    def still_running(self):
        return []

    def trigger(self, kind):
        self.triggered.append(kind)
        return True


@pytest.fixture
def logins(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[0] == "claude":
            return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                                  "email": "someone@example.org"})
        return 0, ("github.com\n  ✓ Logged in to github.com account octo (keyring)\n"
                   "  - Token: gho_" + "*" * 36 + "\n")

    monkeypatch.setattr(setup, "RUN", run)
    monkeypatch.setattr(setup, "_logins", None)
    return calls


@pytest.fixture
def endpoint(monkeypatch):
    holder = {"fake": Accepting(None)}
    real = setup.try_key
    monkeypatch.setattr(setup, "try_key", lambda base, key, transport=None: real(
        base, key, transport=httpx.MockTransport(holder["fake"])))
    return holder


@pytest.fixture
def workspace(tmp_path, store, embedder, make_client, monkeypatch, logins):
    monkeypatch.delenv(ENV, raising=False)
    config_mod.init_workspace(tmp_path)
    # the file says what the runtime was loaded with: providers.choose reads the file
    setup.write_config_values(config_mod.config_path(tmp_path), {("llm", "api_key_env"): ENV})
    cfg = Config(root=tmp_path, llm=llm_config(api_key_env=ENV,
                                               base_url="https://openrouter.ai/api/v1"),
                 budget=BudgetConfig(monthly_usd=10), ingest=IngestConfig(), map=MapConfig())
    client = make_client(lambda body: chat_response("{}"), api_key="")
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client)
    sched = FakeScheduler()
    with web_client(create_app(rt, sched), "http://127.0.0.1:8765") as web:
        yield rt, web, sched
    os.environ.pop(ENV, None)


def everything_written(rt) -> str:
    """Every place a key must never land: the YAML, the library's tables, as one text."""
    parts = [(rt.cfg.root / "kranto.yaml").read_text()]
    for table in ("settings", "llm_calls", "runs"):
        parts += [json.dumps(dict(r)) for r in rt.store.query(f"SELECT * FROM {table}")]
    return "\n".join(parts)


def test_a_fresh_install_needs_setup_and_the_state_holds_no_secret(workspace, logins):
    rt, web, _ = workspace
    s = web.get("/api/setup").json()
    assert s["needs_setup"] and not s["done"] and s["key"]["set"] is False
    assert s["key"]["env"] == ENV and s["key"]["base_url"] == "https://openrouter.ai/api/v1"
    assert s["logins"]["claude"] == {"ok": True, "installed": True,
                                     "detail": "signed in (claude.ai)",
                                     "command": "claude auth login"}
    # Welcome's Ready line: what Kranto costs, and the cap this home has
    assert s["cost"] == ("About $5 to $8 a month for one topic with ten sources, on your own model "
                         "key. Watching stops for the month at your cap of $10.00 (Spend).")
    assert setup.cost_words(None).endswith("No cap is set; set one in Spend.")
    assert s["logins"]["gh"]["detail"] == "signed in to github.com as octo" and s["builds_ok"]
    text = json.dumps(s)
    assert "gho_" not in text and "Token" not in text and "someone@" not in text
    assert s["topics"] == 0 and s["sources"] == 0 and s["build"]["mode"] is None
    # cached: the page polls; a fresh check runs both again
    web.get("/api/setup")
    assert len(logins) == 2
    assert web.post("/api/setup/check", json={}).status_code == 200 and len(logins) == 4


def test_the_key_is_tested_kept_in_env_and_never_echoed(workspace, endpoint, caplog):
    rt, web, _ = workspace
    key = fake_key()
    endpoint["fake"] = Accepting(key)
    (rt.cfg.root / ".env").write_text("KRANTO_NOTIFY_URLS=ntfy://example/x\n")
    caplog.set_level(logging.DEBUG)
    r = web.post("/api/setup/key", json={"key": f"  {key}\n"})
    assert r.status_code == 200, r.text
    assert key not in r.text and r.json()["test"]["ok"] is True
    assert r.json()["test"]["detail"] == "OpenRouter accepted the key"
    # one request, to the key endpoint, with no completion
    assert endpoint["fake"].seen == [("openrouter.ai", "/api/v1/key", f"Bearer {key}")]
    env = rt.cfg.root / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert env.read_text().splitlines() == ["KRANTO_NOTIFY_URLS=ntfy://example/x", f"{ENV}={key}"]
    assert os.environ[ENV] == key and rt.llm.has_key
    state = web.get("/api/setup")
    assert key not in state.text and state.json()["key"]["set"] is True
    assert state.json()["key"]["test"]["ok"]
    assert key not in everything_written(rt)
    assert key not in caplog.text
    assert not list(rt.cfg.root.glob(".env.*.tmp"))


def test_a_preview_tests_no_key_and_says_so(workspace, endpoint, monkeypatch):
    """A preview sent a made-up key to the provider to test it: a key test is a request to the
    provider, so a preview makes none, keeps nothing, and says so in words."""
    from kranto import preview
    rt, web, _ = workspace
    monkeypatch.setenv(preview.ENV, "1")
    key = fake_key()
    for path, body in (("/api/setup/key", {"key": key}),
                       ("/api/setup/provider", {"provider": "openrouter", "key": key})):
        r = web.post(path, json=body)
        assert r.status_code == 400, r.text
        assert r.json()["error"] == preview.NO_KEY_TEST and key not in r.text
    assert endpoint["fake"].seen == []                     # nothing left this machine
    assert not (rt.cfg.root / ".env").exists() and not rt.llm.has_key


def test_a_refused_key_is_not_kept(workspace, endpoint, caplog):
    rt, web, _ = workspace
    key = fake_key()
    caplog.set_level(logging.DEBUG)
    r = web.post("/api/setup/key", json={"key": key})
    assert r.status_code == 400
    assert r.json()["error"] == "openrouter.ai refused the key (HTTP 401)"
    assert key not in r.text and not (rt.cfg.root / ".env").exists()
    assert not rt.llm.has_key and ENV not in os.environ
    assert web.get("/api/setup").json()["key"]["test"]["ok"] is False
    assert key not in everything_written(rt) and key not in caplog.text


def test_a_key_that_could_add_a_line_is_refused(workspace, endpoint):
    rt, web, _ = workspace
    for bad in ("", "   ", "abc\nOTHER=1", "with space" + secrets.token_hex(8), "x" * 600):
        r = web.post("/api/setup/key", json={"key": bad})
        assert r.status_code == 400, bad
    assert endpoint["fake"].seen == [] and not (rt.cfg.root / ".env").exists()
    r = web.post("/api/setup/key", json={"key": fake_key(), "base_url": "ftp://x"})
    assert r.status_code == 400 and "http" in r.json()["error"]


def test_another_endpoint_is_tested_with_models_and_written_to_the_yaml(workspace, endpoint):
    rt, web, _ = workspace
    key = fake_key()
    endpoint["fake"] = Accepting(key)
    before = (rt.cfg.root / "kranto.yaml").read_text()
    r = web.post("/api/setup/key", json={"key": key, "base_url": "http://127.0.0.1:4000/v1/"})
    assert r.status_code == 200, r.text
    assert endpoint["fake"].seen[0][:2] == ("127.0.0.1", "/v1/models")
    after = (rt.cfg.root / "kranto.yaml").read_text()
    assert yaml.safe_load(after)["llm"]["base_url"] == "http://127.0.0.1:4000/v1"
    # comments survive; only the lines providers.choose owns changed (the endpoint, the
    # provider, the tiers' models)
    def others(text):
        return [ln for ln in text.splitlines()
                if not ln.strip().startswith(("base_url:", "provider:", "judge:", "reason:"))]
    assert others(before) == others(after)
    assert yaml.safe_load(after)["llm"]["provider"] == "openai_compat"
    assert rt.cfg.llm.base_url == rt.llm.config.base_url == "http://127.0.0.1:4000/v1"
    assert config_mod.load(rt.cfg.root).llm.base_url == "http://127.0.0.1:4000/v1"
    assert key not in after


def test_finish_writes_the_config_marks_done_and_starts_the_first_ingest(workspace, endpoint):
    rt, web, sched = workspace
    r = web.post("/api/setup/finish", json={"build_mode": "auto"})
    assert r.status_code == 400 and "key first" in r.json()["error"]
    key = fake_key()
    endpoint["fake"] = Accepting(key)
    assert web.post("/api/setup/key", json={"key": key}).status_code == 200
    topic = library.add_topic(rt.store, rt.embedder, "solar", "solar microgrids")
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/feed"}, label="Feed")
    library.link_topic_source(rt.store, topic, src)
    assert web.post("/api/setup/finish", json={"build_mode": "sometimes"}).status_code == 400
    assert web.post("/api/setup/finish", json={"build_mode": "auto",
                                               "concurrency": 0}).status_code == 400
    r = web.post("/api/setup/finish", json={"build_mode": "auto", "concurrency": 1})
    assert r.status_code == 200, r.text
    assert r.json()["ingest"] == "started" and sched.triggered == ["ingest"]
    assert r.json()["build"] == {"mode": "auto", "concurrency": 1}
    loaded = config_mod.load(rt.cfg.root)
    assert loaded.notify.base_url == "http://127.0.0.1:8765"
    s = web.get("/api/setup").json()
    assert s["done"] and not s["needs_setup"] and s["topics"] == 1 and s["sources"] == 1
    # done: the key and finish refuse unless Settings › Keys says replace
    other = fake_key()
    endpoint["fake"] = Accepting(other)
    assert web.post("/api/setup/key", json={"key": other}).status_code == 409
    assert web.post("/api/setup/finish", json={"build_mode": "manual"}).status_code == 409
    r = web.post("/api/setup/key", json={"key": other, "replace": True})
    assert r.status_code == 200 and other not in r.text
    assert (rt.cfg.root / ".env").read_text() == f"{ENV}={other}\n"


def test_a_kranto_home_has_its_kranto_yaml_written(workspace, endpoint):
    """A home made before the rename keeps its settings file's old name: setup writes that
    file, never a new kranto.yaml beside it."""
    from kranto import legacy

    rt, web, _ = workspace
    (rt.cfg.root / "kranto.yaml").rename(rt.cfg.root / legacy.HOME_FILES[0])
    endpoint["fake"] = Accepting(key := fake_key())
    r = web.post("/api/setup/key", json={"key": key, "base_url": "http://127.0.0.1:4000/v1"})
    assert r.status_code == 200, r.text
    assert web.post("/api/setup/finish", json={"build_mode": "manual"}).status_code == 200
    assert not (rt.cfg.root / "kranto.yaml").exists()
    loaded = config_mod.load(rt.cfg.root)
    assert loaded.llm.base_url == "http://127.0.0.1:4000/v1"
    assert loaded.notify.base_url == "http://127.0.0.1:8765"


def test_finish_through_another_port_leaves_the_servers_port_alone(workspace, endpoint):
    """kranto serve reads its port from notify.base_url: setup finished through a tunnel on
    another local port must not move the server there on its next start."""
    rt, _, _ = workspace
    sched = FakeScheduler()
    with web_client(create_app(rt, sched, port=8765), "http://127.0.0.1:9999") as web:
        endpoint["fake"] = Accepting(key := fake_key())
        assert web.post("/api/setup/key", json={"key": key}).status_code == 200
        assert web.post("/api/setup/finish", json={"build_mode": "manual"}).status_code == 200
    assert "9999" not in config_mod.load(rt.cfg.root).notify.base_url


def test_finish_without_sources_or_scheduler_says_so(workspace, endpoint, tmp_path):
    rt, web, sched = workspace
    endpoint["fake"] = Accepting(key := fake_key())
    web.post("/api/setup/key", json={"key": key})
    r = web.post("/api/setup/finish", json={"build_mode": "manual"})
    assert r.json()["ingest"] == "no_sources" and sched.triggered == []
    assert setup.build_choice(rt.store) == {"mode": "manual", "concurrency": 1}


def test_setup_writes_are_guarded(workspace, endpoint):
    rt, web, _ = workspace
    endpoint["fake"] = Accepting(key := fake_key())
    for path, body in (("/api/setup/key", {"key": key}), ("/api/setup/finish", {}),
                       ("/api/setup/check", {})):
        assert web.post(path, json=body, headers=EVIL).status_code == 403
    assert endpoint["fake"].seen == [] and not (rt.cfg.root / ".env").exists()
    assert web.get("/api/setup", headers={"host": "evil.example"}).status_code == 400


def test_login_rows_read_a_yes_or_no_and_never_the_output():
    assert setup._claude(127, "")["ok"] is False
    assert setup._claude(1, '{"loggedIn": false}') == {"ok": False, "installed": True,
                                                         "detail": "not signed in"}
    weird = setup._claude(0, '{"loggedIn": true, "authMethod": "<b>x</b> y"}')
    assert weird == {"ok": True, "installed": True, "detail": "signed in"}
    assert setup._claude(127, "")["installed"] is False            # Ready: not installed
    assert setup._gh(1, "You are not logged into any GitHub hosts.")["ok"] is False
    assert setup._gh(127, "")["detail"].startswith("the GitHub CLI is not installed")
    row = setup._gh(0, "  ✓ Logged in to github.com account a-b (x)\n  - Token: gho_***")
    assert row == {"ok": True, "detail": "signed in to github.com as a-b"}


def test_yaml_values_are_set_in_place():
    text = ("# top comment\nllm:\n  # the endpoint\n  base_url: https://a.example/v1\n"
            "  api_key_env: K\n\nbudget:\n  monthly_usd: 10\nbrb: {}\n")
    out = setup.set_yaml_value(text, "llm", "base_url", "https://b.example/v1")
    assert out == text.replace("base_url: https://a.example/v1",
                               'base_url: "https://b.example/v1"')
    out = setup.set_yaml_value(out, "budget", "alarm_fraction", 0.5)
    assert "  monthly_usd: 10\n  alarm_fraction: 0.5\n" in out
    out = setup.set_yaml_value(out, "brb", "enabled", True)
    out = setup.set_yaml_value(out, "notify", "base_url", "http://127.0.0.1:8765")
    parsed = yaml.safe_load(out)
    assert parsed["brb"] == {"enabled": True} and parsed["budget"]["alarm_fraction"] == 0.5
    assert parsed["notify"] == {"base_url": "http://127.0.0.1:8765"}
    assert out.startswith("# top comment\nllm:\n  # the endpoint\n")
    with pytest.raises(setup.SetupError):
        setup.set_yaml_value(out, "llm", "x: 1\nevil", "v")


def test_a_yaml_value_written_as_a_block_is_replaced_whole():
    # a config whose list was written as a block (by hand, or by a YAML dumper as e2e_update.sh's
    # setup does): Arrange's write answered 500 on it ("while parsing a block mapping")
    text = ("shell:\n  layout: new\n  widgets:\n  - id: greeting\n    size: L\n  - id: foot\n"
            "    size: L\n  pins:\n  - invest\n# the end\nideas:\n  every_hours: 0\n")
    ws = [{"id": "greeting", "size": "L"}, {"id": "activity", "size": "M"}]
    out = setup.set_yaml_value(text, "shell", "widgets", ws)
    parsed = yaml.safe_load(out)
    assert parsed["shell"] == {"layout": "new", "widgets": ws, "pins": ["invest"]}
    assert parsed["ideas"] == {"every_hours": 0} and "# the end\n" in out
    nested = "shell:\n  widgets:\n    - id: foot\n      size: L\n\n  layout: new\n"
    assert yaml.safe_load(setup.set_yaml_value(nested, "shell", "widgets", []))["shell"] == \
        {"widgets": [], "layout": "new"}


def _fake_loop_settings(monkeypatch):
    """The page's settings writer, as a fake: records what it would write."""
    written = []
    brbfake.install(monkeypatch, write_setting=lambda path, keys, value:
                    written.append((str(path), keys, value)))
    return written


def test_the_onboarding_answer_never_reaches_a_build_loop(workspace, endpoint, tmp_path,
                                                         monkeypatch):
    """CUT: builds left Kranto. Even with builds.enabled in an old file, Finish keeps the old
    answer (read by a page that still shows it) and writes nothing to the loop's loop.yaml."""
    from dataclasses import replace
    rt, web, _ = workspace
    rt.cfg = replace(rt.cfg, brb=replace(rt.cfg.brb, enabled=True,
                                         loop_home=str(tmp_path / "loop")),
                     builds=replace(rt.cfg.builds, enabled=True))
    written = _fake_loop_settings(monkeypatch)
    endpoint["fake"] = Accepting(key := fake_key())
    assert web.post("/api/setup/key", json={"key": key}).status_code == 200
    r = web.post("/api/setup/finish", json={"build_mode": "manual", "concurrency": 2})
    assert r.status_code == 200, r.text
    assert written == [] and not (tmp_path / "loop").exists()
    assert r.json()["loop_settings"] is None
    assert r.json()["build"] == {"mode": "manual", "concurrency": 2}


def test_with_builds_off_finish_writes_nothing_to_the_loop(workspace, endpoint, tmp_path,
                                                          monkeypatch):
    """.1: the page mounted and builds.enabled absent: Finish marks setup done and
    leaves the loop's loop.yaml alone."""
    from dataclasses import replace
    rt, web, _ = workspace
    rt.cfg = replace(rt.cfg, brb=replace(rt.cfg.brb, enabled=True,
                                         loop_home=str(tmp_path / "loop")))
    written = _fake_loop_settings(monkeypatch)
    endpoint["fake"] = Accepting(key := fake_key())
    assert web.post("/api/setup/key", json={"key": key}).status_code == 200
    r = web.post("/api/setup/finish", json={})
    assert r.status_code == 200 and r.json()["done"] and r.json()["loop_settings"] is None
    assert written == [] and not (tmp_path / "loop").exists()


def test_without_page_the_answer_is_kept_and_nothing_else_written(workspace, endpoint,
                                                                       tmp_path, monkeypatch):
    from dataclasses import replace
    rt, web, _ = workspace
    rt.cfg = replace(rt.cfg, brb=replace(rt.cfg.brb, enabled=True,
                                         loop_home=str(tmp_path / "loop")))
    brbfake.missing(monkeypatch)
    endpoint["fake"] = Accepting(key := fake_key())
    assert web.post("/api/setup/key", json={"key": key}).status_code == 200
    r = web.post("/api/setup/finish", json={"build_mode": "auto"})
    assert r.status_code == 200 and r.json()["loop_settings"] is None
    assert not (tmp_path / "loop").exists()
