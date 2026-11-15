"""Issue #19: wildcards, the broad lane, feed discovery, full text, backfill, progress."""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from kranto import library, sources
from kranto.config import (
    BudgetConfig,
    Config,
    ConfigError,
    IngestConfig,
    LookConfig,
    MapConfig,
    load,
)
from kranto.map.snapshot import take_snapshot
from kranto.packs import load_pack
from kranto.progress import Progress, library_progress
from kranto.runtime import open_runtime
from kranto.scout import Proposal, parse_proposals, scout_topic, validate
from kranto.sources import HTTP, Item, SourceError
from kranto.sources.discover import advertised_feeds, discover_feed, fallback_candidates
from kranto.sources.fulltext import (
    MAX_FULL_TEXT_CHARS,
    fetch_full_text,
    full_text_target,
    with_full_text,
)
from kranto.sources.hackernews import HackerNewsSource
from kranto.sources.rss import parse_feed
from kranto.tick import run_ingest
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client
from .test_map import add_observations

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
PUBLIC = ["93.184.216.34"]

CONTRIB = json.dumps({
    "kind": "beat", "summary": "a concrete thing", "why_it_matters": "because",
    "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9,
})


def rss(*entries, title="Feed"):
    """entries: (guid, title, body, link)."""
    items = "".join(
        f"<item><title>{t}</title><link>{link}</link><guid>{g}</guid>"
        f"<description>{body}</description><pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate>"
        "</item>"
        for g, t, body, link in entries
    )
    return f"<rss><channel><title>{title}</title>{items}</channel></rss>".encode()


FEED = rss(("1", "solar microgrid battery", "solar microgrid battery details",
            "https://blog.example/post/1"))

ARTICLE_PARAGRAPH = (
    "The cooperative installed forty kilowatts of panels and a lithium iron phosphate "
    "battery bank, then billed members per kilowatt hour through a prepaid meter. "
    "Collections reached ninety-four percent in the first year, and the diesel generator "
    "ran for eleven hours in total across the dry season. "
)
ARTICLE = (
    "<html><head><title>How the co-op did it</title></head><body>"
    "<nav><a href='/'>Home</a> <a href='/about'>About</a></nav>"
    "<article><h1>How the co-op did it</h1>"
    + "".join(f"<p>{ARTICLE_PARAGRAPH}Paragraph {i}.</p>" for i in range(30))
    + "</article><footer>Copyright footer text</footer></body></html>"
)


def http_for(handler, resolver=None) -> HTTP:
    return HTTP(transport=httpx.MockTransport(handler), resolver=resolver or (lambda h: PUBLIC))


# -- wildcards -------------------------------------------------------------------------


def test_wildcards_are_parsed_and_capped_at_three():
    text = json.dumps({"sources": [
        {"kind": "rss", "value": "https://ex.com/a", "why": "core", "role": "core"},
        {"kind": "rss", "value": "https://ex.com/b", "why": "no role"},
        {"kind": "rss", "value": "https://ex.com/c", "role": "nonsense"},
        *[{"kind": "hackernews", "value": f"wild {i}", "role": "Wildcard"} for i in range(5)],
        {"kind": "site", "value": "https://blog.example/", "role": "wildcard"},
    ]})
    proposals = parse_proposals(text)
    roles = [(p.value, p.role) for p in proposals]
    assert roles[:3] == [("https://ex.com/a", "core"), ("https://ex.com/b", "core"),
                         ("https://ex.com/c", "core")]
    wild = [p for p in proposals if p.role == "wildcard"]
    assert [p.value for p in wild] == ["wild 0", "wild 1", "wild 2"]


def test_site_proposals_are_accepted():
    [p] = parse_proposals(json.dumps({"sources": [
        {"kind": "site", "value": "https://blog.example/", "why": "w"}]}))
    assert p.kind == "site" and p.role == "core"


def scout_site(request):
    path = request.url.path
    if path in ("/core", "/wild"):
        return httpx.Response(200, content=rss(
            ("1", "solar microgrid battery storage", "solar microgrid battery", "https://x/1"),
            ("2", "solar microgrid battery prices", "solar battery", "https://x/2")))
    return httpx.Response(404)


