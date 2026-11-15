"""What a deep dive reads: the discussion, the pages linked, the repositories named.

Everything is fetched with the safe ``HTTP`` client (public addresses only,
5 MB cap, redirects re-checked, a whole-request deadline) and capped per deep
dive. Text is scrubbed when each ``Item`` is built, as for every item, before it
reaches a prompt or a table.

- **Hacker News**: the thread from the Algolia items API, the endpoint ingest
  already uses for top comments. The judge saw the first five top-level
  comments with the post; the discussion read here is up to ``max_comments``
  comments, threads ranked by how many replies they drew, each with its most
  replied-to reply. A thread no longer than what the judge already saw gives no
  discussion.
- **Reddit**: comments only when ``deep_dive.reddit_comments`` is on, from the
  post's public comment feed, paced with every other Reddit request. Off
  by default: RESPONSIBLE_USE.md says the adapter fetches no comments.
- **Links**: from the post's own text, the article it links to (main content
  only, links to the article's own site left out, since those are navigation
  and related posts), and the comments, most mentioned first.
- **Repositories**: GitHub links among those, read through GitHub's public API
  (description, numbers, README). 60 unauthenticated requests an hour per
  address, so each run looks up at most ``MAX_REPO_LOOKUPS`` repositories.
- **Never sponsors or ads**: links in sponsor or advertising context on
  any page, post or comment, and ad, affiliate or ad-redirect URLs, are left
  out before anything is fetched (``sources.sponsors``), and listed in
  ``Plan.sponsored`` with the reason.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import trafilatura

from . import fulltext, github, sponsors
from .base import HTTP, Item, SourceError, canonical_url, html_to_text, safe_url
from .hackernews import API as HN_API
from .hackernews import MAX_COMMENTS as JUDGE_SAW_COMMENTS
from .reddit import PACER as REDDIT_PACER
from .rss import parse_feed

COMMENT_CHARS = 800
DISCUSSION_CHARS = 6000
PAGE_CHARS = fulltext.MAX_FULL_TEXT_CHARS
README_CHARS = 4000
MAX_REPO_LOOKUPS = 20
# Links considered from one page or thread, before any is fetched.
MAX_LINKS_CONSIDERED = 40
# Hosts whose pages are a discussion, a copy of another page, or a feed of posts,
# never a source in their own right.
SKIP_HOSTS = frozenset({
    "news.ycombinator.com", "ycombinator.com", "reddit.com", "old.reddit.com", "redd.it",
    "x.com", "twitter.com", "archive.org", "web.archive.org", "archive.ph", "archive.is",
    "archive.today", "facebook.com", "instagram.com", "linkedin.com", "tiktok.com",
})
SKIP_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".mov", ".mp3",
                   ".zip", ".gz", ".tar", ".exe", ".dmg", ".iso", ".pdf")
_HREF = re.compile(r'href="([^"]+)"')
_MD_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
_CONTAINER = re.compile(r"<(?:article|main)\b[^>]*>(.*?)</(?:article|main)>", re.I | re.S)
_MD_NOISE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>")


@dataclass
class Plan:
    """What one deep dive can read, before any page or repository is fetched."""

    discussion: Item | None = None
    links: list[str] = field(default_factory=list)
    repos: list[tuple[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Links left out as sponsor or advertising context: URL -> reason.
    sponsored: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Parent:
    """The item gathering starts from (an observation for a deep dive, an item being
    judged at ingest), with what it pointed at."""

    prefix: str  # what the ids of things reached from it start with (``child_id``)
    source_kind: str
    source_params: dict
    item_id: str | None
    title: str
    source_url: str | None
    canonical: str | None  # the item's canonical URL, from items_seen


def child_id(prefix: str, key: str) -> str:
    """The ``items_seen`` id of something reached from the parent with ``prefix``
    (``deepdive:<observation id>``, ``look:<item id>``).

    Deterministic, so an interrupted deep dive resumes without judging twice."""
    if key == "discussion":
        return f"{prefix}:discussion"
    return f"{prefix}:{hashlib.sha1(key.encode()).hexdigest()[:16]}"


def host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def hrefs(markup: str | None) -> list[str]:
    """Absolute http(s) links in an HTML fragment, in order."""
    return [u for u in (safe_url(html.unescape(m)) for m in _HREF.findall(markup or "")) if u]


def _hrefs_outside_sponsors(markup: str | None, out: Plan) -> list[str]:
    """``hrefs`` without the links in sponsor or advertising context, which
    are recorded in ``out.sponsored``."""
    found = sponsors.sponsor_links(markup)
    kept = []
    for u in hrefs(markup):
        reason = found.get(canonical_url(u) or "")
        if reason:
            out.sponsored.setdefault(u, reason)
        else:
            kept.append(u)
    return kept


def plan(http: HTTP, parent: Parent, *, max_comments: int, reddit_comments: bool) -> Plan:
    """Read the parent's thread and article and list what could be judged.

    Raises ``SourceError`` when the thread itself cannot be read and the error
    may clear (the caller retries later); anything else unreadable is left out."""
    out = Plan()
    post_links: list[str] = []
    comment_links: list[str] = []
    article = None
    if parent.source_kind == "hackernews" and parent.item_id:
        thread = _hn_thread(http, parent.item_id, out)
        if thread is not None:
            post_links += _hrefs_outside_sponsors(_text(thread.get("text")), out)
            article = safe_url(_text(thread.get("url")))
            comments = _hn_comments(thread)
            for c in comments:
                comment_links += _hrefs_outside_sponsors(c[1], out)
            if len(comments) > JUDGE_SAW_COMMENTS and max_comments > JUDGE_SAW_COMMENTS:
                out.discussion = _discussion_item(
                    parent, thread_url=f"https://news.ycombinator.com/item?id={parent.item_id}",
                    comments=_ranked(thread, max_comments))
    elif parent.source_kind == "reddit":
        if parent.canonical and host(parent.canonical) not in SKIP_HOSTS:
            article = parent.canonical
        if reddit_comments and parent.item_id and parent.source_params.get("subreddit"):
            texts, links = _reddit_comments(http, parent, max_comments, out)
            comment_links += links
            if texts:
                out.discussion = _discussion_item(
                    parent, thread_url=parent.source_url, comments=[(0, t) for t in texts])
    else:
        article = safe_url(parent.source_url)

    if article:
        page = fetch_page(http, article)
        if page is None:
            out.notes.append("article not readable")
        elif page.text and fulltext.no_content(page.text):
            # A consent wall's links are its owner's policies, not the article's.
            out.notes.append(f"article is {fulltext.no_content(page.text)}")
        else:
            own = host(page.url)
            post_links += [u for u in page.links if host(u) != own]
            for u, reason in page.sponsored.items():
                if host(u) != own:
                    out.sponsored.setdefault(u, reason)

    excluded = {canonical_url(u) for u in (article, parent.source_url, parent.canonical) if u}
    counts = Counter(canonical_url(u) for u in comment_links)
    ordered: dict[str, str] = {}
    # The post's own links first, in order; then the comments', most mentioned first.
    for u in post_links[:MAX_LINKS_CONSIDERED]:
        ordered.setdefault(canonical_url(u), u)
    first_seen = {}
    for i, u in enumerate(comment_links):
        first_seen.setdefault(canonical_url(u), (i, u))
    for key, (_, u) in sorted(first_seen.items(), key=lambda kv: (-counts[kv[0]], kv[1][0])):
        ordered.setdefault(key, u)
    # A URL in sponsor context anywhere is left out everywhere.
    left_out = {canonical_url(u) for u in out.sponsored}
    for key in left_out:
        ordered.pop(key, None)
    for key, url in list(ordered.items())[:MAX_LINKS_CONSIDERED]:
        if key is None or key in excluded or host(url) in SKIP_HOSTS \
                or urlparse(url).path.lower().endswith(SKIP_EXTENSIONS):
            continue
        reason = sponsors.ad_url(url)
        if reason:
            out.sponsored.setdefault(url, reason)
            continue
        repo = github.repository(url)
        if repo is not None:
            pair = (repo[0], repo[1])
            if pair not in out.repos and repo != github.repository(article or ""):
                out.repos.append(pair)
        elif host(url) != "github.com":
            out.links.append(url)
    if out.sponsored:
        hosts = sorted({host(u) for u in out.sponsored})
        out.notes.append(f"left out {len(out.sponsored)} link(s) in sponsor or advertising "
                         f"context: {', '.join(hosts)[:200]}")
    return out


# -- Hacker News ---------------------------------------------------------------------


def _hn_thread(http: HTTP, item_id: str, out: Plan) -> dict | None:
    try:
        thread = http.get_json(f"{HN_API}/items/{item_id}")
    except SourceError as exc:
        if exc.transient:
            raise
        out.notes.append(f"thread not readable: {exc}")
        return None
    if not isinstance(thread, dict):
        raise SourceError(f"unexpected Algolia thread for item {item_id}")
    return thread


def _children(node: dict) -> list[dict]:
    kids = node.get("children")
    return [k for k in kids if isinstance(k, dict)] if isinstance(kids, list) else []


def _hn_comments(thread: dict) -> list[tuple[int, str]]:
    """Every comment with text in the thread, as (depth, HTML)."""
    out, stack = [], [(c, 0) for c in reversed(_children(thread))]
    while stack:
        node, depth = stack.pop()
        text = _text(node.get("text"))
        if text:
            out.append((depth, text))
        stack += [(c, depth + 1) for c in reversed(_children(node))]
    return out


def _sizes(thread: dict) -> dict[int, int]:
    """Replies under each node (itself included), keyed by ``id()`` of the node."""
    sizes: dict[int, int] = {}
    order, stack = [], [thread]
    while stack:
        node = stack.pop()
        order.append(node)
        stack += _children(node)
    for node in reversed(order):
        sizes[id(node)] = 1 + sum(sizes[id(c)] for c in _children(node))
    return sizes


def _ranked(thread: dict, limit: int) -> list[tuple[int, str]]:
    """Top-level comments that drew the most replies, each followed by its most
    replied-to reply, as (depth, plain text), at most ``limit``."""
    sizes = _sizes(thread)
    out: list[tuple[int, str]] = []
    tops = sorted(_children(thread), key=lambda n: -sizes[id(n)])
    for top in tops:
        if len(out) >= limit:
            break
        text = html_to_text(_text(top.get("text")))
        if not text:
            continue
        out.append((0, text[:COMMENT_CHARS]))
        replies = [r for r in _children(top) if _text(r.get("text"))]
        if replies and len(out) < limit:
            best = max(replies, key=lambda n: sizes[id(n)])
            reply = html_to_text(_text(best.get("text")))
            if reply:
                out.append((1, reply[:COMMENT_CHARS]))
    return out


def _discussion_item(parent: Parent, *, thread_url: str | None,
                     comments: list[tuple[int, str]]) -> Item | None:
    parts, size = [], 0
    for depth, text in comments:
        block = ("Reply: " if depth else "Comment: ") + " ".join(text.split())
        if size + len(block) > DISCUSSION_CHARS:
            break
        parts.append(block)
        size += len(block) + 2
    if not parts:
        return None
    return Item(
        id=child_id(parent.prefix, "discussion"),
        title=f"Discussion: {parent.title}"[:500],
        body="\n\n".join(parts),
        url=safe_url(thread_url),
        reached_from=f"the discussion under the item titled: {parent.title}",
    )


# -- Reddit ----------------------------------------------------------------------------


def _reddit_comments(http: HTTP, parent: Parent, limit: int,
                     out: Plan) -> tuple[list[str], list[str]]:
    """Comment texts and the links in them, from the post's public comment feed."""
    post = (parent.item_id or "").removeprefix("t3_")
    sub = str(parent.source_params["subreddit"])
    if not re.fullmatch(r"[A-Za-z0-9_]+", post) or not re.fullmatch(r"[A-Za-z0-9_]+", sub):
        return [], []
    REDDIT_PACER.wait()
    try:
        response = http.get(f"https://www.reddit.com/r/{sub}/comments/{post}/.rss",
                            params={"sort": "top", "limit": str(limit)})
        _, entries = parse_feed(response.content)
    except SourceError as exc:
        if exc.transient:
            raise
        out.notes.append(f"comments not readable: {exc}")
        return [], []
    texts, links = [], []
    for entry in entries:
        if entry.id.removeprefix("t3_") == post:  # the post itself heads the feed
            continue
        text = re.sub(r"\s*submitted by\s+\S+.*$", "", entry.body, flags=re.I | re.S).strip()
        if text and text.lower() not in ("[removed]", "[deleted]"):
            texts.append(text[:COMMENT_CHARS])
        links += [u for u in re.findall(r"https?://[^\s)\]>\"']+", entry.body)]
        if len(texts) >= limit:
            break
    return texts, links


