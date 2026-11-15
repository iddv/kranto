"""The home's built-ins that are off by default: Spend, A topic (several,
each its own topic), Sources and Your grades answer in /api/home from one query each; a topic that
is gone is that slot's error, never the home's; News's The brief is a manifest widget of Kranto's
own, drawn by the same path as a cub's."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

from kranto import config as config_mod
from kranto.core import home, registry
from kranto.store import iso
from kranto.web.app import create_app

from .conftest import FIXED_NOW, web_client
from .test_today_api import observe, rt  # noqa: F401 - fixture

NOW = FIXED_NOW


def _app(rt, tmp_path, widgets):  # noqa: F811
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    rt.cfg = replace(rt.cfg, root=tmp_path)
    web = web_client(create_app(rt), "http://127.0.0.1:8765")
    return web, widgets


def _home(web, widgets) -> dict:
    r = web.post("/api/shell", json={"key": "shell.widgets", "value": widgets})
    assert r.status_code == 200, r.text
    return web.get("/api/home").json()["slots"]


def test_spend_says_watching_against_its_cap_and_tokens_today(rt, tmp_path):  # noqa: F811
    web, _ = _app(rt, tmp_path, None)
    with web:
        s = _home(web, [{"id": "spend", "size": "S"}])["0"]
    assert s["state"] == "ok"
    assert s["data"]["cap_usd"] == 10 and s["data"]["month_usd"] > 0
    assert set(s["data"]) == {"month_usd", "cap_usd", "tokens_today"}


def test_several_topics_each_its_own_newest_and_new_since_the_visit(rt, tmp_path):  # noqa: F811
    energy, tools = rt.ids["energy"][0], rt.ids["tools"][0]
    web, _ = _app(rt, tmp_path, None)
    with web:
        web.post("/api/seen", json={"at": iso(NOW - timedelta(hours=10))})
        s = _home(web, [{"id": "topic", "size": "S", "options": {"topic": energy}},
                        {"id": "topic", "size": "L", "options": {"topic": tools, "rows": 2}},
                        {"id": "topic", "options": {"topic": 999}}, {"id": "needs"}])
    a, b, gone = s["0"]["data"], s["1"]["data"], s["2"]
    assert a["topic"]["name"] == "energy" and len(a["rows"]) == 3          # S: three rows
    assert a["new"] == 5 and a["total"] >= 5
    assert a["rows"][0]["source"] == "Energy Feed" and a["rows"][0]["at"] >= a["rows"][1]["at"]
    assert b["topic"]["name"] == "tools" and len(b["rows"]) <= 2           # its own rows at most
    assert gone == {"state": "error", "error": "its topic is gone: pick another under ⋯"}
    assert "3" not in s                                                    # Needs you: the page's


def test_sources_and_a_retired_grades_widget(rt, tmp_path):  # noqa: F811
    """the "Your grades" built-in read the empty grades table and always said 0;
    it is retired. A home arranged with it still saves and draws, without it."""
    store = rt.store
    store.insert("runs", {"run_uuid": "r1", "kind": "ingest", "status": "ok",
                          "started_at": iso(NOW - timedelta(hours=2)),
                          "finished_at": iso(NOW - timedelta(hours=1)), "summary": "{}"})
    web, _ = _app(rt, tmp_path, None)
    with web:
        s = _home(web, [{"id": "sources"}, {"id": "grades"}])
    assert list(s) == ["0"]
    src = s["0"]["data"]
    assert src["watched"] == 3 and src["failing"] == [] and src["failing_n"] == 0
    assert src["last_read"] == iso(NOW - timedelta(hours=1))
    assert "grades" not in home.BUILTIN


def test_the_brief_is_news_widget_drawn_as_a_cubs(rt, tmp_path):  # noqa: F811
    news = registry.by_id("news")
    [w] = news.ui.widgets
    assert (w.id, w.kind, w.read, w.sizes) == ("brief", "rows", "widget_brief", ("M", "L"))
    energy = rt.ids["energy"][0]
    rt.store.insert("news_topics", {"topic_id": energy, "enabled": 1, "cadence": "daily",
                                    "hour": 7, "created_at": iso(NOW)})
    items = [{"headline": "Solar tariffs fall", "body": "b", "why": "w", "background": False},
             {"headline": "<b>Batteries</b>", "body": "b", "why": "w", "background": True}]
    rt.store.insert("news_briefs", {"topic_id": energy, "status": "ok", "items": json.dumps(items),
                                    "period_start": iso(NOW - timedelta(days=1)),
                                    "period_end": iso(NOW),
                                    "created_at": iso(NOW - timedelta(hours=1))})
    web, _ = _app(rt, tmp_path, None)
    with web:
        lib = web.get("/api/home").json()["library"]
        assert [x["id"] for g in lib if g["id"] == "news" for x in g["widgets"]] == ["news.brief"]
        s = _home(web, [{"id": "news.brief"}])["0"]
    assert s["state"] == "ok"
    rows = s["data"]["rows"]
    assert [r["title"] for r in rows] == ["Solar tariffs fall", "<b>Batteries</b>"]
    assert rows[0]["open"].startswith("news/b/") and rows[1]["tone"] == "quiet"
