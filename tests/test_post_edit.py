"""Editing a draft in the page (the verb ``post.edit``) and a draft's sources
read as outlets.

An edit is never a change in place: the owner's words are filed as the next draft of the series
(a new ``cub_drafts`` row with ``edited`` and ``edited_from``), the old ask is closed "replaced
by #<ticket>" and a new ask waits with the new words. A press still refuses a draft whose words
differ from what was shown, so the old draft can no longer be sent by mistake.
"""

from __future__ import annotations

import json

from kranto.core import tickets, verbs
from kranto.core.cubs.brokers.base import new_draft, press_draft
from kranto.web import post_api
from kranto.web import types as T
from kranto.web.app import create_app

from .conftest import web_client
from .test_post_api import N, issue
from .test_web import rt  # noqa: F401 - fixture
from .test_web_types import problems


def _toot(store, text: str) -> tuple[dict, int]:
    tickets.kind_names()
    d = new_draft(store, cub="toot", service="mastodon", content={"text": text}, run_uuid=None)
    tid = tickets.file(store, cub="toot", trust="owner", granted=("post.mastodon",),
                       kind="post.mastodon",
                       fields={"draft_ref": d["ref"], "text": text, "visibility": "public",
                               "language": "en"}, subject=("card", "143"))
    return d, tid


def test_saving_files_the_owners_words_as_the_next_draft(rt):  # noqa: F811
    store = rt.store
    ref, tid = issue(store, "Monday's issue", N(9))
    old = store.query_one("SELECT * FROM cub_drafts WHERE ref = ?", (ref,))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        sheet = client.get(f"/api/post/d/{old['id']}").json()
        assert problems(sheet, T.PostSheet) == []
        assert sheet["can_edit"] and sheet["edit"]["title"] == "Monday's issue"
        assert sheet["edit"]["body"].startswith("Intro.") and not sheet["edited"]
        assert sheet["original_draft"] == old["id"] and sheet["limit"] is None
        r = client.post(f"/api/post/d/{old['id']}/edit",
                        json={"title": "Monday, edited", "body": "My own intro.\n\nThe rest."})
        assert r.status_code == 200, r.text
        got = r.json()
        assert problems(got, T.PostEdited) == []
        assert got["withdrew"] and "withdrawn" in got["say"]
        new = client.get(f"/api/post/d/{got['id']}").json()
    assert new["edited"] and new["edited_from"] == old["id"] and new["original_draft"] == old["id"]
    assert new["title"] == "Monday, edited" and new["group"] == "waiting"
    assert new["markdown"] == "# Monday, edited\n\nMy own intro.\n\nThe rest.\n"
    content = json.loads(store.query_one("SELECT content FROM cub_drafts WHERE id = ?",
                                         (got["id"],))["content"])
    assert content["edited"] is True and content["edited_from"] == old["id"]
    # the old ask is closed as replaced; the new one names the new draft and its words
    before = tickets.get(store, tid)
    assert before["state"] == "expired" and before["note"] == f"replaced by #{got['ticket']}"
    after = tickets.get(store, got["ticket"])
    assert after["state"] == tickets.OPEN and after["fields"]["draft_ref"] == got["ref"]
    assert after["fields"]["subject"] == "Monday, edited" and after["fields"]["when"] == "now"
    assert after["history"][0]["note"] == "edited by you"
    # the original draft is unchanged and in Earlier; the edited one is sendable as shown
    assert store.query_one("SELECT content FROM cub_drafts WHERE id = ?",
                           (old["id"],))["content"] == old["content"]
    rows = post_api.post_read(rt)
    assert [d["id"] for d in rows["drafts"]] == [got["id"]]
    assert old["id"] in [d["id"] for d in rows["earlier"]]
    assert not isinstance(press_draft(store, after, ("newsletter",), ("subject",)), str)


def test_an_edit_of_an_edit_keeps_original_version_and_start_again(rt):  # noqa: F811
    store = rt.store
    ref, _ = issue(store, "Issue", N(9))
    first = store.query_one("SELECT id FROM cub_drafts WHERE ref = ?", (ref,))["id"]
    a = post_api.edit_draft(rt, first, {"body": "One."})
    b = post_api.edit_draft(rt, a["id"], {"body": "Two."})
    sheet = post_api.draft_sheet(rt, b["id"])
    assert sheet["edited_from"] == a["id"] and sheet["original_draft"] == first
    # Start again from the original: an edit with its words
    orig = post_api.draft_sheet(rt, first)["edit"]
    c = post_api.edit_draft(rt, b["id"], {"title": orig["title"], "body": orig["body"]})
    assert post_api.draft_sheet(rt, c["id"])["markdown"].startswith("# Issue\n\nIntro.")


