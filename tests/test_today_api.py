"""Today (UI-v4.md 2.2): what was kept since the last visit, per topic, in one call; the
last-visit marker; "new" on the observation list; mute; spend by topic. No model call."""

from datetime import timedelta

import httpx
import pytest

from kranto import library, source_health
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.sources import HTTP, Item
from kranto.store import iso
from kranto.web.app import create_app

from .conftest import FIXED_NOW, chat_response, llm_config, web_client

NOW = FIXED_NOW
MARKER = NOW - timedelta(hours=10)
TOPICS = [("energy", "solar and batteries in Africa", "Energy Feed"),
          ("local-first", "CRDT sync engines and offline apps", "Sync Feed"),
          ("tools", "developer tools for coding agents", "Agent Feed")]


def observe(rt, src, n, signal, hours_ago, cost=0.001):
    store, embedder = rt.store, rt.embedder
    summary = f"observation {src}-{n} at signal {signal}"
    call = store.insert("llm_calls", dict(
        purpose="judge", tier="judge", model="judge-model", prompt_version="judge-x",
        request="{}", response="{}", status="ok", attempts=1, cost_usd=cost,
        created_at=iso(NOW - timedelta(hours=hours_ago))))
    return library.record_observation(
        store, source_id=src, item=Item(id=f"i{src}-{n}", title=f"t{src}-{n}", body=summary,
                                        url=f"https://ex.com/{src}/{n}"),
        fields={"kind": "beat", "summary": summary, "why_it_matters": "because",
                "content_quality": 1.0, "durability": 1.0, "opportunity": signal,
                "signal": signal, "override": False, "override_reason": None, "tags": []},
        embedding=embedder.embed_documents([summary])[0], embedding_model=embedder.model_name,
        llm_call_id=call, prompt_version="judge-x", run_uuid="r", admitted_by="topic",
        topic_similarity=0.6, now=NOW - timedelta(hours=hours_ago))


@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    client = make_client(lambda body: chat_response('{"sources": []}'))
    http = HTTP(transport=httpx.MockTransport(lambda r: httpx.Response(404)),
                resolver=lambda h: ["93.184.216.34"])
    runtime = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http)
    runtime.ids = {}
    for name, desc, label in TOPICS:
        t = library.add_topic(store, embedder, name, desc)
        s = library.add_source(store, "rss", {"url": f"https://ex.com/{name}"}, label=label)
        library.link_topic_source(store, t, s)
        runtime.ids[name] = (t, s)
    e, lf, tools = (runtime.ids[n][1] for n, _, _ in TOPICS)
    # energy: five new (signals .1-.9), two from before the marker with the highest signals
    for n, sig in enumerate((0.1, 0.9, 0.5, 0.7, 0.3)):
        observe(runtime, e, n, sig, hours_ago=2 + n)
    observe(runtime, e, 10, 0.99, hours_ago=20)
    observe(runtime, e, 11, 0.98, hours_ago=30)
    # local-first: one new; tools: only old ones
    observe(runtime, lf, 0, 0.4, hours_ago=1)
    observe(runtime, tools, 0, 0.8, hours_ago=50)
    store.set_setting("seen_at", iso(MARKER))
    return runtime


@pytest.fixture
def web(rt):
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client


def calls(store):
    return store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"]


def test_today_counts_and_tops_three_topics_since_the_marker(web, rt):
    before = calls(rt.store)
    d = web.get("/api/today").json()
    assert d["since"] == iso(MARKER) and d["seen_at"] == iso(MARKER)
    by = {t["name"]: t for t in d["topics"]}
    assert set(by) == {"energy", "local-first", "tools"}
    assert by["energy"]["new_kept"] == 5
    assert [o["signal"] for o in by["energy"]["top"]] == [0.9, 0.7, 0.5], \
        "the top 3 by signal, and nothing from before the marker (0.99, 0.98)"
    assert all(o["created_at"] > iso(MARKER) for o in by["energy"]["top"])
    assert by["local-first"]["new_kept"] == 1 and len(by["local-first"]["top"]) == 1
    assert by["tools"]["new_kept"] == 0 and by["tools"]["top"] == []
    assert d["new_kept"] == 6
    assert d["ingest"]["observations"] == 9 and d["ingest"]["topics"] == 3
    assert d["ingest"]["judge_calls_24h"] == 7
    assert calls(rt.store) == before, "Today makes no model call"


def test_today_since_an_explicit_time_and_its_guard(web):
    d = web.get("/api/today", params={"since": iso(NOW - timedelta(hours=3, minutes=30))}).json()
    assert {t["name"]: t["new_kept"] for t in d["topics"]} == \
        {"energy": 2, "local-first": 1, "tools": 0}
    assert web.get("/api/today?since=yesterday").status_code == 400


def test_today_lists_proposed_sources_per_topic(web, rt):
    t, _ = rt.ids["tools"]
    s = library.add_source(rt.store, "rss", {"url": "https://ex.com/p"}, label="Proposed one",
                           status="proposed")
    library.link_topic_source(rt.store, t, s)
    d = web.get("/api/today").json()
    by = {x["name"]: x for x in d["topics"]}
    assert by["tools"]["proposed"] == 1 and d["proposed"] == 1
    assert by["energy"]["proposed"] == 0


def test_seen_round_trips_and_undoes(web, rt):
    assert web.get("/api/seen").json() == {"seen_at": iso(MARKER), "since": iso(MARKER)}
    r = web.post("/api/seen", json={}).json()
    assert r["previous"] == iso(MARKER) and r["seen_at"] >= iso(NOW)
    assert web.get("/api/today").json()["new_kept"] == 0, "Mark all seen empties Today"
    back = web.post("/api/seen", json={"at": r["previous"]}).json()
    assert back["seen_at"] == iso(MARKER)
    assert web.get("/api/today").json()["new_kept"] == 6
    assert web.post("/api/seen", json={"at": iso(NOW + timedelta(days=1))}).status_code == 400
    assert web.post("/api/seen", json={"at": "soon"}).status_code == 400


