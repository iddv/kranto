"""Migrations only add (section 5.3). An update's rollback reinstalls the old
code and keeps the database the new code migrated, so an old version must start on a newer
schema: every migration may only create tables, indexes, triggers and views, add nullable or
defaulted columns, and seed ``schema_meta`` or ``settings``. A migration that does anything
else (drops, renames, rewrites rows) breaks the rollback and needs its own plan."""

from __future__ import annotations

import re
import sqlite3

from kranto.store import _MIGRATIONS, Store

ALLOWED = [
    re.compile(r"^CREATE (VIRTUAL )?TABLE (IF NOT EXISTS )?\w+", re.I),
    re.compile(r"^CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?\w+", re.I),
    re.compile(r"^CREATE TRIGGER (IF NOT EXISTS )?\w+", re.I),
    re.compile(r"^CREATE VIEW (IF NOT EXISTS )?\w+", re.I),
    re.compile(r"^ALTER TABLE \w+ ADD COLUMN ", re.I),
    re.compile(r"^INSERT (OR IGNORE )?INTO (schema_meta|settings)\b", re.I),
]

# Existing migrations that do more than add, each with why it is safe for a rollback. A new
# entry here needs the same: an old version must still start on the result.
ALLOWLIST: dict[int, str] = {
    12: "fills the new full-text index from the existing observations: it writes only the "
        "table the same migration created",
    13: "drops the no-delete triggers so the recorded purge path can remove expired "
        "rows; every install a rollback can return to already ran it",
    31: "copies migration 30's mod_* rows (and money_orders) into the cub_* tables the same "
        "migration created, ids kept (the rename,); it writes only its own "
        "new tables and leaves the old ones as they were, so an older version still starts "
        "and reads them",
    35: "fills idea_topics and idea_citations, the tables the same migration created, from "
        "the cards' own JSON and topic_sources; it writes no existing table, "
        "so an older version starts and never reads them",
}


def statements(script: str) -> list[str]:
    """The SQL statements of a script (a trigger's body stays in one statement)."""
    out, buf = [], ""
    for line in script.splitlines():
        line = re.sub(r"--.*$", "", line)
        buf += line + "\n"
        if sqlite3.complete_statement(buf):
            if buf.strip().rstrip(";").strip():
                out.append(" ".join(buf.split()).rstrip(";").strip())
            buf = ""
    if buf.strip():
        out.append(" ".join(buf.split()))
    return out


def problems(script: str) -> list[str]:
    bad = []
    for s in statements(script):
        if not any(p.match(s) for p in ALLOWED):
            bad.append(s[:120])
        elif re.match(r"^ALTER TABLE", s, re.I) and re.search(r"\bNOT NULL\b", s, re.I) \
                and not re.search(r"\bDEFAULT\b", s, re.I):
            bad.append(f"NOT NULL without DEFAULT: {s[:100]}")
    return bad


def test_every_migration_only_adds():
    found = {n: problems(script) for n, script in _MIGRATIONS}
    failing = {n: p for n, p in found.items() if p and n not in ALLOWLIST}
    assert failing == {}, failing


def test_the_allowlist_is_not_stale():
    found = {n: problems(script) for n, script in _MIGRATIONS}
    assert all(found.get(n) for n in ALLOWLIST), "remove the allowlisted ones that now pass"


def test_the_lint_catches_what_breaks_a_rollback():
    assert problems("DROP TABLE observations;")
    assert problems("ALTER TABLE runs RENAME COLUMN summary TO s;")
    assert problems("ALTER TABLE runs ADD COLUMN x TEXT NOT NULL;")
    assert problems("UPDATE runs SET status = 'ok';")
    assert not problems("ALTER TABLE runs ADD COLUMN x TEXT NOT NULL DEFAULT '';")
    assert not problems("CREATE TRIGGER t AFTER INSERT ON runs BEGIN SELECT 1; END;")


def test_an_older_version_opens_a_newer_database(tmp_path):
    """What the rollback relies on: a migration this version does not know is ignored."""
    db = tmp_path / "kranto.db"
    store = Store.open(db)
    store.close()
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE from_the_future (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_meta (key, value) VALUES ('migration:9999', 'x')")
    conn.commit()
    conn.close()
    store = Store.open(db)
    try:
        assert not store.missing_tables()
        assert 9999 in store.applied_migrations()
        # its table keeps the newer version's rules: no append-only trigger from this one
        assert "from_the_future" not in store.append_only_tables()
    finally:
        store.close()
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND "
                            "tbl_name = 'from_the_future'").fetchall() == []
        conn.execute("UPDATE from_the_future SET id = 2")
        conn.execute("DELETE FROM from_the_future")
    finally:
        conn.close()


def test_every_table_of_a_new_database_is_one_a_migration_made(tmp_path):
    """Triggers go on the tables known migrations create: on a new database that is every
    library table, so nothing loses its append-only rule."""
    from kranto.store import MUTABLE_TABLES, _derived_tables, _known_tables
    store = Store.open(tmp_path / "kranto.db")
    try:
        rows = store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {r[0] for r in rows}
        derived = set(_derived_tables(store._conn))
        assert tables - MUTABLE_TABLES - derived <= _known_tables()
        assert set(store.append_only_tables()) == tables - MUTABLE_TABLES - derived
    finally:
        store.close()
