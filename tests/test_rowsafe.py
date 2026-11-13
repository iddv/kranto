"""One bad row never takes a page down and every error has an id to send
(B3): in each list the API builds row by row, one row that raises is still listed, as
"Couldn't read this <thing>" with a stable error id, the rest of the list as before; the error
is logged once per id; a response that still fails answers Kranto's error JSON or page with the
version, the id, Try again and Send this error; ``/api/errors/<id>`` is the report it sends,
Kranto's own frames only."""

import argparse
import json
import logging
import re
from pathlib import Path

import pytest

from kranto import __version__, library, rowsafe, source_health
from kranto.web.app import create_app

from .conftest import web_client
from .test_ideas_api import add_card, add_theme, obs_ids
from .test_map import corpus  # noqa: F401 - fixture
from .test_web import rt, web  # noqa: F401 - fixtures
from .test_web_types import seeded  # noqa: F401 - fixture


def poison(monkeypatch, owner, name: str, bad):
    """``owner.name`` raising for the arguments ``bad(*args, **kw)`` picks: the bug of the
    incident, a value its reader cannot format."""
    real = getattr(owner, name)

    def wrapped(*args, **kw):
        if bad(*args, **kw):
            raise TypeError("unsupported format string passed to NoneType.__format__")
        return real(*args, **kw)
    monkeypatch.setattr(owner, name, wrapped)


def unreadable(rows: list[dict]) -> list[dict]:
    return [r for r in rows if isinstance(r.get("unreadable"), dict)]


def check_mark(row: dict, what: str) -> str:
    u = row["unreadable"]
    assert u["what"] == what and u["words"] == f"Couldn't read this {what}"
    assert u["exception"] == "TypeError" and len(u["error_id"]) == 8
    int(u["error_id"], 16)
    return u["error_id"]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rowsafe, "_seen", {})


# -- the lists ------------------------------------------------------------------------------------


def test_one_source_that_cannot_be_read_never_breaks_sources_or_any_topic_page(
        web, rt, monkeypatch, caplog):  # noqa: F811
    """The incident: a source's status line raised on every topic page."""
    [t] = library.active_topics(rt.store)
    [ok] = [s.id for s in library.list_sources(rt.store)]
    other = library.add_topic(rt.store, rt.embedder, "storage", "home batteries")
    bad = library.add_source(rt.store, "rss", {"url": "https://ex.com/b"}, label="Bad Feed",
                             origin="scout", status="proposed",
                             validation={"median_similarity": None, "topic_id": t.id})
    real = source_health._status

    def status(s, last, plan):
        if s.id == bad:        # as 0.5.20 did: a stored null formatted as a number
            return f"sim {s.validation.median_similarity:.2f}", None  # stored-shape: the bug
        return real(s, last, plan)
    monkeypatch.setattr(source_health, "_status", status)
    with caplog.at_level(logging.ERROR):
        for _ in range(3):
            rows = web.get("/api/sources").json()["sources"]
            page = web.get(f"/api/topics/{t.id}")
            assert page.status_code == 200
            assert web.get(f"/api/topics/{other}").status_code == 200
            assert web.get("/api/topics").status_code == 200
            assert web.get("/api/today").status_code == 200
        [u] = unreadable(rows)
        assert u["id"] == bad and u["label"] == "Bad Feed"
        eid = check_mark(u, "source")
        assert [r["label"] for r in rows if r["id"] == ok] == ["Energy Feed"]
        listed = page.json()["source_rows"]
        assert {r["id"] for r in listed} == {ok, bad}
        assert unreadable(listed)[0]["unreadable"]["error_id"] == eid
        # the other topic does not list a source it neither feeds nor was proposed for
        assert bad not in {r["id"] for r in web.get(f"/api/topics/{other}").json()["source_rows"]}
        # the source's own page is the error answer, under the same id
        own = web.get(f"/api/sources/{bad}")
        assert own.status_code == 500 and own.json()["error_id"] == eid
    # logged once for the id, not once per request
    assert sum(eid in r.getMessage() for r in caplog.records) == 1


