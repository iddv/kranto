"""``kranto archive`` and the retired settings (PR A1): every JSON file's
counts equal the tables', the sources are opened read-only and left byte for byte as they were,
the page lists each build with its repository, and a section of a feature that left loads,
is ignored, and is one line in the doctor."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from kranto import archive, doctor, launcher
from kranto import config as config_mod
from kranto.store import Store

from .test_kranto import make_host, user_home  # noqa: F401 - fixture

LOOP_SCHEMA = """
CREATE TABLE ideas (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
  source_ref TEXT, title TEXT, text TEXT NOT NULL, urls TEXT, context TEXT, card TEXT,
  state TEXT NOT NULL, reason TEXT, pitch TEXT, task_dir TEXT, build TEXT, gate TEXT,
  publish TEXT, signals TEXT, created REAL NOT NULL, updated REAL NOT NULL,
  kind TEXT NOT NULL DEFAULT 'app', later_until REAL);
CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, idea TEXT NOT NULL, ts REAL NOT NULL,
  state TEXT NOT NULL, note TEXT, data TEXT);
CREATE TABLE spend (id INTEGER PRIMARY KEY AUTOINCREMENT, idea TEXT, ts REAL NOT NULL,
  kind TEXT NOT NULL, usd REAL NOT NULL, in_tokens INTEGER, out_tokens INTEGER, project TEXT);
CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, idea TEXT,
  repos TEXT NOT NULL, charter TEXT, charter_v INTEGER NOT NULL DEFAULT 0, topic TEXT,
  settings TEXT, stats TEXT, health TEXT, state TEXT NOT NULL DEFAULT 'active',
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE charter_versions (project TEXT NOT NULL, v INTEGER NOT NULL, charter TEXT NOT NULL,
  by TEXT NOT NULL, note TEXT, at REAL NOT NULL, PRIMARY KEY (project, v));
CREATE TABLE changes (id TEXT PRIMARY KEY, project TEXT NOT NULL, fp TEXT NOT NULL,
  title TEXT NOT NULL, kind TEXT NOT NULL, class TEXT NOT NULL, state TEXT NOT NULL,
  card TEXT NOT NULL, filed TEXT, later_until REAL, created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE (project, fp));
