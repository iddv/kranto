"""Scorecards: one per run, ``.json`` (every item's want and got, so two runs can
be diffed) and ``.md`` (one table), in ``<home>/evals/scorecards/``, and a line in
``SCOREBOARD.md``.

A scorecard's ``metrics`` are rows ``{key, label, num, den, value, kind}``: ``kind`` is
``rate`` (num of den agree; compared with the last run and the baseline), ``owner`` (agreement
with the owner's grades: small n, only ever "changed" with the ids, never a verdict), or
``info`` (a drop rate, a cost: shown, never flagged).

**The baseline** is the first scorecard on the same stage, set and model (another can be
pinned with ``kranto eval baseline``). **The noise floor** is the baseline's self-agreement,
measured with ``--repeat 2`` (a rate per step). A rate that moved by less than ``1 - noise``
is "within noise"; a drop larger than that is ``REGRESSION``, a rise ``better``. Without a
measured noise floor the delta is shown and nothing is flagged. A flag blocks nothing."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

BASELINE_FILE = "baseline.json"


def root(home: Path) -> Path:
    return Path(home) / "evals" / "scorecards"


def rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def metric(key: str, label: str, num: int, den: int, kind: str = "rate", **extra) -> dict:
    return {"key": key, "label": label, "num": int(num), "den": int(den),
            "value": rate(num, den), "kind": kind, **extra}


def info(key: str, label: str, value, **extra) -> dict:
    return {"key": key, "label": label, "value": value, "kind": "info", **extra}


def slug(*parts: str) -> str:
    return "-".join(re.sub(r"[^A-Za-z0-9.]+", "-", p).strip("-") for p in parts if p)


def history(home: Path) -> list[dict]:
    """Every scorecard, oldest first."""
    out = []
    for p in sorted(root(home).glob("*.json")):
        if p.name == BASELINE_FILE:
            continue
        try:
            card = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(card, dict) and card.get("stage"):
            card["_file"] = p.name
            out.append(card)
    return sorted(out, key=lambda c: (c.get("at") or "", c["_file"]))


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("stage", "set", "model", "judge"))


def pinned(home: Path) -> dict:
    try:
        return json.loads((root(home) / BASELINE_FILE).read_text())
    except (OSError, ValueError):
        return {}


def pin(home: Path, name: str) -> dict:
    """``kranto eval baseline <scorecard>``: this scorecard is its stage's baseline."""
    card = next((c for c in history(home) if c["_file"] in (name, name + ".json")), None)
    if card is None:
        raise ValueError(f"no scorecard {name!r} in {root(home)}")
    p = pinned(home)
    p[slug(card["stage"], card.get("set") or "", card.get("model") or "")] = card["_file"]
    (root(home) / BASELINE_FILE).write_text(json.dumps(p, indent=1, sort_keys=True) + "\n")
    return card


def baseline_for(home: Path, card: dict, hist: list[dict]) -> dict | None:
    want = pinned(home).get(slug(card["stage"], card.get("set") or "", card.get("model") or ""))
    if want:
        hit = next((c for c in hist if c["_file"] == want), None)
        if hit:
            return hit
    return next((c for c in hist if _same(c, card) and not c.get("candidate_of")), None)


def _value(card: dict | None, key: str):
    for m in (card or {}).get("metrics") or []:
        if m["key"] == key:
            return m.get("value")
    return None


def flag(m: dict, base: dict | None, noise: dict) -> str:
    if m["kind"] == "owner":
        was = {i for i in (_metric(base, m["key"]) or {}).get("ids") or []}
        return "changed" if base and was != set(m.get("ids") or []) else ""
    if m["kind"] != "rate" or m.get("value") is None:
        return ""
    b, n = _value(base, m["key"]), noise.get(m.get("step") or "")
    if b is None or n is None:
        return ""
    floor = round(1 - float(n), 3)
    delta = round(m["value"] - b, 3)
    if abs(delta) <= floor:
        return "within noise"
    return "REGRESSION" if delta < 0 else "better"


def _metric(card: dict | None, key: str) -> dict | None:
    return next((m for m in (card or {}).get("metrics") or [] if m["key"] == key), None)


