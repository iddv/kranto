"""Releases of the repositories a GitHub account stars, read with a connected token.

Stars and releases are public data; the token (``connections.github``) is for
GitHub's signed-in allowance of 5,000 requests an hour instead of 60. A fetch
asks who the token belongs to (``/user``), lists that account's stars most
recently pushed first (``/users/<login>/starred``, which needs no permission on
a fine-grained token), and reads the latest releases of the first
``MAX_REPOS``: at most 32 requests. Drafts are skipped. Authors are not kept.
"""

from __future__ import annotations

from .base import HTTP, Item, SourceError, safe_url
from .rss import _parse_date

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
MAX_REPOS = 30
RELEASES_PER_REPO = 5
BODY_CHARS = 4000
WHATS = ("starred_releases",)


class GitHubSource:
    kind = "github"
    needs = "github"

    def __init__(self, http: HTTP, *, what: str = "starred_releases") -> None:
        if what not in WHATS:
            raise ValueError(f"unknown github source {what!r}; one of {', '.join(WHATS)}")
        self.http, self.what = http, what

    @property
    def label(self) -> str:
        return "Releases of repositories you star"

    def fetch(self) -> list[Item]:
        me = self.http.get_json(f"{API}/user", headers=HEADERS)
        login = me.get("login") if isinstance(me, dict) else None
        if not isinstance(login, str) or not login:
            raise SourceError("GitHub did not say which account the token is for")
        starred = self.http.get_json(f"{API}/users/{login}/starred", headers=HEADERS,
                                     params={"sort": "updated", "direction": "desc",
                                             "per_page": MAX_REPOS})
        if not isinstance(starred, list):
            raise SourceError("unexpected GitHub reply for starred repositories")
        repos = [r["full_name"] for r in starred
                 if isinstance(r, dict) and isinstance(r.get("full_name"), str)][:MAX_REPOS]
        items, failed, last = [], 0, None
        for full_name in repos:
            try:
                releases = self.http.get_json(f"{API}/repos/{full_name}/releases",
                                              headers=HEADERS,
                                              params={"per_page": RELEASES_PER_REPO})
            except SourceError as exc:
                if exc.needs_login:
                    raise
                failed, last = failed + 1, exc
                continue
            for release in releases if isinstance(releases, list) else []:
                item = release_item(full_name, release)
                if item is not None:
                    items.append(item)
        if repos and failed == len(repos) and last is not None:
            raise last
        return items

    def enrich(self, item: Item) -> Item:
        return item


def release_item(full_name: str, release: dict) -> Item | None:
    if not isinstance(release, dict) or release.get("draft"):
        return None
    url = safe_url(release.get("html_url"))
    if not url:
        return None
    name = release.get("name") or release.get("tag_name") or ""
    body = release.get("body") if isinstance(release.get("body"), str) else ""
    return Item(id=url, title=f"{full_name} {name}".strip(), body=body[:BODY_CHARS], url=url,
                published_at=_parse_date(release.get("published_at")
                                         or release.get("created_at") or ""))
