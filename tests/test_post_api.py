"""A draft waits until it is seen, and Post's one read.

An install's asks as they stood on 11 November (read from a copy): five drafts, seven asks, six of
them expired unread. #1 the newsletter's first issue under an earlier release's kind; #2
example.com's
post, offered again as #5, which ran out of time too; #3 the issue of 27 Oct, practiced, offered
again as #4, which ran out of time; #6 the issue of 2 Nov; #7 the issue of 9 Nov, open past its
two days with no ``expired`` row yet (the daily sweep writes it). After this change a draft's ask
has no time limit; #7's issue and example.com's post wait again (each still its cub's newest, never
pressed), the older issues stay where they are, and Post lists the two with Copy and Download.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import time_machine

from kranto import newsletter
from kranto.core import asks, events, tickets
from kranto.core.cubs.brokers.base import new_draft
from kranto.web import post_api
from kranto.web import types as T
from kranto.web.app import create_app

from .conftest import web_client
from .test_asks import old_limits
from .test_web import rt  # noqa: F401 - fixture
from .test_web_types import problems

UI = {"origin": "ui", "via": "cookie"}
OCT = lambda d, h=6: datetime(2026, 10, d, h, 0, tzinfo=UTC)  # noqa: E731
N = lambda d, h=8: datetime(2026, 11, d, h, 0, tzinfo=UTC)  # noqa: E731
NOW = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)
S5 = "This week: Amazon team's single policy grasps 66 objects with no teleoperation"
NL = ("send.newsletter",)


def installed(*cubs: tuple[str, tuple[str, ...]], state: str = "installed") -> dict:
    """The cubs' runtime's ``installed`` map, as ``wait_again`` reads it."""
    return {c: SimpleNamespace(state=state, grants=SimpleNamespace(requests=kinds))
            for c, kinds in cubs}


LIVE_CUBS = installed(("newsletter", NL), ("examplecom", ("draft.sanity",)))


def issue(store, subject: str, at: datetime, *, service: str = "newsletter",
          kind: str = "send.newsletter") -> tuple[str, int]:
    with time_machine.travel(at, tick=False):
        d = new_draft(store, cub="newsletter", service=service,
                      content={"subject": subject, "body": f"Intro.\n\n**{subject}**\n"
                                                            "[source](https://ex.com/a)"},
                      run_uuid=None)
    fields = {"draft_ref": d["ref"], "subject": subject, "audience": "all"}
    if kind == "send.newsletter":
        fields["when"] = "now"
    tid = tickets.file(store, cub="newsletter", trust="owner", granted=(kind,), kind=kind,
                       fields=fields, subject=("newsletter_issue", d["ref"]), now=at)
    return d["ref"], tid


def live_copy(rt) -> dict:  # noqa: F811
    """A real install's five drafts and seven asks, filed under the limits the kinds had then."""
    store = rt.store
    old_kind, old = next(iter(newsletter.legacy_kinds().items()))
    with old_limits():
        r1, t1 = issue(store, "This week: Kodama raises $7M", OCT(21),
                       service=old.legacy["service"], kind=old_kind)
        d2 = new_draft(store, cub="examplecom", service="sanity",
                       content={"doc": "post-what-parallax-turned-into",
                                "title": "What Parallax turned into",
                                "slug": "what-parallax-turned-into", "category": "build",
                                "excerpt": "Six months of patient agents.",
                                "body": "In April I wrote about patient agents."},
                       run_uuid=None)
        fields2 = {"draft_ref": d2["ref"], "slug": "what-parallax-turned-into",
                   "title": "What Parallax turned into", "category": "build"}
        t2 = tickets.file(store, cub="examplecom", trust="owner", granted=("draft.sanity",),
                          kind="draft.sanity", fields=fields2,
                          subject=("examplecom_post", d2["ref"]), now=OCT(22, 3))
        tickets.expire_due(store, now=OCT(25))
        r3, t3 = issue(store, "This week: Eka Robotics raises $150M", OCT(27, 19))
        assert tickets.confirm(store, t3, identity=UI, confirm=True, context=rt,
                               now=OCT(28))["state"] == "dry"
        t4 = tickets.file(store, cub="newsletter", trust="owner", granted=NL,
                          kind="send.newsletter",
                          fields=tickets.get(store, t3)["fields"],
                          subject=("newsletter_issue", r3), now=OCT(31, 10),
                          note=f"offered again by your click (it was #{t3}, dry)")
        t5 = tickets.file(store, cub="examplecom", trust="owner", granted=("draft.sanity",),
                          kind="draft.sanity", fields=fields2,
                          subject=("examplecom_post", d2["ref"]), now=OCT(31, 10),
                          note=f"offered again by your click (it was #{t2}, expired)")
        r6, t6 = issue(store, "This week: Ludo Robotics unveils Ludi 0.2", N(2))
        tickets.expire_due(store, now=N(5, 5))
        r7, t7 = issue(store, S5, N(9))
    return {"t": [None, t1, t2, t3, t4, t5, t6, t7], "r1": r1, "d2": d2["ref"], "r3": r3,
            "r6": r6, "r7": r7}


