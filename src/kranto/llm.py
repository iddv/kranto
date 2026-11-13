"""The metered LLM client. Every model call in the server goes through here.

Before each call: the pause flag and the monthly budget are checked. After
each call, successful or not, one ``llm_calls`` row records the request, the
raw response, tokens, cost and outcome. Nothing spends outside this path.

Failure classes are deliberate:

- ``FatalLLMError``: authentication, payment, or a missing model (401, 402,
  403, 404). Retrying cannot help and continuing would only record the same
  failure against every item, so callers stop the run. In Parallax a dead key
  was retried per item and reported as success for three months.
- ``TransientLLMError``: 429, 5xx, timeouts, connection errors, and 200
  replies that are not a chat completion (a gateway's HTML error page), after
  retries are exhausted. The item stays unconsumed and is retried next run.
- ``EmptyReply`` (a ``TransientLLMError``): a 200 with no content, no tokens and no
  cost (one of these failed a whole ingest on 2026-10-29). It is retried like any
  transient error; still empty after the retries, the call is recorded at $0, unpriced,
  and the caller skips the item for this run and counts it.
- ``RefusedReply`` (an ``LLMError``): the model or the provider's safety filter declined
  this request (OpenRouter's ``content_filter``, Anthropic's ``refusal``). Sending the same
  text again meets the same filter, so it is not retried; the caller skips the item.
- ``LLMError``: any other rejection of this specific request (e.g. a 400 on
  an oversized input). Specific to the item, not the run.
- ``Paused``, ``BudgetExceeded``: raised before any request is sent.
- ``ProviderPaused`` (a ``Paused``): the provider stopped serving for a while, a spend
  limit set at the provider or a plan's usage window. The run halts with nothing consumed,
  the pause is kept with its end (``watch_paused`` in settings), and every call before
  then is refused without a request; afterwards calls go out again by themselves.
- ``TruncatedCompletion``: the reply stopped at ``max_tokens`` (``finish_reason``
  ``length``) or had no content. A reasoning model can spend the whole budget
  before writing anything; its partial text is never parsed as an answer. The
  call is recorded with its real cost. Callers that ask for it (the judge and the
  screen) get one more try with twice the room first.
- ``UnpricedModel``: the cost of a call cannot be determined. Raised before
  the call when using the pricing table, or after it when the reply carried
  tokens and no usable cost (missing, negative or not a number). In that case
  the call is recorded at a conservative estimate from its tokens, so the
  budget still counts it. A call with no tokens and no reported cost has nothing
  to estimate from: it is recorded at $0 and marked unpriced in its row's error,
  and nothing is raised for its price (an empty reply was stored at a made-up
  $0.44 and failed the run with advice about pricing).

The API key never appears in anything stored or raised: provider error text
is scrubbed of it before it is recorded.

How a request reaches a model is a provider's business (``providers/``): an OpenAI-style
endpoint (OpenRouter, or any other) is ``openai_compat``. The client holds one provider
per name in use, picks one per tier (``llm.provider``, ``llm.tiers``) and keeps
everything else here.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import httpx

from . import notify, pricing
from .config import MAX_TOKENS, BudgetConfig, LLMConfig
from .providers import make_provider
from .providers.base import Provider, ProviderError, Reply, Request
from .store import Store, iso, utcnow
from .stored.observations import LlmRequest
from .stored.settings import WatchPause, get_blob, set_blob

__all__ = [
    "BudgetExceeded",
    "Completion",
    "EmptyReply",
    "FatalLLMError",
    "LLMClient",
    "LLMError",
    "Paused",
    "ProviderPaused",
    "RefusedReply",
    "TransientLLMError",
    "TruncatedCompletion",
    "UnpricedModel",
    "watch_pause",
]

# Used when the provider reports no usable cost: well above current prices for
# the default models, so an estimate errs toward stopping early.
CONSERVATIVE_USD_PER_MTOK = (15.0, 75.0)  # input, output
MAX_RETRY_AFTER_SECONDS = 60.0
# The most room a cut-off reply's second try is given.
MAX_RETRY_TOKENS = 16000
# What a retried empty reply is called between tries; the start of Anthropic's refusal.
EMPTY_WORDS = "empty reply: no content, no tokens and no cost"
DECLINED = "the model declined to answer"
# The settings row holding a provider's pause: {"until", "reason", "provider"}.
WATCH_PAUSE_KEY = "watch_paused"


class LLMError(Exception):
    def __init__(self, message: str, *, call_id: int | None = None, status: int | None = None):
        super().__init__(message)
        self.call_id = call_id
        self.status = status


class FatalLLMError(LLMError):
    pass


class TransientLLMError(LLMError):
    pass


class EmptyReply(TransientLLMError):
    """A 200 with no content, no tokens and no cost, still empty after the retries."""


class RefusedReply(LLMError):
    """The model or the provider's safety filter declined this request."""


