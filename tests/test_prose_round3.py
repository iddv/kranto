"""Round 3 of the prose engine (the owner's second blind read): the post follows its angle
outward, salt is a switch on the voice card (plain, dry, salty) with one step more on a thin
item, a salty post names no person its material doesn't, and a post from an idea card is about
the reader's world, not a tool to build. Every test here is offline; the live run's record is
replayed in ``test_prose_round3_record.py``."""

from __future__ import annotations

import importlib.util
from dataclasses import replace

import pytest

from kranto.cubs import examples_dir
from kranto.features.post.evals import writers
from kranto.prose import check, compose
from kranto.prose import profile as profile_mod
from kranto.prose.composer import ANGLE_WORDS, salt_of, thin
from kranto.prose.material import card as card_material
from kranto.prose.profile import Profile

from .test_prose_check import HUMAN
from .test_web import rt  # noqa: F401 - fixture

ITEMS = {it["id"]: it for it in writers.items()}
TEN = ("brief-24-1", "brief-21-1", "card-158", "brief-19-1", "brief-20-1", "brief-26-1",
       "brief-23-1", "card-160", "card-152", "card-155")
CARDS = ("card-158", "card-160", "card-152", "card-155")


def material(iid: str) -> dict:
    it = ITEMS[iid]
    return {"title": writers.about(it), "facts": it["facts"], "angle": "An angle."}


def salted(salt: str, thin_on: str = "on") -> Profile:
    p = Profile()
    return replace(p, switches={**p.switches, "salt": salt, "salt_thin": thin_on})


def system_of(msgs: list[dict]) -> str:
    return msgs[0]["content"]


# -- the body follows the angle outward --------------------------------------------------------


def test_the_angle_rule_asks_for_the_big_claim_and_the_speculation_as_the_persons():
    for words in ("follow it outward", "what else must be true", "how likely",
                  "the item is the evidence", "\"I think\"", "never stated as a fact",
                  "never invent an experience"):
        assert words in ANGLE_WORDS, words
    sys = system_of(compose(material("brief-24-1"), "blog", Profile(), kind="long"))
    assert ANGLE_WORDS in sys


# -- salt ---------------------------------------------------------------------------------------


def test_salt_is_a_switch_plain_by_default_with_more_salt_on_thin_items_off():
    # off until the name rule runs in every writer; a stored "on" is kept
    assert profile_mod.SWITCH_DEFAULTS["salt"] == "plain"
    assert profile_mod.SWITCH_DEFAULTS["salt_thin"] == "off"
    assert profile_mod._clean_switches({"salt_thin": "on"})["salt_thin"] == "on"
    assert profile_mod.SWITCHES["salt"] == ("plain", "wry", "salty")
    assert "salt" in profile_mod.SWITCH_WORDS and "salt_thin" in profile_mod.SWITCH_WORDS


def test_the_salt_switch_is_saved_and_a_wrong_value_refused(rt):  # noqa: F811
    from kranto import prose
    out = profile_mod.change(rt.cfg, rt.store, {"switches": {"salt": "salty",
                                                             "salt_thin": "off"}})
    assert out["ok"]
    p = prose.load(rt.cfg, rt.store)
    assert p.switches["salt"] == "salty" and p.switches["salt_thin"] == "off"
    with pytest.raises(profile_mod.ProfileError):
        profile_mod.change(rt.cfg, rt.store, {"switches": {"salt": "spicy"}})


@pytest.mark.parametrize("stored", [None, "spicy", 3, ["salty"]])
def test_a_salt_stored_in_any_other_shape_reads_as_plain(stored):
    assert profile_mod._clean_switches({"salt": stored, "salt_thin": stored})["salt"] == "plain"
    assert profile_mod._clean_switches({"salt_thin": stored})["salt_thin"] == "off"


def test_which_of_the_ten_items_are_thin():
    got = {iid: thin(material(iid)) for iid in TEN}
    # the four cards are each a small tool; post 8's item (the usage canary) among them
    assert all(got[c] for c in CARDS), got
    assert "canary" in got["card-160"]
    # the news items with a headline and a paragraph of facts are not
    assert not got["brief-21-1"] and not got["brief-24-1"] and not got["brief-26-1"], got


@pytest.mark.parametrize("facts,title,why", [
    ("Version 2.1 is out.", "A small tool", "few facts"),
    ("[1] HN: one line about a thing.", "Something", "few facts"),
    ("A long paragraph " * 30, "Acme releases a browser extension for tabs", "product note"),
])
def test_thin_is_a_rule_on_the_material(facts, title, why):
    assert why.split()[0] in thin({"title": title, "facts": facts})


def test_salt_steps_once_on_a_thin_item_and_never_past_salty():
    thin_m, full = material("card-160"), material("brief-21-1")
    assert salt_of(salted("plain"), thin_m) == "wry"
    assert salt_of(salted("wry"), thin_m) == "salty"
    assert salt_of(salted("salty"), thin_m) == "salty"
    assert salt_of(salted("plain", "off"), thin_m) == "plain"
    assert salt_of(salted("plain"), full) == "plain"
    assert salt_of(salted("salty"), full) == "salty"


def test_the_salty_writers_prompt_differs_from_the_plain_ones_on_a_thin_item():
    m = material("card-160")
    salty = system_of(compose(m, "blog", salted("salty"), kind="long"))
    plain = system_of(compose(m, "blog", salted("plain", "off"), kind="long"))
    default = system_of(compose(m, "blog", salted("plain"), kind="long"))
    assert "# Salt: salty" in salty and "aimed at the thing" in salty
    assert "never a slur" in salty and "name no private person" in salty
    assert "# Salt" not in plain
    assert "# Salt: wry" in default                        # one step on a thin item
    assert "# Salt" not in system_of(compose(material("brief-21-1"), "blog", salted("plain"),
                                             kind="long"))


