"""What a cub asks, in plain words (SEND; the owner, 2026-10-29: "Not sure what 'ticket #1 is
expired' means, I just wanted to post the newsletter. Seems like nothing is connected.").

Live's library as it stood: #1 the newsletter's issue of 21 Oct under an earlier release's kind,
expired on 23 Oct while the cub's own row still said "waiting"; #2 example.com's post, expired on 25
Oct; #3 the newsletter's issue of 27 Oct, approved on 28 Oct in practice, so nothing was sent.
The core, never the cub's row, says what waits: #1 never opens a dialog again (a newer draft came);
#3 and #2 are offered again, each by the owner's click on the page; #3's history says it was
practiced, not sent."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime

import pytest

from kranto import newsletter
from kranto.core import asks, tickets
from kranto.core.cubs.brokers.base import new_draft

from .cubhelp import needs_bwrap
from .test_examples_install import add, brief, home  # noqa: F401 - fixtures
from .test_web import rt  # noqa: F401 - fixture

UI = {"origin": "ui", "via": "cookie"}
CLI = {"origin": "cli"}
T = lambda d, h=6: datetime(2026, 10, d, h, 0, tzinfo=UTC)  # noqa: E731
S1 = "This week: Kodama raises $7M for supervised-autonomy forestry machines"
S3 = "This week: Eka Robotics raises $150M Series A for its vision-force-action model"
# the words a dialog, a row or a history line never says to the owner
JARGON = ("ticket", "dry", "draft:", "cub ")


@contextlib.contextmanager
def old_limits():
    """The kinds' time limits as they were before a draft waited until seen (48 hours for an
    issue and a toot, 72 for a Sanity draft): the tickets live filed then carry them."""
    tickets.kind_names()
    old = {k: s.expires_hours for k, s in tickets.KINDS.items()}
    for k, s in tickets.KINDS.items():
        if s.expires_hours is None:
            s.expires_hours = 72 if tickets.canonical(k) == "draft.sanity" else 48
    try:
        yield
    finally:
        for k, h in old.items():
            tickets.KINDS[k].expires_hours = h


def live(rt) -> dict:  # noqa: F811
    """Live's three tickets, as they stood on 2026-10-29."""
    with old_limits():
        return _live(rt)


def _live(rt) -> dict:  # noqa: F811
    store = rt.store
    old_kind, old = next(iter(newsletter.legacy_kinds().items()))
    d1 = new_draft(store, cub="newsletter", service=old.legacy["service"],
                   content={"subject": S1, "body": "**Kodama raises $7M**\nForestry."},
                   run_uuid=None)
    t1 = tickets.file(store, cub="newsletter", trust="owner", granted=(old_kind,),
                      kind=old_kind, fields={"draft_ref": d1["ref"], "subject": S1,
                                             "audience": "all"}, now=T(21))
    d2 = new_draft(store, cub="examplecom", service="sanity",
                   content={"doc": "post-what-parallax-turned-into", "title": "What Parallax "
                            "turned into", "slug": "what-parallax-turned-into",
                            "category": "build", "body": "Six months of patient agents."},
                   run_uuid=None)
    t2 = tickets.file(store, cub="examplecom", trust="owner", granted=("draft.sanity",),
                      kind="draft.sanity", fields={"draft_ref": d2["ref"], "slug":
                                                   "what-parallax-turned-into", "title":
                                                   "What Parallax turned into",
                                                   "category": "build"}, now=T(22))
    d3 = new_draft(store, cub="newsletter", service="newsletter",
                   content={"subject": S3, "body": "## Eka Robotics\n**$150M** Series A."},
                   run_uuid=None)
    t3 = tickets.file(store, cub="newsletter", trust="owner", granted=("send.newsletter",),
                      kind="send.newsletter", fields={"draft_ref": d3["ref"], "subject": S3,
                                                      "audience": "all", "when": "now"},
                      now=T(27, 19))
    out = tickets.confirm(store, t3, identity=UI, confirm=True, context=rt, now=T(28))
    assert out["state"] == "dry"
    tickets.expire_due(store, now=T(29))
    return {"t1": t1, "t2": t2, "t3": t3, "d1": d1["ref"], "d2": d2["ref"], "d3": d3["ref"]}