def last(store, tid: int) -> dict:
    return tickets.get(store, tid, now=NOW)["history"][-1]


# -- an ask that waits -----------------------------------------------------------------------


def test_a_drafts_ask_has_no_time_limit(rt):  # noqa: F811
    ref, tid = issue(rt.store, S5, N(9))
    t = tickets.get(rt.store, tid, now=NOW + timedelta(days=4000))
    assert t["expires_at"] == tickets.NEVER and t["state"] == tickets.OPEN
    assert tickets.waits(t["expires_at"])
    assert tickets.expire_due(rt.store, now=NOW + timedelta(days=4000)) == 0
    assert [a["id"] for a in asks.latest(rt.store)] == [tid]
    # the posting kinds wait; a trip's proposal keeps its day
    tickets.kind_names()
    waiting = {k for k, s in tickets.KINDS.items() if s.expires_hours is None}
    assert {"send.newsletter", "post.mastodon", "draft.sanity"} <= waiting
    assert tickets.KINDS["book.propose"].expires_hours == 24
    assert tickets.describe_kinds()["send.newsletter"]["expires_hours"] is None


def test_the_next_issue_replaces_this_one(rt):  # noqa: F811
    store = rt.store
    r1, t1 = issue(store, "Monday's issue", N(9))
    r2, t2 = issue(store, "Next Monday's issue", N(16))
    old = tickets.get(store, t1)
    assert old["state"] == "expired" and old["note"] == f"replaced by #{t2}"
    assert tickets.replaced_by(old["note"]) == t2 and not tickets.time_expired(old)
    assert old["said"].startswith("Replaced by a newer issue")
    assert old["history"][-1]["door"] == "core"
    assert [a["id"] for a in asks.latest(store)] == [t2]           # one row a series
    assert asks.again_why_not(store, old) == "a newer draft has come since"
    [ev] = [e for e in events.read(store, kinds=["ticket.resolved"])
            if e["payload"]["ticket_id"] == t1]
    assert ev["payload"]["state"] == "expired"
    # the replaced draft is still there to read
    got = post_api.post_read(rt)
    assert [d["ref"] for d in got["drafts"]] == [r2]
    assert [(d["ref"], d["said"]) for d in got["earlier"]] == [(r1, old["said"])]


def test_short_posts_about_different_things_both_wait(rt):  # noqa: F811
    store = rt.store
    tickets.kind_names()

    def toot(text: str, about: str) -> int:
        d = new_draft(store, cub="toot", service="mastodon", content={"text": text},
                      run_uuid=None)
        return tickets.file(store, cub="toot", trust="owner", granted=("post.mastodon",),
                            kind="post.mastodon",
                            fields={"draft_ref": d["ref"], "text": text,
                                    "visibility": "public", "language": "en"},
                            subject=("card", about))
    a, b = toot("About card 143", "143"), toot("About card 150", "150")
    assert [t["id"] for t in asks.latest(store)] == [b, a]
    c = toot("About card 143, again", "143")
    assert tickets.get(store, a)["note"] == f"replaced by #{c}"
    assert tickets.get(store, b)["state"] == tickets.OPEN


# -- what ran out of time waits again ----------------------------------------------------------


