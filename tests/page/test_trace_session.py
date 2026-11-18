"""An Open in Claude Code session's trace: read from the session's
folder where it is (its record and Claude Code's own transcript, the native format: no init, no
result), live while it runs, its end from its record, "continued in your own terminal" said,
and kept after End (only the working copy goes). No model, no network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kranto.page.box.claude_dirs import project_key
from kranto.page.trace.service import TraceError, Traces
from kranto.page.ui import api
from kranto.page.ui import types as T

TID = "c3f1a9e2"


def make_session(home: Path, state: str = "ended", reason: str | None = "owner") -> Path:
    d = home / "term" / TID
    cwd = d / "ws"
    (d / "claude" / "projects" / project_key(cwd)).mkdir(parents=True)
    rec = {"tid": TID, "key": "idea:i1", "subject": {"kind": "idea", "id": "i1"},
           "title": "Clinic schedules", "session": "s-1", "created": 1.79e9, "updated": 1.79e9 + 90,
           "state": state, "reason": reason, "cwd": str(cwd), "usd": 0.42,
           "tokens": {"in": 1200, "out": 300}}
    (d / "session.json").write_text(json.dumps(rec))
    rows = [
        {"type": "user", "sessionId": "s-1", "uuid": "u1", "timestamp": "2026-10-20T10:00:00Z",
         "message": {"role": "user", "content": "What does this idea need?"}},
        {"type": "assistant", "sessionId": "s-1", "uuid": "a1", "timestamp": "2026-10-20T10:00:03Z",
         "message": {"id": "m1", "usage": {"input_tokens": 9, "output_tokens": 30},
                     "content": [{"type": "text", "text": "Let me look."},
                                 {"type": "tool_use", "id": "t1", "name": "Read",
                                  "input": {"file_path": str(cwd / "README.md")}}]}},
        {"type": "user", "sessionId": "s-1", "uuid": "u2", "timestamp": "2026-10-20T10:00:04Z",
         "toolUseResult": {"type": "text"},
         "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "# x"}]}},
        {"type": "queue-operation", "operation": "enqueue"},
    ]
    t = d / "claude" / "projects" / project_key(cwd) / "s-1.jsonl"
    t.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return t


@pytest.fixture
def tr(tmp_path):
    root = tmp_path / "tasks"
    root.mkdir()
    return Traces(None, loop_home=tmp_path / "loop")


def test_an_ended_session_is_a_trace_with_its_record(tr, tmp_path):
    make_session(tmp_path / "loop")
    o = tr.get(f"session:{TID}")
    kinds = sorted(s.kind for s in o.t.spans.values())
    assert kinds == ["run", "session", "tool", "turn"]
    s = o.t.summary
    assert (s["state"], s["usd"], s["sessions"], s["tools"]) == ("ok", 0.42, 1, 1)
    sess = next(x for x in o.t.spans.values() if x.kind == "session")
    assert sess.status == "ok" and sess.error is None       # no result line is no failure
    assert tr.summary(f"session:{TID}")["href"] == f"#/sessions/{TID}/trace"


def test_its_chat_and_a_tools_output(tr, tmp_path):
    make_session(tmp_path / "loop")
    o = tr.get(f"session:{TID}")
    tool = next(x for x in o.t.spans.values() if x.kind == "tool")
    chat = tr.payload(f"session:{TID}", tool.id, "chat")
    assert [m["role"] for m in chat["messages"]][:3] == ["you", "claude", "claude"]
    assert tr.payload(f"session:{TID}", tool.id, "output")["text"] == "# x"


def test_a_running_session_is_followed_and_reads_on(tr, tmp_path):
    t = make_session(tmp_path / "loop", state="running", reason=None)
    tid = f"session:{TID}"
    first = tr.spans(tid, limit=100)
    assert first["running"] is True
    assert tr.follow(tid)["running"] is True
    with open(t, "a") as f:
        f.write(json.dumps({"type": "assistant", "sessionId": "s-1", "uuid": "a2",
                            "timestamp": "2026-10-20T10:00:09Z", "message": {
                                "id": "m2", "usage": {"input_tokens": 3, "output_tokens": 5},
                                "content": [{"type": "text", "text": "Done."}]}}) + "\n")
    page = tr.spans(tid, after=first["cursor"])
    assert any(s["name"] == "turn 2" for s in page["spans"])


def test_continued_outside_is_said(tr, tmp_path):
    make_session(tmp_path / "loop", reason="outside")
    o = tr.get(f"session:{TID}")
    run = next(x for x in o.t.spans.values() if x.kind == "run")
    assert run.preview.startswith("continued in your own terminal")


def test_an_empty_trace_says_why(tr, tmp_path):
    """ 3: a real install's four sessions kept no transcript and drew one RUN row with nothing said;
    the page now reads the trace's note."""
    t = make_session(tmp_path / "loop")
    assert tr.summary(f"session:{TID}")["note"] is None           # it talked: nothing to say
    t.unlink()
    tr.open_.clear()
    d = tr.summary(f"session:{TID}")
    assert d["sessions"] == 0 and "kept no transcript" in d["note"]
    tr.open_.clear()
    make_outside = json.loads((tmp_path / "loop" / "term" / TID / "session.json").read_text())
    make_outside["reason"] = "outside"
    (tmp_path / "loop" / "term" / TID / "session.json").write_text(json.dumps(make_outside))
    assert tr.summary(f"session:{TID}")["note"].startswith("continued in your own terminal")


