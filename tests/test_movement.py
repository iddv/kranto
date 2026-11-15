import json

import pytest

from kranto.ideate.cards import candidates
from kranto.map import bursts
from kranto.map.read import clusters as read_clusters
from kranto.map.read import latest
from kranto.map.snapshot import _score_movement, take_snapshot

from .conftest import web_client
from .test_map import add_observations

# -- the burst model on synthetic series --------------------------------------------

STEADY = [(10, 100)] + [(2, 20)] * 6  # a lineage taking 10% of arrivals


def test_sustained_surge_enters_a_burst():
    assert bursts.burst_states(STEADY) == [0] * 7
    assert bursts.burst_states(STEADY + [(5, 20)] * 2)[-1] == 1
    assert bursts.burst_states(STEADY + [(9, 20)])[-1] == 1


def test_single_snapshot_spike_is_suppressed_by_the_transition_cost():
    spike = STEADY + [(5, 20)]
    # On its own the spike would pass a naive test...
    assert bursts.binomial_p_value(5, 20, 2.0) < 0.05
    # ...and without a cost for entering the burst state it would be called a burst.
    assert bursts.burst_states(spike, gamma=0.0)[-1] == 1
    assert bursts.burst_states(spike)[-1] == 0
    # A moderate spike in the middle of a steady series is not a burst either.
    assert bursts.burst_states(STEADY + [(6, 20)] + [(2, 20)] * 2) == [0] * 10


def test_burst_rate_is_capped_below_one():
    assert bursts.burst_rate(0.1) == pytest.approx(0.2)
    assert bursts.burst_rate(0.6) == pytest.approx(0.8)
    assert bursts.burst_rate(0.9) < 1.0
    assert bursts.burst_states([(9, 10), (10, 10)]) in ([0, 0], [0, 1])


def test_degenerate_series_stay_in_the_base_state():
    assert bursts.burst_states([]) == []
    assert bursts.burst_states([(0, 0), (0, 5)]) == [0, 0]
    assert bursts.burst_states([(5, 5)]) == [0]


def test_binomial_p_value():
    assert bursts.binomial_p_value(0, 10, 1.0) == 1.0
    assert bursts.binomial_p_value(3, 0, 0.0) is None
    # P(X >= 10) for X ~ Binomial(10, 0.5) is 0.5 ** 10.
    assert bursts.binomial_p_value(10, 10, 5.0) == pytest.approx(0.5 ** 10)
    assert bursts.binomial_p_value(5, 10, 5.0) == pytest.approx(0.623046875)


def test_benjamini_hochberg_on_known_p_values():
    # Values match R's p.adjust(..., method = "BH").
    assert bursts.benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05]) == \
        pytest.approx([0.05] * 5)
    q = bursts.benjamini_hochberg([0.01, 0.04, 0.03, 0.005, None])
    assert q[:4] == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert q[4] is None
    assert bursts.benjamini_hochberg([0.001, 0.5]) == pytest.approx([0.002, 0.5])
    assert bursts.benjamini_hochberg([0.9, 0.8]) == pytest.approx([0.9, 0.9])
    assert bursts.benjamini_hochberg([None, None]) == [None, None]
    assert bursts.benjamini_hochberg([]) == []


def test_rising_needs_entry_significance_and_cross_source():
    before = {"burst": 0, "q_value": None}
    entered = {"burst": 1, "q_value": 0.01}
    assert bursts.rising([before, entered], True)
    assert not bursts.rising([before, entered], False)
    assert not bursts.rising([before, {"burst": 1, "q_value": 0.2}], True)
    assert not bursts.rising([{"burst": 1}, entered], True), "already bursting"
    assert not bursts.rising([before, {"burst": 0, "q_value": 0.001}], True)


