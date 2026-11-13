""" acceptance 4 and 7: the prose eval runs on recorded answers in CI (no model, no
network). Across the new writer's drafts, no first-person claim that neither the item's take
nor a sample backs (P-5); the checker scores the new writer at least as well as the old; the
blind pairwise judgement was recorded for every item."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kranto.features.post.evals import score, writers

REC = Path(writers.__file__).parent / "recorded.json"


@pytest.fixture(scope="module")
def recording() -> dict:
    return json.loads(REC.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def card(recording) -> dict:
    return score.scorecard(recording)


def test_twenty_real_items_each_written_old_and_new_for_both_sites(recording):
    items = writers.items()
    assert len(items) == 20
    assert {i["kind"] for i in items} == {"card", "item"}
    for it in items:
        for site in writers.SITES:
            run = recording["runs"][it["id"]][site]
            assert run["old"]["text"].strip() and run["new"]["text"].strip(), (it["id"], site)
            assert recording["judge"][it["id"]][site]["winner"] in ("old", "new", "tie")
    meta = recording["meta"]
    assert meta["calls"] >= 120
    # each run stops before its next call at its cap: the last call may pass it by a cent
    for run in meta.get("runs") or [meta]:
        assert max(run["cost_usd"], run["equiv_usd"]) <= run["budget_usd"] + 0.05


@pytest.mark.parametrize("site", writers.SITES)
def test_no_invented_first_person_in_the_new_drafts(card, site):
    # after the pipeline's last step (code: an unbacked "I" sentence is cut), replayed here on
    # the recorded answers; what the model wrote before it is kept as invented_raw
    new = card["sites"][site]["new"]
    assert new["invented_share"] == 0.0, new["invented"]
    assert new["invented_share_raw"] <= card["sites"][site]["old"]["invented_share"]


@pytest.mark.parametrize("site", writers.SITES)
def test_the_checker_scores_the_new_writer_at_least_as_well(card, site):
    old, new = card["sites"][site]["old"], card["sites"][site]["new"]
    assert new["score"] >= old["score"]
    assert new["flags_per_post"] <= old["flags_per_post"]


def test_the_new_writers_prompt_is_built_by_compose_with_the_cubs_task_lines():
    item = writers.items()[0]
    msgs = writers.prompt("new", "blog", item)
    blog_task = writers._consts("blog")["ITEM_TASK"]
    assert msgs[0]["content"].startswith(blog_task)
    assert "# The floor" in msgs[0]["content"] and "<example" in msgs[1]["content"]
    toot = writers.prompt("new", "toot", item)
    assert toot[0]["content"].startswith(writers._consts("toot")["TASK"].format(room=280)[:40])
    old = writers.prompt("old", "blog", item)
    assert "the tone is plain and curious, no hype" in old[0]["content"]


def test_the_scorecard_says_how_many_recordings_are_stale(card):
    for site in writers.SITES:
        assert isinstance(card["sites"][site]["stale_prompts"], int)
