"""Stand-ins for the live search backends: Exa's REST API and its keyless hosted
MCP server, Hacker News Algolia, GitHub's repository search, arXiv's export API and the Claude
API's web search tool. Every reply is invented in each service's documented shape (the Exa MCP
text format as its server sent it on 2026-10-17); nothing here was copied from a real result.
``FakeSearch.http()`` is a ``sources.HTTP`` whose every request is answered here and recorded,
so a test sees what Kranto asked and never touches the network."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx

from kranto.sources import HTTP


def public(host):
    return ["93.184.216.34"]


EXA_TEXT = (
    "Title: Sync engines compared in 2026 | example.dev\n"
    "URL: https://example.dev/blog/sync-engines-2026\n"
    "Published: 2026-10-12T00:00:00.000Z\n"
    "Author: N/A\n"
    "Highlights:\n"
    "Sync engines compared in 2026 | example.dev\n\n"
    "# Sync engines compared in 2026\n\n"
    "We moved our app between three sync engines this year.\n"
    "...\n"
    "The third one held up under 40 collaborators.\n"
    "\n---\n\n"
    "Title: tinysync: a CRDT sync server\n"
    "URL: https://github.com/example/tinysync\n"
    "Published: N/A\n"
    "Author: N/A\n"
    "Highlights:\n"
    "A small CRDT sync server written in Rust.\n"
    "\n---\n\n"
    "Title: Local-first, a year on\n"
    "URL: https://example.org/2025/local-first-a-year-on\n"
    "Published: 2025-01-04T10:00:00.000Z\n"
    "Author: Someone\n"
    "Highlights:\n"
    "What changed since last year.\n"
)


def sse(obj: dict) -> httpx.Response:
    return httpx.Response(200, text=f"event: message\ndata: {json.dumps(obj)}\n\n",
                          headers={"content-type": "text/event-stream"})


class FakeSearch:
    """Answers every backend; ``fail`` maps a host to a status code to answer instead;
    ``calls`` records (host, path, query or body) per request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.fail: dict[str, int] = {}
        self.exa_text = EXA_TEXT
        self.exa_session = "sess-1"
        self.exa_tool_error: str | None = None
        self.anthropic_error: str | None = None
        self.page = "<html><body><h1>A page</h1><p>Plain text here.</p></body></html>"

    def http(self) -> HTTP:
        return HTTP(transport=httpx.MockTransport(self.handle), resolver=public)

    def hosts(self) -> list[str]:
        return [c[0] for c in self.calls]

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = json.loads(request.content) if request.content else {}
        self.calls.append((url.hostname, url.path, body or query))
        if url.hostname in self.fail:
            return httpx.Response(self.fail[url.hostname], json={"error": "no"})
        if url.hostname == "mcp.exa.ai":
            return self.exa_mcp(request, body)
        if url.hostname == "api.exa.ai":
            return httpx.Response(200, json={"requestId": "r1", "costDollars": {"total": 0.007},
                                             "results": [
                {"title": "Sync engines compared in 2026", "url": "https://example.dev/s",
                 "publishedDate": "2026-10-12T00:00:00.000Z",
                 "highlights": ["We moved our app between three sync engines."]},
                {"title": "An undated page", "url": "https://example.dev/u",
                 "publishedDate": None, "highlights": ["No date here."]}]})
        if url.hostname == "hn.algolia.com":
            return httpx.Response(200, json={"hits": [
                {"objectID": "101", "title": "Show HN: tinysync", "url": "https://example.com/t",
                 "points": 120, "num_comments": 40, "created_at": "2026-10-14T09:00:00Z"},
                {"objectID": "102", "title": "Ask HN: sync engines?", "url": None,
                 "points": 9, "num_comments": 3, "created_at": "2026-10-01T09:00:00Z"}]})
        if url.hostname == "api.github.com":
            return httpx.Response(200, json={"total_count": 1, "items": [
                {"full_name": "example/tinysync", "html_url": "https://github.com/example/tinysync",
                 "description": "A small CRDT sync server", "stargazers_count": 310,
                 "created_at": "2026-05-02T00:00:00Z", "pushed_at": "2026-10-15T00:00:00Z"}]})
        if url.hostname == "export.arxiv.org":
            return httpx.Response(200, headers={"content-type": "application/atom+xml"}, text=(
                '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                "<title>arXiv Query</title><entry><id>http://arxiv.org/abs/2610.00001v1</id>"
                "<published>2026-10-13T00:00:00Z</published><updated>2026-10-13T00:00:00Z"
                "</updated><title>Sync at scale</title><summary>We measure sync engines."
                '</summary><link href="http://arxiv.org/abs/2610.00001v1" rel="alternate"/>'
                "</entry></feed>"))
        if url.hostname == "api.anthropic.com":
            return self.anthropic(body)
        if url.hostname == "api.search.brave.com":
            return httpx.Response(200, json={"type": "search", "web": {"results": [
                {"title": "Sync engines in practice", "url": "https://forum.example.org/t/1",
                 "description": "A thread on sync engines.", "page_age":
                 "2026-10-11T08:00:00", "age": "October 11, 2026"},
                {"title": "Elsewhere", "url": "https://other.example/x",
                 "description": "Off the site.", "age": "2 days ago"}]}})
        if url.hostname == "api.tavily.com":
            return httpx.Response(200, json={"query": body.get("query"), "results": [
                {"title": "Sync engines in practice", "url": "https://forum.example.org/t/2",
                 "content": "Another thread.", "score": 0.9, "published_date":
                 "2026-10-10"}], "usage": {"credits": 1}})
        if url.hostname == "page.example":
            return httpx.Response(200, text=self.page, headers={"content-type": "text/html"})
        return httpx.Response(404)

    def exa_mcp(self, request: httpx.Request, body: dict) -> httpx.Response:
        method = body.get("method")
        if method == "initialize":
            r = sse({"jsonrpc": "2.0", "id": body["id"], "result": {
                "protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                "serverInfo": {"name": "exa-search-server", "version": "3.5.0"}}})
            r.headers["mcp-session-id"] = self.exa_session
            return r
        if method == "notifications/initialized":
            return httpx.Response(202)
        if request.headers.get("mcp-session-id") != self.exa_session:
            return httpx.Response(400, json={"error": "no session"})
        if method == "tools/call":
            if self.exa_tool_error:
                return sse({"jsonrpc": "2.0", "id": body["id"], "result": {
                    "isError": True, "content": [{"type": "text", "text": self.exa_tool_error}]}})
            return sse({"jsonrpc": "2.0", "id": body["id"], "result": {
                "content": [{"type": "text", "text": self.exa_text}]}})
        return sse({"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32601,
                                                                      "message": "no method"}})

    def anthropic(self, body: dict) -> httpx.Response:
        result = ({"type": "web_search_tool_result_error", "error_code": self.anthropic_error}
                  if self.anthropic_error else [
                      {"type": "web_search_result", "url": "https://example.net/a",
                       "title": "A dated page", "encrypted_content": "opaque",
                       "page_age": "October 14, 2026"},
                      {"type": "web_search_result", "url": "https://example.net/b",
                       "title": "An undated page", "encrypted_content": "opaque"}])
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": body.get("model"),
            "stop_reason": "end_turn",
            "content": [
                {"type": "server_tool_use", "id": "srv_1", "name": "web_search",
                 "input": {"query": "q"}},
                {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": result},
                {"type": "text", "text": "done", "citations": [
                    {"type": "web_search_result_location", "url": "https://example.net/a",
                     "title": "A dated page", "cited_text": "What the page says."}]}],
            "usage": {"input_tokens": 2000, "output_tokens": 5,
                      "server_tool_use": {"web_search_requests": 1}}})
