""" (the F1): the first brief at 8 kept and again over the whole
read, five places ticked for a topic's first watch, the first hour on the home, the status bar
while reading for the first time, no heartbeat before the first read, the cost on a login, and
whether a usage report was really sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kranto import health, library, progress, setup
from kranto.core import home, registry
from kranto.features.news import FEATURE as NEWS
from kranto.features.news import brief
from kranto.store import iso, utcnow

from .test_first_hour import _source_ids, _topic_id, first_read, news_rt  # noqa: F401
from .test_news import StubSearch
from .test_web import rt  # noqa: F401 - fixture


def reading(store, topic_id, *, kept, judged, run="going", start=0):
    """A read still going: its items seen so far, no runs row yet (tick.py writes that last)."""
    sid = _source_ids(store, topic_id)[0]
    for n in range(judged):
        store.insert("items_seen", {"source_id": sid, "item_id": f"{run}-{start + n}",
                                    "outcome": "contributed" if n < kept else "gated",
                                    "run_uuid": run, "created_at": iso(utcnow())})


# -- the first brief at 8 kept ---------------------------------------------------------------------


def test_read_counts_answers_a_read_that_is_still_going(rt):  # noqa: F811
    tid = _topic_id(rt.store)
    reading(rt.store, tid, kept=3, judged=10)
    assert progress.read_counts(rt.store, "going") == {tid: {"kept": 3, "judged": 10}}
    assert progress.read_counts(rt.store, "nothing") == {}


def test_early_brief_at_8_kept_once_then_the_first_reads_own(news_rt):  # noqa: F811
    store = news_rt.store
    tid = _topic_id(store)
    ctx = registry.context(news_rt, NEWS, searcher=StubSearch())
    ctx.clock = lambda: datetime(2026, 9, 24, 3, 0, tzinfo=UTC)
    # 7 kept: not yet
    assert brief.run_early(ctx, {tid: 7})["status"] == "skipped"
    out = brief.run_early(ctx, {tid: brief.EARLY_KEPT})
    assert out["briefs"] == 1
    row = store.query_one("SELECT * FROM news_briefs WHERE topic_id = ?", (tid,))
    assert row["trigger"] == brief.FIRST_EARLY
    # once a topic
    assert brief.run_early(ctx, {tid: 30})["status"] == "skipped"
    # the hourly job writes nothing while the read goes on (no first_read_at yet) ...
    assert brief.run_due(ctx)["briefs"] == 0
    # ... and the first read's own brief once it ends, over the whole read, not after the early
    first_read(store, tid)
    assert brief.run_due(ctx)["briefs"] == 1
    rows = store.query("SELECT * FROM news_briefs WHERE topic_id = ? ORDER BY id", (tid,))
    assert [r["trigger"] for r in rows] == [brief.FIRST_EARLY, brief.FIRST_READ]
    assert rows[1]["previous_id"] is None          # it reads past the early brief
    assert brief.run_due(ctx)["briefs"] == 0       # and once


def test_no_early_brief_once_the_first_read_ended_or_with_news_off(news_rt):  # noqa: F811
    from kranto.features.news import api
    store = news_rt.store
    tid = _topic_id(store)
    ctx = registry.context(news_rt, NEWS, searcher=StubSearch())
    api.toggle(ctx, {"topic_id": tid, "on": False})
    assert brief.run_early(ctx, {tid: 20})["status"] == "skipped"
    api.toggle(ctx, {"topic_id": tid, "on": True})
    first_read(store, tid)
    assert brief.run_early(ctx, {tid: 20})["status"] == "skipped"


def test_the_reads_hook_writes_the_early_brief_between_two_items(news_rt):  # noqa: F811
    from kranto.cli import early_briefs
    from kranto.tick import Progress
    store = news_rt.store
    tid = _topic_id(store)
    hook = early_briefs(news_rt)
    p = Progress("going", iso(utcnow()), 2, kept=3)
    reading(store, tid, kept=3, judged=6)
    hook(p)
    assert store.query_one("SELECT 1 FROM news_briefs") is None
    reading(store, tid, kept=5, judged=5, start=6)
    p.kept = 8
    hook(p)
    row = store.query_one("SELECT trigger FROM news_briefs WHERE topic_id = ?", (tid,))
    assert row["trigger"] == brief.FIRST_EARLY
    run = store.query_one("SELECT status FROM runs WHERE kind = 'news.brief'")
    assert run["status"] == "ok"
    # the same count again does nothing, and a hook that fails never stops the read
    hook(p)
    news_rt.store = None
    p.kept = 9
    hook(p)
    news_rt.store = store


# -- five places for a topic's first watch ---------------------------------------------------------


def test_a_topic_that_watches_nothing_yet_has_at_most_five_ticked():
    from kranto.web.topics_api import FIRST_TICKS, first_ticks
    rows = [{"id": i, "review": "proposed", "topics": [], "pretick": True, "_sim": i / 10}
            for i in range(8)]
    first_ticks(rows, 3)
    assert [r["id"] for r in rows if r["pretick"]] == [3, 4, 5, 6, 7]
    assert FIRST_TICKS == 5
    # a topic that already watches a place keeps the rule as it was
    rows = [{"id": i, "review": "proposed", "topics": [], "pretick": True, "_sim": i / 10}
            for i in range(8)] + [{"id": 9, "review": "approved", "topics": [{"id": 3}],
                                   "pretick": False, "_sim": 1.0}]
    first_ticks(rows, 3)
    assert sum(r["pretick"] for r in rows) == 8


# -- the first hour, the bar, the heartbeat --------------------------------------------------------


def test_the_home_shows_the_first_hour_until_the_first_brief(rt):  # noqa: F811
    store = rt.store
    tid = _topic_id(store)
    got = home.today(rt, next_run={"ingest": "2026-09-24T15:00:00Z"})["first"]
    assert got["topic"]["id"] == tid
    assert [r["key"] for r in got["rows"]] == ["sources", "read", "brief", "ideas"]
    assert got["early_kept"] == brief.EARLY_KEPT
    store.insert("news_briefs", {"topic_id": tid, "period_start": "x", "period_end": "y",
                                 "status": "ok", "items": "[]", "checks": "{}",
                                 "trigger": "first_early", "created_at": iso(utcnow())})
    assert home.today(rt)["first"] is None


def test_the_first_briefs_estimate_follows_the_reads_own_pace():
    now = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)
    assert home.brief_minutes(None, now) == 5
    started = iso(now - timedelta(seconds=100))
    # 4 kept of 20 read in 100 s: 5 s an item, 1 in 5 kept; 4 more need 20 items, 100 s, +60 s
    assert home.brief_minutes({"kept": 4, "judged": 20, "started_at": started}, now) == 3
    assert home.brief_minutes({"kept": 8, "judged": 20, "started_at": started}, now) is None


def test_the_bar_says_reading_for_the_first_time_never_degraded(store):
    library.add_source(store, "rss", {"url": "https://example.org/feed"}, label="a feed")
    said = health.health(store)
    assert said["word"] == "Reading for the first time" and said["tone"] == "grey"


def test_no_heartbeat_before_the_first_read(store, tmp_path):
    from kranto import heartbeat, notify

    from .test_strikes import make_cfg
    report = heartbeat.send_heartbeat(store, make_cfg(tmp_path), now=utcnow(),
                                      after_first_read=True)
    assert report.message_id is None
    assert notify.recent_messages(store, kind="heartbeat") == []
    # by hand (Kranto heartbeat --now) it still says that nothing ran
    assert heartbeat.send_heartbeat(store, make_cfg(tmp_path), now=utcnow()).message_id


def test_the_cost_on_a_claude_code_login_is_the_plans_usage():
    assert setup.cost_words(None, "claude_code") == setup.COST_PLAN
    assert "$" not in setup.COST_PLAN
    assert setup.cost_words(None, "openrouter").startswith(setup.COST)
