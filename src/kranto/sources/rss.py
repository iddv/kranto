"""RSS 2.0 and Atom feeds.

Covers blogs, newsletters, arXiv listings, GitHub release feeds, YouTube
channels, Bluesky profiles and most news sites. Parsing uses defusedxml
because feed URLs are untrusted input.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from .base import HTTP, Item, SourceError, html_to_text

ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
DC = "{http://purl.org/dc/elements/1.1/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
RSS1 = "{http://purl.org/rss/1.0/}"


def _text(el: Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _parse_date(value: str) -> datetime | None:
    """Parse ISO 8601 or RFC 822 dates. A date without a zone is taken as UTC:
    some feeds (Nature's ``dc:date``) omit it, and a naive datetime cannot be
    compared with the aware ones everything else uses."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _fallback_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]


def parse_feed(content: bytes) -> tuple[str, list[Item]]:
    """Return the feed title and its items, newest first as published."""
    try:
        root = SafeET.fromstring(content)
    except Exception as exc:  # defusedxml raises several unrelated types
        raise SourceError(f"not a parseable feed: {type(exc).__name__}", transient=False) from exc

    if root.tag == f"{ATOM}feed":
        title = _text(root.find(f"{ATOM}title"))
        items = []
        for entry in root.findall(f"{ATOM}entry"):
            link = ""
            for link_el in entry.findall(f"{ATOM}link"):
                if link_el.get("rel", "alternate") == "alternate":
                    link = link_el.get("href", "")
                    break
            body_el = entry.find(f"{ATOM}content")
            if body_el is None:
                body_el = entry.find(f"{ATOM}summary")
            entry_title = html_to_text(_text(entry.find(f"{ATOM}title")))
            entry_id = (_text(entry.find(f"{ATOM}id")) or link
                        or _fallback_id(entry_title, _text(body_el)[:200]))
            items.append(
                Item(
                    id=entry_id,
                    title=entry_title,
                    body=html_to_text(_text(body_el)),
                    url=link or None,
                    published_at=_parse_date(
                        _text(entry.find(f"{ATOM}published"))
                        or _text(entry.find(f"{ATOM}updated"))
                    ),
                )
            )
        return title, items

    if root.tag == f"{RDF}RDF":  # RSS 1.0: items are siblings of the channel
        title = _text(root.find(f"{RSS1}channel/{RSS1}title"))
        items = []
        for entry in root.findall(f"{RSS1}item"):
            link = _text(entry.find(f"{RSS1}link"))
            entry_title = html_to_text(_text(entry.find(f"{RSS1}title")))
            body = (_text(entry.find(f"{CONTENT}encoded"))
                    or _text(entry.find(f"{RSS1}description")))
            items.append(
                Item(
                    id=entry.get(f"{RDF}about") or link or _fallback_id(entry_title, body[:200]),
                    title=entry_title,
                    body=html_to_text(body),
                    url=link or None,
                    published_at=_parse_date(_text(entry.find(f"{DC}date"))),
                )
            )
        return title, items

    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise SourceError(f"unrecognised feed root <{root.tag}>", transient=False)
    title = _text(channel.find("title"))
    items = []
    for entry in channel.findall("item"):
        link = _text(entry.find("link"))
        entry_title = html_to_text(_text(entry.find("title")))
        body = _text(entry.find(f"{CONTENT}encoded")) or _text(entry.find("description"))
        entry_id = _text(entry.find("guid")) or link or _fallback_id(entry_title, body[:200])
        items.append(
            Item(
                id=entry_id,
                title=entry_title,
                body=html_to_text(body),
                url=link or None,
                published_at=_parse_date(_text(entry.find("pubDate"))),
            )
        )
    return title, items


class RSSSource:
    kind = "rss"

    def __init__(self, http: HTTP, *, url: str, title: str | None = None) -> None:
        self.http = http
        self.url = url
        self._title = title

    @property
    def label(self) -> str:
        return self._title or self.url

    def fetch(self) -> list[Item]:
        response = self.http.get(self.url)
        title, items = parse_feed(response.content)
        if title and not self._title:
            self._title = title
        return items

    def enrich(self, item: Item) -> Item:
        return item