# -- a salty post names no private person -------------------------------------------------------

SOURCES = ("[1] dev.to: Anthropic removed the 5-hour limit for Ultra accounts.\n"
           "[2] HN: Claude Code's system prompt gained two sentences.")
SALTY_OK = ("Anthropic dropped the 5-hour limit and called it generosity. Claude Code got two "
            "new sentences in its prompt, which is one way to ship a feature. My bet: the meter "
            "you can't read is the product.")
SALTY_NAMES = ("Anthropic dropped the 5-hour limit. Somewhere Dario Amodei is counting tokens, "
               "and @limitwatcher will have a chart by lunch.")


def test_a_salty_post_naming_only_what_its_sources_name_is_clean():
    out = check(SALTY_OK, "blog", salted("salty"), kind="long", sources=SOURCES)
    assert "salt.person" not in {f["rule"] for f in out["flags"]}


def test_a_salty_post_naming_a_person_or_a_handle_the_sources_dont_is_flagged():
    out = check(SALTY_NAMES, "blog", salted("salty"), kind="long", sources=SOURCES)
    named = [f["text"] for f in out["flags"] if f["rule"] == "salt.person"]
    assert named == ["Dario Amodei", "@limitwatcher"]


@pytest.mark.parametrize("i", range(len(HUMAN)))
@pytest.mark.parametrize("salt", ["plain", "salty"])
def test_the_human_paragraphs_still_give_no_flag(i, salt):
    assert check(HUMAN[i], "blog", salted(salt), kind="long")["flags"] == []
    assert check(HUMAN[i], "blog", salted(salt), kind="long", sources=HUMAN[i])["flags"] == []


# -- idea cards: about the reader's world --------------------------------------------------------


def _blog_cub():
    spec = importlib.util.spec_from_file_location("blog_cub_main",
                                                  examples_dir() / "blog" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CARD = {"id": 7, "title": "Fixed-task canary for silent limit cuts",
        "one_liner": "Trackers report how much of a window is used, not what a percent buys.",
        "insight": "Limits change faster than anyone can read them.",
        "thesis": "A small canary would run the same task on a schedule.",
        "why": "they form a group of 604 distinct stories",
        "sources": [{"n": 1, "source": "dev.to", "claim": "Anthropic removed a limit.",
                     "url": "https://example.org/a"}]}


def test_the_blog_cub_and_kranto_give_a_card_the_same_material():
    cub = _blog_cub()
    got = cub.card_material(CARD, CARD["sources"], "an angle")
    want = card_material(CARD)
    assert {k: got[k] for k in ("title", "facts")} == want
    assert got["angle"] == "an angle"


def test_a_cards_material_leads_with_the_change_and_labels_the_idea_background():
    about = card_material(CARD)["title"].split("\n")
    assert about[0] == CARD["title"]                       # Post's row reads the first line
    assert about[1].startswith("What the sources show (the post is about this")
    assert about[-1].startswith("The idea a builder might act on (background only")
    assert "604 distinct stories" not in "\n".join(about)  # the story count is not material


def test_the_card_task_says_the_post_is_about_the_world_not_a_tool():
    task = _blog_cub().CARD_TASK
    assert "what the card's evidence means for the reader's world" in task
    assert "not a description of a tool to build" in task
    toot = writers._consts("toot")["TASK"]
    assert "not a tool to build" in toot


@pytest.mark.parametrize("iid", CARDS)
def test_the_four_cards_prompts_before_and_after(iid):
    """Before (round 2): the card's lines ran together, the tool first and alone. After: the
    change leads, the idea is labelled background, and the task says what the post is for."""
    it = ITEMS[iid]
    before = writers._about(it)
    after = writers.about(it)
    assert before.split("\n")[0] == after.split("\n")[0] == it["title"]
    assert "What the sources show" not in before and "What the sources show" in after
    assert "background only" in after
    sys = system_of(writers.prompt("new", "blog", it, angle="An angle."))
    assert "not a description of a tool to build" in sys


# -- two fixes the live run found --------------------------------------------------------------


def test_a_sentence_does_not_end_at_am_or_eg():
    from kranto.prose.checker import sentences
    t = ("Picture a manager in Ohio at 2 a.m., two vendors' robots stuck in an aisle. A3 "
         "published ISO 21423:2026. The U.S. agreed, e.g. in March. Next one.")
    assert [t[a:b] for a, b in sentences(t)] == [
        "Picture a manager in Ohio at 2 a.m., two vendors' robots stuck in an aisle.",
        "A3 published ISO 21423:2026.", "The U.S. agreed, e.g. in March.", "Next one."]


def test_revise_refuses_a_replacement_that_says_its_clause_twice():
    from kranto.prose.reviser import splice
    text = "A manager in Ohio, 2 a.m.: robots block an aisle. ISO 21423 sets common rules."
    span = {"start": 0, "end": text.index(" ISO")}
    twice = ("Who fixes it when robots from two vendors block an Ohio aisle at 2 a.m.: robots "
             "from two vendors blocking an Ohio aisle.")
    assert splice(text, [span], {1: twice}) == (text, [])
    once = "Who fixes it when robots from two vendors block an Ohio aisle at 2 a.m.?"
    assert splice(text, [span], {1: once})[0].startswith(once)


def test_where_it_leads_may_say_five_or_ten_years():
    from kranto.prose.angles import stock
    assert not stock("In ten years, AI work gets bought like electricity.")
    assert not stock("Within ten years, small firms sign contracts that name a pass rate.")
    assert stock("Within a year, more labs will publish this.")
    assert stock("In the next 18 months most vendors will follow.")
