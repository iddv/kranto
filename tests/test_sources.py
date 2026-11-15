import httpx
import pytest

from kranto.sources import HTTP, Item, SourceError, build, canonical_params, canonical_url
from kranto.sources.base import check_public_url, html_to_text
from kranto.sources.rss import parse_feed

RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Grid Notes</title>
<item><title>Mini-grids in Kenya</title><link>https://ex.com/a</link><guid>a-1</guid>
<description>&lt;p&gt;Pay-as-you-go &amp;amp; solar&lt;/p&gt;</description>
<pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>No guid</title><link>https://ex.com/b</link><description>b</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>r/solar</title>
<entry><id>t3_abc</id><title>Battery prices</title>
<link href="https://www.reddit.com/r/solar/comments/abc/x/"/>
<author><name>/u/someone</name></author><published>2026-09-23T08:00:00+00:00</published>
<content type="html">&lt;div&gt;LFP cells hit $50/kWh&lt;/div&gt;
 submitted by /u/someone [link] [comments]</content>
</entry></feed>"""


def public(host):
    return ["93.184.216.34"]


def http_for(handler) -> HTTP:
    return HTTP(transport=httpx.MockTransport(handler), resolver=public)


def test_parse_rss():
    title, items = parse_feed(RSS)
    assert title == "Grid Notes"
    assert [i.id for i in items] == ["a-1", "https://ex.com/b"]
    assert items[0].body == "Pay-as-you-go & solar"
    assert items[0].published_at.year == 2026


def test_parse_atom_and_reddit_boilerplate():
    source = build(
        "reddit", {"subreddit": "solar"}, http_for(lambda r: httpx.Response(200, content=ATOM))
    )
    [item] = source.fetch()
    assert item.id == "t3_abc"
    assert item.body == "LFP cells hit $50/kWh"
    assert not hasattr(item, "author"), "authors are never kept"
    assert source.label == "r/solar"


def test_parse_rss1_rdf():
    rdf = b"""<?xml version="1.0"?>
    <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
             xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <channel rdf:about="https://ex.com/"><title>Pipeline</title></channel>
    <item rdf:about="https://ex.com/p/1"><title>Kinase inhibitors</title>
    <link>https://ex.com/p/1</link><description>&lt;p&gt;Selectivity data&lt;/p&gt;</description>
    <dc:creator>D. Lowe</dc:creator><dc:date>2026-09-20T10:00:00Z</dc:date></item>
    </rdf:RDF>"""
    title, [item] = parse_feed(rdf)
    assert title == "Pipeline"
    assert item.id == "https://ex.com/p/1" and item.body == "Selectivity data"
    assert item.published_at.day == 20 and not hasattr(item, "author")


def test_unparseable_feed_is_an_error():
    with pytest.raises(SourceError):
        parse_feed(b"<html><body>blocked</body></html>")
    with pytest.raises(SourceError):
        parse_feed(b"not xml at all")


def test_xml_entity_expansion_is_refused():
    bomb = b"""<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>
    <rss><channel><title>&b;</title></channel></rss>"""
    with pytest.raises(SourceError):
        parse_feed(bomb)


def test_hackernews_query_fetch_and_comment_enrichment():
    def handler(request):
        if request.url.path.endswith("/search_by_date"):
            assert request.url.params["query"] == "solar"
            return httpx.Response(200, json={"hits": [{
                "objectID": "42", "title": "Show HN: solar", "url": "https://s.example",
                "author": "pg", "created_at_i": 1790000000, "points": 10, "num_comments": 2,
            }]})
        assert request.url.path.endswith("/items/42")
        return httpx.Response(200, json={"children": [{"text": "<p>Real numbers: 18%</p>"}]})

    source = build("hackernews", {"query": "solar"}, http_for(handler))
    [item] = source.fetch()
    assert item.url == "https://news.ycombinator.com/item?id=42"
    assert item.link == "https://s.example"
    enriched = source.enrich(item)
    assert enriched.comments == ("Real numbers: 18%",)


def test_hackernews_query_search_has_no_typo_tolerance():
    """#33: with typo tolerance on, 'CRDT' matched critical and Criterion."""
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"hits": []})

    source = build("hackernews", {"query": "CRDT"}, http_for(handler))
    source.fetch()
    source.fetch_backfill()
    assert [r.url.params["typoTolerance"] for r in requests] == ["false", "false"]

    requests.clear()
    build("hackernews", {"feed": "new"}, http_for(handler)).fetch()
    assert "typoTolerance" not in requests[0].url.params


