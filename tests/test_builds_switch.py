"""Builds behind one switch: ``builds.enabled``, off unless set.

``brb.enabled`` is the page at /brb/; ``builds.enabled`` is the half of it that builds. With the
page mounted and builds off: no ``b.*`` verb for any door (the guard still refuses an assistant's
``api/act``, so nothing reaches the loop around the ladder), ``/api/status`` says so for the page,
Pause leaves the loop's PAUSE file alone, and the page is told. No model call, no network."""

import pytest

from kranto import config as config_mod
from kranto import tokens
from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    ConfigError,
    IngestConfig,
    MapConfig,
)
from kranto.core import verbs
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, web_client
from .test_verbs_brb import ActApi

BASE = "http://127.0.0.1:8765"
HEAD = "llm:\n  base_url: x\n  api_key_env: K\n  models: {judge: a, reason: b}\n"


def test_absent_means_off_and_the_value_is_checked(tmp_path):
    (tmp_path / "kranto.yaml").write_text(HEAD + "brb:\n  enabled: true\n")
    cfg = config_mod.load(tmp_path, dotenv=False)
    assert cfg.builds == BuildsConfig() and cfg.builds.enabled is False
    assert not config_mod.builds_on(cfg)
    for empty in ("builds:\n", "builds: {}\n", "builds: null\n"):
        (tmp_path / "kranto.yaml").write_text(HEAD + "brb:\n  enabled: true\n" + empty)
        assert not config_mod.builds_on(config_mod.load(tmp_path, dotenv=False)), empty
    (tmp_path / "kranto.yaml").write_text(HEAD + "brb:\n  enabled: true\n"
                                                   "builds:\n  enabled: true\n")
    assert config_mod.builds_on(config_mod.load(tmp_path, dotenv=False))
    # builds need the page: on without brb is off
    (tmp_path / "kranto.yaml").write_text(HEAD + "builds:\n  enabled: true\n")
    assert not config_mod.builds_on(config_mod.load(tmp_path, dotenv=False))
    assert not config_mod.builds_on(None)
    for bad in ("builds: {enabled: yes please}", "builds: {nope: 1}"):
        (tmp_path / "kranto.yaml").write_text(HEAD + bad + "\n")
        with pytest.raises(ConfigError):
            config_mod.load(tmp_path, dotenv=False)


def test_the_default_config_says_builds_are_off():
    assert "builds:\n" in config_mod.DEFAULT_CONFIG_YAML
    block = config_mod.DEFAULT_CONFIG_YAML.split("builds:\n", 1)[1].split("\n\n", 1)[0]
    assert "enabled: false" in block


@pytest.fixture
def api(monkeypatch):
    fake = ActApi()
    fake.configured_with = {}

    def configure(root=None, harness="claude-code", loop_home=None, builds=None):
        fake.configured_with = {"root": root, "builds": builds}

    fake.configure = configure          # a the page that takes the switch
    return brbfake.install(monkeypatch, fake)


def _app(tmp_path, store, embedder, make_client, builds):
    (tmp_path / "kranto.yaml").write_text(HEAD)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(),
                 brb=BrbConfig(enabled=True, root=str(tmp_path / "tasks")),
                 builds=BuildsConfig(enabled=builds))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    return create_app(rt, port=8765)


def bearer(name):
    tokens.Store().ensure_doors()
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def test_builds_off_no_build_verb_and_no_way_around_the_ladder(tmp_path, store, embedder,
                                                                make_client, api):
    app = _app(tmp_path, store, embedder, make_client, builds=False)
    assert verbs.brb_verbs() == () and verbs.get("b.retry") is None
    assert verbs.brb_verbs(gated=False)          # the page has verbs: the guard knows it
    with web_client(app, BASE, signed_in=False) as web:
        kinds = [v["kind"] for v in web.get("/api/verbs").json()["verbs"]]
        assert kinds and not [k for k in kinds if k.startswith("b.")]
        r = web.post("/api/verbs/b.retry", headers=bearer("console"),
                     json={"subject": {"kind": "build", "id": "x"}})
        assert r.status_code in (400, 404), r.text
        body = {"kind": "retry", "subject": {"kind": "build", "id": "x"}}
        for who in ("mcp", "console"):
            r = web.post("/brb/api/act", headers=bearer(who), json=body)
            assert r.status_code == 403, who
    assert not [c for c in api.calls if len(c) == 5]   # nothing reached the loop's api/act