def test_a_short_post_is_one_part_within_its_limit(rt):  # noqa: F811
    store = rt.store
    d, tid = _toot(store, "A toot.")
    sheet = post_api.draft_sheet(rt, d["id"])
    assert sheet["edit"] == {"title": None, "parts": [{"text": "A toot."}]}
    assert sheet["limit"] == {"max": 500, "unit": "characters"}
    try:
        post_api.edit_draft(rt, d["id"], {"parts": [{"text": "x" * 501}]})
        raise AssertionError("past the limit was saved")
    except post_api.WriteError as exc:
        assert exc.code == 400 and "501 characters" in exc.words
    for bad in ({"title": "No title here"}, {"parts": [{"text": "a"}, {"text": "b"}]},
                {"parts": [{"text": "  "}]}, {}, {"drop": "poll"}):
        try:
            post_api.edit_draft(rt, d["id"], bad)
            raise AssertionError(f"{bad} was saved")
        except post_api.WriteError as exc:
            assert exc.code == 400
    got = post_api.edit_draft(rt, d["id"], {"parts": [{"text": "My toot."}]})
    t = tickets.get(store, got["ticket"])
    assert t["fields"]["text"] == "My toot." and t["kind"] == "post.mastodon"
    assert tickets.get(store, tid)["state"] == "expired"


def test_only_a_waiting_draft_can_be_edited(rt):  # noqa: F811
    store = rt.store
    ref, tid = issue(store, "Sent issue", N(9))
    tickets.append_state(store, tid, "confirmed", door="ui", note="mode: live")
    did = store.query_one("SELECT id FROM cub_drafts WHERE ref = ?", (ref,))["id"]
    assert post_api.draft_sheet(rt, did)["cannot_edit"] == "This draft is being sent."
    tickets.append_state(store, tid, "done", door="ui", note="sent")
    sheet = post_api.draft_sheet(rt, did)
    assert not sheet["can_edit"] and sheet["cannot_edit"].startswith("Only a draft that waits")
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post(f"/api/post/d/{did}/edit", json={"body": "x"})
        assert r.status_code == 409
        assert client.post("/api/post/d/999/edit", json={"body": "x"}).status_code == 404
    n = store.query_one("SELECT COUNT(*) AS n FROM cub_drafts")["n"]
    assert n == 1                                    # a refused edit files nothing


def test_edits_do_not_count_against_the_cubs_daily_cap(rt):  # noqa: F811
    store = rt.store
    d, _ = _toot(store, "Toot 0.")
    for i in range(1, 8):                            # post.mastodon allows 5 asks a day
        d = {"id": post_api.edit_draft(rt, d["id"], {"parts": [{"text": f"Toot {i}."}]})["id"]}
    assert post_api.draft_sheet(rt, d["id"])["edit"]["parts"] == [{"text": "Toot 7."}]


def test_post_edit_is_an_outward_core_verb():
    v = next(v for v in verbs.CORE if v.kind == "post.edit")
    assert v.ladder == "outward" and v.method == "POST"
    assert v.path == "/api/post/d/{id:int}/edit" and v.subject == "draft"
    card = next(v for v in verbs.CORE if v.kind == "theme.card")
    assert {f.name for f in card.fields} == {"hint", "story"}


def test_a_drafts_machine_labels_read_as_outlets():
    body = ("**Robots**\nA thing happened.\n[obs 12825](https://www.therobotreport.com/a) · "
            "[exa 3](https://news.ycombinator.com/item?id=1) · [obs 12826](https://www."
            "therobotreport.com/a)\nAnd more (obs 12, exa 4). Web 2 and gh 2 stay.")
    out = post_api.relabel(body)
    assert "[therobotreport.com](https://www.therobotreport.com/a)" in out
    assert "[Hacker News](https://news.ycombinator.com/item?id=1)" in out
    assert out.count("therobotreport.com/a") == 1          # one address written once
    assert "(your library)" in out and "Web 2 and gh 2 stay." in out
    assert "obs 1" not in out and "exa " not in out and "· ·" not in out
    md = post_api.markdown_of({"subject": "S", "body": body})
    assert "obs 12825" not in md
