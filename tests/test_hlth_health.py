""""Degraded" says why, worked out once on the server (``health.health``).

The status bar's word was the browser's alone and said no reason; on live (2026-10-29) the
owner saw Degraded and the console could not say why. Here each rule gives its one line, the
line names no setting key, uuid or class, a run's line opens its trace, and ``/api/today`` and
``/api/activity`` serve the same answer.
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta

import pytest

from kranto import health as H
from kranto import paths
from kranto.store import iso
from kranto.web.app import create_app

from .conftest import FIXED_NOW, web_client
from .test_web import rt  # noqa: F401 - fixture

NOW = FIXED_NOW
RUN = "3ad8f80e82ef43f481c2aa8905c68e48"
# live's 12:42 reply and its row, as they are stored
FILTERED = json.dumps({"choices": [{"finish_reason": "content_filter", "message": {
    "content": None, "refusal": "This request triggered cyber-related safeguards."}}]})
LIVE_ERROR = ("provider reported cost None; counted at a conservative estimate of $0.4379 for "
              "model 'anthropic/claude-haiku-5.5'; set llm.cost_source to 'table' and add "
              "pricing for it")


def run(store, status, *, error=None, sources=(), uuid=RUN, at=NOW - timedelta(minutes=5)):
    store.insert("runs", {"run_uuid": uuid, "kind": "ingest", "status": status,
                          "started_at": iso(at - timedelta(minutes=6)), "finished_at": iso(at),
                          "summary": json.dumps({"sources": list(sources)}), "error": error})


def call(store, *, status="error", error=None, response="{}", provider="openrouter",
         tokens=None, uuid=RUN, purpose="judge", at=NOW - timedelta(minutes=5)):
    store.insert("llm_calls", dict(
        run_uuid=uuid, purpose=purpose, tier="judge", model="anthropic/claude-haiku-5.5",
        prompt_version="v", request="{}", response=response, status=status, error=error,
        http_status=200, attempts=1, prompt_tokens=tokens, completion_tokens=tokens,
        cost_usd=0, provider=provider, created_at=iso(at)))


def said(store, **kw):
    return H.health(store, now=NOW, **kw)


def clean(reason: str | None) -> None:
    """One line of plain words: no setting key, uuid, class name or dollar figure."""
    assert reason and "\n" not in reason and len(reason) <= 200
    assert not re.search(r"\b[a-z]+\.[a-z_]+_[a-z_]+\b|\b[0-9a-f]{32}\b", reason), reason
    assert not re.search(r"LLMError|UnpricedModel|Exception|cost_source|\$\d", reason), reason


def test_a_failed_run_on_live_s_refusal_says_what_happened_and_opens_its_trace(store):
    """Live's 12:36 run, as stored before its error is about pricing, its call says
    the reply was a safety filter's."""
    run(store, "failed", error=LIVE_ERROR, at=NOW.replace(hour=12, minute=42))
    call(store, error="reply had no content; provider reported cost None; counted at a "
                      "conservative estimate of $0.4379", response=FILTERED)
    h = said(store)
    assert h["word"] == "Degraded" and h["tone"] == "amber"
    assert h["reason"] == ("The last read of your sources failed at 12:42: a safety filter at "
                           "OpenRouter declined one item")
    assert h["trace"] == f"#/afk/{RUN}/trace" and h["run"] == RUN
    clean(h["reason"])


def test_an_empty_reply_is_said_as_one(store):
    run(store, "failed", error="whatever the run said")
    call(store, error="reply had no content; provider reported cost None")
    assert said(store)["reason"].endswith(": OpenRouter sent an empty reply")


def test_a_degraded_run_counts_what_went_wrong(store):
    run(store, "degraded", sources=[
        {"label": "a", "llm_errors": 2, "empty_replies": 1, "item_errors": 1, "refused": 1},
        {"label": "b", "fetch_state": "needs_login"}])
    call(store, error="OpenRouter sent an empty reply (HTTP 200, no content, no tokens, "
                      "no cost) 4 times")
    h = said(store)
    assert h["word"] == "Degraded"
    # the two first, the rest counted: one line, its trace has them all
    assert h["reason"].endswith(": OpenRouter sent 1 empty reply (read again next run); a "
                                "safety filter declined 1 item; and 2 more in its trace")
    clean(h["reason"])
    run(store, "degraded", uuid="b" * 32, at=NOW, sources=[
        {"label": "a", "llm_errors": 1, "empty_replies": 1}])
    assert said(store)["reason"].endswith("had problems: the model provider sent 1 empty reply "
                                          "(read again next run)")