def plain(words) -> list[str]:
    """Each jargon word found in what the owner reads."""
    text = " ".join(str(w) for w in words if w).lower()
    return [j for j in JARGON if j in text]


def test_an_expired_ask_whose_draft_is_old_never_opens_a_dialog_again(rt):  # noqa: F811
    x = live(rt)
    waiting = [t["id"] for t in asks.latest(rt.store)]
    assert x["t1"] not in waiting                    # a newer issue came since
    assert waiting == [x["t3"], x["t2"]]
    # the cub's own row still says it waits (1.3.1 never heard its answer): the core names no
    # ticket in it, so no list offers a dialog, and Needs you lists the core's ask instead
    got = {"waiting": [{"id": x["d1"], "ticket": x["t1"]}], "rows": [{"id": x["d1"],
                                                                      "ticket": x["t1"]}]}
    assert asks.overlay(rt.store, "newsletter", got)["waiting"][0]["ticket"] is None
    [row] = asks.needs_rows(rt, "newsletter", {"rows": got["rows"]})["rows"]
    assert row["id"] == x["d3"] and row["ticket"] is None and row["again"] == x["t3"]
    assert row["title"] == S3 and row["verb"] == "Send"
    assert row["meta"] == "needs a newsletter account"


def test_the_practiced_issue_says_so_in_its_history(rt):  # noqa: F811
    x = live(rt)
    t3 = tickets.get(rt.store, x["t3"])
    assert t3["said"] == "Practiced on 28 Oct: not sent"
    [h3, h2] = [h for h in asks.history(rt.store, "newsletter")][:1] + \
        asks.history(rt.store, "examplecom")
    assert h3["said"] == "Practiced on 28 Oct: not sent" and h3["title"] == S3
    assert h2["said"].startswith("Not approved in time: not sent to Sanity")
    assert plain([h3["said"], h2["said"]]) == []


def test_the_dialog_is_plain_and_says_what_stops_it(rt):  # noqa: F811
    x = live(rt)
    a = asks.ask(rt, tickets.get(rt.store, x["t3"]))
    assert a["verb"] == "Send now" and a["title"] == S3 and a["body"].startswith("## Eka")
    assert a["needs"]["button"] == "Connect a newsletter account"
    assert a["needs"]["connect"] == "newsletter" and a["to"] is None
    assert a["practice"]["words"].startswith(asks.PRACTICE) and a["again"] and not a["open"]
    words = [a["verb"], a["title"], a["to"], a["needs"]["words"], a["needs"]["button"],
             a["needs"]["line"], a["practice"]["words"], a["said"]]
    assert plain(words) == []
    post = asks.ask(rt, tickets.get(rt.store, x["t2"]))
    assert post["verb"] == "Send to Sanity" and post["needs"]["button"] == "Connect Sanity"
    assert "publish in Studio" in post["to"]


def test_a_draft_is_offered_again_on_the_page_only(rt):  # noqa: F811
    x = live(rt)
    with pytest.raises(tickets.TicketError) as e:
        asks.again(rt, x["t3"], identity=CLI)
    assert e.value.code == 403
    with pytest.raises(tickets.TicketError) as e:
        asks.again(rt, x["t1"], identity=UI)
    assert e.value.code == 409 and "newer draft" in str(e.value)


