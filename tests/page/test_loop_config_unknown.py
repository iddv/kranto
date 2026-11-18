"""A rolled-back Kranto runs older code on a newer loop.yaml: a settings page of the newer version
may have written keys this version does not know. Config merges loop.yaml over DEFAULTS and must
keep ignoring such keys, never reject them, at the top level and inside a section."""

from kranto.page.settings.store import DEFAULTS, Config


def test_unknown_keys_are_kept_and_ignored(tmp_path):
    (tmp_path / "loop.yaml").write_text(
        "a_setting_from_the_future: {nested: true}\n"
        "term:\n  idle_min: 30\n  a_newer_term_key: 7\n"
        "trace:\n  a_newer_trace_key: [1, 2]\n")
    cfg = Config(tmp_path)
    assert cfg["term"]["idle_min"] == 30
    # everything this version knows still has its default
    assert cfg["term"]["max_sessions"] == DEFAULTS["term"]["max_sessions"]
    assert cfg["trace"]["page_kb"] == DEFAULTS["trace"]["page_kb"]
    assert cfg["feedback"] == DEFAULTS["feedback"]


def test_an_unknown_key_does_not_change_the_defaults(tmp_path):
    (tmp_path / "loop.yaml").write_text("trace:\n  export:\n    content: true\n    newer: x\n")
    Config(tmp_path)
    assert "newer" not in DEFAULTS["trace"]["export"]
