import time
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote_plus

import httpx
import pytest
from starlette.testclient import TestClient

from kranto import library
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.scheduler import Job, Scheduler, is_due
from kranto.sources import HTTP, Item
from kranto.store import iso
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, sign_in, web_client

SUMMARIES = [
    "Pay-as-you-go solar home systems in Kenya reach 30% of rural households",
    "LFP battery cell prices fell below $50/kWh for stationary storage",
    "A CRDT sync engine ships offline-first collaboration for SQLite",
    "<script>alert('x')</script> injected title should be escaped",
]


def feed_site(request):
    rss = (b"<rss><channel><title>Manual Feed</title><item><title>t</title><guid>1</guid>"
           b"<description>d</description></item></channel></rss>")
    return httpx.Response(200, content=rss)


@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(signal_threshold=0.20), map=MapConfig())
    client = make_client(lambda body: chat_response('{"sources": []}'))
    http = HTTP(transport=httpx.MockTransport(feed_site), resolver=lambda h: ["93.184.216.34"])
    runtime = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http)
    topic = library.add_topic(store, embedder, "energy", "solar and batteries in Africa")
    src = library.add_source(store, "rss", {"url": "https://ex.com/feed"}, label="Energy Feed")
    library.link_topic_source(store, topic, src)
    for i, summary in enumerate(SUMMARIES):
        fields = {"kind": "beat", "summary": summary, "why_it_matters": "because",
                  "content_quality": 0.8, "durability": 0.7, "opportunity": 0.5 + i / 10,
                  "signal": 0.8 * 0.7 * (0.5 + i / 10), "override": False,
                  "override_reason": None, "tags": ["t"]}
        call = store.insert("llm_calls", dict(
            purpose="judge", tier="judge", model="judge-model", prompt_version="judge-x",
            request="{}", response='{"raw": true}', status="ok", attempts=1, cost_usd=0.001,
            created_at="2026-09-24T10:00:00Z"))
        library.record_observation(
            store, source_id=src, item=Item(id=f"i{i}", title=f"title {i}", body=summary,
                                            url=f"https://ex.com/{i}"),
            fields=fields, embedding=embedder.embed_documents([summary])[0],
            embedding_model=embedder.model_name, llm_call_id=call, prompt_version="judge-x",
            run_uuid="r", admitted_by="topic", topic_similarity=0.6)
    return runtime


@pytest.fixture
def web(rt):
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client


def test_library_filters_and_sort(web):
    assert web.get("/api/observations").json()["total"] == 4
    strong = web.get("/api/observations?min_signal=0.39").json()["results"]
    assert any("injected title" in o["summary"] for o in strong)
    assert not any("Pay-as-you-go" in o["summary"] for o in strong)
    assert web.get("/api/observations?contains=CRDT").json()["total"] == 1


def test_semantic_search_ranks_and_cuts_off(web):
    body = web.get("/api/observations?q=solar+home+systems+kenya&cutoff=1").json()
    # Unrelated observations score far below the closest match and are left out.
    assert body["total"] == 1 and body["results"][0]["summary"].startswith("Pay-as-you-go")
    assert body["results"][0]["score"] > 0


def test_search_says_off_topic_only_when_even_the_closest_match_is_far(web, rt):
    # The stub embedder scores this query 0.534 against its best match.
    body = web.get("/api/observations?q=solar+home+systems+kenya&cutoff=1").json()
    assert body["closest"] == 0.53 and body["off_topic_below"] == 0.65
    exact = web.get("/api/observations?cutoff=1&q=" +
                    SUMMARIES[1].replace(" ", "+").replace("$", "%24")).json()
    assert exact["results"][0]["summary"].startswith("LFP battery")
    assert exact["closest"] is None


def test_search_results_are_paged(web, monkeypatch):
    from kranto import search
    from kranto.web import app as app_mod

    monkeypatch.setattr(app_mod, "SEARCH_PAGE_SIZE", 1)
    monkeypatch.setattr(search, "CUTOFF_BELOW_BEST", 2.0)
    query = "/api/observations?q=solar+battery+sync&cutoff=1"
    first = web.get(f"{query}&offset=0&limit=1").json()
    assert first["total"] == 4 and len(first["results"]) == 1
    second = web.get(f"{query}&offset=1").json()
    assert len(second["results"]) == 1
    assert second["results"][0]["id"] != first["results"][0]["id"]
    assert web.get(f"{query}&offset=99").json()["results"] == []


