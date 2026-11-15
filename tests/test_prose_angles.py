""" (rule 4, P-9 to P-11; round 3): the angle step and the writer's
own model. ``angles`` gives three distinct sentences of round 3's kinds (where it leads, a bet, a
scene), each checked by a rule before it is shown: never an invented experience, never a stock
prediction, never a tool to build as the end of the line, never the item's own claim restated;
a refused proposal is asked for once more. ``POST /api/post/angles`` answers them for a card and
stores nothing; the writer's model is its own setting (OpenAI's API among its providers), used
for that writer's calls and nobody else's."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from kranto import prose
from kranto.core.cubs import host as cub_host
from kranto.prose import profile as profile_mod
from kranto.prose.angles import KINDS, OLD_KINDS, SCHEMA, WORDS, AnglesError, parse, problems
from kranto.prose.profile import Profile
from kranto.web.app import create_app

from .conftest import chat_response, web_client
from .test_post_write import card
from .test_web import rt  # noqa: F401 - fixture

ITEM = {"title": "China blocks a robotics deal", "facts": "ABB confirmed the sale was stopped."}
THREE = {"end": "Factory data becomes a border, and by the 2030s robot makers sell one arm per "
                "bloc instead of one arm for the world.",
         "bet": "By 2028 at least two Western robot makers keep Chinese plants' camera footage on "
                "servers inside China, because selling there will require it.",
         "scene": "A plant manager in Ohio reads the vendor's contract and finds a clause on "
                  "where the arm's camera footage goes"}
OLD = {"claim": "Robot data is now a national asset, and China just said so.",
       "prediction": "More robotics deals will be blocked over data within a year.",
       "question": "Would you sell a company whose robots see inside every factory"}


def test_three_distinct_angles_where_it_leads_a_bet_and_a_scene():
    seen = []

    def complete(messages, schema):
        seen.append((messages, schema))
        return {"text": json.dumps(THREE), "structured": None}

    got = prose.angles(ITEM, Profile(voice="Short sentences. Dry."), complete=complete)
    assert [a["kind"] for a in got] == ["end", "bet", "scene"]
    assert [a["words"] for a in got] == ["where it leads", "a bet", "a scene"]
    assert len({a["text"] for a in got}) == 3
    (msgs, schema), = seen                                    # all passed: one call
    assert schema == SCHEMA
    assert "Short sentences. Dry." in msgs[0]["content"]      # the person's voice card
    assert "never write as if the person tried" in msgs[0]["content"]
    assert "beyond the item's own claim" in msgs[0]["content"]
    assert "within a year, more X will Y" in msgs[0]["content"]
    assert "China blocks a robotics deal" in msgs[1]["content"]


@pytest.mark.parametrize("bad", [
    {**THREE, "bet": THREE["end"]},                                         # not distinct
    {**THREE, "scene": ""},                                                 # missing
    {**THREE, "end": "I tried their arm at my company and it leaked."},     # an experience
])
def test_angles_that_repeat_are_missing_or_tell_an_experience_are_refused(bad):
    with pytest.raises(AnglesError):
        parse({"structured": bad})


def test_one_sentence_each_at_most_forty_words():
    long = {**THREE, "end": "This is the claim. And a second sentence that should go."}
    assert parse({"structured": long})[0]["text"] == "This is the claim."


@pytest.mark.parametrize("kind,text,code", [
    ("bet", "Within a year, more robotics deals will be blocked over data.", "stock"),
    ("bet", "In the next two years most robot makers will follow China's lead on data.", "stock"),
    ("end", "Others will follow, and the deals stop.", "stock"),
    ("end", "Someone will build a tool that tracks which robot data crosses a border.", "tool"),
    ("bet", "robot makers will keep footage at home because rules demand it.", "unnamed"),
    ("end", "China blocks a robotics deal and ABB confirmed it.", "restates"),
    ("scene", "I've used these arms at work and the data went everywhere.", "experience"),
])
def test_the_rule_refuses_stock_tools_unnamed_bets_restated_items_and_experience(kind, text,
                                                                                 code):
    assert code in [p.split(":")[0] for p in problems(kind, text, ITEM)]


def test_good_angles_pass_the_rule():
    for kind, text in THREE.items():
        assert problems(kind, text, ITEM) == [], kind


def test_a_refused_proposal_is_asked_for_once_more_and_a_stock_one_left_out():
    calls = []
    stock = {**THREE, "bet": "Within a year, more robot makers will do the same."}

    def complete(messages, schema):
        calls.append(messages)
        return {"structured": stock if len(calls) == 1 else THREE}

    got = prose.angles(ITEM, Profile(), complete=complete)
    assert len(calls) == 2                                     # asked once more, no more
    assert "stock" in calls[1][-1]["content"]                  # and told why
    assert [a["kind"] for a in got] == ["end", "bet", "scene"]
    assert got[1] == {**got[1], "text": THREE["bet"], "retried": True}

    calls.clear()
    got = prose.angles(ITEM, Profile(), complete=lambda m, s: calls.append(m) or
                       {"structured": stock})
    assert len(calls) == 2
    assert [a["kind"] for a in got] == ["end", "scene"]        # the stock bet is never shown


def test_too_few_angles_past_the_item_fail_the_call():
    flat = {"end": "Within a year, more labs will publish this.",
            "bet": "Others will follow soon enough, and quickly.",
            "scene": "A plant manager in Ohio reads the contract and finds the data clause"}
    with pytest.raises(AnglesError):
        prose.angles(ITEM, Profile(), complete=lambda m, s: {"structured": flat})


def test_round_2s_kinds_stay_readable():
    assert parse({"structured": OLD}, kinds=OLD_KINDS)[2]["text"].endswith("?")
    assert {WORDS[k] for k in OLD_KINDS} == {"a claim", "a prediction", "a question"}
    assert KINDS == ("end", "bet", "scene")


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
        assert [a["kind"] for a in got["angles"]] == ["end", "bet", "scene"]
        assert got["about"] == f"card:{n}" and got["as"] == "blog"
        asked = seen[0]["messages"][-1]["content"]
        assert "Battery swap ledger" in asked
        # round 3: the card's change leads, its idea is labelled background
        assert "What the sources show (the post is about this" in asked
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


# -- a writer on OpenAI's own API (P-11: built, no default chosen) ------------------------------


def test_a_writer_may_be_on_openais_api_and_the_watcher_never_is(rt):  # noqa: F811
    from kranto.config import PROVIDERS
    out = profile_mod.change(rt.cfg, rt.store, {"writer_model": {
        "blog": {"provider": "openai", "model": "gpt-x"}}})
    assert out["ok"]
    assert prose.load(rt.cfg, rt.store).writer_model("blog") == {"provider": "openai",
                                                                  "model": "gpt-x"}
    assert profile_mod.clean_writers({"toot": {"provider": "openai", "model": "m"}}) == {
        "toot": {"provider": "openai", "model": "m"}}
    assert "openai" not in PROVIDERS                         # never the watcher's provider


def _openai_http(seen: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/models"):
            return httpx.Response(status, json={"data": [{"id": "gpt-x"}]})
        return httpx.Response(200, json={"model": "gpt-x", "choices": [
            {"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return handler


def test_the_openai_provider_sends_what_openais_models_take(rt):  # noqa: F811
    from kranto.providers import make_provider
    from kranto.providers.base import Request
    seen: list = []
    key = "-".join(("test", "key", "for", "openai"))         # built at runtime, never a literal

    def http(**kw):
        return httpx.Client(transport=httpx.MockTransport(_openai_http(seen)))
    p = make_provider("openai", rt.cfg.llm, http=http,
                      key=lambda env: key if env == "OPENAI_API_KEY" else None)
    body = p.build(Request(model="gpt-x", messages=[{"role": "user", "content": "hi"}],
                           max_tokens=300, temperature=0.7, purpose="blog_post"))
    assert body == {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}],
                    "max_completion_tokens": 300}      # no temperature, no max_tokens
    reply = p.send(body)
    assert reply.text == "ok" and reply.input_tokens == 10
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {key}"
    assert p.key_env == "OPENAI_API_KEY" and p.cost_source == "estimate"
    p.close()


def test_the_openai_key_is_tested_and_kept_only_when_it_works(tmp_path, monkeypatch):
    from kranto import providers
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    key = "".join(("sk", "-", "t" * 40))
    seen: list = []
    bad = providers.openai_key(tmp_path, key,
                               transport=httpx.MockTransport(_openai_http(seen, 401)))
    assert not bad["ok"] and not bad["changed"] and key not in bad["detail"]
    assert not (tmp_path / ".env").exists()
    good = providers.openai_key(tmp_path, key, transport=httpx.MockTransport(_openai_http(seen)))
    assert good["ok"] and good["changed"] and key not in json.dumps(good)
    env = tmp_path / ".env"
    assert "OPENAI_API_KEY=" in env.read_text() and oct(env.stat().st_mode)[-3:] == "600"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