def test_wildcards_are_stored_unlinked_and_never_auto_approved(store, embedder, make_client):
    proposals = {"sources": [
        {"kind": "rss", "value": "https://ex.com/core", "why": "on topic", "role": "core"},
        {"kind": "rss", "value": "https://ex.com/wild", "why": "same pattern",
         "role": "wildcard"},
    ]}
    client = make_client(lambda body: chat_response(json.dumps(proposals)))
    topic_id = library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    [topic] = library.active_topics(store)

    # A threshold every valid proposal clears: only the core one may be approved.
    results = scout_topic(store, client, embedder, http_for(scout_site), topic,
                          auto_approve_min_similarity=-1.0, now=NOW)
    by_value = {r.proposal.value: r for r in results}
    assert by_value["https://ex.com/core"].status == "approved"
    wild = by_value["https://ex.com/wild"]
    assert wild.status == "proposed" and wild.proposal.role == "wildcard"

    rows = {s.id: s for s in library.list_sources(store)}
    assert rows[wild.source_id].validation.role == "wildcard"
    assert rows[wild.source_id].validation.topic_id == topic_id
    assert rows[by_value["https://ex.com/core"].source_id].validation.role == "core"
    # Not linked to the topic: once approved, its items skip the topic prefilter.
    assert library.topics_for_source(store, wild.source_id) == []
    assert [t.id for t in library.topics_for_source(
        store, by_value["https://ex.com/core"].source_id)] == [topic_id]


# -- feed discovery ------------------------------------------------------------------


HOMEPAGE = """<html><head>
<link rel="stylesheet" href="/style.css">
<link rel="alternate" type="application/rss+xml; charset=utf-8" href="/blog/feed.rss" title="x">
</head><body>hello</body></html>"""


def discovery_site(request):
    host, path = request.url.host, request.url.path
    if host == "linked.example":
        if path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=HOMEPAGE)
        if path == "/blog/feed.rss":
            return httpx.Response(200, content=FEED)
    if host == "fallback.example":
        if path == "/":
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  content="<html><body>no links</body></html>")
        if path == "/index.xml":
            return httpx.Response(200, content=FEED)
        if path == "/feed":
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  content="<html>not a feed</html>")
    if host == "isfeed.example" and path == "/":
        return httpx.Response(200, content=FEED)
    if host == "nofeed.example" and path == "/":
        return httpx.Response(200, headers={"content-type": "text/html"}, content="<html/>")
    return httpx.Response(404)


def test_discovery_finds_a_linked_feed():
    http = http_for(discovery_site)
    assert discover_feed(http, "https://linked.example/") == "https://linked.example/blog/feed.rss"


def test_discovery_falls_back_to_common_paths():
    http = http_for(discovery_site)
    assert discover_feed(http, "https://fallback.example/") == "https://fallback.example/index.xml"
    assert discover_feed(http, "https://isfeed.example/") == "https://isfeed.example/"
    with pytest.raises(SourceError, match="no feed found"):
        discover_feed(http, "https://nofeed.example/")


def test_discovery_candidates_and_links_are_http_only():
    assert fallback_candidates("https://ex.com/blog")[:2] == [
        "https://ex.com/blog/feed", "https://ex.com/blog/rss.xml"]
    assert fallback_candidates("https://ex.com/")[-3:] == [
        "https://ex.com/feed.xml", "https://ex.com/blog.rss", "https://ex.com/rss"]
    page = ('<link rel="alternate" type="application/atom+xml" href="javascript:alert(1)">'
            '<link rel="alternate" type="application/atom+xml" href="atom.xml">')
    assert advertised_feeds(page, "https://ex.com/a/") == ["https://ex.com/a/atom.xml"]


def test_discovery_uses_the_safe_client():
    http = http_for(discovery_site, resolver=lambda h: ["10.0.0.5"])
    with pytest.raises(SourceError, match="non-public"):
        discover_feed(http, "https://linked.example/")


