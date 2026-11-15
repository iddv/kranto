"""Preconfigured sources: the catalog (section 2).

A preset is a recipe: a provider, a name, an access label, one or two fields, and
a function from the fields to ``(kind, params, label)``. Most presets build a
feed URL for the ``rss`` kind; a few map to ``hackernews``, ``arxiv``,
``bluesky`` or ``mastodon``. The catalog is served as JSON (``GET /api/catalog``)
and drawn by Kranto UI; the plain ``POST /sources`` form takes a preset too, and
the scout proposes sources as presets, so there is one
definition of what can be added.

Access is ``public`` (no login), ``login`` (reads with a connected account,
``needs`` names the provider) or ``not_offered`` (shown with the reason, never
built). A login preset whose provider cannot be connected yet is ``available:
False`` and says when it arrives.

Owner decisions (6 Oct 2026): no Reddit presets (Reddit's feeds stop on 13 Nov
2026 and its API needs an approval the project will not seek); no Lobsters (its
robots.txt signals ``ai-input=no``); newsletter publications are kept 30 days.

Some fields are resolved with a request when a preset is built for a preview
or an add: a YouTube handle to its channel id, a Bluesky handle in a feed or list
URL to its DID. Every such request goes through the safe ``HTTP`` client.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlparse

from .base import HTTP, SourceError, safe_url
from .mastodon import clean_instance

SUBSTACK_RETENTION_DAYS = 30.0
# YouTube's developer policies: API data is kept at most 30 days (config.KIND_MAX_DAYS).
YOUTUBE_RETENTION_DAYS = 30.0


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    placeholder: str = ""
    hint: str = ""


@dataclass(frozen=True)
class Resolved:
    """What a preset builds: a source kind, its parameters, and its label."""

    kind: str
    params: dict
    label: str


@dataclass(frozen=True)
class Preset:
    key: str
    provider: str
    name: str
    blurb: str
    access: str  # "public" | "login" | "not_offered"
    fields: tuple[Field, ...] = ()
    build: Callable[[dict, HTTP | None], Resolved] | None = field(default=None, repr=False)
    needs: str | None = None
    available: bool = True
    reason: str | None = None
    retention_days: float | None = None
    # Whether the scout may propose it: public, available, and buildable without
    # a request that a model's guess could waste.
    scout: bool = False

    def to_json(self) -> dict:
        return {
            "key": self.key, "provider": self.provider,
            "provider_name": PROVIDERS[self.provider], "name": self.name,
            "blurb": self.blurb, "access": self.access, "needs": self.needs,
            "available": self.available and self.access != "not_offered",
            "reason": self.reason, "retention_days": self.retention_days,
            "fields": [{"key": f.key, "label": f.label, "placeholder": f.placeholder,
                        "hint": f.hint} for f in self.fields],
        }


PROVIDERS = {
    "web": "Any website",
    "hackernews": "Hacker News",
    "github": "GitHub",
    "arxiv": "arXiv",
    "youtube": "YouTube",
    "mastodon": "Mastodon and the Fediverse",
    "bluesky": "Bluesky",
    "stackexchange": "Stack Exchange",
    "producthunt": "Product Hunt",
    "substack": "Substack and newsletters",
    "reddit": "Reddit",
    "x": "X / Twitter",
    "linkedin": "LinkedIn",
}
# Providers shown in the catalog (Reddit again since with your own app, or through
# live search).
CATALOG_PROVIDERS = tuple(PROVIDERS)


# -- field helpers ---------------------------------------------------------------------


def _need(fields: dict, key: str, what: str) -> str:
    value = " ".join(str(fields.get(key) or "").split())
    if not value:
        raise ValueError(f"{what} is required")
    return value


def _host(value: str, what: str) -> str:
    host = re.sub(r"^https?://", "", value.strip().lower()).split("/")[0]
    if not re.fullmatch(r"([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", host):
        raise ValueError(f"not a host name for {what}: {value!r}")
    return host


_REPO = re.compile(r"^(?:https?://(?:www\.)?github\.com/)?([A-Za-z0-9-]{1,39})/([A-Za-z0-9_.-]{1,100}?)"
                   r"(?:\.git)?/?(?:[?#].*)?$")


def _repo(value: str) -> tuple[str, str]:
    m = _REPO.match(value.strip())
    if not m or m.group(2) in (".", ".."):
        raise ValueError(f"not a GitHub repository (owner/name or its URL): {value!r}")
    return m.group(1), m.group(2)


def _tag(value: str, what: str = "a tag") -> str:
    tag = value.strip().lstrip("#")
    if not re.fullmatch(r"[\w][\w.+-]{0,99}", tag):
        raise ValueError(f"not {what}: {value!r}")
    return tag


# -- builders --------------------------------------------------------------------------


def _feed_url(f, http):
    url = safe_url(_need(f, "url", "The feed URL"))
    if url is None:
        raise ValueError("the feed URL must start with http:// or https://")
    return Resolved("rss", {"url": url}, urlparse(url).hostname or url)


def _website(f, http):
    from .discover import discover_feed

    site = safe_url(_need(f, "site", "The website"))
    if site is None:
        site = safe_url("https://" + _need(f, "site", "The website").removeprefix("//"))
    if site is None:
        raise ValueError("the website must be a homepage URL")
    if http is None:
        raise ValueError("finding a website's feed needs a fetch")
    url = discover_feed(http, site)
    return Resolved("rss", {"url": url}, urlparse(site).hostname or site)


def _hn_feed(feed: str, label: str):
    return lambda f, http: Resolved("hackernews", {"feed": feed}, label)


def _web_search(f, http):
    from .websearch_source import host_of
    site = host_of(_need(f, "site", "The website"))
    if not site or "." not in site:
        raise ValueError("the website must be an address such as example.org")
    query = " ".join(str(f.get("query") or "").split())[:200]
    return Resolved("websearch", {"site": site, **({"query": query} if query else {})},
                    f"Live search: {site}" + (f" ({query})" if query else ""))


def _reddit_sub(f, http):
    name = _need(f, "subreddit", "The subreddit").removeprefix("https://www.reddit.com")
    name = name.removeprefix("/").removeprefix("r/").strip("/").split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", name):
        raise ValueError("a subreddit is its name, such as wallstreetbets")
    return Resolved("reddit", {"subreddit": name}, f"r/{name}")


def _reddit_search(f, http):
    query = " ".join(str(f.get("query") or "").split())[:200]
    if not query:
        raise ValueError("say what to look for on Reddit: the topic's words")
    sub = str(f.get("subreddit") or "").strip().removeprefix("r/").strip("/")
    site = f"reddit.com/r/{sub}" if sub else "reddit.com"
    return Resolved("websearch", {"site": site, "query": query},
                    f"Reddit (via search): {query}" + (f" in r/{sub}" if sub else ""))





def _hn_search(f, http):
    query = _need(f, "query", "The search phrase")
    return Resolved("hackernews", {"query": query}, f"HN search: {query}")


def _gh_releases(f, http):
    owner, repo = _repo(_need(f, "repo", "The repository"))
    return Resolved("rss", {"url": f"https://github.com/{owner}/{repo}/releases.atom"},
                    f"{owner}/{repo} releases")


def _gh_commits(f, http):
    owner, repo = _repo(_need(f, "repo", "The repository"))
    branch = _need(f, "branch", "The branch")
    if not re.fullmatch(r"[\w./-]{1,200}", branch) or ".." in branch:
        raise ValueError(f"not a branch name: {branch!r}")
    return Resolved("rss", {"url": f"https://github.com/{owner}/{repo}/commits/{branch}.atom"},
                    f"{owner}/{repo} commits on {branch}")


def _arxiv_category(f, http):
    cat = _need(f, "category", "The category").strip()
    if not re.fullmatch(r"[a-z-]{2,20}(\.[A-Za-z-]{1,10})?", cat):
        raise ValueError(f"not an arXiv category such as cs.DC or q-fin.GN: {cat!r}")
    return Resolved("rss", {"url": f"https://rss.arxiv.org/rss/{cat}"}, f"arXiv {cat}")


def _arxiv_search(f, http):
    query = _need(f, "query", "The search")
    return Resolved("arxiv", {"query": query}, f"arXiv search: {query}")


_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")


def _youtube_channel(f, http):
    value = _need(f, "channel", "The channel").strip()
    m = re.search(r"(?:youtube\.com/channel/)?(UC[A-Za-z0-9_-]{22})\b", value)
    if m:
        channel_id = m.group(1)
        name = channel_id
    else:
        handle = re.sub(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/", "", value).split("/")[0]
        handle = handle.split("?")[0]
        if not handle.startswith("@"):
            handle = "@" + handle
        if not re.fullmatch(r"@[A-Za-z0-9._-]{3,100}", handle):
            raise ValueError(f"not a YouTube channel URL or handle: {value!r}")
        if http is None:
            raise ValueError("a channel handle is resolved with a fetch")
        # From the EU, YouTube redirects a first visit to its cookie consent page;
        # SOCS=CAI is the answer "Reject all" gives (essential cookies only).
        page = http.get(f"https://www.youtube.com/{quote(handle)}",
                        headers={"Cookie": "SOCS=CAI"}).text
        found = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/'
                          r'(UC[A-Za-z0-9_-]{22})"', page) \
            or re.search(r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"', page)
        if not found:
            raise SourceError(f"no channel found for {handle}", transient=False)
        channel_id, name = found.group(1), handle
    return Resolved("rss", {"url": f"https://www.youtube.com/feeds/videos.xml?"
                                   f"channel_id={channel_id}"}, f"YouTube: {name}")


def _youtube_playlist(f, http):
    value = _need(f, "playlist", "The playlist").strip()
    found = parse_qs(urlparse(value).query).get("list", [value])[0]
    if not re.fullmatch(r"(?:PL|UU|LL|FL|OL)[A-Za-z0-9_-]{10,64}", found):
        raise ValueError(f"not a YouTube playlist URL or id: {value!r}")
    return Resolved("rss", {"url": f"https://www.youtube.com/feeds/videos.xml?"
                                   f"playlist_id={found}"}, f"YouTube playlist {found}")


def _masto_hashtag(f, http):
    instance = clean_instance(_need(f, "instance", "The instance"))
    tag = _tag(_need(f, "tag", "The hashtag"), "a hashtag")
    return Resolved("rss", {"url": f"https://{instance}/tags/{quote(tag)}.rss"},
                    f"#{tag} on {instance}")


def _masto_account(f, http):
    value = _need(f, "account", "The account").strip()
    m = re.fullmatch(r"https?://([^/\s]+)/@([A-Za-z0-9_]{1,30})/?", value)
    if m:
        instance, name = m.group(1), m.group(2)
    else:
        m = re.fullmatch(r"@?([A-Za-z0-9_]{1,30})@([^@/\s]+)", value)
        if not m:
            raise ValueError(f"not a Mastodon account (@name@instance or its URL): {value!r}")
        name, instance = m.group(1), m.group(2)
    instance = clean_instance(instance)
    return Resolved("rss", {"url": f"https://{instance}/@{name}.rss"}, f"@{name}@{instance}")


def _masto_home(f, http):
    instance = clean_instance(_need(f, "instance", "The instance"))
    return Resolved("mastodon", {"instance": instance, "what": "home"},
                    f"Your home timeline on {instance}")


def _masto_list(f, http):
    instance = clean_instance(_need(f, "instance", "The instance"))
    value = _need(f, "list", "The list").strip()
    m = re.fullmatch(r"(?:https?://[^/]+/lists/)?([0-9]{1,20})/?", value)
    if not m:
        raise ValueError(f"not a Mastodon list (its number, or its URL ending in "
                         f"/lists/<number>): {value!r}")
    list_id, title = m.group(1), None
    if http is not None:
        # The list's own name, read with the account (the adapter's HTTP carries it).
        data = http.get_json(f"https://{instance}/api/v1/lists/{list_id}")
        title = data.get("title") if isinstance(data, dict) else None
    params = {"instance": instance, "what": "list", "list_id": list_id}
    if title:
        params["title"] = str(title)[:100]
    return Resolved("mastodon", params, f"Your list {title or list_id} on {instance}")


_BSKY_HANDLE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def _bsky_actor(value: str) -> str:
    actor = value.strip().lstrip("@").lower()
    if actor.startswith("did:"):
        if not re.fullmatch(r"did:(?:plc|web):[a-z0-9._:%-]{3,200}", actor):
            raise ValueError(f"not a Bluesky DID: {value!r}")
        return actor
    if not _BSKY_HANDLE.fullmatch(actor):
        raise ValueError(f"not a Bluesky handle: {value!r}")
    return actor


def _bsky_did(actor: str, http: HTTP | None) -> str:
    if actor.startswith("did:"):
        return actor
    if http is None:
        raise ValueError("a Bluesky handle is resolved with a fetch")
    from .bluesky import API

    data = http.get_json(f"{API}/com.atproto.identity.resolveHandle", params={"handle": actor})
    did = data.get("did") if isinstance(data, dict) else None
    if not isinstance(did, str) or not did.startswith("did:"):
        raise SourceError(f"Bluesky did not resolve {actor}", transient=False)
    return did


def _bsky_profile(f, http):
    actor = _bsky_actor(re.sub(r"^https?://bsky\.app/profile/", "",
                               _need(f, "handle", "The handle")).split("/")[0])
    return Resolved("rss", {"url": f"https://bsky.app/profile/{actor}/rss"}, f"Bluesky: {actor}")


def _bsky_collection(kind: str):
    path, nsid, param = {"feed": ("feed", "app.bsky.feed.generator", "feed_uri"),
                         "list": ("lists", "app.bsky.graph.list", "list_uri")}[kind]

    def build(f, http):
        value = _need(f, "url", f"The {kind}'s URL").strip()
        m = re.fullmatch(rf"https?://bsky\.app/profile/([^/]+)/{path}/([\w.~-]+)/?", value)
        if not m:
            raise ValueError(f"not a Bluesky {kind} URL (https://bsky.app/profile/<handle>/"
                             f"{path}/<id>): {value!r}")
        did = _bsky_did(_bsky_actor(m.group(1)), http)
        return Resolved("bluesky", {param: f"at://{did}/{nsid}/{m.group(2)}"},
                        f"Bluesky {kind}: {m.group(2)} by {m.group(1)}")
    return build


def _se_tag(f, http):
    site = _host(_need(f, "site", "The site"), "a Stack Exchange site")
    if not re.search(r"(^|\.)(stackexchange|stackoverflow|serverfault|superuser|askubuntu|"
                     r"mathoverflow)\.(com|net)$", site):
        raise ValueError(f"not a Stack Exchange site: {site!r}")
    tag = _tag(_need(f, "tag", "The tag"))
    return Resolved("rss", {"url": f"https://{site}/feeds/tag/{quote(tag)}"}, f"{site}: {tag}")


def _se_search(f, http):
    from .stackexchange import clean_site

    site = clean_site(_need(f, "site", "The site"))
    query = _need(f, "query", "The search")[:200]
    return Resolved("stackexchange", {"site": site, "query": query}, f"{site} search: {query}")


def _ph_today(f, http):
    return Resolved("rss", {"url": "https://www.producthunt.com/feed"}, "Product Hunt: today")


def _ph_launches(f, http):
    from .producthunt import clean_topic

    topic = clean_topic(f.get("topic"))
    params = {"what": "launches", **({"topic": topic} if topic else {})}
    return Resolved("producthunt", params,
                    f"Product Hunt launches: {topic}" if topic else "Product Hunt launches")


def _gh_starred(f, http):
    return Resolved("github", {"what": "starred_releases"}, "Releases of repositories you star")


def _yt_subscriptions(f, http):
    return Resolved("youtube", {"what": "subscriptions"}, "Your YouTube subscriptions")


def _bsky_home(f, http):
    return Resolved("bluesky", {"what": "home"}, "Your Bluesky home timeline")


def _bsky_search(f, http):
    query = _need(f, "query", "The search")[:200]
    return Resolved("bluesky", {"what": "search", "query": query}, f"Bluesky search: {query}")


_X_LIST = re.compile(r"(?:https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/i/lists/)?([0-9]{1,19})/?")
_X_HANDLE = re.compile(r"(?:https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/)?@?([A-Za-z0-9_]{1,15})/?")
X_COST = ("X bills your developer account $0.005 a post read; this reads up to {n} a run "
          "(about ${usd:.2f}).")


def _x_get(http: HTTP | None, path: str, what: str) -> dict:
    if http is None or http.auth_host != "api.x.com":
        raise ValueError(f"{what} is read with your connected X account")
    from .x import API

    data = http.get_json(f"{API}{path}")
    found = data.get("data") if isinstance(data, dict) else None
    if not isinstance(found, dict):
        raise SourceError(f"X did not find {what}", transient=False)
    return found


def _x_list(f, http):
    m = _X_LIST.fullmatch(_need(f, "list", "The list").strip())
    if not m:
        raise ValueError("not an X list: its URL (x.com/i/lists/<number>) or its number")
    found = _x_get(http, f"/lists/{m.group(1)}", "the list")      # one list read, $0.005
    title = str(found.get("name") or "")[:100] or None
    params = {"what": "list", "list_id": m.group(1), **({"title": title} if title else {})}
    return Resolved("x", params, f"X list: {title or m.group(1)}")


def _x_profile(f, http):
    m = _X_HANDLE.fullmatch(_need(f, "handle", "The account").strip())
    if not m or m.group(1).lower() in ("i", "home", "search", "explore"):
        raise ValueError("not an X account: @name or x.com/name")
    found = _x_get(http, f"/users/by/username/{m.group(1)}", f"@{m.group(1)}")  # a user read
    user_id = str(found.get("id") or "")
    if not user_id.isdigit():
        raise SourceError(f"X did not find @{m.group(1)}", transient=False)
    handle = str(found.get("username") or m.group(1))
    return Resolved("x", {"what": "profile", "user_id": user_id, "handle": handle},
                    f"X: @{handle}")


def _x_search(f, http):
    query = _need(f, "query", "The search")[:400]
    lang = " ".join(str(f.get("lang") or "").split()).lower() or None
    if lang and not re.fullmatch(r"[a-z]{2,3}", lang):
        raise ValueError(f"not a language code such as en: {lang!r}")
    return Resolved("x", {"what": "search", "query": query, **({"lang": lang} if lang else {})},
                    f"X search: {query}")


def _x_grok(f, http):
    query = _need(f, "query", "The search")[:300]
    handles = " ".join(str(f.get("handles") or "").replace(",", " ").split()) or None
    if handles and not all(re.fullmatch(r"@?[A-Za-z0-9_]{1,15}", h) for h in handles.split()):
        raise ValueError("handles are X usernames, separated by spaces or commas")
    params = {"query": query, **({"handles": handles.replace("@", "")} if handles else {})}
    return Resolved("xai_search", params, f"X search through Grok: {query}")


def _x_fixed(what: str, label: str):
    return lambda f, http: Resolved("x", {"what": what}, label)


def _substack(f, http):
    value = _need(f, "publication", "The publication").strip().lower()
    if re.fullmatch(r"[a-z0-9-]{1,63}", value):
        host = f"{value}.substack.com"
    else:
        host = _host(value, "a publication")
    return Resolved("rss", {"url": f"https://{host}/feed"}, host)


# -- the catalog ------------------------------------------------------------------------

def _presets() -> list[Preset]:
    url = Field("url", "Feed URL", "https://example.org/feed.xml")
    return [
        Preset("web.feed", "web", "RSS or Atom feed", "Any feed URL: a blog, a newsletter, "
               "a release page.", "public", (url,), _feed_url, scout=True),
        Preset("web.site", "web", "A website", "Give a homepage; the feed is found from the "
               "page.", "public", (Field("site", "Website", "https://example.org/"),),
               _website, scout=True),
        Preset("web.search", "web", "A website without a feed (through live search)",
               "Each run searches the site through your live search backend for what is new "
               "(Settings, Watching, Live search): free in Exa's free mode, $0.005 to $0.008 a "
               "run with a key. For a forum or a page with no feed.", "public",
               (Field("site", "Website", "discuss.example.org"),
                Field("query", "What to look for (optional)", "new releases",
                      "Empty: whatever is new on the site")), _web_search),
        Preset("reddit.sub", "reddit", "A subreddit", "Its new posts. With your own Reddit "
               "app connected (Settings, Accounts, Reddit) through Reddit's API as you, with "
               "scores and top comments; without it, Reddit's public feed, which Reddit stops "
               "on 13 Nov 2026.", "public",
               (Field("subreddit", "Subreddit", "wallstreetbets"),), _reddit_sub),
        Preset("reddit.search", "reddit", "Reddit (via search)", "Reddit posts on the topic's "
               "words through your live search (no Reddit key: the search provider's index): "
               "who is talking about it and when, a signal rather than proof.", "public",
               (Field("query", "What to look for", "humanoid robots"),
                Field("subreddit", "Only this subreddit (optional)", "wallstreetbets",
                      "Empty: all of Reddit")), _reddit_search),
        Preset("hackernews.front", "hackernews", "Front page", "The 50 stories on the front "
               "page, every fetch.", "public", (), _hn_feed("front", "HN front page"),
               scout=True),
        Preset("hackernews.show", "hackernews", "Show HN", "New Show HN posts, newest first.",
               "public", (), _hn_feed("show", "HN show"), scout=True),
        Preset("hackernews.ask", "hackernews", "Ask HN", "New Ask HN posts.", "public", (),
               _hn_feed("ask", "HN ask"), scout=True),
        Preset("hackernews.search", "hackernews", "Search", "New stories matching a short "
               "phrase. Reaches back 14 days on the first run.", "public",
               (Field("query", "Search phrase", "local-first",
                      "Short, distinctive phrases work best."),), _hn_search, scout=True),
        Preset("github.releases", "github", "Releases of a repository", "The repository's "
               "releases feed.", "public",
               (Field("repo", "Repository", "automerge/automerge", "owner/name or its URL"),),
               _gh_releases, scout=True),
        Preset("github.commits", "github", "Commits on a branch", "The branch's commits feed. "
               "Noisy for active repositories.", "public",
               (Field("repo", "Repository", "automerge/automerge", "owner/name or its URL"),
                Field("branch", "Branch", "main")), _gh_commits, scout=True),
        Preset("github.starred", "github", "Releases of repositories you star",
               "The latest releases of the 30 repositories you star that were pushed to most "
               "recently. Reads with your read-only token.", "login", (), _gh_starred,
               needs="github"),
        Preset("github.trending", "github", "Trending", "", "not_offered",
               reason="GitHub has no API or feed for Trending, and scraping the page is "
                      "against its terms."),
        Preset("github.notifications", "github", "Your notifications", "", "not_offered",
               reason="GitHub only serves notifications to a classic personal access token, "
                      "which cannot be made read-only."),
        Preset("arxiv.category", "arxiv", "Category listing", "New papers in one category, "
               "once a day.", "public",
               (Field("category", "Category", "cs.DC", "e.g. cs.DC, q-fin.GN, "
                                                         "physics.soc-ph"),),
               _arxiv_category, scout=True),
        Preset("arxiv.search", "arxiv", "Search", "Papers matching a query, newest first. One "
               "request every three seconds at most.", "public",
               (Field("query", "Search", "conflict-free replicated data types"),),
               _arxiv_search, scout=True),
        Preset("youtube.channel", "youtube", "Channel", "The channel's latest 15 videos from its "
               "public feed. Give a channel URL or handle.", "public",
               (Field("channel", "Channel", "@LocalFirstConf",
                      "A handle, or a youtube.com/@handle or /channel/ URL"),),
               _youtube_channel, scout=True),
        Preset("youtube.playlist", "youtube", "Playlist", "A playlist's latest videos from its "
               "public feed.", "public",
               (Field("playlist", "Playlist", "https://www.youtube.com/playlist?list=PL..."),),
               _youtube_playlist, scout=True),
        Preset("youtube.subscriptions", "youtube", "Your subscriptions", "New videos from "
               "up to 100 channels you subscribe to. Needs your own Google Cloud project; API "
               "data is kept at most 30 days.", "login", (), _yt_subscriptions,
               needs="youtube", retention_days=YOUTUBE_RETENTION_DAYS),
        Preset("mastodon.hashtag", "mastodon", "Hashtag on an instance", "The instance's public "
               "feed for a hashtag. Some instances turn public feeds off.", "public",
               (Field("instance", "Instance", "mastodon.social"),
                Field("tag", "Hashtag", "localfirst")), _masto_hashtag, scout=True),
        Preset("mastodon.account", "mastodon", "An account", "An account's public posts from "
               "its instance feed.", "public",
               (Field("account", "Account", "@name@mastodon.social"),), _masto_account,
               scout=True),
        Preset("mastodon.home", "mastodon", "Your home timeline", "What you follow, read with "
               "your account. Read-only.", "login",
               (Field("instance", "Instance", "mastodon.social",
                      "The instance your connected account is on"),),
               _masto_home, needs="mastodon"),
        Preset("mastodon.list", "mastodon", "A list of yours", "One of your lists, read with "
               "your account.", "login",
               (Field("instance", "Instance", "mastodon.social"),
                Field("list", "List", "12345",
                      "The list's number, or its URL ending in /lists/<number>")),
               _masto_list, needs="mastodon"),
        Preset("bluesky.profile", "bluesky", "Profile", "An account's posts from its public "
               "feed.", "public", (Field("handle", "Handle", "name.bsky.social"),),
               _bsky_profile, scout=True),
        Preset("bluesky.feed", "bluesky", "Custom feed", "A feed generator's posts, from the "
               "public API.", "public",
               (Field("url", "Feed URL", "https://bsky.app/profile/<handle>/feed/<id>"),),
               _bsky_collection("feed"), scout=True),
        Preset("bluesky.list", "bluesky", "A list", "Posts from the accounts on a public list.",
               "public",
               (Field("url", "List URL", "https://bsky.app/profile/<handle>/lists/<id>"),),
               _bsky_collection("list"), scout=True),
        Preset("bluesky.search", "bluesky", "Search", "Recent posts matching a phrase. "
               "Bluesky's search now needs a signed-in account.", "login",
               (Field("query", "Search", "local-first",
                      "Short, distinctive phrases work best."),), _bsky_search,
               needs="bluesky"),
        Preset("bluesky.home", "bluesky", "Your home timeline", "What you follow, read with "
               "your account through read-only scopes.", "login", (), _bsky_home,
               needs="bluesky"),
        Preset("stackexchange.tag", "stackexchange", "Tag on a site", "New questions under a "
               "tag, from the site's public feed. Content is CC BY-SA: observations link to "
               "the post.", "public",
               (Field("site", "Site", "stackoverflow.com"), Field("tag", "Tag", "crdt")),
               _se_tag, scout=True),
        Preset("stackexchange.search", "stackexchange", "Search on a site", "New questions "
               "matching a phrase, through the API. Works without a key at 300 requests a day "
               "per address; your app key (Connections) raises it to 10,000.", "public",
               (Field("site", "Site", "stackoverflow.com"),
                Field("query", "Search", "conflict-free replicated")), _se_search),
        Preset("producthunt.today", "producthunt", "Today's launches", "The public feed of "
               "launches.", "public", (), _ph_today, scout=True),
        Preset("producthunt.launches", "producthunt", "Launches by topic", "The last day's "
               "launches ranked by votes, for one topic or all, through the API with your "
               "developer token.", "login",
               (Field("topic", "Topic (optional)", "developer-tools",
                      "A topic's name or its producthunt.com/topics/ URL; empty for all"),),
               _ph_launches, needs="producthunt"),
        Preset("substack.publication", "substack", "A publication", "Free posts from the "
               "publication's feed. Paid posts arrive as a teaser. Kept 30 days, as "
               "Substack's terms suggest.", "public",
               (Field("publication", "Publication", "name, name.substack.com or its domain"),),
               _substack, retention_days=SUBSTACK_RETENTION_DAYS, scout=True),
        Preset("substack.paid", "substack", "A newsletter you pay for", "", "not_offered",
               reason="Substack has no per-subscriber feed. Later, perhaps: a mailbox Kranto "
                      "read."),
        Preset("x.list", "x", "A list of yours", "Posts from the accounts on one of your lists, "
               "the best signal per post: you chose the authors. "
               + X_COST.format(n=20, usd=0.10) + " Kept 30 days.", "login",
               (Field("list", "List", "https://x.com/i/lists/1234567890",
                      "The list's URL or number; its name is read once ($0.005)"),),
               _x_list, needs="x"),
        Preset("x.home", "x", "Your home timeline", "Posts from the accounts you follow, newest "
               "first, replies left out. " + X_COST.format(n=20, usd=0.10)
               + " A list is usually the cheaper signal. Kept 30 days.", "login", (),
               _x_fixed("home", "Your X home timeline"), needs="x"),
        Preset("x.profile", "x", "An account", "One account's posts, replies left out and its own "
               "threads joined (one search more for a thread). "
               + X_COST.format(n=10, usd=0.05) + " Kept 30 days.",
               "login", (Field("handle", "Account", "@name",
                               "@name or its x.com URL; resolved once ($0.01)"),),
               _x_profile, needs="x"),
        Preset("x.search", "x", "Search", "Recent posts matching a phrase (the last 7 days), "
               "reposts and replies left out, once a day. "
               + X_COST.format(n=10, usd=0.05) + " Kept 30 days.", "login",
               (Field("query", "Search", "local-first sync",
                      "X's search operators work, such as from:name or has:links"),
                Field("lang", "Language (optional)", "en", "A two-letter code; empty for any")),
               _x_search, needs="x"),
        Preset("x.bookmarks", "x", "Your bookmarks", "What you bookmarked, read once a day as "
               "posts you marked. Your own app reads them at $0.001 a post, up to 20 a day. "
               "Kept 30 days.", "login", (), _x_fixed("bookmarks", "Your X bookmarks"),
               needs="x"),
        Preset("x.likes", "x", "Your likes", "What you liked, read once a day as posts you "
               "marked. Your own app reads them at $0.001 a post, up to 20 a day. Kept 30 days.",
               "login", (), _x_fixed("likes", "Your X likes"), needs="x"),
        Preset("x.grok_search", "x", "Search through Grok (an xAI key)", "Without an X "
               "developer app: Grok searches X once a day and lists the posts it read in its "
               "own words, with their links. xAI bills $5 per 1,000 posts it reads plus the "
               "model's tokens (an estimate of $0.06 to $0.17 a search for 10 to 30 posts), "
               "counted in the watcher's "
               "budget. Off until XAI_API_KEY is set.", "login",
               (Field("query", "Search", "solar mini-grids", "What to look for on X"),
                Field("handles", "Only these accounts (optional)", "name1, name2",
                      "Up to 20 usernames; empty for all of X")),
               _x_grok, needs="xai"),
        Preset("x.scrape", "x", "Without the API (Nitter, mirrors, cheap resellers)", "",
               "not_offered",
               reason="They read X through real account sessions, against X's terms; X sent "
                      "Nitter a cease-and-desist in August 2026. kranto reads X only through "
                      "the official API with your own developer app."),
        Preset("linkedin.any", "linkedin", "Anything on LinkedIn", "", "not_offered",
               reason="No API reads the feed or posts for a personal app, and the User "
                      "Agreement forbids automated access."),
    ]


PRESETS: dict[str, Preset] = {p.key: p for p in _presets()}


def catalog_json() -> dict:
    """The catalog as served by ``GET /api/catalog``: providers in order, with presets."""
    return {"providers": [
        {"key": p, "name": PROVIDERS[p],
         "presets": [s.to_json() for s in PRESETS.values() if s.provider == p]}
        for p in CATALOG_PROVIDERS]}


def get(key: str) -> Preset:
    try:
        return PRESETS[key]
    except KeyError:
        raise ValueError(f"unknown preset {key!r}") from None


def resolve(key: str, fields: dict | None, http: HTTP | None = None) -> Resolved:
    """``(kind, params, label)`` for a preset and its fields. Raises ``ValueError``
    for a preset that cannot be built (not offered, not yet available, bad fields)
    and ``SourceError`` when a resolving request fails."""
    preset = get(key)
    if preset.access == "not_offered" or preset.build is None:
        raise ValueError(f"{preset.name} is not offered: {preset.reason}")
    if not preset.available:
        raise ValueError(f"{preset.name}: {preset.reason}")
    fields = {k: v for k, v in (fields or {}).items() if isinstance(v, str | int | float)}
    unknown = set(fields) - {f.key for f in preset.fields}
    if unknown:
        raise ValueError(f"unknown fields for {preset.name}: {', '.join(sorted(unknown))}")
    return preset.build({k: str(v) for k, v in fields.items()}, http)


# -- site labels for existing sources ----------------------------------------------------

_HOSTS = (
    ("github.com", "github"), ("arxiv.org", "arxiv"), ("youtube.com", "youtube"),
    ("bsky.app", "bluesky"), ("substack.com", "substack"), ("producthunt.com", "producthunt"),
    ("stackexchange.com", "stackexchange"), ("stackoverflow.com", "stackexchange"),
    ("serverfault.com", "stackexchange"), ("superuser.com", "stackexchange"),
    ("askubuntu.com", "stackexchange"), ("mathoverflow.net", "stackexchange"),
    ("reddit.com", "reddit"),
)


def provider_of(kind: str, params: dict) -> str:
    """The catalog provider a source belongs to, for its site label."""
    if kind in ("hackernews", "arxiv", "bluesky", "mastodon", "reddit", "github", "youtube",
                "producthunt", "stackexchange", "x"):
        return kind
    if kind == "xai_search":
        return "x"
    if kind == "browser":
        # a site read in the browser is its site's (reddit.com is reddit's)
        site = str(params.get("site") or "")
        if site == "*":
            return "web"
        url = "https://" + site
    else:
        url = str(params.get("url") or "")
    host = (urlparse(url).hostname or "").lower()
    for suffix, provider in _HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return provider
    if re.search(r"/tags/[^/]+\.rss$|/@[A-Za-z0-9_]+\.rss$", urlparse(url).path or ""):
        return "mastodon"
    return "web"


def preset_for_proposal(kind: str, value: str) -> tuple[str, dict] | None:
    """The preset and fields for a scout proposal written as ``(kind, value)``, the
    form before presets, so old and new proposals are shown the same way."""
    if kind == "hackernews":
        feeds = {"front": "hackernews.front", "show": "hackernews.show", "ask": "hackernews.ask"}
        return (feeds[value], {}) if value in feeds else ("hackernews.search", {"query": value})
    if kind == "rss":
        return "web.feed", {"url": value}
    if kind == "site":
        return "web.site", {"site": value}
    if kind == "arxiv":
        return "arxiv.search", {"query": value}
    return None