def test_hackernews_needs_exactly_one_mode():
    with pytest.raises(ValueError):
        build("hackernews", {}, http_for(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError):
        build("hackernews", {"feed": "best"}, http_for(lambda r: httpx.Response(200)))


def test_rate_limit_is_transient_and_404_is_not():
    with pytest.raises(SourceError) as info:
        build("rss", {"url": "https://ex.com/f"},
              http_for(lambda r: httpx.Response(429))).fetch()
    assert info.value.transient
    with pytest.raises(SourceError) as info:
        build("rss", {"url": "https://ex.com/f"},
              http_for(lambda r: httpx.Response(404))).fetch()
    assert not info.value.transient


def test_private_addresses_are_refused():
    for address in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "192.168.1.10"):
        with pytest.raises(SourceError, match="non-public"):
            check_public_url("http://internal.example/feed", resolver=lambda h, a=address: [a])
    with pytest.raises(SourceError):
        check_public_url("file:///etc/passwd", resolver=public)


def test_redirects_are_rechecked():
    def resolver(host):
        return ["127.0.0.1"] if host == "evil.internal" else ["93.184.216.34"]

    http = HTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://evil.internal/x"})
        ),
        resolver=resolver,
    )
    with pytest.raises(SourceError, match="non-public"):
        http.get("https://ex.com/feed")


def test_gzip_encoded_feed_is_decoded_once():
    import gzip

    def handler(request):
        return httpx.Response(
            200, content=gzip.compress(RSS), headers={"content-encoding": "gzip"}
        )

    [first, _] = build("rss", {"url": "https://ex.com/f"}, http_for(handler)).fetch()
    assert first.title == "Mini-grids in Kenya"


def test_oversized_responses_are_refused():
    big = b"x" * 5_000_001
    with pytest.raises(SourceError, match="5MB"):
        http_for(lambda r: httpx.Response(200, content=big)).get("https://ex.com/big")


def test_canonical_params_dedupes_equivalent_sources():
    assert canonical_params("reddit", {"subreddit": "r/Solar"}) == canonical_params(
        "reddit", {"subreddit": "solar"}
    )
    with pytest.raises(ValueError):
        canonical_params("twitter", {})


def test_html_to_text():
    assert html_to_text("<p>a</p><script>x()</script><p>b &amp; c</p>") == "a\nb & c"


def test_only_http_urls_are_kept():
    from kranto.sources import safe_url

    assert safe_url("https://ex.com/a") == "https://ex.com/a"
    for bad in ("javascript:alert(1)", "data:text/html,x", "//ex.com", "ftp://x", "", None):
        assert safe_url(bad) is None


@pytest.mark.parametrize("url, expected", [
    ("https://www.Example.com/a/b/?utm_source=hn&utm_medium=x#frag", "https://example.com/a/b"),
    ("http://example.com:80/a?b=2&a=1&fbclid=z", "https://example.com/a?a=1&b=2"),
    ("https://example.com:8443/a/", "https://example.com:8443/a"),
    ("https://example.com/", "https://example.com"),
    ("https://news.ycombinator.com/item?id=42", "https://news.ycombinator.com/item?id=42"),
    ("javascript:alert(1)", None),
    (None, None),
])
def test_canonical_url(url, expected):
    assert canonical_url(url) == expected


