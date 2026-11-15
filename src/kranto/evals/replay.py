"""``kranto eval replay``: the free half of. Recorded replies (cassettes) replayed
through the current code, with no model and no network: does the code still draw the verdicts
it drew when the call was made? And is the shipped prompt still the one they were recorded
with? A changed verdict is a regression in parsing, gates or scoring; a changed prompt is not
an error, it names the step whose real eval is due.

- screen: ``interpret_screen(reply)`` passes or drops as recorded;
- judge: ``interpret(reply, threshold)`` gives the recorded outcome (skipped, gated,
  contributed);
- card: ``parse_card(reply, n)`` gives the recorded status and title;
- prompt assembly: the recorded system message equals the shipped template rendered with the
  shipped TENETS (screen, judge), or the recorded card prompt reads back through the shipped
  template (card)."""

from __future__ import annotations

from pathlib import Path

from .. import prompts
from ..ideate.cards import parse_card
from ..intern import interpret, interpret_screen
from . import sets


def verdict(step: str, item: dict, threshold: float):
    """What the current code draws from the item's recorded reply, and what it drew then."""
    if step == "screen":
        return interpret_screen(item["reply"])[0], item["recorded"]["passed"]
    if step == "judge":
        return interpret(item["reply"], threshold)[0], item["recorded"]["outcome"]
    status, card = parse_card(item["reply"], int(item.get("n_inputs") or 0))
    return [status, (card or {}).get("title")], [item["recorded"]["status"],
                                                 item["recorded"]["title"]]


def check_step(items: list[dict], step: str, threshold: float) -> dict:
    same, diffs = 0, []
    for it in items:
        now, then = verdict(step, it, threshold)
        if now == then:
            same += 1
        else:
            diffs.append({"id": it["id"], "recorded": then, "now": now})
    return {"n": len(items), "same": same, "changed": len(diffs), "diffs": diffs[:20]}


def drift(items: list[dict], step: str) -> dict:
    """Is the shipped prompt the one these cassettes were recorded with?"""
    shipped = prompts.Prompt(step, prompts.default_text(step))
    recorded = sorted({it["prompt_version"] for it in items if it.get("prompt_version")})
    out = {"recorded": recorded, "shipped": shipped.version,
           "due": bool(items) and shipped.version not in recorded}
    if step in ("screen", "judge"):
        rendered = shipped.render(tenets=prompts.tenets())
        systems = {m["content"] for it in items for m in it["messages"] if m["role"] == "system"}
        out["assembly"] = rendered in systems if systems else None
    else:
        out["assembly"] = any(it.get("inputs") for it in items) if items else None
    return out


def run(set_dir: Path) -> dict:
    """``{"steps": {step: {"parse", "prompt"}}, "changed", "due"}``."""
    m = sets.load_manifest(set_dir)
    thr = float(m.get("judge_threshold", 0.03))
    steps = {}
    for step in sets.STEPS:
        items = sets.load_items(set_dir, step)
        steps[step] = {"parse": check_step(items, step, thr), "prompt": drift(items, step)}
    return {"set": m.get("version"), "steps": steps,
            "changed": sum(s["parse"]["changed"] for s in steps.values()),
            "due": [s for s, r in steps.items() if r["prompt"]["due"]]}


def words(report: dict) -> str:
    lines = [f"Replay of set {report['set']} through this Kranto (no model, no network):"]
    for step, r in report["steps"].items():
        p, d = r["parse"], r["prompt"]
        lines.append(f"  {step:6} {p['same']}/{p['n']} verdicts as recorded"
                     + (f", {p['changed']} changed" if p["changed"] else "")
                     + ("; the shipped prompt is new since: its eval is due"
                        if d["due"] else "; the shipped prompt is the one recorded"))
        for x in p["diffs"][:5]:
            lines.append(f"         {x['id']}: recorded {x['recorded']!r}, now {x['now']!r}")
    lines.append(f"verdicts changed: {report['changed']}; real eval due for: "
                 f"{', '.join(report['due']) or 'nothing'}")
    return "\n".join(lines)
