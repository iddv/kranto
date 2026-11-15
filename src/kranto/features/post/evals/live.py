"""A live run of the prose eval, by hand: never in CI, never by a job.

    python -m kranto.features.post.evals.live --home <a scratch kranto home> --budget 3

For each item and site: today's old prompt, then the new writer (compose, the call, check, and
revise of only the flagged spans), then a blind pairwise judgement of the two texts in a
random order. Every call goes through the home's metered client (``llm_calls``), and the run
stops before the next call once the cost (or, on a plan, the list-price estimate) reaches the
budget. It writes ``recorded.json`` beside this file (or ``--out``) and prints the scorecard.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from ....prose import check, revise
from ....prose.reviser import fit
from . import rubric, score, writers

HERE = Path(__file__).parent
# the judge's rubric is the owner's eight rules (P-12; ``rubric.py``): round 1's
# preferred the cautious, complete post the owner rejected


class Budget(Exception):
    pass


class Meter:
    def __init__(self, rt, budget: float) -> None:
        self.rt, self.budget = rt, budget
        self.usd = self.equiv = 0.0
        self.calls = 0

    def spent(self) -> float:
        return max(self.usd, self.equiv)

    def complete(self, *, tier: str, purpose: str, messages: list[dict], schema=None,
                 max_tokens: int = 1200) -> dict:
        if self.spent() >= self.budget:
            raise Budget(f"stopped at ${self.spent():.2f} of ${self.budget:.2f}")
        got = self.rt.llm.complete(tier=tier, purpose=purpose, messages=messages,
                                   prompt_version="prose-eval@1", max_tokens=max_tokens,
                                   temperature=0.2, schema=schema)
        self.calls += 1
        self.usd += float(got.cost_usd or 0)
        self.equiv += float(getattr(got, "equiv_usd", None) or 0)
        return {"text": got.text, "structured": got.structured, "model": got.model}


def run_one(m: Meter, item: dict, site: str, rnd: random.Random, *,
            old_run: dict | None = None, draft: str | None = None) -> tuple[dict, dict]:
    """One item on one site: the old writer (or ``old_run``, its recorded answer: its prompt
    has not changed), the new writer (or its recorded ``draft``, revised again), the judge."""
    old = old_run if old_run is not None else _old(m, item, site)
    new = _new(m, item, site, draft)
    return {"old": old, "new": new}, _judge(m, item, old["text"], new["text"], rnd, site)


def _old(m: Meter, item: dict, site: str) -> dict:
    old_msgs = writers.prompt("old", site, item)
    # the old writers relied on the provider enforcing the schema; a provider that does not
    # (Claude Code here) is told the format in one line, as the new prompts already say it
    fields = "title, excerpt, body" if site == "blog" else "text"
    old_msgs[0] = {**old_msgs[0], "content": old_msgs[0]["content"]
                   + f" Answer JSON with {fields}."}
    old = m.complete(tier="reason", purpose="prose_eval_write", messages=old_msgs,
                     schema=writers.schema(site), max_tokens=1100 if site == "blog" else 200)
    old_text = writers.text_of(site, old["structured"] or old["text"])
    if site == "toot":                 # the old toot cut at the character, as its code did
        old_text = old_text[:writers.ROOM].strip()
    return {"text": old_text, "sha": writers.sha(old_msgs), "model": old["model"]}


def _new(m: Meter, item: dict, site: str, draft: str | None = None) -> dict:
    p = writers.profile()
    new_msgs = writers.prompt("new", site, item)
    model = None
    if draft is None:
        new = m.complete(tier="reason", purpose="prose_eval_write", messages=new_msgs,
                         schema=writers.schema(site), max_tokens=1100 if site == "blog" else 200)
        draft = writers.text_of(site, new["structured"] or new["text"])
        model = new["model"]
    take = writers.take_of(item) or ""
    sname = score.SITE[site]
    limits = {"max_chars": writers.ROOM, "unit": "characters", "links": 0} \
        if site == "toot" else None
    flags = check(draft, sname, p, take=take, limits=limits)["flags"]

    def complete(messages, schema):
        return m.complete(tier="reason", purpose="prose_eval_revise", messages=messages,
                          schema=schema, max_tokens=1500)
    fixed = revise(draft, flags, p, complete=complete, site=sname, take=take, limits=limits)
    final = fixed["text"] if site == "blog" else fit(" ".join(fixed["text"].split()),
                                                     writers.ROOM)
    return {"text": final, "draft": draft, "rounds": fixed["rounds"],
            "changed": fixed["changed"], "sha": writers.sha(new_msgs), "model": model,
            "redrafted": model is None}


def _judge(m: Meter, item: dict, old_text: str, new_text: str, rnd: random.Random,
           site: str = "blog") -> dict:
    order = ["old", "new"]
    rnd.shuffle(order)
    texts = {"old": old_text, "new": new_text}
    take = writers.take_of(item)
    j = m.complete(tier="judge", purpose="prose_eval_judge", schema=rubric.pick_schema(2),
                   messages=rubric.pick_messages(item, [texts[order[0]], texts[order[1]]],
                                                 site, angle=take), max_tokens=300)
    verdict = j["structured"] or _json(j["text"])
    pick = str((verdict or {}).get("pick") or "cant_tell")
    winner = {"A": order[0], "B": order[1]}.get(pick, "tie")
    return {"winner": winner, "order": "-".join(order), "why": (verdict or {}).get("why"),
            "model": j["model"]}


def _json(text: str) -> dict | None:
    import re
    try:
        got = json.loads(re.sub(r"\A\s*```(?:json)?\s*|\s*```\s*\Z", "", text or ""))
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", required=True, help="a scratch kranto home (never live's)")
    ap.add_argument("--budget", type=float, default=3.0, help="stop at this many dollars")
    ap.add_argument("--items", type=int, default=20)
    ap.add_argument("--sites", default="blog,toot")
    ap.add_argument("--out", default=str(HERE / "recorded.json"))
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--kranto.page", help="a checkout of the page to import (the Claude Code "
                                       "provider's claude_print), when it is not installed")
    ap.add_argument("--follow", help="update this recording instead of starting afresh: the "
                                     "old writer's recorded answers are kept (its prompt is "
                                     "frozen); the new writer and the judge run again")
    ap.add_argument("--redraft", default="", help="with --follow: item:site pairs whose "
                                                  "recorded new draft is revised again, not "
                                                  "written again (comma-separated)")
    ap.add_argument("--only", default="", help="item:site pairs to run (comma-separated)")
    a = ap.parse_args(argv)
    if a.kranto_page:
        sys.path.insert(0, str(Path(a.kranto_page).resolve()))
    from .... import config as config_mod
    from ....runtime import open_runtime
    cfg = config_mod.load(Path(a.home), dotenv=True)
    from ....embed import StubEmbedder
    rt = open_runtime(cfg, embedder=StubEmbedder())
    m = Meter(rt, a.budget)
    rnd = random.Random(a.seed)
    out_path = Path(a.out)
    rec: dict = {"runs": {}, "judge": {}}
    before: dict = {}
    if a.follow:
        rec = json.loads(Path(a.follow).read_text(encoding="utf-8"))
        before = rec.get("meta") or {}
    only = {p for p in a.only.split(",") if p}
    redraft = {p for p in a.redraft.split(",") if p}
    stopped = None
    try:
        for item in writers.items()[:a.items]:
            for site in a.sites.split(","):
                pair = f"{item['id']}:{site}"
                if only and pair not in only:
                    continue
                prior = (rec["runs"].get(item["id"]) or {}).get(site) if a.follow else None
                run, judged = run_one(
                    m, item, site, rnd, old_run=prior["old"] if prior else None,
                    draft=prior["new"]["draft"] if prior and pair in redraft else None)
                rec["runs"].setdefault(item["id"], {})[site] = run
                rec["judge"].setdefault(item["id"], {})[site] = judged
                print(f"{item['id']} {site}: judge {judged['winner']}; "
                      f"${m.spent():.3f} after {m.calls} calls", flush=True)
    except Budget as exc:
        stopped = str(exc)
        print(stopped, flush=True)
    finally:
        this = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "provider": cfg.llm.provider_name,
                "models": {t: cfg.llm.model_for(t) for t in ("reason", "judge")},
                "calls": m.calls, "cost_usd": round(m.usd, 4),
                "equiv_usd": round(m.equiv, 4), "budget_usd": a.budget,
                "stopped": stopped, "seed": a.seed}
        if before:
            # a follow-up: the totals add up; each run is listed as it was
            runs = [*(before.get("runs") or [{k: v for k, v in before.items()
                                              if k != "runs"}]),
                    {**this, "only": sorted(only), "redraft": sorted(redraft)}]
            this = {**this, "runs": runs,
                    "calls": sum(r["calls"] for r in runs),
                    "cost_usd": round(sum(r["cost_usd"] for r in runs), 4),
                    "equiv_usd": round(sum(r["equiv_usd"] for r in runs), 4),
                    "budget_usd": round(sum(r["budget_usd"] for r in runs), 2),
                    "stopped": next((r["stopped"] for r in runs if r.get("stopped")), None)}
        rec["meta"] = this
        out_path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        rt.close()
    print(json.dumps(score.scorecard(rec), indent=1))
    return 0 if stopped is None else 2


if __name__ == "__main__":
    sys.exit(main())
