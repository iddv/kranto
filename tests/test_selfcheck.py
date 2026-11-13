"""The post-update self-check: ``GET /api/selfcheck/paths`` lists every
page the server serves on this install's data (each list, every topic's and source's page, the
core's reads, each feature's), never what reaches past the machine; ``route_check`` reads them
all and names a page that answers 500 with its error's id; ``kranto doctor --routes`` says the
same and exits 1."""

import argparse

import pytest

from kranto import launcher, library, rowsafe
from kranto.update import apply
from kranto.web import selfcheck_api

from .test_web import rt, web  # noqa: F401 - fixtures


def via(client):
    """``route_check``'s getter over the test client (no port, no network)."""
    def get(url, timeout):
        r = client.get(url.removeprefix("http://test"))
        try:
            body = r.json()
        except ValueError:
            body = None
        return r.status_code, body if isinstance(body, dict) else None
    return get


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rowsafe, "_seen", {})


def test_the_list_is_every_page_on_this_installs_data_and_nothing_that_leaves(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    [s] = library.list_sources(rt.store)
    body = web.get("/api/selfcheck/paths").json()
    paths = body["paths"]
    assert paths[:6] == ["/api/status", "/api/home", "/api/topics", "/api/sources",
                         "/api/today", "/api/activity"]
    assert f"/api/topics/{t.id}" in paths and f"/api/sources/{s.id}" in paths
    assert "/api/ideas" in paths and "/api/observations" in paths and "/api/errors" in paths
    assert "/api/read/topics.list" in paths
    for gone in selfcheck_api.EXCLUDED:
        assert gone not in paths
    assert not [p for p in paths if "{" in p]
    assert len(paths) == len(set(paths))
    assert body["excluded"]["/api/websearch"].startswith("a live web search")


def test_a_clean_install_passes(web, rt):  # noqa: F811
    # an install has its config file (Settings' reads say 500 without one, which never happens
    # to a home kranto up or kranto adopt made)
    (rt.cfg.root / "kranto.yaml").write_text("budget:\n  monthly_usd: 10\n")
    res = apply.route_check("http://test", get=via(web))
    assert res["ok"], res["failed"]
    assert res["checked"] == res["of"] > 30 and res["unchecked"] == 0


def test_a_page_that_answers_500_on_this_data_fails_with_its_error_id(rt, monkeypatch):  # noqa: F811
    from kranto.web import topics_api
    from kranto.web.app import create_app

    from .conftest import web_client
    [t] = library.active_topics(rt.store)
    (rt.cfg.root / "kranto.yaml").write_text("budget:\n  monthly_usd: 10\n")
    real = topics_api.TopicsAPI.one_topic

    def one_topic(self, request):          # the deliberately broken build: raises on a topic page
        if request.path_params["topic_id"] == t.id:
            raise TypeError("unsupported format string passed to NoneType.__format__")
        return real(self, request)
    monkeypatch.setattr(topics_api.TopicsAPI, "one_topic", one_topic)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        res = apply.route_check("http://test", get=via(client))
    assert not res["ok"]
    [f] = res["failed"]
    assert f["path"] == f"/api/topics/{t.id}" and f["status"] == 500
    assert f["exception"] == "TypeError" and len(f["error_id"]) == 8
    assert rowsafe.find(f["error_id"])["where"] == "GET /api/topics/{topic_id:int}"
    assert apply.selfcheck_words(res, "0.5.23") == (
        f"0.5.23 broke on your data: GET /api/topics/{t.id} answered 500 "
        f"(error {f['error_id']})")


def test_doctor_routes_says_each_failure_and_exits_1(tmp_path, monkeypatch, capsys):
    said = {"ok": False, "checked": 9, "of": 9, "unchecked": 0, "seconds": 2.0,
            "failed": [{"path": "/api/topics/7", "status": 500, "error_id": "1a2b3c4d"}]}
    seen = []
    monkeypatch.setattr(apply, "route_check", lambda base: seen.append(base) or said)
    args = argparse.Namespace(port=8799, json=False, routes=True)
    assert launcher.doctor_routes(tmp_path, args) == 1
    out = capsys.readouterr().out
    assert seen == ["http://127.0.0.1:8799"]
    assert "FAIL  routes         GET /api/topics/7 answered 500 (error 1a2b3c4d)" in out
    assert "GET /api/topics/7: 500 (error 1a2b3c4d: kranto report 1a2b3c4d)" in out
    monkeypatch.setattr(apply, "route_check", lambda base: {**said, "ok": True, "failed": []})
    assert launcher.doctor_routes(tmp_path, args) == 0
    assert "ok    routes         9 of 9 reads answered on your data in 2.0 s" in \
        capsys.readouterr().out
