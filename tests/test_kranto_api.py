"""The JSON Kranto UI draws Settings (Health) and the Library from: the same queries as
the server's pages, behind the same guard."""

import pytest

from kranto import feedback, grades, search
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.map.snapshot import take_snapshot
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, old_grade, web_client
from .test_map import corpus  # noqa: F401 - fixture
from .test_web import rt, web  # noqa: F401 - fixtures

EVIL = {"origin": "https://evil.example"}


def llm_calls(store):
    return store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"]


# -- watches, retired --------------------------------------------------------------------

def test_watches_are_retired_their_routes_gone_their_tables_kept(web, rt):  # noqa: F811
    """WT: no saved-question API is left; the tables stay one release, unread and unwritten."""
    assert web.get("/api/watches").status_code == 404
    for path in ("/api/watches", "/api/watches/preview", "/api/watches/1/retire",
                 "/watches/1/retire"):
        assert web.post(path, json={"query": "solar"}).status_code in (404, 405), path
    assert web.post("/watches", data={"query": "solar"}).status_code == 405
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM watches")["n"] == 0
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM watch_events")["n"] == 0


# -- health ---------------------------------------------------------------------------------

def test_health_json_matches_the_health_page(web, rt):  # noqa: F811
    rt.store.insert("runs", dict(run_uuid="abc", kind="ingest", status="failed",
                                 started_at="2026-09-24T10:00:00Z",
                                 finished_at="2026-09-24T10:01:00Z",
                                 summary='{"spend_usd": 0, "contributed": 0, "sources": []}',
                                 error="HTTP 401 from provider"))
    h = web.get("/api/health").json()
    [run] = h["runs"]
    assert run["status"] == "failed" and run["error"] == "HTTP 401 from provider"
    # read through its contract (stored.runs.IngestSummary): every field named, as stored
    assert {k: run["summary"][k] for k in ("spend_usd", "contributed", "sources")} == \
        {"spend_usd": 0, "contributed": 0, "sources": []}
    assert run["summary"]["tokens"] is None and run["summary"]["sponsored"] == 0
    assert h["spent_usd"] == pytest.approx(0.004) and h["budget"]["monthly_usd"] == 10
    assert h["alarm"] is False and h["paused"] is None and h["can_run"] is False
    assert h["exploration"][0]["admitted_by"] == "topic" and h["exploration"][0]["n"] == 4
    assert len(h["month"]) == 7
    for key in ("outcomes", "errors", "messages", "decisions", "strike", "retention",
                "delivery_status", "models"):
        assert key in h, key
    assert h["strike"]["max_per_week"] == rt.cfg.strike.max_per_week
    rt.store.pause("night")
    assert web.get("/api/health").json()["paused"] == "night"


# -- the library ------------------------------------------------------------------------------

def test_observations_search_as_the_library_page(web, rt):  # noqa: F811
    data = web.get("/api/observations?q=solar+home+systems+kenya&cutoff=1").json()
    assert data["total"] == 1 and data["results"][0]["summary"].startswith("Pay-as-you-go")
    assert data["closest"] == 0.53 and data["off_topic_below"] == search.OFF_TOPIC_BELOW
    assert "suggestion" not in data and data["rollups"] == []
    paged = web.get("/api/observations?q=solar+battery+sync&k=10&limit=1&offset=1").json()
    assert len(paged["results"]) == 1 and paged["total"] >= 2 and paged["offset"] == 1
    listed = web.get("/api/observations?contains=CRDT").json()
    assert listed["total"] == 1 and listed["compacted"] == {"n": 0, "replaced": 0}
    assert listed["cluster_label"] is None and "until the first map" in listed["progress"]


def test_observation_detail_has_what_its_page_shows(web, rt):  # noqa: F811
    obs_id = rt.store.query_one("SELECT id FROM observations ORDER BY id LIMIT 1")["id"]
    o = web.get(f"/api/observations/{obs_id}").json()
    assert o["call"]["model"] == "judge-model" and o["call"]["response"] == '{"raw": true}'
    assert o["content_quality"] == 0.8 and o["durability"] == 0.7 and o["opportunity"] == 0.5
    assert o["source_url"] == "https://ex.com/0" and o["source_label"] == "Energy Feed"
    assert len(o["neighbours"]) == 3 and o["neighbours"][0]["summary"]
    assert [n["id"] for n in o["neighbours"]] == [s["id"] for s in o["similar"]]
    assert o["dive_parent"] is None and o["dive_children"] == [] and o["synthesis"] is None
    assert o["grade"] is None and o["grade_choices"] == ["useful", "not_useful"]


