"""Brave and Tavily as web backends, searches restricted to a
site, sites like a result, a site with no feed watched through live search, and the scout's
wildcards and feedless sites. Fakes only: no network, no model."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from kranto import library, scrub, sources, websearch
from kranto.config import ConfigError, SearchConfig, parse_search
from kranto.scout import NO_FEED, scout_topic
from kranto.sources import catalog
from kranto.sources.websearch_source import WebSearchSource
from kranto.store import Store
from kranto.stored.sources import Cost
from kranto.websearch import backends as b

from .conftest import chat_response
from .fake_search import FakeSearch

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def db():
    store = Store.memory()
    yield store
    store.close()


def make(fake, store, provider, **cfg):
    http = fake.http()
    found = {"brave": b.Brave(http, key="brave-test-key-not-real"),
             "tavily": b.Tavily(http, key="tavily-test-key-not-real"),
             "exa": b.Exa(http), "hackernews": b.HackerNews(http)}
    found = {k: v for k, v in found.items() if k == provider or k == "hackernews"}
    s = websearch.Searcher(store, SearchConfig(provider=provider, **cfg), found, http=http)
    s.clock = lambda: NOW
    return s


def test_brave_and_tavily_are_dated_and_priced(db):
    fake = FakeSearch()
    brave = make(fake, db, "brave").search("sync engines", recency="4w")
    _, path, query = fake.calls[-1]
    assert path == "/res/v1/web/search" and query["freshness"].startswith("2026-09-19to")
    assert [h.date for h in brave.hits] == ["2026-10-11", None]
    tavily = make(fake, db, "tavily").search("sync engines", recency="4w")
    body = fake.calls[-1][2]
    assert body["start_date"] == "2026-09-19" and body["include_published_date"] is True
    assert tavily.hits[0].date == "2026-10-10" and tavily.labels == ("Tavily",)
    rows = [dict(r) for r in db.query("SELECT provider, kind, usd FROM api_spend ORDER BY id")]
    assert rows == [{"provider": "brave", "kind": "search", "usd": 0.005},
                    {"provider": "tavily", "kind": "search", "usd": 0.008}]


def test_braves_results_are_never_cached(db):
    fake = FakeSearch()
    s = make(fake, db, "brave")
    s.search("sync")
    again = s.search("sync")
    assert not again.cached and len([c for c in fake.calls if c[0] == "api.search.brave.com"]) == 2
    assert db.query_one("SELECT COUNT(*) n FROM search_cache")["n"] == 0


def test_without_their_key_brave_and_tavily_say_so(db):
    http = FakeSearch().http()
    for cls, words in ((b.Brave, "BRAVE_API_KEY"), (b.Tavily, "TAVILY_API_KEY")):
        with pytest.raises(websearch.BackendError, match=words):
            cls(http, key=None).search("q", None, 5)


def test_a_search_restricted_to_a_site_keeps_only_its_pages(db):
    fake = FakeSearch()
    got = make(fake, db, "brave").search("sync", site="https://www.forum.example.org/")
    assert fake.calls[-1][2]["q"] == "sync site:forum.example.org"
    assert [h.url for h in got.hits] == ["https://forum.example.org/t/1"]
    make(fake, db, "tavily").search("sync", site="forum.example.org")
    assert fake.calls[-1][2]["include_domains"] == ["forum.example.org"]
    exa = make(fake, db, "exa").search("sync", site="example.dev")
    assert "Only pages on example.dev." in fake.calls[-1][2]["params"]["arguments"]["objective"]
    assert {h.url.split("/")[2] for h in exa.hits} == {"example.dev"}
    # the site is part of the cache key
    assert not make(fake, db, "exa").search("sync").cached


def test_sites_like_a_result_are_a_described_search(db):
    fake = FakeSearch()
    make(fake, db, "exa").similar("https://example.dev/blog", "A sync blog", n=5)
    args = fake.calls[-1][2]["params"]["arguments"]
    assert args["query"] == ("publications, blogs and communities like A sync blog "
                             "(https://example.dev/blog)") and args["numResults"] == 5


def test_the_config_knows_brave_tavily_and_the_sources_switch():
    assert parse_search({"provider": "brave"}).provider == "brave"
    assert parse_search({"callers": {"sources": False}}).caller("sources") == "off"
    with pytest.raises(ConfigError):
        parse_search({"provider": "kagi"})
    s = websearch.searcher(type("C", (), {"search": SearchConfig(provider="tavily"),
                                          "llm": None})(), None, FakeSearch().http(),
                           environ={"TAVILY_API_KEY": "tavily-test-key-not-real"})
    assert s.web == "tavily" and s.label("tavily") == "Tavily"


def test_search_keys_are_scrubbed_from_text():
    assert "[secret]" in scrub.scrub("token tvly-" + "x9" * 12)


# -- a site watched through live search --------------------------------------------------------


def test_the_catalog_builds_a_live_search_source():
    r = catalog.resolve("web.search", {"site": "https://www.discuss.example.org/latest",
                                       "query": "  releases "}, None)
    assert (r.kind, r.params, r.label) == ("websearch", {"site": "discuss.example.org",
                                                         "query": "releases"},
                                           "Live search: discuss.example.org (releases)")
    assert sources.canonical_params("websearch", {"site": "WWW.Discuss.Example.org"}) == \
        '{"site":"discuss.example.org"}'
    with pytest.raises(ValueError):
        catalog.resolve("web.search", {"site": "localhost"}, None)


def test_a_live_search_source_reads_the_site_through_the_process_searcher(db, monkeypatch):
    fake = FakeSearch()
    s = make(fake, db, "brave")
    monkeypatch.setattr(websearch, "_CURRENT", s)
    src = sources.build("websearch", {"site": "forum.example.org"}, fake.http())
    items = src.fetch()
    assert [i.url for i in items] == ["https://forum.example.org/t/1"]
    assert items[0].published_at.date().isoformat() == "2026-10-11"
    assert items[0].capture_note.startswith("a search result from brave")
    assert db.query_one("SELECT caller FROM api_spend")["caller"] == "sources"
    monkeypatch.setattr(websearch, "_CURRENT", None)
    with pytest.raises(sources.SourceError, match="no live search"):
        src.fetch()
    off = make(FakeSearch(), db, "brave", callers={"sources": "off"})
    monkeypatch.setattr(websearch, "_CURRENT", off)
    with pytest.raises(sources.SourceError, match="live search is off for the sources"):
        WebSearchSource(None, site="forum.example.org").fetch()


# -- the scout: wildcards from sites like the strongest results; feedless sites proposed --------


def site(request):
    if request.url.host == "nofeed.example":
        return httpx.Response(200, text="<html><body>Threads</body></html>",
                              headers={"content-type": "text/html"})
    return httpx.Response(404)


def test_the_scout_proposes_a_feedless_site_to_watch_by_search_and_finds_wildcards(
        store, embedder, make_client):
    library.add_topic(store, embedder, "local-first software", "sync engines")
    [topic] = library.active_topics(store)
    fake = FakeSearch()
    searcher = websearch.Searcher(store, SearchConfig(), {"exa": b.Exa(fake.http())},
                                  caller="scout", http=fake.http())
    searcher.clock = lambda: NOW
    client = make_client(lambda body: chat_response(json.dumps({"sources": [
        {"preset": "web.site", "fields": {"site": "https://nofeed.example/"}, "role": "core",
         "from": ["exa 1"], "why": "a forum"}]})))
    [r] = scout_topic(store, client, embedder,
                      sources.HTTP(transport=httpx.MockTransport(site),
                                   resolver=lambda h: ["93.184.216.34"]),
                      topic, now=NOW, searcher=searcher)
    assert r.status == NO_FEED and r.source_id is not None
    [src] = library.list_sources(store)
    assert (src.kind, src.params, src.status) == ("websearch", {"site": "nofeed.example"},
                                                  "proposed")
    assert src.validation.cost_usd == Cost(check=0.0, run=0.0)     # Exa's free mode
    queries = [c[2]["params"]["arguments"]["query"] for c in fake.calls
               if c[2].get("method") == "tools/call"]
    # the two strongest dated results, one search each
    assert sum(q.startswith("publications, blogs and communities like") for q in queries) == 2
    prompt = client.fake.requests[0]["messages"][0]["content"]
    assert "choose the wildcards from them" in prompt
