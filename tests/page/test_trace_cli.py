"""``kranto trace list / show / follow`` on Kranto's own runs: a session's tree as
text, one span with its payload, ``--raw`` with its path, ``--json``, a running session followed
until it ends, and the build loop's old rows listed from ``trace.db`` without writing it. No
network, no model."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from .test_trace_session import TID, _old_index, make_session
from .trace_common import main

FIX = Path(__file__).parent / "fixtures" / "trace"
STEM = "1790000000-verify"


def run(capsys, lh: Path, *argv) -> str:
    main(["trace", "--loop-home", str(lh), *argv])
    return capsys.readouterr().out


def kept(lh: Path) -> Path:
    """A kept research run: the hand-written verify session in fixtures/trace."""
    d = lh / "research" / "transcripts"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{STEM}.transcript.jsonl"
    shutil.copyfile(FIX / "sample-r1" / ".den" / "v5" / "r1" / "transcripts" /
                    "verify.transcript.jsonl", f)
    return f


def test_show_prints_a_sessions_tree(capsys, tmp_path):
    lh = tmp_path / "loop"
    make_session(lh)
    out = run(capsys, lh, "show", f"session:{TID}")
    head = out.splitlines()[0]
    assert head.startswith("Clinic schedules · ok · ") and "1 sessions · 1 tool calls" in head
    assert "Read" in out


def test_list_shows_the_sessions_and_the_build_loops_old_rows_read_only(capsys, tmp_path):
    lh = tmp_path / "loop"
    make_session(lh)
    _old_index(lh / "trace.db")
    before = (lh / "trace.db").read_bytes()
    rows = json.loads(run(capsys, lh, "list", "--json"))
    assert [r["id"] for r in rows] == [f"session:{TID}"]    # the default: what runs now
    old, = json.loads(run(capsys, lh, "list", "--source", "build", "--json"))
    assert old["title"] == "old build" and old["failed_label"] == "verify › Bash"
    assert [r["id"] for r in json.loads(run(capsys, lh, "list", "--source", "maint",
                                            "--json"))] == ["maint:fix-1/1"]
    out = run(capsys, lh, "list", "--source", "build")
    head, row = out.splitlines()[:2]
    assert head.split()[:3] == ["TRACE", "STATE", "STARTED"]
    assert row.startswith("build:sample-r1/1") and "verify › Bash" in row
    assert (lh / "trace.db").read_bytes() == before


def test_one_span_with_its_payload_and_raw_with_its_path(capsys, tmp_path):
    lh = tmp_path / "loop"
    f = kept(lh)
    tid = f"research:{STEM}"
    data = json.loads(run(capsys, lh, "show", tid, "--json"))
    bash = next(s for s in data["spans"] if s["kind"] == "tool" and s["tool"] == "Bash"
                and s["status"] == "ok")
    out = run(capsys, lh, "show", tid, "--span", bash["id"][:10])
    assert "Input:" in out and "command:" in out and "Output:" in out
    raw = run(capsys, lh, "show", tid, "--span", bash["id"], "--raw")
    first = raw.splitlines()[0]
    assert first.startswith(str(f)) and "(byte " in first
    assert json.loads(raw.splitlines()[1])["type"] == "assistant"


def _turn(n: int) -> list[str]:
    """One more turn of a running session: a Bash call, then its result (two lines)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return [json.dumps(o) + "\n" for o in (
        {"type": "assistant", "sessionId": "s-1", "timestamp": ts, "message": {
            "id": f"live-{n}", "usage": {"input_tokens": 5, "output_tokens": 9},
            "content": [{"type": "tool_use", "id": f"live-tool-{n}", "name": "Bash",
                         "input": {"command": f"pytest -q -k live_{n}"}}]}},
        {"type": "user", "sessionId": "s-1", "timestamp": ts, "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"live-tool-{n}", "content": "1 passed"}]}})]


def test_follow_prints_each_span_as_it_lands_until_the_session_ends(capsys, tmp_path,
                                                                    monkeypatch):
    """A running session's new spans print as their lines land, a half-written line waits for
    its end, and the session's end (its record) ends it. Each of the command's waits writes the
    next piece, so the order is the test's, not the clock's."""
    from kranto.page.trace import cli
    lh = tmp_path / "loop"
    f = make_session(lh, state="running", reason=None)
    rec_f = lh / "term" / TID / "session.json"
    call1, done1 = _turn(1)
    call2, done2 = _turn(2)
    seen: list[str] = []
    at: list[int] = []

    def write(s: str) -> None:
        with open(f, "a") as fh:
            fh.write(s)

    def end() -> None:
        rec = json.loads(rec_f.read_text())
        rec.update(state="ended", reason="owner")
        rec_f.write_text(json.dumps(rec))

    steps = [lambda: write(call1), lambda: write(done1), lambda: write(call2[:40]),
             lambda: write(call2[40:] + done2), end]

    def step(_s):
        at.append(len(seen))
        if not steps:
            raise AssertionError("follow did not end with the session")
        steps.pop(0)()
    monkeypatch.setattr(cli.time, "sleep", step)
    real_print = print

    def tee(*a, **k):
        seen.append(" ".join(str(x) for x in a))
        real_print(*a, **k)
    monkeypatch.setattr("builtins.print", tee)
    main(["trace", "--loop-home", str(lh), "follow", f"session:{TID}"])
    assert seen[0].startswith("Clinic schedules · running")
    live = [ln for ln in seen if "live_" in ln]
    assert any("live_1" in ln for ln in live) and any("live_2" in ln for ln in live)
    assert seen[-1].startswith("over: ok")
    assert not steps                                      # every piece was read, in order
    assert not [ln for ln in seen[at[2]:at[3]] if "live_2" in ln]     # the half line waited


def test_an_unknown_trace_or_span_says_so(capsys, tmp_path):
    lh = tmp_path / "loop"
    make_session(lh)
    with pytest.raises(SystemExit) as e:
        run(capsys, lh, "show", "build:nope/1")
    assert "left with the build loop" in str(e.value)
    with pytest.raises(SystemExit) as e:
        run(capsys, lh, "show", "session:zzzz")
    assert "no session" in str(e.value)
    with pytest.raises(SystemExit) as e:
        run(capsys, lh, "show", f"session:{TID}", "--span", "ffffffffffff")
    assert "no span" in str(e.value)
