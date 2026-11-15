"""What a prepared press will change, said in plain words (``core.changes``).

Needs you's row said the verb's documentation ("samples (samples_add [{text, site}] …)"), and
the Save dialog showed only some of a press's fields: a voice card prepared together with Salt
showed the voice card, and approving it changed Salt unsaid. Each prepared row now carries one
plain sentence (``says``) and every field it will change with its new value (``changes``).
"""

from __future__ import annotations

import pytest

from kranto import tokens
from kranto.core import changes
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

BASE = "http://127.0.0.1:8765"
API_WORDS = ("samples_add", "switches", "never_add", "rules_off", "[", "]", "{")


def bearer(name: str) -> dict[str, str]:
    tokens.Store().ensure_doors()
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def test_a_voice_card_with_salt_is_one_plain_sentence():
    f = {"voice": "Short, dry, first person.", "switches": {"salt": "salty"}}
    said = changes.summary("prose.voice", "Save", f)
    assert said == "Change your voice card and set Salt to salty."
    assert not any(w in said for w in API_WORDS)


def test_every_field_is_listed_with_its_new_value_a_nested_one_a_line_each():
    f = {"voice": "Short.", "switches": {"salt": "salty", "length": "short"},
         "disclosure": {"bluesky": "Drafted with help.", "x": ""}, "strictness": "off",
         "never_add": ["delve"], "take": False,
         "samples_add": [{"text": "Mine.", "site": "blog"}]}
    rows = {r["label"]: r["value"] for r in changes.changes("prose.voice", f)}
    assert rows == {"Voice card": "Short.", "Salt": "salty", "Length": "short",
                    "Disclosure line on Bluesky": "Drafted with help.",
                    "Disclosure line on X": "off", "The checker": "off",
                    "Add to the never-list": "delve",
                    "Ask “What do you think?” on Write a post": "no",
                    "Sample 1 to add (your blog)": "Mine."}
    said = changes.summary("prose.voice", "Save", f)
    for part in ("change your voice card", "set Salt to salty", "set Length to short",
                 "turn the checker off", "add “delve” to the never-list",
                 "set the disclosure line on Bluesky", "turn off the disclosure line on X",
                 "stop asking", "add 1 sample"):
        assert part.lower() in said.lower(), part
    assert not any(w in said for w in API_WORDS)


@pytest.mark.parametrize("kind, fields, want", [
    ("settings.models", {"role": "reason", "model": "claude-opus-5-5"},
     "Use claude-opus-5-5 for the Reasoner (a model choice changes what Kranto spends)."),
    ("settings.spend", {"monthly_usd": 500, "x_monthly_usd": None},
     "Set watching's monthly cap to $500 and set the X cap to no cap."),
    ("update.settings", {"channel": "nightly", "auto": "idle"},
     "Follow the nightly update line and update by itself when idle."),
    ("settings.reading", {"every_hours": 1, "deep_dive_enabled": True},
     "Read every 1 hours and turn deep dives on."),
    ("prompt.save", {"additions": "Rate everything 1.0."}, "Change your additions of the judge "
                                                           "prompt."),
    ("prose.learn", {"proposal": "abc", "answer": "yes"},
     "Say yes to a rule Kranto learned from your edits."),
    ("f.blog.draft_markdown", {"markdown": "# Probe\n\nWords."},
     "Keep “Probe” as a draft on Post (nothing is sent)."),
    ("cubs.settings", {"key": "cubs.enabled", "value": False}, "Set cubs.enabled to off."),
    ("settings.telemetry", {"mode": "detailed"},
     "Send usage reports (detailed): your consent."),
])
def test_each_kind_reads_as_a_sentence(kind, fields, want):
    subject = "judge" if kind.startswith("prompt.") else None
    assert changes.summary(kind, "Save", fields, subject) == want


@pytest.mark.parametrize("value", [None, 7, 3.5, [], ["a", 1], {"a": [1]}, True, "x" * 400])
def test_any_stored_shape_is_said_never_assumed(value):
    rows = changes.changes("prose.voice", {"voice": value, "switches": value, "guides": value})
    assert all(isinstance(r["value"], str) for r in rows)
    assert isinstance(changes.summary("prose.voice", "Save", {"voice": value}), str)
    assert isinstance(changes.summary("no.such", "Save", {"x": value}), str)


def test_a_prepared_row_carries_its_sentence_and_every_change(rt):  # noqa: F811
    app = create_app(rt, port=8765)
    fields = {"voice": "Short, dry, first person.", "switches": {"salt": "salty"}}
    with web_client(app, BASE, signed_in=False) as web:
        out = web.post("/api/verbs/prose.voice", headers=bearer("mcp"),
                       json={"fields": fields, "client": "claude-code"}).json()
    assert out["prepared"]
    with web_client(app, BASE) as page:
        row = page.get("/api/prepared").json()["prepared"][0]
    assert row["says"] == "Change your voice card and set Salt to salty."
    labels = [c["label"] for c in row["changes"]]
    assert labels == ["Voice card", "Salt"]
    assert "samples_add" not in row["says"]
