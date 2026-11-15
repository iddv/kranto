"""The backends behind ``websearch``: one class each, ``search(query, since, n)`` returning
``Hit``s (``backend``, ``query`` and ``rank`` are set by the searcher) or raising
``BackendError``. Every request goes through ``sources.HTTP``: public addresses only, a size
cap, per-host pacing (arXiv's three seconds in ``pacing.HOST_GAPS``).

- **Exa** (``exa.ai``): with a key, ``POST https://api.exa.ai/search`` (highlights, a
  ``startPublishedDate`` for recency; its ``costDollars`` is what the ledger records). Without
  one, Exa's hosted MCP server at ``mcp.exa.ai/mcp``, which its docs offer as "free
  rate-limited usage without sign-in or API key": a streamable-HTTP JSON-RPC session
  (``initialize``, then ``tools/call`` of ``web_search_exa``), its text reply parsed into hits.
  The free mode has no date filter, so recency is asked for in the tool's ``objective`` and
  the searcher drops dated hits older than asked. A 429 is the free limit: the caller says
  so, and a key removes it.
- **Brave** (``api.search.brave.com``, ``BRAVE_API_KEY``): its web search, ``freshness`` as a
  date range, ``page_age`` (else ``age``) as the date.
- **Tavily** (``api.tavily.com``, ``TAVILY_API_KEY``): its basic search (one credit),
  ``start_date`` for recency, ``published_date`` asked for.
- **Anthropic** web search: the Messages API's ``web_search`` server tool, one search on the
  watcher's Claude API key, results read from ``web_search_tool_result`` with ``page_age``
  ($10 per 1,000 searches plus the tokens; the reply's usage prices the call).
- **Hacker News** through Algolia (``/search``, stories, more than 2 points, ``created_at_i``
  for recency), free, 10,000 requests an hour.
- **GitHub** repository search, through the GitHub connection when there is one, else
  unauthenticated (10 a minute); recency is ``created:>`` (what is new, not what moved).
- **arXiv**'s export API, the same query rules as the ``arxiv`` source kind.
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime

from ..sources import HTTP, SourceError
from . import BackendError, Hit

EXA_API = "https://api.exa.ai/search"
EXA_MCP = "https://mcp.exa.ai/mcp"
MCP_PROTOCOL = "2025-03-26"
DEADLINE = 45.0


def on_site(url: str, site: str | None) -> bool:
    """Whether ``url`` is on ``site`` (a host; its subdomains count)."""
    if not site:
        return True
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    site = site.lower().removeprefix("www.")
    return host == site or host.endswith("." + site)


def _hit(url, title, date, snippet) -> Hit | None:
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    return Hit(url=url, title=" ".join(str(title or "").split()) or url, date=date,
               snippet=" ".join(str(snippet or "").split()), backend="", query="", rank=0)


def day(value) -> str | None:
    """``YYYY-MM-DD`` from an ISO timestamp or date, or a "March 9, 2026" style date; None
    for anything else (never a guess)."""
    text = str(value or "").strip()
    if not text or text.upper() in ("N/A", "NONE", "NULL"):
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return m.group(1)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _source_error(exc: SourceError) -> BackendError:
    text = str(exc)
    if "HTTP 429" in text:
        return BackendError("rate-limited (HTTP 429)")
    if "HTTP 401" in text or "HTTP 403" in text:
        return BackendError(f"refused ({text.split(': ')[-1]})")
    return BackendError(text.split(": ", 1)[-1][:200])


# -- Exa -------------------------------------------------------------------------------------


class Exa:
    name = "exa"

    def __init__(self, http: HTTP, *, key: str | None = None) -> None:
        self.http = http
        self._key = key
        self.free_mode = not key
        self.last_usd: float | None = None
        self._session: str | None = None
        self._id = 0

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        self.last_usd = None
        return self._rest(query, start, n, site) if self._key else \
            self._mcp(query, start, n, site)

    # with a key: the REST API
    def _rest(self, query, start, n, site=None) -> list[Hit]:
        body: dict = {"query": query, "numResults": n, "type": "auto",
                      "contents": {"highlights": {"maxCharacters": 400}}}
        if site:
            body["includeDomains"] = [site]
        if start is not None:
            body["startPublishedDate"] = start.strftime("%Y-%m-%dT00:00:00.000Z")
        try:
            response = self.http.post(EXA_API, json=body, deadline=DEADLINE,
                                      headers={"x-api-key": self._key,
                                               "Content-Type": "application/json"})
            data = response.json()
        except SourceError as exc:
            raise _source_error(exc) from None
        except ValueError:
            raise BackendError("Exa's reply is not JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise BackendError(f"unexpected Exa reply: {str(data)[:200]}")
        cost = data.get("costDollars")
        if isinstance(cost, dict) and isinstance(cost.get("total"), int | float):
            self.last_usd = float(cost["total"])
        out = []
        for row in data["results"]:
            if not isinstance(row, dict):
                continue
            highlights = row.get("highlights")
            snippet = " ... ".join(h for h in highlights if isinstance(h, str)) \
                if isinstance(highlights, list) else str(row.get("text") or "")[:400]
            hit = _hit(row.get("url"), row.get("title"), day(row.get("publishedDate")), snippet)
            if hit:
                out.append(hit)
        return out

    # without a key: the hosted MCP server's free mode
    def _rpc(self, method: str, params: dict | None = None, *, notify: bool = False):
        body: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        try:
            response = self.http.post(EXA_MCP, json=body, headers=headers, deadline=DEADLINE)
        except SourceError as exc:
            raise _source_error(exc) from None
        self._session = response.headers.get("mcp-session-id") or self._session
        if notify:
            return None
        return parse_mcp_reply(response.text)

    def _initialize(self) -> None:
        self._session = None
        self._rpc("initialize", {"protocolVersion": MCP_PROTOCOL, "capabilities": {},
                                 "clientInfo": {"name": "kranto", "version": "0.4"}})
        self._rpc("notifications/initialized", notify=True)

    def _mcp(self, query, start, n, site=None) -> list[Hit]:
        objective = f"Pages that answer or cover: {query}. Rank recent pages first."
        if start is not None:
            objective += f" Prefer pages published after {start.date().isoformat()}."
        if site:
            objective += f" Only pages on {site}."
        args = {"query": query, "numResults": n, "objective": objective}
        if self._session is None:
            self._initialize()
        try:
            reply = self._rpc("tools/call", {"name": "web_search_exa", "arguments": args})
        except BackendError as exc:
            if "429" in str(exc):
                raise
            # a session the server forgot answers 4xx: one new session, once
            self._initialize()
            reply = self._rpc("tools/call", {"name": "web_search_exa", "arguments": args})
        if "error" in reply:
            message = reply["error"].get("message") if isinstance(reply["error"], dict) else None
            raise BackendError(f"Exa refused the search: {str(message or reply['error'])[:200]}")
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        text = "\n".join(part.get("text", "") for part in result.get("content") or []
                         if isinstance(part, dict) and part.get("type") == "text")
        if result.get("isError"):
            raise BackendError(f"Exa: {text[:200] or 'the search failed'}")
        return parse_exa_text(text)


def parse_mcp_reply(raw: str) -> dict:
    """A JSON-RPC reply sent as JSON or as server-sent events (the last ``data:`` line that
    holds an ``id``)."""
    raw = raw or ""
    found = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                obj = json.loads(line[5:].strip())
            except ValueError:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                found = obj
    if found is not None:
        return found
    try:
        obj = json.loads(raw)
    except ValueError:
        raise BackendError("Exa's reply is neither JSON nor events") from None
    if not isinstance(obj, dict):
        raise BackendError("unexpected Exa reply")
    return obj


def parse_exa_text(text: str) -> list[Hit]:
    """``web_search_exa``'s text: results separated by ``---`` lines, each ``Title:``,
    ``URL:``, ``Published:`` (or N/A), ``Author:``, ``Highlights:`` then the highlights."""
    out = []
    for chunk in re.split(r"\n-{3,}\n", text or ""):
        title = url = date = None
        rest: list[str] = []
        for line in chunk.splitlines():
            if line.startswith("Title:") and title is None:
                title = line[6:].strip()
            elif line.startswith("URL:") and url is None:
                url = line[4:].strip()
            elif line.startswith("Published:") and date is None:
                date = day(line[10:])
            elif line.startswith(("Author:", "Highlights:")):
                continue
            elif title is not None:
                stripped = line.strip().lstrip("#").strip()
                if stripped and stripped != "..." and stripped != title:
                    rest.append(stripped)
        if title is None and url is None:
            continue
        hit = _hit(url, title, date, " ".join(rest)[:600])
        if hit:
            out.append(hit)
    return out


# -- Anthropic's web search tool ---------------------------------------------------------------


def anthropic_model(llm) -> str:
    """The cheapest tier's model when that tier runs on the Claude API, else Haiku 5.5."""
    for tier in ("judge", "reason"):
        if llm.provider_for(tier) == "anthropic":
            return llm.model_for(tier)
    return "claude-haiku-5-5"