def test_observation_detail_shows_audit_trail_and_neighbours(web, rt):
    obs_id = rt.store.query_one("SELECT id FROM observations ORDER BY id LIMIT 1")["id"]
    one = web.get(f"/api/observations/{obs_id}").json()
    assert one["call"]["model"] == "judge-model" and one["call"]["response"]
    assert one["neighbours"]
    assert web.get("/api/observations/99999").status_code == 404


def test_source_status(web, rt):
    src_id = library.list_sources(rt.store)[0].id
    r = web.post(f"/sources/{src_id}/status", data={"status": "retired"},
                 follow_redirects=False)
    assert r.status_code == 303
    assert rt.store.current_status("source", src_id) == "retired"
    assert web.post(f"/sources/{src_id}/status", data={"status": "nonsense"}).status_code == 400


def test_add_topic_with_scout_and_manual_source(web, rt):
    r = web.post("/topics", data={"name": "local-first", "description": "CRDTs and sync",
                                  "scout": "1"}, follow_redirects=False)
    assert r.status_code == 303     # in the background
    assert "The scout started" in unquote_plus(r.headers["location"])
    topic = next(t for t in library.active_topics(rt.store) if t.name == "local-first")
    deadline = time.time() + 30
    while (job := web.get(f"/api/topics/{topic.id}/scout").json()["job"])["state"] == "running":
        assert time.time() < deadline
        time.sleep(0.05)
    assert "contained no usable proposals; nothing was added" in job["result"]["message"]
    r = web.post("/sources", data={"kind": "rss", "value": "https://ex.com/manual"},
                 follow_redirects=False)
    assert "Added Manual Feed (1 items)" in unquote_plus(r.headers["location"])


