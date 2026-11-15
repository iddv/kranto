"""arXiv search through the export API.

A category listing is an ordinary feed (``rss.arxiv.org/rss/<category>``, the
catalog's "Category listing"); a search is this kind: the export API's Atom
reply for a query, newest submissions first. arXiv's terms of use ask for one
request every three seconds over a single connection: ``export.arxiv.org`` has a
three-second gap in ``pacing.HOST_GAPS``, and requests to it go one at a time,
process-wide, with its 429s backed off. https://info.arxiv.org/help/api/tou.html

A query without arXiv's field syntax is read as words that must all appear
(``all:a AND all:b``); one that already uses fields (``ti:``, ``cat:``, ``AND``)
is passed as written.
"""

from __future__ import annotations

import re

from .base import HTTP, Item, SourceError
from .rss import parse_feed

API = "https://export.arxiv.org/api/query"
MAX_RESULTS = 50
MAX_QUERY_CHARS = 200
_FIELDED = re.compile(r"\b(?:ti|au|abs|co|jr|cat|rn|id|all):|\b(?:AND|OR|ANDNOT)\b")


def search_query(query: str) -> str:
    """The export API's ``search_query`` for what a person typed."""
    query = " ".join(query.split())
    if _FIELDED.search(query):
        return query
    words = [w.strip('"') for w in query.split() if w.strip('"')]
    return " AND ".join(f"all:{w}" for w in words)


class ArxivSource:
    kind = "arxiv"

    def __init__(self, http: HTTP, *, query: str) -> None:
        query = " ".join(str(query or "").split())
        if not query or len(query) > MAX_QUERY_CHARS:
            raise ValueError(f"an arxiv search needs a query of 1 to {MAX_QUERY_CHARS} characters")
        self.http = http
        self.query = query

    @property
    def label(self) -> str:
        return f"arXiv search: {self.query}"

    def fetch(self) -> list[Item]:
        response = self.http.get(API, params={
            "search_query": search_query(self.query), "sortBy": "submittedDate",
            "sortOrder": "descending", "start": 0, "max_results": MAX_RESULTS})
        _, items = parse_feed(response.content)
        # The API answers a malformed query with a feed holding one "Error" entry.
        if len(items) == 1 and items[0].title.strip().lower() == "error":
            raise SourceError(f"arXiv refused the query: {items[0].body[:200]}", transient=False)
        return items

    def enrich(self, item: Item) -> Item:
        return item
