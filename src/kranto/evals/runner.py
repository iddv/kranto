"""``kranto eval watching|ideas``: a stage asked again on the frozen set, through the product's own
provider seam, under a budget, into a dated scorecard.

- **The path is the product's:** every call goes through ``LLMClient`` with the configured
  provider (OpenRouter, the Claude API, an endpoint, or the Claude Code login), the same tier,
  schema and reply ceiling the watcher uses, recorded in ``llm_calls`` with purpose
  ``eval_<step>`` and one ``run_uuid`` (Spend shows them as one line, D9). ``--provider`` and
  ``--model`` choose another of the seam's providers and models for the run.
- **What is sent:** the item exactly as recorded, with the system prompt (or the card prompt)
  rendered from the prompt this install uses now, or from a ``--candidate`` file; a candidate
  runs beside the live prompt on the same items and gets its own scorecard.
- **The budget is checked before anything is sent** (an upper bound at list prices) and
  after every call; ``--budget`` caps the run, and the monthly cap still holds.
- **Cached by content:** a reply is kept under ``<home>/evals/cache/`` keyed by provider,
  model, messages and repeat index, so a rerun is free and a run cut off continues.
- **``--repeat 2``** asks every item twice; the self-agreement is the noise floor.
- **The judge** for ideas is one model (Opus by default, ``--judge``) with the rubric in the
  set's ``judges/`` (IQ's build rubric v3), its known blind spot written on the scorecard (D3).

Never under CI."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import pricing, prompts
from ..ideate.cards import parse_card
from ..intern import extract_json_object, interpret, interpret_screen
from . import Refused, home_dir, refuse_under_ci, scorecard, sets

STAGES = {"watching": ("screen", "judge"), "ideas": ("card",)}
TIER = {"screen": "judge", "judge": "judge", "card": "reason"}
DEFAULT_JUDGE = "claude-opus-5-5"
JUDGE_FILE = "build-rubric.v3.md"
MAX_FAILING = 5                   # calls in a row that fail stop the run
JUDGE_BLIND_SPOT = ("The rubric judge (IQ rubric v3) agreed with the owner on 20 of 20 negatives "
                    "and 2 of 4 positives when it was calibrated: a candidate that accepts more "
                    "cards needs the owner's taste test, not this number.")
# An upper bound for the estimate when a recorded call has no usage: tokens in and out
FALLBACK_TOKENS = {"screen": (2500, 120), "judge": (4000, 500), "card": (6000, 1500),
                   "rubric": (6000, 800)}


@dataclass
class Answer:
    text: str | None
    usd: float = 0.0
    ms: int = 0
    cached: bool = False
    error: str | None = None


@dataclass
class Run:
    """What one stage run sends and spends."""
    client: object
    home: Path
    provider: str
    models: dict
    budget: float
    run_uuid: str = field(default_factory=lambda: f"eval-{uuid.uuid4()}")
    spent: float = 0.0
    calls: int = 0
    cached: int = 0
    errors: int = 0
    failing: int = 0
    list_usd: float = 0.0
    latencies: list = field(default_factory=list)

    def ask(self, step: str, messages: list[dict], version: str, *, repeat: int = 0,
            max_tokens: int, tier: str, model: str | None = None,
            schema: dict | None = None) -> Answer:
        model = model or self.models[tier]
        key = hashlib.sha256(json.dumps([self.provider, model, messages, repeat, max_tokens],
                                        sort_keys=True).encode()).hexdigest()[:32]
        path = home_dir(self.home) / "cache" / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text())
            self.cached += 1
            self.list_usd += float(d.get("list_usd") or 0.0)   # what the reply cost once
            return Answer(d["text"], 0.0, int(d.get("ms") or 0), cached=True)
        if self.spent >= self.budget:
            raise Refused(f"the run's budget is spent (${self.spent:.4f} of ${self.budget:g})")
        from ..llm import LLMError
        t0 = time.monotonic()
        try:
            c = self.client.complete(tier=tier, purpose=f"eval_{step}", messages=messages,
                                     prompt_version=version, run_uuid=self.run_uuid,
                                     max_tokens=max_tokens, retry_truncated=True,
                                     schema=schema,
                                     **({"provider": self.provider, "model": model}
                                        if model != self.models.get(tier) else {}))
        except LLMError as e:
            self.errors += 1
            self.failing += 1
            if self.failing >= MAX_FAILING:
                raise Refused(f"{self.failing} calls in a row failed, the last with: "
                              f"{str(e)[:300]}; no scorecard written") from None
            return Answer(None, error=str(e)[:300])
        self.failing = 0
        ms = int((time.monotonic() - t0) * 1000)
        self.spent += float(c.cost_usd or 0.0)
        # what the call costs at the model's list prices (a login's calls record $0)
        listed = float(pricing.cost(c.model or model, input_tokens=c.prompt_tokens,
                                    output_tokens=c.completion_tokens) or 0.0)
        self.list_usd += listed
        self.calls += 1
        self.latencies.append(ms)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": c.text, "ms": ms, "model": c.model,
                                    "usd": c.cost_usd, "list_usd": listed}))
        return Answer(c.text, float(c.cost_usd or 0.0), ms)


# -- what is sent ---------------------------------------------------------------------------------


def prompt_for(step: str, candidate: str | None = None) -> prompts.Prompt:
    """The prompt this install sends now for ``step`` (the owner's additions and override
    included), or the candidate's text."""
    return prompts.Prompt(step, candidate) if candidate is not None else prompts.load(step)


