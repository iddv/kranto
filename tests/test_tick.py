import json
import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from kranto import library, sources
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.sources import Item, SourceError
from kranto.tick import run_ingest, run_lock

from .conftest import (
    SCREEN_PASS,
    chat_response,
    is_screen,
    judge_requests,
    llm_config,
    screen_requests,
)

CONTRIB = json.dumps({
    "kind": "beat", "summary": "a concrete thing", "why_it_matters": "because",
    "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9,
})


class FakeSource:
    kind = "fake"
    feeds: dict[str, list[Item] | Exception] = {}

    def __init__(self, http, *, name):
        self.name = name

    @property
    def label(self):
        return f"fake:{self.name}"

    def fetch(self):
        feed = self.feeds[self.name]
        if isinstance(feed, Exception):
            raise feed
        return list(feed)

    def enrich(self, item):
        return item


@pytest.fixture(autouse=True)
def fake_kind(monkeypatch):
    monkeypatch.setitem(sources.KINDS, "fake", FakeSource)
    FakeSource.feeds = {}


def items(n, prefix="item", text="solar microgrid battery", start=0):
    base = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        Item(id=f"{prefix}{i}", title=f"{text} {i}", body=f"{text} body {i}",
             url=f"https://ex.com/{prefix}{i}", published_at=base + timedelta(hours=i))
        for i in range(start, start + n)
    ]


@pytest.fixture
def cfg(tmp_path):
    return Config(
        root=tmp_path,
        llm=llm_config(),
        budget=BudgetConfig(monthly_usd=10),
        ingest=IngestConfig(max_items_per_source=10, prefilter_min_similarity=0.3,
                            exploration_fraction=0.0),
        map=MapConfig(),
    )


def add(store, name, feed):
    FakeSource.feeds[name] = feed
    return library.add_source(store, "fake", {"name": name}, label=f"fake:{name}")


def ingest(cfg, store, client, embedder, **kw):
    return run_ingest(cfg, store, client, embedder, sources.HTTP(), **kw)


def seen(store):
    return {r["item_id"]: r["outcome"] for r in store.query("SELECT * FROM items_seen")}


def test_a_new_home_without_sources_or_key_skips_rather_than_fails(cfg, store, make_client,
                                                                   embedder):
    """kranto up starts the scheduler before onboarding: with nothing to read, the first
    ingest is a skip, not a 'no API key' failure on Health. With sources, no key fails."""
    client = make_client(lambda body: chat_response(CONTRIB), api_key="")
    report = ingest(cfg, store, client, embedder)
    assert report.status == "skipped" and report.error == "no approved sources"
    add(store, "a", items(1))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "failed" and "no API key" in report.error


def test_contributes_and_never_rejudges(cfg, store, make_client, embedder):
    add(store, "a", items(3))
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "ok"
    assert report.contributed == 3
    assert store.query_one("SELECT COUNT(*) n FROM observations")["n"] == 3
    assert set(seen(store).values()) == {"contributed"}
    obs = store.query_one("SELECT * FROM observations")
    assert obs["llm_call_id"] and obs["prompt_version"].startswith("judge-")
    assert obs["source_excerpt"] and obs["admitted_by"] == "no_topics"

    report2 = ingest(cfg, store, client, embedder)
    assert report2.contributed == 0
    # One screen and one judge call per item, and none on the second run.
    assert len(judge_requests(client)) == 3 and len(screen_requests(client)) == 3
    assert {r["purpose"] for r in store.query("SELECT purpose FROM llm_calls")} == \
        {"screen", "judge"}
    assert all(r["screen_call_id"] for r in store.query("SELECT * FROM items_seen"))
    run = store.query_one("SELECT * FROM runs WHERE run_uuid = ?", (report.run_uuid,))
    assert run["status"] == "ok"
    assert json.loads(run["summary"])["contributed"] == 3


def test_dead_key_fails_the_run_and_consumes_nothing(cfg, store, make_client, embedder):
    add(store, "a", items(5))
    add(store, "b", items(5, prefix="other"))
    client = make_client(lambda body: httpx.Response(401, json={"error": {"message": "bad key"}}))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "failed"
    assert "401" in report.error
    assert len(client.fake.requests) == 1
    assert seen(store) == {}
    assert store.query_one("SELECT status FROM runs")["status"] == "failed"
    assert report.sources[1].not_reached


