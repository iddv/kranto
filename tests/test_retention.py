"""Retention and compaction: expired observations become rollups, and
removal is possible only inside a recorded purge."""

import json
import sqlite3
import zlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from kranto import library, retention
from kranto.cli import main
from kranto.config import (
    BudgetConfig,
    Config,
    ConfigError,
    IngestConfig,
    MapConfig,
    RetentionConfig,
    init_workspace,
    load,
)
from kranto.ideate import cards
from kranto.llm import LLMClient
from kranto.map.read import map_payload
from kranto.map.snapshot import take_snapshot
from kranto.runtime import open_runtime
from kranto.search import Index, search_rollups
from kranto.sources import Item
from kranto.store import PURGEABLE_AT_MIGRATION_13, PURGEABLE_TABLES, Store, iso, vec_to_blob
from kranto.web.app import create_app

from .conftest import FIXED_NOW, chat_response, llm_config, web_client
from .test_map import THEMES

OLD = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)      # the week of Monday 2026-08-31
RECENT = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)
NOW = FIXED_NOW                                     # 2026-09-24
SHORT = RetentionConfig(default_days=14)


def observe(store, embedder, theme, count, label, when, kind="rss", start=0):
    src = library.add_source(store, kind, _params(kind, label), label=label)
    words = THEMES[theme].split()
    ids = []
    for i in range(start, start + count):
        rng = np.random.default_rng(zlib.crc32(f"{theme}-{label}-{i}".encode()))
        summary = " ".join(rng.choice(words, size=6)) + f" note {i}"
        fields = {"kind": "beat", "summary": summary, "why_it_matters": "w",
                  "content_quality": 0.8, "durability": 0.8, "opportunity": 0.5 + i / 100,
                  "signal": 0.32 + i / 1000, "override": False, "override_reason": None,
                  "tags": []}
        call = store.insert("llm_calls", dict(
            purpose="judge", tier="judge", model="m", prompt_version="v",
            request=f"raw third-party text {theme} {i}", response="{}", status="ok",
            attempts=1, cost_usd=0.001, created_at=iso(when)))
        ids.append(library.record_observation(
            store, source_id=src,
            item=Item(id=f"{theme}-{label}-{i}", title="t", body=summary,
                      url=f"https://ex.com/{theme}/{label}/{i}"),
            fields=fields, embedding=embedder.embed_documents([summary])[0],
            embedding_model=embedder.model_name, llm_call_id=call, prompt_version="v",
            run_uuid="r", admitted_by="topic", topic_similarity=None, now=when))
    return src, ids


def _params(kind, label):
    return {"subreddit": label} if kind == "reddit" else {"url": f"https://ex.com/{label}"}


def rollup_model(body):
    content = body["messages"][-1]["content"]
    assert "Week: 2026-08-31 to 2026-09-06" in content
    return chat_response(json.dumps({
        "name": "solar week", "summary": "Mail a@example.com about solar microgrids in Kenya."}))


@pytest.fixture
def library_with_history(store, embedder):
    old = {}
    for theme in THEMES:
        old[theme] = observe(store, embedder, theme, 15, f"{theme}-old", OLD)[1]
        observe(store, embedder, theme, 10, f"{theme}-new", RECENT)
    return store, old


# -- the purge path ------------------------------------------------------------------