class UnpricedModel(LLMError):
    pass


class TruncatedCompletion(LLMError):
    pass


class Paused(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class ProviderPaused(Paused):
    """The provider will not serve until ``resume_at`` (a spend limit, a usage window)."""

    def __init__(self, message: str, *, resume_at: datetime, call_id: int | None = None,
                 status: int | None = None):
        super().__init__(message, call_id=call_id, status=status)
        self.resume_at = resume_at


def watch_pause(store: Store, now: datetime | None = None) -> dict[str, Any] | None:
    """The provider's pause in force at ``now``: ``{"until", "reason", "provider"}``, or
    None. A pause that has ended is None."""
    pause = get_blob(store, WATCH_PAUSE_KEY, WatchPause)
    if pause is None or pause.until is None:
        return None
    until = datetime.fromisoformat(pause.until.replace("Z", "+00:00"))
    if until.tzinfo is None or until <= (now or utcnow()):
        return None
    return {"until": iso(until), "reason": pause.reason or "", "provider": pause.provider or ""}


def pause_words(pause: dict[str, Any]) -> str:
    """``watching paused until 2026-10-17 15:45 UTC (Claude Code usage limit)``."""
    until = pause["until"].replace("T", " ").removesuffix("Z")[:16]
    reason = f" ({pause['reason']})" if pause.get("reason") else ""
    return f"watching paused until {until} UTC{reason}"


@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float
    call_id: int
    structured: dict[str, Any] | None = None
    # what a plan-billed call would have cost at list prices (its cost_usd is 0); None else
    equiv_usd: float | None = None


class LLMClient:
    def __init__(
        self,
        store: Store,
        config: LLMConfig,
        budget: BudgetConfig,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utcnow,
        backoff_base: float = 1.0,
    ) -> None:
        self.store = store
        self.budget = budget
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._backoff_base = backoff_base
        # Keys given to the client (a test's, or one set while the server runs), by the
        # environment variable they stand for; anything else is read from the environment.
        self._keys: dict[str, str] = {}
        self._providers: dict[str, Provider] = {}
        # Providers a call names itself (xAI's X search), made the first time one is asked for.
        self._named: dict[str, Provider] = {}
        self._config = config
        if api_key is not None and config.key_env:
            self._keys[config.key_env] = api_key
        self._build_providers()

    # -- configuration -------------------------------------------------------

    @property
    def config(self) -> LLMConfig:
        return self._config

    @config.setter
    def config(self, config: LLMConfig) -> None:
        """A changed ``llm`` section (Settings › Watching, onboarding): the providers follow."""
        self._config = config
        self._build_providers()

    def _build_providers(self) -> None:
        old, self._providers = self._providers, {}
        named, self._named = getattr(self, "_named", {}), {}
        for name in self._config.providers_in_use():
            self._providers[name] = make_provider(name, self._config, key=self._key_for,
                                                  http=self._new_http)
        for provider in [*old.values(), *named.values()]:
            provider.close()

    def named_provider(self, name: str) -> Provider:
        """A provider no tier uses, for a call that names it (``complete(provider=...)``)."""
        if name not in self._named:
            self._named[name] = make_provider(name, self._config, key=self._key_for,
                                              http=self._new_http)
        return self._named[name]

    def has_key_for(self, env: str) -> bool:
        return bool(self._key_for(env))

    def _new_http(self, *, timeout: float | None = None,
                  headers: dict[str, Any] | None = None) -> httpx.Client:
        return httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(timeout or self._config.timeout_seconds),
            headers={"X-Title": "kranto", **(headers or {})},
        )

    def _key_for(self, env: str | None) -> str | None:
        if not env:
            return None
        return self._keys.get(env) or os.environ.get(env) or None

    def provider_for(self, tier: str) -> Provider:
        return self._providers[self._config.provider_for(tier)]

    def close(self) -> None:
        for provider in [*self._providers.values(), *self._named.values()]:
            provider.close()

    @property
    def has_key(self) -> bool:
        return self._missing_key() is None

    def use_key(self, api_key: str, config: LLMConfig | None = None) -> None:
        """Take a key (and an endpoint) set while the server runs: onboarding's Keys step."""
        env = (config or self._config).api_key_env
        self._keys[env] = api_key
        if config is not None:
            self.config = config

    def use_provider_key(self, env: str, api_key: str) -> None:
        """Take a key for the provider reading ``env``, set while the server runs."""
        self._keys[env] = api_key

    def model_for(self, tier: str) -> str:
        try:
            return self._config.model_for(tier)
        except KeyError:
            raise LLMError(f"no model configured for tier '{tier}'") from None

    def max_tokens(self, call: str) -> int:
        """The reply-length ceiling for ``call`` (a ``config.MAX_TOKENS`` name): the
        config's ``llm.max_tokens``, else the default."""
        return int(self._config.max_tokens.get(call) or MAX_TOKENS[call])

    def remaining_budget(self) -> float:
        if self.budget.monthly_usd is None:
            return math.inf
        return self.budget.monthly_usd - self.store.month_spend(self._clock())

    def _missing_key(self) -> str | None:
        """The environment variable a provider in use needs and does not have, or None."""
        for provider in self._providers.values():
            if provider.key_env and not self._key_for(provider.key_env):
                return provider.key_env
        return None

    def check_can_spend(self) -> None:
        """Raise if a call made now would be refused. Cheap; no request is sent."""
        reason = self.store.pause_reason()
        if reason is not None:
            raise Paused(f"paused: {reason}")
        now = self._clock()
        pause = watch_pause(self.store, now)
        if pause is not None:
            raise ProviderPaused(pause_words(pause),
                                 resume_at=datetime.fromisoformat(
                                     pause["until"].replace("Z", "+00:00")))
        if self.store.get_setting(WATCH_PAUSE_KEY) is not None:
            self.store.delete_setting(WATCH_PAUSE_KEY)
        spent = self.store.month_spend(now)
        if self.budget.monthly_usd is not None and spent >= self.budget.monthly_usd:
            self._budget_alarm(spent)
            raise BudgetExceeded(
                f"monthly budget exhausted: ${spent:.4f} of ${self.budget.monthly_usd:.2f}"
            )
        missing = self._missing_key()
        if missing:
            raise FatalLLMError(f"no API key: set ${missing}")

    def complete(
        self,
        *,
        tier: str,
        purpose: str,
        messages: list[dict[str, str]],
        prompt_version: str,
        run_uuid: str | None = None,
        max_tokens: int = 800,
        temperature: float = 0.2,
        retry_truncated: bool = False,
        schema: dict[str, Any] | None = None,
        provider: str | None = None,
        model: str | None = None,
        tools: tuple[Any, ...] = (),
    ) -> Completion:
        """One completion. ``retry_truncated``: a reply cut off at ``max_tokens`` (or empty)
        is asked once more with twice the room before ``TruncatedCompletion`` is raised;
        both calls are recorded and count against the budget. ``schema``: the reply's JSON
        schema, used by a provider that can enforce it and set to do so for ``purpose``.
        ``provider`` and ``model``: a call to a provider no tier uses (xAI's X search, with its
        ``tools``), metered, recorded and budgeted like every other; ``tier`` still labels it.
        A call made inside a run without a ``run_uuid`` of its own is that run's (the scout's,
        an explanation's:), so its trace has it."""
        if run_uuid is None:
            from . import activity
            cur = activity.current()
            run_uuid = cur.uuid if cur is not None else None
        args: dict[str, Any] = dict(tier=tier, purpose=purpose, messages=messages,
                    prompt_version=prompt_version, run_uuid=run_uuid, temperature=temperature,
                    schema=schema, provider_name=provider, model_name=model, tools=tools)
        try:
            return self._complete(max_tokens=max_tokens, **args)
        except TruncatedCompletion:
            if not retry_truncated:
                raise
        return self._complete(max_tokens=min(max_tokens * 2, MAX_RETRY_TOKENS), **args)

    def _complete(
        self,
        *,
        tier: str,
        purpose: str,
        messages: list[dict[str, str]],
        prompt_version: str,
        run_uuid: str | None,
        max_tokens: int,
        temperature: float,
        schema: dict[str, Any] | None,
        provider_name: str | None = None,
        model_name: str | None = None,
        tools: tuple[Any, ...] = (),
    ) -> Completion:
        model = model_name or self.model_for(tier)
        provider = self.named_provider(provider_name) if provider_name \
            else self.provider_for(tier)
        self.check_can_spend()
        if provider.key_env and not self._key_for(provider.key_env):
            raise FatalLLMError(f"no API key: set ${provider.key_env}")
        if (provider.cost_source == "table"
                and pricing.price_for(model, self._config.pricing) is None):
            where = ("llm.pricing" if provider.name in ("openai_compat", "openrouter")
                     else "llm.pricing or Kranto's price table")
            raise UnpricedModel(
                f"model '{model}' has no entry in {where} and cost_source is 'table'"
            )
        body = provider.build(Request(model=model, messages=messages, max_tokens=max_tokens,
                                      temperature=temperature, purpose=purpose, schema=schema,
                                      tools=tuple(tools)))
        ctx: dict[str, Any] = dict(model=model, tier=tier, purpose=purpose,
                                   prompt_version=prompt_version,
                   run_uuid=run_uuid, body=body, provider=provider)

        started = time.monotonic()
        attempts = 0
        last_error: str | None = None
        last_status: int | None = None
        max_attempts = max(1, self._config.max_retries + 1)

        while attempts < max_attempts:
            attempts += 1
            try:
                reply = provider.send(body)
            except ProviderError as exc:
                last_error, last_status = self._scrub(str(exc)), exc.status
                if exc.kind == "fatal":
                    call_id = self._record_error(ctx, attempts, started, last_error, last_status)
                    where = f"HTTP {last_status} from {provider.label}" if last_status else \
                        provider.label
                    raise FatalLLMError(f"{where}: {last_error}",
                                        call_id=call_id, status=last_status) from None
                if exc.kind == "item":
                    call_id = self._record_error(ctx, attempts, started, last_error, last_status)
                    prefix = f"HTTP {last_status}: " if last_status else ""
                    cls = RefusedReply if last_error.startswith(DECLINED) else LLMError
                    raise cls(f"{prefix}{last_error}", call_id=call_id,
                              status=last_status) from None
                if exc.kind == "paused":
                    call_id = self._record_error(ctx, attempts, started, last_error, last_status)
                    raise self._pause(provider, exc, last_error, call_id) from None
                if attempts < max_attempts:
                    delay = exc.retry_after
                    if delay is None:
                        delay = self._backoff_base * (2 ** (attempts - 1))
                        if last_error is None or not last_error.startswith("malformed response"):
                            delay += random.uniform(0, 1)
                    self._sleep(min(delay, MAX_RETRY_AFTER_SECONDS))
                continue
            if _empty(reply) and attempts < max_attempts:
                # nothing in it to read or to price: tried again like any transient fault
                last_error, last_status = EMPTY_WORDS, reply.http_status
                self._sleep(min(self._backoff_base * (2 ** (attempts - 1))
                                + random.uniform(0, 1), MAX_RETRY_AFTER_SECONDS))
                continue
            return self._success(reply, attempts=attempts, started=started, **ctx)

        call_id = self._record_error(ctx, attempts, started, last_error, last_status)
        raise TransientLLMError(
            f"gave up after {attempts} attempts at {provider.label}: {last_error}",
            call_id=call_id, status=last_status,
        )

    # -- internals -----------------------------------------------------------

    def _scrub(self, text: str) -> str:
        """Remove every API key in use from text that will be stored, shown or raised."""
        for provider in [*self._providers.values(), *self._named.values()]:
            key = self._key_for(provider.key_env)
            if key and len(key) >= 8:
                text = text.replace(key, "[redacted]")
        return text

    def _pause(self, provider: Provider, exc: ProviderError, words: str,
               call_id: int) -> ProviderPaused:
        resume_at = exc.resume_at or self._clock()
        reason = words[:200]
        set_blob(self.store, WATCH_PAUSE_KEY,
                 WatchPause(until=iso(resume_at), reason=reason, provider=provider.name))
        message = pause_words({"until": iso(resume_at), "reason": reason})
        return ProviderPaused(message, resume_at=resume_at, call_id=call_id,
                              status=exc.status)

    def _success(
        self, reply: Reply, *, model: str, tier: str, purpose: str, prompt_version: str,
        run_uuid: str | None, body: dict[str, Any], provider: Provider, attempts: int,
        started: float,
    ) -> Completion:
        raw = self._scrub(reply.raw)
        prompt_tokens, completion_tokens = reply.input_tokens, reply.output_tokens
        listed = self._cost(provider, model, reply)
        equiv = None
        cost: float | None
        if provider.billing == "plan":
            # A subscription's calls cost no dollars; what they would have cost is kept.
            equiv, cost = listed, 0.0
        else:
            cost = listed
        name = provider_name(provider)
        unpriced = None                   # the row's note: its cost is not a price
        priceless = None                  # tokens and no price: UnpricedModel's words
        if provider.billing != "plan" and (cost is None or not math.isfinite(cost) or cost < 0):
            if not prompt_tokens and not completion_tokens:
                # nothing to estimate from: $0, said, never a made-up figure
                cost = 0.0
                unpriced = f"unpriced: {name} reported no cost and no tokens; stored at $0"
            else:
                cost = _conservative_cost(body, prompt_tokens, completion_tokens)
                tokens = f"{prompt_tokens or 0} input and {completion_tokens or 0} output tokens"
                if provider.cost_source == "provider":
                    unpriced = (f"provider reported cost {reply.reported_cost_usd!r}; counted at "
                                f"a conservative estimate of ${cost:.4f}")
                    priceless = (f"{name} reported no cost for model '{model}' ({tokens}); "
                                 f"counted at a conservative estimate of ${cost:.4f}. To price "
                                 "it from a table instead, add the model to llm.pricing and "
                                 "set llm.cost_source to 'table'")
                else:
                    unpriced = f"no price; counted at a conservative estimate of ${cost:.4f}"
                    priceless = (f"model '{model}' has no price in llm.pricing or Kranto's price "
                                 f"table ({tokens}); counted at a conservative estimate of "
                                 f"${cost:.4f}. Add it to llm.pricing")
        truncated = refused = empty = None
        if reply.finish == "refusal" and not reply.text.strip():
            refused = f"{name} declined to answer: " + (
                _refusal_words(reply.raw) or "the model or a safety filter refused")
        elif _empty(reply):
            empty = (f"{name} sent an empty reply (HTTP {reply.http_status or 200}, no content, "
                     f"no tokens, no cost) {attempts} time{'' if attempts == 1 else 's'}")
        elif reply.finish == "length":
            truncated = f"reply cut off at max_tokens={body.get('max_tokens')}"
        elif not reply.text.strip():
            truncated = "reply had no content"
        failed = refused or empty or truncated
        errors = [e for e in (failed, unpriced) if e]
        row = {
            "run_uuid": run_uuid,
            "purpose": purpose,
            "tier": tier,
            "model": reply.model or model,
            "prompt_version": prompt_version,
            "request": LlmRequest.write(body),
            "response": raw,
            "status": "error" if failed else "ok",
            "error": "; ".join(errors) or None,
            "http_status": reply.http_status,
            "attempts": attempts,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "created_at": iso(self._clock()),
        }
        row.update(self._provider_columns(provider, reply, equiv))
        call_id = self.store.insert("llm_calls", row)
        self._budget_alarm(self.store.month_spend(self._clock()))
        if refused:
            raise RefusedReply(f"{refused[:300]} ({purpose}, {model})", call_id=call_id,
                               status=reply.http_status)
        if empty:
            raise EmptyReply(f"{empty} ({purpose}, {model})", call_id=call_id,
                             status=reply.http_status)
        if priceless:
            raise UnpricedModel(priceless, call_id=call_id)
        if truncated:
            raise TruncatedCompletion(
                f"{truncated} ({purpose}, {model}, {completion_tokens} completion tokens)",
                call_id=call_id,
            )
        assert cost is not None                # priced, the estimate above, or $0 unpriced
        return Completion(reply.text, model, prompt_tokens, completion_tokens, cost, call_id,
                          reply.structured, equiv)

    def _provider_columns(self, provider: Provider, reply: Reply | None,
                          equiv: float | None) -> dict[str, Any]:
        """Migration 25's columns."""
        return {
            "provider": provider.name,
            "cache_read_tokens": reply.cache_read_tokens if reply else None,
            "cache_write_tokens": reply.cache_write_tokens if reply else None,
            "equiv_usd": equiv,
        }

    def _budget_alarm(self, spent: float) -> None:
        if self.budget.monthly_usd is None:
            return
        notify.budget_alarm(self.store, spent=spent, budget=self.budget.monthly_usd,
                            alarm_fraction=self.budget.alarm_fraction, now=self._clock())

    def _cost(self, provider: Provider, model: str, reply: Reply) -> float | None:
        if provider.cost_source == "provider":
            reported = reply.reported_cost_usd
            try:
                return float(cast(Any, reported)) if reported is not None else None
            except (TypeError, ValueError):
                return None
        return pricing.cost(
            model, input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
            cache_read_tokens=reply.cache_read_tokens,
            cache_write_tokens=reply.cache_write_tokens, table=self._config.pricing,
        )

    def _record_error(self, ctx: dict[str, Any], attempts: int, started: float, error: str | None,
                      status: int | None) -> int:
        row = {
            "run_uuid": ctx["run_uuid"],
            "purpose": ctx["purpose"],
            "tier": ctx["tier"],
            "model": ctx["model"],
            "prompt_version": ctx["prompt_version"],
            "request": LlmRequest.write(ctx["body"]),
            "response": None,
            "status": "error",
            "error": self._scrub(error or "unknown error")[:2000],
            "http_status": status,
            "attempts": attempts,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_usd": 0.0,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "created_at": iso(self._clock()),
        }
        row.update(self._provider_columns(ctx["provider"], None, None))
        return self.store.insert("llm_calls", row)


