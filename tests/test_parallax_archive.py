"""The Parallax archive: observations and themes imported, cards from the dispatches,
kept by retention, and never a flood (no new rows on Today, no arrivals, no alerts)."""

import dataclasses
import json
import zlib

import numpy as np
import pytest

from kranto import library
from kranto.config import (
    DEFAULT_CONFIG_YAML,
    ConfigError,
    ParallaxConfig,
    RetentionConfig,
    load,
)
from kranto.ideate import dispatches
from kranto.ideate.cards import _evidence, candidates
from kranto.importers import (
    import_parallax,
    import_parallax_themes,
    latest_themes,
    lineage_at,
    theme_member_ids,
)
from kranto.map.read import clusters as read_clusters
from kranto.map.read import latest
from kranto.map.snapshot import take_snapshot
from kranto.retention import compact
from kranto.sources import Item
from kranto.store import vec_to_blob

from .test_map import add_observations
from .test_web import rt, web  # noqa: F401 - fixtures

EXCERPT = ("I built a budget NAS from an old office mini PC, two drives in a mirror, Debian, "
           "Tailscale instead of port forwarding, and no proprietary enclosure firmware at all")
POLY = "Will the ceasefire hold through June 30? Resolves Yes if no strike lands on territory"


def unit(seed: int, near: np.ndarray | None = None, noise: float = 0.0) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=384)
    if near is not None:
        v = near + noise * v / np.linalg.norm(v)
    return v / np.linalg.norm(v)


def rec(ext, ts, url, *, firehose="reddit:r/example-host", excerpt=EXCERPT, vec=None, **kw):
    r = {"id": ext, "intern": "i", "firehose": firehose, "ts": ts, "kind": "mild_signal",
         "summary": f"summary of {ext}", "why_it_matters": "why", "content_quality": 0.8,
         "durability": 0.5, "opportunity": 0.5, "tags": ["t"],
         "embedding": (vec if vec is not None else unit(zlib.crc32(ext.encode()))).tolist(),
         "embedding_model": "nomic-embed-text-v1.5", "source_url": url,
         "source_excerpt": excerpt, "data_source": f"post:{ext}"}
    r.update(kw)
    return r


def write(path, records):
    path.mkdir(parents=True, exist_ok=True)
    (path / "library.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")


def imported(store):
    return {r["external_id"]: r for r in store.query(
        "SELECT * FROM observations WHERE admitted_by = 'import'")}


# -- importing observations ------------------------------------------------------------