def test_a_chosen_time_is_for_a_kind_that_schedules_and_still_ahead(rt):  # noqa: F811
    store = rt.store
    d = new_draft(store, cub="newsletter", service="newsletter",
                  content={"subject": "s", "body": "b"}, run_uuid=None)
    tid = tickets.file(store, cub="newsletter", trust="owner", granted=("send.newsletter",),
                       kind="send.newsletter", fields={"draft_ref": d["ref"], "subject": "s",
                                                       "audience": "all", "when": "now"})
    with pytest.raises(tickets.TicketError, match="passed"):
        tickets.confirm(store, tid, identity=UI, confirm=True, context=rt,
                        when="2020-01-01T09:00Z")
    with pytest.raises(tickets.TicketError, match="now or a UTC time"):
        tickets.confirm(store, tid, identity=UI, confirm=True, context=rt, when="tomorrow")
    seen = {}
    spec = tickets.KINDS["send.newsletter"]
    perform = spec.perform
    try:
        spec.perform = lambda store, t, context, mode: (seen.update(t), {"state": "dry"})[1]
        tickets.confirm(store, tid, identity=UI, confirm=True, context=rt,
                        when="2099-11-02T09:30Z")
    finally:
        spec.perform = perform
    assert seen["press_when"] == "2099-11-02T09:30Z"
    assert "when: 2099-11-02T09:30Z" in tickets.get(store, tid)["history"][1]["note"]


@needs_bwrap
def test_the_owners_click_offers_the_latest_issue_again_with_no_cub_run(home):  # noqa: F811
    add(home, "newsletter")
    brief(home, "Solar kits sold out in Lagos.", "A battery plant opened in Nairobi.")
    assert home.cubs.run_job("newsletter", "newsletter.weekly", "compose")["status"] == "ok"
    [t] = tickets.listing(home.store, cub="newsletter")
    assert tickets.confirm(home.store, t["id"], identity=UI, confirm=True,
                           context=home)["state"] == "dry"
    home.cubs.deliver_all()
    page = home.cubs.page_read("newsletter", "rows", {})
    [row] = page["rows"]
    assert row["again"] == t["id"] and row["ticket"] is None and row["verb"] == "Send"
    assert home.cubs.page_read("newsletter", "count", {})["count"] == 1
    work = ("SELECT (SELECT COUNT(*) FROM runs) + (SELECT COUNT(*) FROM llm_calls) + (SELECT "
            "COUNT(*) FROM cub_calls WHERE op NOT IN ('read', 'ticket.file')) AS n")
    before = home.store.query_one(work)["n"]
    fresh = asks.again(home, t["id"], identity=UI)
    assert fresh["state"] == tickets.OPEN and fresh["fields"] == t["fields"]
    assert fresh["history"][0]["note"].startswith("offered again by your click")
    # no cub run, no cub call and no model call made it
    assert home.store.query_one(work)["n"] == before
    [row] = home.cubs.page_read("newsletter", "rows", {})["rows"]
    assert row["ticket"] == fresh["id"] and row["again"] is None
    a = asks.ask(home, fresh)
    assert a["practice"]["switch"] == {"cub": "newsletter", "kind": "send.newsletter",
                                       "words": a["practice"]["switch"]["words"]}
    assert "the ones after it" in a["practice"]["switch"]["words"]
    with pytest.raises(tickets.TicketError, match="already"):
        asks.again(home, t["id"], identity=UI)
    # the page's lists name no ticket that is not open
    issues = home.cubs.page_read("newsletter", "issues", {})
    named = [r["ticket"] for g in issues.values() if isinstance(g, list) for r in g]
    assert t["id"] not in named


def test_a_kind_with_no_plain_words_shows_its_read_back_in_the_dialog(rt):  # noqa: F811
    tid = tickets.file(rt.store, cub="trips", trust="owner", granted=("book.propose",),
                       kind="book.propose", fields={"legs": "AMS-LIS", "total": 212.0,
                                                    "currency": "EUR", "links": "one"})
    t = tickets.get(rt.store, tid)
    a = asks.ask(rt, t)
    assert a["facts"] == t["readback"] and ["Total", "212.0"] in a["facts"]
    assert a["question"] == "Propose this trip?"
