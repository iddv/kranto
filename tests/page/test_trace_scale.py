"""A big trace stays fast (the acceptance): a synthetic kept session with
50,000 spans and a 20 MB tool output is read in under 3 s, a page of 500 spans answers in
under 50 ms, one span with its first page of output in under 200 ms; a 5,000-span one in a
tenth of that. The synthetic trace (a research run's kept stream: the format every session
writes) is made here, in a temp folder.

The budgets are the **request thread's CPU time** (``time.thread_time``): the runners share
one machine with every other job (a load average of 30 is ordinary), and wall time there
measures the neighbours. The index is written by its own thread after the answer; its whole
write is bounded in wall time, loosely."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kranto.page.trace.model import span_id
from kranto.page.trace.service import TraceError, Traces, decode_cursor

pytestmark = pytest.mark.slow

STEM = "1790000000-big"
TID = f"research:{STEM}"
T0 = 1_790_000_000.0


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + f".{int(t * 1000) % 1000:03d}Z"


def make_big(home: Path, spans: int = 50_000, big_output_mb: int = 20) -> Path:
    """A kept stream of one session of ``spans // 2`` turns, one Bash call each (turn + tool =
    2 spans), and one call whose output is ``big_output_mb`` MB."""
    tr = home / "research" / "transcripts"
    tr.mkdir(parents=True)
    turns = spans // 2 - 1                     # the run and the session are spans too
    big = "x" * 99 + "\n"
    with open(tr / f"{STEM}.transcript.jsonl", "w") as f:
        f.write(json.dumps({"type": "system", "subtype": "init", "session_id": "S", "uuid": "u",
                            "model": "claude-sonnet-5-5"}) + "\n")
        for i in range(turns):
            t = T0 + 2 + i
            f.write(json.dumps({"type": "assistant", "timestamp": iso(t), "message": {
                "id": f"m{i}", "usage": {"input_tokens": 10, "output_tokens": 20},
                "content": [{"type": "text", "text": f"step {i}: run the tests again"},
                            {"type": "tool_use", "id": f"t{i}", "name": "Bash",
                             "input": {"command": f"pytest -q tests/page/test_{i % 97}.py"}}]}})
                    + "\n")
            out = big * (big_output_mb * 10_000) if i == turns // 2 else f"{i} passed\n"
            f.write(json.dumps({"type": "user", "timestamp": iso(t + 0.5), "message": {
                "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]},
                "tool_use_result": {"stdout": out, "stderr": ""}}) + "\n")
        f.write(json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 9.5,
                            "num_turns": turns}) + "\n")
    return tr


def timed(fn):
    """``(what fn returns, the CPU seconds this thread spent on it)``."""
    t = time.thread_time()
    out = fn()
    return out, time.thread_time() - t


def test_a_5000_span_trace_stays_fast(tmp_path):
    make_big(tmp_path / "loop", spans=5_000, big_output_mb=1)
    tr = Traces(tmp_path / "trace.db", loop_home=tmp_path / "loop")
    o, opened = timed(lambda: tr.get(TID))
    assert len(o.t.spans) >= 4_999 and opened < 0.3, f"read in {opened:.2f} s"
    page, first = timed(lambda: tr.spans(TID, limit=500))
    assert len(page["spans"]) == 500 and first < 0.02, f"a page in {first * 1000:.0f} ms"
    sid = span_id(TID, "tool:t7")
    _, select = timed(lambda: (tr.span(TID, sid), tr.payload(TID, sid, "output")))
    assert select < 0.05, f"one span and its output in {select * 1000:.0f} ms"
    tr.settle()


def test_a_50000_span_trace_with_a_20_mb_output_stays_fast(tmp_path):
    make_big(tmp_path / "loop")
    tr = Traces(tmp_path / "trace.db", loop_home=tmp_path / "loop")   # payload_max_mb: 2
    o, opened = timed(lambda: tr.get(TID))
    assert len(o.t.spans) >= 49_999                      # run, session + 2 a turn
    assert opened < 3.0, f"read in {opened:.2f} s"
    w = time.perf_counter()
    tr.settle()
    assert time.perf_counter() - w < 30, "the index's write"
    assert tr.index.span_count(TID) == len(o.t.spans)
    page, first = timed(lambda: tr.spans(TID, limit=500))
    assert len(page["spans"]) == 500 and page["more"]
    assert first < 0.05, f"the first page in {first * 1000:.0f} ms"
    cur = page["cursor"]
    for _ in range(3):                                   # a page in the middle as fast
        page, nxt = timed(lambda cur=cur: tr.spans(TID, after=cur, limit=500))
        cur = page["cursor"]
    assert nxt < 0.05, f"a later page in {nxt * 1000:.0f} ms"
    sid = span_id(TID, "tool:t7")
    (sp, out), select = timed(lambda: (tr.span(TID, sid), tr.payload(TID, sid, "output")))
    assert out["text"].startswith("7 passed")
    assert select < 0.2, f"one span and its output in {select * 1000:.0f} ms"
    huge = span_id(TID, f"tool:t{(50_000 // 2 - 1) // 2}")       # the 20 MB output
    t = time.thread_time()
    with pytest.raises(TraceError) as e:
        tr.payload(TID, huge, "output")
    assert e.value.code == 413 and f"open {STEM}.transcript.jsonl" in \
        str(e.value) and time.thread_time() - t < 0.2
    assert tr.span(TID, huge)["outputs"]["bytes"] >= 20 * 1_000_000
    errs, flt = timed(lambda: tr.spans(TID, filter="errors"))
    assert errs["total"] == 0 and flt < 0.5
    # 6: every payload searched, the whole trace read for a word in none, within 2 s CPU;
    # a word in every turn stops at 500 hits; the 20 MB line is past payload_max_mb, skipped
    none, scan = timed(lambda: tr.search(TID, "zanzibarquux"))
    assert none["hits"] == [] and not none["more"] and scan < 2.0, f"searched in {scan:.2f} s"
    assert 2_000_000 < none["scanned"] < 20_000_000
    many, scan = timed(lambda: tr.search(TID, "again"))
    assert len(many["hits"]) == 500 and many["more"] and scan < 2.0
    shown = decode_cursor(page["cursor"])[1]
    tail, last = timed(lambda: tr.spans(TID, after=page["cursor"]))
    assert all(s["pos"] > shown for s in tail["spans"])   # nothing changed: only the next page
    assert last < 0.05


def test_the_index_answers_a_search_in_a_big_trace(tmp_path):
    make_big(tmp_path / "loop", spans=20_000, big_output_mb=1)
    tr = Traces(tmp_path / "trace.db", loop_home=tmp_path / "loop")
    tr.get(TID)
    tr.settle()
    hits, took = timed(lambda: tr.index.search(TID, "test_42.py"))
    assert hits and took < 0.2
