"""The catalog of preconfigured sources (section 2) and the new kinds."""

import json

import httpx
import pytest

from kranto import sources
from kranto.sources import HTTP, SourceError, arxiv, catalog
from kranto.sources.bluesky import BlueskySource, post_url
from kranto.sources.mastodon import MastodonSource, clean_instance

DID = "did:plc:abcdefghijklmnopqrstuvwx"
CHANNEL = "UC" + "a1B2c3D4e5F6g7H8i9J0kL"


def http(handler=None):
    return HTTP(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(404))),
                resolver=lambda h: ["93.184.216.34"])


def resolver_site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/@LocalFirstConf":
        page = f'<html><link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL}">'
        return httpx.Response(200, text=page)
    if request.url.path.endswith("resolveHandle"):
        assert request.url.params["handle"] == "alice.bsky.social"
        return httpx.Response(200, json={"did": DID})
    return httpx.Response(404)


# Every public and login preset, with fields, and the (kind, params) it must build.
CASES = [
    ("web.feed", {"url": "https://example.org/feed.xml"}, "rss",
     {"url": "https://example.org/feed.xml"}),
    ("hackernews.front", {}, "hackernews", {"feed": "front"}),
    ("hackernews.show", {}, "hackernews", {"feed": "show"}),
    ("hackernews.ask", {}, "hackernews", {"feed": "ask"}),
    ("hackernews.search", {"query": "local-first"}, "hackernews", {"query": "local-first"}),
    ("github.releases", {"repo": "automerge/automerge"}, "rss",
     {"url": "https://github.com/automerge/automerge/releases.atom"}),
    ("github.releases", {"repo": "https://github.com/automerge/automerge.git"}, "rss",
     {"url": "https://github.com/automerge/automerge/releases.atom"}),
    ("github.commits", {"repo": "automerge/automerge", "branch": "main"}, "rss",
     {"url": "https://github.com/automerge/automerge/commits/main.atom"}),
    ("arxiv.category", {"category": "cs.DC"}, "rss", {"url": "https://rss.arxiv.org/rss/cs.DC"}),
    ("arxiv.search", {"query": "CRDT sync"}, "arxiv", {"query": "CRDT sync"}),
    ("youtube.channel", {"channel": f"https://www.youtube.com/channel/{CHANNEL}"}, "rss",
     {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"}),
    ("youtube.channel", {"channel": "@LocalFirstConf"}, "rss",
     {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"}),
    ("youtube.channel", {"channel": "https://www.youtube.com/@LocalFirstConf/videos"}, "rss",
     {"url": f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"}),
    ("youtube.playlist", {"playlist": "https://www.youtube.com/playlist?list=PLabcdefghij123"},
     "rss", {"url": "https://www.youtube.com/feeds/videos.xml?playlist_id=PLabcdefghij123"}),
    ("mastodon.hashtag", {"instance": "https://Mastodon.Social/", "tag": "#localfirst"}, "rss",
     {"url": "https://mastodon.social/tags/localfirst.rss"}),
    ("mastodon.account", {"account": "@alice@hachyderm.io"}, "rss",
     {"url": "https://hachyderm.io/@alice.rss"}),
    ("mastodon.account", {"account": "https://hachyderm.io/@alice"}, "rss",
     {"url": "https://hachyderm.io/@alice.rss"}),
    ("mastodon.home", {"instance": "mastodon.social"}, "mastodon",
     {"instance": "mastodon.social", "what": "home"}),
    ("mastodon.list", {"instance": "mastodon.social", "list": "https://mastodon.social/lists/42"},
     "mastodon", {"instance": "mastodon.social", "what": "list", "list_id": "42"}),
    ("bluesky.profile", {"handle": "@alice.bsky.social"}, "rss",
     {"url": "https://bsky.app/profile/alice.bsky.social/rss"}),
    ("bluesky.feed", {"url": "https://bsky.app/profile/alice.bsky.social/feed/local-first"},
     "bluesky", {"feed_uri": f"at://{DID}/app.bsky.feed.generator/local-first"}),
    ("bluesky.list", {"url": f"https://bsky.app/profile/{DID}/lists/3kabc"},
     "bluesky", {"list_uri": f"at://{DID}/app.bsky.graph.list/3kabc"}),
    ("stackexchange.tag", {"site": "stackoverflow.com", "tag": "crdt"}, "rss",
     {"url": "https://stackoverflow.com/feeds/tag/crdt"}),
    ("stackexchange.tag", {"site": "https://diy.stackexchange.com/", "tag": "solar"}, "rss",
     {"url": "https://diy.stackexchange.com/feeds/tag/solar"}),
    ("producthunt.today", {}, "rss", {"url": "https://www.producthunt.com/feed"}),
    ("github.starred", {}, "github", {"what": "starred_releases"}),
    ("youtube.subscriptions", {}, "youtube", {"what": "subscriptions"}),
    ("bluesky.home", {}, "bluesky", {"what": "home"}),
    ("bluesky.search", {"query": " local  first "}, "bluesky",
     {"what": "search", "query": "local first"}),
    ("producthunt.launches", {}, "producthunt", {"what": "launches"}),
    ("producthunt.launches", {"topic": "https://www.producthunt.com/topics/developer-tools"},
     "producthunt", {"what": "launches", "topic": "developer-tools"}),
    ("stackexchange.search", {"site": "https://Unix.StackExchange.com/", "query": "crdt"},
     "stackexchange", {"site": "unix.stackexchange.com", "query": "crdt"}),
    ("substack.publication", {"publication": "bootstrapped"}, "rss",
     {"url": "https://bootstrapped.substack.com/feed"}),
    ("substack.publication", {"publication": "https://www.example.com/"}, "rss",
     {"url": "https://www.example.com/feed"}),
    ("x.home", {}, "x", {"what": "home"}),
    ("x.search", {"query": " solar  mini-grids ", "lang": "EN"}, "x",
     {"what": "search", "query": "solar mini-grids", "lang": "en"}),
    ("x.bookmarks", {}, "x", {"what": "bookmarks"}),
    ("x.likes", {}, "x", {"what": "likes"}),
    ("x.grok_search", {"query": "solar mini-grids"}, "xai_search",
     {"query": "solar mini-grids"}),
    ("web.search", {"site": "https://discuss.example.org/"}, "websearch",
     {"site": "discuss.example.org"}),
    ("reddit.sub", {"subreddit": "r/wallstreetbets"}, "reddit", {"subreddit": "wallstreetbets"}),
    ("reddit.search", {"query": " humanoid  robots "}, "websearch",
     {"site": "reddit.com", "query": "humanoid robots"}),
    ("reddit.search", {"query": "CCXI", "subreddit": "r/SPACs"}, "websearch",
     {"site": "reddit.com/r/SPACs", "query": "CCXI"}),
]


@pytest.mark.parametrize(("key", "fields", "kind", "params"), CASES)
def test_each_preset_builds_its_kind_and_params(key, fields, kind, params):
    # Resolving needs no login: list titles are read only when the HTTP carries one.
    h = http(resolver_site) if key != "mastodon.list" else None
    resolved = catalog.resolve(key, fields, h)
    assert (resolved.kind, resolved.params) == (kind, params)
    assert resolved.label
    sources.canonical_params(resolved.kind, resolved.params)  # a known kind with valid params


def test_every_buildable_preset_is_tested():
    tested = {key for key, *_ in CASES}
    # an X list's name and an account's id are read with the account: tests/test_x_sources.py
    buildable = {k for k, p in catalog.PRESETS.items()
                 if p.build is not None and p.available
                 and k not in ("web.site", "x.list", "x.profile")}
    assert buildable <= tested, buildable - tested


def test_the_catalog_has_reddit_two_ways_no_lobsters_and_says_why_for_what_it_does_not_offer():
    data = catalog.catalog_json()
    providers = [p["key"] for p in data["providers"]]
    assert "reddit" in providers and "lobsters" not in providers      # Reddit again: 
    flat = [s for p in data["providers"] for s in p["presets"]]
    assert {s["key"] for s in flat if s["key"].startswith("reddit.")} == {"reddit.sub",
                                                                         "reddit.search"}
    assert not any("lobste" in json.dumps(s) for s in flat)
    for s in flat:
        if s["access"] == "not_offered" or not s["available"]:
            assert s["reason"] and not s["available"]
    login = {s["key"]: s for s in flat if s["access"] == "login"}
    assert login["mastodon.home"]["available"] and login["mastodon.home"]["needs"] == "mastodon"
    # Round 2: every login preset can be built; each names the account it reads with.
    assert all(s["available"] and s["needs"] for s in login.values())
    assert {"github.starred", "youtube.subscriptions", "bluesky.home", "bluesky.search",
            "producthunt.launches"} <= set(login)
    assert {"x", "linkedin"} <= set(providers)
    substack = next(s for s in flat if s["key"] == "substack.publication")
    assert substack["retention_days"] == 30
    youtube = next(s for s in flat if s["key"] == "youtube.subscriptions")
    assert youtube["retention_days"] == 30
    # The scout never proposes a login preset.
    assert not any(catalog.PRESETS[k].scout for k in login)


@pytest.mark.parametrize(("key", "fields", "message"), [
    ("github.releases", {"repo": "not a repo"}, "GitHub repository"),
    ("github.commits", {"repo": "a/b", "branch": "../etc"}, "branch"),
    ("arxiv.category", {"category": "Computer Science"}, "arXiv category"),
    ("mastodon.hashtag", {"instance": "localhost", "tag": "x"}, "instance"),
    ("mastodon.account", {"account": "alice"}, "Mastodon account"),
    ("bluesky.feed", {"url": "https://example.com/feed"}, "Bluesky feed URL"),
    ("stackexchange.tag", {"site": "example.com", "tag": "x"}, "Stack Exchange site"),
    ("youtube.playlist", {"playlist": "nope"}, "playlist"),
    ("hackernews.search", {}, "required"),
    ("hackernews.search", {"query": "x", "extra": "y"}, "unknown fields"),
    ("x.scrape", {}, "not offered"),
    ("x.list", {"list": "1"}, "connected X account"),
    ("bluesky.search", {}, "required"),
    ("producthunt.launches", {"topic": "not a topic!"}, "Product Hunt topic"),
    ("stackexchange.search", {"site": "example.com", "query": "x"}, "Stack Exchange site"),
    ("reddit.subreddit", {"subreddit": "solar"}, "unknown preset"),
])
def test_bad_fields_and_unavailable_presets_are_refused(key, fields, message):
    with pytest.raises(ValueError, match=message):
        catalog.resolve(key, fields, http())


def test_a_channel_handle_is_read_past_youtubes_consent_page():
    """From the EU, YouTube sends a cookie-less visit to consent.youtube.com; the
    "Reject all" cookie (essential cookies only) gets the channel page instead."""
    def site(request):
        if "SOCS=CAI" not in request.headers.get("cookie", ""):
            return httpx.Response(302, headers={"location": "https://consent.youtube.com/m"})
        return resolver_site(request)

    resolved = catalog.resolve("youtube.channel", {"channel": "@LocalFirstConf"}, http(site))
    assert resolved.params["url"].endswith(f"channel_id={CHANNEL}")


def test_a_channel_handle_that_resolves_to_nothing_is_an_error():
    with pytest.raises(SourceError, match="no channel"):
        catalog.resolve("youtube.channel", {"channel": "@nobody-here"},
                        http(lambda r: httpx.Response(200, text="<html></html>")))


def test_site_labels_for_existing_sources():
    assert catalog.provider_of("reddit", {"subreddit": "solar"}) == "reddit"
    assert catalog.provider_of("rss", {"url": "https://github.com/a/b/releases.atom"}) == "github"
    assert catalog.provider_of("rss", {"url": "https://export.arxiv.org/rss/cs.DC"}) == "arxiv"
    assert catalog.provider_of("rss", {"url": "https://hachyderm.io/tags/crdt.rss"}) == "mastodon"
    assert catalog.provider_of("rss", {"url": "https://x.substack.com/feed"}) == "substack"
    assert catalog.provider_of("rss", {"url": "https://example.org/feed"}) == "web"


# -- the new kinds ------------------------------------------------------------------------

ARXIV_FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom"><title>arXiv</title>
<entry><id>http://arxiv.org/abs/2610.00001v1</id><title>Sync without servers</title>
<summary>We study CRDT sync.</summary><published>2026-09-23T00:00:00Z</published>
<link href="http://arxiv.org/abs/2610.00001v1" rel="alternate"/></entry></feed>"""


def test_arxiv_search_is_paced_and_reads_the_export_api(no_host_pacing):
    from kranto.sources import pacing

    seen = []
    # arXiv's own gap, on a clock that stands still: the second search waits it out.
    no_host_pacing.gaps["export.arxiv.org"] = pacing.HOST_GAPS["export.arxiv.org"]
    no_host_pacing.clock = lambda: 100.0

    def api(request):
        seen.append(request.url)
        return httpx.Response(200, content=ARXIV_FEED)

    items = arxiv.ArxivSource(http(api), query="CRDT sync").fetch()
    arxiv.ArxivSource(http(api), query="CRDT sync").fetch()
    assert [i.title for i in items] == ["Sync without servers"]
    assert no_host_pacing.slept == [3.0]
    assert seen[0].host == "export.arxiv.org"
    assert seen[0].params["search_query"] == "all:CRDT AND all:sync"
    assert seen[0].params["sortBy"] == "submittedDate"
    assert arxiv.search_query("ti:crdt AND cat:cs.DC") == "ti:crdt AND cat:cs.DC"
    with pytest.raises(ValueError):
        arxiv.ArxivSource(http(), query=" ")


def test_arxiv_error_entry_is_an_error_not_an_item():
    error =(b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>e</id><title>Error</title>'
             b"<summary>malformed query</summary></entry></feed>")
    with pytest.raises(SourceError, match="refused the query"):
        arxiv.ArxivSource(http(lambda r: httpx.Response(200, content=error)), query="x").fetch()


def bsky_post(n, text, link=None):
    post = {"uri": f"at://{DID}/app.bsky.feed.post/3k{n}", "author": {"handle": "alice.example"},
            "record": {"text": text, "createdAt": "2026-09-23T10:00:00Z"}}
    if link:
        post["embed"] = {"external": {"uri": link, "title": "Linked", "description": "d"}}
    return {"post": post}


def test_bluesky_feed_items_keep_no_author():
    def api(request):
        assert request.url.path.endswith("app.bsky.feed.getFeed")
        return httpx.Response(200, json={"feed": [
            bsky_post(1, "A CRDT engine for SQLite", "https://example.org/post"),
            bsky_post(2, "x" * 300), {"post": "junk"}]})

    src = BlueskySource(http(api), feed_uri=f"at://{DID}/app.bsky.feed.generator/lf")
    first, second = src.fetch()
    assert first.link == "https://example.org/post" and first.title.startswith("A CRDT")
    assert first.url == post_url(f"at://{DID}/app.bsky.feed.post/3k1")
    assert "alice.example" not in json.dumps([first.title, first.body, first.url])
    assert len(second.title) < 150
    with pytest.raises(ValueError):
        BlueskySource(http(), feed_uri="https://bsky.app/x")
    with pytest.raises(SourceError, match="unexpected Bluesky reply"):
        BlueskySource(http(lambda r: httpx.Response(200, json={"error": "x"})),
                      list_uri=f"at://{DID}/app.bsky.graph.list/l").fetch()


def test_mastodon_kind_needs_a_connection():
    with pytest.raises(SourceError) as info:
        sources.build("mastodon", {"instance": "mastodon.social", "what": "home"}, http())
    assert info.value.needs_login and info.value.transient
    assert sources.NEEDS == {"mastodon": "mastodon", "github": "github", "youtube": "youtube",
                             "producthunt": "producthunt", "x": "x"}
    # Bluesky needs an account only for the home timeline and search.
    assert sources.needs("bluesky", {"what": "home"}) == "bluesky"
    assert sources.needs("bluesky", {"feed_uri": "at://x"}) is None
    assert sources.uses("stackexchange") == "stackexchange"
    with pytest.raises(ValueError):
        MastodonSource(http(), instance="mastodon.social", what="list")
    with pytest.raises(ValueError):
        clean_instance("127.0.0.1")
    assert clean_instance("https://Hachyderm.IO/@x") == "hachyderm.io"
