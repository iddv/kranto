"""A site watched through live search: for a real, active site with no feed
Kranto can read (a forum, a newsletter's web page, a lab's news page), each fetch is one search
of the install's web backend restricted to the site (``site``), recent results first; every
result is an item (its title, the result's snippet, its link, its date) and is judged like any
other. 8 of the 11 sites the US measurement's grounded scout found invalid were such sites.

It costs what a search costs (Exa's free mode nothing; $0.007 with an Exa key, $0.005 Brave,
$0.008 Tavily), counted in ``api_spend`` against the caller ``sources``, and it pauses with the
rest of paid search at ``search.monthly_usd``. The scout proposes one for a site it found
without a feed, and never approves it itself. Reads through ``websearch.current()``, the
process's searcher (``open_runtime`` sets it); without one, or with ``search.callers.sources:
off``, the source says "no live search" and is retried like any transient failure."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .base import HTTP, Item, SourceError

MAX_RESULTS = 10
RECENCY = "4w"


def host_of(site: str) -> str:
    from urllib.parse import urlparse
    site = str(site or "").strip()
    host = urlparse(site if "//" in site else f"https://{site}").hostname or ""
    return host.lower().removeprefix("www.")


class WebSearchSource:
    kind = "websearch"

    def __init__(self, http: HTTP, *, site: str, query: str | None = None) -> None:
        self.http = http
        self.site = host_of(site)
        if not self.site or "." not in self.site:
            raise ValueError("a live-search source needs a site's address (example.org)")
        self.query = " ".join(str(query or "").split())[:200] or None

    @property
    def label(self) -> str:
        return f"Live search: {self.site}" + (f" ({self.query})" if self.query else "")

    def fetch(self) -> list[Item]:
        from .. import websearch
        searcher = websearch.current()
        if searcher is None:
            raise SourceError("no live search is configured in this process")
        found = searcher.for_caller("sources").search(
            self.query or f"new posts and discussions on {self.site}", recency=RECENCY,
            n=MAX_RESULTS, site=self.site)
        if not found.live:
            raise SourceError(found.note or websearch.NO_SEARCH)
        items = []
        for hit in found.hits:
            when = None
            if hit.date:
                try:
                    when = datetime.fromisoformat(hit.date).replace(tzinfo=UTC)
                except ValueError:
                    when = None
            items.append(Item(id=hashlib.sha256(hit.url.encode()).hexdigest()[:24],
                              title=hit.title, body=hit.snippet, url=hit.url,
                              published_at=when,
                              capture_note=f"a search result from {found.backend}, not the "
                                           "page"))
        return items

    def enrich(self, item: Item) -> Item:
        return item
