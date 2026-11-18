"""Outcomes on idea cards (PLAN 4.7; migration 24) and what the weekly editor reads: the editor's
class on a card through POST /api/ideas/{id}/outcome, the card's latest outcome in /api/ideas,
one week's observations (``since``/``until``, ``kind=!beat``) and the card prompt's
``editor_notes``."""

import json
import sqlite3

import pytest

from kranto import outcomes
from kranto.ideate import cards as card_mod

from .test_ideas_api import add_card, cards  # noqa: F401 - fixtures
from .test_ideate import card96
from .test_web import rt, web  # noqa: F401 - fixtures


def editor(value="repo idea for Receipts", week="2026-W41", why="gate 6: already built"):
    return {"kind": "editor", "value": value, "detail": {"week": week, "why": why}}


def loop_step(kind, value, **detail):
    return {"kind": kind, "value": value, "detail": {"idea": "i235df527", **detail}}


def old_row(store, idea_id: int, body: dict) -> int:
    """An outcome row as the build loop (and its weekly editor) wrote it before the cut: no
    writer of Kranto takes these kinds any more (CUT, ``outcomes.LOOP_ONLY``)."""
    from kranto.store import iso, utcnow
    detail = body.get("detail", {})
    return store.insert("outcomes", {
        "idea_id": idea_id, "kind": body["kind"], "value": body["value"],
        "detail": detail if isinstance(detail, str) else json.dumps(detail, sort_keys=True),
        "source": body.get("source", "kranto.page"), "created_at": iso(utcnow())})


def test_an_old_editor_outcome_still_lands_on_the_card(web, rt, cards):  # noqa: F811
    old_row(rt.store, cards["new"], editor())
    card = web.get(f"/api/ideas/{cards['new']}").json()
    assert card["editor"]["value"] == "repo idea for Receipts" and card["outcome"] == card["editor"]
    assert card["editor"]["detail"] == {"week": "2026-W41", "why": "gate 6: already built"}
    old_row(rt.store, cards["new"], editor("nominee", "2026-W42", None))
    old_row(rt.store, cards["new"], {"kind": "pitch", "value": "accepted",
                                     "detail": {"buildability": 0.8}})
    listed = {c["id"]: c for c in web.get("/api/ideas").json()["ideas"]}
    assert listed[cards["new"]]["editor"]["value"] == "nominee"
    assert listed[cards["new"]]["outcome"]["kind"] == "pitch"
    assert listed[cards["old"]]["editor"] is None and listed[cards["old"]]["outcome"] is None
    assert [o["value"] for o in outcomes.history(rt.store, cards["new"])] == [
        "repo idea for Receipts", "nominee", "accepted"]


def test_the_loops_old_steps_still_say_what_was_built(web, rt, cards):  # noqa: F811
    """CON L1, read after the cut: the rows the loop wrote still say ``built`` ("built ->
    Repo Recall"), and none once the owner's verdict is newer; no new loop row is taken."""
    new, old = cards["new"], cards["old"]
    for body in (loop_step("intake", "taken in"), loop_step("pitch", "accepted"),
                 loop_step("build", "building", round=1), loop_step("gate", "ready", round=1),
                 loop_step("publish", "published", repo="jo-example/repo-recall",
                           url="https://github.com/jo-example/repo-recall", version="0.1.0")):
        old_row(rt.store, new, body)
    for body in (loop_step("build", "building", round=1), loop_step("verdict", "closed")):
        old_row(rt.store, old, body)
    listed = {c["id"]: c for c in web.get("/api/ideas").json()["ideas"]}
    card = listed[new]
    assert sorted(card["outcomes"]) == ["build", "gate", "intake", "pitch", "publish"]
    assert card["outcomes"]["build"]["detail"] == {"idea": "i235df527", "round": 1}
    built = card["built"]
    assert (built["state"], built["kind"], built["idea"], built["repo"], built["url"]) == (
        "published", "publish", "i235df527", "jo-example/repo-recall",
        "https://github.com/jo-example/repo-recall")
    assert listed[old]["built"] is None and listed[old]["outcomes"]["verdict"]["value"] == "closed"
    ids = outcomes.by_kind(rt.store, [new, old, 99999])
    assert set(ids) == {new, old} and outcomes.built(ids.get(99999)) is None
    # the loop's kinds take no new row (CUT)
    for kind in outcomes.LOOP_ONLY:
        r = web.post(f"/api/ideas/{old}/outcome", json=loop_step(kind, "building"))
        assert r.status_code == 400 and "not part of Kranto any more" in r.json()["error"], kind
    assert len(outcomes.history(rt.store, old)) == 2


def test_built_reads_any_stored_shape(rt, cards):  # noqa: F811
    """The RCA rule: a stored value's shape is never assumed (a detail that is not an object, a
    repo that is not text, a null)."""
    store = rt.store
    old_row(store, cards["new"], {"kind": "publish", "value": "public", "detail": "[1, 2]"})
    old_row(store, cards["old"], {"kind": "publish", "value": "public",
                                  "detail": {"repo": 7, "url": None, "idea": ["x"]}})
    got = outcomes.by_kind(store, [cards["new"], cards["old"]])
    a, b = outcomes.built(got[cards["new"]]), outcomes.built(got[cards["old"]])
    assert a["state"] == "public" and a["repo"] is None and a["idea"] is None
    assert b["repo"] is None and b["url"] is None and b["idea"] is None
    assert outcomes.built({"publish": None, "build": "odd"}) is None
    assert outcomes.built("not a mapping") is None