def test_item_canonical_url_prefers_the_linked_article():
    item = Item(id="1", title="t", body="", url="https://news.ycombinator.com/item?id=1",
                link="https://www.a.example/post/")
    assert item.canonical_url() == "https://a.example/post"
    ask = Item(id="2", title="t", body="", url="https://news.ycombinator.com/item?id=2")
    assert ask.canonical_url() == "https://news.ycombinator.com/item?id=2"


# -- #39: hostile input must fail one source, never the whole run ---------------------


@pytest.mark.parametrize("location", ["mailto:someone@example.com", "javascript:alert(1)"])
def test_redirect_to_a_non_http_location_is_a_permanent_source_error(location):
    """httpx raised InvalidURL (not an HTTPError) for these, which escaped ingest."""
    http = http_for(lambda r: httpx.Response(302, headers={"location": location}))
    with pytest.raises(SourceError) as exc:
        http.get("https://ex.com/article")
    assert not exc.value.transient


def test_slow_drip_hits_the_request_deadline():
    import time

    def drip():
        for _ in range(50):
            time.sleep(0.02)
            yield b"x"

    http = HTTP(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=drip())),
                resolver=public, deadline=0.1)
    started = time.monotonic()
    with pytest.raises(SourceError, match="no complete response within"):
        http.get("https://ex.com/slow")
    assert time.monotonic() - started < 0.5


def test_titles_are_truncated_at_parse_time():
    item = Item(id="1", title="t" * 1_500_000, body="")
    assert len(item.title) <= 510 and item.title.endswith("...")


@pytest.mark.parametrize("payload", [
    [], {"message": "rate limited"}, {"hits": None}, {"hits": "nope"},
])
def test_unexpected_algolia_replies_are_source_errors(payload):
    source = build("hackernews", {"query": "x"}, http_for(lambda r: httpx.Response(
        200, json=payload)))
    with pytest.raises(SourceError, match="unexpected Algolia reply"):
        source.fetch()


def test_algolia_hits_with_wrong_shapes_are_skipped_or_coerced():
    source = build("hackernews", {"query": "x"}, http_for(lambda r: httpx.Response(200, json={
        "hits": ["junk", None, {"objectID": 7, "title": ["not", "a", "string"], "url": 5}]})))
    [item] = source.fetch()
    assert item.id == "7" and item.title == "" and item.link is None


@pytest.mark.parametrize("thread", [[], "x", {"children": None}])
def test_unexpected_algolia_thread_is_a_source_error(thread):
    source = build("hackernews", {"query": "x"}, http_for(lambda r: httpx.Response(
        200, json=thread)))
    item = Item(id="1", title="t", body="", meta={"num_comments": 3})
    with pytest.raises(SourceError, match="unexpected Algolia thread"):
        source.enrich(item)


