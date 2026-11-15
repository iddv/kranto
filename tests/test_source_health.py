"""Source health, the sources API, the plain-form catalog, and the scout speaking in presets
(sections 2, 4 and 5; phase A)."""

import json
import secrets
from dataclasses import replace

import httpx
import pytest

from kranto import library, source_health
from kranto.config import BudgetConfig, Config, IngestConfig, LookConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.scout import SCOUT_PRESETS, Proposal, parse_proposals, presets_text, scout_topic
from kranto.sources import HTTP, SourceError
from kranto.stored.sources import Validation
from kranto.tick import run_ingest
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client


def rss(*titles, date="Tue, 22 Sep 2026 10:00:00 GMT"):
    items = "".join(f"<item><title>{t}</title><link>https://ex.com/{i}</link><guid>{t}</guid>"
                    f"<description>{t} details</description><pubDate>{date}</pubDate></item>"
                    for i, t in enumerate(titles))
    return f"<rss><channel><title>Feed</title>{items}</channel></rss>".encode()


class Web:
    def __init__(self):
        self.token_in_error = "ghp_" + secrets.token_hex(18)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "rss.arxiv.org":
            return httpx.Response(200, content=rss("CRDT sync paper", "Battery chemistry"))
        if path == "/good":
            return httpx.Response(200, content=rss(*(f"solar microgrid {i}" for i in range(7))))
        if path == "/limited":
            return httpx.Response(429)
        if path == "/gone":
            return httpx.Response(404)
        if request.url.host == "bootstrapped.substack.com":
            return httpx.Response(200, content=rss("A newsletter post"))
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": [
                {"objectID": "1", "title": "Show HN: a CRDT", "created_at_i": 1790000000}]})
        return httpx.Response(404)


@pytest.fixture
def site():
    return Web()


@pytest.fixture
def rt(tmp_path, store, embedder, make_client, site):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(fetch_full_text=False), map=MapConfig(),
                 look=LookConfig(enabled=False))
    client = make_client(lambda body: chat_response(json.dumps({
        "kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.9,
        "durability": 0.9, "opportunity": 0.9, "override": False, "tags": []})))
    http = HTTP(transport=httpx.MockTransport(site), resolver=lambda h: ["93.184.216.34"])
    runtime = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http)
    library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    return runtime


@pytest.fixture
def web(rt):
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client


def ingest(rt):
    return run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                      connections=rt.connections, lock_path=rt.cfg.root / "ingest.lock")


def test_every_fetch_is_a_row_and_the_status_follows_it(rt, site):
    store = rt.store
    good = library.add_source(store, "rss", {"url": "https://ex.com/good"}, label="Good")
    paced = library.add_source(store, "rss", {"url": "https://ex.com/limited"}, label="Paced")
    gone = library.add_source(store, "rss", {"url": "https://ex.com/gone"}, label="Gone")
    reddit = library.add_source(store, "reddit", {"subreddit": "solar"}, label="r/solar")
    proposed = library.add_source(store, "rss", {"url": "https://ex.com/p"}, label="P",
                                  status="proposed", validation={"status": "valid",
                                                                 "median_similarity": 0.6,
                                                                 "items": 5, "recent": 4})
    rows = {s["id"]: s for s in source_health.list_sources(store, rt.cfg)}
    assert rows[good]["status"] == "new" and rows[proposed]["status"] == "proposed"
    assert "sim 0.60" in rows[proposed]["detail"]
    assert rows[reddit]["note"] == "Reddit's feeds stop on 13 Nov 2026."

    report = ingest(rt)
    # Paced is not a failure, and one 404 is not yet a persistent one (tests/test_pacing.py).
    assert report.status == "ok"
    fetches = store.query("SELECT source_id, state, fetched, new, error, trigger FROM "
                          "source_fetches ORDER BY id")
    by_source = {r["source_id"]: r for r in fetches}
    assert by_source[good]["state"] == "ok" and by_source[good]["fetched"] == 7
    assert by_source[good]["new"] == 7 and by_source[good]["trigger"] == "run"
    assert by_source[paced]["state"] == "paced" and "HTTP 429" in by_source[paced]["error"]
    assert by_source[gone]["state"] == "failing" and "HTTP 404" in by_source[gone]["error"]
    assert proposed not in by_source
    rows = {s["id"]: s for s in source_health.list_sources(store, rt.cfg)}
    assert rows[good]["status"] == "ok" and rows[good]["detail"] == "7 fetched, 7 new"
    assert rows[good]["items_7d"] == 7 and rows[good]["items_per_day"] == 1.0
    assert rows[good]["kept_30d"] >= 1 and rows[good]["last_fetch"]
    assert rows[paced]["status"] == "paced" and rows[gone]["status"] == "failing"
    assert rows[gone]["last_error"].endswith("HTTP 404")
    assert rows[good]["site"] == "web" and rows[reddit]["site_name"] == "Reddit"


