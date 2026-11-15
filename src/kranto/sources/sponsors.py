"""Sponsor and advertising context: links never followed, items never judged.

Sponsor links and ads are a hard no (operator, 2026-10-03). Whatever can be
decided without a model is decided here, before any request or call:

- **Links in sponsor context.** A link is in sponsor context when it sits in a
  block (paragraph, list item, ``div``, ...) whose own text says so ("Thank you
  to X and Y for supporting the podcast", "Sponsored by", "brought to you by",
  "promo code", "affiliate link"), in the section under a heading or label such
  as "Sponsors", or in an element whose ``class`` or ``id`` names it
  (``sponsor``, ``advert``, ``ads``, ``promo``, ``affiliate``). Detection is
  structural: the sentence or section and the links inside it, so a sponsor's
  homepage is left out on the page that thanks it, and linked normally
  elsewhere. A URL found in sponsor context anywhere on a page is left out
  everywhere on that page.
- **Ad, affiliate and ad-redirect URLs.** A short list of host patterns
  (ad networks, affiliate redirects) and of query parameters that only
  affiliate or paid links carry (``aff_id``, ``utm_medium=sponsored``, an
  Amazon ``tag``).
- **Items that announce themselves as ads.** A title marked "[Sponsor]",
  "Sponsored:", "Advertisement:" and the like, or an item that links to an ad
  or affiliate URL, is consumed as ``sponsored`` without a model call.

Everything else that is an ad (a promotional post that does not say so, a
vendor's landing page) is for the screen and the judge, whose prompts name it.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urljoin, urlparse

import lxml.html
from lxml import etree

from .base import Item, canonical_url, safe_url

# A block whose own text holds one of these is sponsor context, with every link in it.
_PHRASES = re.compile(
    r"\bsponsored\s+by\b"
    r"|\bbrought\s+to\s+you\s+by\b"
    r"|\bthanks?\s+(?:you\s+)?to\b[^.!?]{0,200}?\bfor\s+(?:supporting|sponsoring)\b"
    r"|\bthanks?\s+(?:you\s+)?to\s+(?:our|this\s+\w+'s|today's)\s+sponsors?\b"
    r"|\b(?:our|today's|this\s+(?:week|episode|issue)'s)\s+sponsors?\b"
    r"|\bthis\s+(?:episode|show|podcast|video|post|issue|newsletter|edition)\s+(?:is|was)\s+"
    r"(?:sponsored|supported|brought|made\s+possible)\b"
    r"|\bsupported\s+by\s+our\s+(?:sponsors?|partners?)\b"
    r"|\b(?:promo(?:tional)?|discount|coupon)\s+code\b"
    r"|\b(?:affiliate|referral)\s+links?\b"
    r"|\bpaid\s+partnership\b|\bpartner\s+content\b|\bsponsored\s+(?:post|content)\b"
    r"|\badvertisement\b|\badvertise\s+(?:with|here|on)\b"
    r"|\bbecome\s+a\s+sponsor\b",
    re.I,
)
# "Use code SAVE20": the code is in capitals or digits, so the match is case-sensitive.
_USE_CODE = re.compile(r"\b[Uu]se\s+(?:the\s+)?(?:promo\s+)?code\s+[A-Z0-9]{3,}\b")
# A heading or a short label that heads sponsor content: what follows it, up to
# the next heading, is sponsor context too.
_LABEL = re.compile(
    r"^\W*(?:(?:our|latest|current|episode|today's|this\s+week's|thanks\s+to\s+our)\s+)?"
    r"(?:sponsors?|sponsored(?:\s+by)?|sponsorships?|advertisements?|advertising|ads?|"
    r"promoted|partners?\s+and\s+sponsors?)\W*$",
    re.I,
)
# Blocks longer than this are an article's prose, not a sponsor line: a phrase in
# them marks nothing (an article about sponsorship keeps its links).
BLOCK_CHARS = 600
# Siblings after a sponsor heading or label that are read as its section.
SECTION_SIBLINGS = 6
_BLOCKS = frozenset({
    "p", "li", "div", "section", "aside", "dd", "dt", "td", "th", "blockquote", "figure",
    "figcaption", "header", "footer", "ul", "ol", "table", "tr", "nav", "article", "main",
    "body", "h1", "h2", "h3", "h4", "h5", "h6",
})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# class or id tokens (split on spaces, "-" and "_") that mark an ad or sponsor slot.
_AD_TOKENS = frozenset({
    "ad", "sponsor", "sponsors", "sponsored", "sponsorship", "advert", "adverts", "advertisement",
    "advertising", "ads", "adslot", "adunit", "promo", "promoted", "affiliate",
})

# Hosts (and their subdomains) that serve ads or redirect through ad or affiliate networks.
AD_HOSTS = (
    "doubleclick.net", "googleadservices.com", "googlesyndication.com", "adservice.google.com",
    "amazon-adsystem.com", "adnxs.com", "adsrvr.org", "criteo.com", "taboola.com",
    "outbrain.com", "redirectingat.com", "skimresources.com", "viglink.com",
    "linksynergy.com", "shareasale.com", "awin1.com", "anrdoezrs.net", "dpbolvw.net",
    "jdoqocy.com", "tkqlhce.com", "kqzyfj.com", "emjcd.com", "pxf.io", "sjv.io", "prf.hn",
    "avantlink.com", "rstyle.me", "shopstyle.it", "howl.me", "geni.us", "amzn.to", "amzn.eu",
)
# Query parameters that only an affiliate or paid link carries.
AFFILIATE_PARAMS = frozenset({
    "aff", "affid", "aff_id", "affiliate", "affiliate_id", "aff_sub", "irclickid", "clickref",
})
PAID_MEDIUMS = frozenset({
    "sponsor", "sponsored", "sponsorship", "affiliate", "paid", "cpc", "ppc", "ad", "ads",
    "display", "paidsocial", "paid_social", "native",
})
# A title that announces an ad: "[Sponsor] X", "Sponsored: X", "(Ad) X", "Advertisement - X".
_AD_TITLE = re.compile(
    r"^\s*(?:[\[(]\s*(?:sponsor(?:ed)?|ad|advert(?:isement)?|advertorial|promoted|paid(?:\s+post)?"
    r"|partner(?:\s+content)?)\s*[\])]"
    r"|(?:sponsor(?:ed)?|advertisement|advertorial|promoted|paid\s+(?:post|content)"
    r"|partner\s+content|sponsored\s+(?:post|content))\s*[:|–—-])",
    re.I,
)


def ad_url(url: str | None) -> str | None:
    """Why ``url`` is an ad, affiliate or ad-redirect link; None when it is not."""
    url = safe_url(url)
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    for pattern in AD_HOSTS:
        if host == pattern or host.endswith("." + pattern):
            return f"ad or affiliate host {pattern}"
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        k, v = key.lower(), value.lower()
        if k in AFFILIATE_PARAMS:
            return f"affiliate parameter {k}"
        if k == "utm_medium" and v in PAID_MEDIUMS:
            return f"paid link (utm_medium={v})"
        if k in ("utm_campaign", "utm_source") and "sponsor" in v:
            return f"sponsor link ({k})"
        if k == "tag" and re.search(r"(?:^|\.)amazon\.", host):
            return "Amazon affiliate tag"
    return None


def _own_text(el) -> str:
    return " ".join("".join(el.itertext()).split())


def _marked(el) -> str | None:
    """The class or id token that marks ``el`` as an ad or sponsor slot, if any."""
    attrs = f"{el.get('class') or ''} {el.get('id') or ''}".lower()
    return next((t for t in re.split(r"[\s\-_]+", attrs) if t in _AD_TOKENS), None)


def _block(el):
    while el is not None and (not isinstance(el.tag, str) or el.tag.lower() not in _BLOCKS):
        el = el.getparent()
    return el


def _links(el, base: str | None) -> list[str]:
    out = []
    for a in el.iter("a"):
        href = (a.get("href") or "").strip()
        url = safe_url(urljoin(base, href) if base else href)
        if url:
            out.append(url)
    return out


def _section(label) -> list:
    """The siblings after a sponsor heading or label, up to the next heading."""
    out, sib = [], label.getnext()
    while sib is not None and len(out) < SECTION_SIBLINGS:
        if isinstance(sib.tag, str) and sib.tag.lower() in _HEADINGS:
            break
        out.append(sib)
        sib = sib.getnext()
    return out


def sponsor_links(markup: str | None, base: str | None = None) -> dict[str, str]:
    """Links in sponsor or advertising context in an HTML page or fragment, as
    ``{canonical URL: reason}``. Relative links resolve against ``base``."""
    if not markup or not markup.strip():
        return {}
    try:
        root = lxml.html.fromstring(markup)
    except (etree.ParserError, ValueError):
        return {}
    found: dict[str, str] = {}

    def mark(el, reason: str) -> None:
        for url in _links(el, base):
            key = canonical_url(url)
            if key:
                found.setdefault(key, reason)

    candidates = []  # (block, its text, the match), in document order
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        token = _marked(el)
        if token:
            if len(_own_text(el)) <= BLOCK_CHARS * 2:
                mark(el, f"in an element marked {token!r}")
            continue
        if tag not in _BLOCKS:
            continue
        text = _own_text(el)
        if not text or len(text) > BLOCK_CHARS:
            continue
        if _LABEL.match(text) or (tag in _HEADINGS and _PHRASES.search(text)):
            candidates.append((el, text, None))
        else:
            match = _PHRASES.search(text) or _USE_CODE.search(text)
            if match:
                candidates.append((el, text, match.group(0)))
    # Only the innermost block that says it: a wrapper around a sponsor line and
    # the episode's own links keeps the episode's links.
    outer = set()
    for el, _, _ in candidates:
        parent = el.getparent()
        while parent is not None:
            outer.add(parent)
            parent = parent.getparent()
    for el, text, phrase in candidates:
        if el in outer:
            continue
        if phrase is not None:
            mark(el, f"next to {phrase[:80]!r}")
            continue
        reason = f"under the label {text[:40]!r}"
        mark(el, reason)
        if not _links(el, base):  # a bare label heads the section that follows it
            for sib in _section(el):
                if len(_own_text(sib)) <= BLOCK_CHARS * 2:
                    mark(sib, reason)
    return found


def sponsored_item(item: Item) -> str | None:
    """Why ``item`` is itself an ad (its title says so, or it links to an ad or
    affiliate URL); None when nothing deterministic says it is."""
    if _AD_TITLE.match(item.title or ""):
        return f"title marks an ad: {item.title[:60]!r}"
    for url in (item.link, item.url):
        reason = ad_url(url)
        if reason:
            return reason
    return None
