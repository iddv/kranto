"""A new home's console does not open by itself and asks before every edit and command; a home
whose loop.yaml does not say keeps what it had (opens by itself, auto mode); doctor says which.

The decision is the operator's (S1, 2026-11-17): a person turns the console up in Settings ›
Assistant. ``kranto up`` writes ``console.NEW_HOME_YAML`` into a new home's loop.yaml."""
import yaml

from kranto.page.settings.store import Config
from kranto.page.term import console as C


def test_a_home_that_does_not_say_keeps_what_it_had():
    """Live and every home made before: no ``ask:`` in loop.yaml, so nothing changes."""
    assert C.DEFAULTS["open"] is True and C.DEFAULTS["permission"] == "auto"
    s = C.settings({})
    assert s["open"] is True and s["permission"] == "auto"
    d = C.describe({})
    assert d["said"] is False and d["open"] is True and d["permission"] == "auto"
    assert d["words"] == ("opens by itself; decides edits and commands by itself (Claude "
                          "Code's auto mode) (Kranto's default when loop.yaml does not say; "
                          "Settings › Assistant changes it)")


def test_the_new_home_text_closes_the_console_and_asks():
    raw = yaml.safe_load(C.NEW_HOME_YAML)
    assert raw == {"ask": C.NEW_HOME}
    assert C.NEW_HOME == {"open": False, "permission": "ask"}
    s = C.settings(raw)
    assert s["open"] is False and s["permission"] == "ask"
    assert s["config"] == C.DEFAULTS["config"] and s["daily_usd"] is None
    d = C.describe(raw)
    assert d["said"] is True
    assert d["words"] == (f"opens when you click ✦ (or {C.open_key()}); asks before every edit "
                          "and command (Settings › Assistant changes it)")
    assert C.CLAUDE_MODE[s["permission"]] == "default"    # Claude Code's own asking mode


def test_the_console_key_is_named_as_the_machine_names_it(monkeypatch):
    """Ctrl+J on Linux and Windows, ⌘J on a Mac: doctor's line is read in a terminal there."""
    assert C.open_key("linux") == "Ctrl+J" and C.open_key("win32") == "Ctrl+J"
    assert C.open_key("darwin") == "⌘J"
    monkeypatch.setattr("sys.platform", "linux")
    assert "(or Ctrl+J)" in C.describe(yaml.safe_load(C.NEW_HOME_YAML))["words"]
    monkeypatch.setattr("sys.platform", "darwin")
    assert "(or ⌘J)" in C.describe(yaml.safe_load(C.NEW_HOME_YAML))["words"]


def test_the_page_reads_a_new_homes_loop_yaml_as_closed_and_asking(tmp_path):
    """Through the page's settings store, merged with its DEFAULTS, as the console reads it."""
    (tmp_path / "loop.yaml").write_text("concurrency: 1\n" + C.NEW_HOME_YAML)
    s = C.settings(Config(tmp_path).data)
    assert s["open"] is False and s["permission"] == "ask"
    assert C.doctor_line(tmp_path).startswith("opens when you click ✦")


def test_the_doctor_line_reads_the_file_as_written(tmp_path):
    assert "Kranto's default when loop.yaml does not say" in C.doctor_line(tmp_path)  # no file
    (tmp_path / "loop.yaml").write_text("concurrency: 1\n")
    assert C.doctor_line(tmp_path).startswith("opens by itself; decides edits")
    (tmp_path / "loop.yaml").write_text("ask:\n  open: true\n  permission: accept-edits\n")
    assert C.doctor_line(tmp_path) == ("opens by itself; makes edits by itself and asks before "
                                       "commands (Settings › Assistant changes it)")
    (tmp_path / "loop.yaml").write_text("ask: [not, a, map\n")
    assert "Kranto's default" in C.doctor_line(tmp_path)


def test_every_permission_has_its_words():
    assert set(C.PERMISSION_WORDS) == set(C.PERMISSIONS)
