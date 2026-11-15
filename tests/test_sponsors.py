"""Sponsors and ads are a hard no: links in sponsor or advertising context are
never followed, items that announce themselves as ads never reach a model, and the
judge's override is counted and cannot lift an item too thin for it."""

import json
from datetime import timedelta

import httpx
import pytest

from kranto import library
from kranto.sources import Item, sponsors
from kranto.sources.gather import fetch_page

from .conftest import (
    FIXED_NOW,
    SCREEN_PASS,
    chat_response,
    is_screen,
    judge_requests,
    screen_requests,
)
from .test_look import (
    Feed,
    config,
    feeds,  # noqa: F401  (autouse: registers the fixed-item feeds)
    fields,
    hn,
    hn_item,
    ingest,
    replying,
    seen,
)
from .webfake import PARAGRAPH, Web, http_for, page

EPISODE = "https://podcast.test/21"
INTRO = ("The guest of this episode built the sync engine behind a widely used issue "
         "tracker and has worked on replication for a decade. The conversation covers "
         "why the client holds a full copy of the data, how conflicts are resolved, and "
         "what they would change. ")
LONG_PROSE = ("Event sponsorship in open source has a long history; a study of conference "
              "budgets, sponsored by no one, found that most events depend on a handful of "
              "companies. " + PARAGRAPH * 6 +
              'The full dataset is <a href="https://history.test/sponsorship-study">here</a>.')

# A podcast episode page laid out like a common show-notes template: sponsor logos
# above the notes, the notes inside <main>, a thank-you line and a read-out offer at
# the end, an ad slot beside them and a sponsor call in the footer.
SHOW_NOTES = f"""<html><head><title>#21 - Sync engines in practice</title></head><body>
<header><nav><a href="/">Home</a> <a href="/episodes">Episodes</a></nav></header>
<div class="flex text-sm items-center gap-4"><span class="w-full">Sponsored by</span>
 <a href="https://acmesync.test/"><img src="/acme.png" alt="Acme Sync"></a>
 <a href="https://widgetcorp.test/"><img src="/widget.png" alt="Widget Corp"></a></div>
<main><div class="prose">
<p>{INTRO * 3}</p>
<p>Mentioned in podcast</p>
<ul><li><a href="https://syncproject.test/">Sync Project</a></li>
<li><a href="https://eng.blog.test/how-we-built-sync">How we built our sync engine</a></li>
<li><a href="https://papers.test/crdts">A paper on CRDTs</a></li></ul>
<p>{LONG_PROSE}</p>
<p>Links:</p><ul><li>Website: <a href="https://podcast.test/">podcast.test</a></li></ul>
<p>Thank you to <a href="https://www.acmesync.test">Acme Sync</a> and
 <a href="https://partnerlabs.test/">Partner Labs</a> for supporting the podcast.</p>
<p>This episode is brought to you by
 <a href="https://hosting.test/?utm_source=podcast">Hosting Co</a>: use code KRANTO20.</p>
</div></main>
<aside class="ad-slot"><a href="https://shoes.test/landing">Running shoes</a></aside>
<footer><span>Latest Sponsors:</span>
 <ul><li><a href="https://podcast.test/sponsor">Become a sponsor</a></li></ul></footer>
</body></html>"""

SPONSORS = {"https://acmesync.test", "https://widgetcorp.test", "https://partnerlabs.test",
            "https://hosting.test", "https://shoes.test/landing",
            "https://podcast.test/sponsor"}
CONTENT = {"https://syncproject.test", "https://eng.blog.test/how-we-built-sync",
           "https://papers.test/crdts", "https://history.test/sponsorship-study"}


def test_sponsor_context_on_a_show_notes_page():
    found = sponsors.sponsor_links(SHOW_NOTES, EPISODE)
    assert set(found) == SPONSORS
    assert not CONTENT & set(found), "the episode's own links are kept"
    assert "Sponsored by" in found["https://widgetcorp.test"]
    assert "for supporting" in found["https://partnerlabs.test"]
    assert "brought" in found["https://hosting.test"]
    assert "'ad'" in found["https://shoes.test/landing"]


def test_a_sponsor_is_left_out_everywhere_on_the_page_that_thanks_it():
    page_ = fetch_page(http_for(Web(**{EPISODE: httpx.Response(200, html=SHOW_NOTES)})),
                       EPISODE)
    links = set(page_.links)
    assert not any("acmesync" in u or "partnerlabs" in u or "hosting.test" in u
                   for u in links)
    assert "https://syncproject.test/" in links and "https://papers.test/crdts" in links
    assert any("acmesync" in u for u in page_.sponsored)


