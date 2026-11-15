"""An OpenAI-style chat completions endpoint: OpenRouter (the default) or any other.

This is the request and reply handling ``LLMClient`` had before providers, moved here
unchanged: the body, the key as a bearer token, ``usage.cost`` when ``cost_source`` is
``provider``, and the same reading of errors. ``openrouter`` is this provider under its own
name. One difference, by the owner's decision (MP D13): ``temperature`` is not sent when the
endpoint is Anthropic's own, which refuses it on every current model.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from .base import ProviderError, Reply, Request

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529})
FATAL_STATUS = frozenset({401, 402, 403, 404})
# OpenRouter's 402 for credit too low for the requests in flight (a squeeze, not a refusal)
IN_FLIGHT = re.compile(r"in-flight requests|exceed your available credits", re.I)
NO_TEMPERATURE_HOSTS = frozenset({"api.anthropic.com"})


class OpenAICompatProvider:
    billing = "dollars"

    def __init__(self, *, name: str, base_url: str, key_env: str, cost_source: str,
                 key: Callable[[], str | None], http: httpx.Client):
        self.name = name
        self.label = base_url
        self.base_url = base_url
        self.key_env = key_env
        self.cost_source = cost_source
        self._key = key
        self._http = http

    def build(self, req: Request) -> dict:
        body: dict = {
            "model": req.model,
            "messages": req.messages,
            "max_tokens": req.max_tokens,
        }
        if req.temperature is not None and not _refuses_temperature(self.base_url):
            body["temperature"] = req.temperature
        if self.cost_source == "provider":
            # OpenRouter usage accounting: the response carries usage.cost.
            body["usage"] = {"include": True}
        return body

    def send(self, body: dict) -> Reply:
        try:
            response = self._http.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._key() or ''}"},
            )
        except httpx.TransportError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}", kind="transient") from None
        status = response.status_code
        if status == 200:
            parsed = parse_completion(response)
            if parsed is None:
                # Not a chat completion: a gateway error page or a broken reply. Nothing
                # about the item caused it, so it is retried and never consumes the item.
                raise ProviderError(f"malformed response: {response.text[:300]}",
                                    kind="transient", status=status)
            payload, choice, text = parsed
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
            return Reply(
                text=text,
                model=payload.get("model"),
                input_tokens=int_or_none(usage.get("prompt_tokens")),
                output_tokens=int_or_none(usage.get("completion_tokens")),
                reported_cost_usd=usage.get("cost"),
                finish=_finish(choice),
                raw=response.text,
                http_status=status,
            )
        text = error_text(response)
        if status == 402 and IN_FLIGHT.search(text):
            # credit too low for the calls in flight (OpenRouter): the key works and the call
            # goes once those settle, so it is tried again, never a refused key
            raise ProviderError(text, kind="transient", status=status,
                                retry_after=retry_after_seconds(response))
        if status in FATAL_STATUS:
            raise ProviderError(text, kind="fatal", status=status)
        if status not in RETRYABLE_STATUS:
            raise ProviderError(text, kind="item", status=status)
        raise ProviderError(text, kind="transient", status=status,
                            retry_after=retry_after_seconds(response))

    def close(self) -> None:
        self._http.close()


def _finish(choice: dict) -> str:
    """``length``, ``refusal`` (a safety filter or the model declined: OpenRouter's
    ``content_filter`` with the message's ``refusal``,) or ``stop``."""
    message = choice.get("message")
    refusal = message.get("refusal") if isinstance(message, dict) else None
    if choice.get("finish_reason") == "length":
        return "length"
    if choice.get("finish_reason") == "content_filter" or refusal:
        return "refusal"
    return "stop"


def _refuses_temperature(base_url: str) -> bool:
    return (urlsplit(base_url).hostname or "").lower() in NO_TEMPERATURE_HOSTS


def parse_completion(response: httpx.Response) -> tuple[dict, dict, str] | None:
    """(payload, first choice, content) of a chat completion, or None if the body
    is not one."""
    try:
        payload = response.json()
        choice = payload["choices"][0]
        text = choice["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None
    if not isinstance(payload, dict) or not isinstance(choice, dict) or not isinstance(text, str):
        return None
    return payload, choice, text


def error_text(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:500]
    return response.text[:500]


def retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
