import io
import json
import sqlite3

import numpy as np
import pytest

from kranto.store import Store, blob_to_vec, vec_to_blob

from .conftest import FIXED_NOW


def _observation(store: Store, **overrides) -> int:
    row = dict(
        kind="beat",
        summary="s",
        why_it_matters="w",
        content_quality=0.5,
        durability=0.5,
        opportunity=0.5,
        signal=0.125,
        embedding=vec_to_blob(np.ones(4) / 2),
        embedding_model="stub",
        created_at="2026-09-24T12:00:00Z",
    )
    row.update(overrides)
    return store.insert("observations", row)


def test_every_library_table_rejects_update_and_delete(store):
    tables = store.append_only_tables()
    assert {"observations", "llm_calls", "items_seen", "sources", "topics", "runs"} <= set(tables)
    triggers = {
        (r["tbl_name"], r["name"])
        for r in store.query("SELECT tbl_name, name FROM sqlite_master WHERE type = 'trigger'")
    }
    for table in tables:
        assert (table, f"{table}_no_update") in triggers
        assert (table, f"{table}_no_delete") in triggers


def test_populated_rows_cannot_be_updated_or_deleted(store):
    _observation(store)
    store.set_status("source", 1, "proposed")
    for table in ("observations", "status_events"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query(f"UPDATE {table} SET rowid = rowid")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query(f"DELETE FROM {table}")


def test_observation_update_is_refused_after_insert(store):
    obs_id = _observation(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.query("UPDATE observations SET summary = 'rewritten' WHERE id = ?", (obs_id,))
    assert store.query_one("SELECT summary FROM observations")["summary"] == "s"


def test_corrections_are_new_rows_that_supersede(store):
    first = _observation(store, summary="first take")
    second = _observation(store, summary="corrected", supersedes=first)
    rows = store.query("SELECT id, supersedes FROM observations ORDER BY id")
    assert [(r["id"], r["supersedes"]) for r in rows] == [(first, None), (second, first)]


def test_settings_are_mutable(store):
    store.set_setting("k", "v1")
    store.set_setting("k", "v2")
    assert store.get_setting("k") == "v2"
    store.delete_setting("k")
    assert store.get_setting("k") is None


def test_pause_and_resume(store):
    assert store.pause_reason() is None
    store.pause("maintenance")
    assert store.pause_reason() == "maintenance"
    store.resume()
    assert store.pause_reason() is None


def test_month_spend_counts_only_current_month(store):
    def call(created_at, cost):
        store.insert(
            "llm_calls",
            dict(
                purpose="judge", tier="judge", model="m", prompt_version="v", request="{}",
                status="ok", attempts=1, cost_usd=cost, created_at=created_at,
            ),
        )

    call("2026-08-31T23:59:59Z", 5.0)
    call("2026-09-01T00:00:00Z", 0.25)
    call("2026-09-24T11:00:00Z", 0.5)
    assert store.month_spend(FIXED_NOW) == pytest.approx(0.75)


def test_status_is_latest_event(store):
    assert store.current_status("source", 1) is None
    store.set_status("source", 1, "proposed")
    store.set_status("source", 1, "approved")
    assert store.current_status("source", 1) == "approved"


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "lib.db"
    s1 = Store.open(path)
    version = s1.schema_version()
    _observation(s1)
    s1.close()
    s2 = Store.open(path)
    assert s2.schema_version() == version
    assert s2.query_one("SELECT COUNT(*) AS n FROM observations")["n"] == 1
    s2.close()


def test_vector_blob_roundtrip():
    vec = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    assert np.allclose(blob_to_vec(vec_to_blob(vec)), vec)


def test_export_jsonl_decodes_embeddings(store):
    _observation(store)
    out = io.StringIO()
    assert store.export_jsonl("observations", out) == 1
    record = json.loads(out.getvalue())
    assert record["summary"] == "s"
    assert record["embedding"] == [0.5, 0.5, 0.5, 0.5]


def test_export_rejects_unknown_table(store):
    with pytest.raises(ValueError):
        store.export_jsonl("sqlite_master; DROP TABLE x", io.StringIO())


def test_replace_cannot_overwrite_append_only_rows(store):
    """#44: SQLite resolves REPLACE by deleting the old row, which fires DELETE
    triggers only with recursive_triggers on. Without it this overwrote rows."""
    store.insert("sources", {"kind": "rss", "params": "{}", "label": "s", "origin": "manual",
                             "created_at": "2026-09-25T00:00:00Z"})
    store.insert("items_seen", {"source_id": 1, "item_id": "a", "outcome": "contributed",
                                "created_at": "2026-09-25T00:00:00Z"})
    for verb in ("INSERT OR REPLACE INTO", "REPLACE INTO"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            store.query(f"{verb} items_seen (source_id, item_id, outcome, created_at) "
                          "VALUES (1, 'a', 'gated', '2026-09-25T00:00:01Z')")
    assert store.query_one("SELECT outcome FROM items_seen")["outcome"] == "contributed"


def test_missing_tables_are_reported(tmp_path):
    path = tmp_path / "b.db"
    Store.open(path).close()
    raw = sqlite3.connect(path)
    raw.execute("DROP TABLE grades")
    raw.commit()
    raw.close()
    s = Store.open(path)
    assert s.missing_tables() == ["grades"]
    s.close()


def test_lock_paths_sit_next_to_the_database(tmp_path, store):
    s = Store.open(tmp_path / "data" / "c.db")
    assert s.lock_path("snapshot") == tmp_path / "data" / "c.db.snapshot.lock"
    assert store.lock_path("snapshot") is None
    s.close()


def _fts(store: Store, word: str) -> list[int]:
    return [r["rowid"] for r in store.query(
        "SELECT rowid FROM observations_fts WHERE observations_fts MATCH ? ORDER BY rowid",
        (word,))]


def test_full_text_index_is_derived_and_left_out_of_the_append_only_set(store):
    derived = {r["name"] for r in store.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'observations_fts%'")}
    assert "observations_fts" in derived and "observations_fts_data" in derived
    assert not derived & set(store.append_only_tables())
    triggers = {r["tbl_name"] for r in store.query(
        "SELECT tbl_name FROM sqlite_master WHERE type = 'trigger'")}
    assert not derived & triggers
    with pytest.raises(ValueError):
        store.export_jsonl("observations_fts_data", io.StringIO())


def test_full_text_index_follows_every_insert_through_segment_merges(store):
    """FTS5 rewrites and deletes rows in its shadow tables as segments merge;
    an append-only trigger there would make inserts fail after a few rows."""
    ids = [_observation(store, summary=f"heat pump number{i}") for i in range(40)]
    assert _fts(store, "pump") == ids
    assert _fts(store, "number17") == [ids[17]]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.query("UPDATE observations SET summary = 'x' WHERE id = ?", (ids[0],))


def test_migration_12_indexes_observations_written_before_it(tmp_path):
    path = tmp_path / "lib.db"
    s = Store.open(path)
    first = _observation(s, summary="biogas digesters in Rwanda", title=None)
    second = _observation(s, summary="s", why_it_matters="biogas again", tags='["digester"]')
    s.close()
    raw = sqlite3.connect(path)  # back to the schema before migration 12
    raw.executescript("DROP TRIGGER observations_fts_insert; DROP TABLE observations_fts; "
                      "DELETE FROM schema_meta WHERE key = 'migration:12';")
    raw.close()
    s = Store.open(path)
    assert 12 in s.applied_migrations()
    assert _fts(s, "biogas") == [first, second]
    assert _fts(s, "digester") == [first, second]
    third = _observation(s, summary="biogas three")
    assert _fts(s, "biogas") == [first, second, third]
    s.close()


def test_a_dropped_full_text_index_is_reported_missing(tmp_path):
    path = tmp_path / "c.db"
    Store.open(path).close()
    raw = sqlite3.connect(path)
    raw.execute("DROP TABLE observations_fts")
    raw.commit()
    raw.close()
    s = Store.open(path)
    assert s.missing_tables() == ["observations_fts"]
    s.close()