def test_delete_outside_a_purge_is_refused_with_recursive_triggers_on(store):
    assert store.query_one("PRAGMA recursive_triggers")[0] == 1
    obs = store.insert("observations", dict(
        kind="beat", summary="s", why_it_matters="w", content_quality=0.5, durability=0.5,
        opportunity=0.5, signal=0.125, embedding=vec_to_blob(np.ones(4) / 2),
        embedding_model="stub", external_id="x1", created_at="2026-09-24T12:00:00Z"))
    now = "2026-09-24T12:00:00Z"
    store.insert("llm_calls", dict(purpose="judge", tier="judge", model="m", prompt_version="v",
                                   request="{}", status="ok", attempts=1, created_at=now))
    store.insert("syntheses", dict(cache_key="k", kind="k", subject="s", input_ids="[]",
                                   text="t", created_at=now))
    snap = store.insert("snapshots", dict(fingerprint="f", embedding_model="stub", n=1, k=1,
                                          params="{}", quality="{}", density="[]",
                                          created_at=now))
    store.insert("snapshot_points", dict(snapshot_id=snap, observation_id=obs, cluster=0,
                                         x=0.0, y=0.0))
    store.insert("sources", {"kind": "rss", "params": "{}", "label": "s", "origin": "manual",
                             "created_at": now})
    store.insert("items_seen", {"source_id": 1, "item_id": "a", "outcome": "contributed",
                                "created_at": now})
    store.insert("item_signatures", {"source_id": 1, "item_id": "a", "method": "m",
                                     "signature": b"\x00" * 8, "created_at": now})
    store.insert("story_links", {"source_id": 1, "item_id": "b", "matched_source_id": 1,
                                 "matched_item_id": "a", "root_source_id": 1, "root_item_id": "a",
                                 "similarity": 1.0, "judged": 0, "created_at": now})
    store.insert("purges", {"table_name": "observations", "row_count": 1, "reason": "r",
                            "created_at": now})
    child = store.insert("observations", dict(
        kind="beat", summary="c", why_it_matters="w", content_quality=0.5, durability=0.5,
        opportunity=0.5, signal=0.125, embedding=vec_to_blob(np.ones(4) / 2),
        embedding_model="stub", external_id="x2", created_at=now))
    store.insert("observation_links", {"parent_id": obs, "child_id": child,
                                       "relation": "discussion", "created_at": now})
    store.insert("deep_dives", {"observation_id": obs, "reason": "operator", "created_at": now})
    store.insert("run_marks", {"run_uuid": "r1", "kind": "ingest", "ts": now, "mark": "started"})
    store.insert("browser_captures", {"token_name": "browser:b", "site": "s", "url": "u",
                                      "canonical_url": "u", "item_id": "browser:x",
                                      "mode": "watch", "captured_at": now, "created_at": now})
    for table in PURGEABLE_TABLES + ("items_seen", "story_links", "purges", "snapshots",
                                         "deep_dives"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query(f"DELETE FROM {table}")
    for verb in ("INSERT OR REPLACE INTO", "REPLACE INTO"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.query(
                f"{verb} observations (id, kind, summary, why_it_matters, content_quality, "
                "durability, opportunity, signal, embedding, embedding_model, created_at) "
                "VALUES (?, 'beat', 'overwritten', 'w', 0, 0, 0, 0, x'00', 'stub', 'now')",
                (obs,))
    assert store.query_one("SELECT summary FROM observations WHERE id = ?", (obs,))["summary"] \
        == "s"
    # A token row written outside a purge by some other path still does not open
    # UPDATE, and the trigger text names the token it checks.
    sql = store.query_one("SELECT sql FROM sqlite_master WHERE name = 'observations_no_delete'")
    assert "purge_token" in sql["sql"]


def test_a_purge_deletes_only_purgeable_rows_and_never_updates(store):
    obs = store.insert("observations", dict(
        kind="beat", summary="s", why_it_matters="w", content_quality=0.5, durability=0.5,
        opportunity=0.5, signal=0.125, embedding=vec_to_blob(np.ones(4) / 2),
        embedding_model="stub", created_at="2026-09-24T12:00:00Z"))
    store.insert("sources", {"kind": "rss", "params": "{}", "label": "s", "origin": "manual",
                             "created_at": "2026-09-25T00:00:00Z"})
    store.insert("items_seen", {"source_id": 1, "item_id": "a", "outcome": "contributed",
                                "created_at": "2026-09-25T00:00:00Z"})
    with pytest.raises(sqlite3.IntegrityError, match="append-only"), store.purge() as conn:
        conn.execute("UPDATE observations SET summary = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"), store.purge() as conn:
        conn.execute("DELETE FROM items_seen")
    with pytest.raises(RuntimeError), store.purge() as conn:
        conn.execute("DELETE FROM observations")
        raise RuntimeError("rolled back")
    assert store.query_one("SELECT COUNT(*) AS n FROM observations")["n"] == 1
    assert store.get_setting("purge_token") is None
    with store.purge() as conn:
        conn.execute("DELETE FROM observations WHERE id = ?", (obs,))
    assert store.query_one("SELECT COUNT(*) AS n FROM observations")["n"] == 0
    assert store.get_setting("purge_token") is None
    assert store.query_one("PRAGMA foreign_keys")[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.query("DELETE FROM items_seen")


def test_migration_13_puts_the_token_on_an_existing_database(tmp_path):
    path = tmp_path / "old.db"
    Store.open(path).close()
    raw = sqlite3.connect(path)  # back to the schema before migration 13
    script = ["DROP TRIGGER observations_fts_delete;", "DROP TABLE rollups_fts;",
              "DROP TABLE rollups;", "DROP TABLE purges;", "DROP TABLE source_retention;",
              "DROP TABLE evidence_snapshots;",
              "DELETE FROM schema_meta WHERE key = 'migration:13';"]
    for table in PURGEABLE_AT_MIGRATION_13:
        script += [f"DROP TRIGGER {table}_no_delete;",
                   f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"]
    raw.executescript("\n".join(script))
    raw.close()
    s = Store.open(path)
    assert 13 in s.applied_migrations()
    for table in PURGEABLE_AT_MIGRATION_13:
        sql = s.query_one("SELECT sql FROM sqlite_master WHERE name = ?",
                          (f"{table}_no_delete",))["sql"]
        assert "purge_token" in sql
    assert "rollups" in s.append_only_tables() and "purges" in s.append_only_tables()
    assert "rollups_fts" not in s.append_only_tables()
    s.close()


# -- compaction ------------------------------------------------------------------------


def test_compaction_replaces_expired_observations_with_rollups(library_with_history, embedder,
                                                               make_client):
    store, old = library_with_history
    take_snapshot(store, embedder, None)
    expired = [i for ids in old.values() for i in ids]
    store.insert("syntheses", {"cache_key": "k", "kind": "neighbourhood",
                               "subject": f"obs:{expired[0]}", "input_ids": json.dumps(expired[:3]),
                               "text": "t", "created_at": iso(RECENT)})
    items_before = store.query_one("SELECT COUNT(*) AS n FROM items_seen")["n"]
    spend_before = store.month_spend(NOW)
    index = Index(store, embedder.model_name)
    index.refresh()
    assert len(index.ids) == 75
    client = make_client(rollup_model)

    report = retention.compact(store, SHORT, client, clock=lambda: NOW)

    assert report.status == "ok", report.error
    assert report.expired == 45 and report.periods == 1
    left = {r["id"] for r in store.query("SELECT id FROM observations")}
    assert len(left) == 30 and not left & set(expired)
    rollups = store.query("SELECT * FROM rollups ORDER BY id")
    assert len(rollups) == report.rollups >= 2
    assert sum(r["replaced_count"] for r in rollups) == 45
    assert {r["period_start"] for r in rollups} == {"2026-08-31T00:00:00Z"}
    assert all(r["summary"] == "Mail [email] about solar microgrids in Kenya." for r in rollups)
    assert all(r["summary_call_id"] for r in rollups)
    first = rollups[0]
    assert len(json.loads(first["urls"])) <= 5 and json.loads(first["keywords"])
    assert json.loads(first["platform_mix"]) and json.loads(first["kind_counts"]) == {
        "beat": first["size"]}
    assert first["embedding_model"] == embedder.model_name

    purges = {r["table_name"]: r for r in store.query("SELECT * FROM purges")}
    assert {t: purges[t]["row_count"] for t in purges} == {
        "observations": 45, "snapshot_points": 45, "llm_calls": 45, "syntheses": 1}
    assert json.loads(purges["observations"]["rollup_ids"]) == [r["id"] for r in rollups]
    assert "14 days" in purges["observations"]["reason"]
    assert not store.query("SELECT 1 FROM llm_calls WHERE request LIKE 'raw third-party%' "
                           "AND created_at < '2026-09-10'")
    # Nothing consumed is fetched again, and the budget still sees what was spent.
    assert store.query_one("SELECT COUNT(*) AS n FROM items_seen")["n"] == items_before
    rollup_calls = 0.001 * len(rollups)
    assert store.month_spend(NOW) == pytest.approx(spend_before + rollup_calls)
    assert store.spend_since(OLD - timedelta(days=1)) == pytest.approx(
        spend_before + rollup_calls)
    assert store.spend_since(OLD + timedelta(days=1)) == pytest.approx(
        spend_before + rollup_calls - 0.045)
    # The search index drops removed rows although the newest id is unchanged.
    index.refresh()
    assert len(index.ids) == 30 and not set(index.ids.tolist()) & set(expired)
    # The full-text index forgot the removed rows.
    hits = {r["rowid"] for r in store.query(
        "SELECT rowid FROM observations_fts WHERE observations_fts MATCH 'note'")}
    assert hits == left

    run = store.query_one("SELECT * FROM runs WHERE kind = 'compact'")
    assert run["status"] == "ok" and json.loads(run["summary"])["removed"]["observations"] == 45
    again = retention.compact(store, SHORT, client, clock=lambda: NOW)
    assert again.status == "ok" and again.expired == 0 and again.rollups == 0

    # The map is drawn again from what is left.
    snap = take_snapshot(store, embedder, None)
    assert snap.status == "ok" and snap.n == 30
    latest = store.query_one("SELECT * FROM snapshots ORDER BY id DESC LIMIT 1")
    assert len(map_payload(store, latest)["points"]["id"]) == 30


def test_search_finds_rollups_by_meaning_and_by_words(library_with_history, embedder,
                                                      make_client):
    store, _ = library_with_history
    retention.compact(store, SHORT, make_client(rollup_model), clock=lambda: NOW)
    index = Index(store, embedder.model_name)
    lexical = search_rollups(index, embedder, "microgrids kenya")
    assert lexical and store.query_one("SELECT name FROM rollups WHERE id = ?",
                                       (lexical[0].rollup_id,))["name"] == "solar week"
    by_meaning = search_rollups(index, embedder, THEMES["bread"])
    top = store.query_one("SELECT keywords FROM rollups WHERE id = ?",
                          (by_meaning[0].rollup_id,))
    assert set(json.loads(top["keywords"])) & set(THEMES["bread"].split())


def test_retention_age_per_kind_and_per_source(store, embedder):
    rss, _ = observe(store, embedder, "solar", 5, "feed", OLD)
    reddit, _ = observe(store, embedder, "crdt", 5, "sub", OLD, kind="reddit")
    cfg = RetentionConfig(default_days=90, by_kind={"reddit": 14})
    assert retention.retention_days(store, cfg)[rss] == 90
    assert retention.retention_days(store, cfg)[reddit] == 14
    report = retention.compact(store, cfg, None, clock=lambda: NOW)
    assert report.expired == 5
    assert {r["source_id"] for r in store.query("SELECT source_id FROM observations")} == {rss}

    retention.set_source_retention(store, rss, 0, "keep this one")
    assert retention.compact(store, RetentionConfig(default_days=1), None,
                             clock=lambda: NOW).expired == 0
    retention.set_source_retention(store, rss, 10)
    retention.set_source_retention(store, rss, None)  # back to the kind's default
    assert retention.retention_days(store, cfg)[rss] == 90
    with pytest.raises(ValueError, match="no source"):
        retention.set_source_retention(store, 999, 5)


def test_without_a_model_rollups_are_written_unnamed(library_with_history):
    store, _ = library_with_history
    report = retention.compact(store, SHORT, None, clock=lambda: NOW)
    assert report.status == "ok" and report.summaries_skipped == "no model client"
    assert report.rollups and all(
        r["name"] is None and r["summary"] is None and json.loads(r["keywords"])
        for r in store.query("SELECT * FROM rollups"))


def test_failed_summary_calls_degrade_the_run_but_still_compact(library_with_history,
                                                               make_client):
    store, _ = library_with_history
    client = make_client(lambda body: chat_response("not json at all"))
    report = retention.compact(store, SHORT, client, clock=lambda: NOW)
    assert report.status == "degraded" and report.summaries_failed == report.rollups
    assert store.query_one("SELECT COUNT(*) AS n FROM observations")["n"] == 30


def test_paused_compaction_writes_rollups_without_spending(library_with_history, make_client):
    store, _ = library_with_history
    store.pause("testing")
    client = make_client(rollup_model)
    report = retention.compact(store, SHORT, client, clock=lambda: NOW)
    assert report.status == "ok" and "paused" in report.summaries_skipped
    assert client.fake.requests == []
    assert report.expired == 45


def test_idea_cards_keep_their_evidence_after_compaction(library_with_history, embedder,
                                                         make_client, tmp_path):
    store, old = library_with_history
    rows = library.observations_by_id(store, old["solar"][:2])
    base = {"pattern": "p", "where_now": "w", "thesis": "t", "cheapest_test": "c",
            "risks": "r", "prediction": {"statement": "", "by": None}, "why_selected": "w",
            "ratings": {k: {"value": 0.5, "reason": "r"} for k in cards.RATINGS}}
    new_card = {**base, "title": "new", "evidence": [
        {"n": 1, "claim": "claim one", **cards.evidence_snapshot(rows[old["solar"][0]])}]}
    legacy_card = {**base, "title": "legacy", "evidence": [
        {"n": 1, "claim": "claim two", "observation_id": old["solar"][1]}]}
    for card in (new_card, legacy_card):
        store.insert("ideas", {
            "fingerprint": "f", "origin": "cross_source", "evidence_key": card["title"],
            "input_ids": "[]", "title": card["title"], "card": json.dumps(card), "score": 0.1,
            "status": "shown", "dropped": "[]", "created_at": iso(RECENT)})
    retention.compact(store, SHORT, None, clock=lambda: NOW)

    ideas = cards.list_ideas(store)
    view = cards.evidence_view(store, ideas)
    by_title = {i["title"]: i for i in ideas}
    for title, oid in (("new", old["solar"][0]), ("legacy", old["solar"][1])):
        v = view[(by_title[title]["id"], oid)]
        assert v["compacted"] and v["summary"] == rows[oid]["summary"]
        assert v["url"] == f"https://ex.com/solar/solar-old/{0 if title == 'new' else 1}"
    assert store.query_one("SELECT COUNT(*) AS n FROM evidence_snapshots")["n"] == 1

    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=5),
                 ingest=IngestConfig(), map=MapConfig(), retention=SHORT)
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(rollup_model))
    with web_client(create_app(rt)) as web:
        listed = web.get("/api/ideas").json()
        cited = [e for i in (listed["ideas"] if isinstance(listed, dict) else listed)
                 for e in i["evidence"]]
        assert {e["claim"] for e in cited} == {"claim one", "claim two"}
        assert all(e["compacted"] for e in cited)
        assert rows[old["solar"][1]]["summary"] in {e["summary"] for e in cited}


def test_reads_after_compaction(library_with_history, embedder, make_client, tmp_path):
    store, old = library_with_history
    take_snapshot(store, embedder, None)
    client = make_client(rollup_model)
    retention.compact(store, SHORT, client, clock=lambda: NOW)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=5),
                 ingest=IngestConfig(), map=MapConfig(),
                 retention=RetentionConfig(default_days=14, by_kind={"reddit": 7}))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=client)
    with web_client(create_app(rt)) as web:
        assert web.get("/api/observations").json()["compacted"]["replaced"] == 45
        found = web.get("/api/observations?q=microgrids+kenya&cutoff=1").json()
        assert "solar week" in [r["name"] for r in found["rollups"]]
        rollups = web.get("/api/rollups").json()
        assert "solar week" in [r["name"] for r in rollups["results"]]
        assert rollups["retention_line"] == "14 days; reddit 7 days"
        kept = web.get("/api/health").json()["retention"]
        removed = {r["table_name"]: r["n"] for r in kept["removed"]}
        assert removed["observations"] == 45 and removed["llm_calls"] == 45
        assert web.get(f"/api/observations/{old['solar'][0]}").status_code == 404
        for page in ("/api/clusters", "/api/map"):
            assert web.get(page).status_code == 200
        api = web.get("/api/rollups?q=microgrids").json()
        assert api["results"][0]["name"] == "solar week"
        assert web.get("/api/rollups").json()["total"] == store.query_one(
            "SELECT COUNT(*) AS n FROM rollups")["n"]
        assert web.get("/api/status").json()["rollups"] > 0


