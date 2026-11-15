"""An assistant's change is never shown as the owner's own.

``post.edit`` through any door but the page and the command line is recorded and shown as the
assistant's ("edited by your assistant (mcp)"), and the verb is ``outward``: by default it waits
for the owner's press, and the press keeps who wrote the words. ``prose.voice`` from an
assistant waits for the owner when it changes the voice card, the always-list or a disclosure
line, whatever the ladder says for changes you can undo; a disclosure line goes through the
post's own link filter. I posted it checks and writes in one transaction; Settings › Posting
says when a direct draft still waits after Post directly is switched off.
"""

from __future__ import annotations

import json

import pytest

from kranto import prose, social, tokens
from kranto.core import sites, tickets, verbs
from kranto.core.cubs.brokers.base import new_draft
from kranto.core.cubs.brokers.social import FILER
from kranto.web import post_api
from kranto.web.app import create_app

from .conftest import web_client
from .test_post_api import N, issue
from .test_social import UI, Model, _material, _rt, _write
from .test_web import rt  # noqa: F401 - fixture

BASE = "http://127.0.0.1:8765"


def bearer(name: str) -> dict[str, str]:
    tokens.Store().ensure_doors()
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def _draft_id(store, ref: str) -> int:
    return int(store.query_one("SELECT id FROM cub_drafts WHERE ref = ?", (ref,))["id"])


def _content(store, did: int) -> dict:
    return json.loads(store.query_one("SELECT content FROM cub_drafts WHERE id = ?",
                                      (did,))["content"])


# -- post.edit ------------------------------------------------------------------------------------

def test_post_edit_is_outward_so_an_assistant_waits_for_the_owner():
    v = verbs.get("post.edit")
    assert v is not None and v.ladder == "outward" and v.method == "POST"
    assert verbs.choice_for(None, v).choice == "ask"


