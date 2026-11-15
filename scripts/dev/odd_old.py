#!/usr/bin/env python3
"""One version's part of the ``upgraded`` odd install (step 5): run with an older release's own
interpreter, on a home every
earlier version already wrote to, it opens the library with that version's ``Store`` (which
migrates it to that version) and writes what that version's writers store:

- a topic, linked sources with and without a test-fetch record (``validation`` as that version's
  ``add_source`` took it, when it took one), a run whose summary is that version's ingest
  summary, a card in that version's shape, a ``watch_paused`` setting;
- then a row in every table of that version's schema with every nullable column NULL.

It imports nothing of the current tree and only what every version since v0.2.0 has
(``kranto.store.Store``, ``kranto.library.add_topic``/``add_source``/``link_topic_source``,
``kranto.embed.StubEmbedder``); a writer a version lacks, or that refuses, is skipped and
listed. Standard library otherwise. Prints one JSON line: what it wrote and skipped.

Usage: odd_old.py HOME TAG
"""
from __future__ import annotations

import inspect
import json
import re
import sqlite3
import sys
from pathlib import Path

HOME, TAG = Path(sys.argv[1]), sys.argv[2]
# columns that hold JSON, by name: a NOT NULL one gets an empty value, never a
# made-up text (a later version's migration reads them with json_extract)
JSON_LISTS = {"tags", "input_ids", "links", "evidence_ids", "keywords", "urls", "rollup_ids",
              "names", "history", "reasons", "shares", "scopes", "representatives", "trajectory",
              "centroid_2d", "changed", "dropped", "items", "cites", "candidates", "falsifiers",
              "instruments", "results_json", "density"}
JSON_OBJECTS = {"params", "validation", "request", "response", "summary", "quality", "source_mix",
                "topic_mix", "origin_mix", "platform_mix", "kind_counts", "card", "context",
                "detail", "pair", "search", "checks", "instrument", "quote", "position",
                "order_json", "payload", "fields", "because", "source", "grants", "terms",
                "pricing", "scores", "chain", "material", "report", "body", "needs", "thesis"}
NOW = "2026-01-01T00:00:00Z"
wrote: list[str] = []
skipped: list[str] = []


def attempt(what, fn):
    try:
        fn()
        wrote.append(what)
    except Exception as e:  # noqa: BLE001 - a case this version cannot write is listed
        skipped.append(f"{what}: {type(e).__name__}: {str(e)[:120]}")


def main() -> None:
    from kranto import library
    from kranto.embed import StubEmbedder
    from kranto.store import Store

    db = HOME / "data" / "kranto.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store = Store.open(db)
    emb = StubEmbedder()
    tag = TAG.replace(".", "_")
    ids: dict[str, int] = {}

    attempt("topic", lambda: ids.__setitem__(
        "topic", library.add_topic(store, emb, f"Old topic {TAG}", f"what {TAG} watched")))
    sig = inspect.signature(library.add_source).parameters

    def source(name: str, validation) -> None:
        kw = {"label": f"{name} ({TAG})"}
        if "validation" in sig:
            kw["validation"] = validation
        if "status" in sig:
            kw["status"] = "approved"
        sid = library.add_source(store, "rss", {"url": f"https://old.example/{tag}/{name}.xml"},
                                 **kw)
        ids[name] = sid
        if "topic" in ids:
            library.link_topic_source(store, ids["topic"], sid)

    attempt("source tested", lambda: source("tested", {
        "status": "valid", "items": 3, "recent": 1, "median_similarity": 0.42,
        "checked": NOW}))
    attempt("source untested", lambda: source("untested", None))
    conn: sqlite3.Connection = store._conn
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def cols(t: str) -> set[str]:
        return {r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')}

    def insert(t: str, row: dict) -> None:
        have = cols(t)
        store.insert(t, {k: v for k, v in row.items() if k in have})

    attempt("ingest run", lambda: insert("runs", {
        "run_uuid": f"old-{tag}", "kind": "ingest", "status": "ok", "started_at": NOW,
        "finished_at": NOW, "summary": json.dumps({
            "sources": [{"source_id": ids.get("tested"), "label": f"tested ({TAG})",
                         "fetched": 3, "judged": 1, "contributed": 1}],
            "contributed": 1, "cost_usd": 0.0})}))
    if "ideas" in tables:
        attempt("card", lambda: insert("ideas", {
            "snapshot_id": None, "fingerprint": f"old:{tag}", "evidence_key": f"old-{tag}",
            "lineage_id": None, "origin": "cluster", "input_ids": "[]", "title": f"Old card {TAG}",
            "card": json.dumps({"title": f"Old card {TAG}", "thesis": "t", "pattern": "p",
                                "where_now": "w", "evidence": [{"n": 1, "claim": "c"}],
                                "ratings": {"demand_validation": {"value": 0.5}}}),
            "score": 0.5, "status": "shown", "dropped": "[]", "run_uuid": f"old-{tag}",
            "created_at": NOW}))
    if "settings" in tables:
        attempt("watch_paused", lambda: conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('watch_paused', ?)",
            (json.dumps({"until": "2026-01-02T00:00:00Z", "reason": f"paused at {TAG}"}),)))
    every_table(conn, store, tables, tag)
    store.close()


def every_table(conn, store, tables: set[str], tag: str) -> None:
    """A row in each table of this version's schema: nullable columns NULL, a NOT NULL one a
    made-up value (the CHECK's first word when it says, a parent's id for a foreign key)."""
    skip = {"settings", "schema_meta", "schema_migrations", "purge_tokens"}
    virtual = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL%'")}
    n = 0
    for t in sorted(tables - skip):
        if t.startswith("sqlite_") or t in virtual or any(t.startswith(v + "_") for v in virtual):
            continue
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (t,)).fetchone()[0]
        fks = {r[3]: (r[2], r[4]) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')}
        cols = list(conn.execute(f'PRAGMA table_info("{t}")'))
        sole = sum(1 for c in cols if c[5]) == 1
        row, ok = {}, True
        for _, name, kind, notnull, default, pk in cols:
            kind = (kind or "").upper()
            if pk and kind == "INTEGER" and sole and name not in fks:
                continue
            if name in fks:
                parent, key = fks[name]
                got = conn.execute(f'SELECT "{key or "id"}" FROM "{parent}" LIMIT 1').fetchone()
                if got is None and (notnull or pk):
                    ok = False
                    break
                row[name] = got[0] if got else None
            elif not notnull and not pk:
                row[name] = None
            elif default is not None:
                continue
            elif name in JSON_LISTS or name in JSON_OBJECTS:
                row[name] = "[]" if name in JSON_LISTS else "{}"
            else:
                n += 1
                m = re.search(rf"\b{name}\b[^,]*?CHECK\s*\(\s*{name}\s+IN\s*\(\s*'([^']*)'",
                              sql or "")
                row[name] = (m.group(1) if m else n if kind in ("INTEGER", "REAL")
                             else f"old-{tag}-{name}-{n}")
        if not ok:
            skipped.append(f"{t}: no parent row")
            continue
        try:
            if row:
                store.insert(t, row)
            else:
                conn.execute(f'INSERT INTO "{t}" DEFAULT VALUES')
            wrote.append(f"table {t}")
        except Exception as e:  # noqa: BLE001 - a trigger's or a UNIQUE's no
            skipped.append(f"{t}: {type(e).__name__}: {str(e)[:100]}")


if __name__ == "__main__":
    main()
    print(json.dumps({"tag": TAG, "wrote": wrote, "skipped": skipped}))
