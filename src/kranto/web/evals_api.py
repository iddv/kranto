"""The evaluation's scorecards as JSON, for Settings › System › Evaluation (the
owner's D7: read-only, the runs come from ``kranto eval``).

| Method and path         | Does                                                                 |
|-------------------------|----------------------------------------------------------------------|
| GET /api/evals          | the last ten scorecards (headline, its delta and flag, cost) and    |
|                         | "Live this month" from the ledgers                                   |
| GET /api/evals/{name}   | one scorecard, every metric with its last run, baseline and noise    |

No model call; nothing is written."""

from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..evals import scorecard
from ..store import iso, month_start, utcnow

LAST = 10
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}$")


def _headline(card: dict) -> dict | None:
    m = next((x for x in card.get("metrics") or [] if x.get("kind") == "rate"), None)
    if m is None:
        return None
    return {k: m.get(k) for k in ("key", "label", "num", "den", "value", "last", "baseline",
                                  "noise", "flag")}


def _info(card: dict, key: str):
    return next((x.get("value") for x in card.get("metrics") or [] if x.get("key") == key), None)


def summary(card: dict) -> dict:
    """One row of the list."""
    flags = sorted({m["flag"] for m in card.get("metrics") or [] if m.get("flag")
                    and m["flag"] != "within noise"})
    return {"name": card["_file"].removesuffix(".json"), "date": card.get("date"),
            "at": card.get("at"), "stage": card.get("stage"), "set": card.get("set"),
            "model": card.get("model"), "provider": card.get("provider"),
            "tag": card.get("tag"), "candidate_of": card.get("candidate_of"),
            "headline": _headline(card), "flags": flags,
            "cost_usd": card.get("cost_usd"), "list_usd": _info(card, "list_usd")}


def live(store) -> dict:
    """"Live this month" from the ledgers (the live metrics): what watching kept and what it
    cost, and the cards shown and graded. No model call."""
    from .. import grades
    start = iso(month_start(utcnow()))
    q1 = store.query_one
    watch_usd = q1("SELECT COALESCE(SUM(cost_usd), 0) AS u FROM llm_calls WHERE created_at >= ? "
                   "AND purpose IN ('screen', 'judge', 'deep_dive')", (start,))["u"]
    eval_usd = q1("SELECT COALESCE(SUM(cost_usd), 0) AS u, COUNT(*) AS n FROM llm_calls "
                  "WHERE created_at >= ? AND purpose LIKE 'eval\\_%' ESCAPE '\\'", (start,))
    kept = q1("SELECT COUNT(*) AS n FROM observations WHERE created_at >= ?", (start,))["n"]
    sharp = q1("SELECT COUNT(*) AS n FROM observations WHERE created_at >= ? AND kind = "
               "'sharp_signal'", (start,))["n"]
    ideas = [r["id"] for r in store.query("SELECT id FROM ideas WHERE status = 'shown' AND "
                                          "created_at >= ?", (start,))]
    g = grades.latest(store, "idea", ideas)
    obs_g = [r["value"] for r in store.query(
        "SELECT value FROM feedback WHERE target = 'observation' AND kind = 'grade' AND "
        "created_at >= ? AND value IN ('useful', 'not_useful')", (start,))]
    return {"month": start[:7], "watching_usd": round(float(watch_usd), 4),
            "observations_kept": kept, "sharp_signals": sharp,
            "usd_per_kept": round(float(watch_usd) / kept, 4) if kept else None,
            "observations_graded": len(obs_g),
            "observations_useful": sum(v == "useful" for v in obs_g),
            "cards_shown": len(ideas),
            "cards_useful": sum(1 for v in g.values() if v["grade"] == "useful"),
            "cards_not_useful": sum(1 for v in g.values() if v["grade"] == "not_useful"),
            "eval_usd": round(float(eval_usd["u"]), 4), "eval_calls": eval_usd["n"]}


class EvalsAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def home(self):
        return self.rt.cfg.root

    def index(self, request: Request):
        hist = list(reversed(scorecard.history(self.home())))
        from .. import rowsafe
        return JSONResponse({"scorecards": rowsafe.each(hist[:LAST], summary, "scorecard",
                                                        ident=lambda c: c.get("_file")),
                             "total": len(hist), "live": live(self.rt.store),
                             "run": "kranto eval watching --budget 1 (or ideas, all); the "
                                    "runs come from the command line"})

    def one(self, request: Request):
        name = request.path_params["name"]
        if not NAME.match(name):
            return JSONResponse({"error": "no such scorecard"}, status_code=404)
        card = next((c for c in scorecard.history(self.home())
                     if c["_file"] in (name, name + ".json")), None)
        if card is None:
            return JSONResponse({"error": "no such scorecard"}, status_code=404)
        card.pop("items", None)               # every item's want and got stays in the file
        card["name"] = card.pop("_file").removesuffix(".json")
        return JSONResponse(card)

    def routes(self) -> list[Route]:
        return [Route("/api/evals", self.index), Route("/api/evals/{name}", self.one)]