def test_cross_origin_posts_are_refused(web, rt):
    r = web.post("/pause", data={"reason": "x"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert rt.store.pause_reason() is None
    r = web.post("/pause", data={"reason": "mine"}, headers={"origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert rt.store.pause_reason() == "mine"
    assert "Paused: mine" in web.get("/library").text
    web.post("/resume")
    assert rt.store.pause_reason() is None


def test_health_page(web, rt):
    rt.store.insert("runs", dict(run_uuid="abc", kind="ingest", status="failed",
                                 started_at="2026-09-24T10:00:00Z",
                                 finished_at="2026-09-24T10:01:00Z",
                                 summary='{"spend_usd": 0, "contributed": 0, "sources": []}',
                                 error="HTTP 401 from provider"))
    health = web.get("/api/health").json()
    [run] = [r for r in health["runs"] if r["run_uuid"] == "abc"]
    assert run["status"] == "failed" and run["error"] == "HTTP 401 from provider"
    assert health["spent_usd"] == 0.004


OLD_PAGES = ("/", "/library", "/library?q=solar", "/obs/1", "/obs/99999", "/rollups", "/map",
             "/clusters", "/ideas", "/topics", "/watches", "/health", "/grade/message/1",
             "/grade/cluster/x")


@pytest.mark.parametrize("path", OLD_PAGES)
def test_alone_the_old_pages_show_how_to_install_kranto(web, path):
    """D5: Kranto is one app. Without the page, the server's old page addresses (and its
    front door) answer one install notice, not the pages they used to be."""
    page = web.get(path, follow_redirects=False)
    assert page.status_code == 200
    assert "<h1>Kranto is one app</h1>" in page.text
    assert "follow step 2, Install, of the setup guide" in page.text
    assert "docs/setup.md" in page.text
    assert 'href="/library"' not in page.text and 'href="/health"' not in page.text


def test_alone_the_connection_pages_still_render(web):
    page = web.get("/connections")
    assert page.status_code == 200 and "Kranto is one app" not in page.text
    assert 'href="/connections"' in page.text


def test_json_api(web, rt):
    data = web.get("/api/observations?limit=2&sort=signal").json()
    assert data["total"] == 4 and len(data["results"]) == 2
    assert data["results"][0]["signal"] >= data["results"][1]["signal"]
    hits = web.get("/api/observations?q=battery+prices").json()["results"]
    assert hits[0]["summary"].startswith("LFP battery")
    one = web.get(f"/api/observations/{hits[0]['id']}").json()
    assert len(one["similar"]) == 3
    assert web.get("/api/observations/424242").status_code == 404
    status = web.get("/api/status").json()
    assert status["observations"] == 4 and status["topics"][0]["name"] == "energy"


def test_scheduler_due_from_runs_table(store):
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    ran = []
    job = Job("ingest", 3, lambda: ran.append(1))
    assert is_due(store, job, now)
    store.insert("runs", dict(run_uuid="a", kind="ingest", status="ok",
                              started_at="2026-09-24T10:00:00Z",
                              finished_at="2026-09-24T10:00:00Z", summary="{}"))
    assert not is_due(store, job, now)
    assert is_due(store, job, now + timedelta(hours=1))
    store.insert("runs", dict(run_uuid="b", kind="ingest", status="skipped",
                              started_at="2026-09-24T14:00:00Z",
                              finished_at="2026-09-24T14:00:00Z", summary="{}"))
    # A skip does not reset the interval, but defers the next attempt by an hour
    # rather than one tick, so a job that keeps skipping is not run every minute.
    assert not is_due(store, job, now + timedelta(hours=2, minutes=30))
    assert is_due(store, job, now + timedelta(hours=3))
    sched = Scheduler(store, [job], clock=lambda: now + timedelta(hours=4))
    assert sched.run_due() == ["ingest"]
    assert ran == [1]
    assert not is_due(store, Job("never", 0, lambda: None), now)


def test_a_job_that_keeps_skipping_is_retried_hourly_not_every_tick(store):
    """#88: an unchanged map made the snapshot and ideas jobs run once a minute."""
    start = datetime(2026, 10, 4, 19, 25, tzinfo=UTC)
    clock = [start]

    def skip():
        store.insert("runs", dict(run_uuid=f"s{len(runs)}", kind="snapshot", status="skipped",
                                  started_at=iso(clock[0]), finished_at=iso(clock[0]),
                                  summary="{}"))
        runs.append(clock[0])

    runs = []
    store.insert("runs", dict(run_uuid="ok", kind="snapshot", status="ok",
                              started_at="2026-10-03T19:24:00Z",
                              finished_at="2026-10-03T19:25:00Z", summary="{}"))
    sched = Scheduler(store, [Job("snapshot", 24, skip)], clock=lambda: clock[0])
    for minute in range(3 * 60):
        clock[0] = start + timedelta(minutes=minute)
        sched.run_due()
    assert len(runs) == 3
    assert [r - start for r in runs] == [timedelta(0), timedelta(hours=1), timedelta(hours=2)]


def test_next_run_is_when_the_job_is_next_due_and_running_names_the_job(store):
    """The header's "Watching · next read 18:00" and "Reading sources…" (Kranto UI)."""
    now = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)
    clock = [now]
    seen = []
    sched = Scheduler(store, [Job("ingest", 3, lambda: seen.append(sched.running)),
                              Job("deepdive", 0, lambda: None)], clock=lambda: clock[0])
    # never run: due now; a job that is off (every 0 hours) has no row
    assert sched.next_runs() == {"ingest": iso(now)}
    store.insert("runs", dict(run_uuid="a", kind="ingest", status="ok",
                              started_at="2026-10-08T15:00:00Z",
                              finished_at="2026-10-08T15:10:00Z", summary="{}"))
    assert sched.next_runs()["ingest"] == "2026-10-08T18:10:00Z"
    store.insert("runs", dict(run_uuid="b", kind="ingest", status="skipped",
                              started_at="2026-10-08T18:10:00Z",
                              finished_at="2026-10-08T18:10:00Z", summary="{}"))
    clock[0] = datetime(2026, 10, 8, 18, 30, tzinfo=UTC)
    assert sched.next_runs()["ingest"] == "2026-10-08T19:10:00Z", "a skip rechecks in an hour"
    for minute in (0, 59, 60):
        clock[0] = datetime(2026, 10, 8, 18, 10, tzinfo=UTC) + timedelta(minutes=minute)
        due = is_due(store, sched.jobs[0], clock[0])
        assert due == (sched.next_runs()["ingest"] == iso(clock[0])), minute
    assert sched.running is None
    sched.run_due()
    assert seen == ["ingest"] and sched.running is None


def test_status_and_health_carry_running_and_next_run(rt, store):
    now = datetime(2026, 10, 8, 16, 0, tzinfo=UTC)
    store.insert("runs", dict(run_uuid="r", kind="ingest", status="ok",
                              started_at="2026-10-08T14:50:00Z",
                              finished_at="2026-10-08T15:00:00Z", summary="{}"))
    sched = Scheduler(store, [Job("ingest", 3, lambda: None)], tick_seconds=60,
                      clock=lambda: now)
    with web_client(create_app(rt, sched), "http://127.0.0.1:8765") as client:
        for path in ("/api/status", "/api/health"):
            body = client.get(path).json()
            assert body["running"] is None, path
            assert body["next_run"] == {"ingest": "2026-10-08T18:00:00Z"}, path
    with web_client(create_app(rt, None), "http://127.0.0.1:8765") as client:
        body = client.get("/api/status").json()
        assert body["running"] is None and body["next_run"] == {}


def test_javascript_links_from_feeds_are_never_rendered(web, rt):
    from kranto import library as lib
    from kranto.sources import Item

    src = lib.list_sources(rt.store)[0].id
    fields = {"kind": "beat", "summary": "evil link item", "why_it_matters": "w",
              "content_quality": 1, "durability": 1, "opportunity": 1, "signal": 1,
              "override": False, "override_reason": None, "tags": []}
    call = rt.store.insert("llm_calls", dict(purpose="judge", tier="judge", model="m",
                                             prompt_version="v", request="{}", status="ok",
                                             attempts=1, cost_usd=0, created_at="2026-09-24"))
    obs_id = lib.record_observation(
        rt.store, source_id=src, item=Item(id="evil", title="t", body="b",
                                           url="javascript:alert(document.cookie)"),
        fields=fields, embedding=rt.embedder.embed_documents(["evil"])[0],
        embedding_model=rt.embedder.model_name, llm_call_id=call, prompt_version="v",
        run_uuid="r", admitted_by="topic", topic_similarity=None)
    assert rt.store.query_one("SELECT source_url FROM observations WHERE id = ?",
                              (obs_id,))["source_url"] is None
    assert web.get(f"/api/observations/{obs_id}").json()["source_url"] is None


# -- #40: another site in the operator's browser must not read or drive the UI ----------

BASE = "http://127.0.0.1:8765"


def test_unknown_host_is_refused_so_dns_rebinding_cannot_read_or_post(web, rt):
    """A page on attacker.example re-resolved to 127.0.0.1 sends its own Host,
    and a matching Origin, so the old same-origin check passed."""
    evil = {"host": "attacker.example:8765", "origin": "http://attacker.example:8765"}
    assert web.get("/api/status", headers=evil).status_code == 400
    assert web.get("/api/observations", headers=evil).status_code == 400
    assert web.post("/pause", data={"reason": "x"}, headers=evil).status_code == 400
    assert rt.store.pause_reason() is None
    assert web.get("/api/status", headers={"host": "localhost:8765"}).status_code == 200


def test_extra_allowed_host(rt):
    app = create_app(rt, allowed_hosts={"127.0.0.1", "host.lan"})
    with TestClient(app, base_url="http://host.lan:8765",
                    headers={"origin": "http://host.lan:8765"}) as client:
        sign_in(client, app)
        assert client.get("/api/status").status_code == 200
        assert client.post("/pause", data={"reason": "lan"}).status_code == 200
    assert rt.store.pause_reason() == "lan"


@pytest.mark.parametrize("headers", [
    {"origin": ""},                      # empty Origin
    {"origin": "null"},                  # opaque origin (sandboxed frame, file:)
    {"origin": "http://127.0.0.1:9999"}, # other port
])
def test_posts_without_a_matching_origin_are_refused(web, rt, headers):
    assert web.post("/pause", data={"reason": "x"}, headers=headers).status_code == 403
    assert rt.store.pause_reason() is None


def test_posts_with_neither_origin_nor_referer_are_refused(rt):
    app = create_app(rt)
    with TestClient(app, base_url=BASE) as bare:
        sign_in(bare, app)
        assert bare.post("/pause", data={"reason": "x"}).status_code == 403
        assert bare.post("/pause", data={"reason": "x"},
                         headers={"referer": f"{BASE}/health"}).status_code == 200
    assert rt.store.pause_reason() == "x"


def test_every_response_forbids_framing(web):
    for response in (web.get("/library"), web.get("/static/style.css"),
                     web.post("/pause", headers={"origin": "http://evil.example"}),
                     web.get("/api/status", headers={"host": "evil.example"})):
        assert response.headers["x-frame-options"] == "DENY"
        csp = response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        # the one form the page may post elsewhere: the manifest that creates Kranto's own
        # GitHub App on github.com (the page's Settings › GitHub); nothing else leaves
        assert "form-action 'self' https://github.com;" in csp
        assert "script-src 'self';" in csp and "default-src 'self';" in csp
        assert response.headers["x-content-type-options"] == "nosniff"


def test_out_of_range_numbers_are_not_server_errors(web):
    huge = "9" * 30
    assert web.get(f"/api/observations/{huge}").status_code == 404
    assert web.get(f"/obs/{huge}").status_code in (200, 404)
    assert web.get(f"/api/observations?limit={huge}").status_code == 200
    body = web.get("/api/observations?limit=-1").json()
    assert len(body["results"]) <= 1


@pytest.mark.parametrize("content", ["[1, 2]", "not json", "{" + "x" * 70_000 + "}"])
def test_explain_api_refuses_bad_or_oversized_json(web, content):
    r = web.post("/api/explain", content=content,
                 headers={"content-type": "application/json"})
    assert r.status_code == 400 and "JSON object" in r.json()["error"]


def test_multipart_posts_are_refused(web):
    r = web.post("/grade", data={"target": "observation", "target_id": "1"},
                 files={"note": ("n.txt", b"file body")})
    assert r.status_code == 415


def test_override_shows_only_where_it_lifted_the_item(rt, web):
    """#100: the judge sets override far more often than it is needed. The JSON API shows
    it only where the signal is below the gate, i.e. override kept the item; the stored row
    is not edited."""
    ids = {}
    for name, signal in (("lifted", 0.15), ("unneeded", 0.5)):
        fields = {"kind": "beat", "summary": f"{name} observation", "why_it_matters": "w",
                  "content_quality": 0.5, "durability": 0.5, "opportunity": 0.6,
                  "signal": signal, "override": True,
                  "override_reason": f"{name}-reason", "tags": []}
        ids[name] = library.record_observation(
            rt.store, source_id=1, item=Item(id=name, title=name, body=name,
                                             url=f"https://ex.com/{name}"),
            fields=fields, embedding=rt.embedder.embed_documents([name])[0],
            embedding_model=rt.embedder.model_name, llm_call_id=None,
            prompt_version="judge-x", run_uuid="r", admitted_by="topic",
            topic_similarity=0.6)
    lifted = web.get(f"/api/observations/{ids['lifted']}").json()
    unneeded = web.get(f"/api/observations/{ids['unneeded']}").json()
    assert (lifted["override"], lifted["override_reason"]) == (True, "lifted-reason")
    assert (unneeded["override"], unneeded["override_reason"]) == (False, None)
    listed = {o["id"]: o["override"] for o in web.get("/api/observations").json()["results"]}
    assert listed[ids["lifted"]] and not listed[ids["unneeded"]]
    stored = rt.store.query_one("SELECT override FROM observations WHERE id = ?",
                                (ids["unneeded"],))
    assert stored["override"] == 1
