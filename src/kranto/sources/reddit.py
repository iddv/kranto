"""Reddit subreddits via their public Atom feed.

Reddit's JSON listing refuses unauthenticated clients; the Atom feed at
``/r/<sub>/new/.rss`` still serves them but rate-limits hard. One request per
subreddit per run, no comment enrichment, and a 429 surfaces as a transient
source error rather than an empty feed.

Requests to Reddit are paced: at least ``REQUEST_INTERVAL_SECONDS`` apart across
every subreddit in the process. Measured on 2026-09-26, 17 subreddits in
one run: unpaced, 15 returned 429; 30 s apart, 6 did (after five successes,
every other request); the sustained allowance is about one a minute. A run with
many subreddits takes longer instead.

A link post's entry holds the external URL only in its "[link]" anchor, which
plain-text extraction drops. It is read from the entry's markup and becomes the
item's ``link``, so the same article reaching the library through Reddit and
through HN or its site's feed is recognised as one. Self posts and
galleries link to the post itself and keep no ``link``; a crosspost links to
the original thread, so crossposts are recognised too.

Reddit's Responsible Builder Policy governs any tool that reads Reddit:
https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy
API access through OAuth needs Reddit's prior approval of an app. Kranto seeks none
of its own: with **your own** app, approved by Reddit in your name and
connected under Settings › Accounts › Reddit (the owner's D-R1),
this adapter reads through Reddit's API as you; without one, only the public feed,
until Reddit stops it. The example packs ship without Reddit sources; see
RESPONSIBLE_USE.md at the repository root.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from .base import HTTP, Item, Pacer, SourceError, safe_url
from .rss import ATOM, SafeET, parse_feed

REQUEST_INTERVAL_SECONDS = 60.0
API_HOST = "oauth.reddit.com"           # with your own app (connections.reddit)
# On 30 Sept 2026 Reddit announced that its RSS and Atom feeds stop on this date
# (section 0); this adapter stops working with them.
FEEDS_END = "13 Nov 2026"
FEEDS_END_NOTE = f"Reddit's feeds stop on {FEEDS_END}."

_Pacer = Pacer  # the name the tests and older callers use
PACER = Pacer(REQUEST_INTERVAL_SECONDS)
_LINK = re.compile(r'<a href="([^"]+)">\[link\]</a>')
# The author's name is already replaced by the scrubber when the Item is built.
_BOILERPLATE = re.compile(r"\s*submitted by\s+(?:/u/\S+|\[user\]).*$",
                          re.IGNORECASE | re.DOTALL)
_NAME = re.compile(r"^[A-Za-z0-9_]{2,21}$")


class RedditSource:
    """With your own Reddit app connected (``connections.reddit``,), the
    subreddit's new posts through Reddit's API as you (100 a read, one request a second), each
    with its score and comment count, and the top comments of its ``comments`` highest-scored
    posts in the post's text; a post Reddit removed is left out. Without it, the public feed,
    until Reddit stops it."""

    kind = "reddit"
    uses = "reddit"                    # read with your app when it is connected

    def __init__(self, http: HTTP, *, subreddit: str, comments: int = 5) -> None:
        subreddit = subreddit.removeprefix("r/").removeprefix("/r/").strip("/")
        if not _NAME.match(subreddit):
            raise ValueError(f"not a subreddit name: {subreddit!r}")
        self.http = http
        self.subreddit = subreddit
        self.comments = max(0, min(int(comments), 10))

    @property
    def label(self) -> str:
        return f"r/{self.subreddit}"

    def fetch(self) -> list[Item]:
        if self.http.auth_host == API_HOST:
            return self._api()
        PACER.wait()
        response = self.http.get(f"https://www.reddit.com/r/{self.subreddit}/new/.rss")
        _, entries = parse_feed(response.content)
        links = _external_links(response.content)
        items = []
        for entry in entries:
            body = _BOILERPLATE.sub("", entry.body).strip()
            items.append(
                Item(
                    id=entry.id,
                    title=entry.title,
                    body=body,
                    url=entry.url,
                    link=links.get(entry.id),
                    published_at=entry.published_at,
                )
            )
        return items

    def _api(self) -> list[Item]:
        data = self.http.get_json(f"https://{API_HOST}/r/{self.subreddit}/new",
                                  params={"limit": 100, "raw_json": 1})
        posts: list[dict] = [c["data"] for c in ((data or {}).get("data") or {}).get("children")
                             or [] if isinstance(c, dict) and isinstance(c.get("data"), dict)]
        posts = [p for p in posts if not _removed(p)]
        top = {p.get("id") for p in sorted(posts, key=lambda p: -(p.get("score") or 0))
               [:self.comments]}
        items = []
        for p in posts:
            pid = str(p.get("id") or "")
            if not pid:
                continue
            body = str(p.get("selftext") or "").strip()
            counts = f"Score {int(p.get('score') or 0)}, {int(p.get('num_comments') or 0)} " \
                     "comments on Reddit."
            said = self._top_comments(pid) if pid in top else []
            text = "\n\n".join(x for x in (body, counts, ("Top comments: " + " | ".join(said))
                                           if said else "") if x)
            url = safe_url("https://www.reddit.com" + str(p.get("permalink") or ""))
            link = None if p.get("is_self") else safe_url(str(p.get("url") or ""))
            when = p.get("created_utc")
            items.append(Item(id=f"t3_{pid}", title=str(p.get("title") or "")[:300],
                              body=text, url=url, link=link,
                              published_at=(datetime.fromtimestamp(float(when), UTC)
                                            if isinstance(when, int | float) else None)))
        return items

    def _top_comments(self, pid: str) -> list[str]:
        try:
            got = self.http.get_json(f"https://{API_HOST}/r/{self.subreddit}/comments/{pid}",
                                     params={"limit": 5, "depth": 1, "sort": "top",
                                             "raw_json": 1})
        except SourceError:
            return []                    # a post's comments are extra: the post stands
        listing = got[1] if isinstance(got, list) and len(got) > 1 else {}
        out = []
        for c in ((listing or {}).get("data") or {}).get("children") or []:
            d = c.get("data") if isinstance(c, dict) else None
            if not isinstance(d, dict) or _removed(d):
                continue
            text = " ".join(str(d.get("body") or "").split())[:400]
            if text:
                out.append(f"{text} (score {int(d.get('score') or 0)})")
        return out[:5]

    def enrich(self, item: Item) -> Item:
        return item


def _removed(d: dict) -> bool:
    """A post or comment Reddit removed or its author deleted: never kept (the terms, 2.5)."""
    return any(str(d.get(k) or "") in ("[removed]", "[deleted]")
               for k in ("selftext", "body", "author")) or bool(d.get("removed_by_category"))


def _external_links(content: bytes) -> dict[str, str]:
    """Entry id to the URL its "[link]" anchor points at, when that is not the post."""
    try:
        root = SafeET.fromstring(content)
    except Exception:  # parse_feed has already accepted this feed; be lenient here
        return {}
    out = {}
    for entry in root.findall(f"{ATOM}entry"):
        entry_id = (entry.findtext(f"{ATOM}id") or "").strip()
        match = _LINK.search(entry.findtext(f"{ATOM}content") or "")
        target = safe_url(match.group(1)) if match else None
        post = entry_id.removeprefix("t3_")
        if target and post and f"/{post}" not in target:
            out[entry_id] = target
    return out