def test_dedupes_by_url_oldest_first_and_by_near_duplicate(tmp_path, store, embedder):
    own = library.add_source(store, "rss", {"url": "https://ex.com/feed"}, label="Own Feed")
    library.record_observation(
        store, source_id=own, item=Item(id="own-1", title="t", body="b",
                                        url="https://example.com/own-post"),
        fields={"kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.5,
                "durability": 0.5, "opportunity": 0.5, "signal": 0.125, "override": False,
                "override_reason": None, "tags": []},
        embedding=embedder.embed_documents(["s"])[0], embedding_model="stub", llm_call_id=None,
        prompt_version="v", run_uuid="r", admitted_by="topic", topic_similarity=None)
    base, poly = unit(1), unit(2)
    write(tmp_path / "runs" / "a", [
        rec("later", "2026-05-02T10:00:00Z", "https://www.reddit.com/r/example-host/comments/1/nas/",
            vec=base),
        rec("crosspost", "2026-05-03T10:00:00Z", "https://www.reddit.com/r/selfhosted/2/nas",
            firehose="reddit:r/selfhosted", vec=unit(3, near=base, noise=0.3)),
        rec("same-text-other-meaning", "2026-05-04T10:00:00Z", "https://news.ycombinator.com/x",
            firehose="hn:frontpage", vec=unit(4)),
        rec("market-1", "2026-05-05T10:00:00Z", "https://polymarket.com/market/a",
            firehose="polymarket:polymarket", excerpt=POLY, vec=poly),
        rec("market-2", "2026-05-06T10:00:00Z", "https://polymarket.com/market/b",
            firehose="polymarket:polymarket", excerpt=POLY, vec=unit(5, near=poly, noise=0.1)),
        rec("own-url", "2026-05-07T10:00:00Z", "https://www.example.com/own-post/"),
        rec("no-ratings", "2026-05-08T10:00:00Z", "https://ex.org/n", content_quality=None),
    ])
    # an older observation of the same URL, in another file: it is the one kept
    write(tmp_path / "runs" / "b", [
        rec("earlier", "2026-05-01T10:00:00Z", "http://reddit.com/r/example-host/comments/1/nas",
            vec=base)])

    report = import_parallax(store, [tmp_path])
    assert report.files == 2 and report.read == 8
    assert report.skipped == {
        "same URL as an earlier archive observation": 1,
        "same URL as an observation the library already holds": 1,
        "near duplicate (same text, same meaning)": 1,
        "missing ratings or text": 1,
    }
    got = imported(store)
    assert set(got) == {"earlier", "same-text-other-meaning", "market-1", "market-2"}
    assert got["earlier"]["created_at"] == "2026-05-01T10:00:00Z"
    assert report.imported == 4
    again = import_parallax(store, [tmp_path])
    assert again.imported == 0 and again.already_present == 4
    # importing is not ingest: nothing is new to a watch or a strike gate
    assert store.query_one("SELECT COUNT(*) AS n FROM strike_candidates")["n"] == 0


def bundle(root, ids, *, clusters=("cluster_0", "cluster_0", "cluster_1")):
    """A snapshot bundle with two epochs: lineage L1 (cluster_1, then cluster_0) is alive,
    L2 (cluster_0 in the first epoch only) ended."""
    snaps = root / "snapshots"
    latest_dir = snaps / "latest"
    latest_dir.mkdir(parents=True)
    vecs = np.stack([unit(100 + i) for i in range(len(ids))]).astype(np.float32)
    (latest_dir / "manifest.json").write_text(json.dumps({
        "schema_version": 2, "observation_count": len(ids), "embedding_dim": 384,
        "generation_ts": "2026-05-02T00:00:00Z", "substrate_fingerprint": "sha256:abc"}))
    (latest_dir / "observations.json").write_text(json.dumps([
        {"id": i, "cluster_id": c, "embedding_index": n, "source_url": "u", "firehose": "f",
         "summary": "s", "ts": "t", "coords_2d": [0, 0]}
        for n, (i, c) in enumerate(zip(ids, clusters, strict=True))]))
    vecs.tofile(latest_dir / "embeddings.bin")
    (latest_dir / "keywords.json").write_text(json.dumps(
        {"keywords": {"0": ["nas", "mirror"], "1": ["market", "odds"]}}))
    (latest_dir / "cluster_names.json").write_text(json.dumps({"names": {"0": None, "1": None}}))
    (latest_dir / "trajectories.json").write_text(json.dumps({
        "epochs": [{"snapshot_ts": "2026-05-01T00:00:00Z", "observation_count": 10},
                   {"snapshot_ts": "2026-05-02T00:00:00Z", "observation_count": 20}],
        "lineages": [
            {"lineage_id": "L1", "history": [
                {"snapshot_ts": "2026-05-01T00:00:00Z", "cluster_id": "cluster_1",
                 "observation_count": 4},
                {"snapshot_ts": "2026-05-02T00:00:00Z", "cluster_id": "cluster_0",
                 "observation_count": 10}]},
            {"lineage_id": "L2", "history": [
                {"snapshot_ts": "2026-05-01T00:00:00Z", "cluster_id": "cluster_0",
                 "observation_count": 6}]}]}))
    for day, names in (("2026-05-01T0000Z", {"0": "Old markets", "1": "The server storage"}),
                       ("2026-05-02T0000Z", {"0": None, "1": None})):
        (snaps / day).mkdir()
        (snaps / day / "cluster_names.json").write_text(json.dumps({"names": names}))
    return latest_dir, vecs


