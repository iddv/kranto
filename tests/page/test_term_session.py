"""Open in Claude Code's sessions without bubblewrap (the fake claude on the host): attach and
replay, the SIGWINCH relay, the cap, the idle end and the resume, End's cleanup, the meter and
the spend caps, a kill during setup, the terminal's tickets. The sandbox's own limits are in
``test_term_sandbox.py``."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kranto.page.term import launch, service
from kranto.page.term.pty import Pty

from .term_common import Screen, canary, make_repo, make_term, run


@pytest.fixture
def term(tmp_path, monkeypatch):
    t = make_term(tmp_path, monkeypatch, token=canary("claude"),
                  source=make_repo(tmp_path / "source"), sandboxed=False)
    yield t
    for tid in list(t.live):
        t.end(tid, remove=False)


def opened(term, ref="p1", **kw):
    out = term.open({"kind": "project", "id": ref}, **kw)
    scr = Screen()
    term.live[out["tid"]].pty.attach(scr)
    scr.wait("> ")
    return out, scr


def test_open_starts_once_per_subject_and_a_second_viewer_gets_the_screen_so_far(term):
    out, scr = opened(term)
    assert out["state"] == "running" and out["ticket"]
    assert "auth=fd" in scr.text and "resumed=0" in scr.text
    term.live[out["tid"]].pty.write(b"hello there\n")
    scr.wait("you said: hello there")
    again = term.open({"kind": "project", "id": "p1"})
    assert again["tid"] == out["tid"] and again["ticket"] != out["ticket"]
    late = Screen()
    term.live[out["tid"]].pty.attach(late)
    assert "you said: hello there" in late.text           # replayed from the ring
    term.live[out["tid"]].pty.write(b"more\n")
    late.wait("you said: more")
    scr.wait("you said: more")


def test_resize_reaches_the_program_through_the_relay(term):
    out, scr = opened(term)
    term.live[out["tid"]].pty.resize(91, 23)
    scr.wait("[size 91x23]")


def test_the_cap_refuses_another_session_and_names_the_open_ones(term, monkeypatch):
    monkeypatch.setitem(term.app.over["term"], "max_sessions", 1)
    opened(term, "p1")
    with pytest.raises(service.TermError) as e:
        term.open({"kind": "project", "id": "p2"})
    assert e.value.code == 429 and len(e.value.extra["sessions"]) == 1


def test_an_idle_session_ends_and_open_resumes_its_conversation_in_the_same_copy(term):
    out, scr = opened(term)
    tid = out["tid"]
    term.live[tid].pty.write(b"say first turn\n")
    scr.said("first turn")
    lv = term.live[tid]
    term.tick(now=time.time() + 61 * 60)                    # idle_min 60, nobody watching? no:
    assert lv.pty.alive                                      # a viewer is attached
    lv.pty.detach(next(iter(lv.pty.sinks)))
    term.tick(now=time.time() + 61 * 60)
    assert lv.pty.wait(10) is not None
    deadline = time.time() + 10
    while term.store.get(tid)["state"] != "ended" and time.time() < deadline:
        time.sleep(0.05)
    rec = term.store.get(tid)
    assert rec["reason"] == "idle" and Path(rec["cwd"]).is_dir()
    assert term.view(rec)["words"] == "Ended after 60 minutes idle"
    again, scr2 = opened(term)
    assert again["tid"] == tid and "resumed=1" in scr2.text
    assert f"session={rec['session']}" in scr2.text


def test_end_removes_the_copy_unless_a_proposal_refers_to_it(term):
    a, _ = opened(term, "p1")
    term.end(a["tid"])
    rec = term.store.get(a["tid"])
    assert rec["removed"] and not Path(rec["cwd"]).exists()
    assert a["tid"] not in [s["tid"] for s in term.list()["sessions"]]
    # a new Open after End starts a fresh session
    b, _ = opened(term, "p1")
    assert b["tid"] != a["tid"]
    term.store.update(b["tid"], proposals=[{"kind": "patch", "status": "proposed"}])
    term.end(b["tid"])
    rec = term.store.get(b["tid"])
    assert rec["kept"] and Path(rec["cwd"]).is_dir()


def test_said_waits_for_the_programs_line_not_the_terminals_echo_of_what_was_typed():
    scr = Screen()
    scr(b"\r\r\n> say hi\r\n")                               # the echo alone: not said yet
    assert "hi\r\n" in scr.text                              # what wait("hi\r\n") took for it
    with pytest.raises(AssertionError, match="not seen"):
        scr.said("hi", timeout=0.05)
    scr(b"hi\r\r\n> ")                                       # the program's line, as a pty sends it
    scr.said("hi", timeout=0.05)


def test_the_fake_programs_own_line_never_matches_the_old_wait(term):
    """The bytes the old ``wait("hi\\r\\n")`` was met by: only the echo, never the program."""
    out, scr = opened(term)
    term.live[out["tid"]].pty.write(b"say hi\n")
    scr.said("hi")
    assert scr.text.count("hi\r\n") == 1 and "say hi\r\n" in scr.text


def test_the_meter_counts_claude_codes_figure_into_the_record_and_the_cap_ends_it(term,
                                                                                monkeypatch):
    out, scr = opened(term)
    tid = out["tid"]
    lv = term.live[tid]
    lv.pty.write(b"status 0.25\n")
    scr.wait("[status 0]")
    lv.pty.write(b"say hi\n")
    scr.said("hi")
    term.tick()
    rec = term.store.get(tid)
    assert rec["usd"] == 0.25 and rec["tokens"] == {"in": 100, "out": 20}
    term.tick()                                              # nothing new: nothing added
    assert term.store.get(tid)["usd"] == 0.25
    assert term.spent_today() == 0.25
    # the build loop's ledger is never written (CUT: loop.db is not opened for writing)
    assert not (term.app.loop_home / "loop.db").exists()
    monkeypatch.setitem(term.app.over["term"], "daily_usd", 0.2)
    term.tick()
    assert lv.pty.wait(10) is not None
    deadline = time.time() + 10
    while term.store.get(tid)["reason"] != "cap" and time.time() < deadline:
        time.sleep(0.05)
    assert term.view(term.store.get(tid))["words"] == "Ended: today's spend cap was reached"
    with pytest.raises(service.TermError) as e:
        term.open({"kind": "project", "id": "p2"})
    assert e.value.code == 400 and "cap" in str(e.value)


def test_tool_commands_get_a_scrubbed_environment_even_without_the_sandbox(term, monkeypatch):
    tok = canary("claude")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", tok)
    monkeypatch.setenv("GH_TOKEN", canary("gh"))
    out, scr = opened(term)
    got = run(term, out["tid"], scr, "env")
    assert tok not in got and "GH_TOKEN" not in got and "CLAUDE_CODE_OAUTH" not in got
    assert "CLAUDECODE=1" in got


def test_a_ticket_opens_its_session_once_and_only_while_fresh(term, monkeypatch):
    out, _ = opened(term)
    tid = out["tid"]
    assert term.redeem("deadbeef", out["ticket"]) is None    # another session's id
    t2 = term.ticket(tid)
    assert term.redeem(tid, t2) is not None
    assert term.redeem(tid, t2) is None                      # used
    t3 = term.ticket(tid)
    later = time.time() + 3600
    monkeypatch.setattr(service.time, "time", lambda: later)
    assert term.redeem(tid, t3) is None                      # expired
    assert term.redeem(tid, "") is None


def test_a_restart_leaves_running_records_ended_and_resumable(term):
    out, _ = opened(term)
    tid = out["tid"]
    fresh = service.Term(term.app)
    fresh.sandboxed = lambda: False
    assert fresh.get(tid)["state"] == "ended"
    assert fresh.store.get(tid)["reason"] == "restart"


def test_the_stop_writes_the_reason_before_the_program_exits(term, monkeypatch):
    """STOP's follow-up: the server's stop says "ended: restart" itself, before it signals the
    program, rather than leaving it to the next start's ``_recover``."""
    from kranto.page.ui import api
    out, _ = opened(term)
    tid = out["tid"]
    lv = term.live[tid]
    at_kill = []
    kill = lv.pty.kill
    monkeypatch.setattr(lv.pty, "kill", lambda: (at_kill.append((dict(term.store.get(tid)),
                                                                 lv.pty.alive)), kill()))
    monkeypatch.setattr(api, "_default", term.app)
    monkeypatch.setattr(term.app, "_term", term, raising=False)
    assert api.stop_terms() == [tid]
    rec, alive = at_kill[0]
    assert alive and rec["state"] == "ended" and rec["reason"] == "restart" and rec["pid"] is None
    assert lv.pty.wait(10) is not None
    deadline = time.time() + 10
    while tid in term.live and time.time() < deadline:      # _exited keeps the stop's reason
        time.sleep(0.05)
    assert term.store.get(tid)["reason"] == "restart"
    assert term.view(term.store.get(tid))["words"] == "Ended when Kranto restarted"
    assert api.stop_terms() == []                            # nothing left running