# -- configuration and the command line ------------------------------------------------


def test_retention_config_is_validated(tmp_path):
    init_workspace(tmp_path)
    cfg = load(tmp_path)
    # an imported Parallax archive is kept unless by_kind says otherwise
    # and X posts 30 days, a default by_kind.x may raise
    assert cfg.retention == RetentionConfig(default_days=90, by_kind={"parallax": 0, "x": 30},
                                            every_hours=24)
    path = tmp_path / "kranto.yaml"
    text = path.read_text()
    path.write_text(text.replace("by_kind: {}", "by_kind: {reddit: 30}"))
    assert load(tmp_path).retention.days_for_kind("reddit") == 30
    for bad, message in (("by_kind: {twitter: 30}", "unknown source kinds"),
                         ("by_kind: {reddit: -1}", "0 or more")):
        path.write_text(text.replace("by_kind: {}", bad))
        with pytest.raises(ConfigError, match=message):
            load(tmp_path)
    path.write_text(text.replace("default_days: 90", "default_days: yes"))
    with pytest.raises(ConfigError, match="default_days"):
        load(tmp_path)


def test_cli_sets_source_retention_and_compacts(tmp_path, capsys, embedder):
    init_workspace(tmp_path)
    cfg = load(tmp_path)
    store = Store.open(cfg.db_path)
    src, _ = observe(store, embedder, "solar", 3, "feed", datetime(2026, 1, 5, tzinfo=UTC))
    store.close()

    assert main(["-w", str(tmp_path), "sources", "retention", str(src), "0"]) == 0
    assert "kept forever" in capsys.readouterr().out
    assert main(["-w", str(tmp_path), "sources", "retention", str(src), "soon"]) == 2
    assert main(["-w", str(tmp_path), "sources", "retention", str(src), "default"]) == 0
    assert "kept 90 days (the default for its kind)" in capsys.readouterr().out

    def factory(c):  # no key: summaries are skipped, and nothing reaches the network
        s = Store.open(c.db_path)
        return open_runtime(c, store=s, embedder=embedder,
                            llm=LLMClient(s, c.llm, c.budget, api_key=""))

    assert main(["-w", str(tmp_path), "compact"], runtime_factory=factory) == 0
    out = capsys.readouterr().out
    assert "compact ok: 3 observations past their retention age" in out
    assert "removed 3 llm_calls, 3 observations" in out and "no API key" in out
    assert main(["-w", str(tmp_path), "status"]) == 0
    assert "rollups:      1 (in place of 3 compacted observations)" in capsys.readouterr().out


