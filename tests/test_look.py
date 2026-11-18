"""Look before judging: a lenient screen, what is one step away gathered with no
model call, then a judge that reads both and may keep gathered sources as linked
observations of their own."""

import json
import sqlite3
from datetime import timedelta

import httpx
import pytest

from kranto import library, retention, sources, stories
from kranto.config import (
    MAX_TOKENS,
    BudgetConfig,
    Config,
    ConfigError,
    IngestConfig,
    LookConfig,
    MapConfig,
    RetentionConfig,
    init_workspace,
    load,
)
from kranto.intern import interpret_children, interpret_screen
from kranto.sources import Item, SourceError
from kranto.sources import gather as gather_mod
from kranto.sources.fulltext import blank_no_content, no_content
from kranto.tick import run_ingest

from .conftest import (
    FIXED_NOW,
    SCREEN_DROP,
    SCREEN_PASS,
    chat_response,
    is_screen,
    judge_requests,
    llm_config,
    screen_requests,
)
from .webfake import ARTICLE, Web, http_for

GITHUB_CHROME = ("You signed in with another tab or window. Reload to refresh your session."
                 "You signed out in another tab or window. Reload to refresh your session."
                 "You switched accounts on another tab or window. Reload to refresh your "
                 "session.Dismiss alert")
CONSENT = ("Before you continue to Google We use cookies and data to deliver and maintain "
           "Google services, track outages and protect against spam, fraud and abuse. ") * 4
BODY = "A measured account of battery fade in a community microgrid. " * 10


def fields(summary="a concrete finding", q=0.9, **extra):
    return {"kind": "mild_signal", "summary": summary, "why_it_matters": "because",
            "content_quality": q, "durability": 1.0, "opportunity": 1.0, **extra}


class Feed:
    """A source of fixed items, registered under a real kind so gathering applies."""

    items: dict[str, list[Item]] = {}

    def __init__(self, http, **params):
        self.key = params.get("query") or params.get("url")

    @property
    def label(self):
        return "feed"

    def fetch(self):
        return list(self.items[self.key])

    def enrich(self, item):
        return item


@pytest.fixture(autouse=True)
def feeds(monkeypatch):
    for kind in ("hackernews", "rss"):
        monkeypatch.setitem(sources.KINDS, kind, Feed)
    Feed.items = {}


def hn(store, items, query="battery"):
    Feed.items[query] = items
    return library.add_source(store, "hackernews", {"query": query}, label=f"HN {query}")


def hn_item(item_id="1001", title="Battery fade measured over 18 months", body=BODY,
            link=ARTICLE):
    return Item(id=item_id, title=title, body=body,
                url=f"https://news.ycombinator.com/item?id={item_id}", link=link,
                published_at=FIXED_NOW - timedelta(hours=1))


def config(tmp_path, **look):
    return Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                  ingest=IngestConfig(exploration_fraction=0.0, fetch_full_text=False,
                                      signal_threshold=0.20),   # the gate these tests probe
                  map=MapConfig(), look=LookConfig(**look))


def replying(judge_reply, screen_reply=SCREEN_PASS, cost=0.002):
    def handler(body):
        return chat_response(screen_reply if is_screen(body) else judge_reply, cost=cost)
    return handler


def ingest(cfg, store, client, embedder, web=None):
    return run_ingest(cfg, store, client, embedder, http_for(web or Web()))


def seen(store):
    return {r["item_id"]: r for r in store.query("SELECT * FROM items_seen")}


# -- the screen ------------------------------------------------------------------------