def test_the_verb_agrees_with_the_count(store):
    """Live, 0.6.0.dev16: "2 sources keeps failing to fetch"."""
    run(store, "degraded", sources=[{"label": "a", "fetch_state": "failing"},
                                    {"label": "b", "fetch_state": "failing"}])
    assert said(store)["reason"].endswith("had problems: 2 sources keep failing to fetch")
    run(store, "degraded", uuid="c" * 32, at=NOW, sources=[
        {"label": "a", "fetch_state": "needs_login"}, {"label": "b", "fetch_state": "needs_login"},
        {"label": "c", "fetch_state": "failing"}])
    assert said(store)["reason"].endswith(
        "had problems: 2 sources need you to sign in again; 1 source keeps failing to fetch")


def test_a_run_from_before_today_says_its_day(store):
    run(store, "failed", error="every source failed to fetch", at=NOW - timedelta(days=2))
    assert re.match(r"The last read of your sources failed on \d+ \w{3} at \d\d:\d\d: every source",
                    said(store)["reason"])


def test_a_refused_key_is_said_in_words(store):
    run(store, "failed", error="HTTP 401 from https://openrouter.ai/api/v1: User not found")
    assert said(store)["reason"].endswith(": the OpenRouter key was refused")


def test_no_run_yet(store):
    # a home with nothing watched is new, not broken
    assert said(store) == {"word": "Not set up yet", "tone": "grey",
                           "reason": "Choose a topic to watch on Welcome", "at": None,
                           "run": None, "trace": None}
    from kranto import library
    library.add_source(store, "rss", {"url": "https://example.org/feed"}, label="a feed")
    # fix 7: watched, nothing read yet, is the first read, never Degraded
    assert said(store) == {"word": "Reading for the first time", "tone": "grey",
                           "reason": "Kranto is reading your sources for the first time",
                           "at": None, "run": None, "trace": None}


def test_judge_errors_over_one_in_five(store):
    run(store, "ok")
    for i in range(4):
        call(store, status="ok", uuid=f"r{i}")
    call(store, uuid="r9", error="OpenRouter sent an empty reply (HTTP 200, no content, "
                                 "no tokens, no cost) 4 times")
    call(store, uuid="r8", error="HTTP 400: too long")
    h = said(store)
    assert h["reason"].startswith("2 of 6 judge calls failed in the last 24 hours: ")
    clean(h["reason"])


def test_healthy_says_nothing(store):
    run(store, "ok")
    assert said(store, loop={"paused": False, "running": True}) == {
        "word": "Healthy", "tone": "green", "reason": None, "at": None, "run": None,
        "trace": None}


def test_the_loop(store):
    run(store, "ok")
    assert said(store, loop={"paused": False, "running": False})["reason"] == \
        "The build loop is not running"
    assert said(store, loop={"paused": True, "running": False}) == {
        "word": "Paused", "tone": "amber", "reason": "The build loop is paused", "at": None,
        "run": None, "trace": None}


def test_paused_watching_comes_first(store):
    run(store, "failed", error="x")
    store.pause("you paused it")
    h = said(store)
    assert h["word"] == "Paused" and h["reason"] == "Watching is paused: you paused it"


def test_loop_state_reads_the_loop_s_files(tmp_path):
    home = tmp_path / "loop"
    home.mkdir()
    layout = paths.LoopLayout(home)
    assert H.loop_state(home) == {"paused": False, "running": False}
    layout.pid.write_text(str(os.getpid()))
    layout.pause.write_text("")
    assert H.loop_state(home) == {"paused": True, "running": True}
    assert H.loop_state(None) is None


@pytest.mark.parametrize("path", ["/api/today", "/api/activity"])
def test_today_and_activity_serve_the_same_answer(rt, path):  # noqa: F811 - fixture
    run(rt.store, "failed", error=LIVE_ERROR)
    call(rt.store, error="reply had no content", response=FILTERED)
    want = H.health(rt.store)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        body = web.get(path).json()
    got = body["ingest"]["health"] if path == "/api/today" else body["health"]
    assert got == want and got["word"] == "Degraded"
    assert "a safety filter at OpenRouter declined one item" in got["reason"]