def test_site_proposal_becomes_an_rss_source(store, embedder, make_client):
    proposals = {"sources": [{"kind": "site", "value": "https://linked.example/", "why": "w"},
                             {"kind": "site", "value": "https://nofeed.example/", "why": "w"}]}
    client = make_client(lambda body: chat_response(json.dumps(proposals)))
    library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    [topic] = library.active_topics(store)
    results = scout_topic(store, client, embedder, http_for(discovery_site), topic, now=NOW)
    ok, bad = results
    assert ok.status == "proposed" and ok.validation.discovered_from == "https://linked.example/"
    assert bad.status == "invalid" and bad.source_id is None
    [src] = library.list_sources(store)
    assert src.kind == "rss" and src.params == {"url": "https://linked.example/blog/feed.rss"}
    assert src.validation.discovered_from == "https://linked.example/"
    v, _, kind, params = validate(Proposal("site", "https://fallback.example/", ""),
                            http_for(discovery_site), embedder, topic, now=NOW)
    assert v.status == "valid" and params == {"url": "https://fallback.example/index.xml"}
    assert kind == "rss"


# -- full text -----------------------------------------------------------------------


def article_site(request):
    if request.url.path == "/feed":
        return httpx.Response(200, content=rss(
            ("short", "solar microgrid battery co-op", "solar microgrid teaser",
             "https://blog.example/post/short"),
            ("broken", "solar microgrid battery outage", "solar microgrid teaser two",
             "https://blog.example/post/broken"),
            ("long", "solar microgrid battery long", "solar microgrid battery " * 30,
             "https://blog.example/post/long"),
        ))
    if request.url.path == "/post/short":
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              content=ARTICLE)
    if request.url.path == "/post/long":
        raise AssertionError("an item with a long body must not be fetched")
    return httpx.Response(404)


def test_extraction_keeps_the_article_and_truncates():
    text = fetch_full_text(http_for(article_site), "https://blog.example/post/short")
    assert text is not None and "prepaid meter" in text
    assert "Copyright footer" not in text
    assert len(text) == MAX_FULL_TEXT_CHARS


def test_full_text_targets():
    short = Item(id="1", title="t", body="", url="https://news.ycombinator.com/item?id=1",
                 link="https://blog.example/post/short")
    assert full_text_target("hackernews", short) == "https://blog.example/post/short"
    ask = Item(id="2", title="Ask HN", body="", url="https://news.ycombinator.com/item?id=2")
    assert full_text_target("hackernews", ask) is None
    assert full_text_target("rss", Item(id="3", title="t", body="x", url="https://a.example/"))
    assert full_text_target("rss", Item(id="4", title="t", body="x" * 300,
                                        url="https://a.example/")) is None
    assert full_text_target("reddit", Item(id="5", title="t", body="", url="https://r/")) is None
    assert full_text_target("rss", Item(id="6", title="t", body="", url="javascript:x")) is None


def test_full_text_failures_keep_the_original_item():
    http = http_for(article_site)
    item = Item(id="1", title="t", body="teaser", url="https://blog.example/post/broken")
    assert with_full_text(http, "rss", item) == (item, False)
    private = http_for(article_site, resolver=lambda h: ["127.0.0.1"])
    item = Item(id="1", title="t", body="teaser", url="https://blog.example/post/short")
    assert with_full_text(private, "rss", item) == (item, False)

    def pdf(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    assert fetch_full_text(http_for(pdf), "https://blog.example/x.pdf") is None


def ingest_cfg(tmp_path, **ingest):
    base = dict(max_items_per_source=10, prefilter_min_similarity=0.3, exploration_fraction=0.0)
    # Full text and backfill alone: no screen, no gathering (those are test_look.py's).
    return Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                  ingest=IngestConfig(**{**base, **ingest}), map=MapConfig(),
                  look=LookConfig(enabled=False))


def judged_bodies(client) -> dict[str, str]:
    out = {}
    for request in client.fake.requests:
        payload = json.loads(request["messages"][1]["content"])
        out[payload["item"]["title"]] = payload["item"]["body"]
    return out


def test_ingest_uses_full_text_for_short_items_and_falls_back(
    tmp_path, store, embedder, make_client
):
    library.add_source(store, "rss", {"url": "https://blog.example/feed"}, label="Blog")
    client = make_client(lambda body: chat_response(CONTRIB))
    report = run_ingest(ingest_cfg(tmp_path), store, client, embedder, http_for(article_site))
    assert report.status == "ok"
    assert report.sources[0].full_text == 1
    bodies = judged_bodies(client)
    assert "prepaid meter" in bodies["solar microgrid battery co-op"]
    assert bodies["solar microgrid battery outage"] == "solar microgrid teaser two"
    assert bodies["solar microgrid battery long"].startswith("solar microgrid battery")
    excerpt = store.query_one(
        "SELECT source_excerpt FROM observations WHERE item_id = 'short'")["source_excerpt"]
    assert "cooperative" in excerpt


