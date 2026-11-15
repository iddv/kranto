"""Whose Claude token Open in Claude Code logs in with (TK, from the server #213): the watcher's
Claude API key, which Kranto's ``.env`` puts into the server's environment after its start, is not
a session's login until the owner chooses it (``term.allow_api_key``); a key in the unit's own
environment is used as before. On an API key a sources session runs on the watcher's reason
model. A refusal of the Claude API's in the transcript (``isApiErrorMessage``) is the session's
error, in its record and its view. The key is a canary: never in argv, an environment, a record
or a log. No model, no network."""
from __future__ import annotations

import json
import logging
import os

import pytest

from kranto.page.box import handoff
from kranto.page.term import afk, cli, launch, meter, service

from .term_common import Screen, canary, install_fake_claude, make_term

KEY = "ANTHROPIC_API_KEY"
SOURCES = {"kind": "sources", "id": "151"}


@pytest.fixture
def key(monkeypatch):
    """Only the watcher's key: set in this process's environment after its start, as
    the server's ``config.load`` does with Kranto's ``.env`` (``os.environ.setdefault``)."""
    k = canary("sk-ant")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv(KEY, k)
    monkeypatch.setattr(handoff, "started_names", lambda: frozenset({"PATH", "HOME"}))
    return k


@pytest.fixture
def reason(monkeypatch):
    """the server's model settings: the reason tier on Sonnet 5, in a router's name."""
    asked = []

    def call(url, method, path, body=None, timeout=30):
        asked.append(path)
        return {"roles": [{"role": "judge", "model": "anthropic/claude-haiku-5.5"},
                          {"role": "reason", "model": "anthropic/claude-sonnet-5"}]}
    monkeypatch.setattr(afk, "call", call)
    monkeypatch.setattr(afk, "afk_url", lambda cfg: "http://127.0.0.1:9211")
    return asked


@pytest.fixture
def term(tmp_path, monkeypatch, key, reason):
    t = make_term(tmp_path, monkeypatch, sandboxed=False)
    yield t
    for tid in list(t.live):
        t.end(tid, remove=False)


def nowhere(tmp_path, secret: str) -> None:
    """The secret is in no file under the test's folder (records, transcripts, net.jsonl)."""
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.name != "claude":
            assert secret not in p.read_text(errors="replace"), p


