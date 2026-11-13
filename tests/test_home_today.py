"""The home as one read: the date and one sentence, today's brief, the five
newest cards, the quiet line; While you were away after ``home.away_days`` without a visit, chosen
by rule from stored rows; and the home's own visit marker, ``home.visit``, moved only by
``POST /api/home/visit``."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, timedelta

import pytest

from kranto import config as config_mod
from kranto.config import ConfigError, HomeConfig, parse_home
from kranto.core import home
from kranto.store import iso
from kranto.web.app import create_app

from .conftest import FIXED_NOW, web_client
from .test_today_api import observe, rt  # noqa: F401 - fixtures

NOW = FIXED_NOW


@pytest.fixture(autouse=True)
def utc_day(monkeypatch):
    # "today" is the machine's local day; the tests read it in UTC
    monkeypatch.setattr(home, "LOCAL_TZ", UTC)


def _card(store, title: str, hours_ago: float) -> int:
    return store.insert("ideas", {
        "fingerprint": title, "origin": "cluster", "evidence_key": title, "input_ids": "[]",
        "title": title, "card": "{}", "score": 0.5, "status": "shown", "dropped": "[]",
        "created_at": iso(NOW - timedelta(hours=hours_ago))})


def _brief(store, topic: int, hours_ago: float, heads: list[str], status: str = "ok") -> int:
    items = [{"headline": h, "body": "b", "why": "w", "background": False,
              "sources": [{"kind": "obs", "source": "www.robotreport.example", "id": 1}]}
             for h in heads]
    return store.insert("news_briefs", {
        "topic_id": topic, "status": status, "items": json.dumps(items),
        "period_start": iso(NOW - timedelta(days=1)), "period_end": iso(NOW),
        "created_at": iso(NOW - timedelta(hours=hours_ago))})


def _visit(store, at, previous=None) -> None:
    store.set_setting(home.VISIT_KEY, json.dumps({"at": iso(at), "previous": previous}))


def _rt(rt, days=3):  # noqa: F811
    rt.cfg = replace(rt.cfg, home=HomeConfig(away_days=days))
    return rt


def test_the_ordinary_home_says_the_day_the_brief_the_cards_and_the_quiet_line(rt):  # noqa: F811
    energy = rt.ids["energy"][0]
    _brief(rt.store, energy, 2, ["Solar tariffs fall", "Grid storage doubles", "Wind", "Hydro"])
    _brief(rt.store, energy, 30, ["Yesterday's"])                       # not today's
    for n in range(7):
        _card(rt.store, f"card {n}", hours_ago=70 - n * 10)           # 10 h and 20 h: new
    rt.store.insert("runs", {"run_uuid": "r1", "kind": "ingest", "status": "ok",
                             "started_at": iso(NOW - timedelta(hours=3)),
                             "finished_at": iso(NOW - timedelta(hours=2)), "summary": "{}"})
    got = home.today(_rt(rt), now=NOW, next_run={"ideas": iso(NOW + timedelta(hours=10)),
                                                  "news": iso(NOW + timedelta(hours=19)),
                                                  "ingest": iso(NOW + timedelta(hours=1))})
    assert got["date"] == "2026-09-24" and got["away"] is None and got["visit"] is None
    assert got["sentence"] == "Today's brief is ready, and nothing waits for you."
    [t] = got["briefs"]["topics"]
    assert t["topic"]["name"] == "energy" and t["more"] == 1
    assert [i["title"] for i in t["items"]] == ["Solar tariffs fall", "Grid storage doubles",
                                                "Wind"]
    assert t["items"][0] == {"n": 0, "title": "Solar tariffs fall", "source": "robotreport.example"}
    # the newest brief of any day, for the console's first starter
    assert got["briefs"]["newest"]["name"] == "energy"
    ideas = got["ideas"]
    assert len(ideas["rows"]) == 5 and ideas["total"] == 7
    assert {r["title"] for r in ideas["rows"]} == {f"card {n}" for n in range(2, 7)}
    assert ideas["new"] == 2 and ideas["since"] is None                  # the last 24 hours
    assert all(r["grade"] is None for r in ideas["rows"])                 # none graded yet
    q = got["quiet"]
    assert q["read_at"] == iso(NOW - timedelta(hours=2)) and q["topics"] >= 1
    assert q["next"] == {"kind": "ideas", "words": "ideas", "at": iso(NOW + timedelta(hours=10))}


def test_the_home_shows_what_waits_on_ideas_a_later_or_posted_card_is_left_out(rt):  # noqa: F811
    """ H1 (SHELL's deferred row): the home's new ideas are Ideas' Waiting, by the server's
    own state; a card put off with Later, or one a draft was written about, is not among them"""
    from kranto import outcomes
    kept, later, posted = (_card(rt.store, t, hours_ago=5) for t in ("kept", "later", "posted"))
    outcomes.later(rt.store, later, 7, now=NOW)
    rt.store.insert("cub_tickets", {"cub": "blog", "kind": "post.draft", "trust": "first-party",
                                    "fields": "{}", "fields_hash": "h",
                                    "because": json.dumps({"ideas": [posted]}),
                                    "expires_at": "9999-12-31T00:00:00Z", "created_at": iso(NOW)})
    rows = home.today(_rt(rt), now=NOW)["ideas"]["rows"]
    assert [r["title"] for r in rows] == ["kept"]
    outcomes.later(rt.store, later, 0, now=NOW)                    # back now: on the home again
    assert {r["title"] for r in home.today(_rt(rt), now=NOW)["ideas"]["rows"]} == {"kept", "later"}


def test_the_sentence_counts_what_waits_and_says_when_there_is_no_brief(rt, monkeypatch):  # noqa: F811
    monkeypatch.setattr(home, "_waiting", lambda store, now: {"drafts": 1, "prepared": 0})
    assert home.today(_rt(rt), now=NOW)["sentence"] == \
        "No brief yet today, and one draft waits for you."
    # no brief today, one yesterday: today's list is empty, the newest still names its topic
    _brief(rt.store, rt.ids["tools"][0], 30, ["Yesterday's"])
    got = home.today(_rt(rt), now=NOW)["briefs"]
    assert got["topics"] == [] and got["newest"]["name"] == "tools"
    monkeypatch.setattr(home, "_waiting", lambda store, now: {"drafts": 2, "prepared": 1})
    assert home.today(_rt(rt), now=NOW)["sentence"] == \
        "No brief yet today, and two drafts and one prepared item wait for you."


def test_a_draft_offered_again_waits_as_the_one_thing_says(rt, monkeypatch):  # noqa: F811
    """the sentence counts the asks Needs you draws (``asks.latest``: open, or offered again),
    so it never says "nothing waits" over the one thing's draft"""
    from kranto.core import asks
    offered = [{"id": 7, "state": "expired"}]                    # its draft may be offered again
    monkeypatch.setattr(asks, "latest", lambda store, cub=None, **k: offered)
    assert home.today(_rt(rt), now=NOW)["waiting"] == {"drafts": 1, "prepared": 0}


def test_a_block_that_fails_is_that_blocks_never_the_homes(rt, monkeypatch):  # noqa: F811
    def broken(store, now):
        raise RuntimeError("the briefs table is not readable")
    monkeypatch.setattr(home, "_briefs", broken)
    got = home.today(_rt(rt), now=NOW)
    assert got["briefs"]["error"] == "the briefs table is not readable"
    assert got["briefs"]["error_id"] and got["sentence"] is None and "rows" in got["ideas"]


def test_after_the_away_days_one_list_of_five_best_cards_then_two_brief_leads(rt):  # noqa: F811
    energy, tools = rt.ids["energy"][0], rt.ids["tools"][0]
    _visit(rt.store, NOW - timedelta(days=9))
    old = _card(rt.store, "before you left", hours_ago=24 * 10)
    cards = [_card(rt.store, f"while away {n}", hours_ago=24 * 8 - n) for n in range(4)]
    _brief(rt.store, energy, 24 * 5, ["Five days ago"])
    _brief(rt.store, tools, 24 * 2, ["Two days ago", "second"])
    _brief(rt.store, energy, 24, ["Yesterday"])
    got = home.today(_rt(rt), now=NOW)
    a = got["away"]
    assert a["days"] == 9 and a["ideas"] == 4 and a["briefs"] == 3
    assert a["sentence"] == ("You were away for 9 days. Kranto wrote 3 briefs and 4 ideas. "
                             "These five are the best.")
    assert got["sentence"] == a["sentence"]
    kinds = [r["kind"] for r in a["rows"]]
    assert kinds == ["card", "card", "card", "brief", "brief"]
    assert old not in {r.get("id") for r in a["rows"]}
    assert {r["id"] for r in a["rows"][:3]} <= set(cards)
    assert [r["title"] for r in a["rows"][3:]] == ["Yesterday", "Two days ago"]
    assert a["rows"][4]["n"] == 0 and a["rows"][4]["topic"] == "tools"


def test_fewer_briefs_give_more_cards_and_fewer_things_fewer_rows(rt):  # noqa: F811
    for n in range(6):
        _card(rt.store, f"c{n}", hours_ago=72 - n)                        # the newest 67 h ago
    _visit(rt.store, NOW - timedelta(days=4))
    a = home.today(_rt(rt), now=NOW)["away"]
    assert [r["kind"] for r in a["rows"]] == ["card"] * 5                 # no brief: five cards
    _visit(rt.store, NOW - timedelta(hours=67, minutes=30))               # one card since
    a = home.today(_rt(rt, days=1), now=NOW)["away"]
    assert len(a["rows"]) == 1 and a["sentence"].endswith("Kranto wrote 1 idea. This is the best.")
    _visit(rt.store, NOW - timedelta(hours=66))                           # nothing since
    a = home.today(_rt(rt, days=1), now=NOW)["away"]
    assert a["rows"] == [] and a["sentence"] == "You were away for 2 days. Nothing new was written."


def test_not_away_before_the_away_days_and_never_without_a_marker(rt):  # noqa: F811
    assert home.today(_rt(rt), now=NOW)["away"] is None                    # never opened
    _visit(rt.store, NOW - timedelta(days=2, hours=23))
    assert home.today(_rt(rt), now=NOW)["away"] is None
    assert home.today(_rt(rt, days=2), now=NOW)["away"] is not None        # home.away_days
    rt.store.set_setting(home.VISIT_KEY, "not the marker")                 # read as never set
    assert home.today(_rt(rt, days=1), now=NOW)["away"] is None


def test_the_marker_moves_on_a_visit_and_new_counts_from_the_visit_before(rt):  # noqa: F811
    store = rt.store
    assert home.visit(store, NOW) == {"at": iso(NOW), "previous": None}
    later = NOW + timedelta(hours=2)                                       # the same visit
    assert home.visit(store, later) == {"at": iso(later), "previous": None}
    tomorrow = NOW + timedelta(days=1)                                     # a new one
    assert home.visit(store, tomorrow) == {"at": iso(tomorrow), "previous": iso(later)}
    _card(store, "new since then", hours_ago=-12)                          # made at NOW + 12 h
    got = home.today(_rt(rt), now=tomorrow + timedelta(minutes=5))
    assert got["ideas"]["since"] == iso(later) and got["ideas"]["new"] == 1
    # the reload a minute later still counts from the visit before
    got = home.today(_rt(rt), now=tomorrow + timedelta(minutes=6))
    assert got["ideas"]["since"] == iso(later)


def test_get_home_carries_the_new_home_and_post_visit_moves_the_marker(rt, tmp_path):  # noqa: F811
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    rt.cfg = replace(rt.cfg, root=tmp_path)
    web = web_client(create_app(rt), "http://127.0.0.1:8765")
    with web:
        got = web.get("/api/home").json()
        assert {"date", "sentence", "briefs", "ideas", "quiet", "away", "visit"} <= set(got)
        assert "slots" in got                     # the widgets, for one wave (cubs, FakeHost)
        r = web.post("/api/home/visit")
        assert r.status_code == 200 and r.json()["previous"] is None
        assert web.get("/api/home").json()["visit"]["at"] == r.json()["at"]


def test_home_away_days_is_a_whole_number_of_days():
    assert parse_home(None).away_days == 3 and parse_home({"away_days": 7}).away_days == 7


def test_all_n_on_the_home_is_ideas_waiting_count_no_dispatch_cards(rt, tmp_path):  # noqa: F811
    """the home said "All 143" (every ``shown`` row, the dispatch cards among them)
    beside Ideas' "52 ideas · 39 waiting". ``ideas.total`` is the number of cards
    ``GET /api/ideas`` puts in Waiting."""
    from kranto.ideate.dispatches import ORIGIN as DISPATCH_ORIGIN
    for n in range(3):
        _card(rt.store, f"card {n}", hours_ago=5 + n)
    for n in range(4):
        rt.store.insert("ideas", {
            "fingerprint": f"d{n}", "origin": DISPATCH_ORIGIN, "evidence_key": f"d{n}",
            "input_ids": "[]", "title": f"dispatch {n}", "card": "{}", "score": 0.5,
            "status": "shown", "dropped": "[]", "created_at": iso(NOW - timedelta(hours=n))})
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    rt.cfg = replace(rt.cfg, root=tmp_path)
    web = web_client(create_app(rt), "http://127.0.0.1:8765")
    with web:
        total = web.get("/api/home").json()["ideas"]["total"]
        listed = web.get("/api/ideas?embedding=ref").json()["ideas"]
    waiting = sum(1 for i in listed if i["state"] == "waiting")
    assert waiting == 3 and total == waiting
    for bad in (0, 61, 2.5, True, "3"):
        with pytest.raises(ConfigError, match="home.away_days"):
            parse_home({"away_days": bad})
    with pytest.raises(ConfigError):
        parse_home({"away": 3})
