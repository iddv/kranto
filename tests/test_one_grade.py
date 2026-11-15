""" #7 and #9: a card is ordered by what it stands on, and every grade is written to one
table (``feedback``) and read by one reader (``grades.latest``). The old tables (``verdicts``
before migration 10, ``grades`` before 19) keep their rows and are only read. No model call."""

import pytest

from kranto import feedback, grades
from kranto.ideate import cards

from .conftest import old_grade
from .test_ideas_api import add_card


def live_shaped(cited: int, asks: int, hosts: list[str]) -> dict:
    """A card as live writes it (kranto.db card #125's keys, no text): its verified
    evidence, its demand with its own evidence, and its citations with their links."""
    return {"title": "t", "evidence": [{"n": n, "claim": "c"} for n in range(cited)],
            "demand": {"statement": "s", "evidence": [{"n": n} for n in range(asks)]},
            "citations": [{"url": f"https://{h}/x{n}"} for n, h in enumerate(hosts)],
            "ratings": {"pattern_strength": {"value": 0.5}}}


def test_a_card_is_ordered_by_its_facts_never_by_its_score(store):
    """Live: 125 cards, mean score 0.0039, max 0.0735 (a product of five self-ratings). The
    list is ordered by demand, then citations, then sites, then newest; the score stays in the
    row and orders nothing."""
    weak = add_card(store, "high score, nothing asks", live_shaped(1, 0, ["a.org"]), score=0.0735)
    asked = add_card(store, "low score, asked for", live_shaped(2, 1, ["a.org", "b.org"]),
                     score=0.0012)
    wide = add_card(store, "low score, many sites", live_shaped(2, 0, ["a.org", "b.org",
                                                                      "b.org", "c.org"]),
                    score=0.0039)
    got = cards.list_ideas(store)
    assert [c["id"] for c in got] == [asked, wide, weak]
    assert got[1]["facts"] == {"cited": 2, "asks": 0, "sources": 3}
    assert cards.fact_words(got[0]["facts"]) == ["2 cited", "1 asks for it", "2 sources"]
    assert cards.facts({}) == {"cited": 0, "asks": 0, "sources": 0}


def test_every_grade_is_a_feedback_row(store):
    """The pages (POST /api/feedback) and ``afk grade`` write through ``grades.add_grade``
    or ``feedback.add``: one feedback row, read back with its context. ▲ ▼ only now
   ; an older "wrong" is still read."""
    cid = add_card(store, "a card", live_shaped(1, 0, ["a.org"]))
    gid = grades.add_grade(store, "idea", cid, "useful", "good one")
    cards.grade(store, cid, "not_useful", "misread")
    rows = store.query("SELECT * FROM feedback ORDER BY id")
    assert [r["id"] for r in rows][0] == gid
    assert [(r["target"], r["value"], r["note"]) for r in rows] == [
        ("idea", "useful", "good one"), ("idea", "not_useful", "misread")]
    assert store.query_one("SELECT COUNT(*) AS n FROM grades")["n"] == 0
    assert grades.latest(store, "idea", [cid])[str(cid)]["grade"] == "not_useful"
    with pytest.raises(ValueError, match="one of"):
        grades.add_grade(store, "idea", cid, "worth_waking")
    with pytest.raises(ValueError, match="one of"):
        cards.grade(store, cid, "wrong")
    old_grade(store, "idea", cid, "wrong")
    assert grades.latest(store, "idea", [cid])[str(cid)]["grade"] == "wrong"


def test_the_old_tables_are_read_by_the_one_reader(store):
    """A Parallax-era workspace: a verdict (before migration 10) and a grade (before 19) are
    the latest until a newer feedback row; ``cards.list_ideas`` reads the same reader."""
    cid = add_card(store, "an old card", live_shaped(1, 0, ["a.org"]))
    store.insert("verdicts", {"target": "idea", "target_id": cid, "verdict": "not_useful",
                              "note": None, "created_at": "2026-01-01T00:00:00Z"})
    assert grades.latest(store, "idea", [cid])[str(cid)]["table"] == "verdicts"
    assert cards.list_ideas(store)[0]["verdict"] == "not_useful"
    store.insert("grades", {"target": "idea", "target_id": str(cid), "grade": "useful",
                            "note": None, "context": "{}", "created_at": "2026-02-01T00:00:00Z"})
    assert cards.list_ideas(store)[0]["verdict"] == "useful"
    feedback.add(store, {"target": "idea", "target_id": cid, "value": "skip"})
    assert cards.list_ideas(store)[0]["verdict"] is None          # cleared in the app
    hist = [(h["table"], h["grade"]) for h in grades.history(store, "idea", cid)]
    assert hist == [("verdicts", "not_useful"), ("grades", "useful"), ("feedback", "skip")]
