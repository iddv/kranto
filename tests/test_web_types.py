"""The JSON Kranto UI reads, typed: ``the server/web/types.py`` says what each
route the page reads answers, and these tests keep it true. Every typed route's real answer,
on a library with two maps, a watch that matched, a message, runs, grades, a failing source, a
muted one, a proposed one, a rollup, a deep dive's step, an explained neighbourhood, a
connected account and a finished setup in it, has the shape its TypedDict says (and so does an
empty library's, the Parallax archive's themes and dispatch cards, the scout's job, and the
cards and review queue of a week with cards in it); ``/api/status`` carries ``host_api``; and
the TypeScript ``scripts/gen_ts.py`` writes for Kranto UI is the same text each time it
runs."""
import copy
import importlib.util
import json
import re
import time
import types
import typing
from pathlib import Path
from typing import Any, Literal

import pytest

from kranto import feedback, gate, grades, library, notify, setup, source_health
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.ideate import dispatches
from kranto.map.snapshot import take_snapshot
from kranto.runtime import open_runtime
from kranto.store import iso, utcnow, vec_to_blob
from kranto.tick import RunReport, SourceReport
from kranto.web import types as T
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, old_grade, web_client
from .test_ideas_api import add_theme, cards  # noqa: F401 - fixture
from .test_map import add_observations, corpus  # noqa: F401 - fixture
from .test_parallax_archive import BOLD, import_with_bundle
from .test_topics_api import scouting, themed  # noqa: F401 - fixtures
from .test_web import rt, web  # noqa: F401 - fixtures

ROOT = Path(__file__).resolve().parents[1]

# every typed path, and the queries that change what it answers
ASKED = ["/api/home",
         "/api/status", "/api/topics", "/api/topics?kind=all", "/api/sources", "/api/today",
         "/api/today?since=2026-09-01T00:00:00Z", "/api/health", "/api/observations",
         "/api/observations?since=last&limit=5", "/api/observations?cluster=0",
         "/api/observations?sort=signal&kind=!beat&since=2026-01-01T00:00:00Z"
         "&until=2999-01-01T00:00:00Z",
         "/api/observations?q=solar+battery&cutoff=1",
         "/api/observations?q=solar+battery&k=10&limit=2&offset=1", "/api/map",
         "/api/clusters", "/api/clusters?sort=moving", "/api/clusters?sort=cross",
         "/api/rollups", "/api/rollups?q=solar", "/api/catalog",
         "/api/connections", "/api/setup", "/api/setup/provider", "/api/ideas",
         "/api/ideas?embedding=ref&origin=all",
         "/api/feedback/vocabulary", "/api/review/queue",
         "/api/review/queue?builds=plot-1&controls=2", "/api/grades/summary",
         "/api/post", "/api/post/sites"]
# typed paths checked by their own tests below: POSTs, and the scout's job
ELSEWHERE = {"/api/sources/preview", "/api/topics/{id}/scout",
             "/api/sources/from-text", "/api/sources/from-text/{id}", "/api/sources/approve",
             "/api/websearch", "/api/websearch/fetch",
             "/api/setup/search",  # test_websearch.py, test_search_setup.py
             "/api/newsletter",    # test_newsletter_resend.py (none connected, and Resend's)
             "/api/topics/{id}/sources", "/api/topics/{id}/status",  # test_topic_edit.py
             "/api/errors", "/api/errors/{id}",   # test_rowsafe.py (a server with an error)
             "/api/ideas/{id}/later",             # test_ideas_later.py (a POST)
             "/api/post/d/{id}"}   # test_post_api.py (drafts in every group)


@pytest.fixture(autouse=True)
def no_logins(monkeypatch):
    """``/api/setup`` asks ``claude`` and ``gh`` whether they are signed in: here neither is
    installed, and no process is started."""
    monkeypatch.setattr(setup, "RUN", lambda cmd: (127, ""))
    monkeypatch.setattr(setup, "_logins", None)


