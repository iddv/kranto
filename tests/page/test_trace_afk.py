"""The server's runs as traces: read through the server's API (a fake host here), never its
database file; a call's request and answer are its payloads (redacted, paged), a call whose
payload retention removed says so, a cub's host call shows its op and never its payload, and
the cost is the calls' own."""
from __future__ import annotations

import json

import pytest

from kranto.page.trace.service import TraceError, Traces
from kranto.page.ui import types as T

UUID = "0f9e8d7c-run-1"


def host(store: dict):
    asked = []

    def fetch(path: str) -> dict:
        asked.append(path)
        if path not in store:
            e = RuntimeError("the server: no such run")
            e.code = 404
            raise e
        return json.loads(json.dumps(store[path]))
    return fetch, asked


def run_json(secret: str) -> dict:
    return {"run": {"run_uuid": UUID, "kind": "ideas", "status": "ok",
                    "started_at": "2026-10-20T10:00:00Z", "finished_at": "2026-10-20T10:01:00Z",
                    "summary": "3 cards", "error": None},
            "calls": [
                {"id": 1, "purpose": "judge", "tier": "default", "model": "m",
                 "prompt_version": "v1", "request": json.dumps({"messages": ["judge " + secret]}),
                 "response": "{\"keep\": true}", "status": "ok", "error": None,
                 "http_status": 200, "attempts": 1, "prompt_tokens": 10,
                 "completion_tokens": 4, "cost_usd": 0.02, "latency_ms": 1200,
                 "created_at": "2026-10-20T10:00:30Z"},
                {"id": 2, "purpose": "explain", "tier": "default", "model": "m",
                 "prompt_version": "v1", "request": "", "response": None, "status": "ok",
                 "error": None, "http_status": 200, "attempts": 1, "prompt_tokens": 5,
                 "completion_tokens": 2, "cost_usd": 0.01, "latency_ms": 800,
                 "created_at": "2026-10-20T10:00:50Z", "expired": True}],
            "cub_calls": [{"cub": "newsletter", "service": "newsletter", "op": "emails.get", "status": "ok",
                           "ms": 40, "bytes_in": 10, "bytes_out": 99,
                           "created_at": "2026-10-20T10:00:40Z"}],
            "events": [{"id": 7, "ts": "2026-10-20T10:00:55Z", "kind": "card", "feature": "ideas",
                        "subject_kind": "idea", "subject_id": "12"}]}


def test_a_run_reads_as_a_trace_through_the_hosts_api(tmp_path):
    from .test_trace_redact import rand
    secret = "gh" + "p_" + rand(36)                              # made here, never a literal
    fetch, asked = host({f"/api/runs/{UUID}": run_json(secret)})
    tr = Traces(None, afk_fetch=fetch)
    tid = f"afk:{UUID}"
    o = tr.get(tid)
    # the run, and its marks (ACT: its steps; a server without them answers 404)
    assert asked == [f"/api/runs/{UUID}", f"/api/activity?run={UUID}"]
    kinds = sorted(s.kind for s in o.t.spans.values())
    assert kinds == ["call", "call", "event", "run", "tool"]
    s = o.t.summary
    assert s["usd"] == pytest.approx(0.03) and s["usd_kind"] == "exact" and s["state"] == "ok"
    judge = next(x for x in o.t.spans.values() if x.name.startswith("judge"))
    got = tr.payload(tid, judge.id, "input")
    survived = secret in got["text"]
    assert not survived and got["redactions"]                 # redacted on read
    assert tr.payload(tid, judge.id, "output")["text"].strip().startswith("{")
    chat = tr.payload(tid, judge.id, "chat")["messages"]
    assert [m["role"] for m in chat] == ["you", "claude"]
    expired = next(x for x in o.t.spans.values() if x.name.startswith("explain"))
    assert "removed by retention" in expired.preview
    cub = next(x for x in o.t.spans.values() if x.kind == "tool")
    assert cub.name == "newsletter · newsletter.emails.get" and "never its payload" in cub.preview
    tr.get(tid)
    assert len(asked) == 2                                     # a finished run: read once


def test_a_runs_title_is_its_kind_and_time_and_its_summary_is_in_the_overview(tmp_path):
    """ 3: a real install's telemetry run was titled with its summary JSON; a run with no model calls
    said nothing of why it has one row."""
    summary = json.dumps({"mode": "detailed", "built": [], "sent": 3})
    data = {"run": {"run_uuid": UUID, "kind": "telemetry", "status": "ok",
                    "started_at": "2026-10-21T06:15:00Z", "finished_at": "2026-10-21T06:15:01Z",
                    "summary": summary, "error": None}, "calls": [], "cub_calls": [], "events": []}
    fetch, _ = host({f"/api/runs/{UUID}": data})
    tr = Traces(None, afk_fetch=fetch)
    d = tr.summary(f"afk:{UUID}")
    assert d["title"].startswith("telemetry · ") and "{" not in d["title"]
    assert d["note"] and "no model calls" in d["note"]
    run = tr.span(f"afk:{UUID}", d["failed_at"] or next(iter(tr.get(f"afk:{UUID}").t.spans)))
    assert json.loads(run["attributes"]["summary"]) == json.loads(summary)
    assert "\n" in run["attributes"]["summary"]                  # pretty-printed
    ok = Traces(None, afk_fetch=host({f"/api/runs/{UUID}": run_json("x")})[0])
    d2 = ok.summary(f"afk:{UUID}")
    assert d2["note"] is None and d2["title"].startswith("ideas · ")


def test_a_calls_preview_is_its_answer_and_the_head_counts_calls(tmp_path):
    """On live 0.5.4 an ingest's rows previewed the provider's raw JSON ({"id": "gen-…",
    "object": "chat.completion", …}) and the head said "0 sessions · 0 tool calls" for 20 calls."""
    chat = json.dumps({"id": "gen-1", "object": "chat.completion", "model": "m",
                       "choices": [{"message": {"role": "assistant",
                                                "content": "{\"keep\": true, \"why\": \"new\"}"}}]})
    blocks = json.dumps({"id": "msg_1", "type": "message",
                         "content": [{"type": "text", "text": "Kept: a new benchmark."}]})
    data = run_json("x")
    data["calls"][0]["response"] = chat
    data["calls"].append({**data["calls"][0], "id": 3, "response": blocks,
                          "created_at": "2026-10-20T10:00:52Z"})
    fetch, _ = host({f"/api/runs/{UUID}": data})
    tr = Traces(None, afk_fetch=fetch)
    o = tr.get(f"afk:{UUID}")
    previews = sorted(s.preview for s in o.t.spans.values() if s.kind == "call")
    assert '{"keep": true, "why": "new"}' in previews and "Kept: a new benchmark." in previews
    assert not any("chat.completion" in p or '"id"' in p for p in previews)
    d = tr.summary(f"afk:{UUID}")
    assert d["calls"] == 3 and d["tokens"] == {"in": 25, "out": 10}
    assert T.problems(d, T.TraceDetail) == []


def test_an_unknown_or_malformed_run(tmp_path):
    fetch, _ = host({})
    tr = Traces(None, afk_fetch=fetch)
    for tid in ("afk:0f9e8d7c-none", "afk:../x", "afk:short"):
        with pytest.raises(TraceError) as e:
            tr.get(tid)
        assert e.value.code == 404, tid
    with pytest.raises(TraceError):
        Traces(None).get(f"afk:{UUID}")           # no host here
