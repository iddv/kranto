import json
from pathlib import Path

import pytest

from kranto import prompts
from kranto.intern import (
    OVERRIDE_FLOOR,
    OVERRIDE_MIN_RATING,
    extract_json_object,
    interpret,
    interpret_children,
    override_effect,
)

GOOD = (
    '{"kind": "mild_signal", "summary": "LFP cells at $50/kWh", "why_it_matters": "cost",'
    ' "content_quality": 0.9, "durability": 0.8, "opportunity": 0.5, "tags": ["battery"]}'
)


def test_decomposed_ratings_are_multiplied_in_code():
    outcome, fields = interpret(GOOD, threshold=0.2)
    assert outcome == "contributed"
    assert fields["signal"] == pytest.approx(0.9 * 0.8 * 0.5)


def test_below_threshold_is_gated_not_lost():
    outcome, fields = interpret(GOOD, threshold=0.5)
    assert outcome == "gated"
    assert fields is not None


@pytest.mark.parametrize(
    "text",
    ['{"skip": true}', '```json\n{"skip": true}\n```', '```\n{"skip":true}```', ' {"skip": true} '],
)
def test_skip_in_any_wrapping_is_a_skip(text):
    assert interpret(text, 0.2) == ("skipped", None)


def test_fenced_and_prose_wrapped_json_parse():
    assert interpret(f"```json\n{GOOD}\n```", 0.2)[0] == "contributed"
    assert interpret(f"Here you go:\n{GOOD}\nHope that helps", 0.2)[0] == "contributed"


def test_braces_inside_strings_do_not_break_extraction():
    obj = extract_json_object('{"summary": "uses {curly} braces", "n": 1}')
    assert obj == {"summary": "uses {curly} braces", "n": 1}


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        '{"summary": "x", "why_it_matters": "y"}',  # ratings missing
        '{"summary": "", "why_it_matters": "y", "content_quality": 1, "durability": 1,'
        ' "opportunity": 1}',
        '{"summary": "x", "why_it_matters": "y", "content_quality": "high", "durability": 1,'
        ' "opportunity": 1}',
    ],
)
def test_unusable_replies_are_parse_failures(text):
    assert interpret(text, 0.2) == ("parse_failed", None)


def test_ratings_are_clamped_and_kind_defaults():
    text = ('{"kind": "huge", "summary": "s", "why_it_matters": "w", "content_quality": 3,'
            ' "durability": -1, "opportunity": 0.5}')
    outcome, fields = interpret(text, 0.2)
    assert fields["content_quality"] == 1.0
    assert fields["durability"] == 0.0
    assert fields["kind"] == "beat"
    assert outcome == "gated"


def rated(q, d, o, override=True, reason="an interview whose substance is its audio"):
    obj = {"summary": "s", "why_it_matters": "w", "content_quality": q, "durability": d,
           "opportunity": o, "override": override}
    if reason is not None:
        obj["override_reason"] = reason
    return json.dumps(obj)


def test_override_needs_a_reason():
    assert interpret(rated(0.5, 0.5, 0.5), 0.2)[0] == "contributed"
    outcome, fields = interpret(rated(0.5, 0.5, 0.5, reason=None), 0.2)
    assert outcome == "gated"
    assert fields["override"] is False


@pytest.mark.parametrize("ratings, effect, outcome", [
    # The #47 podcasts the operator wanted kept: modest ratings, signal 0.08 to 0.17.
    ((0.3, 0.4, 0.7), "lifted", "contributed"),
    ((0.4, 0.6, 0.7), "lifted", "contributed"),
    # A rating below the floor is the judge saying the item is empty or of no
    # consequence: no reason makes up for it.
    ((0.1, 0.9, 0.9), "refused", "gated"),
    ((0.9, 0.5, 0.29), "refused", "gated"),
    ((0.1, 0.1, 0.1), "refused", "gated"),
    # Every rating at the floor, but the signal under a quarter of the threshold.
    ((0.3, 0.3, 0.3), "refused", "gated"),
    # Kept by its ratings: the override changes nothing.
    ((0.85, 0.8, 0.75), "unneeded", "contributed"),
])
def test_override_cannot_lift_an_item_too_thin_for_it(ratings, effect, outcome):
    got, fields = interpret(rated(*ratings), 0.2)
    assert (override_effect(fields, 0.2), got) == (effect, outcome)


def test_without_override_there_is_no_effect():
    _, fields = interpret(rated(0.1, 0.1, 0.1, override=False), 0.2)
    assert override_effect(fields, 0.2) is None


def test_the_override_floor_follows_the_threshold():
    _, fields = interpret(rated(0.5, 0.5, 0.5), 0.2)  # signal 0.125
    assert override_effect(fields, 0.4) == "lifted"
    assert override_effect(fields, 0.6) == "refused", "0.125 is under a quarter of 0.6"
    assert OVERRIDE_FLOOR * 0.6 > 0.125 >= OVERRIDE_FLOOR * 0.4
    assert OVERRIDE_MIN_RATING == 0.3


def test_children_get_the_same_backstop():
    text = json.dumps({**json.loads(rated(0.9, 0.9, 0.9, override=False)), "children": [
        json.loads(rated(0.4, 0.6, 0.7)) | {"ref": 1},
        json.loads(rated(0.05, 0.9, 0.9)) | {"ref": 2}]})
    kids = interpret_children(text, 0.2, 2)
    assert [(k.ref, k.outcome) for k in kids] == [(1, "contributed"), (2, "gated")]


def test_the_judge_prompt_keeps_override_narrow_and_sponsors_out():
    text = prompts.load("judge").template
    assert "does NOT qualify" in text
    assert "Never set it on" in text and "already high" in text
    assert "sponsor" in text and "affiliate link" in text
    screen = prompts.load("screen").template
    assert "Sponsors and ads are always dropped" in screen


def test_packaged_tenets_match_docs():
    docs = Path(__file__).parents[1] / "docs" / "design" / "TENETS.md"
    assert prompts.tenets() == docs.read_text(encoding="utf-8")


def test_prompt_version_tracks_content():
    judge = prompts.load("judge")
    assert judge.version.startswith("judge-")
    assert prompts.Prompt("judge", judge.template + " ").version != judge.version
    assert "{tenets}" in judge.template
    rendered = judge.render(tenets="T")
    assert '{"skip": true}' in rendered
