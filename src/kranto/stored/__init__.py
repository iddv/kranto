"""The contracts for what Kranto stores as JSON: one frozen dataclass per column, ``settings`` key
and file, in this
package (a feature's own in ``features/<id>/stored.py``), and the registry that keeps them whole.

``COLUMNS``, ``SETTINGS`` and ``FILES`` fill as each type is defined (``base.Stored``);
importing this package imports every family, so they are complete. ``json_columns()`` lists the
JSON columns the migrations declare, from the schema itself (migration 30's frozen tables left out);
``tests/test_stored.py`` fails when
one has no contract and is not ``OPAQUE``.
"""

from __future__ import annotations

import sqlite3

from . import (
    activity,
    cards,
    cubs,
    events,
    map,
    misc,
    observations,
    prepared,
    release,
    runs,
    settings,
    sources,
)
from .base import COLUMNS, FILES, ISO, SETTINGS, Iso, Noter, Problem, Stored, note, problems_seen

__all__ = ["COLUMNS", "FILES", "FROZEN_MIGRATION", "ISO", "JSON_NAMES", "NOT_JSON", "OPAQUE",
           "RETIRED_TABLES",
           "SETTINGS", "Iso", "frozen_tables",
           "Noter", "Problem", "Stored", "contract_for", "json_columns", "note", "problems_seen",
           "activity", "cards", "cubs", "events", "load_all", "map", "misc",
           "observations", "prepared", "release", "runs", "settings", "sources"]

#: JSON columns with no one contract type, and why.
OPAQUE: dict[tuple[str, str], str] = {
    ("cub_kv", "value"): "a cub's own value; Kranto does not know its shape and keeps the text",
    ("settings", "value"): "one value per key, most of them plain text: the keys that hold an "
                           "object are typed in SETTINGS",
}

#: TEXT columns that hold JSON, by name, where the schema gives no ``'[]'``/``'{}'`` default (the
#: inventory of checked against the writers). A plain-text column that shares a
#: name is in NOT_JSON.
JSON_NAMES = frozenset({
    "params", "validation", "request", "response", "summary", "tags", "quality", "density",
    "centroid_2d", "keywords", "source_mix", "topic_mix", "representatives", "trajectory",
    "origin_mix", "input_ids", "card", "dropped", "links", "evidence_ids", "detail", "context",
    "platform_mix", "kind_counts", "urls", "rollup_ids", "scopes", "reasons", "pair", "names",
    "history", "results_json", "items", "search", "checks", "instrument", "candidates", "quote",
    "position", "order_json", "cites", "payload", "fields", "because", "source", "grants",
    "value", "terms", "pricing", "instruments", "benchmark", "scores", "chain", "falsifiers",
    "material", "report", "body", "shares", "changed", "needs", "quiet", "thesis",
})

#: (table, column) pairs whose name is in JSON_NAMES but that hold plain text.
NOT_JSON = frozenset({
    ("messages", "body"), ("strike_candidates", "body"), ("runs", "error"),
    ("rollups", "summary"), ("observations", "summary"), ("evidence_snapshots", "summary"),
    ("observations", "source_url"), ("feedback", "value"), ("outcomes", "value"),
    ("outcomes", "source"), ("schema_meta", "value"), ("archive_themes", "bundle"),
    ("radar_series", "source"), ("run_marks", "words"), ("cub_drafts", "content"),
    ("search_cache", "kind"), ("cubs", "note"), ("syntheses", "text"),
    ("news_briefs", "quiet"), ("radar_trends", "benchmark"),   # a sentence; a ticker
    ("news_articles", "quiet"),                                 # a sentence
    # a broker call's and an order's note: scrubbed text, at most 300 and 500 characters
    ("cub_calls", "detail"), ("cub_orders", "detail"),
})

#: The migration whose tables are frozen: migration 31 copied their rows into the ``cub_*``
#: tables, and nothing writes or reads them since (but that copy, in ``store.py``).
FROZEN_MIGRATION = 30


#: The tables of the features that left Kranto (cut 2;): every row stays,
#: nothing writes them, and nothing reads them but ``kranto archive``, which copies their text as it
#: is. No contract is kept for their columns.
RETIRED_TABLES = ("invest_", "radar_", "browser_", "deep_dive")


def frozen_tables() -> frozenset[str]:
    """The tables :data:`FROZEN_MIGRATION` made: kept for the copy, never read through a
    contract."""
    import re

    from ..store import _MIGRATIONS
    script = dict(_MIGRATIONS)[FROZEN_MIGRATION]
    return frozenset(re.findall(r"CREATE TABLE (\w+)", script))


def json_columns(conn: sqlite3.Connection | None = None) -> list[tuple[str, str]]:
    """Every JSON column of the library's schema, as the migrations leave it: a TEXT column
    defaulted to ``'[]'`` or ``'{}'``, or named in JSON_NAMES and not in NOT_JSON. ``conn``: a
    migrated library (a fresh in-memory one when None). The full-text index's tables are not
    columns anyone writes JSON to and are left out."""
    if conn is None:
        from ..store import Store
        conn = Store.memory()._conn
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND sql NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name")]
    fts = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL%'")}
    frozen = frozen_tables()
    out = []
    for t in tables:
        if any(t.startswith(f + "_") for f in fts) or t in frozen \
                or t.startswith(RETIRED_TABLES):
            continue
        for _, name, kind, _notnull, default, _pk in conn.execute(f'PRAGMA table_info("{t}")'):
            if (kind or "").upper() != "TEXT":
                continue
            d = (default or "").strip()
            if d in ("'[]'", "'{}'") or (name in JSON_NAMES and (t, name) not in NOT_JSON):
                out.append((t, name))
    return out


#: The features whose tables hold JSON: each declares its contracts in ``<feature>/stored.py``
#: (D-3), imported by :func:`load_all` (importing a feature from here would be a cycle).
FEATURES_WITH_STORED = ("news",)


def load_all() -> dict[tuple[str, str], type[Stored]]:
    """Every contract, the features' too: the registry once each ``stored.py`` is imported."""
    import importlib
    for f in FEATURES_WITH_STORED:
        importlib.import_module(f"kranto.features.{f}.stored")
    return COLUMNS


def contract_for(table: str, column: str) -> type[Stored] | None:
    """The contract type of a column, or None (not yet typed, or OPAQUE)."""
    return COLUMNS.get((table, column))