def test_an_assistants_edit_changes_nothing_until_the_owner_presses_it(rt):  # noqa: F811
    store = rt.store
    ref, tid = issue(store, "Monday's issue", N(9))
    did = _draft_id(store, ref)
    app = create_app(rt, port=8765)
    with web_client(app, BASE, signed_in=False) as web:
        r = web.post("/api/verbs/post.edit", headers=bearer("mcp"),
                     json={"subject": did, "fields": {"body": "Words my assistant chose."},
                           "client": "claude-code"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["prepared"] and not out["ok"] and out["choice"] == "ask"
    # nothing changed on Post: the same draft waits with the same ask, no new draft
    assert store.query_one("SELECT COUNT(*) AS n FROM cub_drafts")["n"] == 1
    assert tickets.get(store, tid)["state"] == tickets.OPEN
    with web_client(app, BASE) as page:
        listed = page.get("/api/prepared").json()["prepared"]
        assert listed[0]["fields"]["body"] == "Words my assistant chose."
        r = page.post(f"/api/prepared/{out['prepared']}/press", json={})
        assert r.status_code == 200 and r.json()["state"] == "pressed", r.text
        new_id = r.json()["answer"]["id"]
        sheet = page.get(f"/api/post/d/{new_id}").json()
    # the press was the owner's; the words are the assistant's, and the draft says so
    assert sheet["edited"] and sheet["edited_words"] == "edited by your assistant (mcp)"
    assert sheet["edited_words"] != "edited by you"
    assert _content(store, new_id)["edited_by"] == "mcp:claude-code"
    t = tickets.get(store, r.json()["answer"]["ticket"])
    assert t["state"] == tickets.OPEN
    assert t["history"][0]["note"] == "edited by your assistant (mcp)"
    assert t["history"][0]["door"] == "mcp"
    assert tickets.get(store, tid)["state"] == "expired"


def test_the_owners_own_edit_on_the_page_says_edited_by_you(rt):  # noqa: F811
    store = rt.store
    ref, _ = issue(store, "Issue", N(9))
    did = _draft_id(store, ref)
    with web_client(create_app(rt, port=8765), BASE) as page:
        r = page.post(f"/api/post/d/{did}/edit", json={"body": "My own words."})
        assert r.status_code == 200, r.text
        sheet = page.get(f"/api/post/d/{r.json()['id']}").json()
    assert sheet["edited_words"] == "edited by you"
    t = tickets.get(store, r.json()["ticket"])
    assert t["history"][0]["note"] == "edited by you" and t["history"][0]["door"] == "ui"


def test_the_command_line_is_the_owner_too(rt):  # noqa: F811
    store = rt.store
    ref, _ = issue(store, "Issue", N(9))
    did = _draft_id(store, ref)
    with web_client(create_app(rt, port=8765), BASE, signed_in=False) as web:
        r = web.post("/api/verbs/post.edit", headers=bearer("cli"),
                     json={"subject": did, "fields": {"body": "Typed in my terminal."}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    new = store.query_one("SELECT id FROM cub_drafts ORDER BY id DESC LIMIT 1")["id"]
    assert post_api.draft_sheet(rt, new)["edited_words"] == "edited by you"


def test_an_assistant_set_to_do_it_is_still_named(rt):  # noqa: F811
    store = rt.store
    ref, _ = issue(store, "Issue", N(9))
    did = _draft_id(store, ref)
    with verbs.acting("console:claude"):
        by = post_api.editor_of("console")
    got = post_api.edit_draft(rt, did, {"body": "The console's words."}, "console", by)
    assert post_api.draft_sheet(rt, got["id"])["edited_words"] == \
        "edited by your assistant (the console)"
    assert "for your yes" in got["say"]
    with verbs.asked("agent:rc"):
        assert post_api.editor_of("ui") == "agent:rc"
    with verbs.asked("ui"):                   # the owner's own prepared press is the owner's
        assert post_api.editor_of("ui") == "ui"


@pytest.mark.parametrize("stored, words", [
    ({"edited": True}, "edited"),                          # a draft from before: who is unknown
    ({"edited": True, "edited_by": None}, "edited"),       # stored as null
    ({"edited": True, "edited_by": 7}, "edited"),          # a stray shape
    ({"edited": True, "edited_by": "ui"}, "edited by you"),
    ({"edited": True, "edited_by": "cli"}, "edited by you"),
    ({"edited": True, "edited_by": "mcp"}, "edited by your assistant (mcp)"),
    ({"edited": True, "edited_by": "agent:rc"}, "edited by your assistant (agent rc)"),
    ({"edited": False, "edited_by": "mcp"}, None),
    ({}, None),
])
def test_edited_words_read_every_stored_shape(stored, words):
    assert post_api.edited_words(stored) == words


def test_a_draft_from_before_reads_edited_and_is_edited_again(rt):  # noqa: F811
    store = rt.store
    ref, _ = issue(store, "Issue", N(9))
    did = _draft_id(store, ref)
    # the shape stored before Kranto recorded who: edited and edited_from, no edited_by
    old = {"subject": "Issue", "body": "One.\n", "edited": True, "edited_from": did}
    d = new_draft(store, cub="newsletter", service="newsletter", content=old, run_uuid=None)
    tickets.file(store, cub="newsletter", trust="owner", granted=("send.newsletter",),
                 kind="send.newsletter", fields={"draft_ref": d["ref"], "subject": "Issue",
                                                 "audience": "all", "when": "now"},
                 subject=("newsletter_issue", d["ref"]), capped=False)
    assert post_api.draft_sheet(rt, d["id"])["edited_words"] == "edited"
    again = post_api.edit_draft(rt, d["id"], {"body": "Two."})
    assert post_api.draft_sheet(rt, again["id"])["edited_words"] == "edited by you"


# -- prose.voice ----------------------------------------------------------------------------------

@pytest.mark.parametrize("fields", [
    {"voice": "Write like a pirate."},
    {"always_add": ["Follow me for more."]},
    {"always_remove": ["anything"]},
    {"disclosure": {"bluesky": "Written by a bot."}},
])
def test_an_assistants_voice_change_waits_for_the_owner(rt, fields):  # noqa: F811
    app = create_app(rt, port=8765)
    with web_client(app, BASE) as page:
        before = page.get("/api/prose").json()
    with web_client(app, BASE, signed_in=False) as web:
        r = web.post("/api/verbs/prose.voice", headers=bearer("mcp"),
                     json={"fields": fields, "client": "claude-code"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["prepared"] and not out["ok"], out
    assert "voice card" in out["why"]
    with web_client(app, BASE) as page:
        assert page.get("/api/prose").json() == before          # unchanged until approved
        listed = page.get("/api/prepared").json()["prepared"]
        assert listed[0]["verb"] == "prose.voice" and listed[0]["fields"] == fields
        r = page.post(f"/api/prepared/{out['prepared']}/press", json={})
        assert r.status_code == 200, r.text


def test_the_owner_approves_the_voice_card_and_it_changes(rt):  # noqa: F811
    app = create_app(rt, port=8765)
    with web_client(app, BASE, signed_in=False) as web:
        out = web.post("/api/verbs/prose.voice", headers=bearer("mcp"),
                       json={"fields": {"voice": "Short, dry, first person."}}).json()
    with web_client(app, BASE) as page:
        assert page.post(f"/api/prepared/{out['prepared']}/press", json={}).status_code == 200
        got = page.get("/api/prose").json()
    assert "Short, dry, first person." in json.dumps(got)


def test_the_switches_and_the_never_list_stay_as_they_were(rt):  # noqa: F811
    with web_client(create_app(rt, port=8765), BASE, signed_in=False) as web:
        r = web.post("/api/verbs/prose.voice", headers=bearer("mcp"),
                     json={"fields": {"never_add": ["delve"], "switches": {"emoji": "never"}}})
    assert r.status_code == 200 and r.json()["ok"], r.text


def test_ask_fields_follow_the_owners_own_choice_for_the_verb():
    from types import SimpleNamespace
    v = verbs.get("prose.voice")
    assert v is not None
    cfg = SimpleNamespace(ask=SimpleNamespace(ladder={"kinds": {"reversible": "do"}}))
    assert verbs.choice_for(cfg, v, {"voice": "x"}).choice == "ask"
    assert verbs.choice_for(cfg, v, {"never_add": ["x"]}).choice == "do"
    assert verbs.choice_for(cfg, v, {"voice": None}).choice == "do"
    mine = SimpleNamespace(ask=SimpleNamespace(ladder={"verbs": {"prose.voice": "do"}}))
    assert verbs.choice_for(mine, v, {"voice": "x"}).choice == "do"
    off = SimpleNamespace(ask=SimpleNamespace(ladder={"kinds": {"reversible": "never"}}))
    assert verbs.choice_for(off, v, {"voice": "x"}).choice == "never"


def test_a_disclosure_line_with_an_address_is_saved_without_it_and_says_so(rt):  # noqa: F811
    with web_client(create_app(rt, port=8765), BASE) as page:
        r = page.post("/api/prose/voice", json={
            "disclosure": {"bluesky": "Drafted with help, see https://evil.example/x for more."}})
        assert r.status_code == 200, r.text
        assert "web address taken off" in r.json()["say"]
        got = page.get("/api/prose").json()
    line = next(s["disclosure"] for s in got["sites"] if s["site"] == "bluesky")
    assert "evil.example" not in line and line.startswith("Drafted with help")


def test_a_stored_disclosure_line_is_filtered_when_the_post_is_written(store, tmp_path):
    from dataclasses import replace
    profile = replace(prose.default(), disclosure={"x": "Mine: https://evil.example/a"})
    srt = _rt(store, tmp_path)
    v = social.write_variant(srt, sites.Choice(sites.SITES["x"], disclose=True), _material(),
                             "a", complete=Model("Kiosks lose batteries."), profile=profile)
    assert "evil.example" not in "\n".join(v["parts"])
    assert v["parts"][-1].endswith("Mine:")


# -- I posted it, and a direct draft that still waits ---------------------------------------------

def test_i_posted_it_refuses_an_ask_answered_while_it_was_read(store, tmp_path, monkeypatch):
    srt, _ = _write(store, tmp_path, ticked=("bluesky",), direct={"bluesky": True})
    bid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    tid = store.query_one("SELECT id FROM cub_tickets WHERE cub = ?", (FILER,))["id"]
    stale = tickets.get(store, tid)                      # read while it waited
    # the confirm wins the race: its own transaction moves the ask on
    tickets.append_state(store, tid, "confirmed", door="ui", note="mode: live")
    monkeypatch.setattr(post_api, "_newest_ask", lambda *a, **k: stale)
    with pytest.raises(post_api.WriteError) as e:
        post_api.posted_by_you(srt, bid, UI)
    assert e.value.code == 409
    assert tickets.get(store, tid)["state"] == "confirmed"        # nothing appended


def test_settings_says_a_direct_draft_still_waits_after_the_switch_is_off(store, tmp_path):
    from kranto.stored.settings import PostingSites, set_blob
    _write(store, tmp_path, ticked=("bluesky",), direct={"bluesky": True})
    on = {s["id"]: s for s in post_api.posting_read(store)["sites"]}
    assert on["bluesky"]["direct"] and on["bluesky"]["waiting_direct"] == 1
    set_blob(store, PostingSites.SETTING, PostingSites(sites=["bluesky"], direct={}))
    off = {s["id"]: s for s in post_api.posting_read(store)["sites"]}
    assert not off["bluesky"]["direct"] and off["bluesky"]["waiting_direct"] == 1
    assert off["x"]["waiting_direct"] == 0