def problems(value: Any, tp: Any, where: str = "$") -> list[str]:
    """Where ``value`` (a decoded JSON answer) does not have the shape ``tp`` says, in words;
    empty when it does. (the page's ``ui/types.py`` has the same check for its own JSON.)"""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if tp is Any:
        return []
    if tp is None or tp is type(None):
        return [] if value is None else [f"{where}: {value!r:.40} is not null"]
    if origin is Literal:
        return [] if value in args else [f"{where}: {value!r:.40} is not one of {args}"]
    if origin in (typing.Union, types.UnionType):
        tried = [problems(value, a, where) for a in args]
        return [] if any(not t for t in tried) else min(tried, key=len)
    if origin is list:
        if not isinstance(value, list):
            return [f"{where}: {type(value).__name__} is not a list"]
        return [p for i, v in enumerate(value) for p in problems(v, args[0], f"{where}[{i}]")]
    if origin is dict:
        if not isinstance(value, dict):
            return [f"{where}: {type(value).__name__} is not an object"]
        return [p for k, v in value.items() for p in problems(v, args[1], f"{where}.{k}")]
    if typing.is_typeddict(tp):
        if not isinstance(value, dict):
            return [f"{where}: {type(value).__name__} is not an object ({tp.__name__})"]
        out = [f"{where}: no {k!r} ({tp.__name__})" for k in sorted(tp.__required_keys__)
               if k not in value]
        hints = typing.get_type_hints(tp)
        for k, v in value.items():
            if k in hints:
                out += problems(v, hints[k], f"{where}.{k}")
            elif tp.__name__ not in T.OPEN:
                out.append(f"{where}: {k!r} is not in {tp.__name__}")
        return out
    if tp is bool:
        return [] if isinstance(value, bool) else [f"{where}: {value!r:.40} is not a boolean"]
    if tp is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return [] if ok else [f"{where}: {value!r:.40} is not an integer"]
    if tp is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return [] if ok else [f"{where}: {value!r:.40} is not a number"]
    if tp is str:
        return [] if isinstance(value, str) else [f"{where}: {value!r:.40} is not a string"]
    raise TypeError(f"problems: no rule for {tp!r} at {where}")