def test_one_topic_that_cannot_be_read_is_listed_as_such(web, rt, monkeypatch):  # noqa: F811
    from kranto.web.topics_api import TopicsAPI
    second = library.add_topic(rt.store, rt.embedder, "storage", "home batteries")
    poison(monkeypatch, TopicsAPI, "_facts", lambda self, topic, *a: topic.id == second)
    data = web.get("/api/topics").json()
    [u] = unreadable(data["topics"])
    assert u["id"] == second and u["name"] == "storage"
    check_mark(u, "topic")
    assert [t["name"] for t in data["topics"] if "unreadable" not in t] == ["energy"]


def test_one_card_that_cannot_be_read_is_listed_and_never_reaches_a_cub(web, rt,  # noqa: F811
                                                                          monkeypatch):
    from kranto.core import api as core_api
    from kranto.web import ideas_api
    oids = obs_ids(rt.store)
    add_theme(rt.store, "lin-a", 4, {"energy": 4})
    cards = [add_card(rt.store, f"Card {n}", {"title": f"Card {n}", "thesis": "t.",
                                              "evidence": [{"n": 1, "claim": "c",
                                                            "observation_id": oids[0]}]})
             for n in range(3)]
    poison(monkeypatch, ideas_api, "card_record", lambda idea, *a: idea["id"] == cards[1])
    ideas = web.get("/api/ideas").json()["ideas"]
    [u] = unreadable(ideas)
    assert u["id"] == cards[1] and u["title"] == "Card 1" and "intake" not in u
    check_mark(u, "idea")
    assert len(ideas) == 3
    assert web.get(f"/api/ideas/{cards[1]}").status_code == 500
    assert web.get(f"/api/ideas/{cards[0]}").status_code == 200

    class Ctx:
        store = rt.store
    got = core_api.ideas_list(Ctx(), {})["ideas"]
    assert sorted(i["id"] for i in got) == [cards[0], cards[2]]
    assert web.get("/api/review/queue").status_code == 200


def test_one_observation_that_cannot_be_read_is_listed_as_such(web, rt, monkeypatch):  # noqa: F811
    from kranto.web import app as app_mod
    oids = obs_ids(rt.store)
    real = app_mod._public
    monkeypatch.setattr(app_mod, "_public", lambda r, threshold: (_ for _ in ()).throw(
        TypeError("x")) if r.get("id") == oids[1] else real(r, threshold))
    results = web.get("/api/observations").json()["results"]
    [u] = unreadable(results)
    assert u["id"] == oids[1]
    check_mark(u, "observation")
    assert len(results) == 4
    assert web.get("/api/observations?q=solar").status_code == 200
    assert web.get("/api/today").status_code == 200


def test_themes_trend_summaries_and_runs_contain_a_bad_row(seeded, rt, monkeypatch):  # noqa: F811
    from kranto.web import app as app_mod
    from kranto.web import kranto_api
    first = seeded.get("/api/clusters").json()["clusters"][0]["lineage_id"]
    real = kranto_api._synthesis
    calls = {"n": 0}

    def synth(row):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("x")
        return real(row)
    monkeypatch.setattr(kranto_api, "_synthesis", synth)
    clusters = seeded.get("/api/clusters").json()["clusters"]
    [u] = unreadable(clusters)
    check_mark(u, "theme")
    assert u["lineage_id"] == first and len(clusters) > 1
    monkeypatch.setattr(app_mod, "_rollup", lambda r: (_ for _ in ()).throw(TypeError("x")))
    rollups = seeded.get("/api/rollups").json()["results"]
    assert rollups and all(check_mark(r, "trend summary") for r in rollups)
    health = seeded.get("/api/health")
    assert health.status_code == 200


def test_activity_lists_a_run_it_cannot_read(rt, web, monkeypatch):  # noqa: F811
    from kranto.activity import read as activity_read
    for n, kind in enumerate(("ingest", "snapshot", "ideas")):
        rt.store.insert("runs", dict(run_uuid=f"r-{n}", kind=kind, status="ok",
                                     started_at="2026-09-24T10:00:00Z",
                                     finished_at="2026-09-24T10:01:00Z", summary="{}"))
    real = activity_read.Reader.view

    def view(self, **kw):
        if kw["uuid"] == "r-1":
            raise TypeError("x")
        return real(self, **kw)
    monkeypatch.setattr(activity_read.Reader, "view", view)
    out = web.get("/api/activity?hours=10000").json()
    [u] = unreadable(out["recent"])
    assert u["uuid"] == "r-1" and u["kind"] == "snapshot"
    check_mark(u, "run")
    assert len(out["recent"]) == 3


