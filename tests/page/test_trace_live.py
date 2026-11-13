"""A running trace, live: the page asks to follow a running session's
trace, the watcher stats its files and publishes a ``trace`` change when one grows (and only for
a followed trace), the page reads on from its cursor and gets the new spans, a follow lapses, and
a session that is over is not followed. Lines appended in a temp dir; no model, no network."""
from __future__ import annotations

import json
import time

import pytest

from kranto.page.trace import service
from kranto.page.ui import api, live

from .term_common import make_home
from .test_trace_session import TID as SESSION
from .test_trace_session import make_session

TID = f"session:{SESSION}"


@pytest.fixture
def app(tmp_path):
    cfg = make_home(tmp_path)
    service._TRACES.clear()
    live.FOLLOWS.by.clear()
    a = api.App(None, "fake", cfg.home)
    a.transcript = make_session(cfg.home, state="running", reason=None)
    yield a
    live.FOLLOWS.by.clear()


def get(app, path, **q):
    code, _, body = api.handle("GET", path, q, app=app)
    assert code == 200, body
    return json.loads(body)


def turn(n: int) -> list[str]:
    """One turn: a Bash call, then its result (two lines)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return [json.dumps(o) + "\n" for o in (
        {"type": "assistant", "sessionId": "s-1", "uuid": f"a{n}", "timestamp": ts, "message": {
            "id": f"live-{n}", "usage": {"input_tokens": 5, "output_tokens": 9},
            "content": [{"type": "tool_use", "id": f"live-tool-{n}", "name": "Bash",
                         "input": {"command": f"pytest -q -k live_{n}"}}]}},
        {"type": "user", "sessionId": "s-1", "uuid": f"u{n}", "timestamp": ts,
         "message": {"content": [{"type": "tool_result", "tool_use_id": f"live-tool-{n}",
                                  "content": "1 passed"}]}})]


def append(app, text: str) -> None:
    with open(app.transcript, "a") as fh:
        fh.write(text)


def test_a_followed_running_trace_publishes_when_it_grows(app):
    first = get(app, "/api/trace/spans", trace=TID, limit="2000")
    w = live.Watcher(app)
    assert w.changes() is None                           # the baseline
    fo = get(app, "/api/trace/follow", trace=TID)
    assert fo["running"] is True and fo["until"] == live.FOLLOW_S
    assert w.changes() is None                           # a new follow is no change
    append(app, "".join(turn(1)))
    c = w.changes()
    assert c is not None and "trace" in c["kinds"] and TID in c["keys"]
    assert w.changes() is None
    page = get(app, "/api/trace/spans", trace=TID, after=first["cursor"])
    assert page["spans"] and page["total"] > first["total"]


def test_a_half_written_line_waits_for_its_end(app):
    first = get(app, "/api/trace/spans", trace=TID, limit="2000")
    call, done = turn(1)
    append(app, call[: len(call) // 2])                  # half a line: nothing new yet
    page = get(app, "/api/trace/spans", trace=TID, after=first["cursor"])
    assert page["total"] == first["total"] and page["spans"] == []
    append(app, call[len(call) // 2:] + done)
    page = get(app, "/api/trace/spans", trace=TID, after=page["cursor"])
    ok = [s for s in page["spans"] if s["kind"] == "tool" and s["status"] == "ok"]
    assert ok                                            # the result finished its call


def test_a_trace_nobody_follows_publishes_nothing_and_a_follow_lapses(app):
    w = live.Watcher(app)
    w.changes()
    append(app, "".join(turn(1)))
    c = w.changes()
    assert c is None or "trace" not in c["kinds"]        # not followed: not even statted
    get(app, "/api/trace/follow", trace=TID)
    o = service._TRACES[next(iter(service._TRACES))].open_[TID]
    live.FOLLOWS.add(TID, o.t.files, 0.0)                 # its time is up
    time.sleep(0.01)
    w.changes()
    append(app, "".join(turn(2)))
    c = w.changes()
    assert c is None or "trace" not in c["kinds"]
    assert TID not in live.FOLLOWS.by


def test_a_session_that_is_over_is_not_followed(app):
    rec_f = app.transcript.parents[3] / "session.json"
    rec = json.loads(rec_f.read_text())
    rec_f.write_text(json.dumps({**rec, "state": "ended", "reason": "owner"}))
    fo = get(app, "/api/trace/follow", trace=TID)
    assert fo["running"] is False and fo["until"] == 0
    assert TID not in live.FOLLOWS.by


def test_the_stream_carries_the_trace_change(app):
    get(app, "/api/trace/follow", trace=TID)
    it = api.stream("/api/stream", app=app)
    next(it), next(it)                                   # retry, host
    append(app, "".join(turn(3)))
    end = time.monotonic() + 10
    while time.monotonic() < end:
        chunk = next(it)
        if chunk.startswith(b"id:"):
            data = json.loads(chunk.split(b"data: ", 1)[1])
            if "trace" in data["kinds"]:
                assert TID in data["keys"]
                break
    else:
        raise AssertionError("no trace change within 10 s")
    it.close()


def test_the_cursor_survives_a_reconnect(app):
    """A page that slept reads on from its last cursor in one request: no gap, no repeat."""
    a = get(app, "/api/trace/spans", trace=TID, limit="2000")
    append(app, "".join(turn(1) + turn(2)))
    b = get(app, "/api/trace/spans", trace=TID, after=a["cursor"], limit="2000")
    ids = {s["id"] for s in a["spans"]} | {s["id"] for s in b["spans"]}
    whole = get(app, "/api/trace/spans", trace=TID, limit="2000")
    assert {s["id"] for s in whole["spans"]} <= ids         # every span arrived, none missed
    assert b["total"] == whole["total"] > a["total"]
    service._TRACES.clear()                               # the server restarted: start over
    code, _, body = api.handle("GET", "/api/trace/spans", {"trace": TID, "after": b["cursor"]},
                               app=app)
    assert code == 422 and "from the top" in json.loads(body)["error"]