def test_full_text_can_be_turned_off(tmp_path, store, embedder, make_client):
    library.add_source(store, "rss", {"url": "https://blog.example/feed"}, label="Blog")
    client = make_client(lambda body: chat_response(CONTRIB))
    report = run_ingest(ingest_cfg(tmp_path, fetch_full_text=False), store, client, embedder,
                        http_for(article_site))
    assert report.sources[0].full_text == 0
    assert judged_bodies(client)["solar microgrid battery co-op"] == "solar microgrid teaser"


def test_full_text_only_after_the_prefilter(tmp_path, store, embedder, make_client):
    src = library.add_source(store, "rss", {"url": "https://blog.example/feed"}, label="Blog")
    topic = library.add_topic(store, embedder, "bread", "sourdough starter flour hydration")
    library.link_topic_source(store, topic, src)
    fetched = []

    def site(request):
        fetched.append(request.url.path)
        return article_site(request)

    client = make_client(lambda body: chat_response(CONTRIB))
    report = run_ingest(ingest_cfg(tmp_path, prefilter_min_similarity=0.9), store, client,
                        embedder, http_for(site), rng=random.Random(0))
    assert report.sources[0].prefiltered == 3
    assert fetched == ["/feed"]


# -- backfill ------------------------------------------------------------------------


class ManyItems:
    kind = "many"
    feeds: dict[str, int] = {}
    backfill_calls: list[str] = []

    def __init__(self, http, *, name):
        self.name = name

    @property
    def label(self):
        return f"many:{self.name}"

    def _items(self):
        base = datetime(2026, 9, 1, tzinfo=UTC)
        return [Item(id=f"{self.name}{i}", title=f"item {i}", body="x" * 400,
                     published_at=base + timedelta(hours=i))
                for i in range(self.feeds[self.name])]

    def fetch(self):
        return self._items()

    def fetch_backfill(self, now=None):
        self.backfill_calls.append(self.name)
        return self._items()

    def enrich(self, item):
        return item


def test_backfill_cap_applies_once_per_source(tmp_path, store, embedder, make_client,
                                              monkeypatch):
    monkeypatch.setitem(sources.KINDS, "many", ManyItems)
    ManyItems.feeds = {"a": 70, "b": 70}
    ManyItems.backfill_calls = []
    cfg = ingest_cfg(tmp_path, backfill_items=40)
    client = make_client(lambda body: chat_response(CONTRIB))
    library.add_source(store, "many", {"name": "a"}, label="many:a")

    first = run_ingest(cfg, store, client, embedder, sources.HTTP())
    assert first.sources[0].backfill and first.sources[0].judged == 40
    assert first.sources[0].deferred == 30
    second = run_ingest(cfg, store, client, embedder, sources.HTTP())
    assert not second.sources[0].backfill and second.sources[0].judged == 10
    assert ManyItems.backfill_calls == ["a"]

    # A source added later gets its own backfill, once; the first one does not.
    library.add_source(store, "many", {"name": "b"}, label="many:b")
    third = run_ingest(cfg, store, client, embedder, sources.HTTP())
    assert [s.judged for s in third.sources] == [10, 40]
    fourth = run_ingest(cfg, store, client, embedder, sources.HTTP())
    assert [s.judged for s in fourth.sources] == [10, 10]
    assert ManyItems.backfill_calls == ["a", "b"]


def test_backfill_is_retried_when_the_first_run_consumed_nothing(
    tmp_path, store, embedder, make_client, monkeypatch
):
    monkeypatch.setitem(sources.KINDS, "many", ManyItems)
    ManyItems.feeds = {"a": 50}
    cfg = ingest_cfg(tmp_path, backfill_items=40)
    library.add_source(store, "many", {"name": "a"}, label="many:a")
    dead = make_client(lambda body: httpx.Response(401))
    assert run_ingest(cfg, store, dead, embedder, sources.HTTP()).status == "failed"
    client = make_client(lambda body: chat_response(CONTRIB))
    report = run_ingest(cfg, store, client, embedder, sources.HTTP())
    assert report.sources[0].backfill and report.sources[0].judged == 40


