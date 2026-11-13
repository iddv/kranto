"""The source rule: many downvotes on a source's evidence recommend removing it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kranto import feedback, library, source_rule
from kranto.config import GradingConfig
from kranto.store import Store, iso

from .conftest import old_grade

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)


class Lib:
    def __init__(self, store: Store, embedder):
        self.s = store
        self.topic = library.add_topic(store, embedder, "tools", "AI developer tooling")
        self.n = 0

    def source(self, label: str = "HN search: local-first") -> int:
        self.n += 1
        sid = library.add_source(self.s, "rss", {"url": f"https://ex.com/{self.n}"}, label=label)
        library.link_topic_source(self.s, self.topic, sid)
        return sid

    def post(self, source: int) -> int:
        return self.s.insert("observations", {
            "source_id": source, "item_id": f"i{self.n}-{id(object())}", "kind": "beat",
            "title": "t", "summary": "s", "why_it_matters": "w", "content_quality": 0.5,
            "durability": 0.5, "opportunity": 0.5, "signal": 0.1, "tags": "[]",
            "embedding": b"", "embedding_model": "stub", "created_at": iso(NOW)})

    def graded(self, source: int, down: int, up: int = 0, days_ago: float = 1) -> None:
        for value, n in (("not_useful", down), ("useful", up)):
            for _ in range(n):
                feedback.add(self.s, {"target": "observation", "target_id": str(self.post(source)),
                                      "value": value}, now=NOW - timedelta(days=days_ago))


@pytest.fixture
def lib(store, embedder):
    return Lib(store, embedder)


def removed(store) -> list[int]:
    return [r["id"] for r in source_rule.to_remove(store, now=NOW)]


@pytest.mark.parametrize("down,up,listed", [(3, 0, True), (4, 1, True), (8, 2, True),
                                            (3, 1, False), (2, 0, False), (0, 0, False)])
def test_the_threshold(lib, store, down, up, listed):
    s = lib.source()
    lib.graded(s, down, up)
    assert (removed(store) == [s]) is listed


def test_the_row_says_the_counts_and_where_it_feeds(lib, store):
    s = lib.source()
    lib.graded(s, 4, 1)
    (row,) = source_rule.to_remove(store, now=NOW)
    assert row["label"] == "HN search: local-first"
    assert (row["down"], row["up"], row["window_days"]) == (4, 1, 90)
    assert row["topics"] == [{"id": lib.topic, "name": "tools"}]
    assert row["items_per_day"] == 0


def test_a_wrong_counts_as_a_downvote_and_a_cleared_grade_as_none(lib, store):
    s = lib.source()
    lib.graded(s, 2)
    o = lib.post(s)
    old_grade(store, "observation", o, "wrong", at=NOW - timedelta(days=1))  # an older Kranto's
    assert removed(store) == [s]
    feedback.add(store, {"target": "observation", "target_id": str(o), "value": "skip"},
                 now=NOW - timedelta(hours=1))
    assert removed(store) == []


def test_keep_hides_the_row_until_three_more_downvotes_after_it(lib, store):
    s = lib.source()
    lib.graded(s, 4, days_ago=3)
    assert removed(store) == [s]
    got = source_rule.keep(store, s, now=NOW - timedelta(days=2))
    assert got == {"id": s, "kept": True, "down": 4, "up": 0, "window_days": 90}
    assert removed(store) == []
    st = source_rule.state(store, now=NOW)[s]
    assert st["recommend"] is False and st["kept"]["down"] == 4
    lib.graded(s, 2, days_ago=1)
    assert removed(store) == []
    lib.graded(s, 1, days_ago=1)
    assert removed(store) == [s]


def test_a_retired_or_paused_source_is_never_listed(lib, store, embedder):
    a, b = lib.source("a"), lib.source("b")
    lib.graded(a, 3)
    lib.graded(b, 3)
    assert set(removed(store)) == {a, b}
    store.set_status("source", a, "retired")
    assert removed(store) == [b]
    store.set_status("topic", lib.topic, "paused")
    assert removed(store) == []


def test_grades_older_than_the_window_do_not_count(lib, store):
    s = lib.source()
    lib.graded(s, 3, days_ago=91)
    assert removed(store) == []
    assert source_rule.to_remove(store, GradingConfig(window_days=120), now=NOW)[0]["id"] == s


def test_a_purged_observations_grade_does_not_count(lib, store):
    s = lib.source()
    lib.graded(s, 2)
    store.insert("feedback", {"target": "observation", "target_id": "99999", "kind": "grade",
                              "value": "not_useful", "origin": "ui",
                              "created_at": iso(NOW - timedelta(days=1))})
    assert removed(store) == []


def test_keep_on_a_missing_source_is_refused(store):
    with pytest.raises(ValueError, match="no source 42"):
        source_rule.keep(store, 42)


def test_the_summary_names_the_closest_and_the_kept(lib, store):
    a, b, c = lib.source("a"), lib.source("b"), lib.source("c")
    lib.graded(a, 2, 1)
    lib.graded(b, 1)
    lib.graded(c, 3)
    source_rule.keep(store, c, now=NOW - timedelta(hours=1))
    got = source_rule.summary(store, now=NOW)
    assert got["recommended"] == []
    assert got["closest"] == {"id": a, "label": "a", "down": 2, "up": 1}
    assert [k["id"] for k in got["kept"]] == [c]


# -- the API -------------------------------------------------------------------------------------

from .test_web import rt, web  # noqa: E402, F401 - fixtures


def test_today_lists_it_keep_takes_it_off_and_the_sheet_says_so(web, rt):  # noqa: F811
    store = rt.store
    src = library.list_sources(store)[0]
    for r in store.query("SELECT id FROM observations WHERE source_id = ? LIMIT 3", (src.id,)):
        assert web.post("/api/feedback", json={"target": "observation", "target_id": str(r["id"]),
                                               "value": "not_useful"}).status_code == 200
    today = web.get("/api/today").json()
    assert [s["id"] for s in today["sources_to_remove"]] == [src.id]
    row = next(s for s in web.get("/api/sources").json()["sources"] if s["id"] == src.id)
    assert row["removal"]["recommend"] is True and row["removal"]["down"] == 3
    got = web.post(f"/api/sources/{src.id}/keep")
    assert got.status_code == 200
    assert got.json() == {"id": src.id, "kept": True, "down": 3, "up": 0, "window_days": 90,
                          "label": src.label}
    assert web.get("/api/today").json()["sources_to_remove"] == []
    row = next(s for s in web.get("/api/sources").json()["sources"] if s["id"] == src.id)
    assert row["removal"]["recommend"] is False and row["removal"]["kept"]["down"] == 3
    assert web.post("/api/sources/9999/keep").status_code == 404


def test_the_verb_is_listed_with_its_route(web):  # noqa: F811
    verbs = {v["kind"]: v for v in web.get("/api/verbs").json()["verbs"]}
    keep = verbs["source.keep"]
    assert keep["ladder"] == "reversible" and keep["page"] == "#/needs"
