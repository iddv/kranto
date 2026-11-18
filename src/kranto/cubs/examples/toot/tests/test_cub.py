"""The toot cub against FakeHost (the eleven)."""
from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bears_cub import HostError, NotConnected
from bears_cub.schema import ManifestError
from bears_cub.testing import FakeHost

HERE = Path(__file__).resolve().parent.parent
MORNING = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
CAPTION = "A tool that reads its own logs and says when it is lost."


@pytest.fixture
def host() -> FakeHost:
    h = FakeHost.from_folder(HERE, now=MORNING)
    h.library.add_topic(1, "Robotics")
    h.model.reply("toot_caption", structured={"text": CAPTION})
    return h


def nominee(h: FakeHost, ident: int = 7, **kw) -> dict:
    h.library.add_observation(70, 1, "An observation")
    return h.library.add_idea(ident, "Self-aware logs", "Logs that notice when a run is lost.",
                              evidence_ids=[70], editor_class="nominee", **kw)


def test_no_nominee_skips(host):
    host.library.add_idea(3, "A candidate only", editor_class="candidate")
    out = host.run_job("draft_pick", strict=True)
    assert out["status"] == "skipped" and not host.tickets and not host.model.calls


def test_one_nominee_files_one_ticket_whose_text_is_the_drafts(host):
    nominee(host)
    out = host.run_job("draft_pick", strict=True)
    assert out["status"] == "ok" and out["summary"]["idea"] == 7
    [t], [d] = host.tickets, host.drafts
    assert t["kind"] == "post.mastodon" and t["fields"]["text"] == d["content"]["text"] == CAPTION
    assert len(t["fields"]["text"]) <= 500
    assert t["because"] == {"ideas": [7], "observations": [70]}
    assert "account" not in t["fields"]


def test_a_pick_the_loop_already_built_is_skipped(host):
    nominee(host, built={"state": "public", "repo": "jo-example/logs", "url": "https://x/logs"})
    out = host.run_job("draft_pick", strict=True)
    assert out["status"] == "skipped" and not host.tickets and not host.model.calls


def test_the_same_nominee_the_next_day_skips(host):
    nominee(host)
    host.run_job("draft_pick", strict=True)
    host.advance(days=1)
    out = host.run_job("draft_pick", strict=True)
    assert out["status"] == "skipped" and len(host.tickets) == 1


def test_a_pick_the_model_failed_on_is_tried_again(host):
    nominee(host)
    host.model.spent_usd = 1.0                     # the $1 cap, spent: the caption fails
    assert host.run_job("draft_pick")["status"] == "failed" and not host.tickets
    host.model.spent_usd = 0.0
    host.advance(days=1)
    assert host.run_job("draft_pick", strict=True)["status"] == "ok" and len(host.tickets) == 1


def test_a_long_caption_is_cut_at_the_limit_and_the_host_refuses_past_it(host):
    nominee(host)
    host.model.reply("toot_caption", structured={"text": "word " * 200})
    host.run_job("draft_pick", strict=True)
    assert len(host.tickets[0]["fields"]["text"]) <= 500
    with pytest.raises(HostError) as got:              # what the cub's own cut prevents
        host.handle("broker.call", {"service": "mastodon", "op": "statuses.draft",
                                    "args": {"text": "x" * 501}})
    assert got.value.code == -32005


def test_the_planted_instruction_reaches_the_text_only(host):
    planted = host.fixtures.planted_instruction(topic_id=1)
    host.model.reply("toot_caption", fn=lambda messages, schema: {
        "text": messages[-1]["content"]})              # a model that echoes what it read
    host.run_job("draft_pick", strict=True)
    [t] = host.tickets
    assert t["kind"] == "post.mastodon" and set(t["because"]) == {"ideas", "observations"}
    assert all(isinstance(i, int) for i in t["because"]["ideas"] + t["because"]["observations"])
    assert planted not in str(t["because"]) and t["fields"]["visibility"] == "public"
    assert "<<<about" in host.model.calls[0]["messages"][-1]["content"]      # fenced, as data


def test_not_connected_the_limit_is_500(host):
    with pytest.raises(NotConnected):
        host.handle("broker.call", {"service": "mastodon", "op": "instance.limits", "args": {}})
    nominee(host)
    host.run_job("draft_pick", strict=True)
    system = host.model.calls[0]["messages"][0]["content"]
    assert "at most 280 characters" in system
    host.broker("mastodon").connected = True
    host.broker("mastodon").max_characters = 200
    before = len(host.model.calls)
    host.act("draft_card", {"idea": "7"}, strict=True)
    # the writing call (a fix of a flagged line may follow it)
    assert "at most 200 characters" in host.model.calls[before]["messages"][0]["content"]


