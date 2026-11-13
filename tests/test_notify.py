import json
import sqlite3
from datetime import UTC, datetime
from xml.etree import ElementTree

import httpx
import pytest

from kranto import notify
from kranto import store as store_mod
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.store import Store
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client


def test_legacy_version_databases_upgrade_in_place(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for number, script in store_mod._MIGRATIONS:
        if number <= 5:
            conn.executescript(script)
    conn.execute("INSERT INTO schema_meta VALUES ('version', '5')")
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES ('paused', 'kept', 'x')")
    conn.commit()
    conn.close()

    s = Store.open(path)
    assert s.applied_migrations() >= {1, 2, 3, 4, 5, 6}
    assert s.pause_reason() == "kept"
    assert s.query_one("SELECT value FROM schema_meta WHERE key = 'version'") is None
    s.close()
    Store.open(path).close()  # idempotent on reopen


def test_numbered_migrations_apply_in_any_merge_order(tmp_path, monkeypatch):
    base = list(store_mod._MIGRATIONS)
    eight = (98, "CREATE TABLE later_feature (id INTEGER PRIMARY KEY);")
    seven = (97, "CREATE TABLE earlier_feature (id INTEGER PRIMARY KEY);")
    path = tmp_path / "db.db"
    monkeypatch.setattr(store_mod, "_MIGRATIONS", base + [eight])
    Store.open(path).close()  # branch with 98 merged first
    monkeypatch.setattr(store_mod, "_MIGRATIONS", base + [eight, seven])
    s = Store.open(path)  # then 97 arrives
    assert {97, 98} <= s.applied_migrations()
    assert "earlier_feature" in s.append_only_tables()
    s.close()


def test_duplicate_migration_numbers_are_refused(monkeypatch):
    monkeypatch.setattr(store_mod, "_MIGRATIONS",
                        list(store_mod._MIGRATIONS) + [(1, "SELECT 1;")])
    with pytest.raises(RuntimeError, match="duplicate"):
        Store.memory()


def test_emit_is_idempotent_and_append_only(store):
    first = notify.emit(store, "alarm", "t", "b", dedup_key="k", origin="test")
    assert first is not None
    assert notify.emit(store, "alarm", "t", "b", dedup_key="k", origin="test") is None
    with pytest.raises(ValueError):
        notify.emit(store, "shout", "t", "b", dedup_key="k2", origin="test")
    with pytest.raises(sqlite3.IntegrityError):
        store.query("DELETE FROM messages")


def test_candidates_are_recorded(store):
    cid = notify.record_candidate(store, origin="burst", subject_key="lineage:abc", score=0.8,
                                  title="t", body="b", evidence_ids=[1, 2], detail={"q": 0.01})
    row = store.query_one("SELECT * FROM strike_candidates WHERE id = ?", (cid,))
    assert row["subject_key"] == "lineage:abc" and json.loads(row["evidence_ids"]) == [1, 2]


def test_failed_ingest_run_raises_exactly_one_alarm(tmp_path, store, embedder, make_client):
    from kranto import library, sources
    from kranto.tick import run_ingest

    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=5),
                 ingest=IngestConfig(), map=MapConfig())
    library.add_source(store, "rss", {"url": "https://ex.com/f"}, label="f")
    http = sources.HTTP(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, content=b"<rss><channel><title>f</title><item><title>x</title><guid>1</guid>"
                     b"</item></channel></rss>")), resolver=lambda h: ["93.184.216.34"])
    client = make_client(lambda body: httpx.Response(401, json={"error": {"message": "dead"}}))
    report = run_ingest(cfg, store, client, embedder, http)
    assert report.status == "failed"
    [alarm] = notify.recent_messages(store, kind="alarm")
    # a refused key is said once for the key, in its own words
    assert alarm["dedup_key"].startswith("auth:") and alarm["dedup_key"].endswith(report.run_uuid)
    assert "401" in alarm["body"] and "key is refused" in alarm["title"]
    notify.alarm_for_run(store, kind="ingest", run_uuid=report.run_uuid, status="failed",
                         error=alarm["body"].split(": ", 1)[1].split(". Every")[0])
    assert len(notify.recent_messages(store, kind="alarm")) == 1
    ok = run_ingest(cfg, store, make_client(lambda b: chat_response('{"skip": true}')),
                    embedder, http)
    assert ok.status != "failed"
    assert len(notify.recent_messages(store, kind="alarm")) == 1


def test_budget_alarms_once_per_month_each(store, make_client):
    client = make_client(lambda body: chat_response("x", cost=0.45), budget=1.0)
    msg = [{"role": "user", "content": "hi"}]
    client.complete(tier="judge", purpose="p", messages=msg, prompt_version="v")
    assert notify.recent_messages(store) == []
    client.complete(tier="judge", purpose="p", messages=msg, prompt_version="v")  # 0.90
    client.complete(tier="judge", purpose="p", messages=msg, prompt_version="v")  # 1.35
    with pytest.raises(Exception, match="budget"):
        client.complete(tier="judge", purpose="p", messages=msg, prompt_version="v")
    with pytest.raises(Exception, match="budget"):
        client.complete(tier="judge", purpose="p", messages=msg, prompt_version="v")
    keys = sorted(m["dedup_key"] for m in notify.recent_messages(store))
    assert keys == ["budget-alarm:2026-09", "budget-exhausted:2026-09"]
    next_month = datetime(2026, 10, 2, tzinfo=UTC)
    notify.budget_alarm(store, spent=0.9, budget=1.0, alarm_fraction=0.8, now=next_month)
    assert len(notify.recent_messages(store)) == 3


def test_atom_feed_is_valid_and_escaped(tmp_path, store, embedder, make_client):
    notify.emit(store, "alarm", "<script>x</script> & friends", "body with <b>tags</b>",
                dedup_key="a", origin="test", evidence_ids=[5],
                links=["https://ex.com/?a=1&b=2", "javascript:alert(1)"])
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=5),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder,
                      llm=make_client(lambda b: chat_response("{}")))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        r = web.get("/feed.xml")
        assert r.headers["content-type"].startswith("application/atom+xml")
        root = ElementTree.fromstring(r.content)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        [entry] = root.findall("a:entry", ns)
        assert entry.find("a:title", ns).text == "[alarm] <script>x</script> & friends"
        hrefs = [link.get("href") for link in entry.findall("a:link", ns)]
        assert "https://ex.com/?a=1&b=2" in hrefs
        assert "http://127.0.0.1:8765/obs/5" in hrefs
        assert not any(h.startswith("javascript") for h in hrefs)
        [message] = web.get("/api/health").json()["messages"]
        assert message["title"] == "<script>x</script> & friends"   # escaped by the page
