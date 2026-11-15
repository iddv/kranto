"""The attention budget's counting script and its allowlist,
shared by tests/page/test_browser_budget.py (every route of the fake app) and the functional suite
(tests/page/functional/browser.py: once a case, on a scratch Kranto).

``count(page, route, phone)`` runs tests/page/budget.js in the page and returns the findings no entry of
tests/page/budget_allow.json allows, each "check (rule) where: text", and counts the entries it used in
``USED``. An entry names the check ("*" for every check), where (routes starting "#/", a trailing
"*" for a route and everything under it, or CSS selectors the finding's element sits in), an
optional pattern its text must match, and why."""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
JS = (HERE / "budget.js").read_text()
ALLOW: list[dict] = json.loads((HERE / "budget_allow.json").read_text())
USED: dict[int, int] = {}


def split(where: str) -> tuple[list[str], list[str]]:
    parts = [w.strip() for w in (where or "").split(",") if w.strip()]
    return [p for p in parts if p.startswith("#/")], [p for p in parts if not p.startswith("#/")]


def for_js() -> list[dict]:
    """the entries as budget.js matches them: by the finding's element (selectors)"""
    return [{"check": a["check"], "pattern": a.get("pattern"), "sel": split(a.get("where", ""))[1]} for a in ALLOW]


def _route_in(route: str, rs: list[str]) -> bool:
    here = ("#/" + route.lstrip("#/")).split("?")[0]
    return any(here == r.split("?")[0] or (r.endswith("*") and here.startswith(r.rstrip("*"))) for r in rs)


def allowed(f: dict, route: str) -> int:
    """the entry that allows a finding: budget.js's (its element), else a route's; -1: none"""
    if f.get("allowed", -1) >= 0:
        return f["allowed"]
    for i, a in enumerate(ALLOW):
        rs, sels = split(a.get("where", ""))
        if sels and not rs:
            continue
        if a["check"] not in (f["check"], "*") or (a.get("pattern") and not re.search(a["pattern"], f["text"])):
            continue
        if not rs or _route_in(route, rs):
            return i
    return -1


def count(page, route: str, phone: bool = False) -> list[str]:
    bad = []
    for f in page.evaluate(JS, {"phone": phone, "allow": for_js()}):
        i = allowed(f, route)
        if i >= 0:
            USED[i] = USED.get(i, 0) + 1
        else:
            bad.append(f"{f['check']} ({f['rule']}) {f['where']}: {f['text']}")
    return bad


def report() -> list[str]:
    """each used entry, with its why (printed by the tests that count)"""
    return [f"budget_allow #{i} ({ALLOW[i]['check']} at {ALLOW[i].get('where', 'everywhere')}) used {n}×: {ALLOW[i]['why']}"
            for i, n in sorted(USED.items())]
