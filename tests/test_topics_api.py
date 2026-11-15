"""The Topics tab's JSON (PLAN.md 2.2, 2.3): topics with their facts, one topic's themes
and sources, pausing a topic, and the scout's proposals as rows to tick."""

import json
import time

import httpx
import pytest

from kranto import library
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.map.snapshot import take_snapshot
from kranto.runtime import open_runtime
from kranto.sources import HTTP
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client
from .test_map import corpus  # noqa: F401 - fixture
from .test_scout import site
from .test_web import rt, web  # noqa: F401 - fixtures

EVIL = {"origin": "https://evil.example"}


def seen_rows(store, source_id, n, kept, cost=0.002):
    for i in range(n):
        call = store.insert("llm_calls", dict(
            purpose="judge", tier="judge", model="m", prompt_version="v", request="{}",
            status="ok", attempts=1, cost_usd=cost, created_at="2026-09-23T10:00:00Z"))
        store.insert("items_seen", dict(
            source_id=source_id, item_id=f"s{source_id}-{i}",
            outcome="contributed" if i < kept else "gated", llm_call_id=call,
            created_at="2026-09-23T10:00:00Z"))


def test_topics_list_counts_what_the_topic_reads(web, rt):  # noqa: F811
    [src] = [s.id for s in library.list_sources(rt.store)]
    seen_rows(rt.store, src, 7, kept=2)
    broad = library.add_source(rt.store, "rss", {"url": "https://ex.com/broad"}, label="Broad")
    seen_rows(rt.store, broad, 14, kept=0)
    library.add_source(rt.store, "rss", {"url": "https://ex.com/p"}, label="Proposed",
                       status="proposed")
    data = web.get("/api/topics").json()
    [t] = data["topics"]
    assert (t["name"], t["status"], t["sources"], t["observations"]) == ("energy", "active", 1, 4)
    # the fixture's four observations were consumed items too: (7 + 4) / 7 and (2 + 4) / 7
    assert t["items_per_day"] == 1.6 and t["kept_per_day"] == 0.9
    assert t["spend_month_usd"] == pytest.approx(7 * 0.002 + 4 * 0.001)
    assert t["themes"] == 0 and t["description"] == "solar and batteries in Africa"
    assert [(b["label"], b["items_per_day"]) for b in data["broad"]] == [("Broad", 2.0)]
    assert data["all"]["sources"] == 2 and data["all"]["items_per_day"] == 3.6
    assert data["all"]["observations"] == 4 and data["all"]["map"] is None


