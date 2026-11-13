"""the validation flaws a real run of the scout's checks found.

arXiv's listing is empty on days without announcements; discovery missed a feed linked
from the page's body and hid a feed's size behind "no feed found"; one response header
outside ASCII raised UnicodeEncodeError; and a feed URL with the wrong path lost the
publication."""

from datetime import UTC, datetime

import httpx
import pytest

from kranto import library
from kranto.scout import Proposal, scout_topic, validate
from kranto.sources import HTTP, SourceError
from kranto.sources.base import MAX_RESPONSE_BYTES
from kranto.sources.discover import body_feed_links, discover_feed

from .conftest import chat_response
from .test_scout import feed

NOW = datetime(2026, 9, 24, tzinfo=UTC)
FEED = feed("solar microgrid battery storage", "solar microgrid battery prices")
HTML = {"content-type": "text/html"}


def web(request):
    host, path = request.url.host, request.url.path
    if host == "rss.arxiv.org":
        return httpx.Response(200, content=feed())   # a Saturday: no announcements
    if host == "jepsen.example":
        if path == "/":
            return httpx.Response(200, headers=HTML, content=(
                '<html><body><a href="/sitemap.xml">map</a> <a href="/blog">Blog</a> '
                '<a href="https://other.example/x.rss">elsewhere</a> '
                '<a href="/blog.rss#top">RSS</a></body></html>'))
        if path == "/blog.rss":
            return httpx.Response(200, content=FEED)
    if host == "big.example":
        if path == "/":
            return httpx.Response(200, headers=HTML, content=(
                '<html><head><link rel="alternate" type="application/atom+xml" '
                'href="/atom.xml"></head><body/></html>'))
        if path == "/atom.xml":
            return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
    if host == "clacks.example":
        return httpx.Response(200, headers=[(b"x-clacks-overhead", "GNU Bjørn".encode()),
                                            (b"content-type", b"application/rss+xml")],
                              content=FEED)
    if host == "blog.example":
        if path == "/":
            return httpx.Response(200, headers=HTML, content="<html><body>posts</body></html>")
        if path == "/feed":
            return httpx.Response(200, content=FEED)
    if host == "github.com" and path == "/feed":
        return httpx.Response(200, content=FEED)
    return httpx.Response(404)


def http():
    return HTTP(transport=httpx.MockTransport(web), resolver=lambda h: ["93.184.216.34"])


@pytest.fixture
def topic(embedder):
    return library.Topic(1, "solar", "solar microgrid battery",
                         embedder.embed_query("solar microgrid battery"))


def preset(key, **fields):
    return Proposal("preset", " ".join([key, *fields.values()]), "", preset=key, fields=fields)


def test_an_empty_arxiv_listing_is_unverified_not_invalid(embedder, topic):
    v, label, kind, params = validate(preset("arxiv.category", category="cs.DC"), http(),
                                      embedder, topic, now=NOW)
    assert v.status == "unverified" and "weekends and holidays" in v.error
    assert params == {"url": "https://rss.arxiv.org/rss/cs.DC"}


def test_discovery_reads_a_feed_linked_from_the_body():
    page = ('<a href="/sitemap.xml">m</a><a href="/a.atom">a</a>'
            '<a href="https://other.example/b.rss">b</a><a href="/c.html">c</a>')
    assert body_feed_links(page, "https://ex.com/") == ["https://ex.com/a.atom"]
    assert discover_feed(http(), "https://jepsen.example/") == "https://jepsen.example/blog.rss"


def test_a_feed_over_the_size_cap_says_so():
    with pytest.raises(SourceError, match="larger than 5 MB") as caught:
        discover_feed(http(), "https://big.example/")
    assert "https://big.example/atom.xml" in str(caught.value)
    assert caught.value.transient is False


def test_a_response_header_outside_ascii_is_kept():
    response = http().get("https://clacks.example/")
    assert response.headers["x-clacks-overhead"] == "GNU Bjørn"
    assert response.content == FEED


def test_a_feed_url_with_the_wrong_path_finds_the_sites_feed(embedder, topic):
    """#78: a guessed feed path 404d and the publication was lost."""
    v, _, kind, params = validate(preset("web.feed", url="https://blog.example/category/rss"),
                                  http(), embedder, topic, now=NOW)
    assert v.status == "valid" and v.items == 2
    assert params == {"url": "https://blog.example/feed"}
    assert v.discovered_from == "https://blog.example/category/rss"
    # On a platform the path names the repository: the root's feed is another source.
    v, _, _, params = validate(
        preset("web.feed", url="https://github.com/someone/missing/releases.atom"), http(),
        embedder, topic, now=NOW)
    assert v.status == "invalid" and v.discovered_from is None
    assert params == {"url": "https://github.com/someone/missing/releases.atom"}


def test_the_scout_records_the_feed_it_found(store, embedder, make_client):
    reply = ('{"sources": [{"preset": "web.feed", "fields": {"url": '
             '"https://blog.example/category/rss"}, "why": "w"}]}')
    client = make_client(lambda body: chat_response(reply))
    library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    [topic] = library.active_topics(store)
    [result] = scout_topic(store, client, embedder, http(), topic, now=NOW)
    assert result.status == "proposed"
    [source] = library.list_sources(store)
    assert source.params == {"url": "https://blog.example/feed"}
    assert source.validation.fields == {"url": "https://blog.example/feed"}
    assert source.validation.discovered_from == "https://blog.example/category/rss"
