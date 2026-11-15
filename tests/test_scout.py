import json
from datetime import UTC, datetime

import httpx

from kranto import library
from kranto.scout import Proposal, parse_proposals, scout_topic, validate
from kranto.sources import HTTP

from .conftest import chat_response

NOW = datetime(2026, 9, 24, tzinfo=UTC)


def feed(*titles, date="Tue, 22 Sep 2026 10:00:00 GMT"):
    items = "".join(
        f"<item><title>{t}</title><link>https://ex.com/{i}</link><guid>{i}</guid>"
        f"<description>{t} details</description><pubDate>{date}</pubDate></item>"
        for i, t in enumerate(titles)
    )
    return f"<rss><channel><title>Feed</title>{items}</channel></rss>".encode()


ROUTES = {
    "/good": feed("solar microgrid battery storage", "solar microgrid battery prices"),
    "/offtopic": feed("knitting wool patterns", "sourdough bread starter"),
    "/empty": feed(),
}


def site(request):
    if request.url.path == "/missing":
        return httpx.Response(404)
    if request.url.path == "/limited":
        return httpx.Response(429)
    if request.url.path in ROUTES:
        return httpx.Response(200, content=ROUTES[request.url.path])
    return httpx.Response(404)


def http():
    return HTTP(transport=httpx.MockTransport(site), resolver=lambda h: ["93.184.216.34"])


def test_parse_proposals_filters_and_dedupes():
    text = json.dumps({"sources": [
        {"kind": "rss", "value": "https://ex.com/good", "why": "w"},
        {"kind": "RSS", "value": "https://EX.com/good", "why": "dupe"},
        {"kind": "twitter", "value": "@x"},
        {"kind": "reddit", "value": ""},
        "junk",
        {"kind": "hackernews", "value": "microgrid"},
    ]})
    proposals = parse_proposals(f"```json\n{text}\n```")
    assert [(p.kind, p.value) for p in proposals] == [
        ("rss", "https://ex.com/good"), ("hackernews", "microgrid")
    ]
    assert parse_proposals("sorry, I cannot help") == []


def test_validation_statuses(store, embedder):
    topic = library.Topic(1, "solar", "solar microgrid battery",
                          embedder.embed_query("solar microgrid battery"))
    h = http()

    def check(url):
        return validate(Proposal("rss", url, ""), h, embedder, topic, now=NOW)[0]

    good = check("https://ex.com/good")
    assert good.status == "valid"
    assert good.items == 2 and good.recent == 2
    assert good.median_similarity > check("https://ex.com/offtopic").median_similarity
    assert check("https://ex.com/missing").status == "invalid"
    assert check("https://ex.com/empty").status == "invalid"
    assert check("https://ex.com/limited").status == "unverified"
    bad_name = validate(Proposal("reddit", "not a valid name!", ""), h, embedder, topic)[0]
    assert bad_name.status == "invalid"


def test_reddit_and_lobsters_are_never_proposed_even_as_a_feed_url(embedder):
    topic = library.Topic(1, "solar", "solar microgrid battery",
                          embedder.embed_query("solar microgrid battery"))
    h = http()
    for proposal in (
        Proposal("rss", "https://www.reddit.com/r/solar/.rss", ""),
        Proposal("rss", "https://lobste.rs/t/hardware.rss", ""),
        Proposal("preset", "web.feed https://old.reddit.com/r/solar/.rss", "",
                 preset="web.feed", fields={"url": "https://old.reddit.com/r/solar/.rss"}),
        Proposal("reddit", "solar", ""),
    ):
        validation, _, _, params = validate(proposal, h, embedder, topic, now=NOW)
        assert validation.status == "invalid" and params is None
        assert "does not propose" in validation.error


def test_scout_records_proposals_and_never_offers_invalid_ones(store, embedder, make_client):
    proposals = {"sources": [
        {"kind": "rss", "value": "https://ex.com/good", "why": "on topic"},
        {"kind": "rss", "value": "https://ex.com/offtopic", "why": "adjacent"},
        {"kind": "rss", "value": "https://ex.com/missing", "why": "hallucinated"},
    ]}
    client = make_client(lambda body: chat_response(json.dumps(proposals)))
    topic_id = library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    [topic] = library.active_topics(store)

    results = scout_topic(store, client, embedder, http(), topic,
                          auto_approve_min_similarity=0.3, now=NOW)
    by_value = {r.proposal.value: r for r in results}
    assert by_value["https://ex.com/good"].status == "approved"
    assert by_value["https://ex.com/offtopic"].status == "proposed"
    assert by_value["https://ex.com/missing"].status == "invalid"

    assert client.fake.requests[0]["model"] == "reason-model"
    statuses = {s.id: s.status for s in library.list_sources(store)}
    assert sorted(statuses.values()) == ["approved", "invalid", "proposed"]
    linked = {s.id for s in [*library.list_sources(store)]
              if topic_id in {t.id for t in library.topics_for_source(store, s.id)}}
    invalid_id = by_value["https://ex.com/missing"].source_id
    assert invalid_id not in linked
    good = next(s for s in library.list_sources(store) if s.status == "approved")
    assert good.origin == "scout" and good.validation.why == "on topic"

    # Scouting again does not duplicate sources.
    scout_topic(store, client, embedder, http(), topic, now=NOW)
    assert len(library.list_sources(store)) == 3


def test_scout_that_returns_nothing_is_an_error_not_a_silent_success(
        store, embedder, make_client, tmp_path):
    """#38: the reasoning model spent all of max_tokens, content was null, and
    `afk topics add` exited 0 having added nothing."""
    from types import SimpleNamespace

    import pytest

    from kranto import cli
    from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig

    from .conftest import llm_config

    topic_id = library.add_topic(store, embedder, "fisheries", "small-scale fisheries")

    def runtime(handler):
        client = make_client(handler)
        cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                     ingest=IngestConfig(), map=MapConfig())
        return SimpleNamespace(store=store, llm=client, embedder=embedder,
                               http=HTTP(), cfg=cfg), client

    rt, client = runtime(lambda body: chat_response(None, completion=8000,
                                                    finish_reason="length"))
    with pytest.raises(cli.CLIError, match="scouting failed: reply cut off"):
        cli._scout(rt, topic_id, approve=False)
    assert client.fake.requests[0]["max_tokens"] == 8000

    rt, _ = runtime(lambda body: chat_response(json.dumps({"sources": []})))
    with pytest.raises(cli.CLIError, match="no usable proposals"):
        cli._scout(rt, topic_id, approve=False)
    assert store.query_one("SELECT COUNT(*) AS n FROM sources")["n"] == 0