# -- pages and repositories -------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    url: str
    title: str | None
    text: str | None
    links: list[str]
    # Links on the page in sponsor or advertising context, left out of ``links``.
    sponsored: dict[str, str] = field(default_factory=dict)


def fetch_page(http: HTTP, url: str) -> Page | None:
    """A page's title, main text and the links in its main content; None if unreadable."""
    try:
        response = http.get(url)
    except SourceError:
        return None
    content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
    if content_type and content_type.lower() not in fulltext._TEXT_TYPES:
        return None
    final = str(response.url)
    try:
        markup = response.text
        text = fulltext.extract_main_text(markup, url=final)
        linked = trafilatura.extract(
            markup, url=final, output_format="markdown", include_links=True,
            include_comments=False, include_tables=False) or ""
        meta = trafilatura.extract_metadata(markup)
    except Exception:  # trafilatura/lxml raise many types on hostile markup
        return None
    # trafilatura drops link-dense paragraphs ("Sources: [1] [2]") as boilerplate;
    # the links inside the page's <article> or <main> are added after its own.
    found = _MD_LINK.findall(linked)
    container = _CONTAINER.search(markup)
    if container:
        found += [urljoin(final, html.unescape(m)) for m in _HREF.findall(container.group(1))]
    context = sponsors.sponsor_links(markup, final)
    links, left_out = [], {}
    for u in dict.fromkeys(u for u in (safe_url(m) for m in found) if u):
        reason = context.get(canonical_url(u) or "")
        if reason:
            left_out[u] = reason
        else:
            links.append(u)
    title = " ".join((meta.title or "").split()) if meta is not None else ""
    return Page(final, title or None, text[:PAGE_CHARS] if text else None, links, left_out)


