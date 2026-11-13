"""``kranto eval watching|ideas``: a stage asked again on the frozen set through
the metered client (a fake model on a mock transport here), the estimate checked against the
budget before anything is sent, every call recorded as ``eval_<step>`` under one run, replies
cached by content, ``--repeat 2``'s noise floor, a candidate prompt beside the live one, the
rubric judge on the cards, and Spend's own line for evaluation (D9)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kranto.config import IngestConfig
from kranto.evals import Refused, runner, scorecard
from kranto.evals import cli as evals_cli
from kranto.ideate.cards import RATINGS

from .conftest import chat_response

FIX = Path(__file__).parent / "fixtures" / "evals"

CARD = json.dumps({"card": {"title": "A dated exporter", "who": "people who keep notes",
                            "evidence": [{"n": 1, "claim": "exports drop dates"}],
                            "ratings": {k: [0.6, "r"] for k in RATINGS}}})
BUILD = json.dumps({"tests": {g: {"pass": True, "why": "w"} for g in
                              ("product_not_feature", "not_absorbed", "broad", "relevant",
                               "lands", "not_shipped")},
                    "insight": 3, "wedge": 4, "bet": "b", "verdict": "build", "class": "build",
                    "reason": "r"})


def answer(body: dict):
    system = next((m["content"] for m in body["messages"] if m["role"] == "system"), "")
    user = body["messages"][-1]["content"]
    if "IQ rubric" in system:
        return chat_response(BUILD)
    if "=== OBSERVATIONS ===" in user or "observations below" in user or not system:
        return chat_response(CARD)
    if '"pass"' in system or "pass" in system and "screen" in system.lower():
        return chat_response('{"pass": true, "reason": "fine"}')
    return chat_response('{"skip": true}')


@pytest.fixture
def home(tmp_path):
    (tmp_path / "judges").mkdir()
    (tmp_path / "judges" / runner.JUDGE_FILE).write_text("# IQ rubric v3 (test)\nJudge it.")
    return tmp_path


def cfg_of(client):
    return SimpleNamespace(llm=client.config, budget=client.budget, ingest=IngestConfig())


def stage(name, client, home, store, **kw):
    return runner.run_stage(name, cfg=cfg_of(client), store=store, home=home, set_dir=FIX,
                            judges=home / "judges", client_for=lambda cfg: client, **kw)


def test_watching_through_the_metered_client(make_client, store, home):
    client = make_client(answer)
    (card,) = stage("watching", client, home, store, budget=1.0)
    m = {x["key"]: x for x in card["metrics"]}
    # every screen passes now: the five recorded passes agree, the five drops do not
    assert (m["screen_agree"]["num"], m["screen_agree"]["den"]) == (5, 10)
    assert m["screen_drop"]["value"] == 0.0 and m["screen_drop"]["recorded"] == 0.5
    # every judge skips now: only the recorded skip agrees; the owner's ▲ is not kept
    assert (m["judge_agree"]["num"], m["judge_agree"]["den"]) == (1, 10)
    assert (m["owner_up_kept"]["num"], m["owner_up_kept"]["den"]) == (0, 1)
    assert (m["owner_down_dropped"]["num"], m["owner_down_dropped"]["den"]) == (1, 1)
    rows = store.query("SELECT purpose, run_uuid, prompt_version FROM llm_calls")
    # ten distinct screens; the ten judge cassettes share one item text: one call (cached)
    assert {r["purpose"] for r in rows} == {"eval_screen", "eval_judge"} and len(rows) == 11
    assert {r["run_uuid"] for r in rows} == {card["run_uuid"]}
    assert card["prompts"]["screen"].startswith("screen-") and card["baseline"] == "this run"
    md = (scorecard.root(home) / card["file"]).with_suffix(".md").read_text()
    assert "| screen agrees with the recorded verdict | 5/10 0.50 |" in md
    # the same run again is free: every reply comes from the cache
    (again,) = stage("watching", client, home, store, budget=1.0)
    assert {x["key"]: x for x in again["metrics"]}["calls"]["value"] == "0 (20)"
    assert len(client.fake.requests) == 11


def test_repeat_measures_the_noise_floor(make_client, store, home):
    client = make_client(answer)
    (card,) = stage("watching", client, home, store, budget=1.0, repeat=2, n=4)
    assert card["noise"] == {"screen": 1.0, "judge": 1.0} and len(client.fake.requests) == 4 * 2 + 2


def test_the_budget_is_checked_before_anything_is_sent(make_client, store, home):
    client = make_client(answer)
    with pytest.raises(Refused, match="over the budget"):
        stage("watching", client, home, store, budget=0.01)
    assert client.fake.requests == []


def test_a_candidate_runs_beside_the_live_prompt(make_client, store, home, tmp_path):
    client = make_client(answer)
    live, cand = stage("watching", client, home, store, budget=1.0, n=3,
                       candidates={"screen": "Screen it. {tenets}\nSay pass."})
    assert cand["candidate_of"] == live["file"] and cand["tag"] == "candidate"
    assert cand["prompts"]["screen"] != live["prompts"]["screen"]
    sent = [b["messages"][0]["content"] for b in client.fake.requests]
    assert any(s.startswith("Screen it.") for s in sent)


def test_ideas_writes_cards_and_the_rubric_judges_them(make_client, store, home):
    client = make_client(answer)
    (card,) = stage("ideas", client, home, store, budget=2.0, judge_model="reason-model")
    m = {x["key"]: x for x in card["metrics"]}
    assert (m["card_parses"]["num"], m["card_parses"]["den"]) == (10, 10)
    assert (m["card_build"]["num"], m["card_build"]["den"]) == (10, 10)
    assert m["mean_wedge"]["value"] == 4.0 and card["notes"] == [runner.JUDGE_BLIND_SPOT]
    purposes = {r["purpose"] for r in store.query("SELECT purpose FROM llm_calls")}
    assert purposes == {"eval_card", "eval_rubric"}


def test_no_rubric_judge_no_ideas_run(make_client, store, tmp_path):
    client = make_client(answer)
    with pytest.raises(Refused, match="no rubric judge"):
        runner.run_stage("ideas", cfg=cfg_of(client), store=store, home=tmp_path,
                         set_dir=FIX, budget=2.0, client_for=lambda cfg: client)


def test_kranto_eval_watching_refuses_under_ci(monkeypatch, tmp_path):
    monkeypatch.setenv("CI", "1")
    assert evals_cli.main(["watching", "--budget", "1", "--set", str(FIX)], tmp_path) == 2


def test_kranto_eval_all_runs_the_stages_in_order(make_client, store, home):
    client = make_client(answer)
    lines = []
    args = evals_cli.parser().parse_args(["all", "--budget", "3", "--set", str(FIX),
                                          "--judges", str(home / "judges"),
                                          "--judge", "reason-model"])
    assert evals_cli.cmd_stage(args, home, lines.append,
                               opened=(cfg_of(client), store, lambda cfg: client)) == 0
    heads = [ln.splitlines()[0] for ln in lines if ln.startswith("# Scorecard")]
    assert heads[0].startswith("# Scorecard: watching") and heads[1].startswith(
        "# Scorecard: ideas")


def test_spend_shows_evaluation_as_its_own_line(store):
    from kranto.web.today_api import evaluation_spend
    for purpose, usd in (("eval_screen", 0.01), ("eval_rubric", 0.2), ("judge", 0.5)):
        store.insert("llm_calls", {"purpose": purpose, "tier": "judge", "model": "m",
                                   "prompt_version": "v", "request": "{}", "response": "{}",
                                   "status": "ok", "attempts": 1, "cost_usd": usd,
                                   "created_at": "2099-01-01T00:00:00Z"})
    other = {"eval_screen": [0.01, 1], "eval_rubric": [0.2, 1], "card": [0.3, 1]}
    line, rest = evaluation_spend(other)
    assert line == {"usd": 0.21, "calls": 2} and set(rest) == {"card"}


def test_a_paused_library_says_so_and_sends_nothing(make_client, store, home):
    client = make_client(answer)
    store.pause("paused from Kranto")
    with pytest.raises(Refused, match="no call would be sent: paused"):
        stage("watching", client, home, store, budget=1.0)
    assert client.fake.requests == [] and not scorecard.history(home)


def test_calls_that_keep_failing_stop_the_run_without_a_scorecard(make_client, store, home):
    import httpx
    client = make_client(lambda body: httpx.Response(400, json={"error": "bad request"}))
    with pytest.raises(Refused, match="5 calls in a row failed"):
        stage("watching", client, home, store, budget=1.0)
    assert not scorecard.history(home)