def test_pausing_a_topic_stops_its_sources_without_making_them_broad(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    [src] = [s.id for s in library.list_sources(rt.store)]
    other = library.add_source(rt.store, "rss", {"url": "https://ex.com/shared"}, label="Shared")
    library.link_topic_source(rt.store, t.id, other)
    second = library.add_topic(rt.store, rt.embedder, "storage", "home batteries")
    library.link_topic_source(rt.store, second, other)

    assert web.post(f"/api/topics/{t.id}/status", json={"status": "paused"},
                    headers=EVIL).status_code == 403
    r = web.post(f"/api/topics/{t.id}/status", json={"status": "paused"})
    assert r.status_code == 200 and r.json() == {"id": t.id, "status": "paused", "was": "active",
                                                 "changed": True}
    assert not web.post(f"/api/topics/{t.id}/status", json={"status": "paused"}).json()["changed"]
    assert [x.id for x in library.active_topics(rt.store)] == [second]
    # its own source waits; the one an active topic shares is still read
    assert library.paused_topic_sources(rt.store) == {src}
    listed = {x["name"]: x["status"] for x in web.get("/api/topics").json()["topics"]}
    assert listed == {"energy": "paused", "storage": "active"}
    page = web.get(f"/api/topics/{t.id}").json()
    assert page["status"] == "paused"
    assert {s["label"]: [x["name"] for x in s["topics"]] for s in page["source_rows"]} == {
        "Energy Feed": ["energy"], "Shared": ["energy", "storage"]}
    assert web.post(f"/api/topics/{t.id}/status", json={"status": "gone"}).status_code == 400
    assert web.post("/api/topics/999/status", json={"status": "active"}).status_code == 404
    assert web.post(f"/api/topics/{t.id}/status", json={"status": "active"}).json()["changed"]
    assert library.paused_topic_sources(rt.store) == set()
    assert web.get("/api/topics/999").status_code == 404


@pytest.fixture
def themed(corpus, embedder, tmp_path, make_client):  # noqa: F811
    solar = library.add_topic(corpus, embedder, "Solar power", "off-grid solar in Kenya")
    bread = library.add_topic(corpus, embedder, "Baking", "sourdough at home")
    by_label = {s.label: s.id for s in library.list_sources(corpus)}
    for label in ("solar-a", "solar-b"):
        library.link_topic_source(corpus, solar, by_label[label])
    library.link_topic_source(corpus, bread, by_label["bread-a"])
    take_snapshot(corpus, embedder, None)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    runtime = open_runtime(cfg, store=corpus, embedder=embedder,
                           llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(runtime)) as client:
        yield client, solar, bread


def test_a_topics_themes_are_the_clusters_its_sources_fed(themed):
    client, solar, bread = themed
    page = client.get(f"/api/topics/{solar}").json()
    assert page["themes"] == len(page["themes_list"]) >= 1
    for c in page["themes_list"]:
        assert c["topic_share"] >= 0.2 and c["topic_mix"]["Solar power"] > 0
        assert "Baking" not in c["topic_mix"] or c["topic_mix"]["Solar power"] > 0
        for key in ("lineage_id", "label", "size", "movement", "rising", "trajectory",
                    "cross_source", "grade", "synthesis", "keywords"):
            assert key in c, key
    words = " ".join(" ".join(c["keywords"]) for c in page["themes_list"])
    assert "solar" in words or "kenya" in words or "battery" in words
    assert page["snapshot"]["id"] and len(page["rising_now"]) <= 3
    assert page["observations"] == 25 and page["sources"] == 2
    listed = {t["name"]: t["themes"] for t in client.get("/api/topics").json()["topics"]}
    assert listed["Solar power"] == page["themes"] and listed["Baking"] >= 1
    baking = client.get(f"/api/topics/{bread}").json()
    assert not {c["lineage_id"] for c in baking["themes_list"]} & {
        c["lineage_id"] for c in page["themes_list"] if c["topic_mix"].get("Baking", 0) == 0}


@pytest.fixture
def scouting(tmp_path, store, embedder, make_client):
    proposals = {"sources": [
        {"kind": "rss", "value": "https://ex.com/good", "why": "on topic"},
        {"kind": "rss", "value": "https://ex.com/offtopic", "why": "adjacent"},
        {"kind": "rss", "value": "https://ex.com/missing", "why": "hallucinated"},
        {"kind": "hackernews", "value": "sourdough", "why": "same pattern", "role": "wildcard"},
    ]}
    client = make_client(lambda body: chat_response(json.dumps(proposals)))

    def hn(request):
        if request.url.host == "hn.algolia.com":
            return httpx.Response(200, json={"hits": [
                {"objectID": "1", "title": "sourdough starter", "url": "https://ex.com/s",
                 "created_at": "2026-09-22T10:00:00Z", "story_text": None}]})
        return site(request)

    http = HTTP(transport=httpx.MockTransport(hn), resolver=lambda h: ["93.184.216.34"])
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt_ = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http)
    with web_client(create_app(rt_)) as web_:
        yield rt_, web_


def scouted(web_, topic_id: int, timeout: float = 30) -> dict:
    """The scout runs in the background (the owner's rule: no request waits on a model);
    poll its job until it is done, as the page does."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = web_.get(f"/api/topics/{topic_id}/scout").json()["job"]
        if job["state"] != "running":
            assert job["state"] == "done", job
            return job["result"]
        time.sleep(0.05)
    raise AssertionError("the scout did not finish")


def test_adding_a_topic_with_scout_returns_rows_to_tick(scouting):
    rt_, web_ = scouting
    r = web_.post("/api/topics", json={"name": "solar", "description":
                                       "solar microgrid battery storage", "scout": True})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["proposals"] == [] and created["job"]["state"] in ("running", "done")
    body = {**scouted(web_, created["id"]), "id": created["id"]}
    assert body["message"].startswith("Scout proposed 4 sources") and body["invalid"] == 1
    rows = {p["id"]: p for p in body["proposals"]}
    assert len(rows) == 3
    line = rt_.cfg.ingest.prefilter_min_similarity
    for p in rows.values():
        assert p["review"] == "proposed" and p["validation"]["items"] >= 1
        sim = p["validation"]["median_similarity"]
        assert p["pretick"] == (p["role"] == "core" and sim >= line)
    wild = next(p for p in rows.values() if p["role"] == "wildcard")
    assert not wild["pretick"] and wild["proposed_for"] == "solar" and wild["topics"] == []
    # ticking one approves it for the topic, as Settings › Sources' Approve does
    core = next(p for p in rows.values() if p["role"] == "core")
    assert web_.post("/api/sources", json={"id": core["id"], "status": "approved",
                                           "topic": body["id"]}).status_code == 200
    page = web_.get(f"/api/topics/{body['id']}").json()
    by_id = {s["id"]: s for s in page["source_rows"]}
    assert by_id[core["id"]]["review"] == "approved" and page["sources"] == 1
    assert wild["id"] in by_id, "the topic's page lists its wildcards too"
    # scout more: the same sources come back, nothing is duplicated
    r = web_.post(f"/api/topics/{body['id']}/scout", json={})
    assert r.status_code == 202 and r.json()["job"]["key"] == f"scout:{body['id']}"
    again = scouted(web_, body["id"])
    rows_ids = set(rows)
    assert {p["id"] for p in again["proposals"]} == rows_ids
    assert len(library.list_sources(rt_.store)) == len(rows_ids) + 1      # + the invalid one