def test_the_unseen_drafts_wait_again_once(rt):  # noqa: F811
    store = rt.store
    x = live_copy(rt)
    t = x["t"]
    # before: #7 reads expired (no row yet), and nothing waits
    assert tickets.get(store, t[7], now=NOW)["state"] == "expired"
    assert all(a["state"] != tickets.OPEN for a in tickets.listing(store, now=NOW))
    new = asks.wait_again(store, LIVE_CUBS, now=NOW)
    assert len(new) == 2
    by_ref = {tickets.get(store, n)["fields"]["draft_ref"]: tickets.get(store, n) for n in new}
    assert set(by_ref) == {x["r7"], x["d2"]}
    issue7, post2 = by_ref[x["r7"]], by_ref[x["d2"]]
    assert issue7["state"] == post2["state"] == tickets.OPEN
    assert issue7["expires_at"] == post2["expires_at"] == tickets.NEVER
    assert issue7["history"][0]["note"] == f"waits for you again: it had run out of time " \
                                           f"(#{t[7]})"
    assert issue7["fields"]["subject"] == S5 and issue7["subject_id"] == x["r7"]
    # #7 got its expired row first, as the sweep would have written it
    assert last(store, t[7]) | {"created_at": None} == {
        "state": "expired", "door": "core", "note": tickets.PAST_TIME, "created_at": None}
    # the older issues stay where they were: #6 (a newer issue came), #4 (pressed once, as #3)
    for old in (t[1], t[4], t[6]):
        assert tickets.get(store, old, now=NOW)["state"] == "expired"
    # once: the fresh asks are the drafts' newest
    assert asks.wait_again(store, LIVE_CUBS, now=NOW + timedelta(days=1)) == []
    assert {a["id"] for a in asks.latest(store)} >= set(new)


def test_a_draft_does_not_wait_again_when_it_should_not(rt):  # noqa: F811
    store = rt.store
    x = live_copy(rt)
    # a cub that is not installed, or no longer asks for the kind: nothing is filed
    assert asks.wait_again(store, {}, now=NOW) == []
    assert asks.wait_again(store, installed(("newsletter", NL), ("examplecom", ("draft.sanity",)),
                                            state="paused"), now=NOW) == []
    assert asks.wait_again(store, installed(("newsletter", ()), ("examplecom", ())),
                           now=NOW) == []
    # a draft withdrawn by its cub (redrafted) or declined does not come back
    ref, tid = issue(store, "Withdrawn", N(10))
    tickets.expire_for(store, cub="newsletter", subject_kind="newsletter_issue",
                       subject_id=ref, note="redrafted")
    assert not tickets.time_expired(tickets.get(store, tid))
    # the withdrawn issue is now the newsletter's newest draft: it does not come back, and #7's
    # issue is no longer the newest, so only example.com's post waits again
    assert x_refs(asks.wait_again(store, LIVE_CUBS, now=NOW), store) == {x["d2"]}


def x_refs(ids, store) -> set[str]:
    return {tickets.get(store, i)["fields"]["draft_ref"] for i in ids}