def test_an_unknown_session(tr):
    for tid in ("session:zzzz", "session:deadbeef"):
        with pytest.raises(TraceError) as e:
            tr.get(tid)
        assert e.value.code == 404


def test_the_route_answers_a_session_typed(tmp_path):
    from kranto.page.trace import service

    from .term_common import make_home
    service._TRACES.clear()
    cfg = make_home(tmp_path)
    make_session(Path(cfg.home))
    app = api.App(None, "fake", cfg.home)
    code, _, body = api.handle("GET", "/api/trace", {"trace": f"session:{TID}"}, app=app)
    assert code == 200, body
    assert T.problems(json.loads(body), T.TraceDetail) == []
    assert not (Path(cfg.home) / "trace.db").exists()        # trace.db is never written


def _old_index(path: Path) -> None:
    """A trace.db the build loop left: a build's, a fix's and a loop step's rows."""
    from kranto.page.trace.index import Index
    ix = Index(path)
    for i, (tid, src) in enumerate((("build:sample-r1/1", "build"), ("maint:fix-1/1", "maint"),
                                    ("loop:pitch-0123456789ab/0", "loop"))):
        ix.put_trace({"id": tid, "source": src, "key": tid.split(":")[1].rsplit("/", 1)[0],
                      "n": 1, "title": f"old {src}", "state": "ok", "started": 1.79e9 + 10 + i,
                      "ended": 1.79e9 + 70 + i, "usd": 1.5, "tokens": {"in": 10, "out": 2},
                      "sessions": 2, "tools": 9, "errors": 0}, "sig", "verify › Bash")
    ix.close()


