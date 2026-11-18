"""OpenAI's own API, for a writer's own model only (P-11): never the watcher's.

A person who wants a post writer on a GPT model pastes an OpenAI key (``kranto watch provider
openai --key-stdin``, kept as ``OPENAI_API_KEY`` in the home's ``.env``, 0600) and sets the writer's
model (``prose.voice`` ``writer_model``: ``{"blog": {"provider": "openai", "model": ...}}``).
The writer's calls then go here by name, through the metered client like every other call, so
each is an ``llm_calls`` row and counts in the budget. Kranto chooses no default model.

The chat completions request of ``openai_compat``, with two differences OpenAI's current models
need: the reply's length is ``max_completion_tokens`` (``max_tokens`` is refused by its reasoning
models), and ``temperature`` is not sent (those models take only the default). OpenAI reports
tokens, not dollars: a model in ``llm.pricing`` is priced from it, any other is counted at the
client's conservative estimate, never as free.

https://platform.openai.com/docs/api-reference/chat/create (read 2026-11-14)
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from .base import KeyTest, Request
from .openai_compat import OpenAICompatProvider

API = "https://api.openai.com/v1"
KEY_ENV = "OPENAI_API_KEY"


class OpenAIProvider(OpenAICompatProvider):
    def __init__(self, *, key: Callable[[], str | None], http: httpx.Client,
                 base_url: str = API) -> None:
        super().__init__(name="openai", base_url=base_url, key_env=KEY_ENV,
                         cost_source="estimate", key=key, http=http)

    def build(self, req: Request) -> dict:
        return {"model": req.model, "messages": req.messages,
                "max_completion_tokens": req.max_tokens}

    def test(self, key: str | None) -> KeyTest:
        """``GET /v1/models``: spends nothing."""
        if not key:
            return KeyTest(False, f"${KEY_ENV} is not set")
        try:
            r = self._http.get(f"{self.base_url}/models",
                               headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            return KeyTest(False, f"OpenAI did not answer ({type(exc).__name__})")
        if r.status_code != 200:
            return KeyTest(False, f"OpenAI refused the key (HTTP {r.status_code})")
        try:
            models = tuple(str(m.get("id")) for m in r.json().get("data") or []
                           if isinstance(m, dict))
        except (ValueError, AttributeError):
            models = ()
        return KeyTest(True, f"OpenAI accepted the key; {len(models)} models offered", models)
