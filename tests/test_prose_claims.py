"""acceptance 1: each of the owner's complaints about
round 1's five posts has a fixture made from those posts, and the new checker flags it there;
the three public-domain paragraphs still give no flag, even checked as posts."""

from __future__ import annotations

import json

import pytest

from kranto.features.post import evals
from kranto.prose import check, invented_first_person

from .test_prose_check import HUMAN

READ = json.loads(evals.fixture("owner_read_1.json").read_text("utf-8"))
POSTS = {p["post"]: p for p in READ["posts"]}


def _check(post: int, version: str) -> dict:
    p = POSTS[post]
    site, kind = ("blog", "long") if p["site"] == "blog" else ("mastodon", "short")
    return check(p[version], site, kind=kind)


def _spans(post: int, version: str, rule: str) -> list[str]:
    return [f["text"] for f in _check(post, version)["flags"] if f["rule"] == rule]


def test_the_fixture_is_the_owners_read():
    assert [POSTS[n]["owner_pick"] for n in range(1, 6)] == ["neither", "old", "old", "neither",
                                                             "neither"]


# (the owner's complaint, the post and version it was about, the rule, words the flag holds)
COMPLAINTS = [
    ("sections like a template, all about the same length", 1, "old", "claim.sections", None),
    ("“What happened / Why it matters” on every post", 1, "old", "claim.skeleton",
     "What happened"),
    ("“What happened / Why it matters” on every post", 2, "old", "claim.skeleton",
     "Why it may matter"),
    ("“What happened / Why it matters” on every post", 3, "old", "claim.skeleton",
     "Why it may matter"),
    ("“the honest reading”", 1, "old", "claim.caveats", "the honest reading"),
    ("“sources give no details”", 1, "new", "claim.caveats", "The sources give no details"),
    ("“worth keeping in mind”", 2, "old", "claim.caveats", "worth keeping in mind"),
    ("the item does not say more", 2, "new", "claim.caveats", "the item does not say"),
    ("“Three things point in this direction.”", 3, "old", "claim.announced",
     "Three things point in this direction."),
    ("“First, memory tooling is growing.”", 3, "old", "claim.announced", "First,"),
    ("why is this interesting? the first sentence needs a claim", 3, "old", "claim.no_hook",
     "Agents are gaining long-term memory"),
    ("just stating facts", 4, "old", "claim.restates", None),
    ("just stating facts", 4, "new", "claim.restates", None),
    ("why should I care!?", 5, "old", "claim.no_hook", "Beijing-based LiberAI announced"),
    ("why should I care!?", 5, "new", "claim.restates", None),
    ("why should I care!?", 5, "new", "claim.no_hook", "LiberAI announced Liber-0"),
]


@pytest.mark.parametrize("why,post,version,rule,words", COMPLAINTS,
                         ids=[f"{c[1]}-{c[2]}-{c[3]}" for c in COMPLAINTS])
def test_each_complaint_is_flagged_in_the_round_1_text(why, post, version, rule, words):
    spans = _spans(post, version, rule)
    assert spans, (why, [f["rule"] for f in _check(post, version)["flags"]])
    if words:
        assert any(words.lower() in s.lower() for s in spans), (why, spans)


@pytest.mark.parametrize("i", range(len(HUMAN)))
@pytest.mark.parametrize("site,kind", [(None, None), ("blog", "long"), ("mastodon", "short")])
@pytest.mark.parametrize("level", ["light", "strict"])
def test_human_prose_gives_no_flag_even_as_a_post(i, site, kind, level):
    limits = {"max_chars": 2000, "unit": "characters"} if site == "mastodon" else None
    out = check(HUMAN[i], site, kind=kind, strictness=level, limits=limits)
    assert out["flags"] == [], out["flags"]


def rules(text: str, **kw) -> set[str]:
    kw.setdefault("site", "blog")
    kw.setdefault("kind", "long")
    return {f["rule"] for f in check(text, **kw)["flags"]}


def test_one_ordinal_or_one_caveat_is_not_a_flag():
    one = ("Cheap robot hands will make teleoperation data a niche cost. First, the team trained "
           "on video, and its numbers are self-reported.")
    assert "claim.announced" not in rules(one)
    assert "claim.caveats" not in rules(one)
    two = one + " Reportedly the hands were off the shelf."
    assert "claim.caveats" in rules(two)


def test_a_claim_a_prediction_or_a_question_opens_a_post():
    for opening in ("Robot data is the next thing governments will guard.",
                    "Would you hand your robot's camera feed to a foreign buyer?",
                    "Nobody tests whether shared agent memory leaks between users."):
        assert "claim.no_hook" not in rules(opening + " ABB confirmed the block on Monday.")
    assert "claim.no_hook" in rules("ABB confirmed the block on Monday. The deal was $5.4B.")


def test_the_skeleton_and_the_sections():
    body = ("The robot policy grasped sixty six objects from video alone, and the team says it "
            "used no teleoperation data at all, which would cut the cost of training hands. ")
    templ = f"## What happened\n\n{body}\n\n## Why it matters\n\n{body}\n\n## Next\n\n{body}"
    got = rules(templ)
    assert {"claim.skeleton", "claim.sections"} <= got
    # one heading of its own is not a skeleton, and sections of different sizes are not one
    free = f"{body}\n\n## The cost of a hand\n\n{body}{body}{body}\n\n## Who wins\n\n{body[:90]}."
    assert not {"claim.skeleton", "claim.sections"} & rules(free)


def test_a_newsletter_opening_and_untyped_text_skip_the_post_rules():
    facts = "ABB confirmed the block on Monday. The deal was worth $5.4B."
    assert "claim.restates" in rules(facts)
    assert "claim.restates" not in rules(facts, site="newsletter", kind=None)
    assert "claim.restates" not in rules(facts, site=None, kind=None)
    assert "claim.restates" not in rules(facts, kind="intro")


def test_an_invented_experience_is_flagged_even_with_an_angle():
    angle = "I think robot data is the next thing governments will guard."
    text = ("Robot data is the next thing governments will guard. I tried a robot arm at my "
            "company last year, and the data never left the building.")
    spans = invented_first_person(text, [angle])
    assert [text[s:e].strip() for s, e in spans] == [
        "I tried a robot arm at my company last year, and the data never left the building."]
    # the stance itself is the angle's, so it stays
    assert not invented_first_person("I think governments will guard robot data.", [angle])
    # an experience the person wrote themselves may be told
    lived = "I tried the arm at my company last year; the data never left the building."
    assert not invented_first_person(text, [lived])
    # a sample's experience is about something else: it does not let the writer invent one
    sample = "I ran the board for a week as a home server."
    assert invented_first_person("I ran the new policy for a week on my home server.",
                                 [angle, sample])
