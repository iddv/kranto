"""The next ideas run in the owner's order: the candidate themes sorted by their
taste against the graded cards and evidence, and a theme the owner voted down far enough left out
of the run with why. No grade: today's order. No model."""

from __future__ import annotations

import pytest

from kranto import taste
from kranto.config import GradingConfig
from kranto.ideate.cards import Candidate, IdeasReport, by_taste

from .test_taste import NOW, World


@pytest.fixture(autouse=True)
def _fresh():
    taste.clear_cache()
    yield
    taste.clear_cache()


def world(store):
    """Three themes: one like a card the owner upvoted, one like a card they downvoted, one
    nothing touches."""
    w = World(store, 5)
    s = w.source()
    bases = [w.vec() * 4 for _ in range(3)]
    obs = {th: [w.obs(s, w.vec(bases[th], 0.3)) for _ in range(4)] for th in range(3)}
    points = {o: th for th, os in obs.items() for o in os}
    snap = w.snapshot(points, {0: "LUP", 1: "LDN", 2: "LNONE"})
    up = w.card(obs[0][:2], "LUP")
    down = w.card(obs[1][:2], "LDN")
    cands = [Candidate("rising", lin, th, "why", obs[th], f"theme {lin}")
             for th, lin in ((2, "LNONE"), (1, "LDN"), (0, "LUP"))]       # today's order
    return w, snap, cands, up, down


def test_no_grades_keep_todays_order_and_leave_nothing_out(store):
    _, snap, cands, _, _ = world(store)
    kept, skipped = by_taste(store, {"id": snap}, cands, None, NOW)
    assert [c.lineage_id for c in kept] == ["LNONE", "LDN", "LUP"]
    assert skipped == []


def test_the_themes_follow_the_grades_and_a_sunk_one_is_left_out_with_why(store):
    w, snap, cands, up, down = world(store)
    w.grade("idea", up, "useful")
    w.grade("idea", down, "not_useful")
    kept, skipped = by_taste(store, {"id": snap}, cands, None, NOW)
    assert [c.lineage_id for c in kept] == ["LUP", "LNONE"]
    assert [s["lineage_id"] for s in skipped] == ["LDN"]
    assert skipped[0]["taste"] <= -0.5 and skipped[0]["name"] == "theme LDN"
    assert skipped[0]["why"] == "not carded: like 1 card you downvoted"
    # the line is a setting: a lower one reorders and leaves nothing out
    kept2, skipped2 = by_taste(store, {"id": snap}, cands, GradingConfig(theme_skip_below=-5), NOW)
    assert [c.lineage_id for c in kept2] == ["LUP", "LNONE", "LDN"] and skipped2 == []


def test_a_skip_lifts_as_the_grade_fades(store):
    w, snap, cands, _, down = world(store)
    w.grade("idea", down, "not_useful", days_ago=200)      # weighs 0.21 now: under the line
    kept, skipped = by_taste(store, {"id": snap}, cands, None, NOW)
    assert skipped == [] and "LDN" in [c.lineage_id for c in kept]


def test_the_run_report_carries_what_was_left_out():
    left = {"lineage_id": "LDN", "name": "theme", "taste": -0.9,
            "why": "not carded: like 1 card you downvoted"}
    r = IdeasReport(run_uuid="u", taste_skipped=[left])
    assert '"taste_skipped": [{"lineage_id": "LDN"' in r.summary()
