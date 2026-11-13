"""Feedback (LEARNING.md 2.4, track L1): one append-only table for Kranto UI's grades, its
vocabulary, the union with the older grades table and the review queue. Grades are kept on
ideas and evidence only: older rows on other targets are history, still read.
No model call anywhere."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from kranto import feedback, grades, library
from kranto.sources import Item
from kranto.store import iso

from .conftest import old_grade
from .test_ideas_api import add_card, add_theme, cards, old_card  # noqa: F401 - fixtures
from .test_web import rt, web  # noqa: F401 - fixtures

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def grade(store, target, target_id, value, **kw):
    return feedback.add(store, {"target": target, "target_id": target_id, "value": value, **kw})


# -- the table --------------------------------------------------------------------------------
def test_the_migration_adds_an_append_only_table_and_leaves_grades_alone(store):
    assert 19 in store.applied_migrations()
    cols = [r["name"] for r in store.query("PRAGMA table_info(feedback)")]
    assert cols == ["id", "target", "target_id", "kind", "value", "reasons", "pair", "note",
                    "origin", "context", "created_at"]
    assert "feedback" in store.append_only_tables()
    grade_cols = [r["name"] for r in store.query("PRAGMA table_info(grades)")]
    assert grade_cols == ["id", "target", "target_id", "grade", "note", "context", "created_at"]
    row = store.insert("feedback", {"target": "build", "target_id": "b1", "kind": "grade",
                                    "value": "useful", "origin": "ui", "created_at": iso(NOW)})
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.query("UPDATE feedback SET value = 'wrong' WHERE id = ?", (row,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.query("DELETE FROM feedback WHERE id = ?", (row,))


def test_the_vocabulary_refuses_what_it_does_not_know(rt):  # noqa: F811
    store = rt.store
    oid = store.query_one("SELECT id FROM observations")["id"]
    for bad, why in [
        ({"target": "planet", "target_id": "1", "value": "useful"}, "target must be"),
        ({"target": "observation", "target_id": oid, "value": "meh"}, "a grade must be"),
        ({"target": "observation", "target_id": oid, "value": "useful", "kind": "vibe"}, "kind"),
        ({"target": "observation", "target_id": oid, "value": "useful", "origin": "x"}, "origin"),
        ({"target": "observation", "target_id": oid, "value": "useful",
          "reasons": ["too_broad"]}, "not a chip for a observation"),
        ({"target": "observation", "target_id": 99999, "value": "useful"}, "no observation"),
        ({"target": "observation", "target_id": "", "value": "useful"}, "target_id"),
        ({"kind": "pair", "value": "a", "pair": {"a": {"target": "idea", "id": "1"}}}, "pair"),
        ({"target": "observation", "target_id": oid, "value": "useful", "context": [1]},
         "context"),
    ]:
        with pytest.raises(ValueError, match=why):
            feedback.add(store, bad)
    # a source or a message is not graded any more, and ▲ ▼ are the values
    for target, tid in (("source", "1"), ("message", "1")):
        with pytest.raises(ValueError, match=feedback.NOT_KEPT):
            grade(store, target, tid, "not_useful")
    # a build, a project or a theme has no object any more (CUT): no new row names one
    for target in feedback.RETIRED_TARGETS:
        with pytest.raises(ValueError, match="target must be"):
            grade(store, target, "plotkeeper-1", "not_useful")
    for value in ("wrong", "missed"):
        with pytest.raises(ValueError, match="useful, not_useful, skip"):
            grade(store, "observation", oid, value)
    assert store.query_one("SELECT COUNT(*) AS n FROM feedback")["n"] == 0
    chips = feedback.vocabulary()["chips"]
    assert not set(feedback.RETIRED_TARGETS) & set(chips)
    assert [c["letter"] for c in chips["idea"]] == list("abcdef")
    assert {t for t in feedback.TARGETS if t != "pair"} <= set(chips)


def test_rows_on_a_build_or_a_theme_are_skipped_and_counted_nowhere(rt, web):  # noqa: F811
    """CUT (``feedback.target``): live holds 6 rows on ``build`` and 2 on
    ``cluster``, written before those left. They stay in the table and every reader skips
    them: no latest, no history, no count in the taste summary or the review queue, and the
    API answers empty (never an error) for a page that still asks."""
    from kranto import taste
    store = rt.store
    for i in range(6):
        old_grade(store, "build", f"plot-{i}", "not_useful", reasons=["bugs"])
    old_grade(store, "cluster", "lin-1", "useful")
    old_grade(store, "cluster", "lin-2", "useful", reasons=["propose_ideas"])
    store.insert("feedback", {"target": "build", "target_id": "plot-9", "kind": "action",
                              "value": "publish", "origin": "ui", "created_at": iso(NOW)})
    assert store.query_one("SELECT COUNT(*) AS n FROM feedback")["n"] == 9    # all kept
    assert feedback.latest(store, "build", [f"plot-{i}" for i in range(6)]) == {}
    assert feedback.history(store, "build", "plot-9") == []
    assert grades.latest(store, "cluster", ["lin-1", "lin-2"]) == {}
    assert grades.history(store, "cluster", "lin-1") == []
    summary = taste.summary(store)
    assert summary["counts"]["cards"] == 0 and summary["counts"]["evidence"] == 0
    r = web.get("/api/feedback?target=build&ids=plot-0,plot-1")
    assert r.status_code == 200 and r.json()["grades"] == {}
    r = web.get("/api/feedback?target=cluster&target_id=lin-1")
    assert r.status_code == 200 and r.json()["history"] == []
    q = web.get("/api/review/queue").json()
    assert {x["target"] for x in q["items"]} <= {"idea"}
    assert "build" not in q["chips"] and "cluster" not in q["chips"]


def test_latest_is_the_newer_of_both_tables_and_a_cleared_grade_is_none(rt):  # noqa: F811
    store = rt.store
    oid = str(store.query_one("SELECT id FROM observations")["id"])
    grades.add_grade(store, "observation", oid, "useful", now=NOW - timedelta(hours=2))
    assert grades.latest(store, "observation", [oid])[oid]["grade"] == "useful"
    feedback.add(store, {"target": "observation", "target_id": oid, "value": "not_useful",
                         "reasons": ["stale"]}, now=NOW - timedelta(hours=1))
    got = grades.latest(store, "observation", [oid])[oid]
    assert (got["grade"], got["table"], got["reasons"]) == ("not_useful", "feedback", ["stale"])
    old_grade(store, "observation", oid, "missed", at=NOW)      # an older Kranto's "missed"
    assert grades.latest(store, "observation", [oid])[oid]["grade"] == "missed"
    feedback.add(store, {"target": "observation", "target_id": oid, "value": "skip"},
                 now=NOW + timedelta(minutes=1))
    assert grades.latest(store, "observation", [oid]) == {}
    assert feedback.latest(store, "observation", [oid]) == {}
    assert feedback.latest(store, "observation", [oid], keep_skip=True)[oid]["value"] == "skip"
    hist = [h["grade"] for h in grades.history(store, "observation", oid)]
    assert hist == ["useful", "not_useful", "missed", "skip"]


def test_api_ideas_and_the_loops_intake_see_the_new_grade(web, cards):  # noqa: F811
    one = lambda: web.get(f"/api/ideas/{cards['new']}").json()["grade"]  # noqa: E731
    assert one() is None
    r = web.post("/api/feedback", json={"target": "idea", "target_id": cards["new"],
                                        "value": "not_useful", "reasons": ["not_buildable"]})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "not useful" and r.json()["reasons"] == ["not_buildable"]
    assert one() == "not_useful"
    web.post("/api/feedback", json={"target": "idea", "target_id": cards["new"], "value": "skip"})
    assert one() is None, "a cleared grade lets the card be taken in again"
    # the older grade on the other card still counts
    assert web.get(f"/api/ideas/{cards['old']}").json()["grade"] == "useful"


# -- the API ----------------------------------------------------------------------------------
def test_post_and_read(web, rt):  # noqa: F811
    store = rt.store
    oids = [str(r["id"]) for r in store.query("SELECT id FROM observations ORDER BY id")]
    assert web.post("/api/feedback", json={"target": "observation", "target_id": oids[0],
                                           "value": "nope"}).status_code == 400
    assert web.post("/api/feedback", json=[1]).status_code == 400
    refused = web.post("/api/feedback", headers={"origin": "http://evil.example"},
                       json={"target": "observation", "target_id": oids[0], "value": "useful"})
    assert refused.status_code == 403
    # one row at a time: the batch route is gone with bulk grading
    build = web.post("/api/feedback", json={"target": "build", "target_id": "plot-1",
                                            "value": "useful"})
    assert build.status_code == 400 and "target must be" in build.json()["error"]
    assert web.post("/api/feedback/batch", json={"rows": []}).status_code in (404, 405)
    assert store.query_one("SELECT COUNT(*) AS n FROM feedback")["n"] == 0
    for o in oids[:3]:
        r = web.post("/api/feedback", json={"target": "observation", "target_id": o,
                                            "value": "useful", "origin": "ui",
                                            "context": {"route": "topics/1/evidence"}})
        assert r.status_code == 200, r.text
    got = web.get("/api/feedback?target=observation&ids=" + ",".join(oids)).json()
    assert set(got["grades"]) == set(oids[:3]) and got["grades"][oids[0]]["value"] == "useful"
    hist = web.get(f"/api/feedback?target=observation&target_id={oids[0]}").json()["history"]
    assert [h["context"] for h in hist] == [{"route": "topics/1/evidence"}]
    assert web.get("/api/feedback?target=nope").status_code == 400
    voc = web.get("/api/feedback/vocabulary").json()
    assert voc["chips"]["source"][2] == {"key": "dead", "label": "dead", "letter": "c"}
    assert "build" not in voc["chips"] and "build" not in voc["targets"]


def test_a_pair_is_two_targets(web, cards):  # noqa: F811
    body = {"kind": "pair", "value": "b", "origin": "review",
            "pair": {"a": {"target": "idea", "id": cards["old"]},
                     "b": {"target": "idea", "id": cards["new"]}}}
    r = web.post("/api/feedback", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["target"] == "pair"
    assert r.json()["target_id"] == f"idea:{cards['old']}|idea:{cards['new']}"
    body["pair"]["b"] = body["pair"]["a"]
    assert web.post("/api/feedback", json=body).status_code == 400


# -- the queue --------------------------------------------------------------------------------
@pytest.fixture
def forty(store, embedder):
    src = library.add_source(store, "rss", {"url": "https://ex.com/f"}, label="Feed")
    for i in range(40):
        library.record_observation(
            store, source_id=src, item=Item(id=f"i{i}", title=f"obs {i}", body="b",
                                            url=f"https://ex.com/{i}"),
            fields={"kind": "beat", "summary": f"summary {i}", "why_it_matters": "w",
                    "content_quality": .5, "durability": .5, "opportunity": .5, "signal": .125,
                    "override": False, "override_reason": None, "tags": []},
            embedding=embedder.embed_documents([f"summary {i}"])[0],
            embedding_model=embedder.model_name, llm_call_id=None, prompt_version="x",
            run_uuid="r", admitted_by="topic", topic_similarity=.5)
    return store


def twelve_cards(store):
    """12 cards this week: 5 from topic A, 3 from B, 4 from C of which 2 are vetoed."""
    out = []
    for i in range(12):
        topic = "A" if i < 5 else "B" if i < 8 else "C"
        cid = add_card(store, f"card {i}", {"title": f"card {i}"}, score=i / 20,
                       lineage=f"lin-{i % 4}")
        out.append({"id": cid, "title": f"card {i}", "status": "shown", "score": i / 20,
                    "created_at": iso(NOW - timedelta(days=1)), "one_liner": f"line {i}",
                    "topic": {"name": topic}, "citations": [{}, {}],
                    "facts": {"cited": i, "asks": i % 3, "sources": 2},
                    "grade": "not_useful" if i >= 10 else None,
                    "theme": {"lineage_id": f"lin-{i % 4}", "name": f"theme {i % 4}",
                              "keywords": ["k"], "size": 7}})
    for ln in range(4):
        add_theme(store, f"lin-{ln}", 7, {"A": 7})
    return out


def test_the_queue_is_cards_in_the_order_of_their_facts(forty):
    """ #3, the live case: the owner graded 21 queue items on 8, 9 and 11 Oct and none
    since; the controls, pairs, themes and opened observations they were asked to grade are
    read by nothing. The queue now asks only what a grade is read for: cards (a card graded
    not useful is never built; taste ranks by them), ordered by what they stand on,
    never by the writer's own score. Builds are not graded: a build named to
    the queue is not asked about."""
    from kranto.ideate.cards import fact_order

    store = forty
    cs = twelve_cards(store)            # 4 open cards in topic A and themes: pairs once came
    for c in cs[10:]:
        grade(store, "idea", c["id"], "not_useful")
    oid = store.query_one("SELECT id FROM observations")["id"]
    feedback.add(store, {"target": "observation", "target_id": oid, "kind": "implicit",
                         "value": "opened"}, now=NOW - timedelta(hours=1))
    q = feedback.build_queue(store, cs, builds=["b-1", "b-2"], now=NOW)
    items = q["items"]
    assert {x["slot"] for x in items} == {"card"}
    assert {x["target"] for x in items} == {"idea"}
    cards_in = [x["id"] for x in items if x["slot"] == "card"]
    assert cards_in == [c["id"] for c in sorted(cs[:10], key=fact_order)]
    assert cards_in[0] == cs[8]["id"]          # 2 ask for it, 8 cited: before 9 cited, 0 ask
    first = next(x for x in items if x["slot"] == "card")
    assert first["facts"][:3] == ["8 cited", "2 ask for it", "2 sources"]
    assert not any("score" in f for x in items for f in x.get("facts") or [])
    # the same all week; a graded card leaves it
    assert feedback.build_queue(store, cs, now=NOW)["items"] == items
    grade(store, "idea", cards_in[0], "useful", origin="review")
    again = feedback.build_queue(store, cs, now=NOW)["items"]
    assert [x["id"] for x in again] == cards_in[1:]


def test_a_queue_skip_hides_for_the_week_and_twice_for_good(forty):
    store = forty
    cs = twelve_cards(store)[:2]
    first = cs[1]["id"]
    week1 = NOW - timedelta(days=14)
    feedback.add(store, {"target": "idea", "target_id": first, "value": "skip",
                         "origin": "review"}, now=NOW - timedelta(hours=1))
    ids = lambda: [x["id"] for x in feedback.build_queue(store, cs, now=NOW)["items"]  # noqa: E731
                   if x["slot"] == "card"]
    assert first not in ids()
    later = NOW + timedelta(days=8)
    for c in cs:
        c["created_at"] = iso(later - timedelta(days=1))
    assert first in [x["id"] for x in feedback.build_queue(store, cs, now=later)["items"]]
    feedback.add(store, {"target": "idea", "target_id": first, "value": "skip",
                         "origin": "review"}, now=week1)
    assert first not in [x["id"] for x in feedback.build_queue(store, cs, now=later)["items"]]


def test_the_queue_api_and_no_learning_stub(web, cards):  # noqa: F811
    q = web.get("/api/review/queue?builds=plot-1&controls=2").json()     # both: ignored
    assert q["items"] and {x["slot"] for x in q["items"]} == {"card"}
    assert "idea" in q["chips"]
    # Settings › Your grades reads /api/grades/summary; the learning stub is gone
    assert web.get("/api/learning").status_code == 404
    assert web.get("/api/grades/summary").status_code == 200
