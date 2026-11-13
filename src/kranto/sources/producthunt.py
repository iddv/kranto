"""Product Hunt launches through its GraphQL API, read with a pasted developer token.

The public feed (``producthunt.com/feed``, the catalog's "Today's launches")
needs no login. With a developer token (``connections.pasted``) the API gives
the last day's launches ranked by votes, optionally for one topic, with each
launch's tagline, description and website. One request per fetch, well inside
the 6,250 complexity points per 15 minutes. Makers are not kept. Product
Hunt's API terms allow non-commercial use.
"""

from __future__ import annotations

import re
from datetime import timedelta

from ..store import iso, utcnow
from .base import HTTP, Item, SourceError, safe_url
from .rss import _parse_date

API = "https://api.producthunt.com/v2/api/graphql"
LIMIT = 30
WHATS = ("launches",)
QUERY = """query($after: DateTime!, $topic: String, $first: Int!) {
  posts(first: $first, order: RANKING, postedAfter: $after, topic: $topic) {
    edges { node { id name tagline description url website votesCount createdAt } }
  }
}"""
TOPIC = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")


def clean_topic(value: str | None) -> str | None:
    topic = str(value or "").strip().lower().rstrip("/").rsplit("/", 1)[-1].replace(" ", "-")
    if not topic:
        return None
    if not TOPIC.fullmatch(topic):
        raise ValueError(f"not a Product Hunt topic such as developer-tools: {value!r}")
    return topic


class ProductHuntSource:
    kind = "producthunt"
    needs = "producthunt"

    def __init__(self, http: HTTP, *, what: str = "launches", topic: str | None = None) -> None:
        if what not in WHATS:
            raise ValueError(f"unknown producthunt source {what!r}; one of {', '.join(WHATS)}")
        self.http, self.what, self.topic = http, what, clean_topic(topic)

    @property
    def label(self) -> str:
        return f"Product Hunt launches: {self.topic}" if self.topic \
            else "Product Hunt launches"

    def fetch(self) -> list[Item]:
        after = iso(utcnow() - timedelta(days=1))
        response = self.http.post(API, json={"query": QUERY, "variables": {
            "after": after, "topic": self.topic, "first": LIMIT}},
            headers={"Accept": "application/json"})
        try:
            data = response.json()
        except ValueError as exc:
            raise SourceError(f"{API}: response is not JSON", transient=False) from exc
        edges = ((((data or {}).get("data") or {}).get("posts") or {}).get("edges")) \
            if isinstance(data, dict) else None
        if not isinstance(edges, list):
            errors = data.get("errors") if isinstance(data, dict) else None
            raise SourceError(f"unexpected Product Hunt reply: {str(errors or data)[:200]}")
        return [item for item in (launch_item((e or {}).get("node")) for e in edges
                                  if isinstance(e, dict)) if item is not None]

    def enrich(self, item: Item) -> Item:
        return item


def launch_item(node: dict) -> Item | None:
    if not isinstance(node, dict):
        return None
    url = safe_url(node.get("url"))
    if not url:
        return None
    name = str(node.get("name") or "")
    tagline = str(node.get("tagline") or "")
    title = f"{name}: {tagline}" if tagline else name
    votes = node.get("votesCount")
    meta = {"producthunt": {"votes": votes}} if isinstance(votes, int) else {}
    return Item(id=url, title=title or "(unnamed launch)",
                body="\n\n".join(p for p in (tagline, str(node.get("description") or "")) if p),
                url=url, link=safe_url(node.get("website")),
                published_at=_parse_date(node.get("createdAt") or ""), meta=meta)