@pytest.mark.parametrize("markup", [
    "<h2>Our sponsors</h2><ul><li><a href='https://a.test/'>A</a> makes databases</li>"
    "<li><a href='https://b.test/'>B</a></li></ul><h2>Notes</h2>"
    "<p><a href='https://c.test/'>kept</a></p>",
    "<p>Today's sponsor is <a href='https://a.test/'>A</a>. And "
    "<a href='https://b.test/'>B</a>, our other one.</p><p><a href='https://c.test/'>kept</a></p>",
    "<div id='sponsor-banner'><a href='https://a.test/'>A</a> <a href='https://b.test/'>B</a>"
    "</div><p><a href='https://c.test/'>kept</a></p>",
    "<p>Affiliate links: <a href='https://a.test/'>A</a>, <a href='https://b.test/'>B</a></p>"
    "<p>See <a href='https://c.test/'>kept</a></p>",
])
def test_sponsor_sections_labels_and_slots(markup):
    assert set(sponsors.sponsor_links(markup)) == {"https://a.test", "https://b.test"}


def test_an_ordinary_page_has_no_sponsor_links():
    assert sponsors.sponsor_links(page("Battery fade", ["https://paper.test/study"])) == {}
    assert sponsors.sponsor_links("") == {} and sponsors.sponsor_links(None) == {}


@pytest.mark.parametrize("url, reason", [
    ("https://ad.doubleclick.net/ddm/clk/123", "doubleclick.net"),
    ("https://amzn.to/3xYz", "amzn.to"),
    ("https://www.amazon.com/dp/B000?tag=kranto-20", "Amazon affiliate tag"),
    ("https://shop.test/item?aff_id=42", "aff_id"),
    ("https://db.test/?utm_source=pod&utm_medium=sponsored", "utm_medium=sponsored"),
    ("https://db.test/?utm_campaign=q3-sponsorship", "utm_campaign"),
    ("https://go.redirectingat.com/?id=1&url=https%3A%2F%2Fshop.test", "redirectingat.com"),
])
def test_ad_and_affiliate_urls(url, reason):
    assert reason in (sponsors.ad_url(url) or "")


@pytest.mark.parametrize("url", [
    "https://github.com/acme/widget?ref=main", "https://paper.test/study?utm_source=hn",
    "https://www.amazon.science/blog/post", "https://shop.test/item?tag=red",
    "https://notdoubleclick.net.test/", None,
])
def test_ordinary_urls_are_not_ads(url):
    assert sponsors.ad_url(url) is None


@pytest.mark.parametrize("title, ad", [
    ("[Sponsor] Acme Sync: real-time sync for Postgres", True),
    ("Sponsored: the fastest database", True),
    ("(Ad) Try our hosting", True),
    ("Advertisement - Acme", True),
    ("Paid post: why you need Acme", True),
    ("GitHub Sponsors pays out to 4,000 maintainers", False),
    ("Show HN: An ad blocker for terminals", False),
    ("Sponsorship in open source, measured", False),
])
def test_items_that_announce_themselves_as_ads(title, ad):
    item = Item(id="1", title=title, body="", url="https://feed.test/1")
    assert (sponsors.sponsored_item(item) is not None) == ad


# -- at ingest ------------------------------------------------------------------------


def episode_item(item_id="ep21", title="#21 - Sync engines in practice", url=EPISODE):
    return Item(id=item_id, title=title, body=INTRO * 3, url=url,
                published_at=FIXED_NOW - timedelta(hours=2))


def podcast_feed(store, items):
    Feed.items["https://podcast.test/feed.xml"] = items
    return library.add_source(store, "rss", {"url": "https://podcast.test/feed.xml"},
                              label="Sync podcast")


