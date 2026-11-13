"""Context from GitHub for items about a repository.

A Show HN post, a release feed or an article that links to a GitHub repository
says more with the repository's own numbers next to it: stars, forks, when it
was last pushed, whether it is archived. The judge sees them under ``stats``,
as a signal about reception, never as a score.

GitHub's public API allows 60 unauthenticated requests an hour per address, so
each run looks up at most ``MAX_LOOKUPS_PER_RUN`` repositories and never the
same one twice. A failed lookup leaves the item as it was.
"""

from __future__ import annotations

import dataclasses
import re

from .base import HTTP, Item, SourceError

API = "https://api.github.com/repos"
MAX_LOOKUPS_PER_RUN = 30
_REPO = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
# Paths under github.com that are not owners.
_NOT_OWNERS = frozenset({"about", "features", "orgs", "settings", "sponsors", "topics",
                         "marketplace", "collections", "trending", "search", "login"})


def repository(url: str | None) -> tuple[str, str] | None:
    """(owner, repo) for a URL inside a GitHub repository, else None."""
    m = _REPO.match(url or "")
    if not m or m.group(1).lower() in _NOT_OWNERS:
        return None
    return m.group(1), m.group(2).removesuffix(".git")


class RepoStats:
    """Looks up repositories for one ingest run: cached, and capped."""

    def __init__(self, http: HTTP, max_lookups: int = MAX_LOOKUPS_PER_RUN) -> None:
        self.http = http
        self.max_lookups = max_lookups
        self._cache: dict[tuple[str, str], dict | None] = {}

    def stats(self, owner: str, repo: str) -> dict | None:
        key = (owner.lower(), repo.lower())
        if key in self._cache:
            return self._cache[key]
        if len(self._cache) >= self.max_lookups:
            return None
        try:
            data = self.http.get_json(f"{API}/{owner}/{repo}")
        except SourceError:
            data = None
        result = None
        if isinstance(data, dict) and isinstance(data.get("stargazers_count"), int):
            result = {
                "stars": data["stargazers_count"],
                "forks": data.get("forks_count"),
                "last_push": (data.get("pushed_at") or "")[:10] or None,
                "archived": bool(data.get("archived")),
            }
        self._cache[key] = result
        return result

    def enrich(self, item: Item) -> Item:
        """``item`` with its repository's numbers under ``meta['github']``, if any."""
        found = repository(item.link) or repository(item.url)
        if found is None:
            return item
        stats = self.stats(*found)
        if stats is None:
            return item
        return dataclasses.replace(item, meta={**item.meta, "github": stats})
