"""The user's Claude Code login as the watcher's model: ``claude -p`` through
the page's ``host_api.claude_print``, which gives the model no tool, no MCP server and no
settings, pipes Kranto's token (or lets claude use its own login) and refuses a session that
started with a tool. Offered only as an explicit choice, never the default, with
``TERMS`` shown where it is chosen (the owner's D2).

Billing is the plan: a call's ``cost_usd`` is 0 and the CLI's list-price estimate
(``total_cost_usd``) is kept as ``equiv_usd`` (D10). When a usage window closes ("You've hit
your session limit · resets 3:45pm"), watching pauses until the reset time it names, else for
an hour (D8): nothing is consumed and nothing fails. An expired login stops the run with the
command to run. The exact shape of a usage-limit result is unverified until one happens: any
error result is kept, scrubbed, in the call's row.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from .base import ProviderError, Reply, Request, schema_on

TERMS = ("Claude Code as the watching model uses your Claude plan's usage, shared with your own "
         "Claude Code; when a usage window closes, watching pauses until it "
         "reopens. Anthropic's terms describe subscription login as meant for ordinary, "
         "individual use and ask developers building products to use API keys.")
MIN_VERSION = (2, 1, 300)
LIMIT = re.compile(r"hit your .{0,40}limit|usage limit reached", re.I)
RESETS = re.compile(r"resets\s+(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+)?(\d{1,2})(?::(\d{2}))?"
                    r"\s*(am|pm)?", re.I)
LOGIN = re.compile(r"login expired|run /login|not logged in|invalid api key|oauth token "
                   r"(has )?expired|authentication_error|please log in", re.I)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CALL_OF_PURPOSE = {"deep_dive": "judge"}


def resume_time(text: str, now: datetime) -> datetime:
    """When a closed usage window reopens, from the CLI's words ("resets 3:45pm", "resets Mon
    12:00am", in this machine's time); an hour from ``now`` when it names none."""
    now = now.astimezone()
    m = RESETS.search(text or "")
    if not m:
        return now + timedelta(hours=1)
    day, hour, minute, half = m.group(1), int(m.group(2)), int(m.group(3) or 0), m.group(4)
    if half:
        hour = hour % 12 + (12 if half.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return now + timedelta(hours=1)
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day:
        at += timedelta(days=(DAYS.index(day.lower()) - at.weekday()) % 7)
        if at <= now:
            at += timedelta(days=7)
    elif at <= now:
        at += timedelta(days=1)
    return at


def host_api():
    """The page's host API, or None without a version of the page that has ``claude_print``."""
    import importlib
    try:
        api = importlib.import_module("kranto.page.host_api")
        api.claude_print                                        # noqa: B018 - is it there
    except (ImportError, AttributeError):
        return None
    return api


def _runner() -> Callable[..., dict]:
    api = host_api()
    if api is None:
        raise ProviderError("Claude Code as the watching model needs the page with "
                            "host_api.claude_print (update Kranto)", kind="fatal")
    return api.claude_print


class ClaudeCodeProvider:
    name = "claude_code"
    billing = "plan"
    cost_source = "provider"
    label = "Claude Code"
    key_env = None

    def __init__(self, *, cwd: str, home: str, structured: dict | None = None,
                 sandbox: bool = False, timeout: float = 180.0,
                 run: Callable[..., dict] | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.cwd, self.home = cwd, home
        self.structured = dict(structured or {})
        self.sandbox, self.timeout = sandbox, timeout
        self._run = run
        self._clock = clock or (lambda: datetime.now().astimezone())

    def build(self, req: Request) -> dict:
        system = "\n\n".join(m["content"] for m in req.messages
                             if m.get("role") == "system" and m.get("content"))
        turns = [m for m in req.messages if m.get("role") in ("user", "assistant")]
        prompt = turns[0]["content"] if len(turns) == 1 else "\n\n".join(
            f"{m['role'].upper()}:\n{m['content']}" for m in turns)
        body = {"model": req.model, "system": system, "prompt": prompt,
                "max_tokens": req.max_tokens}
        # a writer's schema always goes as --json-schema (fix 1: Write a post
        # came back as prose and wrote nothing); the watcher's calls when turned on
        if req.schema is not None and schema_on(self.structured,
                                                CALL_OF_PURPOSE.get(req.purpose, req.purpose)):
            body["schema"] = req.schema
        return body

    def send(self, body: dict) -> Reply:
        run = self._run or _runner()
        try:
            out = run(body["prompt"], system=body["system"], model=body["model"],
                      schema=body.get("schema"), timeout=self.timeout, cwd=self.cwd,
                      sandbox=self.sandbox, kranto_home=self.home)
        except ProviderError:
            raise
        except Exception as exc:                        # noqa: BLE001 - mapped by its kind
            kind = getattr(exc, "kind", None)
            if kind is None:
                raise
            raise self._failure(kind, str(exc), getattr(exc, "text", "") or "") from None
        if out.get("is_error"):
            raise self._failure("result", str(out.get("result") or out.get("subtype") or
                                              "claude -p reported an error"), "", out)
        structured = out.get("structured_output")
        structured = structured if isinstance(structured, dict) else None
        text = json.dumps(structured, ensure_ascii=False) if structured is not None \
            else str(out.get("result") or "")
        usage = out.get("usage") if isinstance(out.get("usage"), dict) else {}
        read = _int(usage.get("cache_read_input_tokens")) or 0
        write = _int(usage.get("cache_creation_input_tokens")) or 0
        uncached = _int(usage.get("input_tokens"))
        models = list((out.get("modelUsage") or {}).keys())
        return Reply(
            text=text,
            model=models[0] if len(models) == 1 else (out.get("init") or {}).get("model"),
            input_tokens=None if uncached is None else uncached + read + write,
            output_tokens=_int(usage.get("output_tokens")),
            cache_read_tokens=read,
            cache_write_tokens=write,
            reported_cost_usd=out.get("total_cost_usd"),
            raw=json.dumps({k: v for k, v in out.items() if k != "env"}, ensure_ascii=False),
            structured=structured,
        )

    def _failure(self, kind: str, message: str, text: str,
                 out: dict | None = None) -> ProviderError:
        words = f"{message} {text}"
        if kind == "missing":
            return ProviderError(message, kind="fatal")
        if kind == "tools":
            return ProviderError(f"refused: {message}", kind="fatal")
        if kind == "timeout":
            return ProviderError(message, kind="transient")
        if LIMIT.search(words):
            return ProviderError(f"Claude Code usage limit: {message}", kind="paused",
                                 resume_at=resume_time(words, self._clock()))
        if LOGIN.search(words):
            return ProviderError(f"{message.strip()}: run 'claude /login' (or give Kranto "
                                 "CLAUDE_CODE_OAUTH_TOKEN from 'claude setup-token')",
                                 kind="fatal")
        if kind == "result":
            return ProviderError(f"claude -p: {message}", kind="item")
        return ProviderError(message, kind="transient")

    def close(self) -> None:
        pass


def version_ok(version: str | None) -> bool:
    try:
        return tuple(int(x) for x in (version or "").split(".")[:3]) >= MIN_VERSION
    except ValueError:
        return False


def _int(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
