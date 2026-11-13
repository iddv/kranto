"""Write ``tests/fixtures/evals/``: a small eval set in the frozen set's format whose items are
**synthetic** (invented items and replies, no third-party text), each picked for a behaviour
the cassette replay must keep: a drop, a pass, a reply in a fence, an unreadable reply, a
skip, a gated item, a kept one, an override, a cut-off reply, a declined card, a malformed
one. The system messages are the shipped prompts rendered as the watcher renders them, so the
prompt-assembly check runs on them too.

    python scripts/eval_fixtures.py        (rewrites the fixtures; review the diff)

Regenerate only on purpose: a changed recorded verdict is what the replay test exists to
catch, and regenerating hides it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from kranto import prompts  # noqa: E402
from kranto.ideate.cards import RATINGS, parse_card  # noqa: E402
from kranto.intern import interpret, interpret_screen  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "evals"
THRESHOLD = 0.03
# the card prompt's {prior_art} when no search ran (cards.prior_art_text's sentence): the fixtures
# hold no third-party text, so no search results either
NO_PRIOR_ART = ("No prior-art search ran (no live search: results are from model memory and may "
                "be stale). Write \"no prior-art search\" in \"pattern\", leave \"prior_art\" "
                "empty, and make no claim that nothing does this.")
TOPIC = ("Tools for people who keep their own notes offline: sync, export, backup and the "
         "plain-text formats they rely on.")


def item_text(title: str, body: str, source: str = "example forum") -> str:
    return json.dumps({"source": source, "topics_this_source_is_watched_for": [TOPIC],
                       "item": {"title": title, "body": body, "url": "https://example.org/t/1",
                                "published_at": "2026-10-01T09:00:00Z"}},
                      ensure_ascii=False, indent=1)


SCREENS = [
    ("pass", "Exporting a notes app to Markdown loses dates", "Every export drops the created "
     "date; is there a tool that keeps it?",
     '{"pass": true, "reason": "people struggling to export notes with their dates"}'),
    ("drop", "Weekly football results", "Scores from the weekend.",
     '{"pass": false, "reason": "sport results: nothing to do with notes"}'),
    ("fenced-pass", "Sync conflicts after a phone restore", "Two copies of every note.",
     '```json\n{"pass": true, "reason": "sync conflict pain"}\n```'),
    ("prose-drop", "A recipe for bread", "Flour, water, salt.",
     'Not relevant.\n{"pass": false, "reason": "a recipe"}'),
    ("string-false", "Celebrity news", "Gossip.",
     '{"pass": "false", "reason": "gossip"}'),
    ("unreadable", "Plain-text journaling for ten years", "What I learned.",
     "I think this is relevant but cannot say more"),
    ("cut-short", "Backups to a USB stick", "A script that copies the notes folder.",
     '{"pass": true, "reason": "a backup scr'),
    ("no", "Stock prices today", "Markets moved.",
     '{"pass": "no", "reason": "markets"}'),
    ("pass-no-reason", "An open format for outlines", "OPML versus Markdown lists.",
     '{"pass": true}'),
    ("drop-no-reason", "A video game trailer", "Coming next year.", '{"pass": false}'),
]

GOOD = {"summary": "A user reports that exports from a popular notes app drop each note's "
                   "creation date, and asks for a tool that keeps it.",
        "why_it_matters": "Losing dates on export blocks people from moving apps; a small "
                          "exporter that keeps them answers a stated need."}
JUDGES = [
    ("kept-sharp", {**GOOD, "kind": "sharp_signal", "content_quality": 0.8, "durability": 0.6,
                    "opportunity": 0.7, "tags": ["export", "markdown"]}),
    ("kept-mild-fenced", "```json\n" + json.dumps(
        {**GOOD, "kind": "mild_signal", "content_quality": 0.5, "durability": 0.5,
         "opportunity": 0.4}) + "\n```"),
    ("skip", {"skip": True}),
    ("gated", {**GOOD, "kind": "beat", "content_quality": 0.2, "durability": 0.2,
               "opportunity": 0.2}),
    ("override-lifted", {**GOOD, "kind": "mild_signal", "content_quality": 0.3,
                         "durability": 0.3, "opportunity": 0.3, "override": True,
                         "override_reason": "a rare first report of a new export bug"}),
    ("override-refused", {**GOOD, "kind": "beat", "content_quality": 0.05, "durability": 0.1,
                          "opportunity": 0.1, "override": True, "override_reason": "a hunch"}),
    ("no-why", {"summary": "A note.", "kind": "beat", "content_quality": 0.9,
                "durability": 0.9, "opportunity": 0.9}),
    ("cut-short", '{"kind": "sharp_signal", "summary": "A user reports that exp'),
    ("unknown-kind", {**GOOD, "kind": "huge_signal", "content_quality": 0.6, "durability": 0.6,
                      "opportunity": 0.6}),
    ("prose-then-json", "Here is my reading.\n" + json.dumps(
        {**GOOD, "kind": "mild_signal", "content_quality": 0.4, "durability": 0.5,
         "opportunity": 0.5})),
]


def rated(v: float) -> dict:
    return {k: [v, "a reason", [1]] for k in RATINGS}


def card_reply(title: str, **extra) -> str:
    card = {"title": title, "pattern": "A known pattern.", "where_now": "Where it now holds.",
            "thesis": "Why now.", "who": "People who keep notes offline.",
            "smallest_v1": "A one-command exporter.",
            "demand": {"statement": "People ask for it.", "evidence": [
                {"n": 1, "claim": "a user asks for dated exports"}]},
            "evidence": [{"n": 1, "claim": "exports drop dates"},
                         {"n": 2, "claim": "sync conflicts duplicate notes"}],
            "prediction": {"statement": "Someone ships it.", "by": "2027-06-30"},
            "cheapest_test": "Post the exporter on the forum.", "risks": "Small market.",
            "ratings": rated(0.6), **extra}
    return json.dumps({"card": card})


CARDS = [
    ("ok", card_reply("Keep the dates when notes leave an app")),
    ("ok-fenced", "```json\n" + card_reply("A dated Markdown exporter") + "\n```"),
    ("declined", '{"card": null, "why": "the observations do not converge"}'),
    ("malformed-no-evidence", json.dumps({"card": {"title": "No evidence", "evidence": [],
                                                   "ratings": rated(0.5)}})),
    ("malformed-bad-rating", json.dumps({"card": {"title": "Bad rating",
                                                  "evidence": [{"n": 1, "claim": "x"}],
                                                  "ratings": {k: ["high", ""] for k in
                                                              RATINGS}}})),
    ("no-card-key", '{"idea": "something"}'),
    ("ok-v1-fields", card_reply("Insight first", insight="Dates are the data.",
                                gap="Exporters drop them.", moment="Apps now allow export.",
                                mechanism="Read the database, write files.")),
    ("prose", "Sorry, I cannot help with that."),
    ("ok-long-title", card_reply("A" * 200)),
    ("card-string", '{"card": "a title only"}'),
]

OBSERVATIONS = ("[1] example forum, 2026-10-01: exports drop dates (why it mattered: blocks "
                "moving apps)\n[2] example forum, 2026-10-02: sync conflicts duplicate notes "
                "(why it mattered: trust)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    screen = prompts.Prompt("screen", prompts.default_text("screen"))
    judge = prompts.Prompt("judge", prompts.default_text("judge"))
    card = prompts.Prompt("card", prompts.default_text("card"))
    tenets = prompts.tenets()
    rows = {"screen": [], "judge": [], "card": []}
    for i, (name, title, body, reply) in enumerate(SCREENS, 1):
        msgs = [{"role": "system", "content": screen.render(tenets=tenets)},
                {"role": "user", "content": item_text(title, body)}]
        passed, reason = interpret_screen(reply)
        rows["screen"].append({"id": f"screen-{name}", "behaviour": name, "step": "screen",
                               "stage": "watching", "split": "dev" if i % 3 else "held",
                               "model": "fixture", "prompt_version": screen.version,
                               "messages": msgs, "reply": reply,
                               "inputs": {"user": msgs[1]["content"]},
                               "recorded": {"passed": passed, "reason": reason},
                               "owner": None, "usage": {}})
    for i, (name, reply) in enumerate(JUDGES, 1):
        text = reply if isinstance(reply, str) else json.dumps(reply)
        msgs = [{"role": "system", "content": judge.render(tenets=tenets)},
                {"role": "user", "content": item_text("Exports drop dates", "A report.")}]
        outcome, fields = interpret(text, THRESHOLD)
        owner = {"value": "useful", "reasons": [], "at": "2026-10-10"} \
            if name == "kept-sharp" else ({"value": "not_useful", "reasons": ["noise"],
                                           "at": "2026-10-10"} if name == "gated" else None)
        rows["judge"].append({"id": f"judge-{name}", "behaviour": name, "step": "judge",
                              "stage": "watching", "split": "held" if owner or i % 3 == 0
                              else "dev", "model": "fixture", "prompt_version": judge.version,
                              "messages": msgs, "reply": text,
                              "inputs": {"user": msgs[1]["content"]},
                              "recorded": {"outcome": outcome,
                                           "kind": (fields or {}).get("kind")},
                              "owner": owner, "usage": {}})
    for i, (name, reply) in enumerate(CARDS, 1):
        vals = {"observations": OBSERVATIONS, "why_selected": "two sources agree",
                "today": "2026-10-17", "prior_art": NO_PRIOR_ART}
        msgs = [{"role": "user", "content": card.render(**vals)}]
        status, c = parse_card(reply, 2)
        rows["card"].append({"id": f"card-{name}", "behaviour": name, "step": "card",
                             "stage": "ideas", "split": "dev" if i % 3 else "held",
                             "model": "fixture", "prompt_version": card.version,
                             "messages": msgs, "reply": reply, "inputs": vals, "n_inputs": 2,
                             "recorded": {"status": status, "title": (c or {}).get("title")},
                             "owner": None, "usage": {}})
    for step, path in (("screen", "watching/screen.jsonl"), ("judge", "watching/judge.jsonl"),
                       ("card", "ideas/cards.jsonl")):
        p = OUT / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                             for r in rows[step]))
    (OUT / "manifest.json").write_text(json.dumps(
        {"version": "fixtures", "from": "scripts/eval_fixtures.py: synthetic items, no "
                                        "third-party text", "judge_threshold": THRESHOLD,
         "parent": None, "built_at": "fixed"}, indent=1, sort_keys=True) + "\n")
    print(f"wrote {sum(len(v) for v in rows.values())} items to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
