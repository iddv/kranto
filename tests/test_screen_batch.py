"""Short posts screened together: X, Bluesky and Mastodon posts under 600
characters share one screen call, a ref the reply leaves out passes, the shared call is kept
until the last item that names it is past its age, and look.screen_batch 1 turns it off."""

import json
import secrets
from datetime import timedelta

import pytest

from kranto import prompts
from kranto.config import ConfigError, LookConfig, _parse_look
from kranto.intern import interpret_screen_batch, render_screen_batch, short_post
from kranto.sources import Item
from kranto.store import utcnow

from .conftest import chat_response
from .fake_x import post
from .test_x_sources import add, ingest, judge_reply, make_rig, mock_http


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


def batch_reply(drop: set[int], *, leave_out: set[int] = frozenset()):
    """The model: drops the refs in ``drop``, says nothing about ``leave_out``."""
    def reply(body):
        user = body["messages"][-1]["content"]
        if "SEVERAL short posts" in body["messages"][0]["content"]:
            refs = [p["ref"] for p in json.loads(user)["posts"]]
            return chat_response(json.dumps({"verdicts": [
                {"ref": r, "pass": r not in drop, "reason": "spam" if r in drop else "ok"}
                for r in refs if r not in leave_out]}))
        return judge_reply(body)
    return reply


def calls(rt, purpose):
    return [json.loads(r["request"]) for r in rt.store.query(
        "SELECT request FROM llm_calls WHERE purpose = ? ORDER BY id", (purpose,))]


def test_reading_a_batch_reply_passes_what_it_does_not_say():
    text = json.dumps({"verdicts": [{"ref": 2, "pass": False, "reason": "spam: a giveaway"},
                                    {"ref": 9, "pass": False, "reason": "no such ref"},
                                    {"ref": "x"}]})
    out = interpret_screen_batch(text, 3)
    assert [p for p, _ in out] == [True, False, True]
    assert out[1][1] == "spam: a giveaway" and "not in the screen's reply" in out[0][1]
    assert all(p for p, _ in interpret_screen_batch("not json", 2))


def test_what_counts_as_a_short_post_and_how_the_batch_is_written():
    assert short_post(Item(id="1", title="t", body="x" * 599))
    assert not short_post(Item(id="1", title="t", body="x" * 600))
    assert not short_post(Item(id="1", title="t", body="x", comments=("c",)))
    text = render_screen_batch([Item(id="1", title="a", body="a"), Item(id="2", title="b",
                                                                        body="b")], "X", ["t"])
    assert [p["ref"] for p in json.loads(text)["posts"]] == [1, 2]
    assert prompts.schema("screen_batch")["required"] == ["verdicts"]
    assert "screen_batch" in prompts.BY_ID


def test_screen_batch_is_validated():
    assert LookConfig().screen_batch == 20
    with pytest.raises(ConfigError, match="screen_batch"):
        _parse_look({"screen_batch": 0})


def test_twenty_short_posts_share_one_screen_and_each_keeps_its_verdict(tmp_path, embedder,
                                                                        machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http, look=LookConfig(),
                        reply=batch_reply({2}, leave_out={3}))
    try:
        fake.timeline = [post(1849000000000000100 - i, f"short post number {i}")
                         for i in range(5)]
        add(rt, "x.home")
        report = ingest(rt)
        rep = report.sources[0]
        screens = calls(rt, "screen")
        assert len(screens) == 1 and rep.screened == 5
        assert len(json.loads(screens[0]["messages"][-1]["content"])["posts"]) == 5
        assert rep.screened_out == 1 and rep.judged == 4
        call = rt.store.query_one("SELECT id FROM llm_calls WHERE purpose = 'screen'")["id"]
        shared = rt.store.query_one("SELECT COUNT(*) n FROM items_seen WHERE screen_call_id = ?",
                                    (call,))["n"]
        assert shared == 5
        # the post the reply left out was passed on, as an unreadable reply is
        assert rt.store.query_one("SELECT COUNT(*) n FROM observations")["n"] == 4
    finally:
        rt.close()


def test_batching_off_screens_one_by_one(tmp_path, embedder, machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http,
                        look=LookConfig(screen_batch=1))
    try:
        add(rt, "x.home")
        ingest(rt)
        assert len(calls(rt, "screen")) == 3
    finally:
        rt.close()


def test_the_shared_screen_call_stays_until_its_last_item_is_past_its_age(tmp_path, embedder,
                                                                         machine_id):
    from kranto.retention import CompactReport, _purge_unkept_calls, retention_days

    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http, look=LookConfig(),
                        reply=batch_reply({1, 2, 3}))
    try:
        add(rt, "x.home")
        ingest(rt)
        call = rt.store.query_one("SELECT id FROM llm_calls WHERE purpose = 'screen'")["id"]
        days = retention_days(rt.store, rt.cfg.retention)
        # a later item names the same call (it was screened in the same batch, seen later)
        first_seen = rt.store.query_one("SELECT MIN(created_at) t FROM items_seen")["t"]
        rt.store.insert("items_seen", {"source_id": 1, "item_id": "late", "outcome":
                                       "screened_out", "screen_call_id": call,
                                       "llm_call_id": call, "run_uuid": "r",
                                       "created_at": (utcnow() + timedelta(days=20))
                                       .strftime("%Y-%m-%dT%H:%M:%SZ")})
        assert first_seen
        now = utcnow() + timedelta(days=31)
        report = CompactReport(run_uuid="t")
        _purge_unkept_calls(rt.store, days, now, report, lambda: now)
        assert rt.store.query_one("SELECT 1 FROM llm_calls WHERE id = ?", (call,)) is not None
        later = utcnow() + timedelta(days=52)
        _purge_unkept_calls(rt.store, days, later, report, lambda: later)
        assert rt.store.query_one("SELECT 1 FROM llm_calls WHERE id = ?", (call,)) is None
    finally:
        rt.close()