def test_atom_entries_without_id_or_link_do_not_collide_on_title():
    feed = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>
    <entry><title>Weekly update</title><summary>first week</summary></entry>
    <entry><title>Weekly update</title><summary>second week</summary></entry></feed>"""
    _, items = parse_feed(feed)
    assert len({it.id for it in items}) == 2


def test_full_text_failure_of_any_kind_keeps_the_item(monkeypatch):
    from kranto.sources import fulltext

    def boom(http, url):
        raise RuntimeError("hostile page")

    monkeypatch.setattr(fulltext, "fetch_full_text", boom)
    item = Item(id="1", title="t", body="", link="https://ex.com/a")
    assert fulltext.with_full_text(http_for(lambda r: None), "hackernews", item) == (item, False)


# -- #46: duplicates beyond exact URLs -------------------------------------------------


@pytest.mark.parametrize("a, b", [
    ("https://github.com/o/r/blob/main/x.py?ref=v1", "https://github.com/o/r/blob/main/x.py?ref=v2"),
    ("https://gitlab.com/o/r/-/raw/x?ref=main", "https://gitlab.com/o/r/-/raw/x?ref=dev"),
    ("https://app.example/#/post/1", "https://app.example/#/post/2"),
    ("https://app.example/#!/post/1", "https://app.example/#!/post/2"),
])
def test_urls_that_differ_in_content_are_not_merged(a, b):
    assert canonical_url(a) != canonical_url(b)


def test_referrer_ref_and_position_fragments_are_still_dropped():
    assert canonical_url("https://blog.example/a?ref=hn#comments") == "https://blog.example/a"


def _reddit_entry(post: str, title: str, content: str) -> str:
    import html

    permalink = f"https://www.reddit.com/r/solar/comments/{post}/x/"
    return (f"<entry><id>t3_{post}</id><title>{title}</title><link href=\"{permalink}\"/>"
            f"<content type=\"html\">{html.escape(content)}</content></entry>")


REDDIT = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
          "<feed xmlns=\"http://www.w3.org/2005/Atom\"><title>r/solar</title>"
          + _reddit_entry("link1", "Kisumu PAYG study",
                          'submitted by <a href="https://www.reddit.com/user/x"> /u/x </a> '
                          '<span><a href="https://www.blog.example/kisumu-payg/?utm_source=reddit">'
                          '[link]</a></span> <span><a href="https://www.reddit.com/r/solar/'
                          'comments/link1/x/">[comments]</a></span>')
          + _reddit_entry("self2", "My setup",
                          '<div>Twelve panels.</div> submitted by /u/y <span><a href='
                          '"https://www.reddit.com/r/solar/comments/self2/x/">[link]</a></span>')
          + _reddit_entry("gal3", "Photos",
                          '<span><a href="https://www.reddit.com/gallery/gal3">[link]</a></span>')
          + "</feed>").encode()


def test_reddit_link_posts_carry_the_article_they_link_to():
    """#46: the external URL lived only in the [link] anchor, so a Reddit post of
    an article already judged via HN or RSS was judged and stored again."""
    source = build("reddit", {"subreddit": "solar"},
                   http_for(lambda r: httpx.Response(200, content=REDDIT)))
    link, self_post, gallery = source.fetch()
    assert link.link == "https://www.blog.example/kisumu-payg/?utm_source=reddit"
    assert link.canonical_url() == canonical_url("https://blog.example/kisumu-payg")
    assert self_post.link is None and gallery.link is None
    assert self_post.canonical_url().startswith("https://reddit.com/r/solar/comments/self2")


def test_reddit_requests_are_paced_across_subreddits():
    """#63: unpaced, 15 of 17 subreddits in one run returned 429."""
    from kranto.sources import reddit

    now, slept = [100.0], []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    pacer = reddit._Pacer(30.0, clock=lambda: now[0], sleep=sleep)
    pacer.wait()          # first request: no wait
    now[0] += 5
    pacer.wait()          # 5 s later: waits the remaining 25
    now[0] += 40
    pacer.wait()          # 40 s later: no wait
    assert slept == [25.0]


def test_github_repository_urls():
    from kranto.sources.github import repository

    assert repository("https://github.com/yjs/yjs/releases/tag/v13.6.0") == ("yjs", "yjs")
    assert repository("https://www.github.com/acme/tool.git") == ("acme", "tool")
    assert repository("https://github.com/topics/crdt") is None
    assert repository("https://gitlab.com/a/b") is None and repository(None) is None


def test_github_lookups_are_cached_capped_and_failures_ignored():
    from kranto.sources.github import RepoStats

    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/broken"):
            return httpx.Response(404)
        return httpx.Response(200, json={"stargazers_count": 7})

    stats = RepoStats(http_for(handler), max_lookups=2)
    assert stats.stats("a", "one")["stars"] == 7
    assert stats.stats("A", "ONE")["stars"] == 7          # cached, case-insensitive
    assert stats.stats("a", "broken") is None             # a failed lookup is not an error
    assert stats.stats("a", "three") is None              # over the cap: not looked up
    assert calls == ["/repos/a/one", "/repos/a/broken"]