def test_no_sponsor_is_gathered_and_each_is_recorded(tmp_path, store, embedder, make_client):
    podcast_feed(store, [episode_item()])
    web = Web(**{EPISODE: httpx.Response(200, html=SHOW_NOTES),
                 "https://syncproject.test/": httpx.Response(200, html=page("Sync Project")),
                 "https://papers.test/": httpx.Response(200, html=page("CRDT paper"))})
    reply = json.dumps({**fields("An episode on sync engines"),
                        "children": [{"ref": 1, **fields("The sync project")},
                                     {"ref": 2, **fields("The CRDT paper")}]})
    client = make_client(replying(reply))
    report = ingest(config(tmp_path), store, client, embedder, web)
    rep = report.sources[0]
    assert report.status == "ok"
    sponsor_hosts = ("acmesync", "widgetcorp", "partnerlabs", "hosting.test", "shoes.test")
    assert not any(h in hit for hit in web.hits for h in sponsor_hosts), "never fetched"
    payload = json.loads(judge_requests(client)[0]["messages"][1]["content"])
    urls = [g["url"] for g in payload["gathered"]]
    assert urls and not any(h in u for u in urls for h in sponsor_hosts)
    kids = store.query("SELECT o.source_url FROM observation_links l "
                       "JOIN observations o ON o.id = l.child_id")
    assert {k["source_url"] for k in kids} == set(urls)
    # Recorded with reasons in the run's summary.
    # Counted: the sponsor links among those gathering would have followed (the
    # thank-you line and the read-out in the notes); the logos and the ad slot sit
    # outside the page's main content and were never candidates.
    assert rep.sponsor_links == 3
    summary = json.loads(store.query_one("SELECT summary FROM runs")["summary"])
    assert summary["sponsor_links"] == 3
    reasons = summary["sources"][0]["sponsor_reasons"]
    assert any("partnerlabs.test" in r and "for supporting" in r for r in reasons)


def test_an_item_that_is_an_ad_never_reaches_a_model(tmp_path, store, embedder, make_client):
    podcast_feed(store, [episode_item("ad1", title="[Sponsor] Acme Sync: try it free",
                                      url="https://podcast.test/sponsor-acme")])
    hn(store, [hn_item("77", title="Great deal on cables", link="https://amzn.to/abc")])
    client = make_client(replying(json.dumps(fields())))
    web = Web()
    report = ingest(config(tmp_path), store, client, embedder, web)
    assert report.status == "ok"
    assert client.fake.requests == [] and web.hits == []
    rows = seen(store)
    assert rows["ad1"]["outcome"] == rows["77"]["outcome"] == "sponsored"
    assert rows["ad1"]["llm_call_id"] is None
    assert [s.sponsored for s in report.sources] == [1, 1]
    summary = json.loads(store.query_one("SELECT summary FROM runs")["summary"])
    assert summary["sponsored"] == 2
    assert "title marks an ad" in summary["sources"][0]["sponsor_reasons"][0]
    assert "amzn.to" in summary["sources"][1]["sponsor_reasons"][0]


def test_a_spam_drop_by_the_screen_is_counted(tmp_path, store, embedder, make_client):
    hn(store, [hn_item()])
    drop = json.dumps({"pass": False, "reason": "spam: a vendor's landing page"})
    client = make_client(replying(json.dumps(fields()), screen_reply=drop))
    report = ingest(config(tmp_path), store, client, embedder)
    assert (report.sources[0].screened_out, report.sources[0].screened_spam) == (1, 1)
    assert len(screen_requests(client)) == 1 and judge_requests(client) == []


# -- override at ingest ------------------------------------------------------------------


def test_the_override_rate_is_in_the_run_summary(tmp_path, store, embedder, make_client):
    items = [hn_item(str(i), title=f"Item {i}: battery fade measured",
                     link=f"https://a{i}.test/post") for i in range(4)]
    hn(store, items)
    reasons = {"override": True, "override_reason": "an interview; the audio holds it"}
    replies = {
        "0": {**fields(q=0.9)},                                          # kept, no override
        "1": {**fields(q=0.9), **reasons},                               # unneeded
        "2": {**fields(q=0.4), "durability": 0.5, "opportunity": 0.8, **reasons},  # lifted
        "3": {**fields(q=0.05), **reasons},                              # refused: too thin
    }

    def handler(body):
        if is_screen(body):
            return chat_response(SCREEN_PASS)
        title = json.loads(body["messages"][1]["content"])["item"]["title"]
        return chat_response(json.dumps(replies[title.split()[1].rstrip(":")]))

    report = ingest(config(tmp_path, enabled=False), store, make_client(handler), embedder)
    rep = report.sources[0]
    assert (rep.rated, rep.override_set, rep.override_lifted, rep.override_refused) == \
        (4, 3, 1, 1)
    assert (rep.contributed, rep.gated) == (3, 1)
    summary = json.loads(store.query_one("SELECT summary FROM runs")["summary"])
    assert summary["overrides"] == {"rated": 4, "set": 3, "lifted": 1, "refused": 1,
                                    "rate": 0.75}
    assert seen(store)["3"]["outcome"] == "gated"