def test_payment_required_is_fatal_too(cfg, store, make_client, embedder):
    add(store, "a", items(2))
    client = make_client(lambda body: httpx.Response(402))
    assert ingest(cfg, store, client, embedder).status == "failed"
    assert seen(store) == {}


def test_transient_errors_leave_items_unconsumed_and_stop_after_three(
    cfg, store, make_client, embedder
):
    add(store, "a", items(6))
    client = make_client(lambda body: httpx.Response(503), max_retries=0)
    report = ingest(cfg, store, client, embedder)
    assert report.status == "degraded"
    assert "transient" in report.error
    assert len(client.fake.requests) == 3
    assert seen(store) == {}


def test_item_level_rejection_is_consumed_once_the_endpoint_is_shown_to_work(
        cfg, store, make_client, embedder):
    """An item the endpoint rejects is consumed as item_error, but only after a
    later call succeeds: until then the fault could be the endpoint's."""
    add(store, "a", items(3))

    def handler(body):
        if "solar microgrid battery 2" in body["messages"][-1]["content"]:
            return httpx.Response(400, json={"error": {"message": "too long"}})
        return chat_response(CONTRIB)

    report = ingest(cfg, store, make_client(handler), embedder)
    assert report.status == "degraded"
    assert seen(store) == {"item2": "item_error", "item1": "contributed",
                           "item0": "contributed"}


def test_item_errors_at_the_end_of_a_run_stay_unconsumed(cfg, store, make_client, embedder):
    add(store, "a", items(2))
    client = make_client(lambda body: httpx.Response(400, json={"error": {"message": "x"}}))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "degraded" and report.sources[0].item_errors == 2
    assert seen(store) == {}


def test_every_item_rejected_stops_the_run_and_consumes_nothing(cfg, store, make_client, embedder):
    """#43: HTTP 400 on every call consumed the whole batch with no alarm."""
    add(store, "a", items(10))
    client = make_client(lambda body: httpx.Response(400, json={"error": {"message": "bad"}}))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "failed" and "3 consecutive model errors" in report.error
    assert len(client.fake.requests) == 3
    assert seen(store) == {}
    assert store.query("SELECT 1 FROM messages WHERE kind = 'alarm'")


def test_cap_defers_the_rest_to_the_next_run(cfg, store, make_client, embedder):
    cfg = Config(**{**cfg.__dict__, "ingest": IngestConfig(
        max_items_per_source=10, prefilter_min_similarity=0.3, exploration_fraction=0.0,
        backfill_items=0)})
    add(store, "a", items(15))
    client = make_client(lambda body: chat_response(CONTRIB))
    first = ingest(cfg, store, client, embedder)
    assert first.sources[0].judged == 10
    assert first.sources[0].deferred == 5
    newest = {f"item{i}" for i in range(5, 15)}
    assert set(seen(store)) == newest
    second = ingest(cfg, store, client, embedder)
    assert second.sources[0].judged == 5
    assert len(seen(store)) == 15


def test_budget_exhausted_mid_run_stops_without_consuming(cfg, store, make_client, embedder):
    add(store, "a", items(5))
    client = make_client(lambda body: chat_response(CONTRIB, cost=4.0), budget=10.0)
    report = ingest(cfg, store, client, embedder)
    assert report.status == "degraded"
    assert "budget" in report.error
    # Screen and judge for the first item ($8), then the second item's screen
    # ($12): its judge call is refused before it is sent, and it stays unconsumed.
    assert len(client.fake.requests) == 3
    assert len(seen(store)) == 1


def test_paused_run_is_skipped_without_calls(cfg, store, make_client, embedder):
    add(store, "a", items(2))
    store.pause("away")
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "skipped"
    assert client.fake.requests == []