def messages_for(item: dict, prompt: prompts.Prompt) -> list[dict] | None:
    """The recorded item with ``prompt`` rendered as it is rendered for a call; None when the
    item's inputs could not be read back (it was recorded with another prompt)."""
    if item["step"] == "card":
        vals = item.get("inputs")
        return [{"role": "user", "content": prompt.render(**vals)}] if vals else None
    user = (item.get("inputs") or {}).get("user") or next(
        (m["content"] for m in item["messages"] if m["role"] == "user"), None)
    if user is None:
        return None
    return [{"role": "system", "content": prompt.render(tenets=prompts.tenets())},
            {"role": "user", "content": user}]


def tokens_of(item: dict, step: str) -> tuple[int, int]:
    u = item.get("usage") or {}
    fin, fout = FALLBACK_TOKENS[step]
    return int(u.get("in") or fin) + 200, max(int(u.get("out") or 0), fout)


def estimate(items: list[dict], models: dict, repeat: int, judge_model: str | None) -> float:
    """An upper bound in dollars at list prices, nothing cached or read from a prompt cache."""
    total = 0.0
    for it in items:
        tin, tout = tokens_of(it, it["step"])
        total += (pricing.cost(models[TIER[it["step"]]], input_tokens=tin, output_tokens=tout)
                  or 0.01) * repeat
        if it["step"] == "card" and judge_model:
            jin, jout = FALLBACK_TOKENS["rubric"]
            total += (pricing.cost(judge_model, input_tokens=jin, output_tokens=jout) or 0.05) \
                * repeat
    return round(total, 4)


# -- the stages -----------------------------------------------------------------------------------


def judge_items(items: list[dict], answers: dict, threshold: float) -> dict:
    """The watching metrics from the recorded items and the answers (``answers[(id, k)]``)."""
    out: dict = {"screen": [], "judge": []}
    for it in items:
        a = answers.get((it["id"], 0))
        if a is None or a.text is None:
            continue
        if it["step"] == "screen":
            got = interpret_screen(a.text)[0]
            out["screen"].append({"id": it["id"], "want": it["recorded"]["passed"], "got": got,
                                  "kept": it["recorded"].get("outcome") == "contributed"})
        else:
            got, _ = interpret(a.text, threshold)
            owner = (it.get("owner") or {}).get("value")
            out["judge"].append({"id": it["id"], "want": it["recorded"]["outcome"], "got": got,
                                 "owner": owner})
    return out


def noise_of(items: list[dict], answers: dict, threshold: float, repeat: int) -> dict:
    """Self-agreement per step: the same model asked twice, the verdicts compared."""
    if repeat < 2:
        return {}
    out = {}
    for step in ("screen", "judge", "card"):
        same = n = 0
        for it in items:
            if it["step"] != step:
                continue
            a, b = answers.get((it["id"], 0)), answers.get((it["id"], 1))
            if not a or not b or a.text is None or b.text is None:
                continue
            n += 1
            if step == "screen":
                same += interpret_screen(a.text)[0] == interpret_screen(b.text)[0]
            elif step == "judge":
                same += interpret(a.text, threshold)[0] == interpret(b.text, threshold)[0]
            else:
                same += (a.verdict if hasattr(a, "verdict") else None) == \
                    (b.verdict if hasattr(b, "verdict") else None)
        if n:
            out[step] = round(same / n, 3)
    return out