def link_item(prefix: str, url: str, page: Page, reached_from: str) -> Item | None:
    """The page as an item to judge, or None if its text is not plausibly an article."""
    if not fulltext.usable(page.text, "") or fulltext.no_content(page.text):
        return None
    return Item(
        id=child_id(prefix, canonical_url(url) or url),
        title=(page.title or url)[:500],
        body=page.text or "",
        url=safe_url(page.url) or url,
        reached_from=reached_from,
    )


class RepoReader:
    """Reads repositories for one deep-dive run: description, numbers and README; capped."""

    def __init__(self, http: HTTP, max_lookups: int = MAX_REPO_LOOKUPS) -> None:
        self.http = http
        self.max_lookups = max_lookups
        self.lookups = 0

    def item(self, prefix: str, owner: str, repo: str, reached_from: str,
             http=None) -> Item | None:
        """``http`` overrides the reader's client for this lookup (an item's ``TimeBox``)."""
        if self.lookups >= self.max_lookups:
            return None
        self.lookups += 1
        http = http or self.http
        try:
            data = http.get_json(f"{github.API}/{owner}/{repo}")
        except SourceError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("stargazers_count"), int):
            return None
        readme = ""
        try:
            payload = http.get_json(f"{github.API}/{owner}/{repo}/readme")
            if isinstance(payload, dict) and payload.get("encoding") == "base64":
                readme = base64.b64decode(str(payload.get("content") or "")).decode(
                    "utf-8", errors="replace")
        except (SourceError, binascii.Error, ValueError):
            readme = ""
        readme = re.sub(r"\n{3,}", "\n\n", _MD_NOISE.sub("", readme)).strip()[:README_CHARS]
        description = " ".join(str(data.get("description") or "").split())
        if not readme and not description:
            return None
        name = str(data.get("full_name") or f"{owner}/{repo}")
        url = safe_url(str(data.get("html_url") or "")) or f"https://github.com/{owner}/{repo}"
        stats = {
            "stars": data["stargazers_count"],
            "forks": data.get("forks_count"),
            "language": data.get("language"),
            "last_push": (data.get("pushed_at") or "")[:10] or None,
            "archived": bool(data.get("archived")),
        }
        return Item(
            id=child_id(prefix, canonical_url(url) or url),
            title=f"{name}: {description}"[:500] if description else name,
            body="\n\n".join(p for p in (description, readme) if p),
            url=url,
            meta={"github": stats},
            reached_from=reached_from,
        )