def test_hackernews_backfill_reaches_back_by_date():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"hits": [
            {"objectID": "7", "title": "t", "created_at_i": 1790000000}]})

    source = HackerNewsSource(http_for(handler), query="microgrid", backfill_days=3)
    [item] = source.fetch_backfill(now=NOW)
    assert item.id == "7"
    since = int((NOW - timedelta(days=3)).timestamp())
    assert seen[0]["numericFilters"] == f"created_at_i>{since}"
    assert seen[0]["hitsPerPage"] == "100" and seen[0]["query"] == "microgrid"
    source.fetch()  # later fetches: the newest 50 inside the same window
    assert seen[1]["numericFilters"].startswith("created_at_i>")
    assert seen[1]["hitsPerPage"] == "50"

    assert HackerNewsSource(http_for(handler), query="x").backfill_days == 14
    with pytest.raises(ValueError):
        HackerNewsSource(http_for(handler), query="x", backfill_days=0)
    feed = HackerNewsSource(http_for(handler), feed="front")
    feed.fetch_backfill(now=NOW)
    assert "numericFilters" not in seen[-1]


def test_ingest_calls_hackernews_backfill_on_first_run_only(
    tmp_path, store, embedder, make_client
):
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"hits": [
            {"objectID": str(len(calls)), "title": "a title", "created_at_i": 1790000000,
             "story_text": "<p>" + "text " * 100 + "</p>"}]})

    library.add_source(store, "hackernews", {"query": "microgrid"}, label="HN search")
    client = make_client(lambda body: chat_response(CONTRIB))
    cfg = ingest_cfg(tmp_path)
    run_ingest(cfg, store, client, embedder, http_for(handler), clock=lambda: NOW)
    run_ingest(cfg, store, client, embedder, http_for(handler), clock=lambda: NOW)
    assert calls[0]["hitsPerPage"] == "100" and calls[1]["hitsPerPage"] == "50"


# -- broad lane, packs, config -------------------------------------------------------


def test_broad_pack_adds_unlinked_sources(tmp_path, store, embedder):
    pack = tmp_path / "broad.yaml"
    pack.write_text("sources:\n  - {kind: rss, value: 'https://blog.example/feed'}\n"
                    "  - {kind: rss, value: 'https://blog.example/missing'}\n")
    report = load_pack(store, embedder, http_for(article_site), pack)
    assert report.topics == [] and report.added == ["Feed"]
    assert len(report.failed) == 1
    [src] = library.list_sources(store)
    assert src.status == "approved" and library.topics_for_source(store, src.id) == []
    with pytest.raises(ValueError):
        (tmp_path / "empty.yaml").write_text("topics: []\n")
        load_pack(store, embedder, http_for(article_site), tmp_path / "empty.yaml")


def test_example_broad_pack_is_well_formed(store, embedder):
    path = Path(__file__).parent.parent / "examples" / "packs" / "broad.yaml"
    text = path.read_text()
    assert "2026-09-24" in text
    report = load_pack(store, embedder, sources.HTTP(), path, check=False)
    assert 6 <= len(report.added) <= 10 and not report.failed and report.topics == []


def test_new_ingest_settings_load_and_validate(tmp_path):
    from kranto.config import init_workspace

    init_workspace(tmp_path)
    cfg = load(tmp_path)
    assert cfg.ingest.fetch_full_text is True and cfg.ingest.backfill_items == 40
    text = (tmp_path / "kranto.yaml").read_text()
    (tmp_path / "kranto.yaml").write_text(text.replace("backfill_items: 40",
                                                         "backfill_items: -1"))
    with pytest.raises(ConfigError, match="backfill_items"):
        load(tmp_path)


def test_feed_dates_without_a_zone_are_utc():
    rdf = b"""<?xml version="1.0"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <channel rdf:about="https://ex.com/"><title>N</title></channel>
    <item rdf:about="https://ex.com/1"><title>a</title><link>https://ex.com/1</link>
    <dc:date>2026-09-24</dc:date></item></rdf:RDF>"""
    _, [item] = parse_feed(rdf)
    assert item.published_at == datetime(2026, 9, 24, tzinfo=UTC)


# -- web: groups, progress, exploration yield ------------------------------------------


@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    cfg = ingest_cfg(tmp_path)
    return open_runtime(cfg, store=store, embedder=embedder,
                        llm=make_client(lambda body: chat_response('{"sources": []}')),
                        http=http_for(article_site))


