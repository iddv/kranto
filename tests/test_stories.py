"""Stories and origins: near-duplicates on pre-judge text, counted once."""

import json
import sqlite3
from datetime import timedelta

import numpy as np
import pytest

from kranto import library, sources, stories, textsig
from kranto.config import (
    BudgetConfig,
    Config,
    ConfigError,
    IngestConfig,
    LookConfig,
    MapConfig,
    RetentionConfig,
    StoriesConfig,
    _parse_stories,
)
from kranto.ideate import cards
from kranto.map import bursts, compute
from kranto.map.read import clusters as read_clusters
from kranto.map.snapshot import take_snapshot
from kranto.retention import compact
from kranto.sources import Item
from kranto.store import iso
from kranto.tick import run_ingest

from .conftest import FIXED_NOW, chat_response, llm_config
from .test_map import add_observations

CONTRIB = json.dumps({
    "kind": "beat", "summary": "a concrete thing", "why_it_matters": "because",
    "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9,
})
SKIP = json.dumps({"skip": True})

POST = ("We built a tiny sync engine for local-first apps",
        "It merges edits from offline replicas with a CRDT and stores everything in SQLite. "
        "After six months in production with two small teams we learned that conflict "
        "resolution matters less than predictable snapshots, and that most users never "
        "notice a merge at all. Happy to answer questions about the design.")
OTHER = ("Sourdough hydration notes from a home baker",
         "Raising hydration from seventy to eighty percent opened the crumb but made shaping "
         "much harder; a longer cold proof fixed most of it.")


class Feed:
    kind = "feed"
    items: dict[str, list[Item]] = {}

    def __init__(self, http, *, name):
        self.name = name

    @property
    def label(self):
        return f"feed:{self.name}"

    def fetch(self):
        return list(self.items.get(self.name, []))

    def enrich(self, item):
        return item


@pytest.fixture(autouse=True)
def feed_kind(monkeypatch):
    monkeypatch.setitem(sources.KINDS, "feed", Feed)
    Feed.items = {}


def item(item_id, title, body, *, url=None, hours=0):
    return Item(id=item_id, title=title, body=body,
                url=url or f"https://site-{item_id}.example.org/post",
                published_at=FIXED_NOW - timedelta(hours=hours))


def source(store, name, feed):
    Feed.items[name] = feed
    return library.add_source(store, "feed", {"name": name}, label=f"feed:{name}")


def config(tmp_path, **stories_cfg):
    # One judge call per item: these tests count calls to see what reached the
    # judge. Screened-out items as stories are tested in test_look.py.
    return Config(
        root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
        ingest=IngestConfig(max_items_per_source=60, backfill_items=60,
                            exploration_fraction=0.0, fetch_full_text=False),
        map=MapConfig(), stories=StoriesConfig(**stories_cfg),
        look=LookConfig(enabled=False),
    )


def run(cfg, store, client, embedder, now=FIXED_NOW):
    return run_ingest(cfg, store, client, embedder, sources.HTTP(), clock=lambda: now)


def outcomes(store):
    return {(r["source_id"], r["item_id"]): r["outcome"]
            for r in store.query("SELECT * FROM items_seen")}


def links(store):
    return {(r["source_id"], r["item_id"]): dict(r)
            for r in store.query("SELECT * FROM story_links")}


def edited(title, body, every):
    """``body`` with every ``every``-th word replaced: an edited crosspost."""
    words = body.split()
    return title + " (crosspost)", " ".join(
        f"changed{i}" if i % every == 0 else w for i, w in enumerate(words))


# -- signatures ----------------------------------------------------------------------