def test_small_groups_are_one_rollup_and_k_is_clamped():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(8, 16)).astype(np.float32)
    assert retention.choose_k(x) == 1
    centers = rng.normal(size=(3, 16)) * 5
    x = np.concatenate([c + rng.normal(size=(6, 16)) * 0.1 for c in centers]).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    assert 2 <= retention.choose_k(x) <= len(x) // retention.MIN_ROLLUP_SIZE


def test_long_summaries_are_cut_after_a_whole_sentence():
    text = "One sentence here. " * 100
    clipped = retention._clip(text.strip())
    assert len(clipped) <= retention.ROLLUP_SUMMARY_CHARS and clipped.endswith("here.")
    assert retention._clip("short.") == "short."


def test_calls_for_items_judged_but_not_kept_expire_with_their_source(store, embedder):
    src, _ = observe(store, embedder, "solar", 2, "feed", RECENT)
    reddit, _ = observe(store, embedder, "crdt", 1, "sub", RECENT, kind="reddit")

    def judged(source, item, outcome, when):
        call = store.insert("llm_calls", dict(
            purpose="judge", tier="judge", model="m", prompt_version="v",
            request=f"raw text of {item}", response="{}", status="ok", attempts=1,
            cost_usd=0.002, created_at=iso(when)))
        library.mark_seen(store, source, item, outcome, run_uuid="r", llm_call_id=call,
                          now=when)
        return call

    old_gated = judged(src, "g1", "gated", OLD)
    old_skipped = judged(reddit, "s1", "skipped", OLD)
    old_failed = judged(src, "p1", "parse_failed", OLD)
    recent = judged(src, "g2", "gated", RECENT)
    library.mark_seen(store, src, "d1", "duplicate", run_uuid="r", now=OLD)
    items = store.query_one("SELECT COUNT(*) AS n FROM items_seen")["n"]
    spend = store.month_spend(NOW)

    report = retention.compact(store, RetentionConfig(default_days=14, by_kind={"reddit": 30}),
                               None, clock=lambda: NOW)

    assert report.status == "ok" and report.expired == 0 and report.unkept_calls == 2
    left = {r["id"] for r in store.query("SELECT id FROM llm_calls")}
    assert old_gated not in left and old_failed not in left
    assert old_skipped in left  # reddit keeps 30 days
    assert recent in left
    # Calls behind the (recent) observations stay.
    kept = store.query("SELECT llm_call_id FROM observations")
    assert all(r["llm_call_id"] in left for r in kept)
    assert store.query_one("SELECT COUNT(*) AS n FROM items_seen")["n"] == items
    assert store.month_spend(NOW) == pytest.approx(spend)
    [purge] = store.query("SELECT * FROM purges")
    detail = json.loads(purge["detail"])
    assert purge["table_name"] == "llm_calls" and purge["row_count"] == 2
    assert detail["outcomes"] == {"gated": 1, "parse_failed": 1}
    assert detail["cost_by_day"] == {"2026-09-01": 0.004}
    assert "judged but not kept" in purge["reason"] and json.loads(purge["rollup_ids"]) == []
    cfg = RetentionConfig(default_days=14, by_kind={"reddit": 30})
    assert retention.compact(store, cfg, None, clock=lambda: NOW).unkept_calls == 0
    # Without the reddit setting, its call is past the default age too.
    assert retention.compact(store, RetentionConfig(default_days=14), None,
                             clock=lambda: NOW).unkept_calls == 1
    assert old_skipped not in {r["id"] for r in store.query("SELECT id FROM llm_calls")}


