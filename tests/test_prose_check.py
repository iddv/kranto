""" acceptance 1: ``check`` flags each shape of on a fixture, and flags
nothing in three paragraphs of real human prose."""

from __future__ import annotations

import pytest

from kranto.prose import check
from kranto.prose.profile import Profile, Sample

# one fixture per shape; the rule the checker must name
SHAPES = {
    "shape.not_x_but_y": "This isn't just a faster database. It's a new way to think about "
                         "storage for small teams.",
    "shape.closer": "The team cut the build from 40 minutes to 6.\n\nThe tests now run on every "
                    "push, and nobody waits for a nightly.\n\nLet that sink in.",
    "shape.runup": "Here's the thing: most teams never measure how long a review waits.",
    "shape.tricolon": "The tool is fast, simple, and reliable. It helps teams plan, build, and "
                      "ship. Users get speed, clarity, and control.",
    "shape.ing_tail": "The city approved forty kilometres of bike lanes on Monday, highlighting "
                      "its growing commitment to safer streets.",
    "rhythm.dashes": "The release — announced on Monday — fixes the login bug. The fix — long "
                     "overdue — ships today, and users — finally — can upgrade.",
    "rhythm.paragraphs": "\n\n".join([
        "The council met on Tuesday to discuss the new library budget for next year, and the "
        "members agreed on most of the plan.",
        "The library will open two hours later on Sundays from March, and the reading room "
        "will get forty new chairs and tables.",
        "The children's section moves to the ground floor in April, so families with prams no "
        "longer need the old lift.",
        "The cost of the changes is about ninety thousand pounds, which the council will pay "
        "from its reserve this spring.",
    ]),
    "shape.moral": "The council moved the bus stop forty metres closer to the school.\n\n"
                   "Ultimately, it's a reminder that small changes can make a big difference.",
    "words.floor": "We delve into the tapestry of open-source tools that teams use.",
}

# Project Gutenberg, public domain: Jerome K. Jerome, Three Men in a Boat (1889), ch. 1;
# Henry David Thoreau, Walden (1854), "Economy"; Mark Twain, Life on the Mississippi (1883),
# ch. 9 (the passage's first sentences).
HUMAN = [
    "We were all feeling seedy, and we were getting quite nervous about it. Harris said he felt "
    "such extraordinary fits of giddiness come over him at times, that he hardly knew what he "
    "was doing; and then George said that _he_ had fits of giddiness too, and hardly knew what "
    "_he_ was doing. With me, it was my liver that was out of order. I knew it was my liver "
    "that was out of order, because I had just been reading a patent liver-pill circular, in "
    "which were detailed the various symptoms by which a man could tell when his liver was out "
    "of order. I had them all.",
    "When I wrote the following pages, or rather the bulk of them, I lived alone, in the woods, "
    "a mile from any neighbor, in a house which I had built myself, on the shore of Walden "
    "Pond, in Concord, Massachusetts, and earned my living by the labor of my hands only. I "
    "lived there two years and two months. At present I am a sojourner in civilized life again.",
    "Now when I had mastered the language of this water and had come to know every trifling "
    "feature that bordered the great river as familiarly as I knew the letters of the "
    "alphabet, I had made a valuable acquisition. But I had lost something, too. I had lost "
    "something which could never be restored to me while I lived. All the grace, the beauty, "
    "the poetry had gone out of the majestic river!",
]


def rules(text: str, **kw) -> set[str]:
    return {f["rule"] for f in check(text, **kw)["flags"]}


@pytest.mark.parametrize("rule", sorted(SHAPES))
def test_each_shape_is_flagged(rule):
    out = check(SHAPES[rule])
    assert rule in {f["rule"] for f in out["flags"]}, out["flags"]
    assert out["score"] < 100 and out["verdict"] != "Reads natural"


def test_each_flag_has_a_span_a_rule_and_a_fix():
    text = SHAPES["shape.ing_tail"]
    for f in check(text)["flags"]:
        assert 0 <= f["start"] < f["end"] <= len(text)
        assert f["text"] == text[f["start"]:f["end"]]
        assert f["fix"] and f["words"] and f["rule"]