def import_with_bundle(tmp_path, store):
    ids = ["a", "b", "c"]
    latest_dir, vecs = bundle(tmp_path, ids)
    write(tmp_path / "runs", [
        rec("a", "2026-05-01T00:00:00Z", "https://ex.org/a", excerpt="alpha", vec=vecs[0]),
        rec("b", "2026-05-01T01:00:00Z", "https://ex.org/b", excerpt="beta", vec=vecs[1]),
        rec("x", "2026-05-01T02:00:00Z", "https://ex.org/x", excerpt="gamma")])
    report = import_parallax(store, [tmp_path / "runs"], snapshot=latest_dir)
    return report, import_parallax_themes(store, latest_dir), latest_dir


def test_snapshot_reconciles_and_themes_carry_names_history_and_members(tmp_path, store):
    report, themes, latest_dir = import_with_bundle(tmp_path, store)
    assert report.snapshot == {"snapshot": 3, "records": 3, "in_both": 2, "snapshot_only": 1,
                               "records_only": 1, "embeddings_differ": 0}
    assert (themes.lineages, themes.written, themes.alive, themes.named) == (2, 2, 1, 2)
    by = {t["lineage_id"]: t for t in latest_themes(store)}
    l1, l2 = by["L1"], by["L2"]
    # the latest names are null: the most recent name it was given is its name
    assert l1["name"] == "The server storage" and l1["alive"] == 1
    assert l1["keywords"] == ["nas", "mirror"]
    assert [h["share"] for h in l1["history"]] == [0.4, 0.5]
    assert l2["name"] == "Old markets" and l2["alive"] == 0 and l2["keywords"] == []
    ids = imported(store)
    assert theme_member_ids(store, "L1") == sorted([ids["a"]["id"], ids["b"]["id"]])
    assert theme_member_ids(store, "L2") == []
    # a cluster id means something only within its epoch
    themes_now = latest_themes(store)
    assert lineage_at(themes_now, "cluster_0", "2026-05-01T12:00:00Z")["lineage_id"] == "L2"
    assert lineage_at(themes_now, "cluster_0", "2026-10-08T01:30:00Z")["lineage_id"] == "L1"
    assert lineage_at(themes_now, "cluster_0", "2026-04-01T00:00:00Z") is None
    assert import_parallax_themes(store, latest_dir).already_present == 2


def test_refuses_an_unknown_snapshot_schema(tmp_path, store):
    latest_dir, _ = bundle(tmp_path, ["a", "b", "c"])
    manifest = json.loads((latest_dir / "manifest.json").read_text())
    (latest_dir / "manifest.json").write_text(json.dumps({**manifest, "schema_version": 9}))
    with pytest.raises(ValueError, match="schema_version 9"):
        import_parallax_themes(store, latest_dir)


# -- retention -------------------------------------------------------------------------


def test_archive_is_kept_forever_unless_the_operator_says_otherwise(tmp_path, store):
    assert RetentionConfig().days_for_kind("parallax") == 0
    yaml_path = tmp_path / "kranto.yaml"
    yaml_path.write_text(DEFAULT_CONFIG_YAML)
    assert load(tmp_path, dotenv=False).retention.days_for_kind("parallax") == 0
    yaml_path.write_text(DEFAULT_CONFIG_YAML.replace("  by_kind: {}", "  by_kind: {reddit: 30}"))
    cfg = load(tmp_path, dotenv=False).retention
    assert cfg.days_for_kind("parallax") == 0 and cfg.days_for_kind("reddit") == 30

    write(tmp_path / "runs", [rec(f"r{i}", "2026-05-01T00:00:00Z", f"https://ex.org/{i}",
                                  excerpt=f"text {i}") for i in range(3)])
    import_parallax(store, [tmp_path / "runs"])
    compact(store, RetentionConfig(), None)
    assert len(imported(store)) == 3            # months older than 90 days, and kept
    compact(store, RetentionConfig(by_kind={"parallax": 30}), None)
    assert imported(store) == {}


