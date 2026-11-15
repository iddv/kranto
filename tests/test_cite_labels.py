"""A citation names an observation by its id however long the id is (found on a copy of live,
2026-10-21: its observations passed id 9999 at 11:00, and the label patterns took four digits at
most, so a brief item citing "obs 10054" was dropped as uncited)."""

from kranto.features.news import check


def test_five_digit_and_longer_ids_are_citable():
    rep = check.Report()
    lines = {"obs 10054": object(), "obs 12": object()}
    assert check._cites(["obs 10054", "[obs 12]", "obs 99999"], lines, rep) == ["obs 10054",
                                                                               "obs 12"]
    assert rep.bad_citations == 1
