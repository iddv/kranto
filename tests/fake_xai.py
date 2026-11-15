"""A fake xAI API: the Responses API with the x_search tool and the models
list, as an ``httpx`` transport, in the shapes on docs.x.ai's X Search and Citations pages
(read 2026-10-17): ``output[]`` items of type ``message`` with ``output_text`` content and its
``url_citation`` annotations, ``usage.server_side_tool_usage_details.x_posts_fetched``. Nothing
here came from a real call; no test reaches xAI."""

from __future__ import annotations

import json

import httpx

DIGEST = {"posts": [
    {"url": "https://x.com/gridco/status/1849300000000000002", "date": "2026-10-16",
     "gist": "A builder reports that solar mini-grid tariffs fell below grid extension "
             "costs in two Kenyan counties.", "link": "https://example.org/tariffs"},
    {"url": "https://x.com/someone/status/1849300000000000001", "date": "2026-10-15",
     "gist": "A thread on productive-use appliances sold with pay-as-you-go solar.",
     "link": None},
]}


class FakeXAI:
    def __init__(self, key: str) -> None:
        self.key = key
        self.requests: list[httpx.Request] = []
        self.posts_fetched = 24
        self.digest = DIGEST

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host != "api.x.ai":
            return httpx.Response(404)
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "grok-4.7"}, {"id": "grok-4.3"}]})
        if request.url.path != "/v1/responses":
            return httpx.Response(404)
        body = json.loads(request.content)
        text = json.dumps(self.digest)
        return httpx.Response(200, json={
            "id": "resp_1", "model": body["model"], "status": "completed",
            "output": [
                {"type": "custom_tool_call", "name": "x_keyword_search",
                 "input": json.dumps({"query": "solar"})},
                {"type": "message", "role": "assistant", "content": [{
                    "type": "output_text", "text": text, "annotations": [
                        {"type": "url_citation", "url": p["url"], "start_index": 0,
                         "end_index": 10, "title": str(i)}
                        for i, p in enumerate(self.digest["posts"], 1)]
                    + [{"type": "url_citation",
                        "url": "https://x.com/other/status/1849300000000000009",
                        "start_index": 0, "end_index": 5,
                        "title": "Cited without being listed"}]}]}],
            "usage": {"input_tokens": 9000, "output_tokens": 600,
                      "server_side_tool_usage_details": {"x_search_calls": 2,
                                                         "x_posts_fetched": self.posts_fetched,
                                                         "x_users_fetched": 0}}})