def test_without_a_marker_new_is_the_last_24_hours(web, rt):
    rt.store.delete_setting("seen_at")
    d = web.get("/api/seen").json()
    assert d["seen_at"] is None and d["since"] < iso(NOW - timedelta(hours=23))
    by = {t["name"]: t["new_kept"] for t in web.get("/api/today").json()["topics"]}
    assert by == {"energy": 6, "local-first": 1, "tools": 0}


def test_reading_today_does_not_move_the_marker(web, rt):
    web.get("/api/today")
    web.get("/api/observations")
    assert rt.store.get_setting("seen_at") == iso(MARKER)


def test_observation_list_marks_new_only_after_the_marker(web, rt):
    t, _ = rt.ids["energy"]
    d = web.get(f"/api/observations?topic={t}&limit=100").json()
    assert d["seen_at"] == iso(MARKER) and d["new_total"] == 5
    for o in d["results"]:
        assert o["new"] is (o["created_at"] > iso(MARKER))
        assert "grade" in o
    assert sum(o["new"] for o in d["results"]) == 5 and len(d["results"]) == 7
    only = web.get(f"/api/observations?topic={t}&since=last").json()
    assert only["total"] == 5 and all(o["new"] for o in only["results"])
    assert web.get("/api/observations?since=never").status_code == 400


def test_mute_round_trips_and_shows_on_the_source_row(web, rt):
    _, s = rt.ids["energy"]
    r = web.post(f"/api/sources/{s}/mute", json={"days": 7}).json()
    assert r["label"] == "Energy Feed" and r["muted_until"] > iso(NOW + timedelta(days=6))
    row = next(x for x in web.get("/api/sources").json()["sources"] if x["id"] == s)
    assert row["mute"]["muted_until"] == r["muted_until"]
    assert row["kept_30d"] == 7 and row["yield_per_day"] == round(7 / 30, 2)
    less = web.post(f"/api/sources/{s}/mute", json={"days": "less"}).json()
    assert less["read_less"] is True and less["muted_until"] is None
    undo = web.post(f"/api/sources/{s}/mute", json={"days": None}).json()
    assert undo == {"id": s, "label": "Energy Feed", "muted_until": None, "read_less": False}
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM source_mutes")["n"] == 3, \
        "append-only: an undo is one more row"
    assert web.post(f"/api/sources/{s}/mute", json={"days": 0}).status_code == 400
    assert web.post(f"/api/sources/{s}/mute", json={"days": "loud"}).status_code == 400
    assert web.post("/api/sources/999/mute", json={"days": 7}).status_code == 404


def test_an_expired_mute_is_no_mute(rt):
    _, s = rt.ids["energy"]
    source_health.set_mute(rt.store, s, days=1, now=NOW - timedelta(days=3))
    assert source_health.mutes(rt.store, now=NOW) == {}
    assert s in source_health.mutes(rt.store, now=NOW - timedelta(days=2, hours=12))


def test_source_mutes_is_an_additive_append_only_table(rt):
    import sqlite3

    assert 20 in rt.store.applied_migrations()
    _, s = rt.ids["energy"]
    source_health.set_mute(rt.store, s, days=7)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        rt.store.query("UPDATE source_mutes SET read_less = 1")
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM sources")["n"] == 3


def test_spend_by_topic_adds_up_to_the_month(web, rt):
    rt.store.insert("llm_calls", dict(
        purpose="card", tier="reason", model="m", prompt_version="card-x", request="{}",
        response="{}", status="ok", attempts=1, cost_usd=0.25, created_at=iso(NOW)))
    d = web.get("/api/spend/topics").json()
    parts = sum(t["usd"] for t in d["topics"]) + d["broad"]["usd"] + \
        sum(o["usd"] for o in d["other"]) + d["compacted_usd"]
    assert abs(parts - d["total_usd"]) < 1e-6
    by = {t["name"]: t for t in d["topics"]}
    assert d["month"] == "2026-09", "every fixture call is in FIXED_NOW's month"
    assert by["energy"]["calls"] == 7 and by["energy"]["usd"] == pytest.approx(0.007)
    assert {o["purpose"] for o in d["other"]} == {"card"}


def test_today_lists_project_topics_apart(web, rt):
    """A project topic (migration 23) is under ``project_topics``, not ``topics``, and the
    totals stay the owner's topics'."""
    ref = "project:p1a2b3c4d"
    tid = library.add_topic(rt.store, rt.embedder, "Receipts", "receipt scanning",
                            kind="project", ref=ref)
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/receipts"},
                             label="Receipts Feed")
    library.link_topic_source(rt.store, tid, src)
    before = web.get("/api/today").json()
    assert before["project_topics"][0]["new_kept"] == 0
    observe(rt, src, 0, 0.6, hours_ago=1)
    data = web.get("/api/today").json()
    assert [t["name"] for t in data["topics"]] == ["energy", "local-first", "tools"]
    assert all((t["kind"], t["ref"]) == ("user", None) for t in data["topics"])
    [p] = data["project_topics"]
    assert (p["id"], p["name"], p["kind"], p["ref"], p["new_kept"]) == (
        tid, "Receipts", "project", ref, 1)
    assert set(p) == set(data["topics"][0])
    assert data["new_kept"] == sum(t["new_kept"] for t in data["topics"]) == before["new_kept"]


def test_today_without_project_topics_has_an_empty_list(web):
    assert web.get("/api/today").json()["project_topics"] == []