def test_the_watchers_key_is_not_a_sources_sessions_login_without_the_choice(term, key,
                                                                            tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    st = term.status()
    assert st["enabled"] and not st["available"] and st["ask"] == "api_key"
    assert st["why"] == launch.WATCHERS_KEY
    assert "would bill your Claude API key (the watcher's)" in st["why"]
    assert "`claude setup-token`" in st["why"] and "Use the API key" in st["why"]
    assert st["sources_on"] == "on your Claude API key (the watcher's), Sonnet 5"
    with pytest.raises(service.TermError) as e:
        term.open(SOURCES)
    assert e.value.code == 503 and e.value.extra == {"ask": "api_key"}
    assert not term.live and not term.store.all()            # nothing started, nothing kept
    assert key not in str(e.value) and key not in caplog.text
    nowhere(tmp_path, key)


def test_with_the_choice_it_is_handed_over_by_pipe_and_the_model_is_pinned(term, key,
                                                                          tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    term.app.over["term"]["allow_api_key"] = True
    assert term.status()["available"]
    out = term.open(SOURCES)
    scr = Screen()
    lv = term.live[out["tid"]]
    lv.pty.attach(scr)
    scr.wait("> ")
    assert f"auth=fd len={len(key)}" in scr.text              # the key, by its descriptor
    rec = term.store.get(out["tid"])
    assert (rec["login"], rec["pinned"]) == ("api_key", "claude-sonnet-5")
    assert out["on"] == rec["on"] == "on your Claude API key (the watcher's), Sonnet 5"
    spec = term.spec(rec)
    argv = launch.argv(spec)
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5"
    env = launch.env(spec, KEY, 9)
    assert env["CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR"] == "9"
    assert key not in json.dumps(argv) and key not in json.dumps(env)
    assert key not in scr.text and key not in caplog.text
    term.end(out["tid"], remove=False)
    nowhere(tmp_path, key)


def test_term_model_wins_and_other_sessions_keep_the_cli_default(term, reason):
    term.app.over["term"]["allow_api_key"] = True
    cred = launch.login(term.cfg(), None)[0]
    assert cred.kind == "api_key" and cred.watchers and "sk-ant" not in repr(cred)
    assert term.model_for("sources", cred) == "claude-sonnet-5"
    assert term.model_for("project", cred) is None
    term.model_for("sources", cred)
    assert reason == ["/api/settings/models"]                 # read once, then kept
    term.app.over["term"]["model"] = "claude-haiku-5-5"
    assert term.model_for("sources", cred) == "claude-haiku-5-5"
    login = handoff.Credential("CLAUDE_CODE_OAUTH_TOKEN", "x")
    term.app.over["term"]["model"] = None
    assert term.model_for("sources", login) is None          # the owner's plan: as before


def test_the_reason_model_falls_back_when_kranto_cannot_say(term, monkeypatch):
    def down(*a, **k):
        raise afk.AfkError("the server's API: refused")
    monkeypatch.setattr(afk, "call", down)
    assert term.reason_model() == launch.SOURCES_MODEL


def test_a_key_in_the_units_own_environment_works_as_before(term, key, monkeypatch):
    monkeypatch.setattr(handoff, "started_names", lambda: frozenset({"PATH", KEY}))
    st = term.status()
    assert st["available"] and st["ask"] is None
    assert st["on"] == "on your Claude API key"
    cred = handoff.credential()
    assert (cred.kind, cred.watchers, cred.words) == ("api_key", False, "Claude API key")


def test_a_login_token_wins_over_the_key(term, key, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", canary("oat"))
    st = term.status()
    assert st["available"] and st["sources_on"] == "on your Claude plan (login token)"
    assert handoff.credential().words == "Claude login token"


def test_where_proc_cannot_say_an_api_key_asks_first(monkeypatch, key):
    monkeypatch.setattr(handoff, "started_names", lambda: None)
    assert handoff.credential().watchers
    assert not handoff.credential({KEY: key}).watchers      # an environment passed in: its own
    assert handoff.credential({KEY: key}, started={"PATH"}).watchers


def test_kranto_term_open_counts_the_units_files_as_the_owners(tmp_path, monkeypatch, key):
    home = tmp_path / "home"
    (home / ".config" / "kranto").mkdir(parents=True)
    environ = {"PATH": "/bin", KEY: key}
    assert launch.login({}, environ, cli.started(environ, home)) [1] is not None
    (home / ".config" / "kranto" / "claude.env").write_text(f"{KEY}={key}\n")
    cred, held = launch.login({}, environ, cli.started(environ, home))
    assert held is None and cred.kind == "api_key" and not cred.watchers


def test_a_credit_refusal_marks_the_session_errored_until_a_reply_comes_through(
        tmp_path, monkeypatch):
    t = make_term(tmp_path, monkeypatch, token=canary("claude"), sandboxed=False)
    try:
        out = t.open({"kind": "project", "id": "p1"})
        tid = out["tid"]
        lv = t.live[tid]
        lv.transcript.parent.mkdir(parents=True, exist_ok=True)

        def line(ev):
            with open(lv.transcript, "a") as f:
                f.write(json.dumps(ev) + "\n")
        line({"type": "user", "message": {"role": "user", "content": "find the feeds"}})
        line({"type": "assistant", "isApiErrorMessage": True, "error": "billing_error",
              "message": {"role": "assistant", "model": "<synthetic>",
                          "content": [{"type": "text", "text": "Credit balance is too low"}],
                          "usage": {"input_tokens": 0, "output_tokens": 0}}})
        t.tick()
        rec = t.store.get(tid)
        assert rec["error"] == "Credit balance is too low"
        assert rec["refused"]["text"] == "Credit balance is too low"
        v = t.get(tid)
        assert v["refused"] == "Credit balance is too low" and v["state"] == "running"
        line({"type": "assistant", "message": {"id": "m2", "role": "assistant",
                                               "content": [{"type": "text", "text": "ok"}],
                                               "usage": {"input_tokens": 5, "output_tokens": 2}}})
        t.tick()
        assert t.store.get(tid)["error"] is None and t.get(tid)["refused"] is None
    finally:
        for tid in list(t.live):
            t.end(tid, remove=False)


@pytest.mark.parametrize("text,error,refused", [
    ("Credit balance is too low", None, True),
    ("Invalid API key · Please run /login", None, True),
    ("Claude AI usage limit reached|1760000000", None, True),
    ("API Error: 400 {\"type\":\"error\"}", "billing_error", True),
    ("API Error: Repeated 529 Overloaded errors", None, False),
    ("Prompt is too long", None, False),
])
def test_which_api_errors_are_refusals(tmp_path, text, error, refused):
    p = tmp_path / "t.jsonl"
    ev = {"type": "assistant", "isApiErrorMessage": True,
          "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if error:
        ev["error"] = error
    p.write_text(json.dumps(ev) + "\n")
    assert (meter.refusal(p) is not None) is refused
    # an ordinary reply that mentions credit is not an API error
    p.write_text(json.dumps({**ev, "isApiErrorMessage": False}) + "\n")
    assert meter.refusal(p) is None


def test_the_doctor_names_the_credential(tmp_path, monkeypatch):
    exe = install_fake_claude(tmp_path, monkeypatch)
    home = tmp_path / "loop"
    home.mkdir()
    (home / "loop.yaml").write_text("{}\n")
    monkeypatch.setattr(launch, "boxed", lambda: True)
    path = f"{exe.parent}{os.pathsep}/usr/bin:/bin"
    status, text = launch.doctor_lines(home, {"PATH": path, "CLAUDE_CODE_OAUTH_TOKEN": "set"})
    assert "its Claude login token by pipe" in text
    status, text = launch.doctor_lines(home, {"PATH": path}, dotenv={KEY})
    assert status == "warn" and "the watcher's Claude API key (Kranto's .env)" in text
    assert "Use the API key (term.allow_api_key)" in text and "by pipe" not in text
    (home / "loop.yaml").write_text("term:\n  allow_api_key: true\n")
    status, text = launch.doctor_lines(home, {"PATH": path}, dotenv={KEY})
    assert "its Claude API key (the watcher's) by pipe" in text
    status, text = launch.doctor_lines(home, {"PATH": path, KEY: "set"}, dotenv={KEY})
    assert "its Claude API key by pipe" in text                # the unit's own wins
