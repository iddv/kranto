"""The rename: migration 31 copies the ``mod_*`` rows (and
``money_orders``) into the ``cub_*`` tables with their ids, the old tables stay as they were,
no code names them any more, ``/api/requests`` answers as ``/api/tickets`` does through 0.5.x,
and ``ideas.list`` gains the weekly editor's verdict."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from kranto.core import api, events, registry
from kranto.store import _MIGRATIONS, Store

from .conftest import web_client
from .test_ideas_api import add_card, cards, obs_ids, old_card  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture

SRC = Path(__file__).resolve().parents[1] / "src" / "kranto"
OLD = re.compile(r"\b(mod_pins|mod_requests|mod_request_states|mod_calls|money_orders)\b")
T = "2026-10-18T22:00:00Z"


def _database_at_30(path: Path) -> None:
    """A database as 0.4.6 to 0.4.8 left it: every migration up to 30, recorded."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT "
                 "NOT NULL)")
    for n, script in sorted(_MIGRATIONS):
        if n > 30:
            continue
        conn.executescript(f"BEGIN IMMEDIATE;\n{script}\nINSERT INTO schema_meta (key, value) "
                           f"VALUES ('migration:{n}', '{T}');\nCOMMIT;")
    conn.execute("INSERT INTO mod_pins (id, feature, version, trust, manifest_hash, created_at) "
                 "VALUES (3, 'news', '1.0.0', 'first-party', 'h1', ?), "
                 "(8, 'invest', '1.0.0', 'first-party', 'h2', ?)", (T, T))
    conn.execute("INSERT INTO mod_requests (id, feature, kind, trust, subject_kind, subject_id, "
                 "fields, fields_hash, because, expires_at, created_at) VALUES "
                 "(5, 'invest', 'trade.instruct', 'first-party', 'invest_proposal', '2', '{}', "
                 "'fh', '{\"briefs\": [1]}', ?, ?), "
                 "(9, 'invest', 'trade.instruct', 'first-party', NULL, NULL, '{}', 'fh2', '{}', "
                 "?, ?)", (T, T, T, T))
    conn.execute("INSERT INTO mod_request_states (id, request_id, state, door, note, created_at) "
                 "VALUES (11, 5, 'needs_confirm', NULL, NULL, ?), (12, 5, 'confirmed', 'ui', "
                 "NULL, ?), (13, 5, 'done', 'ui', 'paper order placed', ?), "
                 "(14, 9, 'needs_confirm', NULL, NULL, ?)", (T, T, T, T))
    conn.execute("INSERT INTO mod_calls (id, feature, service, op, status, request_id, ms, "
                 "detail, created_at) VALUES (21, 'invest', 'ibkr', 'quote', 'ok', 5, 40, NULL, "
                 "?)", (T,))
    conn.execute("INSERT INTO money_orders (id, request_id, client_ref, state, mode, account, "
                 "notional_usd, order_json, broker_ref, detail, created_at) VALUES (31, 5, "
                 "'kranto-5', 'placed', 'paper', 'DU1', 955.7, '{}', 'B1', 'submitted', ?)", (T,))
    conn.close()