def test_a_fetch_error_is_scrubbed_before_it_is_stored(rt, site, monkeypatch):
    from kranto.sources.rss import RSSSource

    def leaky(self):
        raise SourceError(f"https://ex.com/x?access_token={site.token_in_error}: HTTP 500")

    monkeypatch.setattr(RSSSource, "fetch", leaky)
    library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    report = ingest(rt)
    assert site.token_in_error not in report.to_json()
    stored = json.dumps([dict(r) for r in rt.store.query("SELECT * FROM source_fetches")])
    assert site.token_in_error not in stored and "[secret]" in stored


def test_sources_from_before_source_fetches_read_their_last_run(rt):
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    rt.store.insert("runs", {"run_uuid": "old", "kind": "ingest", "status": "ok",
                             "started_at": "2026-09-24T09:00:00Z",
                             "finished_at": "2026-09-24T09:01:00Z", "error": None,
                             "summary": json.dumps({"sources": [{"source_id": src, "fetched": 9,
                                                                 "new": 2}]})})
    [row] = source_health.list_sources(rt.store, rt.cfg)
    assert row["status"] == "ok" and row["detail"] == "9 fetched, 2 new"
    assert row["last_fetch"] == "2026-09-24T09:01:00Z"


def test_catalog_preview_add_and_the_source_page(web, rt):
    catalog = web.get("/api/catalog").json()
    assert catalog["topics"][0]["name"] == "solar"
    keys = [s["key"] for p in catalog["providers"] for s in p["presets"]]
    assert "arxiv.category" in keys and {"reddit.sub", "reddit.search"} <= set(keys)

    body = {"preset": "arxiv.category", "fields": {"category": "cs.DC"}, "topic": 1}
    preview = web.post("/api/sources/preview", json=body).json()
    assert preview["items"] == 2 and preview["kind"] == "rss"
    assert preview["label"] == "arXiv cs.DC" and len(preview["newest"]) == 2
    assert preview["median_similarity"] is not None and preview["prefilter"] == 0.5
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM sources")["n"] == 0, "nothing saved"

    added = web.post("/api/sources", json=body).json()
    assert added["status"] == "approved"
    [row] = web.get("/api/sources").json()["sources"]
    assert row["topics"] == [{"id": 1, "name": "solar", "kind": "user"}] and row["site"] == "arxiv"
    assert row["preset"] == "arxiv.category"
    detail = web.get(f"/api/sources/{added['id']}").json()
    assert detail["how"]["request"] == "https://rss.arxiv.org/rss/cs.DC"
    assert detail["fetches"] == [] and detail["retention_days"] == 90

    now = web.post(f"/api/sources/{added['id']}/fetch").json()
    assert now == {"state": "ok", "fetched": 2, "new": 2, "error": None}
    assert web.get(f"/api/sources/{added['id']}").json()["fetches"][0]["trigger"] == "manual"
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM items_seen")["n"] == 0, \
        "fetch now consumes nothing"

    kept = web.post(f"/api/sources/{added['id']}/retention", json={"days": 30}).json()
    assert kept["effective_days"] == 30
    assert web.post(f"/api/sources/{added['id']}/retention",
                    json={"days": None}).json()["effective_days"] == 90
    assert web.post(f"/api/sources/{added['id']}/retention",
                    json={"days": "lots"}).status_code == 400

    assert web.post(f"/api/sources/{added['id']}/status",
                    json={"status": "retired"}).json()["status"] == "retired"
    assert web.post(f"/api/sources/{added['id']}/status",
                    json={"status": "deleted"}).status_code == 400
    assert web.get("/api/sources/999").status_code == 404


def test_errors_are_plain_and_refuse_nothing_silently(web):
    bad = web.post("/api/sources/preview", json={"preset": "github.releases",
                                                 "fields": {"repo": "nope"}})
    assert bad.status_code == 400 and "GitHub repository" in bad.json()["error"]
    failing = web.post("/api/sources/preview", json={"preset": "web.feed",
                                                     "fields": {"url": "https://ex.com/gone"}})
    assert failing.status_code == 422 and failing.json()["state"] == "failing"
    login = web.post("/api/sources/preview", json={"preset": "mastodon.home",
                                                   "fields": {"instance": "mastodon.social"}})
    assert login.status_code == 422 and login.json()["state"] == "needs_login"
    assert web.post("/api/sources", content=b"[]",
                    headers={"content-type": "application/json"}).status_code == 400


def test_newsletters_are_kept_30_days(web, rt):
    added = web.post("/api/sources", json={"preset": "substack.publication",
                                           "fields": {"publication": "bootstrapped"}}).json()
    from kranto.retention import retention_days

    assert retention_days(rt.store, rt.cfg.retention)[added["id"]] == 30


def test_reviewing_a_proposal_approves_it_on_the_same_endpoint(web, rt):
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good",
                             origin="scout", status="proposed",
                             validation={"preset": "web.feed",
                                         "fields": {"url": "https://ex.com/good"}})
    r = web.post("/api/sources", json={"id": src, "status": "approved", "topic": 1}).json()
    assert r == {"id": src, "status": "approved"}
    assert [t.id for t in library.topics_for_source(rt.store, src)] == [1]