def test_prefilter_and_exploration(cfg, store, make_client, embedder):
    source_id = add(store, "a", items(4, text="solar microgrid battery")
                    + items(4, prefix="off", text="knitting patterns wool", start=10))
    topic = library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    library.link_topic_source(store, topic, source_id)
    client = make_client(lambda body: chat_response(CONTRIB))

    report = ingest(cfg, store, client, embedder)
    rep = report.sources[0]
    assert rep.prefiltered == 4
    assert rep.judged == 4
    outcomes = seen(store)
    assert all(outcomes[f"off{i}"] == "prefiltered" for i in range(10, 14))
    # The judge sees the topic as context.
    assert "solar microgrid battery storage" in client.fake.requests[0]["messages"][1]["content"]

    explore_cfg = Config(**{**cfg.__dict__, "ingest": IngestConfig(
        prefilter_min_similarity=0.3, exploration_fraction=1.0)})
    add(store, "a", items(2, prefix="off2", text="knitting patterns wool", start=20))
    report = ingest(explore_cfg, store, client, embedder, rng=random.Random(1))
    assert report.sources[0].explored == 2
    admitted = {r["admitted_by"] for r in store.query(
        "SELECT admitted_by FROM observations WHERE item_id LIKE 'off2%'")}
    assert admitted == {"exploration"}


def test_a_paused_topics_sources_wait_instead_of_turning_broad(cfg, store, make_client,
                                                               embedder):
    """Pausing a topic must not unlink its sources' prefilter: without an active topic their
    items would all be judged, as a broad source's are."""
    own = add(store, "own", items(3, prefix="own", text="knitting patterns wool"))
    shared = add(store, "shared", items(2, prefix="sh"))
    topic = library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    other = library.add_topic(store, embedder, "storage", "battery storage at home")
    for t, s in ((topic, own), (topic, shared), (other, shared)):
        library.link_topic_source(store, t, s)
    library.set_topic_status(store, topic, "paused")
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    assert [r.label for r in report.sources] == ["fake:shared"]
    assert not any(k.startswith("own") for k in seen(store))
    library.set_topic_status(store, other, "paused")
    report = ingest(cfg, store, client, embedder)
    assert report.status == "skipped" and report.error == "no approved sources"
    library.set_topic_status(store, topic, "active")
    report = ingest(cfg, store, client, embedder)
    own_report = next(r for r in report.sources if r.label == "fake:own")
    assert own_report.prefiltered == 3, "back to the topic's prefilter, not judged as broad"


def test_a_muted_source_is_not_fetched_until_its_mute_ends(cfg, store, make_client, embedder):
    from time_machine import travel

    from kranto import source_health

    from .conftest import FIXED_NOW

    loud = add(store, "loud", items(3, prefix="loud"))
    add(store, "quiet", items(2, prefix="quiet"))
    source_health.set_mute(store, loud, days=7)
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    muted = next(r for r in report.sources if r.label == "fake:loud")
    assert muted.muted and muted.fetched == 0
    assert not any(k.startswith("loud") for k in seen(store))
    assert report.status == "ok" and report.contributed == 2
    summary = json.loads(store.query_one("SELECT summary FROM runs")["summary"])
    assert any(s["muted"] for s in summary["sources"])
    # every source muted: the run is a skip that says why
    quiet = next(s.id for s in library.list_sources(store) if s.label == "fake:quiet")
    source_health.set_mute(store, quiet, days=7)
    assert ingest(cfg, store, client, embedder).error == "every approved source is muted"
    # a week and a day later both are read again
    with travel(FIXED_NOW + timedelta(days=8), tick=True):
        later = ingest(cfg, store, client, embedder)
    assert not any(r.muted for r in later.sources)
    assert {k for k in seen(store) if k.startswith("loud")} == {"loud0", "loud1", "loud2"}


def test_read_less_halves_the_cap_and_undo_restores_it(cfg, store, make_client, embedder):
    from kranto import source_health

    cfg = Config(**{**cfg.__dict__, "ingest": IngestConfig(
        max_items_per_source=10, prefilter_min_similarity=0.3, exploration_fraction=0.0,
        backfill_items=0)})
    src = add(store, "a", items(20))
    source_health.set_mute(store, src, read_less=True)
    client = make_client(lambda body: chat_response(CONTRIB))
    first = ingest(cfg, store, client, embedder)
    assert first.sources[0].read_less and first.sources[0].judged == 5
    assert first.sources[0].deferred == 15
    source_health.set_mute(store, src)          # back to normal
    second = ingest(cfg, store, client, embedder)
    assert not second.sources[0].read_less and second.sources[0].judged == 10


