"""What the owner graded of a source, on the source: its observations' latest
grades over 90 days and the why chips. The Read less suggestion is gone:
the source rule's ``removal`` says when Kranto recommends removing a source
(tests/test_source_rule.py)."""

from datetime import timedelta

from kranto import source_health
from kranto.store import utcnow

from .conftest import old_grade
from .test_ideas_api import obs_ids
from .test_web import rt, web  # noqa: F401 - fixtures


def grade(web, oid, value, reasons=()):  # noqa: F811
    r = web.post("/api/feedback", json={"target": "observation", "target_id": oid,
                                       "value": value, "reasons": list(reasons)})
    assert r.status_code == 200, r.text


def feed(web):  # noqa: F811
    return next(s for s in web.get("/api/sources").json()["sources"] if s["label"] == "Energy Feed")


def test_a_sources_grades_and_chips_count_and_no_read_less_is_suggested(web, rt):  # noqa: F811
    oids = obs_ids(rt.store)
    assert feed(web)["grades"] is None and "suggest" not in feed(web)
    grade(web, oids[0], "useful")
    assert feed(web)["grades"]["useful"] == 1
    grade(web, oids[1], "not_useful", ["off_topic"])
    grade(web, oids[2], "not_useful", ["off_topic"])
    old_grade(rt.store, "observation", oids[3], "wrong")   # an older "wrong" still counts
    got = feed(web)
    g = got["grades"]
    assert (g["useful"], g["not_useful"], g["wrong"]) == (1, 2, 1)
    assert got["grades"]["reasons"] == {"off_topic": 2} and "suggest" not in got
    r = got["removal"]                                     # 3 down, 1 up: not recommended
    assert (r["recommend"], r["down"], r["up"]) == (False, 3, 1)


def test_the_latest_grade_counts_and_a_cleared_or_old_one_does_not(web, rt):  # noqa: F811
    oids = obs_ids(rt.store)
    grade(web, oids[0], "not_useful")
    grade(web, oids[0], "useful")                          # changed mind
    grade(web, oids[1], "not_useful")
    grade(web, oids[1], "skip")                            # cleared
    g = feed(web)["grades"]
    assert (g["useful"], g["not_useful"], g["wrong"]) == (1, 0, 0)
    later = utcnow() + timedelta(days=source_health.GRADE_DAYS + 1)
    assert source_health.source_grades(rt.store, now=later) == {}