@pytest.mark.parametrize("i", range(len(HUMAN)))
@pytest.mark.parametrize("level", ["light", "strict"])
def test_plain_human_prose_is_not_flagged(i, level):
    out = check(HUMAN[i], strictness=level)
    assert out["flags"] == [], out["flags"]
    assert out["verdict"] == "Reads natural" and out["score"] == 100


def test_it_is_deterministic():
    text = "\n\n".join(SHAPES.values())
    assert check(text) == check(text)


def test_the_never_list_and_the_keep_list():
    p = Profile(never=("synergy", "/\\bmoving forward\\b/"), keep=("game-changer for us",))
    text = "Moving forward, this is a game-changer for us. Another game-changer appears."
    flags = check(text, profile=p)["flags"]
    got = [(f["rule"], f["text"]) for f in flags]
    assert ("words.never", "Moving forward") in got
    # the kept phrase is never flagged; the same word outside it is
    assert [t for r, t in got if r == "words.floor"] == ["game-changer"]
    assert flags[-1]["start"] > text.index("Another")


def test_quotes_urls_and_code_are_left_alone():
    text = 'She said "let that sink in" and left. See https://example.org/delve and `robust`.'
    assert rules(text, strictness="strict") == set()


def test_rules_turned_off_and_strictness_off():
    text = SHAPES["shape.runup"]
    assert "shape.runup" not in rules(text, profile=Profile(rules_off=("shape.runup",)))
    assert check(text, strictness="off")["flags"] == []


def test_the_sites_limits():
    long = "A plain sentence about the release. " * 12
    assert "site.length" in rules(long, site="bluesky")
    assert "site.length" not in rules(long, site="mastodon")
    # a link counts 23 on X
    text = "Short post. https://example.org/" + "a" * 200
    assert "site.length" not in rules(text, site="x")
    tags = "New release out. #One #Two #Three #Four"
    assert [f["text"] for f in check(tags, site="mastodon")["flags"]
            if f["rule"] == "site.hashtags"] == ["#Four"]
    never = Profile(switches={**Profile().switches, "hashtags": "never"})
    assert len([f for f in check(tags, site="mastodon", profile=never)["flags"]
                if f["rule"] == "site.hashtags"]) == 4
    assert "site.emoji" in rules("Out now 🚀", site="mastodon")
    two = "Read https://a.example and https://b.example today."
    assert "site.links" in rules(two, site="bluesky")
    assert "site.length" in rules(long, limits={"max_chars": 100, "unit": "characters"})


def test_dashes_follow_the_persons_own_rate():
    text = SHAPES["rhythm.dashes"]
    dashy = Profile(samples=(Sample("a", "I write — always — with dashes — like this — and "
                                         "that — every time — I can."),))
    assert "rhythm.dashes" in rules(text)
    assert "rhythm.dashes" not in rules(text, profile=dashy)
    # a range between digits is not a dash
    assert "rhythm.dashes" not in rules("Open 9–5, Monday–Friday, 2025–2026.", strictness="strict")


def test_rhythm_against_the_voice_card():
    short = Profile(samples=(Sample("a", "Short ones. I like them. They hit. Then stop. "
                                         "Fine by me. Next."),))
    text = " ".join(["This sentence goes on for quite a long while because it keeps adding "
                     "clauses that explain the same idea at length again."] * 6)
    assert "rhythm.voice" in rules(text, profile=short)


def test_invented_first_person_needs_a_take():
    text = "I tried the new release last week and loved the speed. The update ships today."
    assert "voice.invented_i" not in rules(text)          # no take given: not judged
    assert "voice.invented_i" in rules(text, take="")
    assert "voice.invented_i" not in rules(text, take="I tried the release last week; the "
                                                      "speed is what I loved.")
    # quoted speech is the speaker's, not the person's
    assert "voice.invented_i" not in rules('The maintainer said "I rewrote the parser".',
                                           take="")
    # "US" is a country, not "us"
    assert "voice.invented_i" not in rules("The US FCC banned new models of legged robots.",
                                           take="")