def watching_metrics(res: dict) -> list[dict]:
    m = scorecard.metric
    sc, jd = res["screen"], res["judge"]
    rows = []
    if sc:
        rows += [m("screen_agree", "screen agrees with the recorded verdict",
                   sum(r["want"] == r["got"] for r in sc), len(sc), step="screen"),
                 scorecard.info("screen_drop", "screen drop rate",
                                round(sum(not r["got"] for r in sc) / len(sc), 3),
                                recorded=round(sum(not r["want"] for r in sc) / len(sc), 3))]
        kept = [r for r in sc if r["kept"]]
        if kept:
            rows.append(m("screen_keeps_kept", "screen passes what the live judge kept",
                          sum(r["got"] for r in kept), len(kept), step="screen"))
    if jd:
        rows += [m("judge_agree", "judge agrees with the recorded outcome",
                   sum(r["want"] == r["got"] for r in jd), len(jd), step="judge"),
                 m("judge_kept_agree", "judge keeps what live kept, drops what it dropped",
                   sum((r["want"] == "contributed") == (r["got"] == "contributed") for r in jd),
                   len(jd), step="judge")]
        up = [r for r in jd if r["owner"] == "useful"]
        down = [r for r in jd if r["owner"] == "not_useful"]
        if up:
            rows.append(m("owner_up_kept", "the owner's ▲ observations kept",
                          sum(r["got"] == "contributed" for r in up), len(up), kind="owner",
                          ids=sorted(r["id"] for r in up if r["got"] == "contributed")))
        if down:
            rows.append(m("owner_down_dropped", "the owner's ▼ observations not kept",
                          sum(r["got"] != "contributed" for r in down), len(down), kind="owner",
                          ids=sorted(r["id"] for r in down if r["got"] != "contributed")))
    return rows


def card_doc(card: dict, item: dict) -> tuple[str, str]:
    """The card as the rubric judge reads it, and its sources (the observations it was
    written from)."""
    keep = {k: card.get(k) for k in ("title", "insight", "thesis", "who", "moment", "mechanism",
                                     "smallest_v1", "cheapest_test", "gap", "pattern",
                                     "where_now", "risks") if card.get(k)}
    d = card.get("demand") or {}
    keep["demand"] = d.get("statement") if isinstance(d, dict) else d
    keep["evidence_claims"] = [e.get("claim") for e in card.get("evidence") or []][:8]
    return (json.dumps(keep, ensure_ascii=False, indent=0),
            (item.get("inputs") or {}).get("observations") or "(no sources)")


def rubric_verdict(text: str | None) -> dict:
    d = extract_json_object(text or "") or {}
    tests = d.get("tests") if isinstance(d.get("tests"), dict) else {}
    passes = {k: bool((v or {}).get("pass")) for k, v in tests.items()}
    return {"verdict": d.get("verdict"), "class": d.get("class"), "passes": passes,
            "insight": d.get("insight"), "wedge": d.get("wedge"),
            "reason": str(d.get("reason") or "")[:300]}