class AnthropicSearch:
    name = "anthropic"
    free_mode = False
    TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}

    def __init__(self, http: HTTP, *, base_url: str, key: str | None, model: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._key = key
        self.model = model
        self.last_usd: float | None = None

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        from .. import pricing

        self.last_usd = None
        if not self._key:
            raise BackendError("needs the watcher's Claude API key (llm.anthropic.api_key_env)")
        ask = f"Search the web once for: {query}"
        if start is not None:
            ask += f" (pages from after {start.date().isoformat()})"
        tool = {**self.TOOL, **({"allowed_domains": [site]} if site else {})}
        body = {"model": self.model, "max_tokens": 256, "tools": [tool],
                "messages": [{"role": "user", "content": ask + ". Then reply with the word "
                              "done and nothing else."}]}
        try:
            response = self.http.post(f"{self.base_url}/v1/messages", json=body,
                                      deadline=DEADLINE,
                                      headers={"x-api-key": self._key,
                                               "anthropic-version": "2023-06-01",
                                               "content-type": "application/json"})
            data = response.json()
        except SourceError as exc:
            raise _source_error(exc) from None
        except ValueError:
            raise BackendError("the Claude API's reply is not JSON") from None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
        tokens = pricing.cost(self.model, input_tokens=usage.get("input_tokens"),
                              output_tokens=usage.get("output_tokens")) or 0.0
        self.last_usd = tokens + pricing.search_cost("anthropic_search", int(searches))
        quotes: dict[str, str] = {}
        results: list[dict] = []
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "web_search_tool_result":
                content = block.get("content")
                if isinstance(content, dict):
                    raise BackendError(f"web search error: {content.get('error_code')}")
                results += [r for r in content or [] if isinstance(r, dict)]
            for cite in block.get("citations") or []:
                if isinstance(cite, dict) and cite.get("url") and cite.get("cited_text"):
                    quotes.setdefault(cite["url"], cite["cited_text"])
        out = []
        for row in results[:n]:
            hit = _hit(row.get("url"), row.get("title"), day(row.get("page_age")),
                       quotes.get(row.get("url"), ""))
            if hit:
                out.append(hit)
        return out


# -- Brave and Tavily (with a key each) ------------------------------------------------------


class Brave:
    name = "brave"
    free_mode = False
    # Brave's API terms (3(b)(i), read 2026-10-17) allow no storing or caching of results but
    # "transient storage" an application needs: its results skip the day cache
    cacheable = False
    API = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, http: HTTP, *, key: str | None) -> None:
        self.http = http
        self._key = key
        self.last_usd: float | None = None

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        if not self._key:
            raise BackendError("needs BRAVE_API_KEY (a Brave Search API key)")
        params = {"q": query + (f" site:{site}" if site else ""), "count": min(n, 20)}
        if start is not None:
            params["freshness"] = f"{start.date().isoformat()}to{datetime.now().date()}"
        try:
            data = self.http.get_json(self.API, params=params, deadline=DEADLINE,
                                      headers={"X-Subscription-Token": self._key,
                                               "Accept": "application/json"})
        except SourceError as exc:
            raise _source_error(exc) from None
        rows = ((data.get("web") or {}).get("results") if isinstance(data, dict) else None)
        if not isinstance(rows, list):
            rows = []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            hit = _hit(row.get("url"), row.get("title"),
                       day(row.get("page_age")) or day(row.get("age")),
                       " ".join(str(x) for x in [row.get("description") or "",
                                                 *(row.get("extra_snippets") or [])[:2]]))
            if hit:
                out.append(hit)
        return out


