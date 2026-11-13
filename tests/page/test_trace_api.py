"""The trace routes and the index on a kept session (a research run's
stream, the format every session writes: the hand-written verify session in fixtures/trace):
the list, the tree by pages and by branch, filters, one span, payloads paged and capped, a pruned
file, a bad cursor, the cursor that returns only what changed, and the index set aside or
rebuilt. No model, no network."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from kranto.page.trace import index as I
from kranto.page.trace.model import span_id
from kranto.page.trace.service import TraceError, Traces, decode_cursor
from kranto.page.ui import api
from kranto.page.ui import types as T

FIX = Path(__file__).parent / "fixtures" / "trace"
STEM = "1790000000-verify"
TID = f"research:{STEM}"


@pytest.fixture
def root(tmp_path) -> Path:
    """The loop home, with the kept stream under research/transcripts."""
    r = tmp_path / "loop"
    d = r / "research" / "transcripts"
    d.mkdir(parents=True)
    shutil.copyfile(FIX / "sample-r1" / ".den" / "v5" / "r1" / "transcripts" /
                    "verify.transcript.jsonl", d / f"{STEM}.transcript.jsonl")
    return r


def kept(root: Path) -> Path:
    return root / "research" / "transcripts" / f"{STEM}.transcript.jsonl"


@pytest.fixture
def app(root, tmp_path):
    from kranto.page.trace import service
    service._TRACES.clear()
    return api.App(None, "fake", root)


def get(app, path, **q):
    code, ctype, body = api.handle("GET", path, q, app=app)
    return code, json.loads(body)


def ok(app, path, tp=None, **q):
    code, body = get(app, path, **q)
    assert code == 200, body
    if tp is not None:
        assert T.problems(body, tp) == [], path
    return body


def test_the_list_is_typed_and_a_kept_run_links_its_page(app):
    body = ok(app, "/api/traces", T.TraceList, source="research")
    one, = body["traces"]
    assert one["id"] == TID and one["href"] == f"#/research/{STEM}/trace" and one["usd"]
    every = ok(app, "/api/traces", T.TraceList)["traces"]           # the default: all of now
    assert [r["id"] for r in every] == [TID]
    assert ok(app, "/api/traces", source="build")["traces"] == []  # no old rows here


def test_a_trace_its_files_and_cursor(app):
    body = ok(app, "/api/trace", T.TraceDetail, trace=TID)
    assert body["stages"] == [] and body["links"] == []
    assert [f["rel"] for f in body["files"]] == [f"{STEM}.transcript.jsonl"]
    assert decode_cursor(body["cursor"])[1] == -1
    assert body["note"] is None and body["sessions"] == 1


def test_the_tree_comes_in_pages_and_the_cursor_carries_on(app):
    first = ok(app, "/api/trace/spans", T.SpanPage, trace=TID, limit="10")
    assert len(first["spans"]) == 10 and first["more"]
    assert [s["pos"] for s in first["spans"]] == list(range(10))
    seen = [s["id"] for s in first["spans"]]
    cur = first["cursor"]
    while True:
        page = ok(app, "/api/trace/spans", trace=TID, after=cur, limit="10")
        seen += [s["id"] for s in page["spans"]]
        cur = page["cursor"]
        if not page["more"]:
            break
    assert len(seen) == len(set(seen)) == first["total"]
    again = ok(app, "/api/trace/spans", trace=TID, after=cur)
    assert again["spans"] == [] and not again["more"]      # nothing changed, nothing new


def test_a_branch_and_the_filters(app):
    sess = next(s for s in ok(app, "/api/trace/spans", trace=TID, limit="2000")["spans"]
                if s["kind"] == "session")
    kids = ok(app, "/api/trace/spans", trace=TID, parent=sess["id"])
    assert kids["spans"] and all(s["parent"] == sess["id"] for s in kids["spans"])
    errs = ok(app, "/api/trace/spans", T.SpanPage, trace=TID, filter="errors")
    by = {s["id"]: s for s in errs["spans"]}
    assert errs["matches"] and all(by[m]["status"] == "error" for m in errs["matches"])
    for s in errs["spans"]:                                 # ancestors kept: the tree reads
        assert s["parent"] is None or s["parent"] in by
    bash = ok(app, "/api/trace/spans", trace=TID, filter="tool:Bash,kind:tool")
    assert bash["matches"] and all(by_s["tool"] == "Bash"
                                   for by_s in bash["spans"] if by_s["id"] in bash["matches"])
    found = ok(app, "/api/trace/spans", trace=TID, q="pytest")
    assert found["matches"]
    code, body = get(app, "/api/trace/spans", trace=TID, filter="nope")
    assert code == 400


def test_one_span_and_its_payloads(app):
    page = ok(app, "/api/trace/spans", trace=TID, limit="2000")
    tool = next(s for s in page["spans"] if s["tool"] == "Bash" and s["status"] == "ok")
    sp = ok(app, "/api/trace/span", T.SpanDetail, trace=TID, span=tool["id"])
    assert sp["source"]["file"].endswith(".transcript.jsonl") and sp["path"]
    inp = ok(app, "/api/trace/payload", T.TracePayload, trace=TID, span=tool["id"], part="input")
    assert any(f["key"] == "command" for f in inp["fields"])
    out = ok(app, "/api/trace/payload", T.TracePayload, trace=TID, span=tool["id"], part="output")
    assert "text" in out and out["redactions"] == [] or isinstance(out["redactions"], list)
    chat = ok(app, "/api/trace/payload", T.TracePayload, trace=TID, span=tool["id"], part="chat")
    assert chat["messages"] and {m["role"] for m in chat["messages"]} >= {"claude", "tool"}
    code, body = get(app, "/api/trace/payload", trace=TID, span=tool["id"], part="diff")
    assert code == 404
    code, body = get(app, "/api/trace/span", trace=TID, span="0" * 16)
    assert code == 404


def _long_output(root: Path, size: int) -> str:
    """Give the first Bash result of the session an output ``size`` characters long."""
    f = kept(root)
    rows = [json.loads(x) for x in f.read_text().splitlines()]
    for o in rows:
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        for b in msg.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_result" and o.get("type") == "user":
                body = "line of output\n" * (size // 15 + 1)
                b["content"] = body[:size]
                if isinstance(o.get("tool_use_result"), dict):
                    o["tool_use_result"]["stdout"] = body[:size]
                f.write_text("".join(json.dumps(r) + "\n" for r in rows))
                return b["tool_use_id"]
    raise AssertionError("no tool result")


def test_search_every_payload_finds_what_the_previews_do_not(app, root):
    """ 6: a word that is only deep in a tool's output (past the
    8 KB the trace holds in memory, far past the 240-character preview) is found by the
    payload search and not by the search over what is held; a secret is matched only as the page
    shows it (redacted), so a search never confirms one."""
    from .test_trace_redact import rand
    f = kept(root)
    call = _long_output(root, 20_000)
    secret = "gh" + "p_" + rand(36)                             # made here, never a literal
    text = f.read_text()
    deep = "line of output\n" * 1000 + "zanzibarquux was here " + secret + "\n"
    rows = [json.loads(x) for x in text.splitlines()]
    said = None
    for o in rows:
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        for b in msg.get("content") or []:
            if said is None and o.get("type") == "assistant" and isinstance(b, dict) \
                    and b.get("type") == "text":
                b["text"] = "x" * 300 + " quokkaplan: first the tests. " + b["text"]
                said = o["message"]["id"]
            if isinstance(b, dict) and b.get("tool_use_id") == call:
                b["content"] = deep
                if isinstance(o.get("tool_use_result"), dict):
                    o["tool_use_result"]["stdout"] = deep
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    sid = span_id(TID, f"tool:{call}")
    held = ok(app, "/api/trace/spans", trace=TID, q="zanzibarquux")
    assert held["matches"] == []
    every = ok(app, "/api/trace/spans", T.SpanPage, trace=TID, q="zanzibarquux", payloads="1")
    assert every["matches"] == [sid]
    by = {s["id"]: s for s in every["spans"]}
    assert all(s["parent"] is None or s["parent"] in by for s in every["spans"])  # ancestors
    hits = ok(app, "/api/trace/search", T.TraceSearch, trace=TID, q="ZanzibarQuux was")
    assert [(h["span"], h["part"]) for h in hits["hits"]] == [(sid, "output")]
    assert "zanzibarquux was here" in hits["hits"][0]["preview"]
    assert secret not in json.dumps(hits) and "[redacted" in hits["hits"][0]["preview"]
    assert ok(app, "/api/trace/search", trace=TID, q=secret[4:20])["hits"] == []
    # a turn's own words are searched too: the thinking and the text the owner reads in Chat
    assert said is not None
    turn = ok(app, "/api/trace/search", trace=TID, q="quokkaplan")["hits"]
    page = ok(app, "/api/trace/spans", trace=TID, limit="2000")["spans"]
    kinds = {s["id"]: s["kind"] for s in page}
    assert [(kinds[h["span"]], h["part"]) for h in turn] == [("turn", "output")]
    assert "quokkaplan: first the tests" in turn[0]["preview"]
    code, _ = get(app, "/api/trace/search", trace=TID, q="")
    assert code == 400


def test_a_long_output_is_paged_and_a_huge_one_refused(app, root):
    call = _long_output(root, 150_000)
    sid = span_id(TID, f"tool:{call}")
    p1 = ok(app, "/api/trace/payload", trace=TID, span=sid, part="output")
    assert len(p1["text"]) == 64 * 1024 and p1["next"] == 64 * 1024
    p3 = ok(app, "/api/trace/payload", trace=TID, span=sid, part="output", offset="131072")
    assert p3["next"] is None and len(p3["text"]) == 150_000 - 131072
    from kranto.page.trace import service
    service._TRACES.clear()
    _long_output(root, 3 * 1024 * 1024)
    code, body = get(app, "/api/trace/payload", trace=TID, span=sid, part="output")
    assert code == 413 and "open " in body["error"]


def test_a_removed_file_is_410_and_a_bad_cursor_422(app, root):
    page = ok(app, "/api/trace/spans", trace=TID, limit="2000")
    tool = next(s for s in page["spans"] if s["tool"])
    f = kept(root)
    data = f.read_bytes()
    f.write_bytes(b"")                       # emptied (not yet re-read): the line is gone
    from kranto.page.trace import service
    o = service._TRACES[next(iter(service._TRACES))].open_[TID]
    try:
        from kranto.page.trace.payload import payload
        with pytest.raises(Exception) as e:
            payload(o.t, tool["id"], "input")
        assert getattr(e.value, "code", None) == 410
    finally:
        f.write_bytes(data)
    code, body = get(app, "/api/trace/spans", trace=TID, after="not-a-cursor")
    assert code == 422


def running(root: Path) -> Path:
    """The kept stream as it was while its session ran: no result line yet (a file without
    its result that grew lately is running). Returns it."""
    f = kept(root)
    f.write_text("".join(r for r in f.read_text().splitlines(keepends=True)
                         if json.loads(r)["type"] != "result"))
    return f


def test_the_cursor_returns_what_changed(app, root):
    """A running session's file grows: the next read with the last cursor returns the new
    spans and the shown ones that changed (the session, its last turn), not the tree."""
    f = running(root)
    rows = f.read_text().splitlines(keepends=True)
    f.write_text("".join(rows[:-6]))
    cur, total = None, 0
    while True:
        page = ok(app, "/api/trace/spans", trace=TID, after=cur, limit="2000") if cur else \
            ok(app, "/api/trace/spans", trace=TID, limit="2000")
        cur, total = page["cursor"], page["total"]
        if not page["more"]:
            break
    assert page["running"] is True
    with open(f, "a") as fh:
        fh.write("".join(rows[-6:]))
    page = ok(app, "/api/trace/spans", trace=TID, after=cur, limit="2000")
    new = page["total"] - total
    assert new > 0 and page["spans"]
    # what changed (the new spans, the session, hooks that found their call), not the tree
    assert len(page["spans"]) < page["total"] // 5
    ids = {s["id"] for s in page["spans"]}
    sess = next(s for s in page["spans"] if s["kind"] == "session")
    assert sess["status"] == "running" and sess["id"] in ids
    again = ok(app, "/api/trace/spans", trace=TID, after=page["cursor"])
    assert again["spans"] == []


def test_a_rewritten_file_starts_over(app, root):
    page = ok(app, "/api/trace/spans", trace=TID, limit="2000")
    f = kept(root)
    lines = f.read_text().splitlines(keepends=True)
    f.unlink()
    f.write_text("".join(lines[:3]))
    code, body = get(app, "/api/trace/spans", trace=TID, after=page["cursor"])
    assert code == 422 and "from the top" in body["error"]


def test_download_is_the_trace_redacted(app, root):
    code, ctype, data = api.handle("GET", "/api/trace/download", {"trace": TID}, app=app)
    assert code == 200 and ctype.startswith("application/json")
    body = json.loads(data)
    assert body["trace"]["id"] == TID and len(body["spans"]) == body["trace"]["spans"]
    assert any("output" in s for s in body["spans"] if s["kind"] == "tool")


# -- the index ----------------------------------------------------------------------------------

def test_the_index_is_written_and_searched(root, tmp_path):
    tr = Traces(tmp_path / "trace.db", loop_home=root)
    tr.get(TID)
    tr.settle()
    ix = tr.index
    assert ix.trace_row(TID)["sessions"] == 1
    assert ix.span_count(TID) == len(tr.open_[TID].t.spans)
    assert ix.search(TID, "pytest")


def test_an_index_of_another_version_is_rebuilt(root, tmp_path):
    path = tmp_path / "trace.db"
    tr = Traces(path, loop_home=root)
    tr.get(TID)
    tr.settle()
    c = sqlite3.connect(path)
    c.execute("UPDATE trace_meta SET v='0' WHERE k='version'")
    c.commit()
    c.close()
    ix = I.Index(path)
    assert ix.version() == I.VERSION and ix.trace_row(TID) is None    # dropped, not migrated


def test_a_corrupt_index_is_set_aside_and_built_again(root, tmp_path):
    path = tmp_path / "trace.db"
    path.write_bytes(b"this is not a database" * 100)
    tr = Traces(path, loop_home=root)
    tr.get(TID)
    assert tr.index.trace_row(TID) is not None
    assert list(tmp_path.glob("trace.db.bad-*"))


def test_an_unknown_trace(root, tmp_path):
    tr = Traces(None, loop_home=root)
    for tid in ("build:nope/1", "session:x", "nonsense", "research:1790000000-nope",
                "research:not-a-stem", "maint:x/1", "loop:x/1"):
        with pytest.raises(TraceError) as e:
            tr.get(tid)
        assert e.value.code == 404