def _gen_ts():
    spec = importlib.util.spec_from_file_location("gen_ts", ROOT / "scripts" / "gen_ts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seeded(corpus, rt, embedder):  # noqa: F811
    """``rt``'s library (a topic, its source, four observations) with ``corpus``'s 75 in
    three themes and 12 more in one, two maps, a source failing four runs in a row, a muted
    one, a proposed one, a model error, an ingest and a compact run, a strike decision, a
    watch that matched, a message, grades on an observation, a cluster and a message, a
    rollup, a connected Mastodon account with a source that reads with it, a key tried and
    setup done."""
    store = rt.store
    take_snapshot(store, embedder, None)
    add_observations(store, embedder, "solar", 12, "solar-a", start=15)
    take_snapshot(store, embedder, None, force=True)          # a second: clusters have movement
    obs = store.query_one("SELECT id FROM observations WHERE summary LIKE 'LFP battery%'")["id"]
    topic = store.query_one("SELECT id FROM topics")["id"]
    feed = store.query_one("SELECT id FROM sources WHERE label = 'Energy Feed'")["id"]
    for _ in range(4):                                        # failing run after run
        source_health.record_fetch(store, feed, trigger="run", state="failing", fetched=0,
                                   new=0, error="HTTP 500", run_uuid="run-1")
    quiet = store.query_one("SELECT id FROM sources WHERE label = 'bread-b'")["id"]
    source_health.set_mute(store, quiet, days=3)
    library.add_source(store, "rss", {"url": "https://ex.com/proposed"}, label="Proposed Feed",
                       origin="scout", status="proposed",
                       validation={"status": "valid", "items": 12, "recent": 9,
                                   "median_similarity": 0.7, "role": "core",
                                   "topic_id": topic, "why": "covers solar",
                                   "checked": "scout"})
    store.insert("llm_calls", dict(
        purpose="judge", tier="judge", model="judge-model", prompt_version="judge-x",
        request="{}", status="error", http_status=429, error="rate limited", attempts=3,
        prompt_tokens=10, completion_tokens=2, run_uuid="run-1",
        created_at="2026-09-24T09:00:00Z"))
    store.insert("runs", dict(run_uuid="run-2", kind="compact", status="ok",
                              started_at="2026-09-24T08:00:00Z",
                              finished_at="2026-09-24T08:01:00Z",
                              summary='{"expired": 3, "rollups": 1, "removed": {}}'))
    notify.record_candidate(store, origin="burst", subject_key="lineage:1", score=0.7,
                            title="Battery prices", body="A burst.")
    gate.run_gate(store, rt.cfg.strike)
    report = RunReport("run-1", tokens={"in": 10, "out": 2}, sources=[
        SourceReport(feed, "Energy Feed", fetch_error="HTTP 500", fetch_state="failing",
                     failing_runs=4),
        SourceReport(quiet, "bread-b", fetched=3, judged=3, contributed=1)])
    store.insert("runs", dict(run_uuid="run-1", kind="ingest", status="ok",
                              started_at="2026-09-24T10:00:00Z",
                              finished_at="2026-09-24T10:01:00Z", summary=report.to_json()))
    notify.emit(store, "heartbeat", "A quiet week", "Nothing crossed the line.",
                      dedup_key="probe:1", origin="digest", links=["/library"],
                      evidence_ids=[obs])
    grades.add_grade(store, "observation", obs, "useful")
    # a theme's grade from before grades were kept on ideas and evidence only: still read
    lineage = store.query_one("SELECT lineage_id FROM clusters LIMIT 1")["lineage_id"]
    old_grade(store, "cluster", lineage, "missed")
    # the observation's page: a step read from it (a deep dive's link) and its neighbourhood
    # explained
    crdt = store.query_one("SELECT id FROM observations WHERE summary LIKE 'A CRDT%'")["id"]
    store.insert("observation_links", dict(parent_id=obs, child_id=crdt, relation="discussion",
                                           created_at="2026-09-24T10:00:00Z"))
    store.insert("syntheses", dict(cache_key="k1", kind="observation", subject=f"obs:{obs}",
                                   input_ids=json.dumps([obs, crdt]), text="Batteries [1].",
                                   created_at="2026-09-24T10:00:00Z"))
    vec = embedder.embed_documents(["solar microgrid kenya"])[0]
    store.insert("rollups", dict(
        period_start="2026-08-31T00:00:00Z", period_end="2026-09-07T00:00:00Z",
        first_at="2026-08-31T10:00:00Z", last_at="2026-09-06T10:00:00Z", size=3,
        source_mix='{"Energy Feed": 3}', platform_mix='{"rss": 3}', topic_mix='{"energy": 3}',
        mean_signal=0.4, kind_counts='{"beat": 3}', keywords='["solar", "kenya"]',
        name="solar week", summary="Solar microgrids in Kenya.", urls='["https://ex.com/9"]',
        centroid=vec_to_blob(vec), embedding_model=embedder.model_name, replaced_count=3,
        replaced_fingerprint="f", created_at="2026-09-24T10:00:00Z"))
    # a connected account (its rows only: no secret is needed to list it) and its source
    conn = store.insert("connections", dict(provider="mastodon", instance="mastodon.social",
                                            account="@me@mastodon.social",
                                            scopes='["read:statuses"]',
                                            created_at="2026-09-24T10:00:00Z"))
    for event in ("connected", "tested"):
        store.insert("connection_events", dict(connection_id=conn, event=event, note="ok",
                                               created_at="2026-09-24T10:00:00Z"))
    library.add_source(store, "mastodon", {"instance": "mastodon.social", "what": "home"},
                       label="Mastodon home")
    setup.record_key_test(store, setup.KeyTest(True, "the endpoint accepted the key"),
                          "https://openrouter.ai/api/v1")
    setup.mark_done(store, "auto", 2)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client


def _key(path: str) -> str:
    """The path's key in ``RETURNS``: its query left out, an id as ``{id}``."""
    return re.sub(r"^/api/(observations|topics|sources)/\d+", r"/api/\1/{id}",
                  path.split("?")[0])


def _typed(path: str):
    return T.RETURNS[_key(path)]


def _asked(client) -> list[str]:
    """ASKED, with an observation's page and the latest grades of a page's rows: the graded
    LFP observation (a step was read from it), and the CRDT one (read one step from it); the
    topic's page; the pages of the failing source (its fetches) and the proposed one."""
    rows = client.get("/api/observations?limit=200").json()["results"]
    obs = next(o["id"] for o in rows if o["summary"].startswith("LFP battery"))
    other = next(o["id"] for o in rows if o["summary"].startswith("A CRDT"))
    topic = client.get("/api/topics").json()["topics"][0]["id"]
    srcs = {s["label"]: s["id"] for s in client.get("/api/sources").json()["sources"]}
    return [*ASKED, f"/api/observations/{obs}?k=12", f"/api/observations/{other}",
            f"/api/feedback?target=observation&ids={obs},{other}", "/api/feedback?target=cluster"
            "&ids=", "/api/archive/themes", f"/api/topics/{topic}", f"/api/topics/{topic}/start",
            f"/api/sources/{srcs['Energy Feed']}", f"/api/sources/{srcs['Proposed Feed']}"]


def test_every_typed_route_answers_its_type(seeded):
    seen = {}
    for path in _asked(seeded):
        r = seeded.get(path)
        assert r.status_code == 200, (path, r.text[:200])
        seen[path] = got = r.json()
        assert problems(got, _typed(path)) == [], path
    topic = seen["/api/topics"]["topics"][0]["id"]
    r = seeded.post("/api/sources/preview", json={"preset": "web.feed", "topic": topic,
                                                  "fields": {"url": "https://ex.com/feed"}})
    assert r.status_code == 200 and problems(r.json(), T.SourcePreview) == []
    assert r.json()["newest"] and r.json()["existing_id"]
    assert {_key(p) for p in seen} | ELSEWHERE == set(T.RETURNS)
    # the check read real rows, not empty lists
    h = seen["/api/health"]
    assert h["decisions"] and h["errors"] and h["messages"] and "message_grades" not in h
    assert h["retention"]["last"] and any(r["summary"].get("sources") for r in h["runs"])
    today = seen["/api/today"]
    assert today["sources_failing"] and today["topics"][0]["top"] and today["messages"]
    assert any(s["mute"] for s in seen["/api/sources"]["sources"])
    assert any(s["validation"] for s in seen["/api/sources"]["sources"])
    clusters = seen["/api/clusters"]["clusters"]
    # a theme's old grade (feedback target cluster) is skipped since builds left
    assert any(c["movement"] for c in clusters) and not any(c["grade"] for c in clusters)
    assert seen["/api/observations?q=solar+battery&cutoff=1"]["rollups"]
    assert seen["/api/map"]["points"]["id"] and seen["/api/rollups"]["results"]
    assert seen["/api/map"]["snapshot"]["quality"]["structure_null"]
    page, child = (seen[p] for p in seen if _key(p) == "/api/observations/{id}")
    assert page["call"] and page["synthesis"] and page["dive_children"] and page["grade"]
    assert page["neighbours"] and page["similar"] and child["dive_parent"]
    assert [*next(v for p, v in seen.items() if "target=observation" in p)["grades"]] == \
        [str(page["id"])]
    by_key = {_key(p): v for p, v in seen.items()}
    assert by_key["/api/topics/{id}"]["source_rows"] and by_key["/api/topics/{id}"]["snapshot"]
    assert any(v.get("fetches") for p, v in seen.items() if _key(p) == "/api/sources/{id}")
    [account] = seen["/api/connections"]["accounts"]
    assert account["sources"] and account["last_test"]
    assert seen["/api/setup"]["key"]["test"] and seen["/api/setup"]["build"]["mode"] == "auto"
    assert seen["/api/catalog"]["connected"]["mastodon"]
    # builds are not graded: a build named to the queue is not asked about
    assert not [x for x in seen["/api/review/queue?builds=plot-1&controls=2"]["items"]
                if x["slot"] == "build"]


def test_an_empty_library_answers_its_types(store, embedder, tmp_path, make_client):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    runtime = open_runtime(cfg, store=store, embedder=embedder,
                           llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(runtime)) as client:
        for path in ASKED:
            r = client.get(path)
            if path == "/api/map":
                assert r.status_code == 404 and problems(r.json(), T.MapNotYet) == []
                continue
            assert r.status_code == 200, (path, r.text[:200])
            assert problems(r.json(), _typed(path)) == [], path
        for path in ("/api/feedback?target=observation&ids=", "/api/archive/themes"):
            assert problems(client.get(path).json(), _typed(path)) == [], path
        assert client.get("/api/observations/1").status_code == 404


def test_archive_themes_answer_their_type(web, rt, tmp_path):  # noqa: F811
    """The Parallax archive's themes, one alive and one ended, with a dispatch's cards."""
    import_with_bundle(tmp_path, rt.store)
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "2026-10-08-001.md").write_text(BOLD)
    dispatches.import_dispatches(rt.store, folder)
    body = web.get("/api/archive/themes").json()
    assert problems(body, T.ArchiveThemes) == []
    assert body["themes"][0]["dispatches"][0]["cards"] and body["themes"][0]["trajectory"]
    # the dispatch's cards, with the pitch and the dispatch they were made from
    ideas = web.get("/api/ideas?origin=all").json()
    assert problems(ideas, T.Ideas) == []
    assert any(i["origin"] == "dispatch" and i["dispatch"] for i in ideas["ideas"])


