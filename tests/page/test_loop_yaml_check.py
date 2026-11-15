"""loop.yaml checked against DEFAULTS (S-6b; review D-4). An unknown key only warns:
a rolled-back kranto reads a newer file (test_loop_config_unknown.py), and a typo must never
stop Kranto. A wrong value under the build's caps or models keeps builds from starting, with
the reason said, instead of running without them."""
import logging

import pytest

from kranto.page.settings import schema
from kranto.page.settings.store import DEFAULTS, Config


def test_the_defaults_and_an_empty_file_have_no_problems(tmp_path):
    assert schema.check(DEFAULTS) == [] and schema.check({}) == [] and schema.check(None) == []
    assert Config(tmp_path).problems == []


def test_unknown_keys_are_listed_never_refused(tmp_path, caplog):
    (tmp_path / "loop.yaml").write_text(
        "concurrency: 2\nconcurency: 3\nbuild:\n  retries: 2\n  retires: 1\n"
        "capabilities:\n  rea:\n    enabled: true\n    pin: abc\n    scope: pipeline\n"
        "    stages: [build]\n    traits: []\n    settings: {}\n    enabeld: true\n"
        "  max_heavy_concurrent: 1\n")
    with caplog.at_level(logging.WARNING, logger="kranto.page.settings"):
        cfg = Config(tmp_path)
        Config(tmp_path)                                   # said once per file version
    assert cfg["concurrency"] == 2 and cfg["build"]["retries"] == 2
    assert {(p["kind"], p["key"]) for p in cfg.problems} == {
        ("unknown", "concurency"), ("unknown", "build.retires"),
        ("unknown", "capabilities.rea.enabeld")}
    assert schema.refuses_builds(cfg.problems) == []
    said = [r.getMessage() for r in caplog.records if r.name == "kranto.page.settings"]
    assert len(said) == 1 and "3 unknown keys (ignored)" in said[0] and "concurency" in said[0]


def test_free_form_maps_take_any_key(tmp_path):
    (tmp_path / "loop.yaml").write_text(
        "build:\n  models:\n    verify: claude-opus-5-5\n  stage_caps:\n    build: 3.0\n")
    assert Config(tmp_path).problems == []


@pytest.mark.parametrize("text, key", [
    ("build:\n  stage_caps: lots\n", "build.stage_caps"),
    ("build:\n  models: [opus]\n", "build.models"),
    ("daily_usd: [5]\n", "daily_usd"),
])
def test_a_wrong_value_under_the_caps_or_models_refuses_builds(tmp_path, text, key):
    (tmp_path / "loop.yaml").write_text(text)
    bad = schema.refuses_builds(Config(tmp_path).problems)
    assert [p["key"] for p in bad] == [key]
    assert key in schema.describe(bad) and "wrong value" in schema.describe(bad)


def test_a_wrong_value_elsewhere_is_said_but_refuses_nothing(tmp_path):
    (tmp_path / "loop.yaml").write_text("tick_s: soon\nchat:\n  auto: yes please\n  colour: blue\n")
    cfg = Config(tmp_path)
    assert {p["key"] for p in cfg.problems if p["kind"] == "type"} == {"tick_s"}
    # chat.auto is retired (read no more, said no more); chat.colour was never a key
    assert {p["key"] for p in cfg.problems if p["kind"] == "unknown"} == {"chat.colour"}
    assert schema.refuses_builds(cfg.problems) == []