def test_a_screen_drop_is_consumed_with_its_call_and_never_reaches_the_judge(
        tmp_path, store, embedder, make_client):
    hn(store, [hn_item()])
    client = make_client(replying(json.dumps(fields()), screen_reply=SCREEN_DROP))
    web = Web()
    report = ingest(config(tmp_path), store, client, embedder, web)
    rep = report.sources[0]
    assert report.status == "ok"
    assert (rep.screened, rep.screened_out, rep.judged, rep.looked) == (1, 1, 0, 0)
    assert judge_requests(client) == [] and len(screen_requests(client)) == 1
    assert web.hits == [], "nothing is gathered for a dropped item"
    row = seen(store)["1001"]
    assert row["outcome"] == "screened_out"
    assert row["llm_call_id"] == row["screen_call_id"]
    call = store.query_one("SELECT * FROM llm_calls WHERE id = ?", (row["llm_call_id"],))
    assert call["purpose"] == "screen" and call["prompt_version"].startswith("screen-")
    assert "spam: an advert" in call["response"], "the reason is kept with the call"
    # The screen read it: the same URL from elsewhere is a duplicate, not a second call.
    assert library.already_judged(store, "https://article.test/post")


def test_a_copy_of_a_screened_out_item_is_a_near_duplicate(tmp_path, store, embedder,
                                                           make_client):
    hn(store, [hn_item("1", link="https://a.test/x")], query="a")
    hn(store, [hn_item("2", link="https://b.test/y")], query="b")
    client = make_client(replying(json.dumps(fields()), screen_reply=SCREEN_DROP))
    report = ingest(config(tmp_path), store, client, embedder)
    assert [s.screened_out for s in report.sources] == [1, 0]
    assert report.sources[1].near_duplicates == 1
    assert len(client.fake.requests) == 1


@pytest.mark.parametrize("reply, passed", [
    ('{"pass": true, "reason": "on topic"}', True),
    ('{"pass": false, "reason": "off-topic"}', False),
    ('```json\n{"pass": "false", "reason": "spam"}\n```', False),
    ("I think this is fine", True),
    ('{"skip": true}', True),
])
def test_only_an_explicit_no_drops_an_item(reply, passed):
    assert interpret_screen(reply)[0] is passed


def test_the_screen_sees_a_short_version_of_the_item(tmp_path, store, embedder, make_client):
    item = Item(id="1001", title="Battery fade", body="x " * 5000,
                url="https://news.ycombinator.com/item?id=1001", link=ARTICLE,
                comments=tuple(f"comment {i} " + "y" * 900 for i in range(5)),
                published_at=FIXED_NOW)
    hn(store, [item])
    client = make_client(replying(json.dumps({"skip": True})))
    ingest(config(tmp_path), store, client, embedder)
    screen_payload = json.loads(screen_requests(client)[0]["messages"][1]["content"])
    judge_payload = json.loads(judge_requests(client)[0]["messages"][1]["content"])
    assert len(screen_payload["item"]["body"]) == 1500
    assert len(screen_payload["item"]["top_comments"]) == 3
    assert all(len(c) <= 300 for c in screen_payload["item"]["top_comments"])
    assert len(judge_payload["item"]["body"]) == 6000
    # a short answer, but with room for Haiku 5.5's reasoning, which counts against it
    assert screen_requests(client)[0]["max_tokens"] == MAX_TOKENS["screen"]
    assert MAX_TOKENS["screen"] < judge_requests(client)[0]["max_tokens"]


def test_look_off_is_one_judge_call_per_item(tmp_path, store, embedder, make_client):
    hn(store, [hn_item()])
    client = make_client(replying(json.dumps(fields())))
    web = Web()
    report = ingest(config(tmp_path, enabled=False), store, client, embedder, web)
    assert report.sources[0].contributed == 1 and report.sources[0].screened == 0
    assert screen_requests(client) == [] and len(judge_requests(client)) == 1
    assert web.hits == []
    assert "gathered" not in judge_requests(client)[0]["messages"][1]["content"]


# -- gathering and the judge -----------------------------------------------------------


def with_children(*children, parent=None):
    return json.dumps({**(parent or fields("Battery fade measured")), "children": list(children)})


