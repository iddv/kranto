"""X: lists, the home timeline, an account, a search, your bookmarks and likes.

Every source reads with the person's connected X account (``needs = "x"``, the token added at
send time by the connection, never seen here). X bills each post a reply returns, so an
adapter asks for exactly what ingest will consume: ``fetch_after(newest_seen_id, limit)``
sends ``max_results`` = the limit and, where X takes it (home, an account, search), ``since_id``
= the newest post the source has consumed. A list, bookmarks and likes have no ``since_id``
(X's API reference, 2026-10-17): they return the newest ``limit`` posts, the ones already
consumed among them are dropped by ingest, and X bills a post returned twice in one UTC day
once. Searches run once a day and bookmarks and likes once a day (``cadence_hours``).

Requests ask for ``post.fields`` created_at, conversation_id, entities, public_metrics and
note_post and the ``referenced_posts`` expansion (a quoted or reposted original arrives in
``includes.posts``; each is a post read). Never ``author_id`` or ``user.fields``: authors are not
kept and a user read costs twice a post. Replies are excluded on timelines
(``exclude=replies``) and searches (``-is:reply``); a list's replies are dropped here.

An item: the post's id; its handle-less URL ``https://x.com/i/status/<id>``, so no author is
kept and every source that reaches the post names it alike; the first 140 characters as the
title; the full text (``note_post`` for a long post) with t.co links expanded, and the quoted
post's text after it; the first link off X as ``link`` (its article is fetched for a short
post); engagement counts in ``meta["x"]``, and for bookmarks and likes ``meta["x"]["mine"]``.
A repost is the original, under the original's id. Every id in a post's edit history is in
``meta["x"]["seen_ids"]``, so ingest never judges an edited post twice. An account's own
thread (``threads``, ``x.read_threads``) is one item: its root, then the account's replies in
it, "1/ ... 2/ ...", read with one recent search (an account source only: there the author
is known without asking X for it).

X answers spent credits with HTTP 402 (or a 403 that says so): a transient error with the
next try six hours out and the row "X credits exhausted". A list or account that is gone or
protected is a lasting error. Field names are read in the current form (post) and the
earlier one (tweet), which X's own pages still mix."""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from .. import pricing
from .base import HTTP, Item, SourceError, safe_url

API = "https://api.x.com/2"
WHATS = ("list", "home", "profile", "search", "bookmarks", "likes")
# what X takes per endpoint (its API reference, 2026-10-17)
MIN_RESULTS = {"list": 1, "home": 1, "profile": 5, "search": 10, "bookmarks": 1, "likes": 5}
SINCE = frozenset({"home", "profile", "search"})
OWNED = frozenset({"bookmarks", "likes"})
POST_FIELDS = "created_at,conversation_id,entities,public_metrics,note_post"
EXPANSIONS = "referenced_posts"
TITLE_CHARS = 140
MAX_QUERY_CHARS = 512
CREDITS_RETRY = timedelta(hours=6)
X_HOSTS = ("x.com", "twitter.com", "t.co")
_ID = re.compile(r"[0-9]{1,19}")


def _first(d: dict, *names):
    for n in names:
        if n in d:
            return d[n]
    return None


def post_url(post_id: str) -> str:
    return f"https://x.com/i/status/{post_id}"


def _off_x(url: str | None) -> bool:
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    return bool(host) and not any(host == h or host.endswith("." + h) for h in X_HOSTS)


def _text(post: dict) -> tuple[str, str | None]:
    """A post's full text with its t.co links expanded, and its first link off X."""
    note = _first(post, "note_post", "note_tweet")
    note = note if isinstance(note, dict) and isinstance(note.get("text"), str) else None
    text = note["text"] if note else post.get("text") if isinstance(post.get("text"), str) else ""
    entities = (note or {}).get("entities") or post.get("entities") or {}
    urls = entities.get("urls") if isinstance(entities, dict) else None
    link = None
    for u in urls if isinstance(urls, list) else []:
        if not isinstance(u, dict):
            continue
        short = u.get("url")
        full = safe_url(u.get("unwound_url")) or safe_url(u.get("expanded_url"))
        if isinstance(short, str) and short and full:
            text = text.replace(short, full)
        if link is None and full and _off_x(full):
            link = full
    return text, link