def test_one_source_paced_is_ok_all_failing_fails(cfg, store, make_client, embedder):
    add(store, "good", items(1))
    add(store, "bad", SourceError("HTTP 429"))
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    # Paced is not a failure (tests/test_pacing.py): fetched again at the end, still paced.
    assert report.status == "ok"
    assert report.sources[1].fetch_error == "HTTP 429"
    assert report.sources[1].fetch_state == "paced" and not report.sources[1].retried

    FakeSource.feeds["good"] = SourceError("down")
    report = ingest(cfg, store, client, embedder)
    assert report.status == "failed"


def test_concurrent_run_is_skipped(cfg, store, make_client, embedder):
    add(store, "a", items(1))
    client = make_client(lambda body: chat_response(CONTRIB))
    with run_lock(cfg.data_dir / "ingest.lock"):
        report = ingest(cfg, store, client, embedder)
    assert report.status == "skipped"
    assert client.fake.requests == []


def test_no_sources_is_skipped(cfg, store, make_client, embedder):
    report = ingest(cfg, store, make_client(lambda b: chat_response(CONTRIB)), embedder)
    assert report.status == "skipped"


def linked(item_id, link, title="solar microgrid battery", hours=0):
    """An HN-style item: its own discussion page, linking to an article."""
    return Item(id=item_id, title=title, body=f"{title} body",
                url=f"https://news.example/item?id={item_id}", link=link,
                published_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(hours=hours))


SKIP = json.dumps({"skip": True})


def test_same_article_is_judged_once_across_submissions_and_sources(
        cfg, store, make_client, embedder):
    """#34: a resubmitted link, or one article reached through two sources, was
    judged and stored again."""
    add(store, "hn", [
        linked("1", "https://www.notion.com/blog/crdts/", hours=2),
        linked("2", "https://notion.com/blog/crdts?utm_source=hn#top", hours=1),
        linked("3", "https://other.example/post", hours=0),
    ])
    add(store, "rss", [Item(id="entry", title="solar microgrid battery", body="b",
                            url="http://notion.com/blog/crdts")])
    client = make_client(lambda body: chat_response(CONTRIB))

    report = ingest(cfg, store, client, embedder)
    hn, rss = report.sources
    assert (hn.contributed, hn.duplicates) == (2, 1)
    assert (rss.judged, rss.duplicates) == (0, 1)
    assert len(judge_requests(client)) == 2
    assert store.query_one("SELECT COUNT(*) n FROM observations")["n"] == 2
    outcomes = seen(store)
    assert outcomes["2"] == outcomes["entry"] == "duplicate"
    urls = {r["item_id"]: r["canonical_url"] for r in store.query("SELECT * FROM items_seen")}
    assert urls["1"] == urls["2"] == urls["entry"] == "https://notion.com/blog/crdts"
    assert json.loads(store.query_one("SELECT summary FROM runs")["summary"]
                      )["sources"][0]["duplicates"] == 1


def test_skipped_content_is_not_rejudged_but_prefiltered_content_is(
        cfg, store, make_client, embedder):
    # Judged and skipped once: a resubmission is a duplicate, not a second call.
    add(store, "a", [linked("1", "https://ex.com/skipped")])
    ingest(cfg, store, make_client(lambda body: chat_response(SKIP)), embedder)
    add(store, "a", [linked("1", "https://ex.com/skipped"), linked("2", "https://ex.com/skipped")])
    client = make_client(lambda body: chat_response(CONTRIB))
    assert ingest(cfg, store, client, embedder).sources[0].duplicates == 1
    assert client.fake.requests == []

    # Prefiltered by one source's topic: another source may still judge it.
    off = add(store, "topical", [linked("9", "https://ex.com/knit", title="knitting wool")])
    topic = library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    library.link_topic_source(store, topic, off)
    add(store, "broad", [linked("10", "https://ex.com/knit", title="knitting wool")])
    ingest(cfg, store, client, embedder)
    outcomes = seen(store)
    assert outcomes["9"] == "prefiltered" and outcomes["10"] == "contributed"


# -- #39: every run is recorded, whatever it raises ------------------------------------


def test_repeated_id_within_one_fetch_is_judged_once(cfg, store, make_client, embedder):
    add(store, "a", items(2) + items(1))  # item0 appears twice
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder)
    assert report.status == "ok" and report.sources[0].judged == 2
    assert len(judge_requests(client)) == 2


