"""``afk provider replay``: 6's measurement, run by whoever has an Anthropic key.

The newest recorded screens and judges of this library (whatever served them) are asked
again, exactly as recorded, through the Claude API in three variants:

- ``plain``: no prompt cache, no schema;
- ``cache``: the system prompt cached (today's default);
- ``structured``: cached, the reply schema-enforced (``prompts/*.schema.json``), and
  ``effort: low`` on screens.

For each variant it reports agreement with the recorded verdicts (the screen's pass or
drop; the judge's kept or not, and its exact outcome), cache reads, input and output tokens
and cost per call, and p50 latency. Every call goes through the metered client: recorded in
``llm_calls`` (purpose ``replay_screen`` / ``replay_judge``), counted against the budget.
Before anything is sent, an estimate at list prices without the cache is checked against
``max_usd``. Nothing is changed: the result says which settings the numbers support.
"""

from __future__ import annotations

import json
import statistics
import uuid
from dataclasses import dataclass, field, replace

from .. import pricing, prompts
from ..config import Config
from ..intern import interpret, interpret_screen
from ..store import Store
from ..stored.observations import LlmRequest

VARIANTS = ("plain", "cache", "structured")
PURPOSES = ("screen", "judge")


@dataclass
class Sample:
    id: int
    purpose: str
    messages: list[dict]
    max_tokens: int
    prompt_version: str
    recorded: str
    prompt_tokens: int
    completion_tokens: int


@dataclass
class Tally:
    calls: int = 0
    errors: int = 0
    agree: dict = field(default_factory=lambda: {"screen": [0, 0], "judge": [0, 0],
                                                 "judge_exact": [0, 0]})
    cache_read: list = field(default_factory=list)
    input: list = field(default_factory=list)
    output: list = field(default_factory=list)
    cost: list = field(default_factory=list)
    latency: list = field(default_factory=list)


def _messages(request: dict) -> list[dict] | None:
    """A recorded request as OpenAI-shape turns, system first, whichever provider sent it."""
    if isinstance(request.get("messages"), list) and "prompt" not in request:
        turns = [m for m in request["messages"] if isinstance(m, dict)]
        system = request.get("system")
        if isinstance(system, list):                       # the Claude API's blocks
            text = "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
            turns = [{"role": "system", "content": text}, *turns]
        elif isinstance(system, str) and system:
            turns = [{"role": "system", "content": system}, *turns]
        return turns
    if "prompt" in request:                                # Claude Code
        return [{"role": "system", "content": request.get("system") or ""},
                {"role": "user", "content": request["prompt"]}]
    return None


def _reply_text(response: str | None) -> str | None:
    """The text of a recorded reply, whichever provider sent it."""
    try:
        r = json.loads(response or "")
    except ValueError:
        return None
    if not isinstance(r, dict):
        return None
    if isinstance(r.get("choices"), list) and r["choices"]:
        return ((r["choices"][0] or {}).get("message") or {}).get("content")
    if isinstance(r.get("content"), list):
        return "".join(b.get("text", "") for b in r["content"]
                       if isinstance(b, dict) and b.get("type") == "text")
    if isinstance(r.get("structured_output"), dict):
        return json.dumps(r["structured_output"])
    return r.get("result") if isinstance(r.get("result"), str) else None


def sample(store: Store, screens: int, judges: int) -> list[Sample]:
    out = []
    for purpose, n in (("screen", screens), ("judge", judges)):
        for row in store.query(
                "SELECT id, request, response, prompt_version, prompt_tokens, completion_tokens "
                "FROM llm_calls WHERE purpose = ? AND status = 'ok' ORDER BY id DESC LIMIT ?",
                (purpose, n)):
            req = LlmRequest.load(row["request"]).extra
            if not req:
                continue
            msgs, text = _messages(req), _reply_text(row["response"])
            if not msgs or text is None:
                continue
            out.append(Sample(row["id"], purpose, msgs, int(req.get("max_tokens") or 1000),
                              row["prompt_version"], text, int(row["prompt_tokens"] or 0),
                              int(row["completion_tokens"] or 0)))
    return out


def estimate(samples: list[Sample], model: str) -> float:
    """An upper bound: every variant at list price, nothing read from the cache."""
    one = sum(pricing.cost(model, input_tokens=s.prompt_tokens + 1500,
                           output_tokens=max(s.completion_tokens, 400)) or 0.0 for s in samples)
    return one * len(VARIANTS)


