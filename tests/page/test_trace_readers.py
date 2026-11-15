"""The stream-json reader against a small hand-written fixture in the format a Claude Code
session writes (tests/page/fixtures/trace/sample-r1: three invented sessions on a toy to-do
project, ``build``, ``verify`` and ``ready-repair1``), each read as one kept file
(``FileTrace``). The fixture holds what the reader must handle: a response written over several
lines, tool calls that succeed and fail, a permission denial, a background task on a Bash call,
an API retry, Edit and Write calls, and a session that ended without a result."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kranto.page.trace.file import FileTrace
from kranto.page.trace.model import parse_trace_id, span_id

FIX = Path(__file__).parent / "fixtures" / "trace"
# a transcript untouched for two minutes is a finished one (trace.file.QUIET_S); a fresh
# checkout's files are new, so they are dated an hour back here
_OLD = __import__("time").time() - 3600
for _f in FIX.rglob("*.jsonl"):
    __import__("os").utime(_f, (_OLD, _OLD))


def transcripts(name: str, n: int, root: Path = FIX) -> list[Path]:
    return sorted((root / name / ".den" / "v5" / f"r{n}" / "transcripts").glob("*.transcript.jsonl"))


def one(f: Path) -> FileTrace:
    stem = f.name.removesuffix(".transcript.jsonl")
    t = FileTrace(f, f"research:{stem}", stem)
    t.refresh()
    return t


class Many:
    """Every transcript of a fixture's round, each read as one file: their spans together."""

    def __init__(self, name: str, n: int):
        self.traces = [one(f) for f in transcripts(name, n)]
        self.spans = {k: v for t in self.traces for k, v in t.spans.items()}


@pytest.fixture(scope="module")
def sample() -> Many:
    return Many("sample-r1", 1)


def test_one_response_is_one_turn_even_over_several_lines(sample):
    turns = [s for s in sample.spans.values() if s.kind == "turn"]
    mids = [s.attrs.get("message_id") for s in turns]
    assert len(mids) == len(set(mids))
    multi = [s for s in turns if len(s.outputs["lines"]) > 1]
    assert multi, "the fixture has a response written over several lines"
    for s in multi:
        assert s.tokens is not None


def test_a_tool_span_is_the_call_and_its_result(sample):
    tools = [s for s in sample.spans.values() if s.kind == "tool"]
    done = [s for s in tools if s.status in ("ok", "error")]
    assert done
    for s in done:
        assert s.inputs["block"] == s.outputs["block"] == s.attrs["call_id"]
        assert s.end is not None and s.start is not None and s.end >= s.start
        assert s.id == span_id(s.trace, f"tool:{s.attrs['call_id']}")
    errs = [s for s in tools if s.status == "error"]
    assert errs and all(s.error and s.error["message"] for s in errs)


def test_a_denial_marks_its_tool_and_is_an_event(sample):
    denied = [s for s in sample.spans.values() if s.attrs.get("denied")]
    assert denied
    ev = [s for s in sample.spans.values()
          if s.kind == "event" and s.name.startswith("permission_denied")]
    assert ev and ev[0].status == "error"


def test_a_background_task_is_an_event_on_its_tool(sample):
    """A Bash call can start a background shell, not a sub-agent: its task_started line
    lands on the Bash call that started it."""
    with_tasks = [s for s in sample.spans.values() if s.events
                  and any(e["name"] == "task_started" for e in s.events)]
    assert with_tasks and all(s.kind in ("tool", "subagent") for s in with_tasks)


def _line(**o) -> str:
    return json.dumps(o) + "\n"