def _text(value) -> str:
    return value if isinstance(value, str) else ""


# -- gathering for one item at ingest ----------------------------------------------

# Pages fetched per link that may be kept: some are sign-in walls or not articles.
FETCHES_PER_LINK = 2


class TimeBox:
    """The HTTP client for one item's gathering, held to a time budget.

    Every request shares ``seconds`` of wall-clock time and each is cut off at
    ``request_seconds``; once the budget is spent, further requests fail at once
    and what was gathered so far is used. The same URL is fetched once (a link
    post's article is read for its text and again for its links)."""

    def __init__(self, http: HTTP, *, seconds: float, request_seconds: float,
                 clock=time.monotonic) -> None:
        self.http = http
        self.clock = clock
        self.until = clock() + seconds
        self.request_seconds = request_seconds
        self.requests = 0
        self._cache: dict[tuple, object] = {}

    def get(self, url: str, *, params: dict | None = None):
        key = (url, tuple(sorted((params or {}).items())))
        if key in self._cache:
            return self._cache[key]
        left = self.until - self.clock()
        if left <= 0:
            raise SourceError(f"{url}: the time for gathering is spent", transient=False)
        self.requests += 1
        response = self.http.get(url, params=params, deadline=min(left, self.request_seconds))
        self._cache[key] = response
        return response

    def get_json(self, url: str, *, params: dict | None = None):
        response = self.get(url, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"{url}: response is not JSON", transient=False) from exc


