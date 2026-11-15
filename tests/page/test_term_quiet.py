"""Open in Claude Code without Claude Code's own background noise, and with plain words for its
end: the CLI's switches for its updater and telemetry are on, its remaining background hosts are
refused without a card (``quiet``), the page says why a session ended, and ``kranto doctor``'s line
judges the PATH and token it is given (the service's). No model, no network: every request here is
refused before a name is looked up."""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

from kranto.page.term import launch, service

from .term_common import canary, install_fake_claude, make_term


def test_the_session_starts_with_claude_codes_switches_and_never_the_nonessential_one(tmp_path):
    spec = launch.Spec(tid="t1", session="s", resume=False, tdir=tmp_path, cwd=tmp_path,
                       sandboxed=False)
    env = launch.env(spec, "CLAUDE_CODE_OAUTH_TOKEN", 7,
                     {"CLAUDE_CODE_OAUTH_TOKEN": canary("claude"), "PATH": "/bin",
                      "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    for k in ("DISABLE_AUTOUPDATER", "DISABLE_UPDATES", "DISABLE_TELEMETRY",
              "DISABLE_ERROR_REPORTING", "CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL"):
        assert env[k] == "1"
    # it hid Kranto's propose tool (2.1.287): never set, even when Kranto's own environment has it
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in env
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" not in launch.QUIET_ENV


def _connect(sock: Path, host: str) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect(str(sock))
    s.sendall(f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode())
    out = b""
    while chunk := s.recv(4096):
        out += chunk
    s.close()
    return out


def test_claude_codes_background_hosts_are_refused_quietly_and_others_ask(tmp_path, monkeypatch):
    monkeypatch.delenv("KRANTO_WORKER_NET", raising=False)
    term = make_term(tmp_path, monkeypatch, token=canary("claude"))
    tid = term.store.new_tid()
    term.store.dir(tid).mkdir(parents=True)
    term.store.put({"tid": tid, "key": "idea:i1", "net": {"allowed": [], "asked": []}})
    px = term._proxy(tid)
    try:
        for host in ("downloads.claude.ai", "http-intake.logs.us5.datadoghq.com",
                     "raw.githubusercontent.com", "example.org"):
            assert _connect(px.sock, host).startswith(b"HTTP/1.1 403 ")
    finally:
        px.__exit__(None, None, None)
    rec = term.store.get(tid)
    assert rec["net"]["asked"] == ["example.org"]                 # the only card
    log = [json.loads(ln) for ln in (term.store.dir(tid) / "net.jsonl").read_text().splitlines()]
    assert [(x["verdict"], x["host"]) for x in log] == [
        ("quiet", "downloads.claude.ai"), ("quiet", "http-intake.logs.us5.datadoghq.com"),
        ("quiet", "raw.githubusercontent.com"), ("refused", "example.org")]


def test_questions_asked_before_a_host_was_quiet_are_not_cards(tmp_path, monkeypatch):
    """Live's first session (0.3.65) recorded four questions about Claude Code's own hosts; the
    page draws each asked host as a card, so they would come back on the next Open."""
    term = make_term(tmp_path, monkeypatch, token=canary("claude"))
    tid = term.store.new_tid()
    term.store.dir(tid).mkdir(parents=True)
    old = ["raw.githubusercontent.com", "downloads.claude.ai", "github.com",
           "http-intake.logs.us5.datadoghq.com"]
    term.store.put({"tid": tid, "key": "build:receipts", "state": "ended", "reason": "outside",
                    "net": {"allowed": [], "asked": old}})
    assert term.get(tid)["net"]["asked"] == ["github.com"]          # not Claude Code's own
    assert term.store.get(tid)["net"]["asked"] == old              # the record is kept as is


def test_a_quiet_host_the_owner_lists_is_allowed(tmp_path, monkeypatch):
    term = make_term(tmp_path, monkeypatch, token=canary("claude"),
                     net_hosts=["api.anthropic.com", "raw.githubusercontent.com"])
    tid = term.store.new_tid()
    term.store.dir(tid).mkdir(parents=True)
    term.store.put({"tid": tid, "key": "idea:i1", "net": {"allowed": [], "asked": []}})
    px = term._proxy(tid)
    try:
        assert px.host_ok("raw.githubusercontent.com") and not px.host_ok("downloads.claude.ai")
    finally:
        px.__exit__(None, None, None)


def test_the_page_says_why_a_session_ended(tmp_path, monkeypatch):
    term = make_term(tmp_path, monkeypatch, token=canary("claude"))
    base = {"tid": "abcd1234", "state": "ended"}

    def words(**r):
        return term.view({**base, **r})["words"]
    assert words(reason="exit", code=-9) == "The session was stopped unexpectedly (signal 9)"
    assert words(reason="exit", code=137) == "The session was stopped unexpectedly (signal 9)"
    assert words(reason="exit", code=0) == "Claude Code exited"
    assert words(reason="exit", code=1) == "Claude Code exited with code 1"
    assert words(reason="idle") == "Ended after 60 minutes idle"
    assert words(reason="cap") == "Ended: today's spend cap was reached"
    assert words(reason="owner") == "Ended by you"
    assert words(reason="restart") == "Ended when Kranto restarted"
    assert words(reason="outside") == "Continued outside"
    assert words(reason="error", error="bwrap: no") == "Claude Code could not start: bwrap: no"
    # the page asks the moment the exit frame arrives, before the record has the reason
    pty = SimpleNamespace(alive=False, code=-9, viewers=0)
    term.live["abcd1234"] = service.Live("abcd1234", pty, None, None, tmp_path / "t.jsonl")
    try:
        assert words(state="running", reason=None) == \
            "The session was stopped unexpectedly (signal 9)"
    finally:
        term.live.pop("abcd1234")


def test_the_doctor_line_judges_the_path_and_token_it_is_given(tmp_path, monkeypatch):
    exe = install_fake_claude(tmp_path, monkeypatch)
    home = tmp_path / "loop"
    home.mkdir()
    (home / "loop.yaml").write_text("term:\n  enabled: true\n")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    status, text = launch.doctor_lines(home, {"PATH": "/usr/bin:/bin",
                                              "CLAUDE_CODE_OAUTH_TOKEN": "set"})
    assert status == "fail" and "not on Kranto's PATH" in text
    path = f"{exe.parent}{os.pathsep}/usr/bin:/bin"
    status, text = launch.doctor_lines(home, {"PATH": path, "CLAUDE_CODE_OAUTH_TOKEN": "set"})
    assert "claude CLI" not in text and "no Claude token" not in text
    status, text = launch.doctor_lines(home, {"PATH": path})
    assert status == "warn" and "no Claude token in Kranto's environment" in text


def test_it_is_on_by_itself_where_bubblewrap_and_a_token_are_there(tmp_path, monkeypatch):
    """term.enabled is null (automatic) by default: on where bwrap can make the sandbox
    and Kranto has a Claude token; true and false decide; off, one line says how to turn it on
    (the page's c shows it)."""
    from kranto.page.settings.store import DEFAULTS
    assert DEFAULTS["term"]["enabled"] is None
    tok = {"CLAUDE_CODE_OAUTH_TOKEN": "set"}
    assert launch.offered({"enabled": None}, tok, True) == (True, None)
    on, why = launch.offered({"enabled": None}, {}, True)
    assert not on and why.endswith("this install lacks a Claude token (kranto doctor says how), "
                                    "or set term.enabled: true in loop.yaml.")
    on, why = launch.offered({"enabled": None}, tok, False)
    assert not on and "lacks bubblewrap (" in why and "term.enabled: true" in why
    on, why = launch.offered({"enabled": None}, {}, False)
    assert not on and "lacks bubblewrap and a Claude token" in why
    assert launch.offered({"enabled": True}, {}, False) == (True, None)      # true: as before
    on, why = launch.offered({"enabled": False}, tok, True)
    assert not on and "set term.enabled: true in loop.yaml" in why
    # the doctor: off by choice is fine; automatic and off says what is missing
    exe = install_fake_claude(tmp_path, monkeypatch)
    home = tmp_path / "loop"
    home.mkdir()
    path = f"{exe.parent}{os.pathsep}/usr/bin:/bin"
    (home / "loop.yaml").write_text("term:\n  enabled: false\n")
    assert launch.doctor_lines(home, {"PATH": path, **tok}) == \
        ("ok", "Open in Claude Code is off (term.enabled)")
    (home / "loop.yaml").write_text("{}\n")
    monkeypatch.setattr(launch, "boxed", lambda: True)
    status, text = launch.doctor_lines(home, {"PATH": path})
    assert status == "warn" and "turns on by itself" in text and "a Claude token" in text
    status, text = launch.doctor_lines(home, {"PATH": path, **tok})
    assert text.startswith("Open in Claude Code: ") and "not on Kranto's PATH" not in text


def test_the_page_hears_why_it_is_off(tmp_path, monkeypatch):
    term = make_term(tmp_path, monkeypatch)
    monkeypatch.setattr(launch, "offered", lambda cfg, environ=None, sandboxed=None:
                        (False, "Open in Claude Code is off: set term.enabled: true"))
    st = term.status()
    assert st["enabled"] is False and st["available"] is False
    assert st["why"] == "Open in Claude Code is off: set term.enabled: true"
