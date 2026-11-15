"""xAI's Responses API with its ``x_search`` tool: X search through Grok, for a person with an
xAI key and no X developer app (5.9; D11: built last, off until a key is set).

Never a watching provider: only the ``xai_search`` source asks for it, by name, through the
metered client, so every call is an ``llm_calls`` row and counts in the watcher's budget. The
reply is the model's text with ``url_citation`` annotations; the cost is the tokens at
``pricing.XAI_PRICES`` plus ``$5`` per 1,000 posts the tool fetched
(``usage.server_side_tool_usage_details.x_posts_fetched``), computed here and reported as the
call's cost.

https://docs.x.ai/developers/tools/x-search, https://docs.x.ai/developers/tools/citations
(read 2026-10-17)
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from .. import pricing
from .base import KeyTest, ProviderError, Reply, Request
from .openai_compat import FATAL_STATUS, RETRYABLE_STATUS, error_text, int_or_none

API = "https://api.x.ai/v1"
KEY_ENV = "XAI_API_KEY"
MODEL = "grok-4.7"


class XAIProvider:
    name = "xai"
    billing = "dollars"
    cost_source = "provider"          # this provider prices its calls, tool use included
    label = API
    key_env = KEY_ENV

    def __init__(self, *, key: Callable[[], str | None], http: httpx.Client,
                 base_url: str = API) -> None:
        self._key, self._http, self.base_url = key, http, base_url

    def build(self, req: Request) -> dict:
        body: dict = {"model": req.model, "input": req.messages,
                      "max_output_tokens": req.max_tokens}
        if req.tools:
            body["tools"] = [dict(t) for t in req.tools]
            body["max_turns"] = 2
        return body

    def send(self, body: dict) -> Reply:
        try:
            response = self._http.post(f"{self.base_url}/responses", json=body,
                                       headers={"Authorization": f"Bearer {self._key() or ''}"})
        except httpx.TransportError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}", kind="transient") from None
        status = response.status_code
        if status != 200:
            text = error_text(response)
            if status in FATAL_STATUS:
                raise ProviderError(text, kind="fatal", status=status)
            if status not in RETRYABLE_STATUS:
                raise ProviderError(text, kind="item", status=status)
            raise ProviderError(text, kind="transient", status=status)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(f"malformed response: {response.text[:300]}", kind="transient",
                                status=status) from None
        if not isinstance(payload, dict):
            raise ProviderError("malformed response", kind="transient", status=status)
        text, citations = reply_text(payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        tools = usage.get("server_side_tool_usage_details") \
            if isinstance(usage.get("server_side_tool_usage_details"), dict) else {}
        inp, out = int_or_none(usage.get("input_tokens")), int_or_none(usage.get("output_tokens"))
        cost = pricing.xai_cost(str(payload.get("model") or body.get("model")), inp, out,
                                posts=int_or_none(tools.get("x_posts_fetched")) or 0,
                                users=int_or_none(tools.get("x_users_fetched")) or 0)
        return Reply(text=text, model=payload.get("model"), input_tokens=inp,
                     output_tokens=out, reported_cost_usd=cost,
                     finish="length" if payload.get("status") == "incomplete" else "stop",
                     raw=response.text, http_status=status,
                     structured={"citations": citations,
                                 "x_posts_fetched": int_or_none(tools.get("x_posts_fetched"))})

    def test(self, key: str | None) -> KeyTest:
        """``GET /v1/models``: spends nothing."""
        if not key:
            return KeyTest(False, f"${KEY_ENV} is not set")
        try:
            r = self._http.get(f"{self.base_url}/models",
                               headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            return KeyTest(False, f"xAI did not answer ({type(exc).__name__})")
        if r.status_code != 200:
            return KeyTest(False, f"xAI refused the key (HTTP {r.status_code})")
        try:
            models = tuple(str(m.get("id")) for m in r.json().get("data") or []
                           if isinstance(m, dict))
        except (ValueError, AttributeError):
            models = ()
        return KeyTest(True, "xAI accepted the key"
                       + (f"; {MODEL} is offered" if MODEL in models else ""), models)

    def close(self) -> None:
        self._http.close()


def reply_text(payload: dict) -> tuple[str, list[dict]]:
    """The model's text (every ``output_text`` of every ``message``) and its ``url_citation``
    annotations."""
    parts, cites = [], []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "output_text":
                parts.append(str(c.get("text") or ""))
                for a in c.get("annotations") or []:
                    if isinstance(a, dict) and a.get("type") == "url_citation" and a.get("url"):
                        cites.append({"url": str(a["url"]), "title": a.get("title")})
    return "\n".join(parts), cites