def test_the_judge_reads_what_was_gathered_and_keeps_children_linked(
        tmp_path, store, embedder, make_client):
    src = hn(store, [hn_item()])
    reply = with_children(
        {"ref": 1, **fields("The thread adds the operator's own log")},   # discussion
        {"ref": 2, **fields("A thin page", q=0.05)},                      # gated: not kept
        {"ref": 4, **fields("The analyser's repository")},                # repository
        {"ref": 9, **fields("no such source")},                           # dropped
    )
    client = make_client(replying(reply))
    web = Web()
    report = ingest(config(tmp_path), store, client, embedder, web)
    rep = report.sources[0]
    assert report.status == "ok"
    assert (rep.contributed, rep.looked, rep.gathered, rep.children, rep.children_gated) == \
        (1, 1, 4, 2, 1)

    # One judge call that saw the item and every gathered source, numbered.
    payload = json.loads(judge_requests(client)[0]["messages"][1]["content"])
    gathered = payload["gathered"]
    assert [g["ref"] for g in gathered] == [1, 2, 3, 4]
    assert [g["relation"] for g in gathered] == ["discussion", "link", "link", "repository"]
    assert all(len(g["text"]) <= 2000 for g in gathered)
    assert "someone@example.com" not in json.dumps(payload), "gathered text is scrubbed"
    assert judge_requests(client)[0]["max_tokens"] > 800
    assert any("hn.algolia.com/api/v1/items/1001" in h for h in web.hits)

    parent = store.query_one("SELECT * FROM observations WHERE item_id = '1001'")
    kids = store.query("SELECT o.*, l.relation, l.deep_dive_id FROM observation_links l "
                       "JOIN observations o ON o.id = l.child_id WHERE l.parent_id = ? "
                       "ORDER BY o.id", (parent["id"],))
    assert [k["relation"] for k in kids] == ["discussion", "repository"]
    assert [k["summary"] for k in kids] == ["The thread adds the operator's own log",
                                            "The analyser's repository"]
    for k in kids:
        assert k["admitted_by"] == "gathered" and k["deep_dive_id"] is None
        assert k["llm_call_id"] == parent["llm_call_id"]
        assert k["source_id"] == src and k["source_excerpt"]
        assert k["item_id"].startswith("look:1001:")
    assert kids[1]["source_url"] == "https://github.com/acme/widget"
    rows = seen(store)
    assert rows["1001"]["screen_call_id"] and rows["1001"]["outcome"] == "contributed"
    assert {rows[k["item_id"]]["outcome"] for k in kids} == {"contributed"}
    # Not kept and not named: no row, so either can still arrive as an item of its own.
    assert len(rows) == 3
    # One story: the children count with their parent.
    keys = stories.story_keys(store, store.query("SELECT id, source_id, item_id FROM "
                                                 "observations"))
    assert len(set(keys.values())) == 1


def test_children_only_come_with_a_kept_item(tmp_path, store, embedder, make_client):
    hn(store, [hn_item()])
    reply = json.dumps({**fields("thin", q=0.01), "children": [{"ref": 1, **fields()}]})
    client = make_client(replying(reply))
    report = ingest(config(tmp_path), store, client, embedder)
    assert report.sources[0].gated == 1 and report.sources[0].children == 0
    assert store.query("SELECT * FROM observation_links") == []
    assert store.query_one("SELECT COUNT(*) AS n FROM observations")["n"] == 0


def test_children_are_parsed_strictly():
    text = json.dumps({**fields(), "children": [
        {"ref": 1, **fields("one")}, {"ref": 1, **fields("again")}, {"ref": True, **fields()},
        {"ref": 2, "summary": "no ratings"}, "not an object", {"ref": 3, **fields("three")},
        {"ref": 0, **fields()}]})
    kids = interpret_children(text, 0.2, 3)
    assert [(k.ref, k.fields["summary"]) for k in kids] == [(1, "one"), (3, "three")]
    assert interpret_children(json.dumps(fields()), 0.2, 3) == []


