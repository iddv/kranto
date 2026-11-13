"""One model run that holds research tools: the model asks for a read, code
runs it, the answer goes back fenced and labelled, until the model answers or a bound ends the
run. Every step is one call of the metered client (``complete``: a feature's ``ctx.llm.complete``,
so its purposes, tiers and cap apply), recorded in ``llm_calls`` under the run's ``run_uuid``,
so the run's trace is its steps.

The protocol is plain JSON in the reply, so it is the same on every provider (an
OpenAI-style endpoint, Anthropic, the Claude plan): each reply is exactly one object, either a
read ``{"tool": "<name>", "args": {...}}`` or the end ``{"answer": {...}}``. Nothing a reply
says is run but a tool in ``tools``, and every tool is a read written in code: the model holds
no write, ever (``tools`` is the whole list, and the caller's test walks it).

Bounds: ``max_calls`` reads, ``max_usd`` (the calls' cost, or a plan's list-price
equivalent), ``max_seconds``. At a bound the model is told so and asked once more for the answer
from what it has; that run is ``cut_short``. Two replies in a row that are not one JSON object
end the run with no answer.

Every tool's answer is a list of lines, each with a **label** (``web 3``, ``obs 10158``,
``edgar 0001213900-26-109058``): the lines go back inside a fence with their labels, and
``seen`` keeps every line by label, so the answer's citations can only name what the run saw.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..websearch import fenced

ANSWER_CHARS = 6000            # the most of one tool's answer the model is handed


@dataclass(frozen=True)
class Line:
    """One labelled line a tool read: what a citation may name."""

    label: str
    text: str
    url: str | None = None
    date: str | None = None
    kind: str = ""             # web, obs, radar, edgar, broker, page, calendar

    def render(self) -> str:
        parts = [f"[{self.label}]", self.date or "undated", "|", fenced(self.text)]
        if self.url:
            parts += ["|", self.url]
        return " ".join(parts)


@dataclass(frozen=True)
class Tool:
    """A read: its name, what it does in one sentence, its arguments (a JSON schema's
    ``properties``), and the code that runs it: ``run(args) -> (lines, note)``."""

    name: str
    about: str
    args: dict[str, Any]
    run: Callable[[dict[str, Any]], tuple[list[Line], str | None]]
    required: tuple[str, ...] = ()

    def describe(self) -> str:
        args = ", ".join(f"{k}{'' if k in self.required else '?'}: {v.get('type', 'string')}"
                         + (f" ({v['description']})" if v.get("description") else "")
                         for k, v in self.args.items())
        return f"- {self.name}({args}): {self.about}"


@dataclass
class Run:
    answer: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    seen: dict[str, Line] = field(default_factory=dict)
    calls: int = 0              # model calls
    reads: int = 0              # tool calls
    usd: float = 0.0
    call_ids: list[int] = field(default_factory=list)
    cut_short: str | None = None
    error: str | None = None
    seconds: float = 0.0

    def trace(self) -> dict[str, Any]:
        """What the card keeps of its run (no page text: labels and arguments)."""
        return {"steps": self.steps, "calls": self.calls, "reads": self.reads,
                "usd": round(self.usd, 4), "call_ids": self.call_ids,
                "cut_short": self.cut_short, "error": self.error,
                "seconds": round(self.seconds, 1)}


def parse(text: str) -> dict[str, Any]:
    """The reply's one JSON object (a fenced code block or prose around it is tolerated)."""
    text = (text or "").strip()
    try:
        out = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("the reply holds no JSON object") from None
        out = json.loads(text[start:end + 1])
    if not isinstance(out, dict):
        raise ValueError("the reply is not a JSON object")
    return out


def tools_block(tools: dict[str, Tool]) -> str:
    return "\n".join(t.describe() for t in tools.values())


def run(complete: Callable[..., Any], *, prompt: str, tools: dict[str, Tool], purpose: str,
        tier: str, prompt_version: str, run_uuid: str | None = None, max_calls: int = 24,
        max_usd: float | None = 1.5, max_seconds: float = 600.0, max_tokens: int = 3000,
        clock: Callable[[], float] = time.monotonic,
        on_step: Callable[[dict[str, Any]], None] | None = None) -> Run:
    """The loop. ``prompt`` is the whole first message (the ask, the rules, ``tools_block``,
    the protocol and the answer's shape); every later message is a tool's fenced answer."""
    out = Run()
    started = clock()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    bad = 0
    final = False
    while True:
        try:
            reply = complete(purpose=purpose, tier=tier, messages=messages,
                             prompt_version=prompt_version, run_uuid=run_uuid,
                             max_tokens=max_tokens, temperature=0.2, retry_truncated=True)
        except Exception as exc:  # noqa: BLE001 - the run ends with the error in words
            out.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            break
        out.calls += 1
        out.call_ids.append(int(getattr(reply, "call_id", 0) or 0))
        out.usd += float(getattr(reply, "cost_usd", 0.0) or 0.0) or \
            float(getattr(reply, "equiv_usd", 0.0) or 0.0)
        messages.append({"role": "assistant", "content": reply.text})
        try:
            msg = parse(reply.text)
        except ValueError as exc:
            bad += 1
            if bad >= 2 or final:
                out.error = f"no JSON answer: {exc}"
                break
            messages.append({"role": "user", "content": "Your reply was not one JSON object. "
                             "Reply with exactly one JSON object: a tool call or the answer."})
            continue
        bad = 0
        if isinstance(msg.get("answer"), dict):
            out.answer = msg["answer"]
            break
        if final:
            out.error = "the run ended at a bound without an answer"
            break
        name = str(msg.get("tool") or "")
        raw_args = msg.get("args")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        step: dict[str, Any] = {"tool": name, "args": {k: str(v)[:200] for k, v in args.items()}}
        if name not in tools:
            text = (f"There is no tool {fenced(name)[:60]!r}. The tools are: "
                    f"{', '.join(tools)}. Reply with a tool call or the answer.")
            step["error"] = "unknown tool"
        else:
            out.reads += 1
            try:
                lines, note = tools[name].run(args)
            except Exception as exc:  # noqa: BLE001 - a read that failed says so, in words
                lines, note = [], f"the read failed: {type(exc).__name__}: {str(exc)[:200]}"
            for ln in lines:
                out.seen.setdefault(ln.label, ln)
            body = "\n".join(ln.render() for ln in lines)[:ANSWER_CHARS]
            text = (f"<<<tool {name}\n{body or '(nothing found)'}"
                    + (f"\nnote: {fenced(note)}" if note else "") + f"\ntool {name}>>>")
            step.update(labels=[ln.label for ln in lines][:40], note=(note or "")[:200])
        out.steps.append(step)
        if on_step is not None:
            on_step(step)
        elapsed = clock() - started
        limit = None
        if out.reads >= max_calls:
            limit = f"{max_calls} reads"
        elif max_usd is not None and out.usd >= max_usd:
            limit = f"${max_usd:.2f} of model calls"
        elif elapsed >= max_seconds:
            limit = f"{int(max_seconds // 60)} minutes"
        if limit:
            out.cut_short = limit
            final = True
            text += (f"\n\nThe run has reached its bound ({limit}). Reply now with the answer "
                     "from what you have read: {\"answer\": {...}}. No more tool calls.")
        messages.append({"role": "user", "content": text})
    out.seconds = clock() - started
    return out