def test_topics_api_adds_and_counts(web):
    r = web.post("/api/topics", json={"name": "fisheries", "description": "small boats"})
    assert r.status_code == 200 and r.json()["message"] is None
    assert web.post("/api/topics", json={"name": ""}).status_code == 400
    topics = web.get("/api/sources").json()["topics"]
    assert [t["name"] for t in topics] == ["solar", "fisheries"]
    assert web.post("/api/topics/99/scout", json={}).status_code == 404


def test_the_plain_source_form_adds_from_the_catalog(web, rt):
    done = web.post("/sources", data={"preset": "arxiv.category", "field_category": "cs.DC",
                                      "topic": "1"}, follow_redirects=False)
    assert done.status_code == 303 and "Added+arXiv+cs.DC" in done.headers["location"]
    bad = web.post("/sources", data={"preset": "arxiv.category", "field_category": "?"},
                   follow_redirects=False)
    assert "Could+not+add" in bad.headers["location"]
    # The older single-value form still works.
    legacy = web.post("/sources", data={"kind": "rss", "value": "https://ex.com/good"},
                      follow_redirects=False)
    assert "Added" in legacy.headers["location"]


# -- the scout speaks in presets ------------------------------------------------------------


def test_scout_vocabulary_is_public_presets_only():
    assert SCOUT_PRESETS and all(p.access == "public" and p.available
                                 for p in SCOUT_PRESETS.values())
    text = presets_text()
    assert "mastodon.hashtag" in text and "arxiv.search" in text
    assert "mastodon.home" not in text and "reddit" not in text.lower()


def test_parse_preset_proposals():
    text = json.dumps({"sources": [
        {"preset": "mastodon.hashtag", "fields": {"instance": "hachyderm.io", "tag": "crdt"},
         "why": "practitioners", "replaces": "r/localfirst"},
        {"preset": "mastodon.hashtag", "fields": {"instance": "hachyderm.io"}},  # a field short
        {"preset": "mastodon.home", "fields": {"instance": "x.social"}},        # login: never
        {"preset": "reddit.subreddit", "fields": {"subreddit": "solar"}},       # no Reddit
        {"kind": "reddit", "value": "solar"},
        {"preset": "hackernews.front", "fields": {}, "role": "wildcard"},
    ]})
    proposals = parse_proposals(text)
    assert [(p.preset, p.fields) for p in proposals] == [
        ("mastodon.hashtag", {"instance": "hachyderm.io", "tag": "crdt"}),
        ("hackernews.front", {})]
    assert proposals[0].replaces == "r/localfirst" and proposals[1].role == "wildcard"


def test_scout_proposes_replacements_for_reddit_and_records_presets(rt, make_client, site):
    store = rt.store
    reddit = library.add_source(store, "reddit", {"subreddit": "solar"}, label="r/solar")
    library.link_topic_source(store, 1, reddit)
    reply = {"sources": [
        {"preset": "web.feed", "fields": {"url": "https://ex.com/good"}, "why": "on topic",
         "replaces": "r/solar"},
        {"preset": "arxiv.category", "fields": {"category": "physics.soc-ph"}, "why": "papers"},
        {"kind": "hackernews", "value": "microgrid", "why": "older form"},
    ]}
    client = make_client(lambda body: chat_response(json.dumps(reply)))
    [topic] = library.active_topics(store)
    results = scout_topic(store, client, rt.embedder, rt.http, topic)
    prompt = client.fake.requests[0]["messages"][0]["content"]
    assert "r/solar" in prompt and "13 Nov 2026" in prompt and "mastodon.hashtag" in prompt
    by_label = {r.label: r for r in results}
    good = next(s for s in library.list_sources(store) if s.label == "ex.com")
    assert good.validation.preset == "web.feed" and good.validation.replaces == "r/solar"
    assert good.validation.fields == {"url": "https://ex.com/good"}
    assert by_label["arXiv physics.soc-ph"].status == "proposed"
    hn = next(s for s in library.list_sources(store) if s.kind == "hackernews")
    assert hn.validation.preset == "hackernews.search"
    row = next(s for s in source_health.list_sources(store, rt.cfg) if s["id"] == good.id)
    assert row["replaces"] == "r/solar" and row["status"] == "proposed"


def test_a_preset_proposal_that_cannot_build_is_invalid(rt, embedder):
    from kranto.scout import validate

    [topic] = library.active_topics(rt.store)
    v, label, kind, params = validate(
        Proposal("preset", "x", "", preset="github.releases", fields={"repo": "?"}),
        rt.http, embedder, topic)
    assert v.status == "invalid" and params is None


def test_a_proposal_tested_without_a_topic_has_no_similarity_and_still_reads():
    # A friend's topic page answered 500: a proposal's validation held median_similarity None.
    from types import SimpleNamespace

    row = SimpleNamespace(status="proposed", validation=Validation.parse(
        '{"status": "valid", "median_similarity": null, "items": 12, "recent": null}'))
    assert source_health._status(row, None) == ("proposed", "12 items, 0 in 30 days")
    row.validation = replace(row.validation, median_similarity=0.4)
    assert source_health._status(row, None) == ("proposed", "sim 0.40 · 12 items, 0 in 30 days")