def test_progress_messages_are_served(rt, store, embedder):
    add_observations(store, embedder, "solar", 12, "solar-a")
    with web_client(create_app(rt)) as web:
        msg = "12 of 30 observations until the first map"
        assert msg in web.get("/api/observations").json()["progress"]
        assert msg in web.get("/api/map").json()["progress"]
    ideas = library_progress(store).ideas_message
    assert "Ideas need a map and a cross-source cluster of at least 10" in ideas
    assert "12 of 30 observations" in ideas


def test_progress_after_a_map():
    none_yet = Progress(observations=80, has_map=True, candidate_clusters=0)
    assert none_yet.map_message == ""
    assert "has none yet" in none_yet.ideas_message
    ready = Progress(observations=80, has_map=True, candidate_clusters=2)
    assert "2 clusters ideas can be written from" in ready.ideas_message
    enough = Progress(observations=31, has_map=False, candidate_clusters=None)
    assert "enough for a first map" in enough.map_message


def test_exploration_yield_counts_cross_source_members(store, embedder, rt):
    for theme in ("solar", "crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
        add_observations(store, embedder, theme, 10, f"{theme}-b")
    rows = {r["admitted_by"]: r for r in library.exploration_yield(store)}
    assert rows["topic"]["n"] == 75 and rows["topic"]["in_cross_source"] is None

    assert take_snapshot(store, embedder, None).status == "ok"
    progress = library_progress(store)
    assert progress.has_map and progress.candidate_clusters >= 1
    rows = {r["admitted_by"]: r for r in library.exploration_yield(store)}
    cross = store.query_one(
        "SELECT COUNT(*) AS n FROM snapshot_points p JOIN clusters c ON "
        "c.snapshot_id = p.snapshot_id AND c.cluster = p.cluster WHERE c.cross_source = 1")["n"]
    assert rows["topic"]["in_cross_source"] == cross > 0
    assert rows["topic"]["mean_signal"] == pytest.approx(0.32)
    with web_client(create_app(rt)) as web:
        served = web.get("/api/health").json()["exploration"]
    assert {r["admitted_by"]: r["n"] for r in served}["topic"] == 75


# -- #48: what the judge reads ---------------------------------------------------------

ARTICLE_TEXT = "Pay-as-you-go solar kits reached 40,000 homes in Kisumu this year. " * 12


@pytest.mark.parametrize("text", [
    "You signed in with another tab or window. Reload to refresh your session. " * 10,
    "A required part of this site couldn't load. This may be due to a browser "
    "extension, network issues, or browser settings. " * 6,
    "Just a moment... Verifying you are human. This may take a few seconds. " * 10,
    "Too short.",
])
def test_extracted_text_that_is_not_the_article_is_rejected(text):
    from kranto.sources.fulltext import usable

    assert not usable(text, "")
    assert usable(ARTICLE_TEXT, "a one-line teaser")
    assert not usable(ARTICLE_TEXT, ARTICLE_TEXT + "the original is already longer")


def test_github_banner_does_not_replace_release_notes():
    """17 of 18 release items reached the judge with only GitHub's sign-in banner,
    including real yjs release notes that it overwrote."""
    banner = ("<html><body><main><p>" + "You signed in with another tab or window. "
              "Reload to refresh your session. You signed out in another tab. " * 8
              + "</p></main></body></html>")

    def site(request):
        return httpx.Response(200, text=banner, headers={"content-type": "text/html"})

    notes = Item(id="v1", title="v13.6.0", body="Fixes the awareness update race.",
                 url="https://github.com/yjs/yjs/releases/tag/v13.6.0")
    assert with_full_text(http_for(site), "rss", notes) == (notes, False)


@pytest.mark.parametrize("body, fetched", [
    ("x" * 320 + "…", True),        # a teaser just over the short-body line
    ("x" * 320 + " [...]", True),
    ("x" * 320 + ".", False),             # a complete short post
    ("x" * 2500 + "…", False),       # long enough to judge as it is
])
def test_teasers_cut_off_with_an_ellipsis_get_full_text(body, fetched):
    item = Item(id="1", title="t", body=body, url="https://canary.example/a")
    assert (full_text_target("rss", item) is not None) == fetched