def test_pages_already_judged_are_not_read_again(tmp_path, store, embedder, make_client):
    hn(store, [hn_item()])
    library.mark_seen(store, 1, "earlier", "skipped", run_uuid=None,
                      canonical_url="https://paper.test/study")
    client = make_client(replying(json.dumps({"skip": True})))
    web = Web()
    ingest(config(tmp_path), store, client, embedder, web)
    assert not any(h.startswith("https://paper.test/") for h in web.hits)


def test_links_on_a_consent_wall_are_not_followed(tmp_path, store, embedder, make_client):
    from .webfake import page

    hn(store, [hn_item()])
    wall = httpx.Response(200, html=page("Before you continue to Google",
                                         ["https://policies.test/cookies"], body=CONSENT))
    web = Web(**{ARTICLE: wall})
    ingest(config(tmp_path), store, make_client(replying(json.dumps({"skip": True}))),
           embedder, web)
    assert not any("policies.test" in h for h in web.hits)
    assert any(h.startswith("https://paper.test/") for h in web.hits), \
        "the comments' links are still read"


def test_gathering_is_capped_per_run_and_never_loses_an_item(tmp_path, store, embedder,
                                                             make_client):
    hn(store, [hn_item("1", link="https://a.test/1"), hn_item("2", link="https://b.test/2")])
    client = make_client(replying(json.dumps(fields())))
    report = ingest(config(tmp_path, max_per_run=1), store, client, embedder)
    rep = report.sources[0]
    assert (rep.looked, rep.look_capped, rep.contributed) == (1, 1, 2)
    assert json.loads(store.query_one("SELECT summary FROM runs")["summary"]
                      )["sources"][0]["look_capped"] == 1


def test_an_unreadable_thread_leaves_the_item_to_be_judged(tmp_path, store, embedder,
                                                           make_client):
    hn(store, [hn_item()])
    web = Web(**{"https://hn.algolia.com/": httpx.Response(503)})
    client = make_client(replying(json.dumps(fields())))
    report = ingest(config(tmp_path), store, client, embedder, web)
    assert report.status == "ok" and report.sources[0].contributed == 1
    assert "gathered" not in judge_requests(client)[0]["messages"][1]["content"]


def test_a_time_box_stops_requests_once_its_time_is_spent():
    now = [0.0]
    web = Web()
    box = gather_mod.TimeBox(http_for(web), seconds=10, request_seconds=3,
                             clock=lambda: now[0])
    box.get(ARTICLE)
    box.get(ARTICLE)
    assert box.requests == 1, "the same URL is fetched once"
    now[0] = 11
    with pytest.raises(SourceError, match="time for gathering is spent"):
        box.get("https://paper.test/study")
    assert len(web.hits) == 1


# -- no content --------------------------------------------------------------------------


@pytest.mark.parametrize("text, reason", [
    (GITHUB_CHROME, "page chrome"),
    (CONSENT, "cookie-consent"),
    ("Verifying you are human. This may take a few seconds.", "bot-check"),
    (BODY, None),
    ("Access denied errors in S3 are often a bucket policy problem. " * 10, None),
])
def test_no_content_is_recognised(text, reason):
    found = no_content(text)
    assert (found is None) if reason is None else (reason in found)


def test_a_chrome_body_is_blanked_and_the_judge_is_told(tmp_path, store, embedder,
                                                        make_client):
    Feed.items["https://github.com/yjs/yjs/releases.atom"] = [Item(
        id="v14", title="v14.0.0-rc.26", body=GITHUB_CHROME,
        url="https://github.com/yjs/yjs/releases/tag/v14.0.0-rc.26", published_at=FIXED_NOW)]
    library.add_source(store, "rss", {"url": "https://github.com/yjs/yjs/releases.atom"},
                       label="Release notes from yjs")
    client = make_client(replying(json.dumps({"skip": True})))
    report = ingest(config(tmp_path), store, client, embedder,
                    Web(**{"https://github.com/": httpx.Response(404)}))
    assert report.sources[0].no_content == 1
    for request in client.fake.requests:
        item = json.loads(request["messages"][1]["content"])["item"]
        assert item["body"] == "" and "page chrome" in item["capture_note"]
    assert not any("signed in" in r["messages"][1]["content"] for r in client.fake.requests)
    assert blank_no_content(Item(id="x", title="t", body="")).capture_note is None