def provider_name(provider: Provider) -> str:
    """The provider as the owner knows it (OpenRouter, Claude API), else where calls go."""
    from .activity.incidents import provider_words

    return provider_words(f"{provider.name} {provider.label}") or provider.label


def _empty(reply: Reply) -> bool:
    """A reply with nothing in it: no content, no structured answer, no tokens and no cost,
    and not a refusal or a cut-off (those say why they are empty)."""
    cost = reply.reported_cost_usd
    costed = isinstance(cost, int | float) and not isinstance(cost, bool) and cost > 0
    return (not reply.text.strip() and reply.structured is None
            and reply.finish not in ("length", "refusal")
            and not reply.input_tokens and not reply.output_tokens and not costed)


def _refusal_words(raw: str) -> str:
    """A chat completion's ``message.refusal`` (OpenRouter passes the model's words), or ""."""
    try:
        words = json.loads(raw.strip())["choices"][0]["message"].get("refusal")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return ""
    return " ".join(words.split()) if isinstance(words, str) else ""


def _conservative_cost(body: dict[str, Any], prompt_tokens: int | None,
                       completion_tokens: int | None) -> float:
    if prompt_tokens is None:
        prompt_tokens = len(json.dumps(body.get("messages", []))) // 3
    if completion_tokens is None:
        completion_tokens = int(body.get("max_tokens") or 0)
    per_in, per_out = CONSERVATIVE_USD_PER_MTOK
    return (prompt_tokens * per_in + completion_tokens * per_out) / 1_000_000