def test_signatures_ignore_markup_and_urls():
    sig = textsig.signature(textsig.item_text(*POST))
    assert sig.dtype == np.uint32 and sig.shape == (textsig.PERMUTATIONS,)
    marked = textsig.item_text(
        POST[0], "<p>" + POST[1].replace("SQLite", 'SQLite <a href="https:&#x2F;&#x2F;'
                                         'x.org&#x2F;y" rel="nofollow">here</a>') + "</p>")
    assert textsig.normalise('<a href="https:&#x2F;&#x2F;x.org" rel="nofollow">here</a> '
                             'and https://y.org/z there') == ["here", "and", "there"]
    assert textsig.similarity(sig, textsig.signature(marked)[None, :])[0] > 0.8
    unrelated = textsig.signature(textsig.item_text(*OTHER))
    assert textsig.similarity(sig, unrelated[None, :])[0] < 0.1
    assert textsig.signature("") is None
    quote = Item(id="q", title="", body="Great episode! [contains quote post or other "
                                        "embedded content]")
    assert stories.signature(quote) is None, "a feed's placeholder is not the post's text"


def test_signatures_do_not_drift_without_a_new_method():
    # Stored signatures are compared with new ones for a whole window: the seeded
    # hash functions and the normalisation must not change under the same METHOD.
    assert textsig.METHOD == "minhash128-w3-b1000-v1"
    assert textsig.signature("We built a tiny sync engine for local-first apps")[:4].tolist() \
        == [1261402775, 144130638, 434645112, 457279011]
    assert textsig._A[:2].tolist() == [6234069022551104909, 8457750182371691081]
    assert textsig._B[:2].tolist() == [6236906618574884982, 7741515988564161345]


def test_similarity_estimates_jaccard():
    a = textsig.normalise(textsig.item_text(*POST))
    for every in (3, 5, 10):
        title, body = edited(*POST, every)
        b = textsig.normalise(textsig.item_text(title, body))
        sa, sb = textsig.shingles(a), textsig.shingles(b)
        exact = len(sa & sb) / len(sa | sb)
        est = textsig.similarity(textsig.signature(" ".join(a)),
                                 textsig.signature(" ".join(b))[None, :])[0]
        assert abs(est - exact) < 0.15, (every, est, exact)


# -- ingest ----------------------------------------------------------------------------


def test_a_crosspost_is_consumed_without_a_model_call_and_joins_the_story(
        store, embedder, make_client, tmp_path):
    a = source(store, "a", [item("a1", *POST), item("a2", *OTHER)])
    b = source(store, "b", [item("b1", *POST)])
    c = source(store, "c", [item("c1", *POST)])
    client = make_client(lambda body: chat_response(CONTRIB))
    report = run(config(tmp_path), store, client, embedder)
    assert len(client.fake.requests) == 2, "only a1 and a2 reach the judge"
    seen = outcomes(store)
    assert seen[(a, "a1")] == "contributed"
    assert seen[(b, "b1")] == seen[(c, "c1")] == "near_duplicate"
    assert [s.near_duplicates for s in report.sources] == [0, 1, 1]
    found = links(store)
    assert set(found) == {(b, "b1"), (c, "c1")}
    for key in found:
        assert (found[key]["root_source_id"], found[key]["root_item_id"]) == (a, "a1")
        assert found[key]["judged"] == 0 and found[key]["similarity"] == 1.0
    # Signatures are kept for every consumed copy; no text is stored with them.
    assert store.query_one("SELECT COUNT(*) AS n FROM item_signatures")["n"] == 4
    assert store.query_one("SELECT method FROM item_signatures LIMIT 1")["method"] \
        == textsig.METHOD


def test_an_edited_crosspost_is_judged_and_linked(store, embedder, make_client, tmp_path):
    title, body = edited(*POST, 20)
    sim = textsig.similarity(textsig.signature(textsig.item_text(*POST)),
                             textsig.signature(textsig.item_text(title, body))[None, :])[0]
    assert 0.5 <= sim < 0.9, sim
    a = source(store, "a", [item("a1", *POST)])
    b = source(store, "b", [item("b1", title, body)])
    client = make_client(lambda body: chat_response(CONTRIB))
    report = run(config(tmp_path), store, client, embedder)
    assert len(client.fake.requests) == 2, "an edited copy can carry new detail"
    assert outcomes(store)[(b, "b1")] == "contributed"
    link = links(store)[(b, "b1")]
    assert (link["root_source_id"], link["root_item_id"], link["judged"]) == (a, "a1", 1)
    assert report.sources[1].linked == 1
    # Below link_at nothing is linked.
    assert not links(store).get((a, "a1"))


