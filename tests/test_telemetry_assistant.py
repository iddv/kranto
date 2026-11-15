"""The assistant's usage events (TEL, 2026-10-27; ``telemetry/assistant.py``).

They follow the consent Kranto already has, with ``detailed`` only: with anything else nothing
is kept and nothing leaves (a test fails if a connection is even attempted). A long session
sends one batch an hour, not a request a call; every batch passes Kranto's list and the relay's.
Every verb call is counted at the server, by door, client, outcome, refusal kind and rung; a
prepared press is counted again when the owner confirms or dismisses it. Granting consent is a
lock for every assistant under every ladder setting; turning it off is done directly. The
one-time line shows exactly once to an install that never answered. No prompt text, path, id
or secret-shaped string survives into an event."""

from __future__ import annotations

import gzip
import importlib.util
import io
import json
import socket
import string
from contextlib import redirect_stdout
from pathlib import Path

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kranto import config as config_mod
from kranto import telemetry
from kranto.core import verbs
from kranto.telemetry import assistant as A
from kranto.telemetry import cli as tcli
from kranto.telemetry import errors, local
from kranto.telemetry import schema as S

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_790_000_000.0 // 3600 * 3600 + 600          # ten minutes into an hour
ENDPOINT = "http://127.0.0.1:9/v1/logs"            # never reached: every test passes a transport


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (local.DNT, local.ENV_MODE, *tcli.ASSISTANT_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(local.ENV_ENDPOINT, ENDPOINT)
    A._clear()
    A._server_home = None
    yield
    A._clear()
    A._server_home = None
    errors._pending.clear()
    errors._flusher = None
    telemetry.configure(None)


def make_home(tmp_path, mode: str | None, server: bool = True) -> Path:
    h = tmp_path / "home"
    config_mod.init_workspace(h)
    if mode is not None:
        telemetry.set_mode(h, mode)
    telemetry.configure(h)
    if server:
        A._server_home = h
    return h


@pytest.fixture
def no_network(monkeypatch):
    """Any connection attempt fails the test."""
    def refuse(*a, **k):
        raise AssertionError("a connection was attempted")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Spy:
    def __init__(self, status=204):
        self.requests, self.status = [], status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


def body_of(req: httpx.Request) -> dict:
    return json.loads(gzip.decompress(req.content))


def records_of(body: dict) -> list[dict]:
    out = []
    for rec in body["resourceLogs"][0]["scopeLogs"][0]["logRecords"]:
        d = {a["key"]: next(iter(a["value"].values())) for a in rec["attributes"]}
        d["_t"] = int(rec["timeUnixNano"])
        out.append(d)
    return out


def a_session(home, sid="s-1", now=T0, **extra):
    """A whole session as the hooks hand it over."""
    base = {"session": sid, "assistant": "claude-code", "model": "claude-sonnet-5-5",
            "place": "console", "profile": "full", **extra}
    A.hook_event(home, {**base, "event": "start", "source": "startup"}, now=now)
    A.hook_event(home, {**base, "event": "prompt", "command": "status"}, now=now + 5)
    A.hook_event(home, {**base, "event": "tool", "verb": "topic.add"}, now=now + 30)
    A.hook_event(home, {**base, "event": "stop"}, now=now + 60)
    A.hook_event(home, {**base, "event": "end", "reason": "prompt_input_exit"},
                 now=now + 42 * 60 + 5)


# -- consent ---------------------------------------------------------------------------------

@pytest.mark.parametrize("mode,env", [(None, {}), ("local", {}), ("off", {}), ("basic", {}),
                                      ("detailed", {local.DNT: "1"}),
                                      ("detailed", {local.ENV_MODE: "basic"}),
                                      ("detailed", {local.ENV_MODE: "off"})])
def test_without_detailed_nothing_is_kept_and_nothing_leaves(tmp_path, monkeypatch, no_network,
                                                              mode, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    home = make_home(tmp_path, mode)
    for _ in range(5):
        A.note_verb("topic.add", "console", "claude-code", "ok", "do", 12, now=T0)
    A.note_request({"method": "POST", "kranto.identity": {"origin": "ui"}}, "/api/topics",
                   200, 5)
    a_session(home)
    assert A.records() == []
    assert not (A.adir(home) / "spool.jsonl").exists()
    assert not (A.adir(home) / "sessions.json").exists()
    spy = Spy()
    out = A.flush(home, now=T0 + 7200, transport=httpx.MockTransport(spy))
    assert out["sent"] == 0 and spy.requests == [] and A.sent(home) == []


def test_leaving_detailed_deletes_what_waits(tmp_path):
    home = make_home(tmp_path, "detailed", server=False)
    a_session(home)
    A.note_verb("topic.add", "mcp", "codex", "ok", "do", 3, home=home, now=T0)
    assert (A.adir(home) / "spool.jsonl").exists()
    telemetry.set_mode(home, "basic")
    assert not (A.adir(home) / "spool.jsonl").exists()
    assert not (A.adir(home) / "sessions.json").exists()
    assert A.waiting_count(home) == 0


# -- what is counted and how it is batched ---------------------------------------------------

def test_a_long_session_is_one_batch_an_hour(tmp_path):
    home = make_home(tmp_path, "detailed")
    for i in range(500):
        A.note_verb("topic.add", "console", "claude-code", "ok", "do", i % 50, now=T0 + i)
    for i in range(300):
        A.note_verb("settings.telemetry", "console", "claude-code", "prepared", "lock", 7,
                    now=T0 + i)
    for i in range(40):
        A.note_verb("setup.key", "mcp", "codex", "refused", "lock", 1, refusal="door",
                    now=T0 + i)
    spy = Spy()
    t = httpx.MockTransport(spy)
    assert A.flush(home, now=T0 + 60, transport=t)["sent"] == 0      # the hour has not ended
    out = A.flush(home, now=T0 + 3600, transport=t)
    assert out["sent"] == 3 and len(spy.requests) == 1
    recs = {r["kranto.verb"]: r for r in records_of(body_of(spy.requests[0]))}
    assert recs["topic.add"]["kranto.count"] == "500"
    assert recs["topic.add"]["kranto.ms_max"] == "49"
    assert recs["setup.key"]["kranto.refusal"] == "door"
    assert recs["settings.telemetry"]["kranto.rung"] == "lock"
    assert all(r["_t"] % (3600 * 10**9) == 0 for r in recs.values())
    assert A.flush(home, now=T0 + 3700, transport=t)["sent"] == 0      # nothing twice
    assert len(spy.requests) == 1
    assert A.sent(home)[0]["records"] == 3


def test_the_batches_have_a_ceiling(tmp_path):
    home = make_home(tmp_path, "detailed")
    for i, v in enumerate(A.schema_mod.union()["enums"]["verb"][:90]):
        for s in ("ui", "console", "mcp", "cli", "agent"):
            A.note_verb(v, s, "other", "ok", "do", 1, now=T0 + i)
    spy = Spy()
    t = httpx.MockTransport(spy)
    sent = [A.flush(home, now=T0 + 3600 + i, transport=t)["sent"] for i in range(6)]
    assert sent[:3] == [200, 200, 50] and sum(sent) == 450 and len(spy.requests) == 3


def test_a_session_is_paired_and_sent_without_its_id(tmp_path):
    home = make_home(tmp_path, "detailed")
    a_session(home, sid="9f0c1e2d-aaaa-4bbb-8ccc-0123456789ab")
    on_disk = (A.adir(home) / "spool.jsonl").read_text()
    assert "9f0c1e2d" not in on_disk
    spy = Spy()
    A.flush(home, now=T0 + 3 * 3600, transport=httpx.MockTransport(spy))
    recs = records_of(body_of(spy.requests[0]))
    sess = next(r for r in recs if r["event.name"] == "kranto.session")
    assert sess["kranto.minutes"] == "42" and sess["kranto.turns"] == "1"
    assert sess["kranto.tool_calls"] == "1" and sess["kranto.commands"] == "1"
    assert sess["kranto.place"] == "console" and sess["kranto.end"] == "prompt_input_exit"
    assert sess["kranto.model"] == "claude-sonnet-5-5" and sess["kranto.start"] == "startup"
    cmd = next(r for r in recs if r["event.name"] == "kranto.command")
    assert cmd["kranto.command"] == "status" and cmd["kranto.count"] == "1"
    raw = spy.requests[0].content
    assert b"9f0c1e2d" not in gzip.decompress(raw)
    assert A.session_key("9f0c1e2d-aaaa-4bbb-8ccc-0123456789ab").encode() not in \
        gzip.decompress(raw)


def test_an_idle_session_is_closed_at_its_last_event(tmp_path):
    home = make_home(tmp_path, "detailed")
    A.hook_event(home, {"event": "start", "session": "x", "assistant": "codex",
                        "place": "outside", "profile": "compact"}, now=T0)
    A.hook_event(home, {"event": "stop", "session": "x"}, now=T0 + 600)
    A.flush(home, now=T0 + A.IDLE_S + 3600, transport=httpx.MockTransport(Spy()))
    assert json.loads((A.adir(home) / "sessions.json").read_text()) == {}
    sent = [json.loads(b.read_text()) for b in (A.adir(home) / "sent").glob("*.json")
            if not b.name.endswith(".meta.json")]
    (sess,) = [r for r in records_of(sent[0]) if r["event.name"] == "kranto.session"]
    assert sess["kranto.end"] == "idle" and sess["kranto.minutes"] == "10"
    assert sess["kranto.assistant"] == "codex" and sess["kranto.profile"] == "compact"


def test_a_console_tool_failure_is_an_error_report_on_errs_fast_path(tmp_path):
    home = make_home(tmp_path, "basic", server=False)      # error reports go in basic too
    A.hook_event(home, {"event": "tool_failed", "session": "s", "verb": "topic.add",
                        "failure": "timeout",
                        "message": "timed out after 30 seconds reading /home/someone/notes.txt"})
    (e,) = errors.waiting(home)
    assert e["where"] == "console" and e["type"] == "ToolTimeout" and e["verb"] == "topic.add"
    assert "ann" not in json.dumps(e) and "notes" not in json.dumps(e)
    assert errors.build(home, [e], "basic")[1] == [e]          # both lists take it
    assert A.records() == []                                   # basic: no assistant events


# -- the list ------------------------------------------------------------------------------
# (the relay's own copy and its handler left Kranto with ops/ (cut 2): the relay is the
# maintainer's, tested where it lives)


def test_the_verb_list_is_the_registrys():
    own = S.own()["enums"]["verb"]
    want = [v.kind for v in verbs.CORE] + [v.kind for v in verbs.feature_verbs()] + ["other"]
    assert own == want, "a verb changed: run scripts/dev/telemetry_lists.py"


def test_the_command_list_is_the_plugins_skills():
    plugin = ROOT / "src" / "kranto" / "plugin" / "skills"
    assert sorted(S.own()["enums"]["command"]) == sorted(p.name for p in plugin.iterdir()
                                                         if (p / "SKILL.md").is_file())


# -- the one-time line -----------------------------------------------------------------------

def test_the_line_shows_exactly_once_to_an_install_that_never_answered(tmp_path):
    home = make_home(tmp_path, None)
    shown = [A.hook_event(home, {"event": "start", "session": f"s{i}"}) for i in range(5)]
    assert shown[0] == A.NOTICE and shown[1:] == [None] * 4
    assert "/kranto:telemetry" in A.NOTICE and "#/settings/privacy" in A.NOTICE
    # the CLI prints it as the hook's systemMessage, once, and nothing after
    home2 = make_home(tmp_path / "b", None)
    outs = []
    for _ in range(3):
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert tcli.event(home2, io.StringIO('{"event": "start", "session": "z"}')) == 0
        outs.append(buf.getvalue())
    assert json.loads(outs[0]) == {"systemMessage": A.NOTICE} and outs[1:] == ["", ""]


@pytest.mark.parametrize("mode", ["off", "local", "basic", "detailed"])
def test_no_line_once_answered(tmp_path, mode):
    home = make_home(tmp_path, mode)
    assert A.hook_event(home, {"event": "start", "session": "s"}) is None


def test_other_events_never_print(tmp_path):
    home = make_home(tmp_path, None)
    for ev in ("end", "prompt", "tool", "tool_failed", "stop", "nonsense"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            tcli.event(home, io.StringIO(json.dumps({"event": ev, "session": "s"})))
        assert buf.getvalue() == ""
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert tcli.event(home, io.StringIO("not json")) == 0
    assert buf.getvalue() == ""


# -- consent from inside an assistant --------------------------------------------------------

@pytest.mark.parametrize("var", tcli.ASSISTANT_ENV)
@pytest.mark.parametrize("mode", ["basic", "detailed"])
def test_the_command_line_refuses_to_raise_consent_inside_an_assistant(tmp_path, monkeypatch,
                                                                        capsys, var, mode):
    home = make_home(tmp_path, None)
    monkeypatch.setenv(var, "1")
    assert tcli.main(home, [mode]) == 3
    assert "your consent" in capsys.readouterr().err
    assert not local.effective(home).answered
    assert tcli.main(home, ["off"]) == 0                       # off needs no press
    assert local.effective(home).mode == "off"


# -- no words of yours -----------------------------------------------------------------------

SECRETS = st.sampled_from([
    lambda: "sk-ant-" + "a1" * 20, lambda: "ghp_" + "Z9" * 18, lambda: "AKIA" + "Q" * 16,
    lambda: "xoxb-" + "1" * 12 + "-" + "b" * 24,
    lambda: "eyJ" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20])
# a word of the prompt, made unmistakable so finding it anywhere is a leak
WORDS = st.text(alphabet=string.ascii_letters + string.digits, min_size=4,
                max_size=40).map(lambda w: "Qzxv" + w)


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secret=SECRETS, word=WORDS, path=st.sampled_from(
    ["/home/someone/projects/x.py", "/Users/bob/notes.md", "/var/home/c/k.txt"]),
    uid=st.uuids())
def test_no_prompt_path_id_or_secret_survives_into_an_event(tmp_path_factory, secret, word,
                                                              path, uid):
    tmp = tmp_path_factory.mktemp("p")
    home = make_home(tmp, "detailed")
    s = secret()
    text = f"/kranto:status {word} {path} {uid} {s}"
    hook = _hook_module()
    for raw in ({"hook_event_name": "UserPromptSubmit", "session_id": str(uid), "prompt": text},
                {"hook_event_name": "SessionStart", "session_id": str(uid), "source": "startup",
                 "model": text, "cwd": path, "transcript_path": path},
                {"hook_event_name": "PostToolUseFailure", "session_id": str(uid),
                 "tool_name": "mcp__plugin_kranto_kranto__kranto_topic_add",
                 "tool_input": {"name": text}, "error": text},
                {"hook_event_name": "PostToolUse", "session_id": str(uid),
                 "tool_name": "mcp__plugin_kranto_kranto__kranto_topic_add",
                 "tool_input": {"name": text}, "tool_response": {"text": text}},
                {"hook_event_name": "SessionEnd", "session_id": str(uid), "reason": text}):
        ev = hook.reduce(raw, {})
        if ev is not None:
            A.hook_event(home, ev, now=T0)
    A.note_verb(text, text, text, "ok", "do", 1, refusal=text, now=T0)
    on_disk = "".join(p.read_text(errors="replace") for p in home.rglob("*")
                      if p.is_file() and "telemetry" in p.parts)
    errs = json.dumps(errors.waiting(home))
    pv = A.preview(home)
    for needle in (s, path, str(uid), str(uid)[:8], word):
        assert needle not in pv["wire"] and needle not in errs and needle not in on_disk
    for r in pv["records"]:
        A.check(r["event"].split(".")[1], {k: v for k, v in r.items()
                                           if k not in ("event", "hour")})


def _hook_module():
    p = ROOT / "src" / "kranto" / "plugin" / "hooks" / "telemetry.py"
    spec = importlib.util.spec_from_file_location("kranto_hook_telemetry", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
