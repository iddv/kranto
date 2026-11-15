"""New videos from the channels a YouTube account subscribes to (connected account).

Read with the YouTube Data API through a connection made with the owner's own
Google Cloud project (``connections.youtube``). A fetch lists the account's
subscriptions (``subscriptions.list``, 50 a page, at most ``MAX_CHANNELS``) and
reads each channel's latest uploads from its uploads playlist
(``playlistItems.list``). Each call costs one quota unit, so a fetch costs
about ``MAX_CHANNELS + 2`` of the 10,000 units a day. Channel names are not
kept (they name the author): an item is the video's title, description and URL.

YouTube's developer policies allow API data to be kept at most 30 days; the
retention settings cap the ``youtube`` kind at 30 (``config.KIND_MAX_DAYS``).
"""

from __future__ import annotations

import re

from .base import HTTP, Item, SourceError
from .rss import _parse_date

API = "https://www.googleapis.com/youtube/v3"
MAX_CHANNELS = 100
VIDEOS_PER_CHANNEL = 5
DESCRIPTION_CHARS = 2000
WHATS = ("subscriptions",)
_CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}")
_VIDEO = re.compile(r"[A-Za-z0-9_-]{11}")


class YouTubeSource:
    kind = "youtube"
    needs = "youtube"

    def __init__(self, http: HTTP, *, what: str = "subscriptions") -> None:
        if what not in WHATS:
            raise ValueError(f"unknown youtube source {what!r}; one of {', '.join(WHATS)}")
        self.http, self.what = http, what

    @property
    def label(self) -> str:
        return "Your YouTube subscriptions"

    def channels(self) -> list[str]:
        out: list[str] = []
        page = None
        while len(out) < MAX_CHANNELS:
            params = {"part": "snippet", "mine": "true", "maxResults": 50}
            if page:
                params["pageToken"] = page
            data = self.http.get_json(f"{API}/subscriptions", params=params)
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise SourceError("unexpected YouTube reply for subscriptions")
            for sub in data["items"]:
                cid = (((sub or {}).get("snippet") or {}).get("resourceId") or {}) \
                    .get("channelId") if isinstance(sub, dict) else None
                if isinstance(cid, str) and _CHANNEL.fullmatch(cid):
                    out.append(cid)
            page = data.get("nextPageToken")
            if not page:
                break
        return out[:MAX_CHANNELS]

    def fetch(self) -> list[Item]:
        items, failed, last = [], 0, None
        channels = self.channels()
        for cid in channels:
            try:
                data = self.http.get_json(f"{API}/playlistItems", params={
                    "part": "snippet,contentDetails", "playlistId": "UU" + cid[2:],
                    "maxResults": VIDEOS_PER_CHANNEL})
            except SourceError as exc:
                if exc.needs_login:
                    raise
                failed, last = failed + 1, exc
                continue
            for entry in (data.get("items") or []) if isinstance(data, dict) else []:
                item = video_item(entry)
                if item is not None:
                    items.append(item)
        if channels and failed == len(channels) and last is not None:
            raise last
        return items

    def enrich(self, item: Item) -> Item:
        return item


def video_item(entry: dict) -> Item | None:
    if not isinstance(entry, dict):
        return None
    details = entry.get("contentDetails") or {}
    snippet = entry.get("snippet") or {}
    vid = details.get("videoId") if isinstance(details, dict) else None
    if not isinstance(vid, str) or not _VIDEO.fullmatch(vid) or not isinstance(snippet, dict):
        return None
    title = snippet.get("title") if isinstance(snippet.get("title"), str) else ""
    if title in ("Private video", "Deleted video"):
        return None
    description = snippet.get("description") \
        if isinstance(snippet.get("description"), str) else ""
    url = f"https://www.youtube.com/watch?v={vid}"
    return Item(id=url, title=title or "(untitled video)", body=description[:DESCRIPTION_CHARS],
                url=url, published_at=_parse_date(details.get("videoPublishedAt")
                                                  or snippet.get("publishedAt") or ""))
