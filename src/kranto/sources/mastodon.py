"""Mastodon timelines read with a connected account.

The home timeline (what the account follows) and one of the account's lists,
from the instance's REST API, read with the token of a Mastodon connection
(``connections``). A hashtag's or an account's public posts need no login and
are ordinary feeds (``https://<instance>/tags/<tag>.rss``, ``/@<name>.rss``).

The adapter never sees the token: ``build`` hands it an ``HTTP`` that adds the
connection's headers at send time (``HTTP.with_auth``). Authors are not kept: a
status becomes its text, the page it links to (its preview card) and its own
URL. A boost is read as the boosted status, under its own id, so the same post
boosted twice is one item.
"""

from __future__ import annotations

import re

from .base import HTTP, Item, SourceError, html_to_text, safe_url
from .rss import _parse_date

LIMIT = 40
TITLE_CHARS = 140
WHATS = ("home", "list")
INSTANCE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean_instance(value: str) -> str:
    """A bare lowercase host name for an instance given as a host or a URL."""
    host = str(value or "").strip().lower()
    host = re.sub(r"^https?://", "", host).split("/")[0].split("@")[-1]
    if not INSTANCE.match(host):
        raise ValueError(f"not a Mastodon instance host name: {value!r}")
    return host


def status_item(status: dict) -> Item | None:
    """An item from one Mastodon status; None if it is not one."""
    if not isinstance(status, dict):
        return None
    if isinstance(status.get("reblog"), dict):
        status = status["reblog"]
    sid, url = status.get("id"), safe_url(status.get("url") or status.get("uri"))
    if not sid or not url:
        return None
    text = html_to_text(status.get("content") if isinstance(status.get("content"), str) else "")
    spoiler = status.get("spoiler_text") if isinstance(status.get("spoiler_text"), str) else ""
    card = status.get("card") if isinstance(status.get("card"), dict) else {}
    card_title = card.get("title") if isinstance(card.get("title"), str) else ""
    card_desc = card.get("description") if isinstance(card.get("description"), str) else ""
    first = " ".join((spoiler or text).split())
    title = first[:TITLE_CHARS] + (" ..." if len(first) > TITLE_CHARS else "") \
        if first else card_title
    body = "\n\n".join(p for p in (spoiler, text, card_title, card_desc) if p)
    return Item(id=url, title=title or "(no text)", body=body, url=url,
                link=safe_url(card.get("url")),
                published_at=_parse_date(status.get("created_at") or ""))


class MastodonSource:
    kind = "mastodon"
    # The connection this kind reads with: provider "mastodon", keyed by instance.
    needs = "mastodon"

    def __init__(self, http: HTTP, *, instance: str, what: str = "home",
                 list_id: str | None = None, title: str | None = None) -> None:
        if what not in WHATS:
            raise ValueError(f"unknown mastodon timeline {what!r}; one of {', '.join(WHATS)}")
        if what == "list" and not re.fullmatch(r"[0-9]{1,20}", str(list_id or "")):
            raise ValueError("a mastodon list source needs the list's numeric id")
        self.http = http
        self.instance = clean_instance(instance)
        self.what, self.list_id, self.title = what, str(list_id) if list_id else None, title

    @property
    def label(self) -> str:
        if self.what == "home":
            return f"Your home timeline on {self.instance}"
        return f"Your list {self.title or self.list_id} on {self.instance}"

    def fetch(self) -> list[Item]:
        path = "timelines/home" if self.what == "home" else f"timelines/list/{self.list_id}"
        payload = self.http.get_json(f"https://{self.instance}/api/v1/{path}",
                                     params={"limit": LIMIT})
        if not isinstance(payload, list):
            message = payload.get("error") if isinstance(payload, dict) else None
            raise SourceError(f"unexpected Mastodon reply: {str(message or payload)[:200]}")
        return [item for item in map(status_item, payload) if item is not None]

    def enrich(self, item: Item) -> Item:
        return item