def test_a_topics_page_with_themes_answers_its_type(themed):  # noqa: F811
    client, solar, _ = themed
    page = client.get(f"/api/topics/{solar}").json()
    assert problems(page, T.TopicPage) == []
    assert page["themes_list"] and page["source_rows"]


def test_the_scouts_job_answers_its_type(scouting):  # noqa: F811
    """Running (the POST's 202) and done, with the proposals as rows to tick."""
    _, client = scouting
    topic = client.post("/api/topics", json={"name": "solar", "description":
                                             "solar microgrid battery storage"}).json()["id"]
    assert client.get(f"/api/topics/{topic}/scout").status_code == 404
    r = client.post(f"/api/topics/{topic}/scout", json={})
    assert r.status_code == 202 and problems(r.json(), T.Scout) == []
    deadline = time.time() + 30
    while (job := client.get(f"/api/topics/{topic}/scout").json())["job"]["state"] == "running":
        assert time.time() < deadline, "the scout did not finish"
        time.sleep(0.05)
    assert problems(job, T.Scout) == []
    assert job["job"]["state"] == "done" and job["job"]["result"]["proposals"]


def test_a_described_batch_and_approving_it_answer_their_types(tmp_path, store, embedder):
    """Running (the POST's 202), done with every kind of line, read again by its id, and
    approved in one request."""
    from .test_resolve import REPLY, TEXT, app_rig, finished, replying

    library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    runtime = app_rig(tmp_path, store, embedder, replying(REPLY))
    with web_client(create_app(runtime)) as client:
        r = client.post("/api/sources/from-text", json={"text": TEXT, "topic": 1})
        assert r.status_code == 202 and problems(r.json(), T.FromText) == []
        job = {"job": finished(client)}
        assert problems(job, T.FromText) == []
        lines = job["job"]["result"]["lines"]
        assert {x["status"] for x in lines} >= {"valid", "invalid", "not_found",
                                                "already_proposed"}
        again = client.get(f"/api/sources/from-text/{job['job']['result']['call_id']}").json()
        assert problems(again, T.FromText) == []
        r = client.post("/api/sources/approve", json={"ids": [lines[0]["source_id"], 999]})
        assert problems(r.json(), T.SourcesApproved) == [] and r.json()["skipped"]