def test_any_adapter_exception_fails_only_that_source(cfg, store, make_client, embedder):
    add(store, "broken", AttributeError("'list' object has no attribute 'get'"))
    add(store, "fine", items(2))
    report = ingest(cfg, store, make_client(lambda body: chat_response(CONTRIB)), embedder)
    # One failure is not yet persistent: the run is ok, the source's row says failing.
    assert report.status == "ok" and report.sources[0].fetch_state == "failing"
    assert "AttributeError" in report.sources[0].fetch_error
    assert report.sources[1].contributed == 2


def test_enrich_failure_of_any_kind_judges_the_item_as_it_is(
        cfg, store, make_client, embedder, monkeypatch):
    def boom(self, item):
        raise AttributeError("unexpected thread shape")

    monkeypatch.setattr(FakeSource, "enrich", boom)
    add(store, "a", items(1))
    report = ingest(cfg, store, make_client(lambda body: chat_response(CONTRIB)), embedder)
    assert report.status == "ok" and report.contributed == 1


def test_unexpected_exception_is_recorded_as_a_failed_run_with_an_alarm(
        cfg, store, make_client, embedder, monkeypatch):
    from kranto import tick

    def boom(*a, **kw):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(tick, "judge", boom)
    add(store, "a", items(2))
    report = ingest(cfg, store, make_client(lambda body: chat_response(CONTRIB)), embedder)
    assert report.status == "failed" and "RuntimeError" in report.error
    run = store.query_one("SELECT * FROM runs WHERE run_uuid = ?", (report.run_uuid,))
    assert run["status"] == "failed"
    assert store.query("SELECT 1 FROM messages WHERE kind = 'alarm'")
    assert seen(store) == {}  # nothing consumed


def test_unwritable_database_stops_before_any_paid_call(
        cfg, store, make_client, embedder, monkeypatch):
    import sqlite3

    add(store, "a", items(2))
    client = make_client(lambda body: chat_response(CONTRIB))

    def full(*a, **kw):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(store, "set_setting", full)
    with pytest.raises(sqlite3.OperationalError):
        ingest(cfg, store, client, embedder)
    assert client.fake.requests == []


# -- #69: hygiene before judging, and GitHub context ------------------------------------


def test_removed_and_stale_items_never_reach_the_judge(cfg, store, make_client, embedder):
    now = datetime(2026, 9, 27, tzinfo=UTC)
    add(store, "a", [
        Item(id="gone", title="t", body="[removed]", url="https://ex.com/gone",
             published_at=now - timedelta(days=1)),
        Item(id="old", title="solar microgrid battery", body="solar microgrid battery",
             url="https://ex.com/old", published_at=now - timedelta(days=120)),
        Item(id="fresh", title="solar microgrid battery", body="solar microgrid battery",
             url="https://ex.com/fresh", published_at=now - timedelta(days=2)),
        Item(id="undated", title="solar microgrid battery", body="solar microgrid battery",
             url="https://ex.com/undated"),
    ])
    client = make_client(lambda body: chat_response(CONTRIB))
    report = ingest(cfg, store, client, embedder, clock=lambda: now)
    rep = report.sources[0]
    assert (rep.removed, rep.stale, rep.contributed) == (1, 1, 2)
    assert len(judge_requests(client)) == 2 and len(screen_requests(client)) == 2
    assert seen(store)["gone"] == "removed" and seen(store)["old"] == "stale"


def test_max_age_zero_turns_the_staleness_check_off(cfg, store, make_client, embedder):
    now = datetime(2026, 9, 27, tzinfo=UTC)
    old_ok = Config(**{**cfg.__dict__, "ingest": IngestConfig(
        prefilter_min_similarity=0.3, exploration_fraction=0.0, max_age_days=0)})
    add(store, "a", [Item(id="old", title="solar microgrid battery", body="solar microgrid",
                          url="https://ex.com/old", published_at=now - timedelta(days=400))])
    report = ingest(old_ok, store, make_client(lambda body: chat_response(CONTRIB)), embedder,
                    clock=lambda: now)
    assert report.sources[0].contributed == 1


