"""Settings › Watching and Welcome open without waiting on ``claude`` or ``gh`` (SL).

``/api/setup`` shows the two logins (``claude auth status``, ``gh auth status``) and
``/api/setup/provider`` Claude Code's version and login: about half a second of processes. The
last answer comes back at once; one older than ``LOGIN_CACHE_SECONDS`` is asked again on a
background thread. An audit hook watches the asking thread: no process the second time. The
``claude`` and ``gh`` here are scripts on a temporary PATH; nothing reaches the network.
"""
import os
import stat
import sys
import threading
import time

import pytest

from kranto import providers, setup

_WATCH: dict = {"thread": None, "seen": []}


def _hook(event, args):
    if _WATCH["thread"] == threading.get_ident() and event in ("subprocess.Popen",
                                                               "os.posix_spawn"):
        _WATCH["seen"].append(repr(args)[:120])


sys.addaudithook(_hook)


@pytest.fixture
def tools(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "asked.txt"
    login = '{"loggedIn": true, "authMethod": "claude.ai"}'
    for name, text in (("claude", "1.2.3 (Claude Code)"),
                       ("gh", "github.com\n  Logged in to github.com account octo (keyring)")):
        p = bin_ / name
        status = login if name == "claude" else text
        p.write_text(f"#!{sys.executable}\nimport sys\n"
                     f"a = ' '.join(sys.argv[1:])\n"
                     f"open({str(log)!r}, 'a').write({name!r} + ' ' + a + '\\n')\n"
                     f"print({status!r} if a == 'auth status' else {text!r})\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(setup, "RUN", setup._run)
    monkeypatch.setattr(setup, "_logins", None)
    monkeypatch.setattr(providers, "_claude_seen", None)
    monkeypatch.setattr(setup, "connection", lambda: None)
    return log


def asked(log) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def settle():
    for t in [t for t in threading.enumerate() if t.name.startswith("kranto-")]:
        t.join(10)


def watched(fn):
    _WATCH["seen"], _WATCH["thread"] = [], threading.get_ident()
    try:
        return fn(), list(_WATCH["seen"])
    finally:
        _WATCH["thread"] = None


def test_the_logins_and_claude_code_come_back_at_once_and_are_asked_again_behind(
        tools, tmp_path, monkeypatch):
    first, seen = watched(setup.logins)                 # the first ask waits for them
    assert first["claude"]["ok"] and first["gh"]["ok"] and seen
    cc, seen = watched(lambda: providers.detect(tmp_path)["claude_code"])
    assert cc["installed"] and cc["version"] == "1.2.3" and cc["logged_in"] and seen
    n = len(asked(tools))
    monkeypatch.setattr(setup, "LOGIN_CACHE_SECONDS", 0.0)   # every answer old at once
    t = time.monotonic()
    again, seen = watched(setup.logins)
    assert again == first and seen == []
    cc2, seen = watched(lambda: providers.detect(tmp_path)["claude_code"])
    assert cc2["version"] == "1.2.3" and seen == []
    assert time.monotonic() - t < 1.0
    settle()
    assert len(asked(tools)) > n                         # asked again, in the background
    _, seen = watched(lambda: setup.logins(fresh=True))  # Check again waits for the answer
    assert seen


def test_warm_asks_both_in_the_background(tools):
    _, seen = watched(setup.warm)
    assert seen == []
    settle()
    assert {x.split()[0] for x in asked(tools)} == {"claude", "gh"}
    _, seen = watched(setup.logins)
    assert seen == []