def test_the_cubs_start_and_daily_gc_let_drafts_wait_again(rt, monkeypatch):  # noqa: F811
    from kranto.core.cubs.runtime import CubRuntime
    store = rt.store
    x = live_copy(rt)
    cubs = CubRuntime(rt)
    cubs.installed = LIVE_CUBS
    monkeypatch.setattr("kranto.core.asks.utcnow", lambda: NOW)
    assert cubs._wait_again() == 2
    assert cubs._wait_again() == 0
    assert tickets.get(store, x["t"][7])["state"] == "expired"
    # a failure never stops the cubs' start
    monkeypatch.setattr("kranto.core.asks.wait_again",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cubs._wait_again() == 0


# -- Post's read -------------------------------------------------------------------------------


@pytest.fixture
def post(rt):  # noqa: F811
    x = live_copy(rt)
    asks.wait_again(rt.store, LIVE_CUBS, now=NOW)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        yield client, x


def _counts(store) -> tuple:
    return tuple(store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
                 for t in ("cub_tickets", "cub_ticket_states", "cub_drafts", "events"))


def test_post_lists_the_two_drafts_that_wait(rt, post):  # noqa: F811
    client, x = post
    before = _counts(rt.store)
    r = client.get("/api/post")
    assert r.status_code == 200 and problems(r.json(), T.Post) == []
    got = r.json()
    assert got["line"] == "Drafts wait here until you have seen them."
    rows = got["drafts"]
    assert [(d["ref"], d["word"], d["kind"]) for d in rows] == [
        (x["r7"], "newsletter", "newsletter"), (x["d2"], "blog post", "blog")]
    issue7 = rows[0]
    assert issue7["title"] == S5 and issue7["fact"] == "Monday's issue"
    assert issue7["ticket"] and issue7["verb"] == "Send" and not issue7["account"]
    assert issue7["line"] == "needs a newsletter account" and issue7["said"] is None
    assert [d["ref"] for d in got["earlier"]] == [x["r6"], x["r3"], x["r1"]]
    # an earlier draft says what happened to it, and offers no Send
    assert all(d["line"] is None and d["ticket"] is None and d["verb"] is None
               and d["said"].startswith("Not approved in time") for d in got["earlier"])
    assert got["sent"] == []
    assert [(a["key"], a["word"], a["state"]) for a in got["accounts"]] == [
        ("newsletter", "Newsletter", "not set"), ("mastodon", "Mastodon", "not set"),
        ("blog", "Blog", "not set")]
    assert _counts(rt.store) == before                             # a read writes nothing


def test_a_drafts_sheet_and_its_download(rt, post):  # noqa: F811
    client, x = post
    issue7 = client.get("/api/post").json()["drafts"][0]
    r = client.get(f"/api/post/d/{issue7['id']}")
    assert r.status_code == 200 and problems(r.json(), T.PostSheet) == []
    sheet = r.json()
    assert sheet["group"] == "waiting" and sheet["markdown"].startswith(f"# {S5}\n\nIntro.")
    assert "[source](https://ex.com/a)" in sheet["markdown"]
    assert sheet["filename"] == "This week Amazon teams single policy grasps 66 objects with " \
                                "no teleoperation.md"
    assert sheet["account_of"]["key"] == "newsletter"
    d = client.get(f"/api/post/d/{issue7['id']}.md")
    assert d.status_code == 200 and d.headers["content-type"].startswith("text/markdown")
    assert d.text == sheet["markdown"]
    assert re.fullmatch(r'attachment; filename="[A-Za-z0-9 _-]+\.md"',
                        d.headers["content-disposition"])
    # the blog post: its title, its excerpt, its body
    blog = client.get("/api/post").json()["drafts"][1]
    md = client.get(f"/api/post/d/{blog['id']}.md").text
    assert md == ("# What Parallax turned into\n\n*Six months of patient agents.*\n\n"
                  "In April I wrote about patient agents.\n")
    for path in ("/api/post/d/999", "/api/post/d/999.md"):
        assert client.get(path).status_code == 404


def test_sent_and_an_account_show_on_post(rt):  # noqa: F811
    store = rt.store
    ref, tid = issue(store, "Sent issue", N(9))
    tickets.append_state(store, tid, "confirmed", door="ui", note="mode: live")
    tickets.append_state(store, tid, "done", door="ui",
                         note="sent to 312 subscribers (https://buttondown.com/x/archive/1); "
                              "undo within minutes at Buttondown")
    conn = store.insert("connections", dict(provider="mastodon", instance="mastodon.social",
                                            account="@me@mastodon.social", scopes="[]",
                                            created_at="2026-11-01T00:00:00Z"))
    store.insert("connection_events", dict(connection_id=conn, event="connected", note="ok",
                                           created_at="2026-11-01T00:00:00Z"))
    got = post_api.post_read(rt)
    [sent] = got["sent"]
    assert sent["ref"] == ref and sent["said"].startswith("Sent on")
    assert sent["link"] == "https://buttondown.com/x/archive/1" and "312" in sent["note"]
    acct = {a["key"]: a for a in got["accounts"]}
    assert acct["mastodon"]["state"] == "connected"
    assert acct["mastodon"]["account"] == "@me@mastodon.social"


def test_a_practiced_newest_draft_still_waits_and_an_unreadable_one_is_skipped(rt):  # noqa: F811
    store = rt.store
    ref, tid = issue(store, "Practiced issue", N(9))
    assert tickets.confirm(store, tid, identity=UI, confirm=True, context=rt)["state"] == "dry"
    store.insert("cub_drafts", {"cub": "toot", "service": "mastodon", "ref": "draft:99",
                                "content": "not json", "content_hash": "x",
                                "created_at": "2026-11-10T00:00:00Z"})
    got = post_api.post_read(rt)
    [row] = got["drafts"]
    assert row["ref"] == ref and row["again"] == tid and row["ticket"] is None
    assert row["said"].startswith("Practiced on")
    assert all(d["ref"] != "draft:99" for d in got["drafts"] + got["earlier"])


def test_the_markdown_and_file_name_rules():
    assert post_api.markdown_of({"text": "A toot."}) == "A toot.\n"
    assert post_api.markdown_of({"subject": "S", "body": "B\n\n"}) == "# S\n\nB\n"
    assert post_api.filename("a/b: c?.md") == "ab cmd.md"
    assert post_api.filename("///") == "draft.md"
    assert len(post_api.filename("x" * 300)) == 83
    assert post_api.kind_of(None, "buttondown") == "newsletter"
    assert post_api.title_of({"text": "First line\nsecond"}) == "First line"
    json.dumps(post_api.post_read.__doc__)