def test_items_about_a_github_repository_carry_its_numbers(cfg, store, make_client, embedder):
    from kranto.tick import run_ingest

    def github(request):
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json={"stargazers_count": 1234, "forks_count": 56,
                                         "pushed_at": "2026-09-20T10:00:00Z", "archived": False})

    add(store, "a", [
        Item(id="1", title="Show: a CRDT engine", body="solar microgrid battery",
             url="https://news.example/1", link="https://github.com/acme/engine"),
        Item(id="2", title="Show: same repo again", body="solar microgrid battery",
             url="https://news.example/2", link="https://github.com/acme/engine/releases"),
    ])
    client = make_client(lambda body: chat_response(CONTRIB))
    http = sources.HTTP(transport=httpx.MockTransport(github), resolver=lambda h: ["93.184.216.34"])
    run_ingest(cfg, store, client, embedder, http)
    prompts = [r["messages"][-1]["content"] for r in client.fake.requests]
    assert all('"stars": 1234' in p and '"last_push": "2026-09-20"' in p for p in prompts)


def test_a_provider_pause_halts_the_run_unconsumed_and_skips_until_it_ends(
        cfg, store, make_client, embedder):
    from kranto.providers.base import ProviderError

    from .conftest import FIXED_NOW
    add(store, "a", items(3))
    calls = []

    def spend_limit(body):
        calls.append(body)
        return httpx.Response(200)

    client = make_client(spend_limit)
    until = FIXED_NOW + timedelta(hours=4)
    provider = client._providers["openai_compat"]

    def send(body):
        calls.append(body)
        raise ProviderError("usage limit", kind="paused", status=429, resume_at=until)
    provider.send = send
    report = ingest(cfg, store, client, embedder)
    assert "watching paused until" in report.error
    assert len(calls) == 1
    assert seen(store) == {}
    # The next run is skipped before any request while the pause lasts.
    report = ingest(cfg, store, client, embedder)
    assert report.status == "skipped" and "watching paused until" in report.error
    assert len(calls) == 1


def test_a_run_says_how_far_it_is_and_forgets_it_after(cfg, store, make_client, embedder):
    """S2 (MEM): a first read ran 39 minutes with nothing said. Each source as it starts,
    once its new items are known, and before each item; ``current_progress`` while running."""
    from kranto import tick

    add(store, "a", items(3, prefix="a"))
    add(store, "b", items(2, prefix="b", text="tidal kelp farming cooperative"))
    client = make_client(lambda body: chat_response(SCREEN_PASS if is_screen(body)
                                                    else CONTRIB))
    seen_progress, live = [], []

    def note(p):
        seen_progress.append((p.source_index, p.source, p.items, p.item, p.done_items,
                              p.kept))
        live.append(tick.current_progress())

    report = ingest(cfg, store, client, embedder, on_progress=note)
    assert report.contributed == 5
    assert seen_progress == [
        (1, "fake:a", None, 0, 0, 0), (1, "fake:a", 3, 0, 0, 0),
        (1, "fake:a", 3, 0, 0, 0), (1, "fake:a", 3, 1, 1, 1), (1, "fake:a", 3, 2, 2, 2),
        (2, "fake:b", None, 0, 2, 3), (2, "fake:b", 2, 0, 2, 3),
        (2, "fake:b", 2, 0, 3, 3), (2, "fake:b", 2, 1, 4, 4)]
    assert live[-1]["sources"] == 2 and live[-1]["run_uuid"] == report.run_uuid
    assert tick.current_progress() is None


def test_afk_run_prints_its_progress_to_stderr():
    import io

    from kranto.cli import _run_progress
    from kranto.tick import Progress

    out, now = io.StringIO(), [0.0]
    show = _run_progress(out, clock=lambda: now[0])
    p = Progress("r", "2026-10-20T00:00:00Z", 8, source_index=3, source="www.inkandswitch.com")
    show(p)
    p.items = 40
    show(p)
    show(p)                                         # the first item: already said
    for i in range(1, 12):
        now[0] += 5
        p.item = p.done_items = i
        show(p)
    assert out.getvalue().splitlines() == [
        "[3/8] www.inkandswitch.com: reading; 0 read and 0 kept so far, 0m00s",
        "[3/8] www.inkandswitch.com: 40 new items to read; 0 read and 0 kept so far, 0m00s",
        "[3/8] www.inkandswitch.com: 6 of 40 items; 6 read and 0 kept so far, 0m30s",
        "[3/8] www.inkandswitch.com: 10 of 40 items; 10 read and 0 kept so far, 0m50s"]
