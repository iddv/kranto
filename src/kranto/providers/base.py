"""What a model provider is: one request in, one reply or one typed error out.

``LLMClient`` (``llm.py``) keeps everything that is Kranto's business: the pause flag, the
monthly budget, retries and backoff, the cut-off retry, the ``llm_calls`` row and the key
scrub. A provider turns one ``Request`` into the body it sends (``build``), sends it once
(``send``) and returns a ``Reply`` or raises ``ProviderError``. It never retries, records or
sleeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

ErrorKind = Literal["fatal", "transient", "item", "paused"]


@dataclass(frozen=True)
class Request:
    model: str
    messages: list[dict]          # the conversation in the OpenAI shape, system turns included
    max_tokens: int
    temperature: float | None     # a provider may drop it (Anthropic's API must)
    purpose: str                  # the llm_calls purpose (``screen``, ``judge``...)
    schema: dict | None = None    # structured output, when the stage asks and the provider can
    tools: tuple = ()             # server-side tools a provider runs (xAI's x_search)


@dataclass(frozen=True)
class Reply:
    text: str
    model: str | None             # what the provider says it used
    input_tokens: int | None      # total input: uncached + cache write + cache read
    output_tokens: int | None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported_cost_usd: object = None   # the provider's own figure, unchecked (``usage.cost``)
    finish: str = "stop"          # stop | length | refusal | other
    raw: str = ""                 # the whole reply as received; the client scrubs it
    http_status: int | None = None
    structured: dict | None = None
    headers: dict = field(default_factory=dict)


class ProviderError(Exception):
    """One attempt failed. ``kind``: ``fatal`` (a key, payment or model: stop the run),
    ``transient`` (retry, then give up for this run), ``item`` (this request only) or
    ``paused`` (a spend cap or a usage window: nothing more until ``resume_at``)."""

    def __init__(self, message: str, *, kind: ErrorKind, status: int | None = None,
                 retry_after: float | None = None, resume_at: datetime | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.resume_at = resume_at


@dataclass(frozen=True)
class KeyTest:
    """The result of a test that spends nothing (``Provider.test``)."""

    ok: bool
    detail: str
    models: tuple[str, ...] = ()


class Provider(Protocol):
    name: str                         # openrouter | openai_compat | anthropic | claude_code
    billing: Literal["dollars", "plan"]
    cost_source: Literal["provider", "table"]
    label: str                        # where calls go, for messages (a base URL, "Claude Code")
    key_env: str | None               # the environment variable holding its key, if it has one

    def build(self, req: Request) -> dict: ...
    def send(self, body: dict) -> Reply: ...
    def close(self) -> None: ...


# The watcher's own structured calls: their schema goes to the provider only when the owner's
# ``structured`` setting turns it on (``config.STRUCTURED_CALLS``; a literal here, providers
# import no config).
WATCHER_CALLS = ("screen", "judge", "name")


def schema_on(structured: dict, call: str) -> bool:
    """Whether a call's schema is sent for the provider to enforce: a writer's call always
    unless its own entry says no (fix 1: a blog post asked for in a schema
    came back as prose on the Claude Code login), the watcher's calls only when turned on."""
    if call in structured:
        return bool(structured[call])
    return call not in WATCHER_CALLS
