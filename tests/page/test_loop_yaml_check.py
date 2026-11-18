"""loop.yaml checked against DEFAULTS. An unknown key or a wrong value is said once and never
refused: a rolled-back Kranto reads a newer file (test_loop_config_unknown.py), and a typo must
never stop Kranto. A key an older Kranto read (the build loop's) is neither: it is said nowhere."""
import logging

from kranto.page.settings import schema
from kranto.page.settings.store import DEFAULTS, Config


def test_the_defaults_and_an_empty_file_have_no_problems(tmp_path):
    assert schema.check(DEFAULTS) == [] and schema.check({}) == [] and schema.check(None) == []
    assert Config(tmp_path).problems == []


def test_unknown_keys_are_listed_never_refused(tmp_path, caplog):
    (tmp_path / "loop.yaml").write_text(
        "term:\n  idle_min: 30\n  idle_mni: 3\ntrace:\n  page_kb: 32\ntrcae: {}\n")
    with caplog.at_level(logging.WARNING, logger="kranto.page.settings"):
        cfg = Config(tmp_path)
        Config(tmp_path)                                   # said once per file version
    assert cfg["term"]["idle_min"] == 30 and cfg["trace"]["page_kb"] == 32
    assert {(p["kind"], p["key"]) for p in cfg.problems} == {
        ("unknown", "term.idle_mni"), ("unknown", "trcae")}
    said = [r.getMessage() for r in caplog.records if r.name == "kranto.page.settings"]
    assert len(said) == 1 and "2 unknown keys (ignored)" in said[0] and "idle_mni" in said[0]


def test_the_build_loops_keys_are_read_without_a_word(tmp_path, caplog):
    """A file written before the build loop left: every section it had, and the build
    section's own keys, are retired; the two build keys the console reads still count."""
    (tmp_path / "loop.yaml").write_text(
        "tasks_dir: ~/tasks\nconcurrency: 2\ndaily_usd: 5\ntick_s: soon\n"
        "intake:\n  auto:\n    mode: editor\n"
        "build:\n  retries: 2\n  models:\n    verify: claude-opus-5-5\n  stage_caps: lots\n"
        "  claude_command: /opt/claude\n"
        "publish:\n  approval: auto\nmaintain:\n  poll_s: 60\nprojects:\n  enabled: true\n"
        "capabilities:\n  rea:\n    enabled: true\nchat:\n  auto: yes\n"
        "kranto:\n  db: /x/kranto.db\n  url: http://127.0.0.1:8765\n")
    with caplog.at_level(logging.WARNING, logger="kranto.page.settings"):
        cfg = Config(tmp_path)
    assert cfg.problems == [] and not [r for r in caplog.records
                                       if r.name == "kranto.page.settings"]
    assert cfg["build"]["claude_command"] == "/opt/claude"
    assert cfg["kranto"]["url"] == "http://127.0.0.1:8765"


def test_a_wrong_value_is_said_and_refuses_nothing(tmp_path):
    (tmp_path / "loop.yaml").write_text(
        "term:\n  idle_min: soon\n  daily_usd: lots\nbuild:\n  allow_api_key: maybe\n")
    cfg = Config(tmp_path)
    assert {p["key"] for p in cfg.problems if p["kind"] == "type"} == {
        "term.idle_min", "term.daily_usd", "build.allow_api_key"}
    line = schema.describe(cfg.problems)
    assert "3 wrong values" in line and "number of dollars" in line


def test_the_console_keeps_one_default_for_each_of_its_settings(tmp_path):
    """``ask`` is empty here: the console's own defaults (``console.DEFAULTS``) are what an
    empty file reads as, through Config as the page reads it."""
    from kranto.page.term import console
    assert DEFAULTS["ask"] == {}
    assert console.settings(Config(tmp_path).data) == console.DEFAULTS
    # a home whose loop.yaml has no ask: section (an existing install) keeps what it ran on:
    # open when Kranto opens, Claude Code's auto mode, the person's own configuration
    got = console.settings(Config(tmp_path).data)
    assert (got["open"], got["permission"], got["config"]) == (True, "auto", "own")
    (tmp_path / "loop.yaml").write_text("ask:\n  open: false\n  colour: blue\n")
    cfg = Config(tmp_path)
    assert cfg.problems == [] and console.settings(cfg.data)["open"] is False
