"""Bluesky custom feeds and lists through the public AppView; timeline and search signed in.

``public.api.bsky.app`` serves a feed generator's posts (``getFeed``) and the
posts of a list's members (``getListFeed``) without a login. A profile's posts
are an ordinary feed (``bsky.app/profile/<handle>/rss``, the catalog's
"Profile").

The home timeline (``getTimeline``) and search (``searchPosts``, which Bluesky
now serves only to a signed-in account) are read with a connected account
(``what``: home or search): the request goes to the account's PDS, which the
connection's ``HTTP`` names (``auth_host``) and signs (DPoP, or an app
password's session), and the PDS proxies it to the AppView.

Authors are not kept: a post becomes its text, the page it links to, and its
own URL (which names the account by its DID, as any link to the post does).
"""

from __future__ import annotations

import re

from .base import HTTP, Item, SourceError, safe_url
from .rss import _parse_date

API = "https://public.api.bsky.app/xrpc"
LIMIT = 50
TITLE_CHARS = 140
_FEED_URI = re.compile(r"^at://did:[a-z]+:[A-Za-z0-9._:%-]+/app\.bsky\.feed\.generator/[\w.~-]+$")
_LIST_URI = re.compile(r"^at://did:[a-z]+:[A-Za-z0-9._:%-]+/app\.bsky\.graph\.list/[\w.~-]+$")


def post_url(uri: str) -> str | None:
    """``https://bsky.app/profile/<did>/post/<rkey>`` for a post's ``at://`` URI."""
    m = re.match(r"^at://(did:[^/]+)/app\.bsky\.feed\.post/([\w.~-]+)$", uri or "")
    return f"https://bsky.app/profile/{m.group(1)}/post/{m.group(2)}" if m else None


def post_item(post: dict) -> Item | None:
    """An item from one ``app.bsky.feed.defs#postView``; None if it is not a post."""
    uri = post.get("uri") if isinstance(post, dict) else None
    record = post.get("record") if isinstance(post, dict) else None
    if not isinstance(uri, str) or not isinstance(record, dict):
        return None
    text = record.get("text") if isinstance(record.get("text"), str) else ""
    external = ((post.get("embed") or {}).get("external") or {}) \
        if isinstance(post.get("embed"), dict) else {}
    link = safe_url(external.get("uri")) if isinstance(external, dict) else None
    ext_title = external.get("title") if isinstance(external.get("title"), str) else ""
    ext_desc = external.get("description") \
        if isinstance(external.get("description"), str) else ""
    first = " ".join(text.split())
    title = first[:TITLE_CHARS] + (" ..." if len(first) > TITLE_CHARS else "") \
        if first else ext_title
    body = "\n\n".join(part for part in (text, ext_title, ext_desc) if part)
    return Item(id=uri, title=title or "(no text)", body=body, url=post_url(uri), link=link,
                published_at=_parse_date(record.get("createdAt") or ""))


WHATS = ("home", "search")


class BlueskySource:
    kind = "bluesky"

    @staticmethod
    def needs_for(params: dict) -> str | None:
        """The home timeline and search read with a connected account; feeds and
        lists do not."""
        return "bluesky" if params.get("what") else None

    def __init__(self, http: HTTP, *, feed_uri: str | None = None, list_uri: str | None = None,
                 title: str | None = None, what: str | None = None,
                 query: str | None = None) -> None:
        self.http = http
        self.feed_uri, self.list_uri, self.title = feed_uri, list_uri, title
        self.what, self.query = what, " ".join(str(query or "").split())[:200] or None
        if what is not None:
            if what not in WHATS:
                raise ValueError(f"unknown bluesky timeline {what!r}; one of {', '.join(WHATS)}")
            if feed_uri or list_uri:
                raise ValueError("a signed-in bluesky source takes no feed or list")
            if what == "search" and not self.query:
                raise ValueError("a bluesky search needs a query")
            return
        if bool(feed_uri) == bool(list_uri):
            raise ValueError("a bluesky source needs exactly one of 'feed_uri' or 'list_uri'")
        if feed_uri and not _FEED_URI.match(feed_uri):
            raise ValueError(f"not a Bluesky feed generator URI: {feed_uri!r}")
        if list_uri and not _LIST_URI.match(list_uri):
            raise ValueError(f"not a Bluesky list URI: {list_uri!r}")

    @property
    def label(self) -> str:
        if self.what == "home":
            return "Your Bluesky home timeline"
        if self.what == "search":
            return f"Bluesky search: {self.query}"
        what = "feed" if self.feed_uri else "list"
        return f"Bluesky {what}: {self.title}" if self.title else f"Bluesky {what}"

    def _signed_in(self) -> list:
        host = self.http.auth_host
        if not host:
            raise SourceError("needs login: no Bluesky account is connected", needs_login=True)
        if self.what == "home":
            payload = self.http.get_json(f"https://{host}/xrpc/app.bsky.feed.getTimeline",
                                         params={"limit": LIMIT})
            entries = payload.get("feed") if isinstance(payload, dict) else None
            posts = [e.get("post") for e in entries if isinstance(e, dict)] \
                if isinstance(entries, list) else None
        else:
            payload = self.http.get_json(f"https://{host}/xrpc/app.bsky.feed.searchPosts",
                                         params={"q": self.query, "sort": "latest",
                                                 "limit": LIMIT})
            posts = payload.get("posts") if isinstance(payload, dict) else None
        if not isinstance(posts, list):
            message = payload.get("message") if isinstance(payload, dict) else None
            raise SourceError(f"unexpected Bluesky reply: {str(message or payload)[:200]}")
        return posts

    def fetch(self) -> list[Item]:
        if self.what:
            return [item for item in map(post_item, self._signed_in()) if item is not None]
        if self.feed_uri:
            payload = self.http.get_json(f"{API}/app.bsky.feed.getFeed",
                                         params={"feed": self.feed_uri, "limit": LIMIT})
        else:
            payload = self.http.get_json(f"{API}/app.bsky.feed.getListFeed",
                                         params={"list": self.list_uri, "limit": LIMIT})
        entries = payload.get("feed") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            message = payload.get("message") if isinstance(payload, dict) else None
            raise SourceError(f"unexpected Bluesky reply: {str(message or payload)[:200]}")
        items = []
        for entry in entries:
            item = post_item(entry.get("post")) if isinstance(entry, dict) else None
            if item is not None:
                items.append(item)
        return items

    def enrich(self, item: Item) -> Item:
        return item
