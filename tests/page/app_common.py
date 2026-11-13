"""Shared set-up for the tests that call the app: the page's settings folder (``loop.yaml``) in
a temp dir, the app over it, and the fake ``claude`` (``fake_claude_stream.py``) first on PATH,
with a config dir of its own (no credentials of the owner's are ever copied)."""
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from kranto.page.settings.store import Config
from kranto.page.ui import api

FAKE = Path(__file__).parent / "fake_claude_stream.py"


def install_fake_claude(tmp: Path, monkeypatch) -> Path:
    bin_dir = tmp / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "claude"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    owner = tmp / "owner-claude"
    owner.mkdir(exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(owner))
    log = tmp / "fake-claude.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


def make_home(tmp: Path, **settings) -> Config:
    """A settings folder with a ``loop.yaml`` of ``settings`` (the page's own: term, ask,
    trace, feedback, the server), and its Config."""
    home = tmp / "loop"
    home.mkdir(parents=True, exist_ok=True)
    (home / "loop.yaml").write_text(yaml.safe_dump(settings or {}))
    return Config(home)


def make_app(tmp: Path, monkeypatch, **settings):
    """``(home, app, log)``: ``home.cfg`` is the settings' Config (the shape the tests read)."""
    cfg = make_home(tmp, **settings)
    log = install_fake_claude(tmp, monkeypatch)
    return SimpleNamespace(cfg=cfg), api.App(None, "fake", cfg.home), log


def call(app, method, path, query=None, body=None):
    code, ctype, data = api.handle(method, path, query,
                                   json.dumps(body).encode() if body is not None else None,
                                   app=app)
    return code, (json.loads(data) if ctype.startswith("application/json") else data)


def calls(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