"""

# what each retired table needs to take a row (the rest of its NOT NULL columns get a filler)
FILL = {"radar_trends": {"kind": "secular", "origin": "owner", "state": "active"},
        "radar_proposals": {"kind": "cyclical", "state": "proposed"},
        "deep_dives": {"reason": "operator"}}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _add(con: sqlite3.Connection, table: str, n: int) -> None:
    """``n`` rows in ``table``, each NOT NULL column without a default given a filler."""
    cols = [c for c in con.execute(f'PRAGMA table_info("{table}")')
            if c[3] and c[4] is None and not c[5]]          # notnull, no default, not the key
    for i in range(n):
        row = {}
        for c in cols:
            name, kind = c[1], (c[2] or "").upper()
            row[name] = FILL.get(table, {}).get(
                name, i + 1 if "INT" in kind else 0.5 if "REAL" in kind else
                ("2026-10-28T06:42:37Z" if name.endswith("_at") else f"{name} {i}"))
        if table == "deep_dives":
            row["observation_id"] = i + 1
        con.execute(f'INSERT INTO "{table}" ({", ".join(row)}) VALUES '
                    f'({", ".join("?" * len(row))})', list(row.values()))


@pytest.fixture
def home(user_home):  # noqa: F811
    h = user_home / ".kranto"
    launcher.make_home(h, 8800, user_home)
    cfg = config_mod.load(h, dotenv=False)
    Store.open(cfg.db_path).close()
    con = sqlite3.connect(cfg.db_path)
    con.execute("PRAGMA foreign_keys = OFF")
    for table, n in {"invest_cards": 3, "invest_card_events": 4, "invest_resolutions": 2,
                     "radar_trends": 2, "radar_proposals": 5, "radar_series": 7,
                     "deep_dives": 1}.items():
        _add(con, table, n)
    con.commit()
    con.close()
    loop = user_home / ".kranto" / "loop"
    loop.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(loop / "loop.db")
    con.executescript(LOOP_SCHEMA)
    pub = {"repo": "someone/plotkeeper", "url": "https://github.com/someone/plotkeeper"}
    con.execute("INSERT INTO ideas VALUES ('i1','f1','kranto',NULL,'Plotkeeper','t',NULL,NULL,"
                "NULL,'public',NULL,NULL,'/t/plotkeeper',NULL,NULL,?,NULL,1791228912.6,"
                "1791228999.0,'app',NULL)", (json.dumps(pub),))
    con.execute("INSERT INTO ideas VALUES ('i2','f2','kranto',NULL,'<b>Never built</b>','t',"
                "NULL,NULL,NULL,'rejected',NULL,NULL,NULL,NULL,NULL,NULL,NULL,1791228913.0,"
                "1791228913.0,'app',NULL)")
    con.executemany("INSERT INTO history (idea, ts, state) VALUES (?, ?, ?)",
                    [("i1", 1.0, "queued"), ("i1", 2.0, "public"), ("i2", 3.0, "rejected")])
    con.executemany("INSERT INTO spend (idea, ts, kind, usd) VALUES (?, ?, ?, ?)",
                    [("i1", 1.0, "build", 10.5), ("i1", 2.0, "pitch", 0.25),
                     (None, 3.0, "evolve", 1.0)])
    con.execute("INSERT INTO projects (id, name, kind, idea, repos, created, updated) VALUES "
                "('p1', 'Plotkeeper', 'built', 'i1', ?, 1.0, 1.0)",
                (json.dumps([{"repo": "someone/plotkeeper",
                              "url": "https://github.com/someone/plotkeeper"}]),))
    con.execute("INSERT INTO charter_versions VALUES ('p1', 1, 'keep it small', 'owner', NULL, 1)")
    con.execute("INSERT INTO changes VALUES ('c1','p1','fp','Fix','fix','small','open','{}',NULL,"
                "NULL,1,1)")
    con.commit()
    con.close()
    return h


def _table_counts(db: Path, tables) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def test_each_files_counts_equal_the_tables_and_nothing_is_written(home):
    cfg = config_mod.load(home, dotenv=False)
    loop_db = home / "loop" / "loop.db"
    before = {p: _sha(p) for p in (cfg.db_path, loop_db)}
    done = archive.write(home, cfg.db_path, loop_db)
    assert done.out == home / "archive" and not done.missing
    assert {p: _sha(p) for p in before} == before            # read-only, byte for byte
    for name, counts in done.counts.items():
        rec = json.loads((home / "archive" / f"{name}.json").read_text())
        assert rec["counts"] == counts
        db = loop_db if name in ("builds", "projects") else cfg.db_path
        assert counts == _table_counts(db, counts), name
        for table, rows in rec.get("tables", {}).items():
            assert len(rows) == counts[table], table
    inv = json.loads((home / "archive" / "invest.json").read_text())
    assert inv["counts"]["invest_cards"] == 3 and inv["counts"]["invest_card_events"] == 4
    assert all(t.startswith("invest_") for t in inv["counts"])       # not the frozen copies
    radar = json.loads((home / "archive" / "radar.json").read_text())
    assert radar["counts"]["radar_trends"] == 2 and radar["counts"]["radar_proposals"] == 5
    assert len(radar["tables"]["radar_series"]) == 7
    ext = json.loads((home / "archive" / "extension.json").read_text())
    assert ext["counts"] and all(t.startswith("browser_") for t in ext["counts"])
    b = json.loads((home / "archive" / "builds.json").read_text())
    assert b["counts"] == {"ideas": 2, "history": 3, "spend": 3}
    first = b["builds"][0]
    assert (first["title"], first["repo"], first["spend_usd"]) == ("Plotkeeper",
                                                                   "someone/plotkeeper", 10.75)
    assert len(first["history"]) == 2 and first["idea"]["publish"]["repo"] == "someone/plotkeeper"
    assert len(b["spend_without_build"]) == 1                 # every spend row is somewhere
    p = json.loads((home / "archive" / "projects.json").read_text())
    assert p["projects"][0]["charters"][0]["charter"] == "keep it small"
    assert len(p["projects"][0]["changes"]) == 1


def test_the_page_lists_each_build_with_its_repository_and_escapes(home):
    cfg = config_mod.load(home, dotenv=False)
    archive.write(home, cfg.db_path, home / "loop" / "loop.db")
    page = (home / "archive" / "index.html").read_text()
    assert "<h2>Builds (2)</h2>" in page and "<h2>Projects (1)</h2>" in page
    assert '<a href="https://github.com/someone/plotkeeper">someone/plotkeeper</a>' in page
    assert "&lt;b&gt;Never built&lt;/b&gt;" in page and "<b>Never" not in page
    assert "Invest (3 cards)" in page and "(2 trends, 5 proposals)" in page
    assert "<script" not in page and "http://" not in page     # self-contained, no fetch


def test_the_command_writes_the_home_archive_or_out(home, tmp_path):
    host = make_host(home.parent)
    assert launcher.main(["--home", str(home), "archive", "--json"], host) == 0
    assert (home / "archive" / "index.html").is_file()
    out = tmp_path / "elsewhere"
    assert launcher.main(["--home", str(home), "archive", "--out", str(out)], host) == 0
    assert json.loads((out / "builds.json").read_text())["counts"]["ideas"] == 2


def test_no_loop_and_a_fresh_library_write_empty_files(user_home, tmp_path):  # noqa: F811
    h = tmp_path / "fresh"
    config_mod.init_workspace(h)
    cfg = config_mod.load(h, dotenv=False)
    Store.open(cfg.db_path).close()
    done = archive.write(h, cfg.db_path, tmp_path / "no-loop" / "loop.db")
    assert done.missing and done.counts["builds"] == {}
    assert done.counts["invest"] and not any(done.counts["invest"].values())
    assert "<h2>Builds (0)</h2>" in (h / "archive" / "index.html").read_text()


def test_a_retired_section_loads_is_ignored_and_is_one_doctor_line(home, monkeypatch):
    monkeypatch.setitem(config_mod.RETIRED, "oldthing", "The old thing")
    path = config_mod.config_path(home)
    assert path is not None
    path.write_text(path.read_text() + "\noldthing:\n  enabled: true\n  nonsense: [1, 2]\n")
    cfg = config_mod.load(home, dotenv=False)
    assert cfg.retired == ("oldthing",)
    lines = doctor.retired_sections(cfg)
    assert [(c.status, c.name) for c in lines] == [("ok", "oldthing")]
    assert lines[0].detail.startswith("The old thing is not part of Kranto any more")
    assert str(home / "archive") in lines[0].detail
    assert "oldthing:" in path.read_text()                       # the file is left as written
    store = Store.open(cfg.db_path)
    try:
        said = [c for c in doctor.run(cfg, store, check_embedder=False) if c.name == "oldthing"]
    finally:
        store.close()
    assert len(said) == 1
    monkeypatch.delitem(config_mod.RETIRED, "oldthing")
    assert config_mod.load(home, dotenv=False).retired == ()