def test_migration_31_copies_every_row_with_its_id(tmp_path):
    path = tmp_path / "kranto.db"
    _database_at_30(path)
    store = Store.open(path)
    assert 31 in store.applied_migrations()
    pins = [dict(r) for r in store.query("SELECT id, cub, version, tree_hash FROM cub_pins")]
    assert pins == [{"id": 3, "cub": "news", "version": "1.0.0", "tree_hash": None},
                    {"id": 8, "cub": "invest", "version": "1.0.0", "tree_hash": None}]
    t = [dict(r) for r in store.query("SELECT id, cub, kind, subject_id, because, run_uuid "
                                      "FROM cub_tickets ORDER BY id")]
    assert [x["id"] for x in t] == [5, 9] and t[0]["cub"] == "invest"
    assert json.loads(t[0]["because"]) == {"briefs": [1]} and t[0]["run_uuid"] is None
    states = store.query("SELECT id, ticket_id, state, note FROM cub_ticket_states ORDER BY id")
    assert [(r["id"], r["ticket_id"], r["state"]) for r in states] == \
        [(11, 5, "needs_confirm"), (12, 5, "confirmed"), (13, 5, "done"), (14, 9, "needs_confirm")]
    call = store.query_one("SELECT * FROM cub_calls")
    assert (call["id"], call["cub"], call["ticket_id"], call["bytes_in"]) == (21, "invest", 5, None)
    order = store.query_one("SELECT * FROM cub_orders")
    assert (order["id"], order["ticket_id"], order["notional_usd"]) == (31, 5, 955.7)
    # the old tables are as they were, and still append-only
    assert store.query_one("SELECT COUNT(*) AS n FROM mod_requests")["n"] == 2
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("UPDATE mod_requests SET kind = 'x'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store._conn.execute("DELETE FROM cub_tickets")
    # a copied ticket reads the same under the new names; new ids follow the copied ones
    from kranto.core import tickets
    got = tickets.get(store, 5)
    assert got["state"] == "done" and got["note"] == "paper order placed"
    assert got["cub"] == got["feature"] == "invest"
    assert store.insert("cub_tickets", {"cub": "x", "kind": "k", "trust": "owner",
                                        "fields": "{}", "fields_hash": "h", "expires_at": T,
                                        "created_at": T}) == 10
    store.close()


def test_cub_kv_is_the_one_mutable_table(store):
    store.insert("cub_kv", {"cub": "c", "key": "k", "value": "1", "bytes": 1, "updated_at": T})
    store._conn.execute("UPDATE cub_kv SET value = '2' WHERE cub = 'c'")
    store._conn.execute("DELETE FROM cub_kv WHERE cub = 'c'")
    for table in ("cubs", "cub_installs", "cub_drafts", "cub_dedupe", "cub_calls"):
        assert table in store.append_only_tables()


def _source_without_old_migrations(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.name == "store.py" and "_MIGRATIONS: list" in text:   # the migrations keep the names
        start = text.index("_MIGRATIONS: list")
        end = text.index("def _derived_tables")
        text = text[:start] + text[end:]
    return text


def test_no_code_names_the_old_tables():
    found = []
    for py in SRC.rglob("*.py"):
        for n, line in enumerate(_source_without_old_migrations(py).splitlines(), 1):
            if OLD.search(line):
                found.append(f"{py.relative_to(SRC)}:{n}: {line.strip()[:80]}")
    assert found == []


def test_the_core_events_are_renamed():
    assert "ticket.filed" in events.CORE_KINDS and "ticket.resolved" in events.CORE_KINDS
    assert "request.made" not in events.CORE_KINDS
    from kranto.core.manifest import API
    assert API == "cub/1" and registry.m_api() == "cub/1"


def test_afk_features_says_the_protocol(capsys):
    from kranto import cli
    assert cli.main(["features"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "api: cub/1" and "news " in out and "invest" not in out


def test_requests_and_tickets_answer_the_same(rt):  # noqa: F811
    from kranto.core import tickets
    from kranto.web.app import create_app

    from .test_cub_surfaces import _draft
    _draft(rt.store, "toot", "draft:4")
    tid = tickets.file(rt.store, cub="toot", trust="owner", granted=("post.mastodon",),
                       kind="post.mastodon", fields={"draft_ref": "draft:4", "text": "hi",
                                                     "visibility": "public", "language": "en"})
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        new = web.get("/api/tickets?open=1").json()["tickets"]
        old = web.get("/api/requests?open=1").json()["requests"]
        assert new == old and new[0]["id"] == tid and new[0]["feature"] == "toot"
        assert web.get("/api/tickets?cub=toot").json() == {"tickets": new}
        assert web.get(f"/api/tickets/{tid}").json() == web.get(f"/api/requests/{tid}").json()
        r = web.post(f"/api/requests/{tid}/decline", json={"note": "no"})
        assert r.status_code == 200 and r.json()["state"] == "declined"
        assert web.get("/api/features").json()["api"] == "cub/1"


def test_ideas_list_carries_the_editors_verdict_and_filters_by_it(rt, cards):  # noqa: F811
    # rows the weekly editor wrote before the cut (CUT: no new editor row is taken)
    from .test_outcomes import old_row
    old_row(rt.store, cards["new"], {"kind": "editor", "value": "nominee",
                                     "detail": {"week": "2026-W42", "why": "strong"}})
    old_row(rt.store, cards["old"], {"kind": "editor", "value": "candidate",
                                     "detail": {"week": "2026-W42"}})

    class Ctx:
        feature = None
        store = rt.store

    out = api.ideas_list(Ctx(), {})["ideas"]
    by = {i["id"]: i for i in out}
    assert by[cards["new"]]["editor"]["class"] == "nominee"
    assert by[cards["new"]]["editor"]["week"] == "2026-W42"
    assert by[cards["new"]]["editor"]["why"] == "strong"
    nominees = api.ideas_list(Ctx(), {"editor_class": "nominee"})["ideas"]
    assert [i["id"] for i in nominees] == [cards["new"]]
    with pytest.raises(api.ReadError, match="editor_class is one of"):
        api.ideas_list(Ctx(), {"editor_class": "favourite"})
