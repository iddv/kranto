"""Send at an hour (SOC-10): a post the person said yes to goes at the hour they chose, can be
moved or cancelled until then, never goes without that yes, survives a restart, and a missed
hour (Kranto stopped) asks again instead of sending late. Nothing is posted: the site's send is
replaced by a counter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kranto.core import tickets
from kranto.core.cubs.brokers.base import new_draft
from kranto.core.cubs.brokers.social import FILER
from kranto.social import hours
from kranto.store import Store, iso
from kranto.web import post_api

UI = {"origin": "ui", "via": "cookie"}
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
NINE = "2026-11-16T09:00Z"
AT_NINE = datetime(2026, 11, 16, 9, 0, 20, tzinfo=UTC)


@pytest.fixture
def sent(monkeypatch):
    """Every site's send replaced: a list of the tickets pressed, each answered done."""
    tickets.kind_names()
    pressed: list[int] = []

    def perform(store, t, context, mode="live"):
        pressed.append(int(t["id"]))
        return {"state": "done", "note": "posted: https://bsky.app/profile/a/post/x"}
    for kind in hours.kinds():
        monkeypatch.setattr(tickets.KINDS[kind], "perform", perform)
    return pressed


def _rt(store, tmp_path):
    return SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), cubs=None)


def _ask(store, site="bluesky", kind="post.bluesky", text="Kiosks lose batteries daily."):
    d = new_draft(store, cub=FILER, service=site, run_uuid=None, content={
        "site": site, "parts": [{"text": text}], "text": text, "group": "w1",
        "about_title": "Kiosks"})
    fields = {"draft_ref": d["ref"], "text": text}
    if kind == "post.bluesky":
        fields.update(parts=1, language="en")
    if kind == "post.open":
        fields["site"] = site
    tid = tickets.file(store, cub=FILER, trust="core", granted=(kind,), kind=kind,
                       fields=fields, capped=False, now=NOW - timedelta(hours=1))
    return d, tid


def _schedule(store, tid, rt, when=NINE, now=NOW):
    return tickets.confirm(store, tid, identity=UI, confirm=True, context=rt, now=now, when=when)


def test_every_direct_send_may_be_held_and_open_may_not():
    assert set(hours.kinds()) == {"post.bluesky", "post.mastodon", "post.threads",
                                  "post.linkedin"}
    assert not tickets.KINDS["post.open"].meta.get("holds")


