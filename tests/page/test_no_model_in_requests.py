"""The owner's rule (2026-10-11): no request the page's server answers waits on a model call. A
model-backed step runs in the background (the console, an Open in Claude Code session) with a
state the page shows.

Here a fake ``claude`` that records each call and then blocks for two minutes is first on PATH,
so a request that reached a model would hang past the bound, and the record would show it. The
build presses this file once covered (Publish anyway's pre-push checks) left with the factory."""
import os
import stat
import time

import pytest

from kranto.page.ui import api

from .app_common import call, make_home

BOUND_S = 10


@pytest.fixture
def world(tmp_path, monkeypatch):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    called = tmp_path / "model-called"
    shim = bin_dir / "claude"
    shim.write_text(f"#!/bin/sh\necho \"$*\" >> '{called}'\nsleep 120\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "no-claude-config"))
    cfg = make_home(tmp_path)
    return api.App(None, "fake", cfg.home), called


def test_no_read_of_the_page_waits_on_a_model(world):
    app, called = world
    paths = api.selfcheck_paths(app)
    assert "/api/header" in paths and "/api/activity" in paths
    for path in paths:
        t0 = time.time()
        code, _ = call(app, "GET", path)
        assert time.time() - t0 < BOUND_S, path
        assert code < 500 or code in (502, 503), (path, code)
    assert not called.exists(), called.read_text()


def test_the_console_settings_write_waits_on_no_model(world):
    app, called = world
    t0 = time.time()
    code, r = call(app, "POST", "/api/term/settings", body={"key": "term.daily_usd", "value": 3})
    assert code == 200 and time.time() - t0 < BOUND_S, r
    assert not called.exists()