def test_legacy_trajectory_points_are_skipped_in_the_series():
    rows = [{"trajectory": [
        {"at": "a", "share": 0.1, "size": 10, "expected_share": None},
        {"at": "b", "share": 0.1, "size": 12, "expected_share": 0.1, "new_total": 20,
         "new_in_cluster": 2, "expected_new": 2.0},
    ]}]
    _score_movement(rows)
    last = rows[0]["trajectory"][-1]
    assert last["burst"] == 0
    assert last["p_value"] == pytest.approx(bursts.binomial_p_value(2, 20, 2.0), rel=1e-3)
    assert last["q_value"] == last["p_value"]
    assert "burst" not in rows[0]["trajectory"][0]


# -- through real snapshots -----------------------------------------------------------

MIXED = ("mix-a", "mix-b")


@pytest.fixture(autouse=True)
def small_libraries_are_tested(monkeypatch):
    """These libraries are built small on purpose; the production floor on the
    previous map's size (MOVEMENT_MIN_PREVIOUS_N) would switch the test off."""
    from kranto.map import snapshot

    monkeypatch.setattr(snapshot, "MOVEMENT_MIN_PREVIOUS_N", 0)


class Feed:
    """Posts observations round by round; item ids never repeat."""

    def __init__(self, store, embedder):
        self.store, self.embedder, self.next = store, embedder, 0

    def post(self, source, theme, count):
        if count:
            add_observations(self.store, self.embedder, theme, count, source, start=self.next)
            self.next += count

    def round(self, per_mixed_source: dict[str, int], bread_only: int = 0):
        for source in MIXED:
            for theme, count in per_mixed_source.items():
                self.post(source, theme, count)
        self.post("bread-only", "bread", bread_only)
        report = take_snapshot(self.store, self.embedder, None)
        assert report.status == "ok", report.error
        return report


STEADY_ROUND = {"solar": 4, "crdt": 4, "bread": 1}


@pytest.fixture
def steady_library(store, embedder):
    """Two sources posting all three themes, one posting only bread; three steady rounds."""
    feed = Feed(store, embedder)
    feed.round({"solar": 20, "crdt": 20, "bread": 4}, bread_only=3)
    for _ in range(3):
        feed.round(STEADY_ROUND)
    return feed


def _bread(store, snapshot_id):
    rows = read_clusters(store, snapshot_id)
    found = [c for c in rows if any("sourdough" in k or "loaf" in k or "crumb" in k
                                    for k in c["keywords"])]
    assert len(found) == 1, [c["keywords"] for c in rows]
    return found[0]


def _burst_candidates(store):
    return [dict(r) for r in store.query(
        "SELECT * FROM strike_candidates WHERE origin = 'burst' ORDER BY id")]


def test_steady_rounds_record_arrivals_and_stay_quiet(steady_library):
    store = steady_library.store
    bread = _bread(store, latest(store)["id"])
    assert len(bread["trajectory"]) == 4
    last = bread["trajectory"][-1]
    assert last["new_total"] == 18 and last["new_in_cluster"] == 2
    assert last["expected_new"] == pytest.approx(2.0, abs=0.6)
    assert last["burst"] == 0 and last["q_value"] > 0.05
    first = bread["trajectory"][0]
    assert first["new_total"] == 91 and first["expected_new"] is None
    assert _burst_candidates(store) == []


def test_surge_into_one_lineage_enters_a_burst_and_yields_a_candidate(steady_library):
    feed = steady_library
    surge = {"solar": 4, "crdt": 4, "bread": 5}
    reports = [feed.round(surge), feed.round(surge)]
    store = feed.store
    bread = _bread(store, reports[-1].snapshot_id)
    assert bread["cross_source"]
    states = [p["burst"] for p in bread["trajectory"]]
    assert states[:4] == [0, 0, 0, 0] and states[-1] == 1

    found = _burst_candidates(store)
    assert len(found) == 1, "entering a burst is reported once, not once per snapshot"
    cand = found[0]
    assert cand["subject_key"] == f"lineage:{bread['lineage_id']}"
    detail = json.loads(cand["detail"])
    assert detail["q_value"] < 0.05
    assert detail["new_in_cluster"] > detail["expected_new"]
    assert set(detail["arriving_sources"]) == set(MIXED)
    assert sum(r.burst_candidates for r in reports) == 1
    evidence = json.loads(cand["evidence_ids"])
    members = {r["observation_id"] for r in store.query(
        "SELECT observation_id FROM snapshot_points WHERE snapshot_id = ? AND cluster = ?",
        (detail["snapshot_id"], detail["cluster"]))}
    assert evidence and set(evidence) <= members

    # The idea-card "rising" path uses the same rule; only the snapshot where the burst
    # was entered offers the lineage as rising.
    entered_at = detail["snapshot_id"]
    rising = [c for c in candidates(store, store.query_one(
        "SELECT * FROM snapshots WHERE id = ?", (entered_at,))) if c.origin == "rising"]
    assert [c.lineage_id for c in rising] == [bread["lineage_id"]]
    assert "entered a burst" in rising[0].why_selected
    if entered_at != reports[-1].snapshot_id:
        assert not [c for c in candidates(store, latest(store)) if c.origin == "rising"]