def test_a_fix_row_has_an_error_id_whose_report_send_this_error_files(rt, web):  # noqa: F811
    for n in range(2):
        rt.store.insert("runs", dict(run_uuid=f"f-{n}", kind="snapshot", status="failed",
                                     started_at="2026-09-24T10:00:00Z",
                                     finished_at=f"2026-09-24T10:0{n + 1}:00Z", summary="{}",
                                     error=f"database is locked at {Path.home()}/x"))
    [f] = web.get("/api/activity?hours=10000").json()["failing"]
    assert f["kind"] == "snapshot" and len(f["error_id"]) == 8
    rep = web.get(f"/api/errors/{f['error_id']}").json()
    assert rep["record"]["kind"] == "failure" and rep["record"]["where"] == "activity:snapshot"
    assert str(Path.home()) not in rep["body"] and "database is locked" in rep["body"]


def test_news_briefs_list_a_brief_whose_items_are_not_json(rt, web):  # noqa: F811
    """Read through its contract (kranto.features.news.stored), items that are not JSON are
    none: the brief is listed, readable, and the problem noted once. A
    reader that raises on a brief is still contained: the next test's map and features."""
    from kranto import stored
    stored.base.forget_problems()
    [t] = library.active_topics(rt.store)
    for n in range(2):
        rt.store.insert("news_briefs", dict(
            topic_id=t.id, status="ok", period_start="2026-09-23T00:00:00Z",
            period_end="2026-09-24T00:00:00Z", items="{not json" if n else "[]", quiet=0,
            search="{}", checks="{}", trigger="schedule",
            created_at=f"2026-09-24T0{n}:00:00Z"))
    r = web.get("/api/f/news/briefs.list")
    assert r.status_code == 200
    briefs = r.json()["briefs"]
    assert len(briefs) == 2 and unreadable(briefs) == []
    assert any(p.where == "news_briefs.items" and p.expected == "JSON"
               for p in stored.problems_seen())
    assert web.get("/api/f/news/latest").status_code == 200