def test_status_says_why_open_is_not_offered(tmp_path, monkeypatch):
    t = make_term(tmp_path, monkeypatch, token=None, sandboxed=False)
    st = t.status()
    # the way on doctor names too: kranto setup claude keeps a token every Open reads
    assert not st["available"] and "kranto setup claude" in st["why"]
    with pytest.raises(service.TermError) as e:
        t.open({"kind": "idea", "id": "i1"})
    assert e.value.code == 503
    monkeypatch.setitem(t.app.over["term"], "enabled", False)
    assert "off" in t.status()["why"]


def test_a_program_killed_during_its_setup_is_reaped():
    p = Pty(["/bin/sh", "-c", "exec sleep 60"], env={"PATH": "/usr/bin:/bin"}, cwd="/").start()
    t0 = time.time()
    p.kill(grace_s=1)
    assert p.wait(5) is not None and time.time() - t0 < 5
    assert not p.alive


def test_a_viewer_that_cannot_keep_up_is_dropped_and_the_program_goes_on():
    p = Pty(["/bin/sh", "-c", "for i in $(seq 1 2000); do echo line $i; done; sleep 1"],
            env={"PATH": "/usr/bin:/bin"}, cwd="/")
    slow_calls = []

    def slow(data):
        slow_calls.append(data)
        return False                                         # always behind
    fast = Screen()
    p.attach(slow)
    p.attach(fast)
    p.start()
    fast.wait("line 2000")
    assert p.viewers == 1 and len(slow_calls) <= 2
    p.kill(grace_s=1)


def test_the_argv_has_no_token_and_the_env_hands_it_over_by_descriptor(term, tmp_path):
    rec = term.store.get(opened(term)[0]["tid"])
    spec = term.spec(rec, sandboxed=False)
    tok = canary("claude")
    env = launch.env(spec, "CLAUDE_CODE_OAUTH_TOKEN", 7,
                     {"CLAUDE_CODE_OAUTH_TOKEN": tok, "ANTHROPIC_API_KEY": tok, "PATH": "/bin"})
    assert tok not in json.dumps(env) and env["CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"] == "7"
    assert Path(env["CLAUDE_CODE_SHELL_PREFIX"]).name.startswith("kranto-shell")
    assert (env["KRANTO_SHELL"], env["KRANTO_SHELL_ENV"]) == ("plain", "strict")
    argv = launch.argv(spec)
    assert argv[0].endswith("claude") and "--restricted" in argv
    assert "--session-id" in argv or "--resume" in argv
    env2 = launch.env(spec, "ANTHROPIC_API_KEY", 9, {"ANTHROPIC_API_KEY": tok})
    assert env2["CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR"] == "9" and tok not in json.dumps(env2)
