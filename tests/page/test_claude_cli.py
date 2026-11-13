"""``build.claude_command``: the Claude Code binary ``kranto setup --claude
PATH`` (or the wizard, finding it off PATH) keeps in loop.yaml, used by the console, Open in
Claude Code and the single-shot calls; unset, or naming nothing, ``claude`` on PATH as before."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from kranto.page import claude_cli
from kranto.page.box import sandbox
from kranto.page.settings.store import DEFAULTS
from kranto.page.term import launch


def _exe(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return p


def _loop(tmp_path, monkeypatch, build: dict) -> Path:
    home = tmp_path / "loop"
    home.mkdir()
    (home / "loop.yaml").write_text(yaml.safe_dump({"build": build}))
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(home))
    return home


def test_the_setting_exists_and_is_null_by_default():
    assert "claude_command" in DEFAULTS["build"] and DEFAULTS["build"]["claude_command"] is None


def test_unset_is_claude_on_path_as_before(tmp_path, monkeypatch):
    _loop(tmp_path, monkeypatch, {})
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert claude_cli.configured() is None and claude_cli.find() == "/usr/bin/claude"
    assert launch.claude_binary() == "/usr/bin/claude"


def test_the_configured_binary_is_used_everywhere(tmp_path, monkeypatch):
    exe = _exe(tmp_path / "nvm" / "v22" / "bin" / "claude")
    _loop(tmp_path, monkeypatch, {"claude_command": str(exe)})
    monkeypatch.setattr(shutil, "which", lambda name: None)       # PATH has none
    assert claude_cli.find() == str(exe)
    assert launch.claude_binary() == str(exe)
    assert sandbox.claude_binary() == exe.resolve()


def test_a_setting_that_names_nothing_falls_back_to_path(tmp_path, monkeypatch):
    _loop(tmp_path, monkeypatch, {"claude_command": str(tmp_path / "gone" / "claude")})
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert claude_cli.configured() == str(tmp_path / "gone" / "claude")
    assert claude_cli.configured_exe() is None and claude_cli.find() == "/usr/bin/claude"


def test_a_tilde_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    exe = _exe(tmp_path / ".local" / "bin" / "claude")
    _loop(tmp_path, monkeypatch, {"claude_command": "~/.local/bin/claude"})
    assert claude_cli.find() == str(exe)