# -- ingest's candidates, retention, config ------------------------------------------


def test_ingest_records_no_strike_candidate_and_reads_no_watch(tmp_path, store, embedder,
                                                               make_client):
    """Watches are retired: an ingest that keeps an item and its children writes no
    candidate, and a watch row left from before is neither read nor matched."""
    hn(store, [hn_item()])
    query = "community battery round-trip efficiency log analyser"
    store.insert("watches", {"query": query, "embedding": b"\0" * 4, "embedding_model": "x",
                             "min_similarity": 0.0, "min_signal": 0.0,
                             "created_at": "2026-01-01T00:00:00Z"})
    reply = with_children({"ref": 4, **fields(query)},
                          parent=fields("knitting patterns and wool prices"))
    report = ingest(config(tmp_path), store, make_client(replying(reply)), embedder)
    assert store.query_one("SELECT COUNT(*) AS n FROM observation_links")["n"] == 1
    assert store.query_one("SELECT COUNT(*) AS n FROM strike_candidates")["n"] == 0
    assert "watch_candidates" not in json.loads(report.to_json())
    assert store.get_setting("watch_matches_written_through") is None


def test_screen_calls_expire_with_their_items(tmp_path, store, embedder, make_client):
    hn(store, [hn_item("1", link="https://a.test/1")], query="a")
    hn(store, [hn_item("2", title="Something else entirely about tea",
                       link="https://b.test/2")], query="b")
    state = {"n": 0}

    def handler(body):
        if is_screen(body):
            state["n"] += 1
            return chat_response(SCREEN_PASS if state["n"] == 1 else SCREEN_DROP)
        return chat_response(json.dumps(fields()))

    ingest(config(tmp_path), store, make_client(handler), embedder)
    assert store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"] == 3

    # Before the items' age nothing goes, though nothing but items_seen names a screen.
    soon = FIXED_NOW + timedelta(days=100)
    retention.compact(store, RetentionConfig(default_days=200), None, clock=lambda: soon)
    assert store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"] == 3

    later = FIXED_NOW + timedelta(days=30)
    report = retention.compact(store, RetentionConfig(default_days=14), None,
                               clock=lambda: later)
    assert report.status == "ok", report.error
    assert store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"] == 0
    detail = json.loads(store.query_one(
        "SELECT detail FROM purges WHERE table_name = 'llm_calls' "
        "AND reason LIKE '%judged but not kept%'")["detail"])
    assert detail["outcomes"] == {"screen": 1, "screened_out": 1}


def test_migration_16_adds_the_screen_call_column(store):
    columns = {r["name"] for r in store.query("PRAGMA table_info(items_seen)")}
    assert "screen_call_id" in columns
    src = library.add_source(store, "rss", {"url": "https://feed.test/rss"}, label="feed")
    library.mark_seen(store, src, "a", "screened_out", run_uuid=None)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.query("UPDATE items_seen SET screen_call_id = 1")


def test_look_config_defaults_and_validation(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root)
    cfg = load(root)
    assert cfg.look == LookConfig()
    assert cfg.look.enabled and cfg.look.max_links == 2 and cfg.look.max_per_run == 40
    assert cfg.deep_dive.min_signal == 0.5, "still accepted, so old configurations load"
    text = (root / "kranto.yaml").read_text()
    for old, new, match in (("  max_links: 2", "  max_links: -1", "whole number"),
                            ("  item_seconds: 30", "  item_seconds: 0", "seconds"),
                            ("  enabled: true", "  enabled: yes please", "true or false"),
                            ("look:\n", "look:\n  colour: red\n", "unknown")):
        assert text.count(old) == 1
        (root / "kranto.yaml").write_text(text.replace(old, new))
        with pytest.raises(ConfigError, match=match):
            load(root)