def test_tickets_and_cubs_contain_a_bad_row(rt, monkeypatch):  # noqa: F811
    from kranto.core import tickets
    from kranto.core.cubs import registry as cub_registry
    from kranto.core.cubs import views

    class Tickets:
        def query(self, sql, params=()):
            return [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(tickets, "get", lambda store, rid, now=None: (
        _ for _ in ()).throw(TypeError("x")) if rid == 2 else {"id": rid, "state": "open"})
    out = tickets.listing(Tickets(), unreadable=True)
    assert out[0] == {"id": 1, "state": "open"}
    check_mark(out[1], "ticket")
    # a cub's and a feature's reads, and the counts, never see it
    assert tickets.listing(Tickets()) == [{"id": 1, "state": "open"}]

    monkeypatch.setattr(cub_registry, "latest_rows", lambda store: {
        "aaa": {"state": "on"}, "bbb": {"state": "on"}})
    monkeypatch.setattr(views, "row", lambda rt_, cid, r=None: (
        _ for _ in ()).throw(TypeError("x")) if cid == "bbb" else {"id": cid})
    cubs = views.listing(rt)["cubs"]
    assert cubs[0] == {"id": "aaa"} and cubs[1]["id"] == "bbb"
    check_mark(cubs[1], "cub")


def test_the_map_features_and_jobs_contain_a_bad_row(seeded, rt, monkeypatch):  # noqa: F811
    from kranto.core import registry
    from kranto.core.cubs import install
    from kranto.map import read as map_read

    # a cluster that cannot be read is left out of every page that reads the map; the map answers
    snap = map_read.latest(rt.store)
    n = len(map_read.clusters(rt.store, snap["id"]))
    first = rt.store.query_one("SELECT cluster FROM clusters WHERE snapshot_id = ? "
                               "ORDER BY size DESC", (snap["id"],))["cluster"]
    real_cluster = map_read._cluster
    monkeypatch.setattr(map_read, "_cluster", lambda r: (_ for _ in ()).throw(ValueError(
        "keywords do not parse")) if r["cluster"] == first else real_cluster(r))
    assert len(map_read.clusters(rt.store, snap["id"])) == n - 1
    for path in ("/api/map", "/api/clusters", "/api/topics", "/api/today"):
        assert seeded.get(path).status_code == 200, path
    # a feature that cannot be described is listed as such
    real = registry._described
    monkeypatch.setattr(registry, "_described", lambda rt_, f: (_ for _ in ()).throw(
        TypeError("x")) if f.id == "news" else real(rt_, f))
    feats = seeded.get("/api/features").json()["features"]
    [u] = unreadable(feats)
    assert u["id"] == "news" and u["title"]
    check_mark(u, "feature")
    # an install job: listed on the page, left out of what reads its fields
    monkeypatch.setattr(install, "job", lambda store, cfg, i: (_ for _ in ()).throw(
        TypeError("x")) if i == "j2" else {"id": i})

    class Jobs:
        def query(self, sql, params=()):
            return [{"job_id": "j1"}, {"job_id": "j2"}]
    listed = install.jobs(Jobs(), rt.cfg, unreadable=True)
    assert listed[0] == {"id": "j1"} and check_mark(listed[1], "job")
    assert install.jobs(Jobs(), rt.cfg) == [{"id": "j1"}]


def test_home_slots_carry_an_error_id(rt, monkeypatch):  # noqa: F811
    from kranto.core import home
    monkeypatch.setattr(home, "BUILTIN", {**home.BUILTIN, "spend": lambda *a: (
        _ for _ in ()).throw(TypeError("x"))})
    slot = home._builtin_slot(rt, {"id": "spend", "size": "S"}, {})
    assert slot["state"] == "error" and len(slot["error_id"]) == 8


# -- the error answer and the report ----------------------------------------------------------


TOKEN = "sk-ant-" + "q" * 32


@pytest.fixture
def broken(rt, monkeypatch):  # noqa: F811
    """A server whose ``/api/topics`` and ``/api/status`` raise past every row."""
    from kranto.web import topics_api
    monkeypatch.setattr(topics_api.TopicsAPI, "list_topics",
                        lambda self, request: {}[f"{Path.home()}/notes {TOKEN}"])
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client


def test_a_response_that_still_fails_answers_kranto_error_json(broken, rt, caplog):  # noqa: F811
    with caplog.at_level(logging.ERROR):
        answers = [broken.get("/api/topics") for _ in range(3)]
    for r in answers:
        assert r.status_code == 500
        body = r.json()
        assert body["version"] == __version__ and body["exception"] == "KeyError"
        assert f"error {body['error_id']}" in body["error"]
        assert body["report"] == f"/api/errors/{body['error_id']}"
        assert r.headers["x-frame-options"] == "DENY"
    eid = answers[0].json()["error_id"]
    assert {r.json()["error_id"] for r in answers} == {eid}
    assert sum(eid in r.getMessage() for r in caplog.records) == 1
    # kept once, in the data folder, for kranto report and the reports that read it
    kept = [json.loads(x) for x in (rt.cfg.data_dir / "errors.jsonl").read_text().splitlines()]
    assert [k["id"] for k in kept] == [eid]
    assert kept[0]["where"] == "GET /api/topics" and kept[0]["kind"] == "response"


def test_the_report_is_what_send_this_error_files_and_nothing_else(broken, rt):  # noqa: F811
    eid = broken.get("/api/topics").json()["error_id"]
    rep = broken.get(f"/api/errors/{eid}").json()
    assert rep["id"] == eid and rep["title"].startswith(f"Error {eid}: KeyError")
    body = rep["body"]
    code = body.split("```\n")[1].split("```")[0].splitlines()
    assert code and all(re.fullmatch(r"(kranto|kranto.page)(\.[a-z_0-9]+)+:\d+", f)
                        for f in code), code
    assert rep["record"]["frames"] == code
    assert f"Kranto: {__version__}" in body and "OS: " in body and "kranto doctor: " in body
    # the message is errtrace's template: what it quoted (a path, a key) never survives
    assert str(Path.home()) not in body and TOKEN not in body and "notes" not in body
    assert "- message, as a template: " in body
    assert rep["url"].startswith("https://github.com/iddv/kranto/issues/new?template="
                                 "feedback.yml&title=")
    listed = broken.get("/api/errors").json()
    assert [e["id"] for e in listed["errors"]] == [eid]
    # the answers have the shapes web/types.py says, the error answer too
    from kranto.web import types as T

    from .test_web_types import problems
    assert problems(rep, T.ErrorReport) == [] and problems(listed, T.Errors) == []
    assert problems(broken.get("/api/topics").json(), T.ErrorAnswer) == []
    assert broken.get("/api/errors/0000beef").status_code == 404


def test_a_page_that_fails_answers_the_error_page(rt, monkeypatch):  # noqa: F811
    from kranto.web import app as app_mod
    monkeypatch.setattr(app_mod.App, "feed", lambda self, request: (_ for _ in ()).throw(
        ValueError(f"cannot read {Path.home()}/feeds {TOKEN}")))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.get("/feed.xml")
    assert r.status_code == 500 and r.headers["content-type"].startswith("text/html")
    eid = r.text.split("error ")[1][:8]
    assert f"Kranto {__version__} · error {eid}" in r.text
    assert "Try again" in r.text and "Send this error" in r.text
    assert f"/#/today?send_error={eid}" in r.text
    assert "ValueError" in r.text and TOKEN not in r.text and str(Path.home()) not in r.text


# -- the ids and the file ------------------------------------------------------------------------


def _raise(n):
    if n is None:
        return f"{n:.2f}"
    return n


def test_an_error_id_is_the_same_for_the_same_bug_and_carries_no_value():
    ids, frames = set(), []
    for secret in ("sk-ant-" + "x" * 30, "/home/someone/private"):
        try:
            _raise(None) if secret else None
        except TypeError as exc:
            ids.add(rowsafe.error_id(exc))
            frames = rowsafe.frames(exc)
    assert len(ids) == 1
    assert frames == [] or all(":" in f and "/" not in f for f in frames)


def test_the_file_keeps_each_id_once_and_at_most_keep_lines(tmp_path, monkeypatch):
    rowsafe.configure(tmp_path)
    monkeypatch.setattr(rowsafe, "KEEP", 5)
    try:
        from kranto import errtrace
        for n in range(8):
            exc = TypeError(str(n))
            monkeypatch.setattr(errtrace, "scrub", lambda e, n=n: errtrace.Trace(
                "TypeError", (), "", f"{n:08x}{0:08x}"))
            rowsafe.note(exc, "x")
            rowsafe.note(exc, "x")
        lines = (tmp_path / "errors.jsonl").read_text().splitlines()
        assert [json.loads(x)["id"] for x in lines] == [f"{n:08x}" for n in range(3, 8)]
        assert rowsafe.find("00000007")["where"] == "x"
    finally:
        rowsafe.configure(None)


def test_kranto_report_writes_the_report_to_one_file_and_prints_its_path(tmp_path, monkeypatch,
                                                                       capsys):
    from kranto import launcher

    from .test_kranto import make_host
    user = tmp_path / "u"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    home = user / ".kranto"
    launcher.make_home(home, 8800, user)
    rec = {"id": "1a2b3c4d", "at": "2026-10-23T16:00:00Z", "kind": "row",
           "where": "list:source", "exception": "TypeError",
           "frames": ["kranto.source_health._status:209"], "version": "0.5.20"}
    (home / "data" / "errors.jsonl").write_text(json.dumps(rec) + "\n")
    args = argparse.Namespace(home=str(home), error_id=None, no_doctor=True)
    assert launcher.cmd_report(args, make_host(user)) == 0
    out = Path(capsys.readouterr().out.strip())
    assert out.parent == home / "reports" and out.name.startswith("kranto-report-1a2b3c4d-")
    text = out.read_text()
    assert "# Error 1a2b3c4d: TypeError in list:source" in text
    assert "kranto.source_health._status:209" in text and "Kranto: 0.5.20" in text
    assert "kranto doctor: not run yet" in text
    args = argparse.Namespace(home=str(home), error_id="ffffffff", no_doctor=True)
    assert launcher.cmd_report(args, make_host(user)) == 1


def test_the_doctor_line_is_counts_and_names_never_details(tmp_path):
    from kranto.doctor import Check
    rowsafe.keep_doctor(tmp_path, [Check("ok", "key", "sk-" + "ant-" + "x" * 24),
                                   Check("warn", "gh", "/home/someone/.config/gh"),
                                   Check("FAIL", "bwrap", "not installed")])
    line = rowsafe.doctor_line(tmp_path)
    assert line.startswith("1 ok, 1 warn, 1 fail (") and "warn: gh; FAIL: bwrap" in line
    assert "sk-ant" not in line and "/home" not in line
    assert rowsafe.doctor_line(tmp_path / "none") == "not run yet (kranto doctor)"