def test_a_subagent_holds_the_lines_it_made(tmp_path):
    """An Agent call is a subagent span; every later line with its id as
    parent_tool_use_id is its child (made here: the fixture has no sub-agent)."""
    from kranto.page.trace.readers.stream_json import StreamReader
    ts = "2026-10-20T10:00:0{}.000Z"
    f = tmp_path / "s.jsonl"
    f.write_text(
        _line(type="system", subtype="init", session_id="S", uuid="u0", model="m") +
        _line(type="assistant", timestamp=ts.format(1), message={
            "id": "m1", "usage": {"input_tokens": 3, "output_tokens": 4}, "content": [
                {"type": "tool_use", "id": "A1", "name": "Agent",
                 "input": {"subagent_type": "explore", "description": "look"}}]}) +
        _line(type="system", subtype="task_started", tool_use_id="A1", task_id="t1") +
        _line(type="assistant", parent_tool_use_id="A1", timestamp=ts.format(2), message={
            "id": "m2", "content": [{"type": "tool_use", "id": "G1", "name": "Grep",
                                     "input": {"pattern": "x"}}]}) +
        _line(type="user", parent_tool_use_id="A1", timestamp=ts.format(3), message={
            "content": [{"type": "tool_result", "tool_use_id": "G1", "content": "hit"}]}) +
        _line(type="user", timestamp=ts.format(4), message={
            "content": [{"type": "tool_result", "tool_use_id": "A1", "content": "done"}]}) +
        _line(type="result", subtype="success", total_cost_usd=0.5,
              usage={"input_tokens": 3, "output_tokens": 4}))
    r = StreamReader("build:x/1", "s.jsonl", None, "verify")
    r.read(f)
    sub = r.spans[span_id("build:x/1", "tool:A1")]
    assert sub.kind == "subagent" and sub.name == "Agent explore" and sub.status == "ok"
    assert [e["name"] for e in sub.events] == ["task_started"]
    inner = r.spans[span_id("build:x/1", "turn:m2")]
    assert inner.parent == sub.id and inner.name == "turn 1"
    grep = r.spans[span_id("build:x/1", "tool:G1")]
    assert grep.parent == inner.id and grep.status == "ok"
    assert r.session.status == "ok" and r.session.usd == 0.5


def test_a_session_with_no_result_stopped(sample):
    s = next(s for s in sample.spans.values() if s.kind == "session"
             and s.attrs.get("purpose") == "research" and s.trace.endswith("ready-repair1"))
    assert s.status == "error"
    assert s.error["type"] == "no-result" and s.error["stopped"]


def test_depth_first_positions_are_a_tree_order(sample):
    for t in sample.traces:
        order = sorted(t.spans.values(), key=lambda s: s.pos)
        assert order[0].kind == "run" and order[0].depth == 0
        seen = {order[0].id}
        for s in order[1:]:
            assert s.parent in seen                      # a parent comes before its children
            assert s.depth == t.spans[s.parent].depth + 1
            seen.add(s.id)
        assert sorted(s.pos for s in order) == list(range(len(order)))


def test_an_edit_counts_its_lines(sample):
    t = sample
    edits = [s for s in t.spans.values() if s.attrs.get("tool") in ("Edit", "Write")]
    assert edits and any(s.attrs.get("lines_added") for s in edits)


def test_an_api_retry_is_an_event(sample):
    t = sample
    ev = [s for s in t.spans.values() if s.kind == "event" and s.name.startswith("api_retry")]
    assert ev and ev[0].attrs["level"] == "warning"


def test_reading_in_pieces_gives_the_same_spans(tmp_path):
    """A transcript read while it is written (a half line left for later) ends with the
    same spans, by id, as one read of the whole."""
    src = next(f for f in transcripts("sample-r1", 1) if f.name == "verify.transcript.jsonl")
    whole = one(src)
    f = tmp_path / src.name
    data = src.read_bytes()
    cut = data.index(b"\n", len(data) // 2) + 20               # mid-line
    f.write_bytes(data[:cut])
    t = one(f)
    r = next(iter(t.streams.values()))
    assert r.offset < cut and data[r.offset - 1:r.offset] == b"\n"   # the half line waits
    half = set(t.spans)
    with open(f, "ab") as fh:
        fh.write(data[cut:])
    assert t.refresh() is True
    assert set(t.spans) == set(whole.spans) and half < set(t.spans)
    for i, s in whole.spans.items():
        assert (t.spans[i].kind, t.spans[i].parent, t.spans[i].status) == \
            (s.kind, s.parent, s.status)


def test_a_file_that_was_rewritten_is_read_again(tmp_path):
    src = next(f for f in transcripts("sample-r1", 1) if f.name == "build.transcript.jsonl")
    f = tmp_path / src.name
    shutil.copyfile(src, f)
    t = one(f)
    n = len(t.spans)
    lines = f.read_text().splitlines(keepends=True)
    f.unlink()
    f.write_text("".join(lines[:5]))
    t.refresh()
    assert len(t.spans) < n


@pytest.mark.parametrize("tid,want", [("build:beliefline/1", ("build", "beliefline", 1)),
                                      ("build:a/b/12", ("build", "a/b", 12)),
                                      ("session:t9", ("session", "t9", None))])
def test_trace_ids(tid, want):
    assert parse_trace_id(tid) == want


@pytest.mark.parametrize("bad", ["", "build:", "build:x", "x:y/1", "build:/1", "build:x/y"])
def test_bad_trace_ids(bad):
    with pytest.raises(ValueError):
        parse_trace_id(bad)