def test_the_build_loops_old_rows_still_list_read_only_and_do_not_open(tmp_path):
    """CUT: build, maint and loop rows stay in trace.db; they list with their stored words,
    trace.db is not written (its bytes and time are unchanged), and they no longer open."""
    db = tmp_path / "loop" / "trace.db"
    db.parent.mkdir(parents=True)
    _old_index(db)
    before = (db.read_bytes(), db.stat().st_mtime_ns)
    tr = Traces(None, loop_home=tmp_path / "loop", archive=db)
    rows = tr.list(source="build")["traces"]
    assert [(r["id"], r["title"], r["failed_label"], r["href"]) for r in rows] == [
        ("build:sample-r1/1", "old build", "verify › Bash", None)]
    every = [r for src in ("loop", "maint", "build") for r in tr.list(source=src)["traces"]]
    assert [r["source"] for r in every] == ["loop", "maint", "build"]
    for r in every:
        with pytest.raises(TraceError) as e:
            tr.get(r["id"])
        assert e.value.code == 404 and "left with the build loop" in str(e.value)
    assert tr.list()["traces"] == []                  # the default (all of now) has none of them
    make_session(tmp_path / "loop")
    assert [r["id"] for r in tr.list()["traces"]] == [f"session:{TID}"]
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before
    # no archive, a broken one or another version's: an empty list, never an error
    (tmp_path / "bad.db").write_bytes(b"not a database")
    for a in (tmp_path / "none.db", tmp_path / "bad.db"):
        assert Traces(None, archive=a).list(source="build")["traces"] == []


def test_sessions_list_from_their_records_without_being_opened(tmp_path):
    """The Trace page lists the console's and Open in Claude Code's sessions from their records
    (term/<tid>/session.json, read-only), opened or not; a running one says so, a capped one is
    stopped; once read, the trace's own summary is listed."""
    home = tmp_path / "loop"
    t = make_session(home, state="running", reason=None)
    before = t.read_bytes()
    tr = Traces(None, loop_home=home)
    row, = tr.list()["traces"]
    assert row["id"] == f"session:{TID}" and row["state"] == "running" and row["ended"] is None
    assert (row["title"], row["usd"], row["tokens"]) == ("Clinic schedules", 0.42,
                                                        {"in": 1200, "out": 300})
    assert row["href"] == f"#/sessions/{TID}/trace" and not tr.open_     # nothing opened
    assert tr.list(source="session")["traces"] == [row]
    assert tr.list(source="afk")["traces"] == [] and tr.list(source="research")["traces"] == []
    tr.summary(f"session:{TID}")
    row2, = tr.list()["traces"]
    assert row2["tools"] == 1                                    # the trace's own, once read
    assert t.read_bytes() == before                              # read, never written
    rec = json.loads((home / "term" / TID / "session.json").read_text())
    (home / "term" / TID / "session.json").write_text(json.dumps(
        {**rec, "state": "ended", "reason": "cap"}))
    assert Traces(None, loop_home=home).list()["traces"][0]["state"] == "stopped"
    with pytest.raises(TraceError) as e:
        tr.list(source="nope")
    assert e.value.code == 400


def test_krantos_runs_list_with_the_sessions(tmp_path):
    home = tmp_path / "loop"
    make_session(home)
    asked = []

    def fetch(path):
        asked.append(path)
        return {"runs": [
            {"run_uuid": "run-0001", "kind": "news.brief", "status": "ok",
             "started_at": "2026-10-20T10:01:00Z", "finished_at": "2026-10-20T10:02:00Z",
             "calls": 3, "cost_usd": 0.02, "error": None},
            {"run_uuid": "run-0002", "kind": "ingest", "status": "running",
             "started_at": "2026-10-20T10:03:00Z", "finished_at": None, "calls": 0,
             "cost_usd": 0}]}
    tr = Traces(None, loop_home=home, afk_fetch=fetch)
    rows = tr.list()["traces"]
    assert [r["id"] for r in rows] == ["afk:run-0002", "afk:run-0001", f"session:{TID}"]
    assert rows[0]["state"] == "running" and rows[1]["state"] == "ok"
    assert rows[1]["href"] == "#/afk/run-0001/trace" and rows[1]["calls"] == 3
    assert asked and asked[0].startswith("/api/runs?limit=")
    assert [r["source"] for r in tr.list(source="afk")["traces"]] == ["afk", "afk"]

    def broken(path):
        raise RuntimeError("the server is down")
    assert [r["id"] for r in Traces(None, loop_home=home, afk_fetch=broken).list()["traces"]] \
        == [f"session:{TID}"]
