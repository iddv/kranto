"""``taste``: the deterministic order the owner's ▲ and ▼ give the cards.

A synthetic library with seeded 16-float vectors; no model, no embedder."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from kranto import feedback, taste
from kranto.config import ConfigError, GradingConfig, parse_grading
from kranto.store import Store, iso

from .conftest import old_grade

NOW = datetime(2026, 10, 28, 8, 0, tzinfo=UTC)
DIM = 16
CFG = GradingConfig()


@pytest.fixture(autouse=True)
def _fresh():
    taste.clear_cache()
    yield
    taste.clear_cache()


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


class World:
    """Topics, sources, observations, one map and cards, written as Kranto writes them."""

    def __init__(self, store: Store, seed: int = 7):
        self.s = store
        self.rng = np.random.default_rng(seed)
        self.at = iso(NOW - timedelta(days=30))

    def topic(self, name: str) -> int:
        return self.s.insert("topics", {"name": name, "description": name, "embedding": b"",
                                        "embedding_model": "stub", "created_at": self.at})

    def source(self, topic: int | None = None, label: str = "src") -> int:
        params = json.dumps({"u": label, "n": self.rng.random()})
        sid = self.s.insert("sources", {"kind": "rss", "params": params, "label": label,
                                        "origin": "manual", "created_at": self.at})
        if topic is not None:
            self.s.insert("topic_sources", {"topic_id": topic, "source_id": sid,
                                            "created_at": self.at})
        return sid

    def vec(self, base=None, noise: float = 1.0):
        v = self.rng.normal(size=DIM) * noise
        return unit(v if base is None else base + v)

    def obs(self, source: int, vec) -> int:
        return self.s.insert("observations", {
            "source_id": source, "item_id": f"i{self.rng.random()}", "kind": "beat",
            "title": "t", "summary": "s", "why_it_matters": "w", "content_quality": 0.5,
            "durability": 0.5, "opportunity": 0.5, "signal": 0.1, "tags": "[]",
            "embedding": np.asarray(vec, dtype=np.float32).tobytes(),
            "embedding_model": "stub", "created_at": self.at})

    def snapshot(self, points: dict[int, int], lineages: dict[int, str]) -> int:
        snap = self.s.insert("snapshots", {"fingerprint": "f", "embedding_model": "stub",
                                           "n": len(points), "k": len(lineages), "params": "{}",
                                           "quality": "{}", "density": "{}",
                                           "created_at": self.at})
        vecs: dict[int, list] = {}
        for oid, c in points.items():
            row = self.s.query_one("SELECT embedding FROM observations WHERE id = ?", (oid,))
            vecs.setdefault(c, []).append(np.frombuffer(row["embedding"], dtype=np.float32))
            self.s.insert("snapshot_points", {"snapshot_id": snap, "observation_id": oid,
                                              "cluster": c, "x": 0.0, "y": 0.0})
        for c, lin in lineages.items():
            cen = unit(np.mean(vecs[c], axis=0)) if c in vecs else unit(np.ones(DIM))
            self.s.insert("clusters", {
                "snapshot_id": snap, "cluster": c, "lineage_id": lin, "size": len(vecs.get(c, [])),
                "share": 0.1, "centroid": np.asarray(cen, dtype=np.float32).tobytes(),
                "centroid_2d": "[0,0]", "keywords": "[]", "name": f"theme {lin}",
                "source_mix": "{}", "max_source_share": 0.5, "cross_source": 0,
                "topic_mix": "{}", "representatives": "[]", "trajectory": "[]"})
        return snap

    def card(self, cites: list[int], lineage: str | None = None, topic: int | None = None,
             asks: int = 0, status: str = "shown") -> int:
        body = {"title": "c", "evidence": [{"n": n, "observation_id": o, "claim": "x",
                                            "supported": True}
                                           for n, o in enumerate(cites, 1)]}
        if asks:
            body["demand"] = {"statement": "asks", "evidence": [
                {"n": n, "observation_id": o} for n, o in enumerate(cites[:asks], 1)]}
        iid = self.s.insert("ideas", {"fingerprint": "f", "origin": "cross_source",
                                      "evidence_key": f"k{self.rng.random()}",
                                      "lineage_id": lineage, "input_ids": "[]",
                                      "title": f"card {len(cites)}", "card": json.dumps(body),
                                      "score": 0.5, "status": status, "dropped": "[]",
                                      "created_at": self.at})
        self.s.insert("idea_topics", {"idea_id": iid, "topic_id": topic,
                                      "shares": json.dumps([{"id": topic, "kind": "user"}]
                                                           if topic else []),
                                      "created_at": self.at})
        for n, o in enumerate(cites, 1):
            self.s.insert("idea_citations", {"idea_id": iid, "observation_id": o, "n": n,
                                             "role": "evidence", "created_at": self.at})
        return iid

    def grade(self, target: str, ident: int, value: str, days_ago: float = 0) -> int:
        return feedback.add(self.s, {"target": target, "target_id": str(ident), "value": value},
                            now=NOW - timedelta(days=days_ago))


def random_world(store: Store, seed: int = 7) -> tuple[World, list[int], list[int]]:
    """40 cards and 60 observations over four themes, two topics and three sources."""
    w = World(store, seed)
    t1, t2 = w.topic("one"), w.topic("two")
    srcs = [w.source(t1, "a"), w.source(t2, "b"), w.source(None, "c")]
    bases = [w.vec() * 3 for _ in range(4)]
    obs, points = [], {}
    for i in range(60):
        th = i % 4
        o = w.obs(srcs[i % 3], w.vec(bases[th]))
        obs.append(o)
        points[o] = th
    w.snapshot(points, {th: f"L{th}" for th in range(4)})
    r = random.Random(seed)
    cards = []
    for _ in range(40):
        th = r.randrange(4)
        mine = [o for o in obs if points[o] == th]
        cards.append(w.card(r.sample(mine, r.randint(1, 4)), f"L{th}" if r.random() < 0.7
                            else None, r.choice([t1, t2]), asks=r.randint(0, 1)))
    return w, cards, obs


def tastes(store: Store) -> dict[int, float]:
    taste.clear_cache()
    return {i: r.taste for i, r in taste.rank(store, NOW).items()}


# -- 1. an upvote never lowers a card; a downvote never raises one -----------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_an_upvote_never_lowers_a_card_and_a_downvote_never_raises_one(store, seed):
    w, cards, obs = random_world(store, seed)
    r = random.Random(seed)
    w.grade("idea", cards[0], "not_useful")
    w.grade("observation", obs[5], "useful", days_ago=40)
    for value, target in (("useful", "idea"), ("not_useful", "observation"),
                          ("useful", "observation"), ("not_useful", "idea")):
        ident = r.choice(cards[1:] if target == "idea" else obs)
        before = tastes(store)
        w.grade(target, ident, value)
        after = tastes(store)
        for c in cards:
            if target == "idea" and c == ident:
                continue
            if value == "useful":
                assert after[c] >= before[c] - 1e-3, (c, before[c], after[c])
            else:
                assert after[c] <= before[c] + 1e-3, (c, before[c], after[c])


# -- 2. same data, same order ------------------------------------------------------------------


def test_same_data_same_order_and_lines(store):
    w, cards, obs = random_world(store)
    w.grade("idea", cards[3], "useful")
    w.grade("idea", cards[9], "not_useful", days_ago=20)
    w.grade("observation", obs[11], "useful", days_ago=3)
    first = {i: (r.key, r.line, r.position) for i, r in taste.rank(store, NOW).items()}
    taste.clear_cache()
    again = {i: (r.key, r.line, r.position) for i, r in taste.rank(store, NOW).items()}
    assert first == again
    # the graded items read in another order give the same parts
    m = taste.model(store, NOW)
    keys = list(m.graded.items())
    random.Random(3).shuffle(keys)
    m.graded = dict(keys)
    for c in cards:
        item = m.items[("idea", str(c))]
        assert taste.parts_of(item, m, CFG)[0] == -first[c][0][1]
    # positions are 1..n over the shown cards, every key distinct
    pos = sorted(p for _, _, p in first.values())
    assert pos == list(range(1, len(cards) + 1))
    assert len({k for k, _, _ in first.values()}) == len(cards)


def test_no_grades_keep_todays_order(store):
    w, cards, _ = random_world(store)
    from kranto.ideate.cards import fact_order, list_ideas

    got = list_ideas(store, now=NOW)
    assert [d["id"] for d in got] == [d["id"] for d in sorted(got, key=fact_order)]
    assert all(d["rank"].taste == 0 and d["rank"].line == "" for d in got)


# -- 3. the owner's own grade pins -------------------------------------------------------------


def test_own_grade_pins_first_and_last(store):
    w, cards, _ = random_world(store)
    up, down = cards[17], cards[4]
    w.grade("idea", up, "useful")
    old_grade(store, "idea", down, "wrong", at=NOW)  # an older "wrong" counts as a downvote
    ranks = taste.rank(store, NOW)
    assert ranks[up].position == 1
    assert ranks[down].position == len(cards)
    assert ranks[up].line == "you graded it useful"
    assert ranks[down].line == "you graded it not useful"
    # cleared: back among the others
    w.grade("idea", up, "skip")
    assert taste.rank(store, NOW)[up].own is None


# -- 4. decay ----------------------------------------------------------------------------------


def _one_pair(store):
    w = World(store)
    s = w.source()
    o1, o2 = w.obs(s, w.vec()), w.obs(s, w.vec())
    w.snapshot({o1: 0, o2: 0}, {0: "L0"})
    a, b = w.card([o1]), w.card([o1])
    return w, a, b


@pytest.mark.parametrize("days,expected", [(0, 1.0), (90, 0.5), (180, 0.25), (361, 0.0)])
def test_a_grade_decays_by_half_every_90_days_and_is_not_read_after_a_year(store, days,
                                                                             expected):
    w, a, b = _one_pair(store)
    w.grade("idea", a, "useful", days_ago=days)
    assert taste.rank(store, NOW)[b].taste == pytest.approx(expected, abs=1e-3)


# -- 5. resemblance ----------------------------------------------------------------------------


def item(key="1", vec=None, obs=(), src=(), themes=(), topics=()):
    return taste.Item(("idea", key), None if vec is None else unit(vec), frozenset(obs),
                      frozenset(src), frozenset(themes), frozenset(topics))


def test_resemblance_is_the_strongest_feature_once_and_in_0_1():
    v = np.ones(DIM)
    same_theme_alike = taste.resemblance(item(vec=v, themes={"L"}), item(vec=v, themes={"L"}),
                                         CFG)
    assert same_theme_alike == (1.0, "same theme")
    half = taste.resemblance(item(obs={1, 2}), item(obs={2, 3, 4, 5}), CFG)
    assert half == (0.5, "shares 1 of its evidence")
    assert taste.resemblance(item(obs={1}), item(obs={1, 2}), CFG) == (1.0,
                                                                        "cites the same evidence")
    rng = np.random.default_rng(1)
    for _ in range(200):
        a, b = item(vec=rng.normal(size=DIM)), item(vec=rng.normal(size=DIM))
        r, _ = taste.resemblance(a, b, CFG)
        assert 0.0 <= r <= 1.0


def test_a_shared_source_alone_counts_nothing_and_the_topic_only_without_a_vector():
    v1, v2 = np.eye(DIM)[0], np.eye(DIM)[1]          # orthogonal: they do not read alike
    assert taste.resemblance(item(vec=v1, src={9}), item(vec=v2, src={9}), CFG)[0] == 0
    assert taste.resemblance(item(vec=v1, topics={3}), item(vec=v2, topics={3}), CFG)[0] == 0
    assert taste.resemblance(item(topics={3}), item(vec=v2, topics={3}), CFG) == (0.25,
                                                                                 "same topic")


def test_vectors_of_two_sizes_are_no_vector_never_an_error():
    """Two embedding models (a theme's centroid from before a model change, or no map to say
    which size is current): the pair reads as if a side had no vector, and the summary of
    such a library answers instead of failing."""
    a, b = item(vec=np.ones(DIM), topics={3}), item(vec=np.ones(4), topics={3})
    assert taste.resemblance(a, b, CFG) == (0.25, "same topic")
    assert taste.resemblance(item(vec=np.ones(DIM)), item(vec=np.ones(4)), CFG) == (0.0, "")


def test_reads_alike_ramps_between_the_two_cosines():
    a = np.eye(DIM)[0]
    for cos, want in ((0.2, 0.0), (0.45, 0.5), (0.7, 1.0)):
        b = cos * a + np.sqrt(1 - cos * cos) * np.eye(DIM)[1]
        r, why = taste.resemblance(item(vec=a), item(vec=b), CFG)
        assert r == pytest.approx(want, abs=1e-6)
        if want:
            assert why == f"reads alike ({cos:.2f})"


# -- 6. purged evidence ------------------------------------------------------------------------


def test_a_purged_observations_grade_counts_nothing(store):
    w, a, b = _one_pair(store)
    store.insert("feedback", {"target": "observation", "target_id": "999", "kind": "grade",
                              "value": "not_useful", "origin": "ui", "created_at": iso(NOW)})
    assert ("observation", "999") not in taste.graded(store, NOW, CFG)
    assert taste.rank(store, NOW)[b].taste == 0


def test_a_card_with_no_live_citations_ranks_by_theme_and_topic(store):
    w = World(store)
    t = w.topic("one")
    s = w.source(t)
    o = w.obs(s, w.vec())
    w.snapshot({o: 0}, {0: "L0"})
    graded = w.card([o], "L0", t)
    gone_theme = w.card([998], "L0")
    gone_topic = w.card([997], None, t)
    w.grade("idea", graded, "useful")
    ranks = taste.rank(store, NOW)
    m = taste.model(store, NOW)
    assert m.items[("idea", str(gone_theme))].vec is None
    assert ranks[gone_theme].taste == 1.0
    assert ranks[gone_theme].parts[0]["why"] == "same theme"
    assert ranks[gone_topic].taste == 0.25
    assert ranks[gone_topic].parts[0]["why"] == "same topic"


# -- 7. the line -------------------------------------------------------------------------------


def part(w, target="idea"):
    return {"weight": w, "target": target}


@pytest.mark.parametrize("parts,want", [
    ([part(0.9), part(0.88)], "ranked up: like 2 cards you upvoted"),
    ([part(-0.9)], "ranked down: like 1 card you downvoted"),
    ([part(-0.918), part(0.859), part(0.2, "observation"), part(0.15, "observation")],
     "ranked up: like 1 card you upvoted and 1 you downvoted · near 2 observations you upvoted"),
    ([part(0.1), part(0.09)], "ranked up: reads a little like what you upvoted"),
    ([part(-0.12, "observation")], "ranked down: reads a little like what you downvoted"),
    ([part(0.02)], ""),
    ([], ""),
])
def test_the_line_matches_the_parts(parts, want):
    assert taste.line(None, parts, CFG) == want


# -- 8. the worked example's shape -------------------------------------------------------------


def test_the_worked_example(store):
    """Two sibling pitches upvoted lift their third sibling and the neighbouring dispatch;
    a downvoted card sinks its theme; an untouched card keeps its place."""
    w = World(store, 11)
    s = w.source()
    memory = w.vec() * 4
    other = w.vec() * 4
    e = [w.obs(s, w.vec(memory, 0.3)) for _ in range(3)]          # one dispatch's links
    near = [w.obs(s, w.vec(memory, 0.6)) for _ in range(2)]       # the next dispatch's
    mcp = [w.obs(s, w.vec(other, 0.3)) for _ in range(3)]
    far = [w.obs(s, w.vec(None, 1.0)) for _ in range(30)]          # the rest of the library
    pts = {o: 0 for o in e + near} | {o: 1 for o in mcp} | {o: 2 for o in far}
    w.snapshot(pts, {0: "LM", 1: "LX", 2: "LF"})
    untouched = w.card(far[:3], "LF", asks=1)                     # stands on the most
    sib1, sib2, sib3 = w.card(e), w.card(e), w.card(e)
    neighbour = w.card(near)
    down = w.card(mcp[:2], "LX")
    same_theme = w.card(mcp[2:], "LX")
    obs_up = far[10]
    w.grade("idea", sib1, "useful", days_ago=17)
    w.grade("idea", sib2, "useful", days_ago=17)
    w.grade("idea", down, "not_useful", days_ago=11)
    w.grade("observation", obs_up, "useful", days_ago=20)
    ranks = taste.rank(store, NOW)
    order = sorted((r for r in ranks.values()), key=lambda r: r.key)
    ids = [r.id for r in order]
    assert ids[:2] == sorted([sib1, sib2], reverse=True)          # own useful, newest first
    assert ids[2] == sib3
    assert ranks[sib3].line == "ranked up: like 2 cards you upvoted"
    assert ranks[sib3].parts[0]["why"] == "cites the same evidence"
    assert ranks[neighbour].taste > 0 and ids.index(neighbour) < ids.index(untouched)
    assert ranks[same_theme].line.startswith("ranked down: like 1 card you downvoted")
    assert ids[-1] == down and ids[-2] == same_theme
    assert ranks[untouched].taste == 0 or ranks[untouched].line.startswith("ranked up")


# -- the settings ------------------------------------------------------------------------------


def test_the_settings_have_their_defaults_and_refuse_out_of_range():
    assert parse_grading(None) == GradingConfig()
    assert parse_grading({"half_life_days": 30}).half_life_days == 30.0
    for bad in ({"remove_ratio": 2}, {"half_life_days": 0}, {"cos_low": 0.7},
                {"window_days": 1.5}, {"remove_after": True}, {"nope": 1}):
        with pytest.raises(ConfigError):
            parse_grading(bad)


def test_a_shorter_half_life_is_read(store):
    w, a, b = _one_pair(store)
    w.grade("idea", a, "useful", days_ago=30)
    assert taste.rank(store, NOW, GradingConfig(half_life_days=30))[b].taste == \
        pytest.approx(0.5, abs=1e-3)


# -- the API -----------------------------------------------------------------------------------


def test_the_summary_counts_and_moves(store):
    w, cards, obs = random_world(store)
    w.grade("idea", cards[0], "useful")
    w.grade("observation", obs[1], "not_useful")
    w.grade("observation", obs[2], "useful")
    w.grade("observation", obs[2], "skip")
    got = taste.summary(store, NOW)
    assert got["counts"] == {"grades": 3, "cards": 1, "evidence": 2, "cleared": 1}
    i = got["ideas"]
    assert i["graded"] == 1 and i["moved"] + i["still"] + i["graded"] == i["shown"] == 40
    assert len(i["top"]) <= 5 and all(t["line"] for t in i["top"])
    assert all(t["taste"] != 0 for t in got["themes"])
