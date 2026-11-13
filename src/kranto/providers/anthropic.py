"""The Claude API's native Messages endpoint, with an Anthropic key.

Native rather than Anthropic's OpenAI-compatible layer, because only ``/v1/messages`` has
prompt caching, structured outputs and the cache fields in ``usage``. What it sends:

- the conversation's system turns as the top-level ``system``, with one cache breakpoint on
  it when ``llm.anthropic.cache`` is on (the stage prompts are the same on every call, so a
  burst of screens or judges reads them from the cache at a tenth of the input price);
- never ``temperature``: current Claude models refuse it (MP D13);
- ``output_config.format`` (a JSON schema) when the call passes a schema: always for a
  writer's call (fix 1: a blog post asked for in a schema came back as
  prose), and for the watcher's own calls (``screen``, ``judge``, ``name``) when
  ``llm.anthropic.structured`` turns it on; ``output_config.effort`` when set.

Its calls are priced from ``pricing.py`` by their tokens. A spend limit is a pause, not a
failure: the limit set in the Console (400, "You have reached your specified API usage
limits") and the organisation's monthly cap (429 without ``retry-after``,
``enforced_spend_limit_reached``) both pause watching until the first of next month.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from .base import KeyTest, ProviderError, Reply, Request, schema_on
from .openai_compat import int_or_none, retry_after_seconds

API_VERSION = "2023-06-01"
FATAL_STATUS = frozenset({401, 402, 403, 404})
TRANSIENT_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})
USER_LIMIT = "reached your specified api usage limits"
LOW_CREDIT = "credit balance is too low"
# A stage's purpose to its MAX_TOKENS call name, where they differ.
CALL_OF_PURPOSE = {"deep_dive": "judge", "replay_screen": "screen", "replay_judge": "judge"}


def next_month_start(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)


class AnthropicProvider:
    name = "anthropic"
    billing = "dollars"
    cost_source = "table"

    def __init__(self, *, base_url: str, key_env: str, key: Callable[[], str | None],
                 http: httpx.Client, cache: bool = True, structured: dict | None = None,
                 effort: dict | None = None, clock: Callable[[], datetime] | None = None):
        self.base_url = base_url.rstrip("/")
        self.label = self.base_url
        self.key_env = key_env
        self._key = key
        self._http = http
        self.cache = cache
        self.structured = dict(structured or {})
        self.effort = dict(effort or {})
        self._clock = clock or (lambda: datetime.now(UTC))
        self.last_headers: dict = {}

    def _headers(self, key: str | None = None) -> dict:
        return {"x-api-key": key if key is not None else (self._key() or ""),
                "anthropic-version": API_VERSION}

    def build(self, req: Request) -> dict:
        system = "\n\n".join(m["content"] for m in req.messages
                             if m.get("role") == "system" and m.get("content"))
        turns = [{"role": m["role"], "content": m["content"]} for m in req.messages
                 if m.get("role") in ("user", "assistant")]
        body: dict = {"model": req.model, "max_tokens": req.max_tokens, "messages": turns}
        if system:
            block = {"type": "text", "text": system}
            if self.cache:
                block["cache_control"] = {"type": "ephemeral"}
            body["system"] = [block]
        call = CALL_OF_PURPOSE.get(req.purpose, req.purpose)
        output: dict = {}
        if req.schema is not None and schema_on(self.structured, call):
            output["format"] = {"type": "json_schema", "schema": req.schema}
        if self.effort.get(call):
            output["effort"] = self.effort[call]
        if output:
            body["output_config"] = output
        return body

    def send(self, body: dict) -> Reply:
        try:
            response = self._http.post(f"{self.base_url}/v1/messages", json=body,
                                       headers=self._headers())
        except httpx.TransportError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}", kind="transient") from None
        self.last_headers = {k: v for k, v in response.headers.items()
                             if k.lower().startswith("anthropic-ratelimit-")}
        status = response.status_code
        if status == 200:
            return self._reply(response, body)
        kind, message, details = _error(response)
        lowered = message.lower()
        if status == 400 and USER_LIMIT in lowered:
            raise ProviderError(f"spend limit set in the Claude Console reached: {message}",
                                kind="paused", status=status,
                                resume_at=next_month_start(self._clock()))
        if status == 429 and (details.get("error_code") == "enforced_spend_limit_reached"
                              or (response.headers.get("retry-after") is None
                                  and "spend limit" in lowered)):
            raise ProviderError(f"the organisation's monthly spend limit is reached: {message}",
                                kind="paused", status=status,
                                resume_at=next_month_start(self._clock()))
        if status in FATAL_STATUS or kind in ("authentication_error", "permission_error") or \
                (status == 400 and LOW_CREDIT in lowered):
            raise ProviderError(message, kind="fatal", status=status)
        if status in TRANSIENT_STATUS or kind in ("overloaded_error", "api_error"):
            raise ProviderError(message, kind="transient", status=status,
                                retry_after=retry_after_seconds(response))
        raise ProviderError(message, kind="item", status=status)

    def _reply(self, response: httpx.Response, body: dict) -> Reply:
        try:
            payload = response.json()
            blocks = payload["content"]
            usage = payload.get("usage") or {}
            if not isinstance(blocks, list) or not isinstance(usage, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            raise ProviderError(f"malformed response: {response.text[:300]}", kind="transient",
                                status=response.status_code) from None
        text = "".join(b.get("text") or "" for b in blocks
                       if isinstance(b, dict) and b.get("type") == "text")
        stop = payload.get("stop_reason")
        if stop == "refusal":
            raise ProviderError("the model declined to answer (stop_reason refusal)",
                                kind="item", status=response.status_code)
        uncached = int_or_none(usage.get("input_tokens"))
        read = int_or_none(usage.get("cache_read_input_tokens")) or 0
        write = int_or_none(usage.get("cache_creation_input_tokens")) or 0
        structured = None
        if "format" in (body.get("output_config") or {}) and stop != "max_tokens":
            try:
                parsed = json.loads(text)
                structured = parsed if isinstance(parsed, dict) else None
            except ValueError:
                structured = None
        return Reply(
            text=text,
            model=payload.get("model"),
            input_tokens=None if uncached is None else uncached + read + write,
            output_tokens=int_or_none(usage.get("output_tokens")),
            cache_read_tokens=read,
            cache_write_tokens=write,
            finish="length" if stop == "max_tokens" else "stop",
            raw=response.text,
            http_status=response.status_code,
            structured=structured,
            headers=dict(self.last_headers),
        )

    def test(self, key: str | None = None) -> KeyTest:
        """``GET /v1/models`` with the key: authenticated, free, and it lists the models the
        key may use. Spends nothing."""
        key = key if key is not None else self._key()
        if not key:
            return KeyTest(False, f"${self.key_env} is not set")
        try:
            response = self._http.get(f"{self.base_url}/v1/models", params={"limit": 1000},
                                      headers=self._headers(key))
        except httpx.HTTPError as exc:
            return KeyTest(False, f"could not reach {self.base_url}: {type(exc).__name__}")
        if response.status_code in (401, 403):
            return KeyTest(False, f"The Claude API refused the key (HTTP {response.status_code})")
        if response.status_code != 200:
            return KeyTest(False, f"The Claude API answered HTTP {response.status_code}")
        try:
            models = tuple(str(m["id"]) for m in response.json().get("data", [])
                           if isinstance(m, dict) and m.get("id"))
        except (ValueError, AttributeError, TypeError):
            models = ()
        return KeyTest(True, "The Claude API accepted the key", models)

    def close(self) -> None:
        self._http.close()


def _error(response: httpx.Response) -> tuple[str, str, dict]:
    """(error type, message, details) of an error reply."""
    try:
        payload = response.json()
    except ValueError:
        return "", response.text[:500], {}
    err = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(err, dict):
        return "", response.text[:500], {}
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    return (str(err.get("type") or ""), str(err.get("message") or response.text)[:500],
            details)