def test_a_cub_reads_a_cards_old_outcome_and_what_was_built(rt, cards):  # noqa: F811
    from kranto.core import api
    old_row(rt.store, cards["new"], loop_step("publish", "public", repo="jo-example/x",
                                              url="https://github.com/jo-example/x"))
    ctx = type("Ctx", (), {"store": rt.store})()
    got = api.ideas_get(ctx, {"id": cards["new"]})
    assert got["built"] == {"state": "public", "repo": "jo-example/x", "url": "https://github.com/jo-example/x"}
    assert got["outcome"]["kind"] == "publish" and got["outcome"]["at"]
    other = api.ideas_get(ctx, {"id": cards["old"]})
    assert other["built"] is None and other["outcome"] is None


def test_outcomes_are_append_only(rt, cards):  # noqa: F811
    outcomes.later(rt.store, cards["new"], 3)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        rt.store.query("UPDATE outcomes SET value = 'note'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        rt.store.query("DELETE FROM outcomes")
    assert [o["value"] for o in outcomes.history(rt.store, cards["new"])] == ["later"]


@pytest.mark.parametrize("body, words", [
    ({"kind": "mood", "value": "x"}, "kind is one of decision, signal_external"),
    ({"kind": "editor", "value": "note", "detail": {"week": "2026-W41"}}, "build loop's"),
    ({"kind": "signal_external", "value": "", "detail": {}}, "value is"),
    ({"kind": "decision", "value": "later", "detail": {"until": "soon"}}, "ISO time"),
    ({"kind": "signal_external", "value": "ok", "detail": "text"}, "detail is an object"),
    ({"kind": "signal_external", "value": "ok", "detail": {"x": "y" * 5000}}, "at most"),
    ({"kind": "signal_external", "value": "ok", "source": "someone"}, "source is one of"),
])
def test_a_wrong_outcome_is_refused_with_the_reason(web, cards, body, words):  # noqa: F811
    r = web.post(f"/api/ideas/{cards['new']}/outcome", json=body)
    assert r.status_code == 400 and words in r.json()["error"]


def test_an_outcome_needs_a_card_an_object_and_the_same_origin(web, cards):  # noqa: F811
    ok = {"kind": "signal_external", "value": "a link", "source": "ui"}
    assert web.post("/api/ideas/99999/outcome", json=ok).status_code == 404
    assert web.post(f"/api/ideas/{cards['new']}/outcome", json=[1]).status_code == 400
    r = web.post(f"/api/ideas/{cards['new']}/outcome", json=ok,
                 headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert web.post(f"/api/ideas/{cards['new']}/outcome", json=ok).status_code == 200


def test_one_weeks_observations_without_beats(web):  # noqa: F811
    every = web.get("/api/observations?sort=signal&limit=10").json()
    assert every["total"] == 4
    signals = [o["signal"] for o in every["results"]]
    assert signals == sorted(signals, reverse=True)
    assert web.get("/api/observations?kind=beat").json()["total"] == 4
    assert web.get("/api/observations?kind=!beat").json()["total"] == 0
    assert web.get("/api/observations?kind=!sharp_signal").json()["total"] == 4
    assert web.get("/api/observations?until=2000-01-01T00:00:00Z").json()["total"] == 0
    assert web.get("/api/observations?since=2000-01-01T00:00:00Z"
                   "&until=2999-01-01T00:00:00Z").json()["total"] == 4
    assert web.get("/api/observations?until=soon").status_code == 400


def test_parse_card_keeps_the_editor_notes_when_the_reply_has_them():
    reply = json.loads(card96())
    reply["card"]["editor_notes"] = {
        "kind": "feature of Claude Code", "gap": "null", "absorber": "the harness",
        "facets": ["records", " ", None, "checks"], "integration_point": "a git hook",
        "channel": "none", "existing": [{"n": 2, "name": "AgentSight", "covers": "traces"}]}
    _, card = card_mod.parse_card(json.dumps(reply), 5)
    assert card["editor_notes"] == {
        "kind": "feature of Claude Code", "absorber": "the harness",
        "facets": ["records", "checks"], "integration_point": "a git hook",
        "existing": [{"n": 2, "name": "AgentSight", "covers": "traces"}]}
    _, plain = card_mod.parse_card(card96(), 5)
    assert "editor_notes" not in plain
    reply["card"]["editor_notes"] = {"kind": "none", "facets": []}
    _, empty = card_mod.parse_card(json.dumps(reply), 5)
    assert "editor_notes" not in empty


def test_the_api_sends_the_editor_notes(web, rt, cards):  # noqa: F811
    notes = {"kind": "product", "facets": ["a", "b", "c"], "channel": "r/selfhosted"}
    card = {**json.loads(rt.store.query_one("SELECT card FROM ideas WHERE id = ?",
                                            (cards["old"],))["card"]), "editor_notes": notes}
    with_notes = add_card(rt.store, "Noted one", card, score=0.3)
    listed = {c["id"]: c for c in web.get("/api/ideas").json()["ideas"]}
    assert listed[with_notes]["editor_notes"] == notes
    assert listed[cards["old"]]["editor_notes"] is None
