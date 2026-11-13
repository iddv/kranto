"""The sites Kranto writes short posts for: one entry each, data rather than code.

A post reaches a site in one of two ways, and never in a third:

- **Open** (``open``): the site's own composer opens in the person's browser with the draft
  filled in, and they press Post there. Kranto sends nothing. Offered first wherever a site has
  one, even where Kranto could post directly.
- **Post directly** (``direct``): Kranto posts the draft through the site's API, after the
  person's yes in the confirm dialog, with their own connection. Switched on per site in
  Settings › Posting; off until they do.

A site with neither is not offered (``not_offered`` says why, in the person's words). There is
no "copy and open": Copy is a plain button on every draft and is not a way of posting.

Each entry carries the site's limit and how it counts (``count``), what Kranto may attach
(``links``, ``hashtags``, whether a thread is possible when posting directly), and a short
playbook that goes into the writer's prompt after the person's own template (the prose
engine's ``sites/<id>`` guide). The model is told what the site can carry; the code below
decides what is actually kept (``fit``).

``SOURCES`` names the page each site's Open and limit were read from, and the day.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

URL = re.compile(r"https?://[^\s<>\"')\]]+")
LINK_WEIGHT = 23                 # what a link counts on X and Mastodon, whatever its length


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    limit: int                     # the most one post holds, in ``unit``
    unit: str                      # the words the counter says: "characters", …
    counting: str                  # chars | graphemes | x | mastodon
    open: str | None = None        # the composer's address: {text}, {url}, {instance}
    open_takes_url: bool = False   # the composer takes the link apart from the text
    direct: str | None = None      # the connection Kranto posts with, when it can
    direct_kind: str | None = None  # the ask a direct post waits on
    thread: bool = False           # a thread is possible when posting directly
    links: int = 1
    hashtags: int = 0
    playbook: str = ""
    needs: str | None = None       # what the person types before Open works ("instance")
    not_offered: str | None = None  # why it is not offered, when it is not
    later: str | None = None       # what would make it possible (shown under "Not possible")

    def ways(self) -> tuple[str, ...]:
        """``("open", "direct")``, ``("open",)``, ``("direct",)`` or ``()``."""
        if self.not_offered:
            return ()
        return tuple(w for w, ok in (("open", self.open), ("direct", self.direct_kind)) if ok)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "limit": self.limit, "unit": self.unit,
                "ways": list(self.ways()), "direct": self.direct, "thread": self.thread,
                "needs": self.needs, "not_offered": self.not_offered, "later": self.later}


# the playbooks: what Kranto attaches and when; the person's template (the prose engine's
# sites/<id> guide) says how a post on the site reads
_LINK_LAST = ("The link goes on its own line at the end; never a shortener, never a second link. "
              "Do not write \"link below\" or \"read more\": the reader sees the link.")
SITES: dict[str, Site] = {s.id: s for s in (
    Site("bluesky", "Bluesky", 300, "characters", "graphemes",
         open="https://bsky.app/intent/compose?text={text}",
         direct="bluesky_post", direct_kind="post.bluesky", thread=True, hashtags=2,
         playbook="One post that stands alone. When posting directly and the post has three or "
                  "more points, a thread of two or three, the first standing alone. Tags: at "
                  "most two, at the end, only ones the sources use. " + _LINK_LAST),
    Site("mastodon", "Mastodon", 500, "characters, a link counts 23", "mastodon",
         open="https://{instance}/share?text={text}", needs="instance",
         direct="mastodon_post", direct_kind="post.mastodon", hashtags=3,
         playbook="One post. Tags: one to three in CamelCase (#OpenSource), on the last line, "
                  "so screen readers say them. No @mentions. " + _LINK_LAST),
    Site("x", "X", 280, "characters, a link counts 23", "x",
         open="https://x.com/intent/tweet?text={text}&url={url}", open_takes_url=True,
         hashtags=1,
         playbook="One post. At most one hashtag, usually none. No @mentions. The link is "
                  "added after the text by X's composer, which draws its card: do not write "
                  "the link in the text."),
    Site("threads", "Threads", 500, "characters", "chars",
         open="https://www.threads.com/intent/post?text={text}&url={url}",
         open_takes_url=True, hashtags=1,
         playbook="One post. At most one topic tag. The link is added by Threads' composer "
                  "and drawn as a card: do not write the link in the text."),
)}

# What could not be offered, and why. Filled from the live check of 13 November 2026
# (docs/posting.md, "Which sites, and why"): a site here appears under "Not possible today".
NOT_OFFERED: dict[str, Site] = {s.id: s for s in (
    Site("linkedin", "LinkedIn", 3000, "characters", "chars", hashtags=3,
         not_offered="LinkedIn has no documented link that fills in a post's text, and posting "
                     "directly needs your own LinkedIn app",
         later="Posting directly with your own LinkedIn app comes in the next release"),
    Site("substack", "Substack", 0, "words", "chars",
         not_offered="Substack has no link that fills in a post or a Note, and no way for an "
                     "app to post"),
    Site("instagram", "Instagram", 0, "", "chars",
         not_offered="Instagram takes pictures and video from a public address, not words"),
    Site("facebook", "Facebook Pages", 0, "", "chars",
         not_offered="a Page post from your own app is hidden until Meta reviews the app"),
)}


def get(site_id: str | None) -> Site | None:
    """The site, offered or not; None for a name Kranto does not know."""
    if not site_id:
        return None
    return SITES.get(site_id) or NOT_OFFERED.get(site_id)


def offered() -> list[Site]:
    return [s for s in SITES.values() if s.ways()]


def name_of(site_id: str | None) -> str:
    """A site's name, or the stored value itself for a site Kranto does not know (never an
    error: a draft written by a later Kranto still draws)."""
    s = get(site_id)
    return s.name if s else str(site_id or "")


# -- counting, the site's way ------------------------------------------------------------------

_EXTEND = {"Mn", "Me", "Mc"}


def graphemes(text: str) -> int:
    """User-perceived characters, as Bluesky counts them: a base character with its combining
    marks, variation selectors, skin tones and zero-width-joined parts is one; a pair of
    regional indicators (a flag) is one. Standard library only."""
    n, prev_zwj, ri_open = 0, False, False
    for ch in text:
        cp = ord(ch)
        if prev_zwj:
            prev_zwj = False
            continue
        if cp == 0x200D:
            prev_zwj = True
            continue
        if (unicodedata.category(ch) in _EXTEND or 0xFE00 <= cp <= 0xFE0F
                or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F):
            continue
        if 0x1F1E6 <= cp <= 0x1F1FF:
            if ri_open:
                ri_open = False
                continue
            ri_open = True
        else:
            ri_open = False
        n += 1
    return n


# twitter-text v3: weight 1 for these ranges, 2 for the rest (CJK, emoji); a link is 23
_X_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def _x_weight(text: str) -> int:
    w = 0
    for ch in text:
        cp = ord(ch)
        if cp == 0x200D or 0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF:
            continue                   # part of the emoji before it, already counted
        w += 1 if any(a <= cp <= b for a, b in _X_LIGHT) else 2
    return w


def count(site: Site | str, text: str) -> int:
    """``text``'s length the site's way."""
    s = site if isinstance(site, Site) else get(site)
    text = text or ""
    if s is None or s.counting == "chars":
        return len(text)
    if s.counting == "graphemes":
        return graphemes(text)
    links = URL.findall(text)
    rest = URL.sub("", text)
    if s.counting == "x":
        return _x_weight(rest) + LINK_WEIGHT * len(links)
    return len(rest) + LINK_WEIGHT * len(links)        # mastodon


def room(site: Site, link: str | None) -> int:
    """What the words may use when the link is added after them (on its own line), or by the
    composer (X, Threads: still counted by X)."""
    if not link:
        return site.limit
    extra = count(site, "\n\n" + link)
    return site.limit - extra


def fit(site: Site, text: str, limit: int) -> tuple[str, bool]:
    """``(text, cut)``: at most ``limit`` the site's way; the last full sentence that fits,
    else cut at a word with "…". ``cut`` says whether anything was taken off."""
    text = text.strip()
    if count(site, text) <= limit:
        return text, False
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text)]
    for e in reversed(ends):
        if count(site, text[:e]) <= limit and e >= len(text) // 4:
            return text[:e].strip(), True
    words = text.split(" ")
    while words and count(site, " ".join(words) + "…") > limit:
        words.pop()
    return (" ".join(words).rstrip(",;:—- ") + "…") if words else text[:max(0, limit - 1)] + "…", \
        True


# -- the words Kranto keeps: links, tags --------------------------------------------------------

TAG = re.compile(r"(?<![\w#])#(\w{2,40})")


def clean(site: Site, text: str, allowed: set[str]) -> tuple[str, list[str]]:
    """The model's words with what the site cannot carry taken off: any address that is not
    one of ``allowed`` (the post's link and the sources), and tags past the site's count.
    ``(text, removed)``, ``removed`` in words for the draft's facts."""
    removed: list[str] = []

    def link(m: re.Match[str]) -> str:
        url = m.group(0).rstrip(".,;:!?")
        tail = m.group(0)[len(url):]
        if url in allowed:
            return m.group(0)
        removed.append(f"an address that is not one of the sources ({urlsplit(url).hostname})")
        return tail
    out = URL.sub(link, text)
    tags = TAG.findall(out)
    if len(tags) > site.hashtags:
        keep = set(tags[:site.hashtags])
        seen: set[str] = set()

        def tag(m: re.Match[str]) -> str:
            t = m.group(1)
            if t in keep and t not in seen:
                seen.add(t)
                return m.group(0)
            return ""
        out = TAG.sub(tag, out)
        removed.append(f"{len(tags) - site.hashtags} tag(s) past {site.name}'s {site.hashtags}")
    out = re.sub(r"[ \t]+\n", "\n", re.sub(r"[ \t]{2,}", " ", out)).strip()
    return out, removed


# -- Open: the composer's address -------------------------------------------------------------

def open_address(site: Site, text: str, link: str | None, *, instance: str | None = None
                 ) -> str | None:
    """The address that opens the site's composer with ``text`` (and ``link``) filled in; None
    when the site has no Open or it needs what the person has not typed (Mastodon's server)."""
    if not site.open or site.not_offered:
        return None
    if site.needs == "instance":
        host = (instance or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9.-]{3,253}", host) or "." not in host:
            return None
    else:
        host = ""
    words = text
    if link and not site.open_takes_url and link not in words:
        words = f"{words}\n\n{link}"
    return site.open.format(text=quote(words, safe=""), url=quote(link or "", safe=""),
                            instance=host)


# -- the person's choices (Settings › Posting) -------------------------------------------------

@dataclass(frozen=True)
class Choice:
    """One site as the person set it: ticked, whether Kranto posts directly, and (Mastodon) the
    server to open."""

    site: Site
    direct: bool = False
    instance: str | None = None
    disclose: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def choices(store) -> list[Choice]:
    """The sites the person ticked, in the registry's order, each with their choices; a ticked
    site Kranto no longer offers is left out (Settings › Posting says so)."""
    from ..stored.settings import PostingSites, get_blob
    row = get_blob(store, PostingSites.SETTING, PostingSites) or PostingSites()
    ticked = [s for s in (row.sites or []) if isinstance(s, str)]
    direct = row.direct if isinstance(row.direct, dict) else {}
    disclose = row.disclose if isinstance(row.disclose, dict) else {}
    out = []
    for s in offered():
        if s.id in ticked:
            out.append(Choice(s, direct=direct.get(s.id) is True and "direct" in s.ways(),
                              instance=row.instance if s.needs == "instance" else None,
                              disclose=disclose.get(s.id) is True))
    return out


SOURCES = {
    "bluesky": "https://docs.bsky.app/docs/advanced-guides/intent-links (read 2026-11-13)",
    "mastodon": "https://github.com/mastodon/mastodon, app/helpers/application_helper.rb and "
                "the /share route (read 2026-11-13)",
    "x": "https://docs.x.com/x-for-websites/post-button/guides/web-intent (read 2026-11-13)",
    "threads": "https://developers.facebook.com/docs/threads/threads-web-intents "
               "(read 2026-11-13)",
    "linkedin": "https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/"
                "plugins/share-plugin (a link to share carries an address only; read "
                "2026-11-13)",
    "substack": "https://substack.com/api-tos and https://on.substack.com/p/notes-faq (no "
                "publishing API, no composer link; read 2026-11-13)",
}
