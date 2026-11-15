""" (rule 4, P-9 to P-11): the angle step and the writer's own
model. ``angles`` gives three distinct sentences (a claim, a prediction, a question) and never an
invented experience; ``POST /api/post/angles`` answers them for a card and stores nothing; the
writer's model is its own setting, used for that writer's calls and nobody else's."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from kranto import prose
from kranto.core.cubs import host as cub_host
from kranto.prose import profile as profile_mod
from kranto.prose.angles import SCHEMA, AnglesError, parse
from kranto.prose.profile import Profile
from kranto.web.app import create_app

from .conftest import chat_response, web_client
from .test_post_write import card
from .test_web import rt  # noqa: F401 - fixture

THREE = {"claim": "Robot data is now a national asset, and China just said so.",
         "prediction": "More robotics deals will be blocked over data within a year.",
         "question": "Would you sell a company whose robots see inside every factory"}


def test_three_distinct_angles_a_claim_a_prediction_and_a_question():
    seen = []

    def complete(messages, schema):
        seen.append((messages, schema))
        return {"text": json.dumps(THREE), "structured": None}

    got = prose.angles({"title": "China blocks a robotics deal", "facts": "ABB confirmed."},
                       Profile(voice="Short sentences. Dry."), complete=complete)
    assert [a["kind"] for a in got] == ["claim", "prediction", "question"]
    assert len({a["text"] for a in got}) == 3
    assert got[2]["text"].endswith("?")                     # a question reads as one
    (msgs, schema), = seen
    assert schema == SCHEMA
    assert "Short sentences. Dry." in msgs[0]["content"]      # the person's voice card
    assert "never write as if the person tried" in msgs[0]["content"]
    assert "China blocks a robotics deal" in msgs[1]["content"]


@pytest.mark.parametrize("bad", [
    {**THREE, "prediction": THREE["claim"]},                                # not distinct
    {**THREE, "question": ""},                                              # missing
    {**THREE, "claim": "I tried their arm at my company and it leaked."},   # an experience
])
def test_angles_that_repeat_are_missing_or_tell_an_experience_are_refused(bad):
    with pytest.raises(AnglesError):
        parse({"structured": bad})


def test_one_sentence_each_at_most_thirty_five_words():
    long = {**THREE, "claim": "This is the claim. And a second sentence that should go."}
    assert parse({"structured": long})[0]["text"] == "This is the claim."


def _angle_model(seen: list):
    def model(body):
        seen.append(body)
        return chat_response(json.dumps(THREE))
    return model


def test_the_angles_route_answers_three_for_a_card_and_stores_nothing(rt):  # noqa: F811
    seen: list = []
    rt.llm.fake.handler = _angle_model(seen)
    n = card(rt)
    prose.load(rt.cfg, rt.store)            # the one-time tone migration writes its mark first
    before = rt.store.query_one("SELECT COUNT(*) AS n FROM settings")["n"]
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/post/angles", json={"about": f"card:{n}"})
        assert r.status_code == 200, r.text
        got = r.json()
        assert [a["kind"] for a in got["angles"]] == ["claim", "prediction", "question"]
        assert got["about"] == f"card:{n}" and got["as"] == "blog"
        assert "Battery swap ledger" in seen[0]["messages"][-1]["content"]
        # a week has no one subject to take an angle on; an unknown card is said
        assert client.post("/api/post/angles", json={"about": "week"}).status_code == 400
        assert client.post("/api/post/angles", json={"about": "card:99999"}).status_code == 404
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM settings")["n"] == before


def test_the_angles_route_with_no_key_says_type_your_own(rt, monkeypatch):  # noqa: F811
    monkeypatch.setattr(type(rt.llm), "has_key", property(lambda self: False))
    n = card(rt)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/post/angles", json={"about": f"card:{n}"})
    assert r.status_code == 409 and "type your own sentence" in r.json()["error"]


def test_the_writers_model_is_its_own_setting(rt):  # noqa: F811
    p = prose.load(rt.cfg, rt.store)
    assert p.writer_model("blog") is None                    # no default chosen (P-11)
    out = profile_mod.change(rt.cfg, rt.store, {"writer_model": {
        "blog": {"provider": "openrouter", "model": "google/gemini-x"}}})
    assert out["ok"] and "the writer's model" in out["changed"]
    p = prose.load(rt.cfg, rt.store)
    assert p.writer_model("blog") == {"provider": "openrouter", "model": "google/gemini-x"}
    assert p.writer_model("toot") is None
    for bad in ({"blog": {"provider": "nobody", "model": "x"}}, {"linkedin": None},
                {"blog": {"provider": "openrouter", "model": ""}}, ["blog"]):
        with pytest.raises(profile_mod.ProfileError):
            profile_mod.change(rt.cfg, rt.store, {"writer_model": bad})
    profile_mod.change(rt.cfg, rt.store, {"writer_model": {"blog": None}})
    assert prose.load(rt.cfg, rt.store).writer_model("blog") is None


@pytest.mark.parametrize("stored", [None, [], {"blog": None}, {"blog": "gpt"},
                                    {"blog": {"provider": "openrouter"}},
                                    {"nobody": {"provider": "openrouter", "model": "m"}}])
def test_a_stored_writers_value_of_any_shape_reads_as_unset(stored):
    assert profile_mod.clean_writers(stored) == {}


def test_the_angles_route_uses_the_writers_model(rt):  # noqa: F811
    seen: list = []
    rt.llm.fake.handler = _angle_model(seen)
    profile_mod.change(rt.cfg, rt.store, {"writer_model": {
        "toot": {"provider": rt.cfg.llm.provider_name, "model": "another/model"}}})
    n = card(rt)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        assert client.post("/api/post/angles", json={"about": f"card:{n}"}).status_code == 200
        assert client.post("/api/post/angles",
                           json={"about": f"card:{n}", "as": "toot"}).status_code == 200
    assert seen[0]["model"] != "another/model" and seen[1]["model"] == "another/model"


def test_a_writer_cubs_model_calls_go_to_its_own_model(store, monkeypatch):
    profile_mod.save_row(store, replace(profile_mod.ProfileRow(), writers={
        "blog": {"provider": "anthropic", "model": "claude-x"}}))
    asked: list[dict] = []

    def complete(**kw):
        asked.append(kw)
        return SimpleNamespace(text="ok", structured=None, model=kw.get("model") or "tier",
                               prompt_tokens=1, completion_tokens=1, cost_usd=0.0,
                               equiv_usd=None, call_id=1)

    monkeypatch.setattr(cub_host.CubHost, "store", store)
    monkeypatch.setattr(cub_host.api, "spend_of", lambda store, f: {"month_usd": 0.0})
    for cid, want in (("blog", "claude-x"), ("toot", None), ("someone", None)):
        h = cub_host.CubHost.__new__(cub_host.CubHost)
        h.rt = SimpleNamespace(llm=SimpleNamespace(complete=complete))
        h.cub = SimpleNamespace(id=cid, version="1", feature=cid)
        h.run_uuid = None
        h.runtime = SimpleNamespace(cap_usd=lambda cub: None)
        monkeypatch.setattr(h, "_grant", lambda *a, **k: None, raising=False)
        monkeypatch.setattr(h, "_per_hour", lambda *a, **k: None, raising=False)
        h._m_model_complete({"purpose": "blog_post", "tier": "reason",
                             "messages": [{"role": "user", "content": "hi"}]})
        assert asked[-1].get("model") == want, cid
        assert asked[-1].get("provider") == ("anthropic" if want else None)