def test_parallax_settings_are_checked(tmp_path):
    yaml_path = tmp_path / "kranto.yaml"
    for line, bad in (("topic_match: 0", "topic_match: 1.5"), ("topic_match: 0", "other: 1"),
                      ("topic_match: 0", "topic_match: true"),
                      ("card_evidence: false", "card_evidence: 1")):
        yaml_path.write_text(DEFAULT_CONFIG_YAML.replace("  " + line, "  " + bad))
        with pytest.raises(ConfigError, match="parallax"):
            load(tmp_path, dotenv=False)
    yaml_path.write_text(DEFAULT_CONFIG_YAML.replace("  topic_match: 0", "  topic_match: 0.5"))
    assert load(tmp_path, dotenv=False).parallax == ParallaxConfig(topic_match=0.5)


# -- no flood ----------------------------------------------------------------------------


def archive_rows(store, embedder, n, text, created="2026-05-01T00:00:00Z"):
    src = store.insert("sources", {"kind": "parallax", "params": '{"firehose":"x"}',
                                   "label": "x (Parallax)", "origin": "import",
                                   "created_at": created})
    vecs = embedder.embed_documents([f"{text} {i}" for i in range(n)])
    for i, v in enumerate(vecs):
        store.insert("observations", {
            "source_id": src, "item_id": f"a{i}", "kind": "beat", "summary": f"{text} {i}",
            "why_it_matters": "w", "content_quality": 0.9, "durability": 0.9,
            "opportunity": 0.9, "signal": 0.729, "tags": "[]", "embedding": vec_to_blob(v),
            "embedding_model": embedder.model_name, "external_id": f"ext-{i}",
            "admitted_by": "import", "created_at": created})