def test_one_way_to_grade_and_the_json_twin_is_gone(web, rt):  # noqa: F811
    """POST /api/grades (the ``grade.add`` verb) is retired; a grade is one
    POST /api/feedback, as every page sends it."""
    obs_id = rt.store.query_one("SELECT id FROM observations ORDER BY id LIMIT 1")["id"]
    body = {"target": "observation", "target_id": obs_id, "value": "useful"}
    assert web.post("/api/grades", json={**body, "grade": "useful"}).status_code in (404, 405)
    assert web.post("/api/feedback", json=body, headers=EVIL).status_code == 403
    r = web.post("/api/feedback", json=body)
    assert r.status_code == 200 and r.json()["label"] == "useful"
    assert grades.latest(rt.store, "observation", [obs_id])[str(obs_id)]["grade"] == "useful"
    assert web.get(f"/api/observations/{obs_id}").json()["grade"]["grade"] == "useful"
    bad = web.post("/api/feedback", json={**body, "value": "worth_waking"})
    assert bad.status_code == 400 and "must be one of" in bad.json()["error"]
    assert web.post("/api/feedback", json={**body, "target_id": 99999}).status_code == 400


@pytest.fixture
def mapped(corpus, embedder, tmp_path, make_client):  # noqa: F811
    take_snapshot(corpus, embedder, None)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    runtime = open_runtime(cfg, store=corpus, embedder=embedder,
                           llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(runtime)) as client:
        yield client


def test_clusters_json_matches_the_clusters_page(mapped, corpus):  # noqa: F811
    data = mapped.get("/api/clusters").json()
    assert data["snapshot"]["n"] == 75 and len(data["clusters"]) == data["snapshot"]["k"]
    c = data["clusters"][0]
    for key in ("cluster", "lineage_id", "label", "keywords", "size", "share", "source_mix",
                "cross_source", "max_source_share", "trajectory", "movement", "rising",
                "examples", "synthesis", "grade", "topic_mix", "origin_mix"):
        assert key in c, key
    assert 1 <= len(c["examples"]) <= 3 and c["examples"][0]["summary"]
    assert [x["size"] for x in data["clusters"]] == sorted(
        (x["size"] for x in data["clusters"]), reverse=True)
    assert {"silhouette_umap", "structure_null"} <= set(data["quality"])
    cross = mapped.get("/api/clusters?sort=cross").json()["clusters"]
    assert cross[0]["cross_source"] or not any(x["cross_source"] for x in cross)
    # the members of one cluster, named as /library?cluster= names them
    members = mapped.get(f"/api/observations?cluster={c['cluster']}&limit=200").json()
    assert members["total"] == c["size"] and members["cluster_label"] == c["label"]
    # a theme is not graded any more; one graded before is skipped since the
    # cut (feedback.RETIRED_TARGETS: counted nowhere, drawn nowhere)
    r = mapped.post("/api/feedback", json={"target": "cluster", "target_id": c["lineage_id"],
                                           "value": "useful"})
    assert r.status_code == 400 and "target must be" in r.json()["error"]
    assert "cluster" in feedback.RETIRED_TARGETS
    old_grade(corpus, "cluster", c["lineage_id"], "missed")
    again = mapped.get("/api/clusters").json()["clusters"]
    assert next(x for x in again if x["cluster"] == c["cluster"])["grade"] is None


def test_empty_library_json(store, embedder, tmp_path, make_client):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    runtime = open_runtime(cfg, store=store, embedder=embedder,
                           llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(runtime)) as client:
        assert client.get("/api/clusters").json() == {
            "snapshot": None, "clusters": [], "progress": "0 of 30 observations until the "
                                                          "first map."}
        r = client.get("/api/map")
        assert r.status_code == 404 and r.json()["progress"].startswith("0 of 30")
        assert client.get("/api/health").json()["runs"] == []
        rollups = client.get("/api/rollups").json()
        assert rollups["total"] == 0 and rollups["retention_line"]
