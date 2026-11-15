"""Find the feed behind a website's homepage.

The scout may propose a ``site`` (a homepage URL) instead of a feed URL when
it knows a publication but not where its feed lives. Discovery tries, in
order: the URL itself (it may already be a feed), feeds the page advertises
with ``<link rel="alternate" type="application/rss+xml|atom+xml">``, links in
the page's body to the same host whose path ends in ``.rss``, ``.atom`` or
``.xml`` (jepsen.io links its feed as ``/blog.rss`` and advertises nothing),
then the common paths ``/feed``, ``/rss.xml``, ``/atom.xml``, ``/index.xml``,
``/feed.xml``, ``/blog.rss`` and ``/rss``. A candidate counts only if it parses
as a feed with at least one item. Every request goes through the safe ``HTTP``
client, so a site URL from a model cannot reach a private address or pull more
than 5MB.

A candidate larger than 5MB is refused, not truncated, and when nothing else
works that refusal is what discovery reports ("the feed at ... is larger than
5 MB"), not "no feed found" (danluu.com's 6.6 MB atom.xml; 2.4, D9).
"""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .base import HTTP, SourceError, TooLarge, safe_url
from .rss import parse_feed

FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml"})
FALLBACK_PATHS = ("feed", "rss.xml", "atom.xml", "index.xml", "feed.xml", "blog.rss", "rss")
FEED_SUFFIXES = (".rss", ".atom", ".xml")
MAX_ADVERTISED = 5
MAX_BODY_LINKS = 5


class _FeedLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.advertised: list[str] = []
        self.anchors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("link", "a"):
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        href = a.get("href", "").strip()
        if not href:
            return
        if tag == "a":
            self.anchors.append(href)
            return
        rels = a.get("rel", "").lower().split()
        kind = a.get("type", "").lower().split(";")[0].strip()
        if "alternate" in rels and kind in FEED_TYPES:
            self.advertised.append(href)


def _links(markup: str) -> _FeedLinks:
    parser = _FeedLinks()
    parser.feed(markup)
    parser.close()
    return parser


def _absolute(hrefs: list[str], base_url: str) -> list[str]:
    out: list[str] = []
    for href in hrefs:
        url = safe_url(urljoin(base_url, href).split("#")[0])
        if url and url not in out:
            out.append(url)
    return out


def advertised_feeds(markup: str, base_url: str) -> list[str]:
    """Absolute http(s) URLs of the feeds a page links to, in page order."""
    return _absolute(_links(markup).advertised, base_url)[:MAX_ADVERTISED]


def body_feed_links(markup: str, base_url: str) -> list[str]:
    """Links in the page's body to the same host whose path ends in .rss, .atom or .xml
    (not a sitemap), in page order, at most ``MAX_BODY_LINKS``."""
    host = (urlparse(base_url).hostname or "").lower().removeprefix("www.")
    out = []
    for url in _absolute(_links(markup).anchors, base_url):
        parsed = urlparse(url)
        path = parsed.path.lower()
        if (parsed.hostname or "").lower().removeprefix("www.") != host:
            continue
        if path.endswith(FEED_SUFFIXES) and "sitemap" not in path:
            out.append(url)
    return out[:MAX_BODY_LINKS]


def fallback_candidates(url: str) -> list[str]:
    """Common feed paths, under the page's own directory first, then the site root."""
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}/"
    bases = []
    path = parsed.path or "/"
    if path not in ("", "/"):
        bases.append(urljoin(root, path if path.endswith("/") else path + "/"))
    bases.append(root)
    out: list[str] = []
    for base in bases:
        for suffix in FALLBACK_PATHS:
            candidate = urljoin(base, suffix)
            if candidate not in out:
                out.append(candidate)
    return out


def _is_feed(http: HTTP, url: str) -> bool:
    """Whether ``url`` is a feed with items. ``TooLarge`` is raised, not swallowed."""
    try:
        _, items = parse_feed(http.get(url).content)
    except TooLarge:
        raise
    except SourceError:
        return False
    return bool(items)


def discover_feed(http: HTTP, site_url: str) -> str:
    """Return the URL of a working feed for ``site_url`` or raise ``SourceError``."""
    url = safe_url(site_url)
    if url is None:
        raise SourceError(f"not an http(s) URL: {site_url}", transient=False)
    response = http.get(url)  # errors here (unreachable, private, 404) are the site's
    final_url = str(response.url)
    try:
        _, items = parse_feed(response.content)
        if items:
            return final_url
    except SourceError:
        pass
    tried = {final_url}
    markup = response.text if "html" in response.headers.get("content-type", "html") else ""
    too_large = None
    candidates = [*advertised_feeds(markup, final_url), *body_feed_links(markup, final_url),
                  *fallback_candidates(final_url)]
    for candidate in candidates:
        if candidate in tried:
            continue
        tried.add(candidate)
        try:
            if _is_feed(http, candidate):
                return candidate
        except TooLarge:
            too_large = too_large or candidate
    if too_large:
        raise SourceError(f"the feed at {too_large} is larger than 5 MB, and Kranto does not "
                          "read feeds that large", transient=False)
    raise SourceError(f"no feed found at {url}", transient=False)
