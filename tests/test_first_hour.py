"""The first hour of a topic (package HOUR's H1): News on for a topic when it is made,
the first brief when its first read ends whatever the hour, the jobs that follow a run in the
same round (the first cards the night a map is drawn), and the topic's four rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from kranto import library, progress, scheduler
from kranto.core import registry
from kranto.features.news import FEATURE as NEWS
from kranto.features.news import brief
from kranto.scheduler import Job, Scheduler
from kranto.store import iso, utcnow

from .conftest import chat_response, web_client
from .test_news import StubSearch, item, reply
from .test_web import rt  # noqa: F401 - fixture


def _topic_id(store) -> int:
    return int(store.query_one("SELECT id FROM topics ORDER BY id LIMIT 1")["id"])


def _source_ids(store, topic_id) -> list[int]:
    return [r["source_id"] for r in store.query(
        "SELECT source_id FROM topic_links WHERE topic_id = ?", (topic_id,))]


def first_read(store, topic_id, *, at=None, kept=1, judged=3, status="ok", run="read-1"):
    """An ingest run that fetched the topic's sources and ended at ``at``: what tick.py records
    (its fetches as it goes, its items seen, its runs row at the end)."""
    at = at or utcnow()
    for sid in _source_ids(store, topic_id):
        store.insert("source_fetches", {"source_id": sid, "run_uuid": run, "trigger": "run",
                                        "state": "ok", "fetched": judged, "new": judged,
                                        "error": None, "created_at": iso(at)})
        for n in range(judged):
            store.insert("items_seen", {"source_id": sid, "item_id": f"{run}-{n}",
                                        "outcome": "contributed" if n < kept else "gated",
                                        "run_uuid": run, "created_at": iso(at)})
    store.insert("runs", {"run_uuid": run, "kind": "ingest", "status": status,
                          "started_at": iso(at - timedelta(minutes=5)), "finished_at": iso(at),
                          "summary": "{}", "error": None})


# -- News on for a topic the owner makes -----------------------------------------------------------


def test_a_topic_made_now_has_news_on_and_one_made_before_keeps_its_setting(rt):  # noqa: F811
    store = rt.store
    new = library.add_topic(store, rt.embedder, "padel", "padel rackets, clubs and tours")
    row = store.query_one("SELECT * FROM news_topics WHERE topic_id = ?", (new,))
    assert row["enabled"] == 1 and row["origin"] == brief.NEW_TOPIC
    # a topic from before this change has no row: News stays off for it
    old = store.insert("topics", {"name": "old", "description": "from before",
                                  "embedding": store.query_one(
                                      "SELECT embedding FROM topics")["embedding"],
                                  "embedding_model": rt.embedder.model_name,
                                  "created_at": "2026-01-01T00:00:00Z"})
    store.set_status("topic", old, "active")
    ctx = registry.context(rt, NEWS, searcher=StubSearch())
    assert brief.topic_setting(ctx, new)["enabled"]
    assert not brief.topic_setting(ctx, old)["enabled"]


def test_a_new_topic_row_follows_the_owners_hour_until_the_topic_sets_its_own(rt):  # noqa: F811
    from kranto.features.news import api
    store = rt.store
    tid = _topic_id(store)
    rt.cfg = rt.cfg.__class__(**{**rt.cfg.__dict__, "features": {
        "news": {**registry.settings.section(rt.cfg, "news"), "news.hour": 18}}})
    ctx = registry.context(rt, NEWS, searcher=StubSearch())
    assert brief.topic_setting(ctx, tid)["hour"] == 18
    api.toggle(ctx, {"topic_id": tid, "on": True, "hour": 9})
    assert brief.topic_setting(ctx, tid)["hour"] == 9


def test_a_project_topic_gets_no_news_row(rt):  # noqa: F811
    tid = library.add_topic(rt.store, rt.embedder, "Recall", "the project recall",
                            kind="project", ref="project:recall")
    assert rt.store.query_one("SELECT 1 FROM news_topics WHERE topic_id = ?", (tid,)) is None


# -- the first read --------------------------------------------------------------------------------


def test_the_first_read_is_the_first_ingest_that_fetched_a_source_after_it_was_linked(rt):  # noqa: F811,E501
    store = rt.store
    tid = _topic_id(store)
    assert progress.first_read(store, tid) is None
    # a fetch from before the link does not count
    sid = _source_ids(store, tid)[0]
    store.insert("source_fetches", {"source_id": sid, "run_uuid": "early", "trigger": "run",
                                    "state": "ok", "fetched": 1, "new": 1, "error": None,
                                    "created_at": "2020-01-01T00:00:00Z"})
    store.insert("runs", {"run_uuid": "early", "kind": "ingest", "status": "ok",
                          "started_at": "2020-01-01T00:00:00Z",
                          "finished_at": "2020-01-01T00:01:00Z", "summary": "{}",
                          "error": None})
    assert progress.first_read(store, tid) is None
    # a run in progress has fetched but has no runs row yet: not ended
    store.insert("source_fetches", {"source_id": sid, "run_uuid": "going", "trigger": "run",
                                    "state": "ok", "fetched": 1, "new": 1, "error": None,
                                    "created_at": iso(utcnow() + timedelta(seconds=1))})
    assert progress.first_read(store, tid) is None
    store.insert("runs", {"run_uuid": "going", "kind": "ingest", "status": "ok",
                          "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                          "summary": "{}", "error": None})
    got = progress.first_read(store, tid)
    assert got["run_uuid"] == "going" and progress.first_read_at(store, tid) == got["finished_at"]
    # topics.list carries it for News (an additive v1 field)
    ctx = registry.context(rt, NEWS, searcher=StubSearch())
    row = next(t for t in ctx.read("topics.list")["topics"] if t["id"] == tid)
    assert row["first_read_at"] == got["finished_at"]


# -- the first brief -------------------------------------------------------------------------------


@pytest.fixture
def news_rt(rt, make_client):  # noqa: F811
    replies = [reply([item()])]

    def handler(body):
        return chat_response(replies.pop(0) if replies else reply([]), cost=0.04)

    rt.llm = make_client(handler)
    brief.LOCAL_TZ = UTC
    yield rt
    brief.LOCAL_TZ = None


def test_the_first_brief_is_written_when_the_first_read_ends_whatever_the_hour(news_rt):
    store = news_rt.store
    tid = _topic_id(store)
    ctx = registry.context(news_rt, NEWS, searcher=StubSearch())
    # 03:00, hours before the topic's hour (7): nothing is due, as before
    at = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    ctx.clock = lambda: at
    assert brief.run_due(ctx)["status"] == "skipped"
    first_read(store, tid)    # just now: after the link (the brief job runs on its own clock)
    out = brief.run_due(ctx)
    assert out["briefs"] == 1
    row = store.query_one("SELECT * FROM news_briefs WHERE topic_id = ?", (tid,))
    assert row["trigger"] == brief.FIRST_READ and row["status"] == "ok"
    # once a topic; and the day it covers has its brief: 07:00 writes none ("Tomorrow's covers
    # a day")
    assert brief.run_due(ctx)["briefs"] == 0
    ctx.clock = lambda: at.replace(hour=8)
    assert brief.run_due(ctx)["briefs"] == 0
    ctx.clock = lambda: at + timedelta(days=1, hours=5)
    assert brief.run_due(ctx)["briefs"] == 1


def test_no_first_brief_while_news_is_off_and_a_failed_one_is_tried_twice(news_rt, make_client):
    from kranto.features.news import api
    store = news_rt.store
    tid = _topic_id(store)
    ctx = registry.context(news_rt, NEWS, searcher=StubSearch())
    at = datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    ctx.clock = lambda: at
    first_read(store, tid)    # just now: after the link (the brief job runs on its own clock)
    api.toggle(ctx, {"topic_id": tid, "on": False})
    assert brief.run_due(ctx)["briefs"] == 0
    api.toggle(ctx, {"topic_id": tid, "on": True, "hour": 7})

    news_rt.llm = make_client(lambda body: chat_response("not json at all"))
    ctx = registry.context(news_rt, NEWS, searcher=StubSearch())
    ctx.clock = lambda: at
    for _ in range(3):
        brief.run_due(ctx)
    tries = store.query("SELECT status, trigger FROM news_briefs WHERE topic_id = ?", (tid,))
    assert [(r["status"], r["trigger"]) for r in tries] == [("failed", "first_read")] * 2


# -- jobs that follow a run ------------------------------------------------------------------------


def _job(store, kind, every, ran, *, record=True):
    def run():
        ran.append(kind)
        if record:
            store.insert("runs", {"run_uuid": f"{kind}-{len(ran)}", "kind": kind,
                                  "status": "ok", "started_at": iso(utcnow()),
                                  "finished_at": iso(utcnow()), "summary": "{}",
                                  "error": None})
    return Job(kind, every, run)


def test_a_follower_runs_in_the_same_round_right_after_the_run_it_follows(store):
    ran: list[str] = []
    # the brief ran a minute ago (hourly: not due); the read is due now
    store.insert("runs", {"run_uuid": "b0", "kind": "news.brief", "status": "ok",
                          "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                          "summary": "{}", "error": None})
    s = Scheduler(store, [_job(store, "ingest", 3, ran), _job(store, "news.brief", 1, ran)])
    assert s.run_due() == ["ingest", "news.brief"]
    # nothing is due now, and nothing follows a round with no run
    assert s.run_due() == []


def test_a_skip_leads_nothing_and_an_off_follower_never_runs(store):
    ran: list[str] = []
    s = Scheduler(store, [_job(store, "snapshot", 24, ran, record=False),
                          _job(store, "ideas", 0, ran)])
    assert s.run_due() == ["snapshot"]
    s = Scheduler(store, [_job(store, "snapshot", 24, ran), _job(store, "ideas", 0, ran)])
    assert s.run_due() == ["snapshot"]
    assert scheduler.FOLLOWS["snapshot"] == ("ideas",)


def test_a_pressed_read_is_followed_by_the_brief_and_a_pressed_map_is_not(store):
    import time
    ran: list[str] = []
    store.insert("runs", {"run_uuid": "i0", "kind": "ideas", "status": "ok",
                          "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                          "summary": "{}", "error": None})
    s = Scheduler(store, [_job(store, "ingest", 3, ran), _job(store, "snapshot", 24, ran),
                          _job(store, "ideas", 24, ran), _job(store, "news.brief", 1, ran)])
    assert s.trigger("ingest")
    for _ in range(100):
        if not s.busy:
            break
        time.sleep(0.02)
    assert ran == ["ingest", "news.brief"]
    assert s.trigger("snapshot")
    for _ in range(100):
        if not s.busy:
            break
        time.sleep(0.02)
    assert ran == ["ingest", "news.brief", "snapshot"]


# -- the topic's four rows -------------------------------------------------------------------------


def test_the_four_rows_from_a_new_topic_to_its_first_idea(rt):  # noqa: F811
    store = rt.store
    tid = library.add_topic(store, rt.embedder, "padel", "padel rackets, clubs and tours")
    nxt = {"ingest": "2026-09-24T15:00:00Z", "snapshot": "2026-09-24T22:00:00Z",
           "news.brief": "2026-09-24T13:00:00Z"}
    got = progress.topic_start(store, tid, next_runs=nxt, news_on=True)
    assert [r["title"] for r in got["rows"]] == ["Sources", "First read", "First brief",
                                                 "First ideas"]
    assert [r["state"] for r in got["rows"]] == ["waiting"] * 4 and not got["done"]
    src = library.add_source(store, "rss", {"url": "https://padel.example/feed"},
                             label="Padel Feed")
    library.link_topic_source(store, tid, src)
    got = progress.topic_start(store, tid, next_runs=nxt, news_on=True)
    assert got["rows"][0]["state"] == "done" and got["rows"][0]["words"] == "1 source watched"
    assert got["rows"][1] == {"key": "read", "title": "First read", "state": "waiting",
                              "words": "At the next read", "at": "2026-09-24T15:00:00Z"}
    # fix 10 and before the first read ends the brief comes once 8 items
    # are kept, with no other job's time beside it; the ideas follow tonight's map
    assert got["rows"][2]["words"] == "As soon as 8 items are kept"
    assert got["rows"][2]["at"] is None
    assert got["rows"][3]["at"] == "2026-09-24T22:00:00Z"
    reading = progress.topic_start(store, tid, next_runs=nxt, news_on=True,
                                   reading={"sources": 8, "source_index": 2,
                                            "started_at": "2026-09-24T12:00:00Z"})
    assert reading["rows"][1]["state"] == "running"
    assert reading["rows"][1]["words"] == "Reading now: source 2 of 8"
    # the first read ends with one item kept: quiet
    first_read(store, tid, kept=1, judged=4)
    got = progress.topic_start(store, tid, next_runs=nxt, news_on=True)
    assert got["rows"][1]["state"] == "done" and got["rows"][1]["words"] == \
        "Kept 1 of 4 items read"
    assert got["rows"][2]["state"] == "waiting"
    # the first read ended and no brief yet (News turned on later, as Padel's on the preview):
    # it waits for News' own hour, never "as soon as the first read ends" (the walk)
    assert got["rows"][2]["words"] == "Written at News' next hour"
    assert got["rows"][2]["at"] == "2026-09-24T13:00:00Z"
    assert got["quiet"] == ("A quiet topic takes longer. One item in the first read is few. "
                            "Scout more sources or widen the sentence, and ideas come sooner.")
    assert progress.topic_start(store, tid, next_runs=nxt, news_on=False)["rows"][2]["state"] \
        == "off"
    assert progress.topic_start(store, tid, next_runs=nxt, news_on=True,
                                brief_running=True)["rows"][2]["state"] == "running"
    store.insert("news_briefs", {"topic_id": tid, "period_start": "x", "period_end": "y",
                                 "status": "ok", "items": json.dumps([{"headline": "h"}] * 3),
                                 "checks": "{}", "trigger": "first_read",
                                 "created_at": "2026-09-24T12:10:00Z"})
    got = progress.topic_start(store, tid, next_runs=nxt, news_on=True)
    assert got["rows"][2] == {"key": "brief", "title": "First brief", "state": "done",
                              "words": "3 items", "at": "2026-09-24T12:10:00Z",
                              "brief_id": got["rows"][2]["brief_id"]}
    # 4 observations of 30: the words say how far
    ideas = got["rows"][3]
    assert ideas["words"] == f"After the map, once 30 items are kept. So far: " \
        f"{progress.observation_count(store)}." and ideas["at"] == "2026-09-24T22:00:00Z"
    assert progress.ideas_wait(store, {}, 4, 30)["at"] is None        # no scheduler: no time


def test_with_the_scheduler_off_or_no_key_the_rows_say_why_nothing_comes(rt):  # noqa: F811
    """ 8 (Codex 6, Gemini 18): on a copy with the scheduler off and no key the rows said
    "At the next read" and "Written as soon as the first read ends"; nothing could run."""
    store = rt.store
    tid = library.add_topic(store, rt.embedder, "padel", "padel rackets, clubs and tours")
    src = library.add_source(store, "rss", {"url": "https://padel.example/feed"}, label="Padel")
    library.link_topic_source(store, tid, src)
    off = progress.topic_start(store, tid, next_runs=None, news_on=True)
    assert off["rows"][1]["words"] == progress.STUCK_SCHEDULER and off["rows"][1]["at"] is None
    assert off["rows"][2]["words"] == progress.STUCK_SCHEDULER and off["rows"][2]["at"] is None
    nxt = {"ingest": "2026-09-24T15:00:00Z", "news.brief": "2026-09-24T13:00:00Z"}
    nokey = progress.topic_start(store, tid, next_runs=nxt, news_on=True, no_key=True)
    assert nokey["rows"][1]["words"] == progress.STUCK_KEY
    assert "Settings › Watching" in progress.STUCK_KEY


def test_first_ideas_names_the_next_map_once_30_are_kept_and_the_rows_leave_with_a_card(rt):  # noqa: F811,E501
    from .test_ideas_api import add_card, obs_ids, old_card
    store = rt.store
    tid = _topic_id(store)
    nxt = {"snapshot": "2026-09-24T22:00:00Z"}
    got = progress.ideas_wait(store, nxt, 31, 30)
    assert got == {"words": "After the next map", "at": "2026-09-24T22:00:00Z"}
    add_card(store, "Solar kits for clinics", old_card(store, obs_ids(store)[:2]))
    got = progress.topic_start(store, tid, next_runs=nxt, news_on=True)
    assert got["done"] and got["rows"][3]["state"] == "done" and got["quiet"] is None


def test_the_start_route_answers_the_rows_and_404_for_no_topic(rt):  # noqa: F811
    from kranto.web.app import create_app
    tid = _topic_id(rt.store)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        got = web.get(f"/api/topics/{tid}/start").json()
        assert [r["key"] for r in got["rows"]] == ["sources", "read", "brief", "ideas"]
        assert got["rows"][2]["state"] in ("waiting", "off")
        assert web.get("/api/topics/999/start").status_code == 404


def test_watch_these_on_a_topic_never_read_starts_its_first_read(rt):  # noqa: F811
    from kranto import setup
    from kranto.web.app import create_app
    store = rt.store
    tid = library.add_topic(store, rt.embedder, "padel", "padel rackets, clubs and tours")
    src = library.add_source(store, "rss", {"url": "https://padel.example/feed"},
                             label="Padel Feed")
    store.set_status("source", src, "proposed")

    class Sched:
        pressed: list = []
        running = None

        def trigger(self, kind, origin="press", by=None):
            self.pressed.append((kind, origin, by))
            return True

        def next_runs(self):
            return {}

    app = create_app(rt)
    with web_client(app, "http://127.0.0.1:8765") as web:
        app.state.app.scheduler = Sched()
        # before setup is done, Welcome's own finish starts the read
        r = web.post("/api/sources/approve", json={"ids": [src], "topic": tid})
        assert r.status_code == 200 and r.json()["first_read"] is None
        setup.mark_done(store, "auto", 1)
        src2 = library.add_source(store, "rss", {"url": "https://padel.example/two"},
                                  label="Padel Two")
        store.set_status("source", src2, "proposed")
        r = web.post("/api/sources/approve", json={"ids": [src2], "topic": tid})
        assert r.json()["first_read"] == "started"
        assert Sched.pressed == [("ingest", "press", "ui")]
        # a topic read before starts nothing
        first_read(store, tid)
        src3 = library.add_source(store, "rss", {"url": "https://padel.example/three"},
                                  label="Padel Three")
        store.set_status("source", src3, "proposed")
        assert web.post("/api/sources/approve",
                        json={"ids": [src3], "topic": tid}).json()["first_read"] is None