def test_the_same_source_repeats_only_with_history_and_within_days(
        store, embedder, make_client, tmp_path):
    history = [item(f"h{i}", f"Distinct post number {i} about topic {i}",
                    f"body {i} " + " ".join(f"w{i}x{j}" for j in range(30)), hours=i)
               for i in range(25)]
    s = source(store, "s", history + [item("p1", *POST, hours=1), item("p2", *POST)])
    client = make_client(lambda body: chat_response(SKIP))
    cfg = config(tmp_path)
    run(cfg, store, client, embedder)
    # First run: no history for this source yet, so a repost is judged again
    # (a templated feed's first items must not be read as reposts).
    assert outcomes(store)[(s, "p1")] == outcomes(store)[(s, "p2")] == "skipped"
    calls = len(client.fake.requests)
    Feed.items["s"] = [item("p3", *POST)]
    run(cfg, store, client, embedder, now=FIXED_NOW + timedelta(days=1))
    assert outcomes(store)[(s, "p3")] == "near_duplicate"
    assert len(client.fake.requests) == calls
    # Older than same_source_days: a recurring thread, judged again.
    Feed.items["s"] = [item("p4", *POST)]
    run(cfg, store, client, embedder, now=FIXED_NOW + timedelta(days=5))
    assert outcomes(store)[(s, "p4")] == "skipped"


def template(n, start=0):
    body = ("This market will resolve to the temperature range that contains the highest "
            "temperature recorded at the airport station in degrees Celsius. The resolution "
            "source is the station history page; revisions after the next data point are not "
            "considered, and the market resolves to whole degrees.")
    return [item(f"m{t}", f"Will the highest temperature in Kuala Lumpur be {t}C on May 31?",
                 body, hours=1) for t in range(start, start + n)]


def test_a_templated_source_is_detected_and_its_items_are_all_judged(
        store, embedder, make_client, tmp_path):
    m = source(store, "markets", template(30))
    client = make_client(lambda body: chat_response(SKIP))
    cfg = config(tmp_path)
    run(cfg, store, client, embedder)
    assert len(client.fake.requests) == 30
    index = stories.Index.load(store, cfg.stories, FIXED_NOW)
    assert m in index.templated and not index.same_source_allowed(m)
    Feed.items["markets"] = template(3, start=40)
    run(cfg, store, client, embedder, now=FIXED_NOW + timedelta(hours=2))
    assert len(client.fake.requests) == 33, "distinct markets are distinct events"
    assert not links(store)


def test_listed_templated_sources_are_never_matched_with_themselves(
        store, embedder, make_client, tmp_path):
    history = [item(f"h{i}", f"Distinct post number {i} about topic {i}",
                    f"body {i} " + " ".join(f"w{i}x{j}" for j in range(30)), hours=i)
               for i in range(25)]
    s = source(store, "s", history + [item("p1", *POST, hours=1)])
    client = make_client(lambda body: chat_response(SKIP))
    run(config(tmp_path), store, client, embedder)
    cfg = config(tmp_path, templated_sources=(s,))
    assert not stories.Index.load(store, cfg.stories, FIXED_NOW).same_source_allowed(s)
    Feed.items["s"] = [item("p2", *POST)]
    run(cfg, store, client, embedder, now=FIXED_NOW + timedelta(hours=1))
    assert outcomes(store)[(s, "p2")] == "skipped"


def test_short_texts_and_unread_items_are_never_matched(store, embedder, make_client, tmp_path):
    a = source(store, "a", [item("a1", "Coding on Paper", ""), item("a2", *POST)])
    b = source(store, "b", [item("b1", "Coding on Paper", ""), item("b2", *POST)])
    replies = iter([CONTRIB, "not json at all", CONTRIB, CONTRIB])  # a1, a2, b1, b2
    client = make_client(lambda body: chat_response(next(replies)))
    run(config(tmp_path), store, client, embedder)
    seen = outcomes(store)
    # Three words are not evidence of one story; a reply that did not parse is not
    # a reading of the text, so the copy is judged.
    assert seen[(a, "a1")] == "contributed" and seen[(b, "b1")] == "contributed"
    assert seen[(a, "a2")] == "parse_failed" and seen[(b, "b2")] == "contributed"
    assert len(client.fake.requests) == 4 and not links(store)