def finish(home: Path, card: dict) -> dict:
    """Fill ``card``'s comparisons (last run, baseline, noise, flags), write it and its line."""
    hist = history(home)
    last = next((c for c in reversed(hist) if _same(c, card)), None)
    base = baseline_for(home, card, hist)
    noise = card.get("noise") or (base or {}).get("noise") or {}
    for m in card["metrics"]:
        m["last"] = _value(last, m["key"])
        m["baseline"] = _value(base, m["key"])
        m["noise"] = noise.get(m.get("step") or "") if m["kind"] == "rate" else None
        m["flag"] = flag(m, base, noise)
    card["last_run"] = (last or {}).get("_file")
    card["baseline"] = (base or {}).get("_file") or "this run"
    name = slug(card["date"], card["stage"], card.get("set") or "", card.get("model") or "",
                card.get("tag") or "")
    d = root(home)
    d.mkdir(parents=True, exist_ok=True)
    k, path = 1, d / f"{name}.json"
    while path.exists():
        k += 1
        path = d / f"{name}-{k}.json"
    card["file"] = path.name
    path.write_text(json.dumps(card, indent=1, sort_keys=True, default=str) + "\n")
    path.with_suffix(".md").write_text(markdown(card))
    board(home, card)
    return card


def _cell(v) -> str:
    if v is None:
        return ""
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def markdown(card: dict) -> str:
    head = (f"# Scorecard: {card['stage']}, {card['date']} (set {card.get('set')}, "
            f"{card.get('model')}, split {card.get('split')}, budget "
            f"${float(card.get('budget_usd') or 0):g})")
    lines = [head, "", "| metric | value | last run | baseline | noise | flag |",
             "|---|---|---|---|---|---|"]
    for m in card["metrics"]:
        if m["kind"] == "info":
            v = m["value"]
            val = f"${v:.3f}" if m["key"].endswith("usd") and isinstance(v, int | float) \
                else _cell(v)
        elif m["kind"] == "owner":
            val = f"{m['num']}/{m['den']}"
        else:
            val = f"{m['num']}/{m['den']} {_cell(m['value'])}"
        lines.append(f"| {m['label']} | {val} | {_cell(m.get('last'))} | "
                     f"{_cell(m.get('baseline'))} | {_cell(m.get('noise'))} | "
                     f"{m.get('flag') or ''} |")
    for note in card.get("notes") or []:
        lines += ["", note]
    used = ", ".join(f"{k} {v}" for k, v in sorted((card.get("prompts") or {}).items()))
    lines += ["", f"Prompts: {used}.",
              f"Baseline: {card.get('baseline')}; last run: {card.get('last_run') or 'none'}."]
    return "\n".join(lines) + "\n"


def board(home: Path, card: dict) -> None:
    """One line in ``SCOREBOARD.md``: date, stage, set, model, prompts, headline, cost, flags."""
    p = root(home).parent / "SCOREBOARD.md"
    if not p.exists():
        p.write_text("# Scoreboard\n\n| date | stage | set | model | prompts | headline | cost "
                     "| flags | scorecard |\n|---|---|---|---|---|---|---|---|---|\n")
    head = next((m for m in card["metrics"] if m["kind"] == "rate"), None)
    flags = sorted({m["flag"] for m in card["metrics"] if m.get("flag")
                    and m["flag"] != "within noise"})
    with p.open("a") as f:
        f.write(f"| {card['date']} | {card['stage']} | {card.get('set')} | {card.get('model')} "
                f"| {' '.join(sorted((card.get('prompts') or {}).values()))} | "
                + (f"{head['label']} {head['num']}/{head['den']}" if head else "") + " | "
                + f"${float(card.get('cost_usd') or 0):.3f} | {', '.join(flags)} | "
                + f"{card['file']} |\n")


def new(stage: str, *, set_version: str | None, model: str | None, split: str,
        budget_usd: float, tag: str | None = None, **extra) -> dict:
    now = datetime.now(UTC)
    return {"stage": stage, "date": now.strftime("%Y-%m-%d"),
            "at": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "set": set_version, "model": model,
            "split": split, "budget_usd": budget_usd, "tag": tag, "metrics": [], **extra}
