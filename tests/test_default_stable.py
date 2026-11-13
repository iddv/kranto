"""A setting's default by line (the owner, 2026-10-24: "a feature that isn't
done can ride a promotion with its stable default being the old behaviour"):
``Setting(default_stable=)``. Nightly takes ``default``; stable takes ``default_stable``; a value
written in kranto.yaml wins on both."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from kranto import launcher
from kranto.core import settings as settings_mod
from kranto.core import shell as shell_mod
from kranto.core.manifest import Setting, Settings

FEATURE = SimpleNamespace(id="demo", settings=Settings(keys={
    "demo.layout": Setting("enum", "new", choices=("new", "classic"), default_stable="classic"),
    "demo.plain": Setting("bool", True),
}))


@pytest.mark.parametrize("version, stable", [("0.6.2", True), ("0.7.0.dev12", False),
                                             ("0.5.27rc1", False), ("0.7.0.dev3+g1a2b3c4", False)])
def test_the_line_is_the_running_version(monkeypatch, version, stable):
    import kranto
    monkeypatch.setattr(kranto, "__version__", version)
    assert settings_mod.on_stable() is stable


def test_each_line_takes_its_default_and_a_written_value_wins(monkeypatch):
    monkeypatch.setattr(settings_mod, "on_stable", lambda: True)
    assert settings_mod.parse_section(FEATURE, {})["demo.layout"] == "classic"
    assert settings_mod.parse_section(FEATURE, {"layout": "new"})["demo.layout"] == "new"
    assert settings_mod.parse_section(FEATURE, {})["demo.plain"] is True
    rows = {r["key"]: r for r in settings_mod.describe(FEATURE, {})}
    assert rows["demo.layout"]["default"] == "classic" and rows["demo.layout"]["line"] == "stable"
    assert rows["demo.layout"]["default_other"] == "new"           # "nightly's default is new"
    assert rows["demo.plain"]["default_other"] is None
    monkeypatch.setattr(settings_mod, "on_stable", lambda: False)
    assert settings_mod.parse_section(FEATURE, {})["demo.layout"] == "new"
    assert settings_mod.parse_section(FEATURE, {"layout": "classic"})["demo.layout"] == "classic"
    rows = {r["key"]: r for r in settings_mod.describe(FEATURE, {})}
    assert rows["demo.layout"]["default_other"] == "classic" and rows["demo.layout"]["line"] == \
        "nightly"


def test_the_shell_reads_its_defaults_by_line(monkeypatch):
    keys = {**shell_mod.KEYS, "shell.layout": Setting("enum", "new", choices=("new", "classic"),
                                                      default_stable="classic")}
    monkeypatch.setattr(shell_mod, "KEYS", keys)
    monkeypatch.setattr(settings_mod, "on_stable", lambda: True)
    assert shell_mod.parse({})["shell.layout"] == "classic"
    monkeypatch.setattr(settings_mod, "on_stable", lambda: False)
    assert shell_mod.parse({})["shell.layout"] == "new"


def test_what_stays_off_on_stable_is_listed(monkeypatch, capsys):
    keys = {**shell_mod.KEYS, "shell.layout": Setting("enum", "new", choices=("new", "classic"),
                                                      default_stable="classic")}
    monkeypatch.setattr(shell_mod, "KEYS", keys)
    assert {"key": "shell.layout", "default": "new", "default_stable": "classic"} in \
        settings_mod.stable_defaults()
    assert launcher.main(["settings", "stable-defaults", "--json"]) == 0
    assert {"key": "shell.layout", "default": "new", "default_stable": "classic"} in \
        json.loads(capsys.readouterr().out)
    assert launcher.main(["settings", "stable-defaults"]) == 0
    assert "shell.layout: stable keeps 'classic' (nightly: 'new')" in capsys.readouterr().out
    assert launcher.main(["settings"]) == 2


def test_nothing_differs_by_line_today():
    """The owner's Q8: stable's layout stays New. No first-party setting has a stable default
    yet; the first big change that needs one adds it."""
    assert settings_mod.stable_defaults() == []