# -- reading: origins, mixes, movement --------------------------------------------------


def test_origin_is_the_registrable_domain():
    assert stories.origin("https://docs.anthropic.com/en/x?utm_source=y") == "anthropic.com"
    assert stories.origin("https://www.anthropic.com/news/a") == "anthropic.com"
    assert stories.origin("https://a.b.example.co.uk/p") == "example.co.uk"
    assert stories.origin("https://someone.github.io/post") == "someone.github.io"
    assert stories.origin("https://www.reddit.com/r/x/comments/1/y") is None
    assert stories.origin("https://news.ycombinator.com/item?id=1") is None
    assert stories.origin("https://github.com/owner/repo/releases") is None
    assert stories.origin("https://192.168.0.1/x") is None
    assert stories.origin("javascript:alert(1)") is None
    assert stories.origin(None) is None


def test_one_origin_cannot_make_a_cluster_cross_source():
    labels = ["a"] * 5 + ["b"] * 5
    assert compute.source_mix(labels)[2] is True
    vendor = ["vendor.com"] * 8 + ["x.org", "y.org"]
    assert compute.source_mix(labels, vendor)[2] is False
    assert compute.source_mix(labels, ["vendor.com"] * 7 + [None] * 3)[2] is True
    assert compute.source_mix(labels, [None] * 10)[2] is True, "platform pages never dominate"
    assert stories.origin_mix(["v.com", "v.com", None, "w.org"]) == ({"v.com": 2, "w.org": 1},
                                                                    0.5)


def test_one_origin_cannot_make_a_lineage_rise():
    before = {"burst": 0, "q_value": None}
    entered = {"burst": 1, "q_value": 0.01, "new_max_origin_share": 0.5}
    assert bursts.rising([before, entered], True)
    assert not bursts.rising([before, {**entered, "new_max_origin_share": 0.8}], True)
    assert bursts.rising([before, {"burst": 1, "q_value": 0.01}], True), "older points"


def link(store, copy_source, copy_item, root_source, root_item):
    store.insert("story_links", {
        "source_id": copy_source, "item_id": copy_item, "matched_source_id": root_source,
        "matched_item_id": root_item, "root_source_id": root_source, "root_item_id": root_item,
        "similarity": 0.95, "judged": 0, "created_at": "2026-09-24T10:00:00Z"})