def _verdict(purpose: str, text: str, threshold: float) -> tuple[str, str]:
    """(kept or not, exact outcome) for a judge; (pass or drop, same) for a screen."""
    if purpose == "screen":
        passed = interpret_screen(text)[0]
        return ("pass" if passed else "drop",) * 2
    outcome, _ = interpret(text, threshold)
    return ("kept" if outcome == "contributed" else "not kept"), outcome


def variant_config(cfg: Config, variant: str):
    from . import models_for
    llm = cfg.llm
    a = replace(llm.anthropic, cache=variant != "plain",
                structured={"screen": True, "judge": True} if variant == "structured" else {},
                effort={"screen": "low"} if variant == "structured" else {})
    return replace(llm, provider="anthropic", tiers={}, anthropic=a,
                   models=models_for("anthropic", llm))


def run(cfg: Config, store: Store, samples: list[Sample], *, client_for=None,
        progress=None) -> dict:
    """Ask every sample in every variant; returns the tallies by variant."""
    from ..llm import LLMClient, LLMError
    run_uuid = f"replay-{uuid.uuid4()}"
    threshold = cfg.ingest.signal_threshold
    out = {}
    for variant in VARIANTS:
        llm_cfg = variant_config(cfg, variant)
        client = client_for(llm_cfg) if client_for else LLMClient(store, llm_cfg, cfg.budget)
        t = Tally()
        try:
            for s in samples:
                schema = prompts.schema(s.purpose) if variant == "structured" else None
                try:
                    c = client.complete(tier="judge", purpose=f"replay_{s.purpose}",
                                        messages=s.messages, prompt_version=s.prompt_version,
                                        run_uuid=run_uuid, max_tokens=s.max_tokens,
                                        retry_truncated=True, schema=schema)
                except LLMError:
                    t.errors += 1
                    continue
                t.calls += 1
                row = store.query_one("SELECT latency_ms, cache_read_tokens FROM llm_calls "
                                      "WHERE id = ?", (c.call_id,))
                t.cache_read.append(row["cache_read_tokens"] or 0)
                t.latency.append(row["latency_ms"] or 0)
                t.input.append(c.prompt_tokens or 0)
                t.output.append(c.completion_tokens or 0)
                t.cost.append(c.cost_usd)
                was, was_exact = _verdict(s.purpose, s.recorded, threshold)
                now, now_exact = _verdict(s.purpose, c.text, threshold)
                t.agree[s.purpose][0] += was == now
                t.agree[s.purpose][1] += 1
                if s.purpose == "judge":
                    t.agree["judge_exact"][0] += was_exact == now_exact
                    t.agree["judge_exact"][1] += 1
                if progress:
                    progress(variant, s)
        finally:
            if not client_for:
                client.close()
        out[variant] = t
    return out


def summary(tallies: dict) -> dict:
    """The numbers, by variant, and what they support."""
    rows = {}
    for variant, t in tallies.items():
        rows[variant] = {
            "calls": t.calls, "errors": t.errors,
            "screens_agree": t.agree["screen"], "judges_agree": t.agree["judge"],
            "judges_exact": t.agree["judge_exact"],
            "cache_read_per_call": round(statistics.mean(t.cache_read), 1) if t.cache_read else 0,
            "input_per_call": round(statistics.mean(t.input), 1) if t.input else 0,
            "output_per_call": round(statistics.mean(t.output), 1) if t.output else 0,
            "usd_per_call": round(statistics.mean(t.cost), 7) if t.cost else 0,
            "usd_total": round(sum(t.cost), 6),
            "latency_p50_ms": int(statistics.median(t.latency)) if t.latency else 0,
        }
    s, c = rows.get("structured"), rows.get("cache")
    support = []
    if s and c and s["calls"] and c["calls"]:
        def held(key):
            return s[key][1] and s[key][0] >= c[key][0]
        if held("judges_agree") and held("screens_agree"):
            support.append("structured outputs for judge and name agree at least as often as "
                           "without: turn on llm.anthropic.structured.judge and .name")
        if s["output_per_call"] < c["output_per_call"] and held("screens_agree"):
            support.append("effort low on screens cut output tokens with the same screen "
                           "verdicts: set llm.anthropic.effort.screen: low")
    return {"variants": rows, "supports": support}
