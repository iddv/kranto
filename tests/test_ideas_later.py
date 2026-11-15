"""Ideas on cards alone (cut 4, package HOUR's H1): Later is ``idea.later`` in
the server, a card's ``state`` on Ideas comes from the server's own rows, and the empty list says
when the first cards come. Nothing here reaches the build loop's ledger."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from kranto import grades, outcomes
from kranto.core import verbs
from kranto.store import iso, utcnow
from kranto.web.ideas_api import card_state, drafts_of

from .conftest import web_client
from .test_ideas_api import add_card, cards, obs_ids, old_card  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture


def _web(rt):  # noqa: F811
    from kranto.web.app import create_app
    return web_client(create_app(rt), "http://127.0.0.1:8765")


def _card(rt, title="Padel court finder"):  # noqa: F811
    return add_card(rt.store, title, old_card(rt.store, obs_ids(rt.store)[:2]))


def test_later_puts_a_card_off_for_a_week_and_zero_brings_it_back(rt):  # noqa: F811
    n = _card(rt)
    with _web(rt) as web:
        r = web.post(f"/api/ideas/{n}/later", json={})
        assert r.status_code == 200
        got = r.json()
        assert got["state"] == "later" and got["outcome"]["value"] == "later"
        until = got["later_until"]
        assert until[:10] == iso(utcnow() + timedelta(days=7))[:10]
        card = web.get(f"/api/ideas/{n}").json()
        assert card["state"] == "later" and card["later_until"] == until
        from kranto.web import types as T

        from .test_web_types import problems
        assert problems(got, T.IdeaLater) == []
        r = web.post(f"/api/ideas/{n}/later", json={"days": 0})
        assert r.json()["state"] == "waiting" and r.json()["outcome"]["value"] == "open"
        card = web.get(f"/api/ideas/{n}").json()
        assert card["state"] == "waiting" and card["later_until"] is None
        assert web.post(f"/api/ideas/{n}/later", json={"days": 2})
        assert web.post("/api/ideas/9999/later", json={}).status_code == 404
        for bad in (-1, 400, "7", True):
            assert web.post(f"/api/ideas/{n}/later", json={"days": bad}).status_code == 400
    rows = rt.store.query("SELECT kind, value, detail, source FROM outcomes WHERE idea_id = ? "
                          "ORDER BY id", (n,))
    assert [(r["kind"], r["value"], r["source"]) for r in rows] == [
        ("decision", "later", "ui"), ("decision", "open", "ui"), ("decision", "later", "ui")]
    assert json.loads(rows[2]["detail"])["days"] == 2


def test_later_comes_back_by_itself_once_its_day_has_passed(rt):  # noqa: F811
    n = _card(rt)
    outcomes.later(rt.store, n, 7, now=utcnow() - timedelta(days=8))
    kinds = outcomes.by_kind(rt.store, [n])[n]
    assert outcomes.later_until(kinds) is None
    assert card_state(None, kinds, []) == "waiting"


def test_later_writes_kranto_alone_never_the_build_loops_ledger(rt, tmp_path):  # noqa: F811
    # the route touches no file outside the server's database: the loop's ledger is not opened
    import os
    n = _card(rt)
    loop = tmp_path / "loop.db"
    loop.write_bytes(b"ledger")
    before = (loop.read_bytes(), os.stat(loop).st_mtime_ns)
    with _web(rt) as web:
        assert web.post(f"/api/ideas/{n}/later", json={"days": 7}).status_code == 200
    assert (loop.read_bytes(), os.stat(loop).st_mtime_ns) == before


def test_a_later_decision_needs_a_time(rt):  # noqa: F811
    n = _card(rt)
    with pytest.raises(ValueError, match="until"):
        outcomes.add(rt.store, n, {"kind": "decision", "value": "later", "detail": {}})
    with pytest.raises(ValueError, match="days"):
        outcomes.later(rt.store, n, 9999)


@pytest.mark.parametrize("grade,kinds,drafts,want", [
    (None, {}, [], "waiting"),
    ("useful", {}, [], "waiting"),
    ("not_useful", {}, [], "passed"),                                 # Pass is the grade
    ("wrong", {}, ["needs_confirm"], "passed"),
    (None, {}, ["needs_confirm"], "posted"),                          # a draft about it
    (None, {}, ["declined"], "waiting"),
    (None, {"publish": {"id": 3, "kind": "publish", "value": "public", "detail": {},
                 "created_at": "2026-10-01T00:00:00Z"}}, [],
     "passed"),                                                       # the loop built it
    (None, {"verdict": {"id": 4, "kind": "verdict", "value": "closed", "detail": {}}}, [],
     "passed"),
])
def test_a_cards_state(grade, kinds, drafts, want):
    assert card_state(grade, kinds, drafts) == want


def test_states_on_the_list_and_a_draft_makes_a_card_posted(rt):  # noqa: F811
    store = rt.store
    waiting, later, passed, posted = (_card(rt, t) for t in ("W", "L", "P", "D"))
    outcomes.later(store, later, 7)
    grades.add_grade(store, "idea", passed, "not_useful")
    store.insert("cub_tickets", {"cub": "blog", "kind": "post.draft", "trust": "first-party",
                                 "fields": "{}", "fields_hash": "h",
                                 "because": json.dumps({"ideas": [posted]}),
                                 "expires_at": "9999-12-31T00:00:00Z",
                                 "created_at": iso(utcnow())})
    assert drafts_of(store, [posted, waiting]) == {posted: ["needs_confirm"]}
    with _web(rt) as web:
        got = {c["id"]: c["state"] for c in web.get("/api/ideas").json()["ideas"]}
    assert got[waiting] == "waiting" and got[later] == "later"
    assert got[passed] == "passed" and got[posted] == "posted"


def test_the_empty_list_says_when_the_first_cards_come(rt):  # noqa: F811
    with _web(rt) as web:
        got = web.get("/api/ideas").json()
        assert got["count"] == 0
        assert got["first"]["needed"] == 30 and got["first"]["observations"] == 4
        assert got["first"]["words"] == "After the map, once 30 items are kept. So far: 4."
        assert "first" not in web.get("/api/ideas?topic=1").json()
        _card(rt)
        assert "first" not in web.get("/api/ideas").json()


def test_idea_later_is_a_verb_of_every_door():
    v = verbs.get("idea.later")
    assert v is not None and v.path == "/api/ideas/{idea_id}/later" and v.method == "POST"
    assert v.subject == "idea" and v.ladder == "reversible"
    assert [f.name for f in v.fields] == ["days"]