def ideas_metrics(rows: list[dict]) -> list[dict]:
    m = scorecard.metric
    out = []
    if not rows:
        return out
    ok = [r for r in rows if r["status"] == "ok"]
    out += [m("card_parses", "the writer's reply is a card or a decline",
              sum(r["status"] in ("ok", "declined") for r in rows), len(rows), step="card"),
            scorecard.info("card_declined", "declined", sum(r["status"] == "declined"
                                                           for r in rows)),
            scorecard.info("card_written", "cards written", len(ok))]
    judged = [r for r in ok if r.get("rubric", {}).get("verdict")]
    if judged:
        out.append(m("card_build", "cards the rubric judge calls a build",
                     sum(r["rubric"]["verdict"] == "build" for r in judged), len(judged),
                     step="card"))
        for gate in ("product_not_feature", "not_absorbed", "broad", "relevant", "lands",
                     "not_shipped"):
            n = sum(1 for r in judged if gate in r["rubric"]["passes"])
            ok = sum(r["rubric"]["passes"].get(gate, False) for r in judged)
            if n:
                out.append(scorecard.info(f"gate_{gate}",
                                          f"gate {gate.replace('_', ' ')} passed", f"{ok}/{n}"))
        for k in ("insight", "wedge"):
            vals = [float(r["rubric"][k]) for r in judged
                    if isinstance(r["rubric"].get(k), int | float)]
            if vals:
                out.append(scorecard.info(f"mean_{k}", f"mean {k} (1 to 5)",
                                          round(statistics.mean(vals), 2)))
    up = [r for r in rows if r["owner"] == "useful"]
    down = [r for r in rows if r["owner"] == "not_useful"]
    if up:
        out.append(m("owner_up_build", "the owner's ▲ cards written and judged a build",
                     sum(r.get("rubric", {}).get("verdict") == "build" for r in up), len(up),
                     kind="owner", ids=sorted(r["id"] for r in up
                                              if r.get("rubric", {}).get("verdict") == "build")))
    if down:
        out.append(m("owner_down_not_build", "the owner's ▼ cards declined or not judged a "
                     "build", sum(r.get("rubric", {}).get("verdict") != "build" for r in down),
                     len(down), kind="owner",
                     ids=sorted(r["id"] for r in down
                                if r.get("rubric", {}).get("verdict") != "build")))
    return out


def load_judge(set_dir: Path, judges: Path | None) -> str:
    for d in ([judges] if judges else []) + [Path(set_dir) / "judges",
                                             Path(set_dir).parent.parent / "judges"]:
        p = Path(d) / JUDGE_FILE
        if p.is_file():
            return p.read_text()
    raise Refused(f"no rubric judge ({JUDGE_FILE}) beside the set: give --judges DIR")


# -- one run --------------------------------------------------------------------------------------


def select(set_dir: Path, steps: tuple[str, ...], split: str, n: int | None) -> list[dict]:
    items = []
    for step in steps:
        got = [i for i in sets.load_items(set_dir, step) if split == "all" or i["split"] == split]
        items += got[:n] if n else got
    return items


def make_client(cfg, store, provider: str | None, model: str | None, reason_model: str | None):
    """The metered client on the configured provider, or another of the seam's (and its
    models in that provider's names)."""
    from ..llm import LLMClient
    from ..providers import models_for
    llm = cfg.llm
    if provider and provider != llm.provider_name:
        llm = replace(llm, provider=provider, tiers={}, models=models_for(provider, llm))
    models = dict(llm.models)
    if model:
        models["judge"] = model
    if reason_model:
        models["reason"] = reason_model
    llm = replace(llm, models=models)
    return LLMClient(store, llm, cfg.budget), llm


def run_stage(stage: str, *, cfg, store, home: Path, set_dir: Path, budget: float,
              split: str = "all", n: int | None = None, repeat: int = 1,
              provider: str | None = None, model: str | None = None,
              reason_model: str | None = None, judge_model: str | None = DEFAULT_JUDGE,
              judges: Path | None = None, candidates: dict | None = None,
              tag: str | None = None, client_for=None, progress=None) -> list[dict]:
    """Run ``stage`` (watching or ideas) on the set; returns the scorecards written (the live
    prompt's, then a candidate's)."""
    if client_for is None:
        refuse_under_ci()
    steps = STAGES[stage]
    items = select(set_dir, steps, split, n)
    if not items:
        raise Refused(f"the set has no {stage} items on split {split}")
    manifest = sets.load_manifest(set_dir)
    threshold = float(manifest.get("judge_threshold", cfg.ingest.signal_threshold))
    if client_for is not None:
        client, llm = client_for(cfg), cfg.llm
    else:
        client, llm = make_client(cfg, store, provider, model, reason_model)
    judge_text = load_judge(set_dir, judges) if stage == "ideas" and judge_model else None
    arms = [("live", {})] + ([("candidate", candidates)] if candidates else [])
    est = estimate(items, llm.models, repeat, judge_model if judge_text else None) * len(arms)
    if est > budget:
        raise Refused(f"{len(items)} items x {repeat} on {llm.models} could cost up to "
                      f"${est:.2f}, over the budget ${budget:g}: lower --n, or raise --budget")
    from ..llm import LLMError
    try:
        client.check_can_spend()            # paused, the month's cap reached, no key: say so
    except LLMError as e:
        if client_for is None:
            client.close()
        raise Refused(f"no call would be sent: {e}") from None
    r = Run(client, home, llm.provider_name, dict(llm.models), budget)
    out = []
    try:
        for arm, cands in arms:
            out.append(_arm(stage, arm, cands or {}, items, r, set_dir, manifest, threshold,
                            repeat, judge_model, judge_text, budget, tag, progress, out))
    finally:
        if client_for is None:
            client.close()
    return out


