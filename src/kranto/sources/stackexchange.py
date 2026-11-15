"""Stack Exchange search through the public API, with the owner's app key if pasted.

``/2.3/search/advanced`` on one site, newest first, with each question's body.
No login is needed; a pasted app key (``connections.pasted``) raises the daily
allowance from 300 requests per address to 10,000, so this kind *uses* the
connection when there is one and reads without it otherwise. The API's
``backoff`` field (seconds to wait before the next request) is honoured
process-wide. Content is CC BY-SA: an observation links to the question; askers
are not kept. A tag on a site is an ordinary feed (the catalog's "Tag on a site").
"""

from __future__ import annotations

import re
import threading
import time

from .base import HTTP, Item, SourceError, from_timestamp, html_to_text, safe_url

API = "https://api.stackexchange.com/2.3"
LIMIT = 30
BODY_CHARS = 4000
_SITE = re.compile(r"(?:[a-z0-9-]+\.)?(?:stackexchange|stackoverflow|serverfault|superuser|"
                   r"askubuntu|mathoverflow)\.(?:com|net)")

_backoff_lock = threading.Lock()
_backoff_until = 0.0


def clean_site(value: str) -> str:
    site = re.sub(r"^https?://", "", str(value or "").strip().lower()).split("/")[0]
    if not _SITE.fullmatch(site):
        raise ValueError(f"not a Stack Exchange site such as stackoverflow.com: {value!r}")
    return site


class StackExchangeSource:
    kind = "stackexchange"
    # Reads with the owner's key when one is connected, and without it otherwise.
    uses = "stackexchange"

    def __init__(self, http: HTTP, *, site: str, query: str) -> None:
        query = " ".join(str(query or "").split())
        if not query:
            raise ValueError("a stackexchange search needs a query")
        self.http, self.site, self.query = http, clean_site(site), query[:200]

    @property
    def label(self) -> str:
        return f"{self.site} search: {self.query}"

    def fetch(self) -> list[Item]:
        global _backoff_until
        with _backoff_lock:
            wait = _backoff_until - time.monotonic()
        if wait > 0:
            raise SourceError(f"Stack Exchange asked for a pause of {wait:.0f}s more")
        data = self.http.get_json(f"{API}/search/advanced", params={
            "site": self.site, "q": self.query, "sort": "creation", "order": "desc",
            "pagesize": LIMIT, "filter": "withbody"})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise SourceError("unexpected Stack Exchange reply")
        backoff = data.get("backoff")
        if isinstance(backoff, int) and backoff > 0:
            with _backoff_lock:
                _backoff_until = max(_backoff_until, time.monotonic() + backoff)
        return [item for item in map(question_item, data["items"]) if item is not None]

    def enrich(self, item: Item) -> Item:
        return item


def question_item(q: dict) -> Item | None:
    if not isinstance(q, dict):
        return None
    url = safe_url(q.get("link"))
    if not url:
        return None
    title = html_to_text(str(q.get("title") or ""))
    body = html_to_text(q.get("body") if isinstance(q.get("body"), str) else "")
    tags = [t for t in q.get("tags") or [] if isinstance(t, str)]
    return Item(id=url, title=title or "(untitled question)", body=body[:BODY_CHARS], url=url,
                published_at=from_timestamp(q.get("creation_date")),
                meta={"stackexchange": {"tags": tags[:10], "score": q.get("score")}}
                if tags else {})