def test_imported_rows_are_on_the_map_but_never_arrivals(store, embedder):
    for theme in ("solar", "crdt", "bread"):
        add_observations(store, embedder, theme, 15, f"{theme}-a")
        add_observations(store, embedder, theme, 10, f"{theme}-b")
    take_snapshot(store, embedder, None)
    archive_rows(store, embedder, 60, "sourdough starter flour hydration oven crumb")
    report = take_snapshot(store, embedder, None)
    assert report.n == 135
    for c in read_clusters(store, report.snapshot_id):
        last = c["trajectory"][-1]
        assert last["new_total"] == 0 and last["new_in_cluster"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM strike_candidates")["n"] == 0
    archive = {r["id"] for r in store.query(
        "SELECT id FROM observations WHERE admitted_by = 'import'")}
    cited = {i for c in candidates(store, latest(store)) for i in c.observation_ids}
    assert cited and not cited & archive


def test_card_evidence_leaves_the_archive_out_unless_asked(store, embedder):
    add_observations(store, embedder, "solar", 3, "solar-a")
    archive_rows(store, embedder, 4, "solar microgrid battery kenya")
    rows = store.query("SELECT id, admitted_by FROM observations ORDER BY id")
    archive = [r["id"] for r in rows if r["admitted_by"] == "import"]
    snap = {"id": store.insert("snapshots", {
        "fingerprint": "f", "embedding_model": embedder.model_name, "n": len(rows), "k": 1,
        "params": "{}", "quality": "{}", "density": "{}",
        "created_at": "2026-09-24T12:00:00Z"}), "created_at": "2026-09-24T12:00:00Z"}
    for r in rows:
        store.insert("snapshot_points", {"snapshot_id": snap["id"], "observation_id": r["id"],
                                         "cluster": 0, "x": 0.0, "y": 0.0})
    cluster = {"cluster": 0, "representatives": archive[:3]}
    own_only = _evidence(store, snap, cluster)
    assert len(own_only) == 3 and not set(own_only) & set(archive)
    assert set(_evidence(store, snap, cluster, archive=True)) & set(archive)


def test_today_library_and_topics_keep_the_archive_in_its_place(web, rt):  # noqa: F811
    store = rt.store
    before = web.get("/api/today").json()["new_kept"]
    topic = library.active_topics(store)[0]
    archive_rows(store, rt.embedder, 5, "solar and batteries in Africa archive note")
    assert web.get("/api/today").json()["new_kept"] == before
    body = web.get("/api/observations").json()
    assert not body["results"][0]["source_label"].endswith("(Parallax)")
    assert all(not o["new"] for o in body["results"] if o["source_label"] == "x (Parallax)")
    only = web.get("/api/observations?source=parallax").json()
    assert only["total"] == 5 and {o["source_label"] for o in only["results"]} == \
        {"x (Parallax)"}
    labels = {o["source_label"] for o in
              web.get(f"/api/observations?topic={topic.id}&limit=50").json()["results"]}
    assert "x (Parallax)" not in labels
    rt.cfg = dataclasses.replace(rt.cfg, parallax=ParallaxConfig(topic_match=0.5))
    labels = {o["source_label"] for o in
              web.get(f"/api/observations?topic={topic.id}&limit=50").json()["results"]}
    assert "x (Parallax)" in labels


# -- dispatch cards --------------------------------------------------------------------

BOLD = """---
dispatch_id: 2026-10-08-001
generated_at: 2026-10-08T01:30:00Z
strategy: C
cluster_ids: [cluster_0, cluster_1]
schema_version: 2
title: "The pitch was the exclusion list"
slug: the-pitch-was-the-exclusion-list
---

A [the server NAS build](https://www.reddit.com/r/example-host/comments/1/nas/) lists what it
refuses. \
It is cheap.

Across the clusters, the [market](https://polymarket.com/market/a) names what will not count.

## The the server shipped a ledger of refusals

A [vendor post](https://example.org/unmatched) is not in the library. See [an earlier \
one](/blog/earlier).

## What this means

My bet, six to eighteen months out. By the end of Q2 2027, a vendor will lead with refusals.

**An OSS idea.** A `refusal-ledger` CLI for technical writers that reads a draft post and \
reports whether its exclusions are explicit. Ships with templates.

**A commercial pitch.** A positioning advisory for developer-tool startups. The buyer is a \
head of growth whose launch posts underconvert.

**A founder pitch.** A platform that generates a vendor's refusals page: every dependency \
they will not take on.

This article was generated from the [Parallax observation library](/parallax) by a fleet.
"""

PROSE = """---
dispatch_id: 2026-07-09-001
generated_at: 2026-07-09T01:30:00Z
strategy: C
cluster_ids: [cluster_0]
schema_version: 2
title: "The aha moment is the moat now"
slug: the-aha-moment-is-the-moat-now
---

The founder posted on [r/SaaS](https://www.reddit.com/r/example-host/comments/1/nas/) that she \
was building without AI.

## Where this goes

One falsifiable prediction, eighteen months out. By December 2027, two post-mortems name it.

The OSS play here is an aha-moment observability tool. Not another analytics library.

For commercial: aha reliability monitoring for AI-in-onboarding. The buyer is not a founder; \
she cannot afford it. The buyer is a Series B PM.

The founder move is to build the counter-pattern. Ship a SaaS where the AI is optional.
"""

DUMP = "---\ndispatch_id: 2026-04-27-001\nschema_version: 1\n---\n# Dispatch\n\n" \
       "**Cluster ID**: cluster_7.\n"
HALF = "---\ndispatch_id: 2026-06-01-001\nschema_version: 2\ntitle: Half\n---\n\nIntro.\n\n" \
       "**Open source.** A thing.\n\n**Commercial pitch.** Another thing.\n"


@pytest.fixture
def archive(tmp_path, store):
    import_with_bundle(tmp_path, store)
    write(tmp_path / "more", [
        rec("nas", "2026-05-02T00:00:00Z", "https://www.reddit.com/r/example-host/comments/1/nas/",
            excerpt="nas"),
        rec("market", "2026-05-02T01:00:00Z", "https://polymarket.com/market/a",
            firehose="polymarket:polymarket", excerpt="market")])
    import_parallax(store, [tmp_path / "more"])
    folder = tmp_path / "dispatches"
    (folder / "skipped").mkdir(parents=True)
    (folder / "skipped" / "2026-07-19-overlap.txt").write_text("Skipped: same clusters.")
    for name, text in (("2026-10-08-001", BOLD), ("2026-07-09-001", PROSE),
                       ("2026-04-27-001", DUMP), ("2026-06-01-001", HALF)):
        (folder / f"{name}.md").write_text(text)
    return folder


def test_parses_bold_and_prose_pitches_and_reports_what_lacks_them(archive):
    bold = dispatches.parse(archive / "2026-10-08-001.md")
    assert [p.kind for p in bold.pitches] == ["oss", "commercial", "founder"]
    oss = bold.pitches[0]
    assert oss.markdown.startswith("**An OSS idea.** A `refusal-ledger` CLI")
    assert dispatches.title_of(oss) == "A refusal-ledger CLI for technical writers"
    assert dispatches.who_of(bold.pitches[1]) == \
        "a head of growth whose launch posts underconvert"
    assert dispatches.prediction_by(dispatches.plain(bold.prediction), bold.date) == "2027-06-30"
    assert dispatches.thesis(bold).startswith("A the server NAS build lists what it refuses.")
    prose = dispatches.parse(archive / "2026-07-09-001.md")
    assert [(p.kind, dispatches.title_of(p)) for p in prose.pitches] == [
        ("oss", "An aha-moment observability tool"),
        ("commercial", "Aha reliability monitoring for AI-in-onboarding"),
        ("founder", "To build the counter-pattern")]
    assert dispatches.who_of(prose.pitches[1]) == "a Series B PM"
    assert dispatches.prediction_by(dispatches.plain(prose.prediction), prose.date) == \
        "2027-12-31"
    assert "schema 1" in dispatches.parse(archive / "2026-04-27-001.md").problem
    assert dispatches.parse(archive / "2026-06-01-001.md").problem == "no founder pitch"


@pytest.mark.parametrize(("text", "who"), [
    ("A service. The buyer is a head of growth.", "a head of growth"),
    ("A platform. The customer is the head of platform whose team argues.",
     "the head of platform whose team argues"),
    ("A desk. Buyers: compliance officers.", "compliance officers"),
    ("A feed. Customers are analysts and strategy teams.", "analysts and strategy teams"),
    ("Support contracts. The customers are trapped, the vendor has walked away.", None),
    ("A tool. The buyer is not a founder; she cannot afford it.", None),
])
def test_who_is_taken_only_when_the_pitch_names_the_buyer(text, who):
    pitch = dispatches.Pitch("commercial", "**Commercial pitch.**",
                             "**Commercial pitch.** " + text, True)
    assert dispatches.who_of(pitch) == who


def test_cards_cite_url_matched_observations_and_never_strike(archive, store):
    report = dispatches.import_dispatches(store, archive)
    assert (report.read, report.carded, report.lacking, report.cards) == (4, 2, 2, 6)
    assert (report.shown, report.unsupported) == (3, 3)
    assert report.skip_records == ["2026-07-19-overlap.txt"]
    assert (report.links, report.matched) == (4, 3)
    rows = store.query("SELECT * FROM ideas WHERE origin = 'dispatch' ORDER BY id")
    cards = {(json.loads(r["card"])["dispatch"]["dispatch_id"],
              json.loads(r["card"])["pitch_kind"]): (r, json.loads(r["card"])) for r in rows}
    row, card = cards[("2026-10-08-001", "oss")]
    assert row["status"] == "shown" and row["title"] == card["title"]
    assert card["pitch"] == dispatches.parse(archive / "2026-10-08-001.md").pitches[0].markdown
    assert [c["verified"] for c in card["citations"]] == ["url_match", "url_match"]
    assert card["evidence"][0]["claim"] == "A the server NAS build lists what it refuses."
    assert card["links"] == [{"url": "https://example.org/unmatched",
                              "claim": "A vendor post is not in the library."}]
    assert card["dispatch"]["url"] == "https://example.com/blog/the-pitch-was-the-exclusion-list"
    assert [x["lineage_id"] for x in card["lineages"]] == ["L1", None]
    assert card["prediction"]["by"] == "2027-06-30"
    # one matched link is not enough: stored, but not shown
    assert cards[("2026-07-09-001", "founder")][0]["status"] == "unsupported"
    assert store.query_one("SELECT COUNT(*) AS n FROM strike_candidates")["n"] == 0
    again = dispatches.import_dispatches(store, archive)
    assert again.cards == 0 and again.already == 2
    assert dispatches.import_dispatches(store, archive, only=["2026-07-09-001"]).read == 1


def test_ideas_api_filters_dispatch_cards_and_keeps_them_manual(web, rt, tmp_path):  # noqa: F811
    store = rt.store
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "2026-10-08-001.md").write_text(BOLD)
    write(tmp_path / "r", [
        rec("nas", "2026-05-02T00:00:00Z", "https://www.reddit.com/r/example-host/comments/1/nas/",
            excerpt="nas"),
        rec("market", "2026-05-02T01:00:00Z", "https://polymarket.com/market/a",
            firehose="polymarket:polymarket", excerpt="market")])
    import_parallax(store, [tmp_path / "r"])
    dispatches.import_dispatches(store, folder)
    everything = web.get("/api/ideas?origin=all&embedding=ref").json()["count"]
    # a reader that does not ask for them (the page's intake, an older UI) never sees them
    assert web.get("/api/ideas?embedding=ref").json()["count"] == everything - 3
    body = web.get("/api/ideas?origin=dispatch").json()
    assert body["count"] == 3
    oss = web.get("/api/ideas?origin=dispatch&kind=oss").json()["ideas"]
    assert [i["pitch_kind"] for i in oss] == ["oss"]
    one = web.get(f"/api/ideas/{oss[0]['id']}?embedding=ref").json()
    # ``intake`` (the build loop's automatic intake) left with builds (CUT)
    assert one["score"] is None and "intake" not in one
    assert one["pitch_label"] == "An OSS idea" and one["dispatch"]["slug"]
    assert {c["verified"] for c in one["citations"]} == {"url_match"}
    assert web.get("/api/ideas?kind=other").status_code == 400
    summary = web.get("/api/archive").json()
    assert summary["observations"] == 2 and summary["retention_days"] == 0
    assert summary["dispatch_cards"]["by_kind"] == {"oss": 1, "commercial": 1, "founder": 1}


def test_archive_themes_api_lists_themes_with_their_dispatches(web, rt, tmp_path):  # noqa: F811
    store = rt.store
    import_with_bundle(tmp_path, store)
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "2026-10-08-001.md").write_text(BOLD)
    dispatches.import_dispatches(store, folder)
    body = web.get("/api/archive/themes").json()
    assert [t["lineage_id"] for t in body["themes"]] == ["L1", "L2"]
    l1 = body["themes"][0]
    assert l1["name"] == "The server storage" and l1["alive"] and l1["members"] == 2
    assert [p["size"] for p in l1["trajectory"]] == [4, 10]
    assert [d["dispatch_id"] for d in l1["dispatches"]] == ["2026-10-08-001"]
    assert web.get("/api/archive/themes/L2").json()["dispatches"] == []
    assert web.get("/api/archive/themes/nope").status_code == 404
    members = web.get("/api/observations?theme=L1").json()
    assert members["total"] == 2