def _arm(stage, arm, cands, items, r: Run, set_dir, manifest, threshold, repeat, judge_model,
         judge_text, budget, tag, progress, done) -> dict:
    spent0, calls0, cached0, errors0, list0 = r.spent, r.calls, r.cached, r.errors, r.list_usd
    lat0 = len(r.latencies)
    used = {}
    skipped = 0
    answers: dict = {}
    card_rows = []
    for it in items:
        step = it["step"]
        p = prompt_for(step, cands.get(step))
        used[step] = p.version
        msgs = messages_for(it, p)
        if msgs is None:                 # recorded with another prompt: its inputs unread
            skipped += 1
            continue
        for k in range(repeat):
            a = r.ask(step, msgs, p.version, repeat=k,
                      max_tokens=int(it.get("max_tokens") or r.client.max_tokens(step)),
                      tier=TIER[step], schema=prompts.schema(step))
            if step == "card" and a.text is not None:
                status, card = parse_card(a.text, int(it.get("n_inputs") or 0))
                a.verdict = status
                row = {"id": it["id"], "status": status, "title": (card or {}).get("title"),
                       "owner": (it.get("owner") or {}).get("value")} if k == 0 else None
                if card and judge_text:
                    idea, src = card_doc(card, it)
                    j = r.ask("rubric", [{"role": "system", "content": judge_text},
                                         {"role": "user", "content":
                                          f"=== IDEA ===\n{idea[:9000]}\n\n=== SOURCES ===\n"
                                          f"{src[:10000]}\n\n=== END ==="}],
                              f"rubric-{hashlib.sha256(judge_text.encode()).hexdigest()[:8]}",
                              repeat=k, max_tokens=2000, tier="reason", model=judge_model)
                    rv = rubric_verdict(j.text)
                    a.verdict = (status, rv["verdict"])
                    if row is not None:
                        row["rubric"] = rv
                if row is not None:
                    card_rows.append(row)
            answers[(it["id"], k)] = a
            if progress:
                progress(step, it["id"], k, a)
    if stage == "watching":
        res = judge_items(items, answers, threshold)
        metrics = watching_metrics(res)
        detail = res
    else:
        metrics = ideas_metrics(card_rows)
        detail = {"card": card_rows}
    lat = r.latencies[lat0:]
    if skipped:
        metrics.append(scorecard.info("not_replayed", "items recorded with another prompt "
                                      "(their inputs could not be read back)", skipped))
    metrics += [scorecard.info("cost_usd", "cost of the run", round(r.spent - spent0, 4)),
                scorecard.info("list_usd", "its replies at list prices (cached ones too)",
                               round(r.list_usd - list0, 4)),
                scorecard.info("calls", "calls sent (cached)", f"{r.calls - calls0} "
                               f"({r.cached - cached0})"),
                scorecard.info("errors", "calls that failed", r.errors - errors0)]
    if lat:
        metrics.append(scorecard.info("latency_s", "median latency, s",
                                      round(statistics.median(lat) / 1000, 1)))
    card = scorecard.new(stage, set_version=manifest.get("version"),
                         model=r.models.get("judge" if stage == "watching" else "reason"),
                         split="all" if not items else _split(items), budget_usd=budget,
                         tag=(f"{tag}-" if tag else "") + "candidate" if arm == "candidate"
                         else tag, provider=r.provider, run_uuid=r.run_uuid, repeat=repeat,
                         judge=judge_model if stage == "ideas" else None, prompts=used,
                         items=detail, cost_usd=round(r.spent - spent0, 4))
    card["metrics"] = metrics
    noise = noise_of(items, answers, threshold, repeat)
    if noise:
        card["noise"] = noise
    if stage == "ideas" and judge_text:
        card["notes"] = [JUDGE_BLIND_SPOT]
    if arm == "candidate" and done:
        card["candidate_of"] = done[0]["file"]
    return scorecard.finish(Path(r.home), card)


def _split(items: list[dict]) -> str:
    s = {i["split"] for i in items}
    return s.pop() if len(s) == 1 else "all"