def test_builds_off_status_and_pause(tmp_path, store, embedder, make_client, api):
    app = _app(tmp_path, store, embedder, make_client, builds=False)
    assert api.configured_with.get("builds") is False
    with web_client(app, BASE) as web:
        assert web.get("/api/status").json()["builds"] is False
        r = web.post("/pause", data={"reason": "night"}, headers={"accept": "application/json"})
        assert r.status_code == 200 and r.json()["ok"], r.text
    assert store.pause_reason() == "night" and not api.paused   # the loop's left alone


def test_status_has_no_loop_line_while_builds_are_off(tmp_path, monkeypatch, capsys):
    """The acceptance's `kranto status`: no loop lane, loop, build spend or build login line, and
    still well; the watching spend is said."""
    from kranto import launcher

    from .test_kranto import FakeMachine, make_host
    user_home = tmp_path / "u"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    launcher.make_home(user_home / ".kranto", 8765, user_home)
    assert config_mod.load(user_home / ".kranto", dotenv=False).brb.enabled   # the page is on
    status = {"version": "0.1.0", "scheduler": True, "paused": None, "lanes": {}}
    host = make_host(user_home, FakeMachine(active={"kranto.service": "active"}), status=status)
    host.machine.enabled["kranto.service"] = "enabled"
    assert launcher.main(["status"], host) == 0
    out = capsys.readouterr().out
    names = {line.split()[0] for line in out.splitlines() if line.strip()}
    assert not {"loop", "claude"} & names, out
    assert "loop lane" not in out and "builds" not in out and "broker" not in out.lower()
    assert "spend      watching $0.00 this month" in out


def test_doctor_has_no_build_word_while_builds_are_off(tmp_path, monkeypatch):
    """The word test's doctor half: the launcher's checks never say build or publish, and have
    no GitHub, build login or claude token line; gh is a warning at most ('File a Kranto issue'
    files through it), and the console's line says what it needs."""
    from kranto import launcher

    from .test_kranto import FakeMachine, make_host
    user_home = tmp_path / "u"
    user_home.mkdir()
    monkeypatch.setenv("HOME", str(user_home))
    launcher.make_home(user_home / ".kranto", 8765, user_home)
    host = make_host(user_home, FakeMachine(rc={"claude": 1, "bwrap": 1, "gh": 1}))
    checks = {c.name: c for c in launcher.prerequisite_checks(user_home / ".kranto", host)}
    assert {"claude", "bwrap", "uv", "gh"} <= set(checks)
    assert checks["gh"].status == launcher.WARN
    assert not {"github", "build login", "claude token"} & set(checks)
    for c in checks.values():
        assert "build" not in c.detail.lower() and "publish" not in c.detail.lower(), c


def test_builds_on_in_the_file_still_tells_the_page_off(tmp_path, store, embedder, make_client,
                                                        api):
    """CUT: a the page that still takes the switch is told builds are off, whatever the file
    says (its verbs' listing is core.verbs', until its own cut)."""
    app = _app(tmp_path, store, embedder, make_client, builds=True)
    assert api.configured_with.get("builds") is False
    assert verbs.get("b.retry") is not None
    with web_client(app, BASE) as web:
        assert web.get("/api/status").json()["builds"] is True
        assert [v for v in web.get("/api/verbs").json()["verbs"] if v["kind"] == "b.retry"]