class Tavily:
    name = "tavily"
    free_mode = False
    API = "https://api.tavily.com/search"

    def __init__(self, http: HTTP, *, key: str | None) -> None:
        self.http = http
        self._key = key
        self.last_usd: float | None = None

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        if not self._key:
            raise BackendError("needs TAVILY_API_KEY (a Tavily API key)")
        body: dict = {"query": query, "max_results": min(n, 20), "search_depth": "basic",
                      "topic": "general", "include_published_date": True,
                      "include_usage": True}
        if start is not None:
            body["start_date"] = start.date().isoformat()
        if site:
            body["include_domains"] = [site]
        try:
            response = self.http.post(self.API, json=body, deadline=DEADLINE,
                                      headers={"Authorization": f"Bearer {self._key}",
                                               "Content-Type": "application/json"})
            data = response.json()
        except SourceError as exc:
            raise _source_error(exc) from None
        except ValueError:
            raise BackendError("Tavily's reply is not JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise BackendError(f"unexpected Tavily reply: {str(data)[:200]}")
        out = []
        for row in data["results"]:
            if isinstance(row, dict):
                hit = _hit(row.get("url"), row.get("title"), day(row.get("published_date")),
                           str(row.get("content") or "")[:600])
                if hit:
                    out.append(hit)
        return out


# -- the free three -------------------------------------------------------------------------------


class HackerNews:
    name = "hackernews"
    free_mode = False
    last_usd = 0.0
    API = "https://hn.algolia.com/api/v1/search"

    def __init__(self, http: HTTP) -> None:
        self.http = http

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        filters = "points>2" + (f",created_at_i>{int(start.timestamp())}" if start else "")
        try:
            # typo tolerance off, as the hackernews source does: a near-miss word matched
            # stories about something else
            data = self.http.get_json(self.API, deadline=DEADLINE, params={
                "query": query, "tags": "story", "hitsPerPage": n, "numericFilters": filters,
                "typoTolerance": "false"})
        except SourceError as exc:
            raise _source_error(exc) from None
        hits = data.get("hits") if isinstance(data, dict) else None
        if not isinstance(hits, list):
            raise BackendError("unexpected Algolia reply")
        out = []
        for h in hits:
            if not isinstance(h, dict) or not h.get("objectID"):
                continue
            thread = f"https://news.ycombinator.com/item?id={h['objectID']}"
            hit = _hit(h.get("url") or thread, h.get("title"), day(h.get("created_at")),
                       f"{h.get('points') or 0} points, {h.get('num_comments') or 0} comments "
                       f"on Hacker News ({thread})")
            if hit:
                out.append(hit)
        return out


class GitHub:
    name = "github"
    free_mode = False
    last_usd = 0.0
    API = "https://api.github.com/search/repositories"

    def __init__(self, http: HTTP, *, connections=None) -> None:
        self.http = http
        self.connections = connections

    def _http(self) -> HTTP:
        if self.connections is not None:
            # not connected: unauthenticated, 10 searches a minute
            with contextlib.suppress(SourceError):
                return self.connections.http_for("github", None, self.http)
        return self.http

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        q = query + (f" created:>{start.date().isoformat()}" if start else "")
        try:
            data = self._http().get_json(self.API, deadline=DEADLINE, params={
                "q": q, "per_page": n},
                headers={"Accept": "application/vnd.github+json"})
        except SourceError as exc:
            raise _source_error(exc) from None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise BackendError(f"unexpected GitHub reply: {str(data)[:200]}")
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            created, pushed = day(it.get("created_at")), day(it.get("pushed_at"))
            desc = " ".join(str(it.get("description") or "").split())[:240]
            hit = _hit(it.get("html_url"), it.get("full_name"), created,
                       f"{it.get('stargazers_count') or 0} stars, created {created or '?'}, "
                       f"last push {pushed or '?'}: {desc}")
            if hit:
                out.append(hit)
        return out


class Arxiv:
    name = "arxiv"
    free_mode = False
    last_usd = 0.0

    def __init__(self, http: HTTP) -> None:
        self.http = http

    def search(self, query: str, start: datetime | None, n: int,
               site: str | None = None) -> list[Hit]:
        from ..sources.arxiv import API, search_query
        from ..sources.rss import parse_feed

        try:
            response = self.http.get(API, deadline=DEADLINE, params={
                "search_query": search_query(query[:200]),
                "sortBy": "submittedDate" if start else "relevance",
                "sortOrder": "descending", "start": 0, "max_results": n})
            _, items = parse_feed(response.content)
        except SourceError as exc:
            raise _source_error(exc) from None
        if len(items) == 1 and items[0].title.strip().lower() == "error":
            raise BackendError(f"arXiv refused the query: {items[0].body[:200]}")
        out = []
        for it in items:
            hit = _hit(it.url or it.link, it.title,
                       it.published_at.date().isoformat() if it.published_at else None,
                       it.body[:400])
            if hit:
                out.append(hit)
        return out