def _refs(post: dict) -> list[dict]:
    refs = _first(post, "referenced_posts", "referenced_tweets")
    return [r for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []


def _published(post: dict) -> datetime | None:
    value = post.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def post_item(post: dict, included: dict[str, dict] | None = None, *,
              mine: str | None = None) -> Item | None:
    """An item from one post (and the posts its reply included); None if it is not a post."""
    included = included or {}
    if not isinstance(post, dict) or not _ID.fullmatch(str(post.get("id") or "")):
        return None
    for ref in _refs(post):
        if ref.get("type") == "retweeted" and str(ref.get("id")) in included:
            # a repost is the original, under the original's id
            return post_item(included[str(ref["id"])], included, mine=mine)
    text, link = _text(post)
    quoted = next((included.get(str(r.get("id"))) for r in _refs(post)
                   if r.get("type") == "quoted"), None)
    body = text
    if isinstance(quoted, dict):
        qtext, qlink = _text(quoted)
        if qtext:
            body = f"{text}\n\nQuoting: {qtext}"
        link = link or qlink
    flat = " ".join(text.split())
    title = flat[:TITLE_CHARS] + (" ..." if len(flat) > TITLE_CHARS else "")
    m = post.get("public_metrics") if isinstance(post.get("public_metrics"), dict) else {}
    meta = {"likes": m.get("like_count"), "reposts": _first(m, "repost_count", "retweet_count"),
            "replies": m.get("reply_count"), "quotes": m.get("quote_count"),
            "bookmarks": m.get("bookmark_count")}
    meta = {k: v for k, v in meta.items() if isinstance(v, int)}
    history = _first(post, "edit_history_post_ids", "edit_history_tweet_ids")
    seen = [str(i) for i in history if _ID.fullmatch(str(i)) and str(i) != str(post["id"])] \
        if isinstance(history, list) else []
    if seen:
        meta["seen_ids"] = seen
    if mine:
        meta["mine"] = mine
    return Item(id=str(post["id"]), title=title or "(no text)", body=body,
                url=post_url(str(post["id"])), link=link, published_at=_published(post),
                meta={"x": meta})


def is_reply(post: dict) -> bool:
    return any(r.get("type") == "replied_to" for r in _refs(post))


# -- what a source reads, and how often -------------------------------------------------------


def limit_for(params: dict, xcfg) -> int:
    """Posts one run asks for (``config.XConfig``)."""
    what = params.get("what")
    n = xcfg.profile_per_fetch if what == "profile" else xcfg.search_results \
        if what == "search" else xcfg.posts_per_fetch
    return max(MIN_RESULTS.get(what, 1), min(100, int(n)))


def cadence_hours(params: dict, xcfg) -> float:
    """At most one fetch this often (0: every run): searches, bookmarks and likes."""
    what = params.get("what")
    if what == "search":
        return float(xcfg.search_every_hours)
    if what in OWNED:
        return float(xcfg.owned_every_hours)
    return 0.0


def run_cost(params: dict, xcfg) -> float:
    """USD one run reads at most at X's list price (quoted originals come on top)."""
    line = "owned_read" if params.get("what") in OWNED else "post_read"
    return pricing.x_cost(line, limit_for(params, xcfg))


def search_query(query: str, lang: str | None = None) -> str:
    q = " ".join(str(query or "").split())
    extra = " -is:retweet -is:reply" + (f" lang:{lang}" if lang else "")
    return q[:MAX_QUERY_CHARS - len(extra)] + extra


class XSource:
    kind = "x"
    needs = "x"

    def __init__(self, http: HTTP, *, what: str, list_id: str | None = None,
                 title: str | None = None, user_id: str | None = None,
                 handle: str | None = None, query: str | None = None,
                 lang: str | None = None) -> None:
        if what not in WHATS:
            raise ValueError(f"unknown X source {what!r}; one of {', '.join(WHATS)}")
        self.http, self.what = http, what
        self.list_id, self.title, self.user_id, self.handle = list_id, title, user_id, handle
        self.query = " ".join(str(query or "").split())[:400] or None
        self.lang = lang or None
        if what == "list" and not _ID.fullmatch(str(list_id or "")):
            raise ValueError("an X list source needs the list's number")
        if what == "profile" and not _ID.fullmatch(str(user_id or "")):
            raise ValueError("an X account source needs the account's numeric id")
        if what == "search" and not self.query:
            raise ValueError("an X search needs a query")
        if self.lang and not re.fullmatch(r"[a-z]{2,3}", self.lang):
            raise ValueError(f"not a language code such as en: {self.lang!r}")

    @property
    def label(self) -> str:
        return {"list": f"X list: {self.title or self.list_id}",
                "home": "Your X home timeline",
                "profile": f"X: @{self.handle}" if self.handle else f"X account {self.user_id}",
                "search": f"X search: {self.query}", "bookmarks": "Your X bookmarks",
                "likes": "Your X likes"}[self.what]

    def _me(self) -> str:
        me = self.http.auth_account if self.http is not None else None
        if not me:
            raise SourceError("needs login: no X account is connected", needs_login=True)
        return me

    def request(self, newest_seen_id: str | None, limit: int) -> tuple[str, dict]:
        """The URL and query of one fetch."""
        limit = max(MIN_RESULTS[self.what], min(100, int(limit)))
        params: dict = {"max_results": limit, "post.fields": POST_FIELDS,
                        "expansions": EXPANSIONS}
        if self.what == "list":
            url = f"{API}/lists/{self.list_id}/tweets"
        elif self.what == "home":
            url = f"{API}/users/{self._me()}/timelines/reverse_chronological"
            params["exclude"] = "replies"
        elif self.what == "profile":
            url = f"{API}/users/{self.user_id}/tweets"
            params["exclude"] = "replies"
        elif self.what == "search":
            url = f"{API}/tweets/search/recent"
            params.update(query=search_query(self.query, self.lang), sort_order="recency")
        else:
            url = f"{API}/users/{self._me()}/" + ("bookmarks" if self.what == "bookmarks"
                                                  else "liked_tweets")
        if self.what in SINCE and newest_seen_id and _ID.fullmatch(str(newest_seen_id)):
            params["since_id"] = str(newest_seen_id)
        return url, params

    def get(self, url: str, params: dict) -> dict:
        """One request; X's own refusals turned into what a source row can say."""
        response = self.http.get(url, params=params, errors=False)
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                raise SourceError(f"{url}: X answered with something other than JSON",
                                  transient=False) from None
            if not isinstance(body, dict):
                raise SourceError(f"{url}: unexpected X reply", transient=False)
            return body
        try:
            problem = response.json()
        except ValueError:
            problem = {}
        words = " ".join(str(problem.get(k) or "") for k in ("title", "detail")) \
            if isinstance(problem, dict) else ""
        if response.status_code == 402 or (response.status_code in (403, 429)
                                           and re.search(r"credit|balance", words, re.I)):
            raise SourceError("X credits exhausted: add credits in the Developer Console "
                              "(console.x.com); Kranto tries again in six hours",
                              retry_at=datetime.now(UTC) + CREDITS_RETRY)
        if response.status_code == 404:
            raise SourceError(f"{url}: HTTP 404: X has no such list or account, or it is "
                              "protected", transient=False)
        raise SourceError(f"{url}: HTTP {response.status_code}"
                          + (f": {words.strip()[:120]}" if words.strip() else ""),
                          transient=False)

    def thread_of(self, root: dict) -> list[dict]:
        """The account's own replies in a thread it started (an account source only: its
        author is the account, and a post's author is never asked for), oldest first. One
        recent search, 10 posts at most, billed only for what it returns."""
        query = f"conversation_id:{root['id']} from:{self.user_id} -is:retweet"
        body = self.get(f"{API}/tweets/search/recent", {
            "query": query, "max_results": MIN_RESULTS["search"], "sort_order": "recency",
            "post.fields": POST_FIELDS})
        posts = [p for p in body.get("data") or [] if isinstance(p, dict)
                 and _ID.fullmatch(str(p.get("id") or "")) and str(p["id"]) != str(root["id"])]
        return sorted(posts, key=lambda p: int(p["id"]))

    def fetch_after(self, newest_seen_id: str | None, limit: int, *,
                    threads: bool = False) -> list[Item]:
        """``threads``: an account's own threads are joined into one item ("1/ ... 2/ ...")."""
        url, params = self.request(newest_seen_id, limit)
        body = self.get(url, params)
        data = body.get("data")
        if data is None and isinstance(body.get("meta"), dict):
            return []                                  # nothing new: result_count 0
        if not isinstance(data, list):
            raise SourceError(f"{url}: unexpected X reply: {str(body)[:200]}")
        includes = body.get("includes") if isinstance(body.get("includes"), dict) else {}
        extra = _first(includes, "posts", "tweets") or []
        included = {str(p.get("id")): p for p in extra if isinstance(p, dict)}
        mine = {"bookmarks": "bookmarked", "likes": "liked"}.get(self.what)
        items = []
        for post in data:
            if self.what == "list" and isinstance(post, dict) and is_reply(post):
                continue
            item = post_item(post, included, mine=mine)
            if item is None:
                continue
            replies = ((post.get("public_metrics") or {}).get("reply_count") or 0) \
                if isinstance(post.get("public_metrics"), dict) else 0
            if threads and self.what == "profile" and replies and \
                    str(post.get("conversation_id") or "") == item.id:
                try:
                    rest = self.thread_of(post)
                except SourceError:
                    rest = []                    # the root stands alone; never lose it
                if rest:
                    parts = [item.body] + [_text(p)[0] for p in rest]
                    body = "\n\n".join(f"{n}/ {t}" for n, t in enumerate(parts, 1))
                    seen = list(item.meta["x"].get("seen_ids", [])) + [str(p["id"]) for p in rest]
                    item = dataclasses.replace(item, body=body,
                                               meta={"x": {**item.meta["x"], "seen_ids": seen,
                                                           "thread": len(parts)}})
            items.append(item)
        return items

    def fetch(self) -> list[Item]:
        """One fetch at the source's default size (a preview, Fetch now, a scout check)."""
        from ..config import XConfig

        return self.fetch_after(None, limit_for({"what": self.what}, XConfig()))

    def enrich(self, item: Item) -> Item:
        return item
