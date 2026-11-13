"""X's content rules (5.5, 5.6; D5, D6, D8): an account's own threads joined, an
edited post judged once, bookmarks and likes as the person's own mark, deleted posts leaving
the library (the weekly re-check and Remove this post), and no post text in a bundle.
Against ``tests/fake_x.py``; nothing reaches X."""

import json
from datetime import timedelta

import pytest

from kranto import library, xrecheck
from kranto.config import XConfig
from kranto.intern import render_item
from kranto.sources import Item
from kranto.web.app import create_app

from .conftest import web_client
from .fake_x import USER_ID, fixture, post
from .test_x_sources import add, ingest, make_rig, mock_http, x_reads


@pytest.fixture
def rig(tmp_path, embedder, machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http)
    yield rt, fake
    rt.close()


@pytest.fixture
def machine_id(tmp_path):
    import secrets
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


def judge_requests(rt):
    return [json.loads(r["request"]) for r in rt.store.query(
        "SELECT request FROM llm_calls WHERE purpose = 'judge' ORDER BY id")]


def test_an_accounts_own_thread_is_one_item_in_order(rig):
    rt, fake = rig
    root = 1849000000000000005
    fake.timeline = [post(root, "Why local-first matters, a thread",
                          public_metrics={"reply_count": 2, "like_count": 9})]
    fake.thread = [post(root + 2, "Second: ownership", conversation_id=str(root)),
                   post(root + 1, "First: latency", conversation_id=str(root))]
    add(rt, "x.profile", {"handle": "local_first"})
    start = len(fake.requests)
    report = ingest(rt)
    assert report.contributed == 1
    search = next(r for r in x_reads(fake, start) if r.url.path == "/2/tweets/search/recent")
    assert search.url.params["query"] == f"conversation_id:{root} from:783214 -is:retweet"
    assert search.url.params["max_results"] == "10"
    [obs] = rt.store.query("SELECT item_id, source_excerpt FROM observations")
    assert obs["item_id"] == str(root)
    body = judge_requests(rt)[0]["messages"][1]["content"]
    text = json.loads(body)["item"]["body"]
    assert text.startswith("1/ Why local-first matters") and text.index("2/ First") < \
        text.index("3/ Second")
    # the replies are known, so they are never read as items of their own
    stats = json.loads(body)["item"]["stats"]["x"]
    assert "seen_ids" not in stats and stats["thread"] == 3


def test_threads_off_reads_the_root_only(tmp_path, embedder, machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http,
                        xcfg=XConfig(read_threads=False))
    try:
        fake.timeline = [post(1849000000000000005, "a thread", public_metrics={"reply_count": 3})]
        add(rt, "x.profile", {"handle": "local_first"})
        start = len(fake.requests)
        ingest(rt)
        assert [r.url.path for r in x_reads(fake, start)] == ["/2/users/783214/tweets"]
    finally:
        rt.close()


def test_an_edited_post_is_judged_once(rig):
    rt, fake = rig
    add(rt, "x.home")
    ingest(rt)
    first = rt.store.query_one("SELECT COUNT(*) n FROM llm_calls WHERE purpose = 'judge'")["n"]
    old = fake.timeline[0]["id"]
    edited = post(int(old) + 10, "A CRDT engine for SQLite ships offline sync (edited)",
                  edit_history_post_ids=[old, str(int(old) + 10)])
    fake.timeline.insert(0, edited)
    report = ingest(rt)
    assert report.sources[0].fetched == 1 and report.sources[0].new == 0
    assert rt.store.query_one("SELECT COUNT(*) n FROM llm_calls WHERE purpose = 'judge'")["n"] \
        == first


def test_bookmarks_skip_the_prefilter_and_the_judge_is_told(rig):
    rt, fake = rig
    topic = library.add_topic(rt.store, rt.embedder, "Solar",
                              "Solar mini-grids in sub-Saharan Africa")
    src = add(rt, "x.bookmarks")
    library.link_topic_source(rt.store, topic, src)
    fake.timeline = [post(1849000000000000009, "A recipe for sourdough bread")]
    report = ingest(rt)
    assert report.sources[0].prefiltered == 0 and report.sources[0].judged == 1
    row = rt.store.query_one("SELECT admitted_by FROM observations")
    assert row["admitted_by"] == "marked"
    item = json.loads(judge_requests(rt)[0]["messages"][1]["content"])["item"]
    assert item["marked"] == "the person running this bookmarked this post on X"
    assert "mine" not in item["stats"]["x"]


def test_the_judge_reads_no_bookkeeping_ids():
    it = Item(id="1", title="t", body="b", meta={"x": {"likes": 3, "seen_ids": ["0"]}})
    payload = json.loads(render_item(it, "X list", []))["item"]
    assert payload["stats"] == {"x": {"likes": 3}} and "marked" not in payload


# -- deleted posts ----------------------------------------------------------------------------


def test_what_a_lookup_says_is_gone():
    assert xrecheck.gone(fixture("lookup_errors.json")) == {"1849100000000000009"}
    assert xrecheck.gone({"data": [{"id": "5", "withheld": {"copyright": True}}]}) == {"5"}
    assert xrecheck.gone({"errors": [{"title": "Authorization Error",
                                      "resource_id": "6"}]}) == set()