def test_growth_explained_by_one_source_posting_more_is_not_a_candidate(steady_library):
    feed = steady_library
    report = feed.round(STEADY_ROUND, bread_only=10)
    store = feed.store
    bread = _bread(store, report.snapshot_id)
    assert bread["cross_source"], "the test needs a cross-source lineage to be meaningful"
    last = bread["trajectory"][-1]
    assert last["new_in_cluster"] == 12
    # The burst model alone, which knows nothing about sources, would call it a burst.
    assert last["burst"] == 1
    # The per-source baseline explains it: bread-only always posts bread.
    assert last["expected_new"] > 8
    assert last["q_value"] > 0.05
    assert _burst_candidates(store) == []
    assert not [c for c in candidates(store, latest(store)) if c.origin == "rising"]


def test_old_points_reassigned_do_not_count_as_arrivals(steady_library):
    store = steady_library.store
    report = take_snapshot(store, steady_library.embedder, None, force=True)
    for c in read_clusters(store, report.snapshot_id):
        last = c["trajectory"][-1]
        assert last["new_total"] == 0 and last["new_in_cluster"] == 0
        assert last["p_value"] is None and last["q_value"] is None


def test_clusters_json_carries_state_and_q_value(steady_library, tmp_path, make_client):

    from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import chat_response, llm_config

    feed = steady_library
    feed.round({"solar": 4, "crdt": 4, "bread": 5})
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=feed.store, embedder=feed.embedder,
                      llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(rt)) as web:
        clusters = web.get("/api/clusters?sort=moving").json()["clusters"]
        # moving first: the rising cluster leads, the steady ones follow
        assert clusters[0]["rising"] and not all(c["rising"] for c in clusters)
        movement = clusters[0]["movement"]
        assert movement["q_value"] is not None and movement["expected_new"] is not None
        assert "excess" in movement


def test_expected_arrivals_follow_the_current_boundaries():
    """#41: a cluster that absorbed old points when the map was redrawn expects more
    arrivals, so the absorption cannot read as movement."""
    from kranto.map.snapshot import _expected_new

    old_by_source = {"a": 100, "b": 100}
    arrivals = {"a": 10, "b": 10}
    small = _expected_new({"a": 10, "b": 10}, 0.1, old_by_source, arrivals)
    grown = _expected_new({"a": 40, "b": 40}, 0.4, old_by_source, arrivals)
    assert small == pytest.approx(20 * (10 + 0.1) / 101)
    assert grown == pytest.approx(4 * small, rel=0.02)


def test_no_movement_test_until_the_previous_map_is_large_enough(store, embedder, monkeypatch):
    from kranto.map import snapshot

    monkeypatch.setattr(snapshot, "MOVEMENT_MIN_PREVIOUS_N", 10_000)
    feed = Feed(store, embedder)
    feed.round({"solar": 20, "crdt": 20, "bread": 4}, bread_only=3)
    feed.round({"solar": 4, "crdt": 4, "bread": 9})
    for row in read_clusters(store, latest(store)["id"]):
        last = row["trajectory"][-1]
        assert last["expected_new"] is None and last["q_value"] is None
    assert _burst_candidates(store) == []
