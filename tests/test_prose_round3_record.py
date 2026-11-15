"""Round 3's live run, replayed (``recorded3.json``, written by ``evals round3`` through a Claude
Code login on a scratch home): round 2's ten items, each written once from each of round 3's
angle kinds, the salty and plain pairs on two thin items, and the rubric judge's marks, the
owner's second read included. Nothing here calls a model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kranto.features.post.evals import round3, writers
from kranto.prose import check
from kranto.prose.angles import KINDS, problems, stock

REC = json.loads((Path(round3.__file__).parent / "recorded3.json").read_text(encoding="utf-8"))
ITEMS = {it["id"]: it for it in writers.items()}
DRAFTS = [(iid, r["site"], kind, d) for iid, r in REC["items"].items()
          for kind, d in r["drafts"].items()]
IDS = [f"{iid}-{kind}" for iid, _, kind, _ in DRAFTS]


def material(iid: str) -> dict:
    return {"title": writers.about(ITEMS[iid]), "facts": ITEMS[iid]["facts"]}


def test_ten_items_three_new_angles_each_and_the_run_stayed_under_three_dollars():
    assert set(REC["items"]) == set(round3.OWNER_FIVE) | set(round3.FIVE_MORE)
    for iid, r in REC["items"].items():
        assert [a["kind"] for a in r["angles"]] == list(KINDS), iid
        assert set(r["drafts"]) == set(KINDS), iid
    assert REC["meta"]["equiv_usd"] < 3.0 and REC["meta"]["cost_usd"] == 0.0


def test_every_proposed_angle_passes_the_rule_and_none_is_stock():
    for iid, r in REC["items"].items():
        for a in r["angles"]:
            assert not stock(a["text"]), (iid, a["text"])
            assert problems(a["kind"], a["text"], material(iid)) == [], (iid, a)


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_a_blog_post_is_120_to_200_words_and_a_short_post_within_its_limit(iid, site, kind, d):
    if site == "blog":
        assert 120 <= len(d["text"].split()) <= 200, (iid, kind, len(d["text"].split()))
    else:
        assert len(d["text"]) <= writers.ROOM, (iid, kind, len(d["text"]))


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_the_prompt_that_wrote_each_draft_is_the_one_exported(iid, site, kind, d):
    msgs = writers.prompt("new", site, ITEMS[iid], angle=d["angle"])
    if d["salt"] == "wry":
        # the middle salt step was called "dry" when the run wrote the thin items' drafts and
        # was renamed after ("dry" is a practice run everywhere else on the page); its words
        # are otherwise the same
        then, now = "# Salt: dry\n\nDry:", "# Salt: wry\n\nWry:"
        msgs = [{**m, "content": m["content"].replace(now, then)} for m in msgs]
    assert writers.sha(msgs) == d["sha"]


@pytest.mark.parametrize("iid,site,kind,d", DRAFTS, ids=IDS)
def test_no_draft_names_a_person_its_material_doesnt(iid, site, kind, d):
    src = f"{writers.about(ITEMS[iid])}\n{ITEMS[iid]['facts']}"
    flags = check(d["text"], "blog", sources=src)["flags"]
    assert not [f for f in flags if f["rule"] == "salt.person"], (iid, kind)


def test_the_judge_marks_whether_each_draft_goes_beyond_the_item():
    marks = [d["mark"] for _, _, _, d in DRAFTS]
    assert all(isinstance(m.get("beyond"), bool) for m in marks)
    beyond = sum(m["beyond"] for m in marks)
    assert beyond >= 24, beyond                      # 25 of 30 at the recording


def test_on_the_four_cards_the_first_sentence_is_about_the_world():
    cards = [(iid, k, d["mark"]["first_world"]) for iid, _, k, d in DRAFTS
             if iid.startswith("card-")]
    assert len(cards) == 12
    # 11 of 12: card-155's bet angle is itself a product release ("vLLM will ship...")
    assert [(i, k) for i, k, w in cards if not w] == [("card-155", "bet")]


def test_the_salty_writer_reads_differently_from_the_plain_one_and_names_no_one():
    for iid in round3.SALT:
        row = REC["items"][iid]
        salty, plain = row["salted"]["salty"], row["salted"]["plain"]
        assert salty["salt"] == "salty" and plain["salt"] == "plain"
        assert row["drafts"][salty["kind"]]["salt"] == "wry"        # the default on a thin item
        assert salty["text"] != plain["text"]
        src = f"{writers.about(ITEMS[iid])}\n{ITEMS[iid]['facts']}"
        for d in (salty, plain):
            assert 120 <= len(d["text"].split()) <= 200
            names = [f for f in check(d["text"], "blog", sources=src)["flags"]
                     if f["rule"] == "salt.person"]
            assert names == [], (iid, names)


def test_the_judge_marked_the_owners_second_read():
    marks = REC["owner_marks"]
    picked = [m for m in marks if m["owner"] != "none"]
    refused = [m for m in marks if m["owner"] == "none"]
    assert len(picked) == 6 and len(refused) == 12
    # the new rule is stricter than the owner was in round 2: of his six picks it marks one
    # (post 1) as going beyond the item, and two of the twelve drafts he refused
    assert [m["post"] for m in picked if m["beyond"]] == [1]
    assert sum(m["beyond"] for m in refused) == 2
