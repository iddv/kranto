"""Hacker News via the Algolia search API.

A source is either a feed (``front``, ``new``, ``show``, ``ask``) or a search
query over recent stories, which makes HN topic-addressable.

HN link posts carry a title and a URL and nothing else, which is why HN
yielded roughly four times less than Reddit in Parallax (exp 16): the judge
had almost nothing to read. ``enrich`` adds the top comments for items that
reach the judge, and HN discussion is often where the substance is.

A query source's first fetch (``fetch_backfill``) reaches back
``backfill_days`` through Algolia's ``created_at_i`` filter, so a new topic
starts with recent history instead of an empty page.

Query searches turn off Algolia's typo tolerance. With it on, a short technical
query matches near-miss words: "CRDT" returned 4 relevant stories in 50, the
rest matching critical or Criterion.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..store import utcnow
from .base import HTTP, Item, SourceError, from_timestamp, html_to_text

API = "https://hn.algolia.com/api/v1"
FEEDS = {"front": "front_page", "new": "story", "show": "show_hn", "ask": "ask_hn"}
MAX_COMMENTS = 5
COMMENT_CHARS = 600
DEFAULT_BACKFILL_DAYS = 14
BACKFILL_HITS = 100


class HackerNewsSource:
    kind = "hackernews"

    def __init__(
        self,
        http: HTTP,
        *,
        feed: str | None = None,
        query: str | None = None,
        backfill_days: int = DEFAULT_BACKFILL_DAYS,
    ) -> None:
        if bool(feed) == bool(query):
            raise ValueError("a hackernews source needs exactly one of 'feed' or 'query'")
        if feed and feed not in FEEDS:
            raise ValueError(f"unknown hackernews feed {feed!r}; one of {', '.join(FEEDS)}")
        if isinstance(backfill_days, bool) or not isinstance(backfill_days, int) \
                or backfill_days < 1:
            raise ValueError("backfill_days must be a whole number of days, at least 1")
        self.http = http
        self.feed = feed
        self.query = query
        self.backfill_days = backfill_days

    @property
    def label(self) -> str:
        return f"HN {self.feed}" if self.feed else f"HN search: {self.query}"

    def fetch_backfill(self, now: datetime | None = None) -> list[Item]:
        """First fetch of a query source: up to ``BACKFILL_HITS`` stories from the
        last ``backfill_days``. Feed sources have no date filter and fetch as usual."""
        if self.feed:
            return self.fetch()
        since = int(((now or utcnow()) - timedelta(days=self.backfill_days)).timestamp())
        payload = self.http.get_json(
            f"{API}/search_by_date",
            params={"tags": "story", "query": self.query, "hitsPerPage": BACKFILL_HITS,
                    "typoTolerance": "false", "numericFilters": f"created_at_i>{since}"},
        )
        return self._items(payload)

    def fetch(self) -> list[Item]:
        if self.feed == "front":
            payload = self.http.get_json(
                f"{API}/search", params={"tags": "front_page", "hitsPerPage": 50}
            )
        elif self.feed:
            payload = self.http.get_json(
                f"{API}/search_by_date", params={"tags": FEEDS[self.feed], "hitsPerPage": 50}
            )
        else:
            # The same window as the backfill: without it the newest 50 matches
            # reached back months once a query's recent stories were consumed.
            since = int((utcnow() - timedelta(days=self.backfill_days)).timestamp())
            payload = self.http.get_json(
                f"{API}/search_by_date",
                params={"tags": "story", "query": self.query, "hitsPerPage": 50,
                        "typoTolerance": "false", "numericFilters": f"created_at_i>{since}"},
            )
        return self._items(payload)

    @staticmethod
    def _items(payload) -> list[Item]:
        # A reply without a list of hits is an error (Algolia returns
        # {"message": ...} when it refuses), never a quiet feed.
        hits = payload.get("hits") if isinstance(payload, dict) else None
        if not isinstance(hits, list):
            message = payload.get("message") if isinstance(payload, dict) else None
            raise SourceError(f"unexpected Algolia reply: {str(message or payload)[:200]}")
        items = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            object_id = str(hit.get("objectID") or "")
            if not object_id:
                continue
            items.append(
                Item(
                    id=object_id,
                    title=_text(hit.get("title")),
                    body=html_to_text(_text(hit.get("story_text"))),
                    url=f"https://news.ycombinator.com/item?id={object_id}",
                    link=_text(hit.get("url")) or None,
                    published_at=from_timestamp(hit.get("created_at_i")),
                    meta={
                        "points": hit.get("points"),
                        "num_comments": hit.get("num_comments"),
                    },
                )
            )
        return items

    def enrich(self, item: Item) -> Item:
        if not item.meta.get("num_comments"):
            return item
        thread = self.http.get_json(f"{API}/items/{item.id}")
        children = thread.get("children") if isinstance(thread, dict) else None
        if not isinstance(children, list):
            raise SourceError(f"unexpected Algolia thread for item {item.id}")
        comments = []
        for child in children[:MAX_COMMENTS]:
            if not isinstance(child, dict):
                continue
            text = html_to_text(_text(child.get("text")))
            if text:
                comments.append(text[:COMMENT_CHARS])
        return Item(
            id=item.id, title=item.title, body=item.body, url=item.url, link=item.link,
            published_at=item.published_at, meta=item.meta, redactions=item.redactions,
            comments=tuple(comments),
        )


def _text(value) -> str:
    return value if isinstance(value, str) else ""