def fresh_card(store, title: str, lineage: str) -> int:
    """A card written now (the queue takes this week's), with a rating."""
    card = {"title": title, "thesis": "Kiosks rent batteries.", "one_liner": f"{title}.",
            "evidence": [], "prediction": {"statement": "s", "by": "2027-01-01"},
            "ratings": {"demand_validation": {"value": 0.4, "reason": "asked", "cites": [1]}}}
    return store.insert("ideas", {
        "fingerprint": "f", "lineage_id": lineage, "origin": "cross_source",
        "evidence_key": f"k-{title}", "input_ids": "[]", "title": title,
        "card": json.dumps(card), "score": 0.6, "status": "shown", "dropped": "[]",
        "created_at": iso(utcnow())})


def test_the_cards_and_the_review_queue_answer_their_types(web, rt, cards):  # noqa: F811
    """``cards``' old, new and unsupported cards, and four written this week on one theme of
    the topic, with observations opened this week: the queue has cards and nothing else, a
    build named or not (#3; builds are not graded,)."""
    store = rt.store
    add_theme(store, "lin-q", 8, {"energy": 8}, name="Battery kiosks")
    for n in range(4):
        fresh_card(store, f"Kiosk ledger {n}", "lin-q")
    for row in store.query("SELECT id FROM observations"):
        feedback.add(store, {"target": "observation", "target_id": str(row["id"]),
                             "kind": "implicit", "value": "opened"})
    for path in ("/api/ideas", "/api/ideas?embedding=ref", "/api/ideas?status=unsupported"):
        assert problems(web.get(path).json(), T.Ideas) == [], path
    ideas = web.get("/api/ideas").json()["ideas"]
    assert any(i["existing"] for i in ideas) and any(i["dropped"] for i in ideas)
    assert any(i["ratings"] for i in ideas) and any(i["theme"] for i in ideas)
    queue = web.get("/api/review/queue?builds=plot-1").json()
    assert problems(queue, T.ReviewQueue) == []
    assert {x["slot"] for x in queue["items"]} == {"card"}
    assert problems(web.get("/api/feedback/vocabulary").json(), T.FeedbackVocabulary) == []


