"""``kranto trace export --otlp`` against a receiver on 127.0.0.1 in this process:
OTLP/HTTP JSON to ``/v1/traces``, the GenAI conventions' names, one UUIDv5 trace id (the same
on a re-export), parents that exist, and content only when asked, redacted. No model; the
secret is made up here at run time and never printed."""
from __future__ import annotations

import json
import random
import shutil
import string
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from kranto.page.trace.export_otlp import NS, trace_id

from .trace_common import main

FIX = Path(__file__).parent / "fixtures" / "trace"
STEM = "1790000000-verify"
TID = f"research:{STEM}"


@pytest.fixture(autouse=True)
def kept(tmp_path):
    """A kept stream-json file in the loop home (a research run's, the format every session
    writes): the hand-written verify session in fixtures/trace."""
    d = tmp_path / "lh" / "research" / "transcripts"
    d.mkdir(parents=True)
    shutil.copyfile(FIX / "sample-r1" / ".den" / "v5" / "r1" / "transcripts" /
                    "verify.transcript.jsonl", d / f"{STEM}.transcript.jsonl")
    return d


@pytest.fixture
def receiver():
    got: list[tuple[str, str, dict]] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.append((self.path, self.headers.get("Content-Type"),
                        json.loads(self.rfile.read(n))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", got
    srv.shutdown()
    srv.server_close()


def run(tmp_path, *argv):
    main(["trace", "--loop-home", str(tmp_path / "lh"), "export", *argv])


def spans_of(body: dict) -> list[dict]:
    return body["resourceSpans"][0]["scopeSpans"][0]["spans"]


def attrs(sp: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values())) for a in sp["attributes"]}


def test_a_trace_goes_to_the_collector_as_genai_spans(tmp_path, receiver, capsys):
    url, got = receiver
    run(tmp_path, TID, "--otlp", url)
    assert "sent to" in capsys.readouterr().out
    (path, ctype, body), = got
    assert path == "/v1/traces" and ctype == "application/json"
    sp = spans_of(body)
    assert len(sp) > 5
    tid = uuid.uuid5(NS, TID).hex
    assert {s["traceId"] for s in sp} == {tid} == {trace_id(TID)}
    ids = {s["spanId"] for s in sp}
    assert all(s["parentSpanId"] in ids or s["parentSpanId"] == "" for s in sp)
    assert sum(1 for s in sp if s["parentSpanId"] == "") == 1          # one root: the run
    names = {s["name"].split(" ")[0] for s in sp}
    assert {"invoke_workflow", "invoke_agent", "chat", "execute_tool"} <= names
    tool = next(s for s in sp if s["name"].startswith("execute_tool"))
    a = attrs(tool)
    assert a["gen_ai.operation.name"] == "execute_tool" and a["gen_ai.tool.name"]
    assert int(tool["endTimeUnixNano"]) >= int(tool["startTimeUnixNano"]) > 0
    chat = next(s for s in sp if s["name"].startswith("chat") and s["kind"] == 3)
    assert "gen_ai.usage.output_tokens" in attrs(chat)
    # no content unless asked: no messages, arguments or results
    keys = {k for s in sp for k in attrs(s)}
    assert not keys & {"gen_ai.input.messages", "gen_ai.output.messages",
                       "gen_ai.tool.call.arguments", "gen_ai.tool.call.result"}


def test_a_re_export_sends_the_same_ids(tmp_path, receiver):
    url, got = receiver
    run(tmp_path, TID, "--otlp", url)
    run(tmp_path, TID, "--otlp", url)
    a, b = (sorted((s["traceId"], s["spanId"]) for s in spans_of(x[2])) for x in got)
    assert a == b


def _kept(tmp: Path, secret: str) -> str:
    ts = "2001-09-09T01:47:01.000Z"
    lines = [{"type": "system", "subtype": "init", "session_id": "S", "uuid": "u", "model": "m"},
             {"type": "assistant", "timestamp": ts, "message": {
                 "id": "m1", "usage": {"input_tokens": 1, "output_tokens": 1},
                 "content": [{"type": "tool_use", "id": "B1", "name": "Bash",
                              "input": {"command": "echo hi"}}]}},
             {"type": "user", "timestamp": ts, "message": {"content": [
                 {"type": "tool_result", "tool_use_id": "B1", "content": "token " + secret}]},
              "tool_use_result": {"stdout": "token " + secret, "stderr": ""}},
             {"type": "result", "subtype": "success", "total_cost_usd": 0.1}]
    (tmp / "lh" / "research" / "transcripts" / "1000000000-t.transcript.jsonl").write_text(
        "".join(json.dumps(o) + "\n" for o in lines))
    return "research:1000000000-t"


def test_content_only_when_asked_and_then_redacted(tmp_path, receiver):
    url, got = receiver
    rng = random.Random(7)
    secret = "".join(("gh", "p_", "".join(rng.choice(string.ascii_letters + string.digits)
                                          for _ in range(36))))
    tid = _kept(tmp_path, secret)
    run(tmp_path, tid, "--otlp", url)
    run(tmp_path, tid, "--otlp", url, "--content")
    plain, full = (json.dumps(x[2]) for x in got)
    assert "gen_ai.tool.call.result" not in plain
    assert "gen_ai.tool.call.result" in full and "gen_ai.tool.call.arguments" in full
    leaked = secret in full or secret in plain
    assert not leaked
    assert "echo hi" in full


def test_out_writes_the_body_and_sends_nothing(tmp_path, receiver):
    url, got = receiver
    out = tmp_path / "t.json"
    run(tmp_path, TID, "--out", str(out))
    assert not got
    assert spans_of(json.loads(out.read_text()))[0]["traceId"] == trace_id(TID)


def test_no_address_no_export(tmp_path):
    with pytest.raises(SystemExit) as e:
        run(tmp_path, TID)
    assert "--otlp" in str(e.value)
    with pytest.raises(SystemExit) as e:
        run(tmp_path, TID, "--otlp", "file:///etc/passwd")
    assert "http(s)" in str(e.value)


def test_the_setting_is_the_default_address(tmp_path, receiver):
    url, got = receiver
    (tmp_path / "lh" / "loop.yaml").write_text(f"trace:\n  export:\n    otlp_url: {url}\n")
    run(tmp_path, TID)
    assert len(got) == 1