def test_draft_card_with_link_appends_the_cards_url(host):
    nominee(host, url="https://example.com/ideas/7")
    host.act("draft_card", {"idea": "7", "link": True}, strict=True)
    assert host.tickets[0]["fields"]["text"].endswith("\n\nhttps://example.com/ideas/7")
    host.act("draft_card", {"idea": "7", "tone": "playful"}, strict=True)
    assert "https://" not in host.tickets[1]["fields"]["text"]


def test_redraft_withdraws_and_files_again(host):
    nominee(host)
    host.run_job("draft_pick", strict=True)
    ref = host.tickets[0]["fields"]["draft_ref"]
    out = host.act("redraft", {"tone": "playful"}, subject={"kind": "toot_post", "id": ref},
                   strict=True)
    assert out["ok"] and [t["state"] for t in host.tickets] == ["expired", "needs_confirm"]
    assert host.read("count") == {"count": 1}


@pytest.mark.parametrize("state, group", [("done", "posted"), ("dry", "practiced"),
                                          ("expired", "closed")])
def test_on_resolved_moves_the_post(host, state, group):
    nominee(host)
    host.run_job("draft_pick", strict=True)
    host.resolve(host.tickets[0]["id"], state)
    posts = host.read("posts")
    assert len(posts[group]) == 1 and not posts["waiting"]
    assert host.read("rows") == {"rows": []}


def test_a_direct_post_is_refused(host):
    nominee(host)
    host.run_job("draft_pick", strict=True)
    d = host.drafts[0]
    with pytest.raises(HostError) as got:
        host.handle("ticket.file", {"kind": "post.mastodon", "fields": {
            "draft_ref": d["ref"], "text": CAPTION, "visibility": "direct", "language": "en"}})
    assert got.value.code == -32005


def test_asking_for_a_trade_fails_validation(tmp_path):
    """A mutation of ``requests``: a cub may never ask for Kranto's own trade instruction."""
    folder = tmp_path / "toot"
    shutil.copytree(HERE, folder, ignore=shutil.ignore_patterns("__pycache__"))
    text = (folder / "cub.yaml").read_text().replace("requests: [post.mastodon]",
                                                     "requests: [post.mastodon, trade.instruct]")
    (folder / "cub.yaml").write_text(text)
    with pytest.raises(ManifestError, match="trade.instruct"):
        FakeHost.from_folder(folder)


@pytest.mark.parametrize("answer, text", [
    ('{"text": "Clubs book by phone."}', "Clubs book by phone."),
    ('```json\n{"text": "Clubs book by phone."}\n```', "Clubs book by phone."),
    ("**Text:** Clubs book by phone.", "Clubs book by phone."),
    ('"Clubs book by phone."', "Clubs book by phone."),
])
def test_a_caption_answered_as_text_is_read(host, answer, text):
    # fix 1: a provider that answers the schema's call as text
    nominee(host)
    host.model.reply("toot_caption", text=answer)
    host.act("draft_card", {"idea": "7"}, strict=True)
    assert host.tickets[0]["fields"]["text"] == text


def test_an_unreadable_caption_says_so(host):
    nominee(host)
    host.model.reply("toot_caption", text='{"caption": "a field never asked for"}')
    out = host.act("draft_card", {"idea": "7"}, strict=True)
    assert out["ok"] is False and "could not read" in out["say"] and not host.tickets


def test_the_take_leads_and_the_forms_tone_is_a_hint_through_the_prose_engine(host):
    # toot.tone moved into the voice card: the form's tone is a one-off hint
    nominee(host)
    host.prose.voice = "Tone: plain. Short sentences."
    host.act("draft_card", {"idea": "7", "tone": "playful", "angle": "Worth a try for clubs."},
             strict=True)
    msgs = host.model.calls[0]["messages"]
    assert "Tone: plain. Short sentences." in msgs[0]["content"]
    assert "# A Mastodon post" in msgs[0]["content"]
    assert "Worth a try for clubs." in msgs[-1]["content"]
    assert "This time: a playful tone." in msgs[-1]["content"]
    assert [c["method"] for c in host.prose.calls][:2] == ["compose", "check"]
    ref = host.tickets[0]["fields"]["draft_ref"]
    assert host.kv[f"post:{ref}"]["prose"]["score"] is not None
