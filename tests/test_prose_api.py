"""``/api/prose/*`` and the three verbs (``prose.check``, ``prose.voice``,
``prose.learn``) under the ladder; ``post.write`` carries the owner's take."""

from __future__ import annotations

import json

from kranto.core import verbs
from kranto.web import post_api
from kranto.web.app import create_app

from .conftest import chat_response, web_client
from .test_web import rt  # noqa: F401 - fixture

AI = "Here's the thing: this tool is a game-changer. Let that sink in."


def test_the_four_verbs_are_in_the_table_with_their_ladder():
    got = {v.kind: v for v in verbs.CORE if v.kind.startswith("prose.")}
    assert set(got) == {"prose.check", "prose.voice", "prose.learn", "prose.writer_key"}
    assert got["prose.check"].ladder == "read"
    # the OpenAI key a writer's own model uses: pasted on the page only, never by an assistant
    assert got["prose.writer_key"].ladder == "credential"
    assert got["prose.writer_key"].doors == verbs.PAGE_ONLY
    assert got["prose.voice"].ladder == "reversible" and got["prose.learn"].ladder == "reversible"
    assert {f.name for f in next(v for v in verbs.CORE if v.kind == "post.write").fields} \
        >= {"about", "as", "take"}


def test_read_check_voice_and_learn(rt):  # noqa: F811
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        got = client.get("/api/prose").json()
        assert got["voice"] == "" and got["strictness"] == "light" and got["take"] is True
        assert {r["id"] for r in got["rules"]} >= {"shape.not_x_but_y", "rhythm.dashes"}
        assert any(g["name"] == "floor" and g["always"] for g in got["guides"])
        assert next(s for s in got["sites"] if s["site"] == "bluesky")["limits"]["max_chars"] \
            == 300
        r = client.post("/api/prose/check", json={"text": AI, "site": "mastodon"})
        flags = r.json()["flags"]
        assert r.status_code == 200 and {"shape.runup", "shape.closer", "words.floor"} <= \
            {f["rule"] for f in flags}
        assert client.post("/api/prose/check", json={"text": ""}).status_code == 400
        r = client.post("/api/prose/voice", json={"voice": "Short. Dry.",
                                                  "never_add": ["synergy"],
                                                  "rules_off": ["shape.runup"]})
        assert r.status_code == 200 and r.json()["ok"]
        assert client.post("/api/prose/voice", json={"strictness": "max"}).status_code == 400
        after = client.get("/api/prose").json()
        assert after["voice"] == "Short. Dry." and after["never"] == ["synergy"]
        assert "shape.runup" not in {f["rule"] for f in client.post(
            "/api/prose/check", json={"text": AI}).json()["flags"]}
        r = client.post("/api/prose/learn", json={"draft": "A pivotal week.",
                                                  "sent": "A busy week."})
        [prop] = r.json()["proposals"]
        assert prop["kind"] == "never" and prop["entry"] == "pivotal"
        assert client.get("/api/prose").json()["proposals"][0]["id"] == prop["id"]
        r = client.post("/api/prose/learn", json={"proposal": prop["id"], "answer": "yes"})
        assert r.status_code == 200 and "pivotal" in client.get("/api/prose").json()["never"]
        assert client.post("/api/prose/learn", json={"proposal": "x", "answer": "yes"}
                           ).status_code == 404


def test_the_verbs_door_runs_them_for_an_assistant(rt):  # noqa: F811
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/verbs/prose.check", json={"fields": {"text": AI}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] and body["verb"] == "prose.check"
        assert {"shape.runup", "shape.closer"} <= {f["rule"] for f in body["answer"]["flags"]}


def test_fix_and_the_voice_card_draft_call_the_model_and_store_nothing(rt):  # noqa: F811
    def model(body):
        system = body["messages"][0]["content"]
        if "edit a draft post" in system:
            return chat_response(json.dumps({"edits": [{"id": i, "text": ""} for i in
                                                       range(1, 6)]}))
        return chat_response("Sentences: short, 8 words on average.")
    rt.llm.fake.handler = model
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/prose/revise", json={"text": AI})
        assert r.status_code == 200 and r.json()["rounds"] >= 1
        assert "Let that sink in" not in r.json()["text"]
        r = client.post("/api/prose/voice/draft", json={"samples": ["I write short things. "
                                                                    "Very short ones."]})
        assert r.status_code == 200 and r.json()["voice"].startswith("Sentences:")
        assert client.get("/api/prose").json()["voice"] == ""        # nothing saved
        assert client.post("/api/prose/revise", json={"text": "A plain line."}
                           ).json()["rounds"] == 0


def test_post_write_carries_the_take_as_the_angle():
    # round 1's take is the angle's alias: the writer gets it as the angle
    assert post_api.plan_write("card:7", "blog", "Good, but late.")[3] == {
        "card": 7, "angle": "Good, but late."}
    assert post_api.plan_write("card:7", "blog", "old", "Mine wins.")[3]["angle"] == "Mine wins."
    assert post_api.plan_write("card:7", "toot", "  ")[3] == {"idea": "7"}
    try:
        post_api.plan_write("card:7", "blog", "x" * 601)
    except post_api.WriteError as exc:
        assert "600" in exc.words
    else:
        raise AssertionError("a long take is refused")


def test_the_voice_card_draft_says_claude_code_is_missing_in_words(rt, monkeypatch):  # noqa: F811
    """Show my voice card on an install whose Claude Code is gone answered with the raw error."""
    from kranto.web import prose_api

    def complete(rt_, purpose, max_tokens):
        def call(messages, schema):
            raise RuntimeError("Claude Code: Claude Code is not installed (no claude on PATH)")
        return call
    monkeypatch.setattr(prose_api, "_complete", complete)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/prose/voice/draft", json={"samples": ["I write short things. "
                                                                    "Very short ones."]})
        assert r.status_code == 502
        assert r.json()["error"].startswith("Claude Code is not installed on this machine.")
