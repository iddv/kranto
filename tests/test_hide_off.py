"""What is off is hidden: a feature that is off and the cub shop. A
feature that is off has no pin, no tile and no verb (News stands in for any of Kranto's own); the
cub shop's routes and verbs need ``cubs.developer`` (off unless set); a feature's own skill is
not in the console's plugin while it is off. Turned on, each is back. The browser extension is
retired: its section in kranto.yaml is never read. No model call, no network."""

from __future__ import annotations

import shutil
from dataclasses import replace

import pytest

from kranto import assistant
from kranto import config as config_mod
from kranto.core import registry, settings, verbs
from kranto.core import shell as shell_mod
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

BASE = "http://127.0.0.1:8765"


def _features(rt, **on):  # noqa: F811
    rt.cfg = replace(rt.cfg, features={
        **(rt.cfg.features or {}),
        **{fid: {**settings.section(rt.cfg, fid), f"{fid}.enabled": v} for fid, v in on.items()}})


def _cubs(rt, **values):  # noqa: F811
    rt.cfg = replace(rt.cfg, cubs={**(rt.cfg.cubs or {}), **values})


def test_off_by_default():
    from kranto.core.cubs import settings as cub_settings
    assert cub_settings.GLOBAL["cubs.developer"].default is False


def test_a_feature_that_is_off_has_no_pin_and_comes_back(rt, monkeypatch):  # noqa: F811
    # News is one of the home's doors, never a pin: a feature of Kranto's own that is not
    from kranto import features as features_pkg
    from kranto.core.manifest import Feature, Setting, Settings
    demo = Feature(id="demo", title="Demo", says="A feature for this test.", version="1.0.0",
                   settings=Settings(keys={"demo.enabled": Setting("bool", True)}))
    monkeypatch.setattr(features_pkg, "FEATURES", (*features_pkg.FEATURES, demo))
    verbs.configure(builds=False, rt=rt)
    rt.cfg = replace(rt.cfg, shell={**shell_mod.parse({}), "shell.pins": ["demo"]})
    _features(rt, demo=False)
    got = shell_mod.arrangement(rt.cfg, registry.features())
    assert got["pins"] == [] and "demo" not in {c["id"] for c in got["cubs"]}
    _features(rt, demo=True)
    assert shell_mod.arrangement(rt.cfg, registry.features())["pins"] == ["demo"]


def test_a_built_in_feature_that_is_off_is_not_listed(rt):  # noqa: F811
    # no Cubs row, Settings page or palette entry: the page lists what /api/features answers
    _features(rt, news=False)
    with web_client(create_app(rt), BASE) as web:
        ids = {f["id"] for f in web.get("/api/features").json()["features"]}
    assert "news" not in ids
    _features(rt, news=True)
    assert "news" in {f["id"] for f in registry.describe(rt)["features"]}


def test_what_a_feature_that_is_off_left_waiting_is_not_drawn(rt):  # noqa: F811
    # a feature's run stopped for you, then the feature was turned off
    from kranto import activity
    with activity.run(rt.store, "news.brief") as r:
        r.waiting("News wrote a brief and waits for you")
    activity.flush(5)
    _features(rt, news=False)
    with web_client(create_app(rt), BASE) as web:
        assert web.get("/api/activity").json()["waiting"] == []
    _features(rt, news=True)
    with web_client(create_app(rt), BASE) as web:
        assert [w["kind"] for w in web.get("/api/activity").json()["waiting"]] == ["news.brief"]


def test_a_cub_the_owner_turned_off_is_still_listed(rt, monkeypatch):  # noqa: F811
    # so it can be turned on again: only Kranto's own features leave the list while off
    from types import SimpleNamespace
    cub = SimpleNamespace(id="toot", data=object())   # a cub: it carries its runtime's data
    monkeypatch.setattr(registry, "enabled", lambda cfg, f: False)
    assert registry.listed(rt.cfg, cub) is True
    assert registry.listed(rt.cfg, registry.by_id("news")) is False


def test_a_feature_that_is_off_offers_no_verb(rt):  # noqa: F811
    verbs.configure(builds=False, rt=rt)
    _features(rt, news=False)
    kinds = {v.kind for v in verbs.all_verbs()}
    assert not [k for k in kinds if k.startswith("f.news.")]
    assert verbs.get("f.news.write_now") is None
    _features(rt, news=True)
    assert "f.news.write_now" in {v.kind for v in verbs.all_verbs()}
    assert verbs.get("f.news.write_now") is not None