def test_the_weekly_recheck_removes_deleted_posts_with_a_purge_record(rig):
    rt, fake = rig
    add(rt, "x.home")
    ingest(rt)
    kept = {r["item_id"]: r["id"] for r in rt.store.query("SELECT id, item_id FROM observations")}
    assert len(kept) == 3
    gone_id = fake.timeline[1]["id"]
    fake.lookup_missing = {gone_id}
    before = len(fake.requests)
    result = xrecheck.run_recheck(rt.cfg, rt.store, rt.connections, rt.http)
    assert result == {"status": "ok", "error": None, "checked": 3, "removed": 1}
    [lookup] = x_reads(fake, before)
    assert lookup.url.path == "/2/tweets" and sorted(lookup.url.params["ids"].split(",")) == \
        sorted(kept)
    left = {r["item_id"] for r in rt.store.query("SELECT item_id FROM observations")}
    assert left == set(kept) - {gone_id}
    purge = rt.store.query_one("SELECT reason, rollup_ids FROM purges WHERE table_name = "
                               "'observations'")
    assert purge["reason"] == xrecheck.REMOVED_ON_X and purge["rollup_ids"] == "[]"
    assert rt.store.query_one("SELECT COUNT(*) n FROM rollups")["n"] == 0
    # never read again: its items_seen row stays
    assert rt.store.query_one("SELECT COUNT(*) n FROM items_seen WHERE item_id = ?",
                              (gone_id,))["n"] == 1
    # the two posts X returned were reads, in the run's name
    run = rt.store.query_one("SELECT run_uuid, status FROM runs WHERE kind = 'xrecheck'")
    assert run["status"] == "ok"
    assert rt.store.query_one("SELECT SUM(count) n FROM api_spend WHERE run_uuid = ?",
                              (run["run_uuid"],))["n"] == 2


def test_the_recheck_stops_at_its_limit_cited_first(rig):
    rt, fake = rig
    fake.timeline = [post(1849000000000000000 + i, f"post {i}") for i in range(12, 0, -1)]
    add(rt, "x.home")
    ingest(rt)
    ids = [r["id"] for r in rt.store.query("SELECT id FROM observations ORDER BY id")]
    rt.store.insert("ideas", {"snapshot_id": None, "fingerprint": "f", "lineage_id": None,
                              "origin": "card", "evidence_key": "k",
                              "input_ids": json.dumps([ids[0]]), "title": "t", "card": "{}",
                              "score": 0.5, "status": "shown", "dropped": "[]",
                              "gen_call_id": None, "verify_call_id": None, "run_uuid": None,
                              "created_at": "2026-10-17T00:00:00Z"})
    picks = xrecheck.candidates(rt.store, 5)
    assert len(picks) == 5 and picks[0][0] == ids[0]
    assert [p[0] for p in picks[1:]] == sorted(ids[1:], reverse=True)[:4]


def test_the_recheck_waits_without_posts_or_under_the_cap(rig):
    rt, _ = rig
    # nothing kept: a finished run (due again in a week), no request
    got = xrecheck.run_recheck(rt.cfg, rt.store, rt.connections, rt.http)
    assert got["status"] == "ok" and got["checked"] == 0 and got["note"] == "no kept X posts"
    from kranto.scheduler import Job, is_due
    from kranto.store import utcnow
    assert not is_due(rt.store, Job("xrecheck", 7 * 24, lambda: None), utcnow())


def test_remove_this_post_by_hand_through_the_api_and_the_url(rig):
    rt, fake = rig
    add(rt, "x.home")
    ingest(rt)
    first, second, third = [r["id"] for r in rt.store.query(
        "SELECT id FROM observations ORDER BY id")]
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        r = web.post(f"/api/observations/{first}/remove")
        assert r.status_code == 200 and r.json()["removed"] == 1
        assert web.post(f"/api/observations/{first}/remove").status_code == 404
    item = rt.store.query_one("SELECT item_id FROM observations WHERE id = ?", (second,))[0]
    assert xrecheck.remove_post(rt.store, url=f"https://x.com/someone/status/{item}") == 1
    assert xrecheck.remove_post(rt.store, url="https://x.com/someone/status/1") == 0
    reasons = [r["reason"] for r in rt.store.query(
        "SELECT reason FROM purges WHERE table_name = 'observations'")]
    assert reasons == [xrecheck.REMOVED_BY_YOU] * 2
    assert [r["id"] for r in rt.store.query("SELECT id FROM observations")] == [third]


def test_a_bundle_carries_no_x_post_text(rig, tmp_path):
    from kranto.bundle import export_bundle
    from kranto.map.snapshot import take_snapshot

    rt, fake = rig
    themes = ["solar microgrids rural power", "crdt sync offline database",
              "battery storage chemistry cells"]
    fake.timeline = [post(1849000000000000100 - i, f"{themes[i % 3]} note {i}")
                     for i in range(36)]
    add(rt, "x.home")
    ingest(rt)
    take_snapshot(rt.store, rt.embedder, None)
    export_bundle(rt.store, tmp_path / "bundle")
    rows = json.loads((tmp_path / "bundle" / "observations.json").read_text())
    assert rows and all(r["title"] is None for r in rows)
    assert all(r["source_url"].startswith("https://x.com/i/status/") for r in rows)
    text = (tmp_path / "bundle" / "observations.json").read_text()
    assert "note 1" not in text


def test_x_posts_expire_into_compaction_at_30_days(rig):
    from kranto.retention import _expired

    rt, _ = rig
    add(rt, "x.home")
    ingest(rt)
    from kranto.store import utcnow
    assert _expired(rt.store, rt.cfg.retention, utcnow() + timedelta(days=29)) == []
    assert len(_expired(rt.store, rt.cfg.retention, utcnow() + timedelta(days=31))) == 3


def test_the_owned_endpoints_use_the_accounts_id(rig):
    rt, fake = rig
    add(rt, "x.likes")
    start = len(fake.requests)
    ingest(rt)
    [req] = x_reads(fake, start)
    assert req.url.path == f"/2/users/{USER_ID}/liked_tweets"
    assert req.url.params["max_results"] == "40"