def test_calls_nothing_remaining_references_expire_at_the_default_age(store):
    def call(purpose, when, status="ok"):
        return store.insert("llm_calls", dict(
            purpose=purpose, tier="reason", model="m", prompt_version="v",
            request="third-party text", status=status, attempts=1, cost_usd=0.01,
            created_at=iso(when)))

    failed = call("judge", OLD, status="error")
    scout_gone = call("scout", OLD)
    scout_kept = call("scout", OLD)
    store.insert("sources", {"kind": "rss", "params": "{}", "label": "s", "origin": "scout",
                             "origin_call_id": scout_kept, "created_at": iso(OLD)})
    explain_kept = call("explain", OLD)
    store.insert("syntheses", dict(cache_key="k", kind="neighbourhood", subject="obs:1",
                                   input_ids="[]", text="t", llm_call_id=explain_kept,
                                   created_at=iso(OLD)))
    card_kept, verify_kept = call("card", OLD), call("verify", OLD)
    store.insert("ideas", {"fingerprint": "f", "origin": "cross_source", "evidence_key": "e",
                           "input_ids": "[]", "title": "t", "card": "{}", "score": 0.1,
                           "status": "shown", "dropped": "[]", "gen_call_id": card_kept,
                           "verify_call_id": verify_kept, "created_at": iso(OLD)})
    recent = call("explain", RECENT)
    spend = store.month_spend(NOW)

    assert retention.compact(store, RetentionConfig(default_days=0), None,
                             clock=lambda: NOW).unreferenced_calls == 0
    report = retention.compact(store, SHORT, None, clock=lambda: NOW)

    assert report.status == "ok" and report.unreferenced_calls == 2
    left = {r["id"] for r in store.query("SELECT id FROM llm_calls")}
    assert left == {scout_kept, explain_kept, card_kept, verify_kept, recent}
    assert failed not in left and scout_gone not in left
    assert store.month_spend(NOW) == pytest.approx(spend)
    [purge] = store.query("SELECT * FROM purges")
    detail = json.loads(purge["detail"])
    assert purge["row_count"] == 2 and detail["failed"] == 1
    assert detail["purposes"] == {"judge": 1, "scout": 1}
    assert detail["cost_by_day"] == {"2026-09-01": 0.02}