def test_status_carries_the_host_api_version(seeded):
    status = seeded.get("/api/status").json()
    assert status["host_api"] == T.HOST_API_VERSION
    # 2 since builds left: the page's afk.gen.ts is regenerated with it in the page
    assert T.HOST_API_VERSION == 2


def test_a_renamed_or_retyped_field_is_caught(seeded):
    """What the check exists for: a field the page reads renamed, dropped or retyped."""
    h = seeded.get("/api/health").json()
    bad = copy.deepcopy(h)
    bad["runs"][0]["uuid"] = bad["runs"][0].pop("run_uuid")          # renamed
    bad["budget"]["monthly_usd"] = "10"                                # retyped
    del bad["retention"]["line"]                                       # dropped
    bad["flagged"] = 1                                                 # added to a closed type
    got = problems(bad, T.Health)
    assert "$.runs[0]: no 'run_uuid' (HealthRun)" in got
    assert "$.budget.monthly_usd: '10' is not a number" in got
    assert "$.retention: no 'line' (Retention)" in got
    assert "$: 'flagged' is not in Health" in got
    # an open row may carry keys the types don't name; a closed one may not
    assert problems({**h["runs"][0]["summary"], "extra": 1}, T.RunSummary) == []


def test_the_checks_rules():
    assert problems(1, float) == [] and problems(True, int) != [] and problems(1.5, int)
    assert problems(None, str | None) == [] and problems(3, str | None)
    assert problems("warmup", T.Decision.__annotations__["reason"]) == []
    assert problems({"a": 1}, dict[str, int]) == [] and problems({"a": "1"}, dict[str, int])
    assert problems([1, "2"], list[int]) == ["$[1]: '2' is not an integer"]
    with pytest.raises(TypeError):
        problems(1, complex)


def test_the_generated_typescript_is_stable(tmp_path):
    gen = _gen_ts()
    a, b = tmp_path / "a.ts", tmp_path / "b.ts"
    assert gen.main([str(a)]) == 0 and gen.main([str(b)]) == 0
    text = a.read_text()
    assert text == b.read_text() == gen.types_ts()
    assert gen.main(["--check", str(a)]) == 0
    b.write_text(text.replace("host_api: number;", "host_api: string;"))
    assert gen.main(["--check", str(b)]) == 1
    assert gen.main(["--check", str(tmp_path / "missing.ts")]) == 1
    assert text.startswith("// Generated from the server's web/types.py; do not edit")
    assert f"export const HOST_API_VERSION = {T.HOST_API_VERSION};" in text
    for name in ("Status", "Topics", "Sources", "Today", "Health", "Observations", "Rollups",
                 "Map", "Clusters", "ObservationPage", "FeedbackGrades",
                 "ArchiveThemes", "TopicPage", "Scout", "SourcePage",
                 "SourcePreview", "Catalog", "Connections", "Setup", "Ideas",
                 "FeedbackVocabulary", "ReviewQueue"):
        assert f"export interface {name} {{" in text, name
    assert '  "/api/health": Health;' in text
    assert "  tokens_today: Tokens | null;" in text                  # a union with None
    assert "  new?: boolean;" in text                                 # NotRequired
    assert "  [key: string]: unknown;" in text                        # OPEN
    assert '  table: "grades" | "feedback";' in text                  # Literal