@dataclass(frozen=True)
class Gathered:
    relation: str  # "discussion" | "link" | "repository", as in observation_links
    item: Item


def collect(http, parent: Parent, *, max_links: int, max_repos: int, max_comments: int,
            reddit_comments: bool, repos: RepoReader,
            skip=lambda canonical: False
            ) -> tuple[list[Gathered], list[str], dict[str, str]]:
    """What is one step from ``parent``: its discussion, up to ``max_links`` linked
    pages that read as articles, and up to ``max_repos`` repositories, with notes on
    what could not be read and the links left out as sponsor or advertising context
    (URL -> reason). ``skip(canonical_url)`` leaves out what the library has
    already judged. Never raises for an unreadable source: gathering is context,
    and an item is judged without it rather than lost."""
    try:
        found = plan(http, parent, max_comments=max_comments, reddit_comments=reddit_comments)
    except SourceError as exc:
        return [], [f"thread not readable: {exc}"], {}
    out: list[Gathered] = []
    if found.discussion is not None:
        out.append(Gathered("discussion", found.discussion))
    context = f"a page linked from the item titled: {parent.title}"
    tried = kept = 0
    for url in found.links:
        if kept >= max_links or tried >= max_links * FETCHES_PER_LINK:
            break
        if skip(canonical_url(url)):
            continue
        tried += 1
        page = fetch_page(http, url)
        item = link_item(parent.prefix, url, page, context) if page else None
        if item is not None:
            kept += 1
            out.append(Gathered("link", item))
    for owner, repo in found.repos[:max_repos]:
        if skip(canonical_url(f"https://github.com/{owner}/{repo}")):
            continue
        item = repos.item(parent.prefix, owner, repo,
                          f"a repository named in the item titled: {parent.title}", http=http)
        if item is not None:
            out.append(Gathered("repository", item))
    return out, found.notes, found.sponsored