def test_the_browser_extension_is_retired(rt, tmp_path):  # noqa: F811
    # a browser: section still in kranto.yaml loads and is never read; the status says no browser
    (tmp_path / "kranto.yaml").write_text(
        config_mod.DEFAULT_CONFIG_YAML + "\nbrowser:\n  enabled: true\n", encoding="utf-8")
    cfg = config_mod.load(tmp_path, dotenv=False)
    assert "browser" in cfg.retired and not hasattr(cfg, "browser")
    verbs.configure(builds=False, rt=rt)
    assert not [v for v in verbs.all_verbs() if v.kind.startswith("browser.")]
    with web_client(create_app(rt), BASE) as web:
        assert web.get("/api/status").json()["browser"] is False


def test_the_cub_shop_needs_cubs_developer(rt):  # noqa: F811
    verbs.configure(builds=False, rt=rt)
    kinds = {v.kind for v in verbs.all_verbs()}
    assert not kinds & verbs.SHOP and "cub.enable" in kinds and "cub.dry" in kinds
    with web_client(create_app(rt), BASE) as web:
        assert web.get("/api/status").json()["cubs_developer"] is False
        for path, body in (("/api/cubs/check", {"text": "id: x"}), ("/api/cubs/fetch", {}),
                           ("/api/cubs/x/install", {}), ("/api/cubs/x/apply_update", {}),
                           ("/api/cubs/x/remove", {})):
            r = web.post(path, json=body)
            assert r.status_code == 404 and "cubs.developer" in r.json()["error"], path
        assert web.get("/api/cubs").status_code == 200              # your cubs stay
    _cubs(rt, **{"cubs.developer": True})
    assert {v.kind for v in verbs.all_verbs()} >= verbs.SHOP
    with web_client(create_app(rt), BASE) as web:
        assert web.post("/api/cubs/check", json={"text": "id: x"}).status_code != 404
        assert web.get("/api/status").json()["cubs_developer"] is True


@pytest.fixture
def news_skill(tmp_path, monkeypatch):
    """A copy of the plugin with a skill of News's own, as a feature's skill would be (no
    feature ships one now: ``FEATURE_SKILLS`` is empty)."""
    plugin = tmp_path / "wheel" / "plugin"
    shutil.copytree(assistant.PLUGIN_DIR, plugin, ignore=shutil.ignore_patterns("__pycache__"))
    (plugin / "skills" / "news").mkdir()
    (plugin / "skills" / "news" / "SKILL.md").write_text("---\nname: news\n---\nNews.\n",
                                                         encoding="utf-8")
    monkeypatch.setattr(assistant, "PLUGIN_DIR", plugin)
    monkeypatch.setattr(assistant, "SKILLS", (*assistant.SKILLS, "news"))
    monkeypatch.setattr(assistant, "FEATURE_SKILLS", {"news": "news"})
    yield
    assistant.configure(off_features=())


def test_the_consoles_plugin_leaves_out_the_skill_of_a_feature_that_is_off(tmp_path,
                                                                           news_skill):
    home = tmp_path / "home"
    assistant.configure(off_features={"news"})
    assert "news" not in assistant.skills_now()
    copy = assistant.console_plugin(home)
    assert copy == home / "assistant" / "plugin"
    assert (copy / ".claude-plugin" / "plugin.json").is_file()
    assert (copy / "skills" / "kranto" / "SKILL.md").is_file()
    assert not (copy / "skills" / "news").exists()
    assert ".agents/skills/news/SKILL.md" not in assistant.home_files()
    assistant.configure(off_features=())
    assert assistant.console_plugin(home) is None and not copy.exists()
    assert "news" in assistant.skills_now()
    assert ".agents/skills/news/SKILL.md" in assistant.home_files()


@pytest.mark.parametrize("off", [True, False])
def test_the_runtime_says_which_skills_are_off(rt, news_skill, off):  # noqa: F811
    from kranto.runtime import open_runtime
    _features(rt, news=not off)
    rt2 = open_runtime(rt.cfg, store=rt.store, embedder=rt.embedder, llm=rt.llm, http=rt.http)
    try:
        assert ("news" in assistant.skills_now()) is (not off)
    finally:
        assistant.configure(off_features=())
        del rt2
