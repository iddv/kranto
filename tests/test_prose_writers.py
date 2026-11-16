""" acceptance 5: the three writers use the engine, through the cub host. An old settings
file with ``blog.tone: "plain"`` migrates into the voice card, and the drafts still write (the
real blog cub, in its sandbox, against a fake model transport)."""

from __future__ import annotations

import json

from bears_cub import grants
from kranto.core import tickets
from kranto.web import post_api

from .conftest import chat_response
from .cubhelp import needs_bwrap
from .test_examples_install import home  # noqa: F401 - fixture
from .test_post_write import POST_JSON, card
from .test_web import rt  # noqa: F401 - fixture


def test_prose_is_granted_with_the_model_and_revise_under_its_purpose():
    writer = {"model": {"purposes": ["blog_post"], "tiers": ["reason"]}}
    assert grants.allow(writer, "prose.compose", {"material": {}}) is None
    assert grants.allow(writer, "prose.check", {"text": "x"}) is None
    assert grants.allow(writer, "prose.revise", {"text": "x", "purpose": "blog_post",
                                                 "tier": "reason"}) is None
    assert grants.allow(writer, "prose.revise", {"text": "x", "purpose": "other",
                                                 "tier": "reason"})[0] == -32001
    assert grants.allow({"model": {}}, "prose.compose", {"material": {}})[0] == -32001


@needs_bwrap
def test_an_old_tone_setting_reaches_the_voice_card_and_the_draft_still_writes(home):  # noqa: F811
    path = home.cfg.root / "kranto.yaml"
    path.write_text(path.read_text() + "\nblog:\n  tone: plain\n")
    seen: list[list[dict]] = []

    def model(body: dict):
        seen.append(body["messages"])
        system = body["messages"][0]["content"]
        if "edit a draft post" in system:          # a revise round: nothing to change
            return chat_response(json.dumps({"edits": []}))
        return chat_response(json.dumps(POST_JSON))

    home.llm.fake.handler = model
    n = card(home)
    out = post_api.write(home, f"card:{n}", "blog", door="ui")
    assert out["cub"] == "blog" and "waits on Post" in out["say"]
    # the tone is now the voice card's first line, and the writer's prompt carries it
    voice = (home.cfg.root / "prose" / "voice.md").read_text()
    assert voice.splitlines()[0] == "Tone: plain."
    system = seen[0][0]["content"]
    assert "# The person's voice card" in system and "Tone: plain." in system
    assert "# The floor" in system and "# A blog post" in system
    # the old one-line tone sentence is gone
    assert "the tone is plain" not in system
    [t] = tickets.listing(home.store, cub="blog")
    assert t["kind"] == "draft.sanity" and t["state"] == tickets.OPEN
    [d] = post_api.post_read(home)["drafts"]
    assert d["title"] == POST_JSON["title"]
    # the host recorded the engine's calls as the cub's
    ops = {r["op"] for r in home.store.query(
        "SELECT op FROM cub_calls WHERE cub = 'blog' AND service = 'prose'")}
    assert {"compose", "check"} <= ops


PROSE_REPLY = ("**Title:** Kiosks lose track of their batteries\n"
               "Excerpt: A ledger per kiosk would show where each battery went.\n\n"
               "## What happened\n\nKiosks swap batteries all day [1] and keep no record [2].")


@needs_bwrap
def test_a_reply_in_prose_still_writes_a_draft_and_nonsense_says_why(home):  # noqa: F811
    """ fix 1: a provider that answers the schema's call in prose ("Title: /
    Excerpt: / body", as the Claude Code login did) still gives a draft; an answer Kranto cannot
    read says so, not "the model wrote nothing"."""
    answers = iter([PROSE_REPLY, json.dumps({"headline": "A field the writer never asked for"})])

    def model(body: dict):
        if "edit a draft post" in body["messages"][0]["content"]:
            return chat_response(json.dumps({"edits": []}))
        return chat_response(next(answers))

    home.llm.fake.handler = model
    n = card(home)
    post_api.write(home, f"card:{n}", "blog", door="ui")
    [d] = post_api.post_read(home)["drafts"]
    assert d["title"] == "Kiosks lose track of their batteries"
    md = post_api.draft_sheet(home, d["id"])["markdown"]
    assert "Kiosks swap batteries all day" in md and "Title:" not in md
    assert "*A ledger per kiosk would show where each battery went.*" in md
    try:
        post_api.write(home, f"card:{n}", "blog", door="ui")
    except post_api.WriteError as exc:
        assert exc.words == ("No draft was written: The model answered in a form Kranto could "
                             "not read: try again.")
    else:
        raise AssertionError("an unreadable answer writes no draft")


@needs_bwrap
def test_the_products_own_write_flags_a_person_its_card_does_not_name(home):  # noqa: F811
    """salt.person through the cub host: the blog cub's polish step passes the card's words as
    the check's sources (SDK 1.4), so a draft naming someone the card does not is flagged."""
    named = {**POST_JSON, "body": "Kiosks swap batteries all day [1]. Ask Jane Stranger, who "
                                  "keeps no record [2]."}

    def model(body: dict):
        if "edit a draft post" in body["messages"][0]["content"]:
            return chat_response(json.dumps({"edits": []}))
        return chat_response(json.dumps(named))

    home.llm.fake.handler = model
    n = card(home)
    post_api.write(home, f"card:{n}", "blog", door="ui")
    rows = [json.loads(r["value"]) for r in home.store.query(
        "SELECT value FROM cub_kv WHERE cub = 'blog' AND key LIKE 'post:%'")]
    assert rows and "salt.person" in rows[0]["prose"]["left"]