def test_copies_count_once_in_shares_mixes_and_the_cross_source_rule(store, embedder):
    for theme in ("crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
        add_observations(store, embedder, theme, 10, f"{theme}-b")
    a = add_observations(store, embedder, "solar", 15, "solar-a")
    b = add_observations(store, embedder, "solar", 10, "solar-b")
    before = take_snapshot(store, embedder, None)
    solar = [c for c in read_clusters(store, before.snapshot_id) if "solar-a" in c["source_mix"]]
    assert solar[0]["cross_source"] and solar[0]["stories"] == 25
    # Every solar-b item turns out to be a crosspost of a solar-a item.
    for i in range(10):
        link(store, b, f"solar-solar-b-{i}", a, f"solar-solar-a-{i}")
    after = take_snapshot(store, embedder, None, force=True)
    solar = [c for c in read_clusters(store, after.snapshot_id) if "solar-a" in c["source_mix"]]
    c = solar[0]
    assert (c["size"], c["stories"]) == (25, 15)
    assert c["source_mix"] == {"solar-a": 15}
    assert not c["cross_source"], "one voice crossposted is not a second source"
    assert c["share"] == pytest.approx(15 / 65)
    quality = after.quality if "stories" in after.quality else json.loads(store.query_one(
        "SELECT quality FROM snapshots WHERE id = ?", (after.snapshot_id,))["quality"])
    assert quality["stories"]["observations"] == 75 and quality["stories"]["distinct"] == 65


def test_a_copy_of_an_earlier_story_is_not_a_new_arrival(store, embedder):
    for theme in ("solar", "crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
    first = take_snapshot(store, embedder, None)
    assert first.status == "ok"
    copies = add_observations(store, embedder, "solar", 6, "solar-copies")
    a = library.list_sources(store)[0].id
    for i in range(6):
        link(store, copies, f"solar-solar-copies-{i}", a, f"solar-solar-a-{i}")
    second = take_snapshot(store, embedder, None)
    points = [c["trajectory"][-1] for c in read_clusters(store, second.snapshot_id)]
    assert all(p["new_total"] == 0 and p["new_in_cluster"] == 0 for p in points)
    assert sum(c["size"] for c in read_clusters(store, second.snapshot_id)) == 51


def test_a_deep_dive_child_never_adds_a_story(store, embedder):
    for theme in ("solar", "crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
    first = take_snapshot(store, embedder, None)
    parent = store.query_one("SELECT id, source_id FROM observations WHERE item_id = ?",
                             ("solar-solar-a-0",))
    words = "solar microgrid battery kenya off-grid pay-as-you-go inverter panels"
    fields = {"kind": "beat", "summary": words, "why_it_matters": "w", "content_quality": 0.8,
              "durability": 0.8, "opportunity": 0.5, "signal": 0.32, "override": False,
              "override_reason": None, "tags": []}
    for i, relation in enumerate(("discussion", "link", "repository")):
        call = store.insert("llm_calls", dict(
            purpose="deep_dive", tier="judge", model="m", prompt_version="v", request="{}",
            status="ok", attempts=1, cost_usd=0.0, created_at="2026-09-24T10:00:00Z"))
        library.record_observation(
            store, source_id=parent["source_id"], item=Item(id=f"dd-{i}", title="t", body=words),
            fields=fields, embedding=embedder.embed_documents([words])[0],
            embedding_model=embedder.model_name, llm_call_id=call, prompt_version="v",
            run_uuid="r", admitted_by="deep_dive", topic_similarity=None,
            parent={"parent_id": parent["id"], "relation": relation})
    second = take_snapshot(store, embedder, None)
    assert second.status == "ok", second.error
    quality = json.loads(store.query_one("SELECT quality FROM snapshots WHERE id = ?",
                                         (second.snapshot_id,))["quality"])
    assert quality["stories"]["observations"] == 48
    assert quality["stories"]["distinct"] == 45, "children belong to their parent's story"
    points = [c["trajectory"][-1] for c in read_clusters(store, second.snapshot_id)]
    assert all(p["new_total"] == 0 for p in points), "children are not new arrivals"
    assert first.snapshot_id != second.snapshot_id


def test_idea_evidence_cites_one_observation_per_story(store, embedder):
    for theme in ("crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
    a = add_observations(store, embedder, "solar", 12, "solar-a")
    b = add_observations(store, embedder, "solar", 12, "solar-b")
    for i in range(12):
        link(store, b, f"solar-solar-b-{i}", a, f"solar-solar-a-{i}")
    snap = take_snapshot(store, embedder, None)
    cluster = next(c for c in read_clusters(store, snap.snapshot_id)
                   if "solar-a" in c["source_mix"])
    row = store.query_one("SELECT * FROM snapshots WHERE id = ?", (snap.snapshot_id,))
    ids = cards._evidence(store, row, cluster)
    rows = store.query(f"SELECT source_id, item_id FROM observations WHERE id IN "
                       f"({','.join('?' * len(ids))})", tuple(ids))
    told = {r["item_id"].split("-")[-1] for r in rows}
    assert len(told) == len(ids), "no story cited twice"


# -- the check -------------------------------------------------------------------------


def store_signatures(store, texts, now=FIXED_NOW, prefix="i"):
    src = library.add_source(store, "rss", {"url": "https://n.example.org/feed"}, label="n")
    for i, text in enumerate(texts):
        sig = textsig.signature(text)
        store.insert("item_signatures", {"source_id": src, "item_id": f"{prefix}{i}",
                                         "method": textsig.METHOD,
                                         "signature": textsig.to_blob(sig),
                                         "created_at": iso(now)})


def test_null_check_passes_on_distinct_texts_with_real_copies(store):
    rng = np.random.default_rng(1)
    vocab = [f"word{i}" for i in range(3000)]
    texts = [" ".join(rng.choice(vocab, size=60)) for _ in range(80)]
    texts += texts[:10]  # ten crossposts
    store_signatures(store, texts)
    result = stories.null_check(store, StoriesConfig(), FIXED_NOW)
    assert result["status"] == "ok"
    assert result["real_rate"] > 0.15 and result["null_rate"] == 0.0
    assert not result["explained_by_chance"]


def test_null_check_fails_when_boilerplate_makes_everything_alike(store):
    boilerplate = ("this is an automatic post triggered within two minutes of an official "
                   "status update check on progress and whether or not the incident has been "
                   "resolved yet here also check the performance megathread for reports ") * 3
    texts = [f"{boilerplate} incident {i} affected model {i * 7}" for i in range(80)]
    store_signatures(store, texts)
    result = stories.null_check(store, StoriesConfig(), FIXED_NOW)
    assert result["status"] == "ok" and result["real_rate"] > 0.9
    assert result["null_rate"] > 0.5
    assert result["explained_by_chance"], "the check must be able to fail"


def test_null_check_needs_enough_items(store):
    store_signatures(store, ["one two three four five six"] * 5)
    assert stories.null_check(store, StoriesConfig(), FIXED_NOW)["status"] == "too_few"


# -- retention and the append-only discipline -----------------------------------------


def test_signatures_expire_through_a_recorded_purge_and_links_stay(store):
    store_signatures(store, [f"{w} alpha beta gamma delta epsilon" for w in "abc"],
                     now=FIXED_NOW - timedelta(days=40))
    store_signatures(store, ["zeta eta theta iota kappa lambda"], now=FIXED_NOW, prefix="new")
    link(store, 1, "i1", 1, "i0")
    report = compact(store, RetentionConfig(default_days=0), None,
                     stories_cfg=StoriesConfig(window_days=30), clock=lambda: FIXED_NOW)
    assert report.status == "ok", report.error
    assert report.removed == {"item_signatures": 3}
    assert store.query_one("SELECT COUNT(*) AS n FROM item_signatures")["n"] == 1
    purge = store.query_one("SELECT * FROM purges WHERE table_name = 'item_signatures'")
    assert purge["row_count"] == 3 and "comparison window" in purge["reason"]
    assert store.query_one("SELECT COUNT(*) AS n FROM story_links")["n"] == 1
    assert store.get_setting("purge_token") is None


def test_signatures_and_links_are_append_only(store):
    store_signatures(store, ["one two three four five six"])
    link(store, 1, "x", 1, "i0")
    for sql in ("UPDATE item_signatures SET method = 'x'", "UPDATE story_links SET judged = 1",
                "DELETE FROM item_signatures", "DELETE FROM story_links"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query(sql)
    trigger = store.query_one(
        "SELECT sql FROM sqlite_master WHERE name = 'item_signatures_no_delete'")["sql"]
    assert "purge_token" in trigger


# -- configuration ----------------------------------------------------------------------


def test_stories_config_is_validated():
    assert _parse_stories(None) == StoriesConfig()
    cfg = _parse_stories({"skip_at": 0.95, "templated_sources": [3, 4]})
    assert cfg.skip_at == 0.95 and cfg.templated_sources == (3, 4)
    for bad in ({"link_at": 0.95, "skip_at": 0.9}, {"link_at": 0}, {"skip_at": 1.5},
                {"templated_sources": ["polymarket"]}, {"window_days": -1}, {"nope": 1}):
        with pytest.raises(ConfigError):
            _parse_stories(bad)
