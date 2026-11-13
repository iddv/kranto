"""Fetch the article behind a thin feed item.

HN link posts carry a title and a URL; many RSS feeds carry a one-line
teaser. The judge cannot rate what it cannot read, so an item whose body is
shorter than ``SHORT_BODY_CHARS``, or is a teaser cut off with an ellipsis, has
its link fetched and the main text extracted with trafilatura.

Extracted text replaces the body only when it is plausibly the article: long
enough, and not a sign-in banner, a bot check or an error page. Otherwise the
item keeps its own text (#48: GitHub's "You signed in with another tab"
banner replaced real release notes, and Nature's "a required part of this
site couldn't load" replaced the HN post that linked to a paper).

The page is fetched with the safe ``HTTP`` client (public addresses only, 5MB
cap, redirects re-checked); trafilatura
only parses what that client returned and never fetches anything itself.

Any failure returns ``None`` and the caller keeps the original item: a thin
item judged is better than an item lost.
"""

from __future__ import annotations

import dataclasses
import logging
import re

import trafilatura

from .base import HTTP, Item, SourceError, safe_url

SHORT_BODY_CHARS = 300
# A body this short that ends in an ellipsis is a teaser, not the article: Canary
# Media's run 305-330 characters, and 0 of 90 were kept until the judge saw more.
TEASER_MAX_CHARS = 2000
TEASER_ENDINGS = ("\u2026", "...", "[\u2026]", "[...]")
MAX_FULL_TEXT_CHARS = 4000
MIN_FULL_TEXT_CHARS = 400
# Text of pages that stand in front of an article, checked near the start of the
# extracted text.
NOT_THE_ARTICLE = (
    "you signed in with another tab or window",
    "a required part of this site couldn",
    "enable javascript and cookies to continue",
    "please enable javascript",
    "verifying you are human",
    "checking if the site connection is secure",
    "access denied",
    "are you a robot",
    # Cookie-consent walls (#47: a Chrome Web Store link gave Google's).
    "before you continue to google",
    "before you continue to youtube",
    "we use cookies and data to",
)
# Lines of page chrome that say nothing about the page: GitHub's
# session banners, skip links, dismiss buttons.
_CHROME = re.compile(
    r"you signed (?:in|out) (?:with|in) another tab or window\.?|"
    r"you switched accounts on another tab or window\.?|"
    r"reload to refresh your session\.?|dismiss alert|skip to (?:main )?content|"
    r"navigation menu|toggle navigation|sign in|sign up",
    re.I)
CONSENT_WALLS = ("before you continue to google", "before you continue to youtube",
                 "we use cookies and data to")
# Text left after chrome is removed that is too short to be content.
MIN_CONTENT_CHARS = 40
# A body this short that opens with a NOT_THE_ARTICLE marker is that wall. Longer
# text that mentions "access denied" may well be about it, and is left alone.
WALL_MAX_CHARS = 400
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

# trafilatura logs every page it cannot parse at WARNING; those are expected here.
logging.getLogger("trafilatura").setLevel(logging.ERROR)


def full_text_target(kind: str, item: Item) -> str | None:
    """The URL to fetch for ``item``, or None when it should be judged as it is."""
    body = (item.body or "").rstrip()
    teaser = len(body) < TEASER_MAX_CHARS and body.endswith(TEASER_ENDINGS)
    if len(body) >= SHORT_BODY_CHARS and not teaser:
        return None
    if kind in ("hackernews", "x"):
        # only link posts (an HN story with a URL, an X post that links off x.com); the
        # post's own page is not the article
        return safe_url(item.link)
    if kind == "rss":
        return safe_url(item.url or item.link)
    return None


def extract_main_text(markup: str, url: str | None = None) -> str | None:
    text = trafilatura.extract(
        markup, url=url, include_comments=False, include_tables=False, favor_precision=True,
    )
    text = (text or "").strip()
    return text or None


def fetch_full_text(http: HTTP, url: str) -> str | None:
    """Main text of the page at ``url``, truncated, or None if it cannot be had."""
    try:
        response = http.get(url)
    except SourceError:
        return None
    content_type = response.headers.get("content-type", "text/html").split(";")[0].strip()
    if content_type and content_type.lower() not in _TEXT_TYPES:
        return None
    try:
        text = extract_main_text(response.text, url=str(response.url))
    except Exception:  # trafilatura/lxml raise many types on hostile markup
        return None
    return text[:MAX_FULL_TEXT_CHARS] if text else None


def with_full_text(http: HTTP, kind: str, item: Item) -> tuple[Item, bool]:
    """Return the item with its body replaced by the linked page's text when that helps.

    The second value says whether the body was replaced. Full text is an
    enrichment: any failure to get it leaves the item as it was.
    """
    target = full_text_target(kind, item)
    if target is None:
        return item, False
    try:
        text = fetch_full_text(http, target)
    except Exception:  # a hostile linked page must never stop ingest
        return item, False
    if not usable(text, item.body or ""):
        return item, False
    return dataclasses.replace(item, body=text), True


def usable(text: str | None, original: str) -> bool:
    """Whether extracted text is plausibly the article and says more than the item."""
    if not text or len(text) < MIN_FULL_TEXT_CHARS or len(text) <= len(original):
        return False
    head = " ".join(text[:1500].split()).lower()
    return not any(marker in head for marker in NOT_THE_ARTICLE)


def no_content(text: str | None) -> str | None:
    """Why ``text`` is not content, or None if it may be.

    Feeds and fetched pages sometimes hand over what stands in front of the
    content: GitHub's session banners for a release, Google's cookie-consent
    page for a Chrome Web Store link. Judged as the item, they read as an
    item about cookies or about nothing. A body this returns a reason for is
    blanked before any model sees it, and the reason is shown instead."""
    flat = " ".join((text or "").split())
    if not flat:
        return "empty"
    rest = " ".join(_CHROME.sub(" ", flat).split())
    if rest != flat and len(rest) < MIN_CONTENT_CHARS:
        return "page chrome only (sign-in banners, navigation)"
    head = flat[:200].lower()
    if any(m in head for m in CONSENT_WALLS):
        return "a cookie-consent page"
    if len(flat) < WALL_MAX_CHARS and any(m in head for m in NOT_THE_ARTICLE):
        return "a sign-in, bot-check or error page"
    return None


def blank_no_content(item: Item) -> Item:
    """``item`` with a body that is no content (``no_content``) blanked and the
    reason in ``capture_note``; otherwise ``item`` itself. An empty body is left
    as it is: a link post's title is its whole text."""
    if not (item.body or "").strip():
        return item
    reason = no_content(item.body)
    if reason is None:
        return item
    return dataclasses.replace(item, body="", capture_note=reason)
