"""X search through Grok (xAI's ``x_search`` tool): the second X path,
for a person with an xAI key (``XAI_API_KEY`` in the home's ``.env``) and no X developer app.
Off until that key is set: without it the source says "Needs login: no xAI key".

One metered call a fetch (``LLMClient.complete(provider="xai")``: an ``llm_calls`` row, in the
watcher's budget), once a day (``x.search_every_hours``), asking Grok to search X for the topic
since the last fetch's day and list the distinct posts it read: ``{"posts": [{"url", "date",
"gist", "link"}]}``. Each becomes an item under the post's id, with its handle-less URL, the
model's own gist as title and body (never the post's text: nothing X-licensed is asked for or
kept) and ``capture_note`` "a Grok digest, not the post", so the judge knows what it reads. A
post Grok cites (``url_citation``) but does not list becomes an item with the citation's
title. Items dedup by canonical URL against posts read through the X API.

Cost: the tokens at grok-4.7's price and $5 per 1,000 posts the tool fetched, as xAI bills."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from .base import HTTP, Item, SourceError, safe_url

KEY_ENV = "XAI_API_KEY"
STATUS = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/(?:[A-Za-z0-9_]{1,15}|i(?:/web)?)"
                    r"/status/([0-9]{1,19})")
NOTE = "a Grok digest, not the post"
MAX_POSTS = 20
GIST_CHARS = 300


def post_id(url: str | None) -> str | None:
    m = STATUS.match(str(url or ""))
    return m.group(1) if m else None


class XAISearchSource:
    kind = "xai_search"
    # read with the watcher's metered client and the xAI key, not a connection
    needs_llm = True

    def __init__(self, http: HTTP, *, query: str, handles: str | None = None,
                 llm=None) -> None:
        self.http, self.llm = http, llm
        self.query = " ".join(str(query or "").split())[:300]
        if not self.query:
            raise ValueError("a Grok X search needs a query")
        self.handles = [h.lstrip("@") for h in re.split(r"[\s,]+", handles or "") if h][:20]
        if any(not re.fullmatch(r"[A-Za-z0-9_]{1,15}", h) for h in self.handles):
            raise ValueError("handles are X usernames, at most 20")

    @property
    def label(self) -> str:
        return f"X search through Grok: {self.query}"

    def fetch(self, *, since: datetime | None = None) -> list[Item]:
        from .. import prompts

        if self.llm is None:
            raise SourceError("needs login: the watcher's client is not available here",
                              needs_login=True)
        if not self.llm.has_key_for(KEY_ENV):
            raise SourceError(f"needs login: no xAI key (set {KEY_ENV} in the home's .env; "
                              "Settings › Watching)", needs_login=True)
        since = since or datetime.now(UTC) - timedelta(days=1)
        tool: dict = {"type": "x_search", "from_date": since.strftime("%Y-%m-%d")}
        if self.handles:
            tool["allowed_x_handles"] = self.handles
        prompt = prompts.load("xai_search")
        completion = self.llm.complete(
            tier="judge", purpose="xai_search", provider="xai", model="grok-4.7",
            prompt_version=prompt.version, max_tokens=2000, tools=(tool,),
            messages=[{"role": "user", "content": prompt.render(
                query=self.query, since=since.strftime("%Y-%m-%d"),
                max_posts=str(MAX_POSTS))}])
        return digest_items(completion.text, (completion.structured or {}).get("citations")
                            or [])

    def enrich(self, item: Item) -> Item:
        return item


def digest_items(text: str, citations: list[dict]) -> list[Item]:
    """Items from Grok's reply: the posts it listed, then any it cited without listing."""
    from ..intern import extract_json_object

    obj = extract_json_object(text) or {}
    posts = obj.get("posts") if isinstance(obj.get("posts"), list) else []
    out: dict[str, Item] = {}
    for p in posts[:MAX_POSTS]:
        if not isinstance(p, dict):
            continue
        pid = post_id(p.get("url"))
        gist = " ".join(str(p.get("gist") or "").split())[:GIST_CHARS]
        if not pid or not gist or pid in out:
            continue
        link = safe_url(p.get("link"))
        out[pid] = Item(id=pid, title=gist[:140], body=gist,
                        url=f"https://x.com/i/status/{pid}",
                        link=link if link and post_id(link) is None else None,
                        published_at=_date(p.get("date")), capture_note=NOTE,
                        meta={"x": {"via": "grok"}})
    for c in citations:
        pid = post_id(c.get("url"))
        title = " ".join(str(c.get("title") or "").split())[:140]
        if pid and pid not in out and title and not title.isdigit():
            out[pid] = Item(id=pid, title=title, body=title,
                            url=f"https://x.com/i/status/{pid}", capture_note=NOTE,
                            meta={"x": {"via": "grok"}})
    return list(out.values())


def _date(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None
