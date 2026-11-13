"""A kept research run's trace: a stream the researcher kept (``<loop home>/research/
transcripts/<stem>.transcript.jsonl``; the researcher left with the build loop, the files it kept
still read) is a trace: the run, the session, its kranto_search call, and it is listed. No model,
no network."""
from __future__ import annotations

import json
from pathlib import Path

from kranto.page.trace.file import transcripts_dir
from kranto.page.trace.service import TraceError, Traces


def stream() -> str:
    rows = [{"type": "system", "subtype": "init", "session_id": "R", "uuid": "r0",
             "model": "m", "tools": ["mcp__kranto__kranto_search", "mcp__kranto__kranto_fetch"],
             "mcp_servers": [{"name": "kranto", "status": "connected"}]},
            {"type": "assistant", "timestamp": "2026-10-20T10:00:01Z", "message": {
                "id": "m1", "usage": {"input_tokens": 4, "output_tokens": 9},
                "content": [{"type": "tool_use", "id": "q1", "name": "mcp__kranto__kranto_search",
                             "input": {"query": "clinic scheduling tools"}}]}},
            {"type": "user", "timestamp": "2026-10-20T10:00:02Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "q1", "content": "1. Acme (2026-09-01)"}]}},
            {"type": "result", "subtype": "success", "result": "{\"verdict\": \"keep\"}",
             "total_cost_usd": 0.21, "usage": {"input_tokens": 4, "output_tokens": 9}}]
    return "".join(json.dumps(r) + "\n" for r in rows)


def test_a_kept_run_reads_as_a_trace_and_is_listed(tmp_path):
    loop = tmp_path / "loop"
    d = transcripts_dir(loop)
    d.mkdir(parents=True)
    (d / "1790000000-loop.transcript.jsonl").write_text(stream())
    tr = Traces(None, loop_home=loop)
    listed = tr.list(source="research")["traces"]
    assert len(listed) == 1 and listed[0]["source"] == "research"
    tid = listed[0]["id"]
    assert tid == "research:1790000000-loop"
    assert listed[0]["href"] == "#/research/1790000000-loop/trace"
    assert [r["id"] for r in tr.list()["traces"]] == [tid]          # in the default list too
    o = tr.get(tid)
    tools = [s for s in o.t.spans.values() if s.kind == "tool"]
    assert [t.attrs["server"] for t in tools] == ["kranto"] and tools[0].status == "ok"
    assert o.t.summary["state"] == "ok" and o.t.summary["usd"] == 0.21
    assert tr.payload(tid, tools[0].id, "output")["text"] == "1. Acme (2026-09-01)"


def test_a_stem_that_is_not_one_is_refused(tmp_path):
    tr = Traces(None, loop_home=tmp_path)
    for stem in ("../x", "abc", "1-../../etc"):
        try:
            tr.get(f"research:{stem}")
        except TraceError as e:
            assert e.code == 404
        else:
            raise AssertionError(stem)
    assert Path(tmp_path).is_dir()