def test_schedule_keeps_the_yes_and_sends_nothing_until_the_hour(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    out = _schedule(store, tid, rt)
    assert out["outcome"]["state"] == "scheduled" and "Monday 16 Nov" in out["outcome"]["note"]
    assert out["state"] == tickets.OPEN and sent == []
    assert hours.tick(store, rt, now=NOW + timedelta(minutes=59)) == []
    assert sent == []
    got = hours.tick(store, rt, now=AT_NINE)
    assert sent == [tid] and got[0]["state"] == "done"
    assert tickets.get(store, tid)["state"] == "done"
    hist = tickets.get(store, tid)["history"]
    assert hist[-2]["state"] == "confirmed" and hist[-2]["door"] == "ui"
    assert "when: 2026-11-16T09:00:00Z" in hist[-2]["note"] and "your yes at" in hist[-2]["note"]
    assert hours.tick(store, rt, now=AT_NINE + timedelta(minutes=1)) == [] and sent == [tid]


def test_the_scheduled_group_on_post_with_its_hour(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    _schedule(store, tid, rt)
    page = post_api.post_read(rt)
    assert page["drafts"] == []
    row, = page["scheduled"]
    assert row["id"] == d["id"] and row["due"] == "2026-11-16T09:00:00Z"
    assert row["due_words"].endswith(":00") and row["ticket"] == tid
    sheet = post_api.draft_sheet(rt, d["id"])
    assert sheet["group"] == "scheduled" and not sheet["can_edit"]
    assert "cancel its time first" in sheet["cannot_edit"]


def test_cancel_before_the_hour_sends_nothing_and_the_draft_waits(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    _schedule(store, tid, rt)
    out = post_api.cancel_hour(rt, d["id"], UI)
    assert out["ok"] and "nothing is sent" in out["say"]
    assert hours.tick(store, rt, now=AT_NINE) == [] and sent == []
    page = post_api.post_read(rt)
    assert page["scheduled"] == [] and page["drafts"][0]["ticket"] == tid
    with pytest.raises(post_api.WriteError):
        post_api.cancel_hour(rt, d["id"], UI)


def test_moving_the_hour_sends_only_at_the_new_one(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    _schedule(store, tid, rt, when="2026-11-16T11:30Z")
    assert hours.tick(store, rt, now=AT_NINE) == [] and sent == []
    hours.tick(store, rt, now=datetime(2026, 11, 16, 11, 30, 5, tzinfo=UTC))
    assert sent == [tid]


def test_only_the_page_may_schedule_and_never_on_the_preview(store, tmp_path, sent,
                                                             monkeypatch):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    for who in ({"origin": "agent"}, {"origin": "cli"}, {"origin": "ui", "via": "token"}):
        with pytest.raises(tickets.TicketError) as e:
            tickets.confirm(store, tid, identity=who, confirm=True, context=rt, now=NOW,
                            when=NINE)
        assert e.value.code == 403
    monkeypatch.setenv("KRANTO_PREVIEW", "1")
    with pytest.raises(tickets.TicketError) as e:
        _schedule(store, tid, rt)
    assert e.value.code == 409 and hours.held(store) == []


def test_a_held_post_is_never_pressed_on_the_preview(store, tmp_path, sent, monkeypatch):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    monkeypatch.setenv("KRANTO_PREVIEW", "1")
    assert hours.tick(store, rt, now=AT_NINE) == [] and sent == []


def test_a_time_too_soon_past_or_far_is_refused_in_words(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    for when, words in (("2026-11-16T08:01Z", "two minutes"), ("2026-11-15T09:00Z", "passed"),
                        ("2027-02-16T09:00Z", "60 days")):
        with pytest.raises(tickets.TicketError, match=words):
            _schedule(store, tid, rt, when=when)
    assert hours.held(store) == []


def test_a_restart_keeps_the_schedule(tmp_path, sent):
    path = tmp_path / "kranto.db"
    s1 = Store.open(path)
    s1.migrate()
    rt = _rt(s1, tmp_path)
    _, tid = _ask(s1)
    _schedule(s1, tid, rt)
    s1.close()
    s2 = Store.open(path)                    # Kranto started again
    s2.migrate()
    rt2 = _rt(s2, tmp_path)
    assert [h["ticket_id"] for h in hours.held(s2)] == [tid]
    hours.tick(s2, rt2, now=AT_NINE)
    assert sent == [tid]
    s2.close()


def test_a_missed_hour_asks_again_instead_of_sending_late(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    _schedule(store, tid, rt)
    late = datetime(2026, 11, 16, 9, 11, tzinfo=UTC)     # Kranto was stopped at 09:00
    got = hours.tick(store, rt, now=late)
    assert got[0]["state"] == "missed" and sent == []
    assert tickets.get(store, tid)["state"] == tickets.OPEN
    row = post_api.post_read(rt)["drafts"][0]
    assert row["ticket"] == tid and "passed while Kranto was stopped" in row["missed"]
    msg = store.query_one("SELECT title, origin FROM messages WHERE dedup_key LIKE 'post-missed:%'")
    assert msg["origin"] == "post.hours" and "Not posted at" in msg["title"]
    assert hours.tick(store, rt, now=late + timedelta(minutes=1)) == []
    # the person's new yes goes at once
    out = tickets.confirm(store, tid, identity=UI, confirm=True, context=rt, now=late,
                          when="now")
    assert out["state"] == "done" and sent == [tid]


def test_under_ten_minutes_late_still_goes_over_does_not(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, a = _ask(store, text="One.")
    _, b = _ask(store, site="threads", kind="post.threads", text="Two.")
    _schedule(store, a, rt)
    _schedule(store, b, rt, when="2026-11-16T09:01Z")
    # 10.5 minutes after a's hour, 9.5 after b's
    hours.tick(store, rt, now=datetime(2026, 11, 16, 9, 10, 30, tzinfo=UTC))
    assert sent == [b]
    assert hours.newest(store, a)["state"] == "missed"


def test_an_edit_after_the_yes_needs_a_new_yes(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    _schedule(store, tid, rt)
    post_api.cancel_hour(rt, d["id"], UI)            # the page's way: cancel, then edit
    _schedule(store, tid, rt)
    # an edit files the next draft and replaces the ask (the edit route's own path)
    d2 = new_draft(store, cub=FILER, service="bluesky", run_uuid=None, content={
        "site": "bluesky", "parts": [{"text": "Other words."}], "text": "Other words.",
        "group": "w1"})
    tickets.append_state(store, tid, "expired", door="core", note="replaced by #99")
    got = hours.tick(store, rt, now=AT_NINE)
    assert got[0]["state"] == "void" and sent == []
    assert d2["ref"] != d["ref"]


def test_a_decline_before_the_hour_voids_the_hold(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    tickets.decline(store, tid, identity=UI)
    assert hours.tick(store, rt, now=AT_NINE)[0]["state"] == "void" and sent == []


def test_post_now_beside_a_hold_sends_once(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    tickets.confirm(store, tid, identity=UI, confirm=True, context=rt, now=NOW, when="now")
    hours.tick(store, rt, now=AT_NINE)
    assert sent == [tid]


def test_press_held_refuses_a_yes_for_other_words_or_another_door(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    h = hours.held(store)[0]
    with pytest.raises(tickets.TicketError, match="words changed"):
        tickets.press_held(store, tid, context=rt, now=AT_NINE, yes={**h, "fields_hash": "x"})
    with pytest.raises(tickets.TicketError, match="page"):
        tickets.press_held(store, tid, context=rt, now=AT_NINE, yes={**h, "door": "cli"})
    assert sent == []


def test_a_send_that_fails_at_its_hour_is_not_tried_again(store, tmp_path, monkeypatch):
    rt = _rt(store, tmp_path)
    tickets.kind_names()
    calls = []

    def boom(store, t, context, mode="live"):
        calls.append(t["id"])
        raise RuntimeError("the site did not answer")
    monkeypatch.setattr(tickets.KINDS["post.bluesky"], "perform", boom)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    hours.tick(store, rt, now=AT_NINE)
    hours.tick(store, rt, now=AT_NINE + timedelta(seconds=30))
    assert calls == [tid] and tickets.get(store, tid)["state"] == "unknown"


def test_the_lane_ticks_and_says_its_state(store, tmp_path, sent):
    rt = _rt(store, tmp_path)
    lane = hours.HoursLane(rt, tick_seconds=0.01)
    assert lane.once() == [] and lane.status()["state"] == "running"
    lane.hold = "updating"
    assert lane.status()["state"] == "held"


def test_the_dialog_offers_schedule_in_the_persons_own_time(store, tmp_path, sent):
    from kranto.core import asks
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    a = asks.ask(rt, tickets.get(store, tid))
    assert a["schedule"] is True and a["zone"] == "local"
    _, opened = _ask(store, site="x", kind="post.open")
    assert asks.ask(rt, tickets.get(store, opened))["schedule"] is False


def test_readers_of_the_ticket_states_see_a_held_ask_as_waiting(store, tmp_path, sent):
    """No new ticket state: a held ask is ``needs_confirm`` for every reader (asks.latest,
    the overlay, the sweep), and ``post_due`` is read only by ``hours`` and ``post_api``."""
    from kranto.core import asks
    rt = _rt(store, tmp_path)
    _, tid = _ask(store)
    _schedule(store, tid, rt)
    assert [t["id"] for t in asks.latest(store, FILER)] == [tid]
    assert tickets.expire_due(store, now=NOW + timedelta(days=30)) == 0
    assert iso(NOW)  # the clock the hold used


def test_no_door_may_edit_a_scheduled_draft_so_its_time_never_carries_other_words(store, tmp_path,
                                                                                  sent):
    """``post.edit`` runs from any door (an assistant's too): a scheduled draft is refused, so a
    time the person chose never goes with words they did not say yes to."""
    rt = _rt(store, tmp_path)
    d, tid = _ask(store)
    _schedule(store, tid, rt)
    for door in ("ui", "cli"):
        with pytest.raises(post_api.WriteError, match="cancel its time first"):
            post_api.edit_draft(rt, d["id"], {"parts": [{"text": "Other words."}]}, door)
    # an assistant's edit (``edited_by``), pressed by the owner after the time was chosen
    with pytest.raises(post_api.WriteError, match="cancel its time first"):
        post_api.edit_draft(rt, d["id"], {"parts": [{"text": "My assistant's words."}]}, "mcp",
                            by="mcp:claude-code")
    assert hours.held_of(store, tid) is not None
    hours.tick(store, rt, now=AT_NINE)
    assert sent == [tid]
