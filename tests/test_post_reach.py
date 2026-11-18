"""Reach (POSTING-9): the numbers of the posts Kranto sent, read back once a day where the site
gives them to the person's own account, shown on Sent; the sites that give none say so once;
what was learned (``GET /api/post/learned``); LinkedIn's 60-day reminder. Every answer is a
documented shape (``tests/fixtures/social/reach.json``); nothing touches the network."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from kranto.core import tickets
from kranto.core.cubs.brokers.base import new_draft
from kranto.core.cubs.brokers.social import FILER
from kranto.social import reach
from kranto.sources.base import HTTP
from kranto.store import iso
from kranto.web import post_api

FX = json.loads((Path(__file__).parent / "fixtures" / "social" / "reach.json").read_text())
URI = FX["bluesky_posts"]["posts"][0]["uri"]
SENT_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
NEXT_DAY = SENT_AT + timedelta(days=1)


def _done(store, site, kind, ids, *, at=SENT_AT, card=False, parts=1, text="Words."):
    content = {"site": site, "parts": [{"text": text}] * parts, "text": text}
    if card:
        content["card"] = {"url": "https://ex.com/a", "title": "A"}
    d = new_draft(store, cub=FILER, service=site, run_uuid=None, content=content)
    fields = {"draft_ref": d["ref"], "text": text}
    if kind == "post.bluesky":
        fields.update(parts=parts, language="en")
    if kind == "post.open":
        fields["site"] = site
    tid = tickets.file(store, cub=FILER, trust="core", granted=(kind,), kind=kind,
                       fields=fields, capped=False, now=at)
    tickets.append_state(store, tid, "done", door="ui", note="posted: https://ex.com/p", now=at)
    if ids is not None:
        reach.sent(store, tid, site, ids, content, parts=parts, now=at)
    return d, tid


def _http(handler):
    return HTTP(transport=httpx.MockTransport(handler), resolver=lambda h: ["93.184.216.34"])


def test_the_send_keeps_the_sites_ids_and_the_posts_shape(store):
    _, tid = _done(store, "bluesky", "post.bluesky", {"uri": URI}, card=True, parts=2)
    p, = reach.posts(store)
    assert p["ticket_id"] == tid and p["shape"]["ids"] == {"uri": URI}
    assert p["shape"]["parts"] == 2 and p["shape"]["card"] is True
    assert p["shape"]["weekday"] and isinstance(p["shape"]["hour"], int) and p["last"] is None


def test_a_bluesky_post_is_read_from_the_public_appview_with_its_did_address(store, tmp_path):
    _, tid = _done(store, "bluesky", "post.bluesky", {"uri": URI})
    asked = []

    def handler(req: httpx.Request):
        asked.append(req)
        return httpx.Response(200, json=FX["bluesky_posts"])
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), http=_http(handler))
    out = reach.run(rt, now=NEXT_DAY)
    assert out["read"] == 1
    req, = asked
    assert req.url.host == "public.api.bsky.app" and req.method == "GET"
    assert req.url.params.get_list("uris") == [URI]
    assert "authorization" not in {k.lower() for k in req.headers}
    n = reach.newest(store, tid)
    assert (n["replies"], n["reposts"], n["likes"], n["quotes"], n["views"]) == (4, 9, 31, 1,
                                                                                None)
    assert n["words"] == "4 replies, 9 reposts, 31 likes, 1 quote"
    assert reach.run(rt, now=NEXT_DAY + timedelta(hours=2))["read"] == 0   # once a day


def test_a_bluesky_count_left_out_is_zero():
    """The AppView leaves a count of zero out of a post it answers for."""
    post = {k: v for k, v in FX["bluesky_posts"]["posts"][0].items()
            if k not in ("quoteCount", "replyCount")}

    def handler(req):
        return httpx.Response(200, json={"posts": [post]})
    got = reach.read_bluesky(_http(handler), [URI])[URI]
    assert got["quotes"] == 0 and got["replies"] == 0 and got["likes"] == 31
    assert reach.words(got) == "0 replies, 9 reposts, 31 likes, 0 quotes"


def test_mastodon_and_threads_readers_take_the_documented_shapes():
    def mast(method, url, **kw):
        assert method == "GET" and url == "https://mastodon.example/api/v1/statuses/1"
        return httpx.Response(200, json=FX["mastodon_status"])
    assert reach.read_mastodon(mast, "mastodon.example", "1") == {
        "replies": 5, "reposts": 6, "likes": 11, "quotes": 2, "views": None}
    old = reach.read_mastodon(lambda *a, **k: httpx.Response(
        200, json=FX["mastodon_status_before_4_5"]), "m.example", "1")
    assert old["quotes"] is None and old["likes"] == 3

    def th(method, url, params=None, **kw):
        assert url == "https://graph.threads.net/v1.0/1234567/insights"
        assert params == {"metric": "views,likes,replies,reposts,quotes"}
        return httpx.Response(200, json=FX["threads_insights"])
    assert reach.read_threads(th, "1234567") == {"views": 820, "likes": 100, "replies": 10,
                                                 "reposts": 3, "quotes": 0}
    said = reach.read_threads(lambda *a, **k: httpx.Response(
        403, json=FX["threads_no_permission"]), "1")
    assert isinstance(said, str) and "threads_manage_insights" in said


def test_daily_for_two_weeks_then_weekly_then_never(store):
    _, tid = _done(store, "bluesky", "post.bluesky", {"uri": URI})
    assert reach.due(store, SENT_AT + timedelta(minutes=30)) == []        # too fresh
    assert len(reach.due(store, NEXT_DAY)) == 1
    store.insert("post_reach", {"ticket_id": tid, "site": "bluesky",
                                "read_at": iso(SENT_AT + timedelta(days=20)), "likes": 1,
                                "shape": "{}", "created_at": iso(SENT_AT + timedelta(days=20))})
    assert reach.due(store, SENT_AT + timedelta(days=22)) == []          # weekly now
    assert len(reach.due(store, SENT_AT + timedelta(days=27))) == 1
    assert reach.due(store, SENT_AT + timedelta(days=61)) == []          # past 60 days


def test_sites_that_give_no_numbers_are_never_read_and_say_so_once(store, tmp_path):
    _done(store, "linkedin", "post.linkedin", {"urn": "urn:li:share:1"})
    _done(store, "x", "post.open", None)
    assert reach.due(store, NEXT_DAY) == []
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), cubs=None)
    page = post_api.post_read(rt)
    assert len(page["sent"]) == 2 and all(r["reach"] is None for r in page["sent"])
    assert page["reach_foot"] == ("No numbers from LinkedIn and X: LinkedIn gives its numbers "
                                  "only to approved partners; X charges for each read.")


def test_sent_shows_the_numbers(store, tmp_path):
    _, tid = _done(store, "bluesky", "post.bluesky", {"uri": URI})
    store.insert("post_reach", {"ticket_id": tid, "site": "bluesky", "read_at": iso(NEXT_DAY),
                                "replies": 4, "reposts": 9, "likes": 31, "shape": "{}",
                                "created_at": iso(NEXT_DAY)})
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), cubs=None)
    row, = post_api.post_read(rt)["sent"]
    assert row["reach"]["words"] == "4 replies, 9 reposts, 31 likes"
    assert post_api.post_read(rt)["reach_foot"] is None


def test_the_preview_reads_nothing(store, tmp_path, monkeypatch):
    _done(store, "bluesky", "post.bluesky", {"uri": URI})
    monkeypatch.setenv("KRANTO_PREVIEW", "1")

    def handler(req):
        raise AssertionError("the preview asked a site")
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), http=_http(handler))
    assert reach.run(rt, now=NEXT_DAY)["read"] == 0


def test_a_site_that_does_not_answer_is_read_tomorrow_not_retried(store, tmp_path):
    _done(store, "bluesky", "post.bluesky", {"uri": URI})
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(502)
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), http=_http(handler))
    assert reach.run(rt, now=NEXT_DAY)["read"] == 0
    assert len(reach.due(store, NEXT_DAY + timedelta(minutes=1))) == 1


def test_a_run_is_recorded_so_the_job_is_due_once_a_day_not_every_minute(store, tmp_path):
    """Each run writes its ``runs`` row: without it the scheduler found the job due at every
    tick (once a minute), whether or not there was anything to read."""
    from kranto.scheduler import Job, is_due
    from kranto.store import utcnow

    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path),
                         http=_http(lambda req: httpx.Response(502)))
    job = Job(reach.KIND, 24, lambda: reach.run(rt))
    now = utcnow()
    assert is_due(store, job, now)
    job.run()
    row = store.query_one("SELECT status FROM runs WHERE kind = ?", (reach.KIND,))
    assert row["status"] == "ok"
    assert not is_due(store, job, now + timedelta(minutes=1))
    assert not is_due(store, job, now + timedelta(hours=23))
    assert is_due(store, job, now + timedelta(hours=25))


def test_learned_says_nothing_under_eight_a_side(store):
    for i in range(5):
        _, tid = _done(store, "bluesky", "post.bluesky", {"uri": f"{URI}{i}"}, parts=1 + i % 2)
        store.insert("post_reach", {"ticket_id": tid, "site": "bluesky", "read_at": iso(NEXT_DAY),
                                    "likes": i, "shape": "{}", "created_at": iso(NEXT_DAY)})
    sky = next(s for s in reach.learned(store)["sites"] if s["site"] == "bluesky")
    assert sky["posts"] == 5 and sky["lines"] == [] and sky["needs"] == 11


def test_learned_compares_threads_and_single_posts_with_eight_each(store):
    for i in range(16):
        thread = i % 2 == 1
        _, tid = _done(store, "bluesky", "post.bluesky", {"uri": f"{URI}{i}"},
                       parts=2 if thread else 1)
        store.insert("post_reach", {"ticket_id": tid, "site": "bluesky", "read_at": iso(NEXT_DAY),
                                    "replies": 2 if thread else 1, "likes": 8 if thread else 4,
                                    "shape": "{}", "created_at": iso(NEXT_DAY)})
    sky = next(s for s in reach.learned(store)["sites"] if s["site"] == "bluesky")
    line = next(x for x in sky["lines"] if x["key"] == "thread")
    assert line["words"] == "Threads drew 2.0 times what single posts did (16 posts)"


def test_linkedins_token_is_reminded_a_week_before_once(store):
    cid = store.insert("connections", {"provider": "linkedin_post", "instance": "api.linkedin.com",
                                       "account": "Alex Example", "scopes": "[]",
                                       "created_at": iso(SENT_AT)})
    store.insert("connection_events", {"connection_id": cid, "event": "connected",
                                       "created_at": iso(SENT_AT)})
    assert reach.remind(store, SENT_AT + timedelta(days=50)) == []
    got = reach.remind(store, SENT_AT + timedelta(days=54))
    assert got == ["LinkedIn needs a new token by 12 January (5 minutes)"]
    assert reach.remind(store, SENT_AT + timedelta(days=55)) == []       # once
    m = store.query_one("SELECT kind, origin, links FROM messages")
    assert m["kind"] == "alarm" and m["origin"] == reach.KIND and "settings/posting" in m["links"]
    assert reach.remind(store, SENT_AT + timedelta(days=61)) == [
        "LinkedIn's token has run out: make a new one (5 minutes)"]


@pytest.mark.parametrize("raw", [None, "", "not json", "[]", '{"ids": null}'])
def test_a_shape_stored_otherwise_reads_as_none(store, raw):
    """A reader of ``post_reach.shape`` never assumes its shape: null, empty, not JSON, a
    list, or a key stored as null all read as an object."""
    store.insert("post_reach", {"ticket_id": 1, "site": "bluesky", "read_at": iso(SENT_AT),
                                "shape": raw if raw is not None else "{}", "note": reach.SENT,
                                "created_at": iso(SENT_AT)})
    p, = reach.posts(store)
    assert isinstance(p["shape"], dict)
    assert reach.due(store, NEXT_DAY) == [p] or reach.due(store, NEXT_DAY) == []
