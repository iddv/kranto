"""Where updates come from (section 3): the ``Source`` seam.

- ``GitHubReleases``: the releases of one repository (iddv/kranto). Private: ``gh api``,
  so the token stays in gh and never enters this process (``token_env_file`` sets
  ``GH_TOKEN`` for gh's subprocess only). Without gh, or with a gh that is not logged in:
  HTTPS with the cached ``ETag`` (a 304 is the common answer and costs no rate limit), sending
  the token from ``token_env_file`` (Kranto's own GitHub connection) when there is one, so a
  private repo answers, and downloading assets through the API's asset address; anonymous
  when there is none (a public repo).
- ``GitMain``: the ``main`` channel: the head commit of each repo's ``main``.

A ``PyPI`` source (the meta-package as ``kranto==X``) is a later third implementation.
Nothing here calls a model; tests pass a fake ``run`` and ``http_get``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .apply import REPOS, redact, tag_version, verify_set, vkey

NOTE_LINES = 8


class SourceError(Exception):
    """A check or download that did not work (offline, 401, rate limit); already redacted."""


@dataclass
class Release:
    version: str
    tag: str
    published_at: str | None = None
    prerelease: bool = False
    notes_url: str | None = None
    notes: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    commits: dict[str, str] | None = None   # the main channel: each repo's head

    def as_dict(self) -> dict:
        return asdict(self)


class Source(Protocol):
    def latest(self, channel: str, etag: str | None = None) -> tuple[Release | None, str | None]:
        """The newest release on ``channel`` and the response's ETag. Raises SourceError."""

    def download(self, release: Release, dest: Path) -> None: ...

    def verify(self, dest: Path, release: Release) -> None: ...


class NotModified(Exception):
    """The release list has not changed since ``etag`` (HTTP 304)."""


def _run(cmd: list[str], env: dict | None = None, timeout: float = 120) -> \
        subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False,
                          env=env)


def _http_get(url: str, headers: dict, timeout: float = 20) -> tuple[int, dict, bytes]:
    import httpx

    r = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    return r.status_code, dict(r.headers), r.content


def gh_error(text: str | None, limit: int = 200) -> str:
    """gh's stderr as one line a status screen can show: "gh is not logged in (gh auth
    login)" for gh's two-paragraph "To get started with GitHub CLI" text, else the first
    sentence, whitespace folded."""
    s = " ".join(str(text or "").split())
    if "gh auth login" in s and ("To get started" in s or "not logged in" in s.lower()):
        prefix = s.split(":", 1)[0] + ": " if s.startswith("gh ") and ":" in s else ""
        return f"{prefix}gh is not logged in (gh auth login)"
    head = s.split(". ", 1)[0]
    return (head if len(head) <= limit else head[:limit - 1] + "…") or "no answer"


def connection_file() -> str | None:
    """Kranto's own GitHub connection's token file: gone with builds (CUT; the page's
    ``github_user`` left with the repositories it published). Always None: the update source
    uses ``update.token_env_file`` when it names one, else gh's own login, as before the
    connection existed."""
    return None


def token_of(path: str | None) -> str | None:
    """The token in a 0600 ``KEY=VALUE`` file (``GH_TOKEN=`` or ``GITHUB_TOKEN=``), or None
    when no file is named. Raises SourceError for a file that is open to others, unreadable or
    has no token line."""
    if not path:
        return None
    p = Path(path).expanduser()
    try:
        if p.stat().st_mode & 0o077:
            raise SourceError(f"{p} must be readable by you only (chmod 600)")
        lines = p.read_text().splitlines()
    except OSError as exc:
        raise SourceError(f"cannot read update.token_env_file: {exc.strerror}") from exc
    token = None
    for line in lines:
        key, sep, value = line.strip().removeprefix("export ").partition("=")
        if sep and key.strip() in ("GH_TOKEN", "GITHUB_TOKEN"):
            token = value.strip().strip("\"'")
    if not token:
        raise SourceError(f"{p} has no GH_TOKEN=")
    return token


def token_env(path: str | None) -> dict | None:
    """The environment for gh with ``GH_TOKEN`` from a 0600 ``KEY=VALUE`` file, or None (gh's
    own login). Only gh's subprocess gets it."""
    token = token_of(path)
    return None if token is None else {**os.environ, "GH_TOKEN": token}


def note_lines(body: str | None, n: int = NOTE_LINES) -> list[str]:
    """The first ``n`` change lines (``- ...``) of a release's notes."""
    return [line.strip() for line in (body or "").splitlines()
            if line.strip().startswith("- ")][:n]


def release_of(r: dict) -> Release:
    return Release(version=tag_version(r["tag_name"]), tag=r["tag_name"],
                   published_at=r.get("published_at"), prerelease=bool(r.get("prerelease")),
                   notes_url=r.get("html_url"), notes=note_lines(r.get("body")),
                   assets=[a.get("name") for a in r.get("assets") or []])


WITHDRAWN = "**Do not install:**"
_STABLE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
_NIGHTLY_TAG = re.compile(r"^v\d+\.\d+\.\d+-dev\d+$")


def channel_of(channel: str | None) -> str:
    """The channel as kranto reads it now: ``rc`` (retired: it meant prereleases too) is
    ``nightly``."""
    return "nightly" if channel == "rc" else str(channel or "stable")


def pick(releases: list[dict], channel: str) -> dict | None:
    """The newest release on ``channel``'s line, by version, not by date:

    - ``stable``: a published non-prerelease ``vX.Y.Z`` (a held candidate is a prerelease
      until it is promoted);
    - ``nightly`` (and the retired ``rc``): a published ``vX.Y.0-devN``, a build from main;
      never a stable release or fix.

    Drafts, other tags and a release withdrawn in its notes (``**Do not install:**``) never
    count."""
    channel = channel_of(channel)
    form = _NIGHTLY_TAG if channel == "nightly" else _STABLE_TAG
    ok = [r for r in releases if not r.get("draft") and form.match(r.get("tag_name") or "")
          and (channel == "nightly" or not r.get("prerelease"))
          and WITHDRAWN not in (r.get("body") or "")]
    return max(ok, key=lambda r: vkey(r["tag_name"]), default=None)


class GitHubReleases:
    def __init__(self, repo: str, *, token_env_file: str | None = None,
                 run: Callable[..., subprocess.CompletedProcess] = _run,
                 http_get: Callable[..., tuple[int, dict, bytes]] = _http_get,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        self.repo = repo
        self.token_env_file = token_env_file
        self.run = run
        self.http_get = http_get
        self.which = which
        self.anonymous = False      # gh said it is not logged in: anonymous HTTPS from then on

    @property
    def use_gh(self) -> bool:
        return bool(self.which("gh")) and not self.anonymous

    def _gh(self, *args: str, timeout: float = 120) -> str:
        env = token_env(self.token_env_file)
        try:
            r = self.run(["gh", *args], env=env, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceError(redact(f"gh {args[0]}: {exc}")) from exc
        if r.returncode != 0:
            raise SourceError(redact(gh_error(f"gh {args[0]}: {r.stderr or r.stdout}")))
        return r.stdout

    def releases(self, etag: str | None = None) -> tuple[list[dict], str | None]:
        if self.use_gh:
            try:
                out = self._gh("api", f"repos/{self.repo}/releases?per_page=100", timeout=60)
                return json.loads(out or "[]"), None
            except SourceError as exc:
                # gh installed but never logged in (most people): a public repo needs no
                # login, so ask GitHub anonymously; a private one answers 404 and says so
                if "gh is not logged in" not in str(exc):
                    raise
                self.anonymous = True
        headers = self._http_headers("application/vnd.github+json")
        if etag:
            headers["If-None-Match"] = etag
        try:
            code, h, body = self.http_get(
                f"https://api.github.com/repos/{self.repo}/releases?per_page=100", headers)
        except Exception as exc:  # noqa: BLE001 - offline, DNS, TLS: one reason line
            raise SourceError(redact(f"{type(exc).__name__}: {exc}")) from exc
        if code == 304:
            raise NotModified()
        if code != 200:
            why = ""
            if code == 404:
                why = (" (Kranto's GitHub login cannot see it)" if "Authorization" in headers
                       else " (a private repo needs a GitHub login)")
            elif code == 401:
                why = " (Kranto's GitHub login no longer works: connect GitHub again)"
            raise SourceError(f"GitHub answered {code} for {self.repo}'s releases{why}")
        return json.loads(body or b"[]"), h.get("etag") or h.get("ETag")

    def _http_headers(self, accept: str) -> dict:
        """Headers for GitHub's API over HTTPS, without gh: the token from ``token_env_file``
        (Kranto's own GitHub connection) when there is one, so a private repo answers; else
        anonymous, which is enough for a public one."""
        headers = {"Accept": accept}
        token = token_of(self.token_env_file)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def latest(self, channel: str, etag: str | None = None):
        rels, new_etag = self.releases(etag)
        r = pick(rels, channel)
        if r is None and channel_of(channel) == "stable":
            # nightlies come several a day, so the last stable can fall off the list's page:
            # GitHub's latest release is always the newest stable
            newest = self.latest_release()
            r = pick([newest], "stable") if isinstance(newest, dict) else None
        return (release_of(r) if r else None), new_etag

    def latest_release(self) -> dict | None:
        """GitHub's ``releases/latest`` (never a prerelease or a draft), or None."""
        path = f"repos/{self.repo}/releases/latest"
        if self.use_gh:
            try:
                return json.loads(self._gh("api", path, timeout=60) or "null")
            except SourceError as exc:
                if "Not Found" in str(exc) or "404" in str(exc):
                    return None
                if "gh is not logged in" not in str(exc):
                    raise
                self.anonymous = True
        try:
            code, _, body = self.http_get(f"https://api.github.com/{path}",
                                          self._http_headers("application/vnd.github+json"))
        except Exception as exc:  # noqa: BLE001 - offline, DNS, TLS: one reason line
            raise SourceError(redact(f"{type(exc).__name__}: {exc}")) from exc
        if code == 404:
            return None
        if code != 200:
            raise SourceError(f"GitHub answered {code} for {self.repo}'s latest release")
        return json.loads(body or b"null")

    def download(self, release: Release, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        if self.use_gh:
            self._gh("release", "download", release.tag, "-R", self.repo, "-p", "*.whl",
                     "-p", "SHA256SUMS", "-p", "manifest.json", "-D", str(dest), "--clobber",
                     timeout=600)
            return
        rels, _ = self.releases()
        r = next((x for x in rels if x.get("tag_name") == release.tag), None)
        if r is None:
            raise SourceError(f"{release.tag} is no longer on {self.repo}")
        for a in r.get("assets") or []:
            name = a.get("name", "")
            if not (name.endswith(".whl") or name in ("SHA256SUMS", "manifest.json")):
                continue
            # the API's asset address answers for a private repo with the token (GitHub
            # redirects to storage; httpx drops the Authorization header on another host);
            # browser_download_url only for a public one without a token
            headers = self._http_headers("application/octet-stream")
            url = a.get("url") if a.get("url") else a["browser_download_url"]
            try:
                code, _, body = self.http_get(url, headers, 300)
            except Exception as exc:  # noqa: BLE001 - offline, DNS, TLS: one reason line
                raise SourceError(redact(f"downloading {name}: {type(exc).__name__}: {exc}")) \
                    from exc
            if code != 200:
                raise SourceError(f"downloading {name}: HTTP {code}")
            (dest / Path(name).name).write_bytes(body)

    def verify(self, dest: Path, release: Release) -> None:
        verify_set(dest, release.version)


class GitMain:
    """The ``main`` channel: each repo's ``main`` head, compared with the installed commits."""

    def __init__(self, repos: dict[str, str] | None = None, *,
                 run: Callable[..., subprocess.CompletedProcess] = _run,
                 token_env_file: str | None = None) -> None:
        self.repos = repos or dict(REPOS)
        self.run = run
        self.token_env_file = token_env_file

    def latest(self, channel: str, etag: str | None = None):
        commits = {}
        for name, repo in self.repos.items():
            try:
                r = self.run(["gh", "api", f"repos/{repo}/commits/main", "--jq", ".sha"],
                             env=token_env(self.token_env_file), timeout=60)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SourceError(redact(f"gh api: {exc}")) from exc
            if r.returncode != 0:
                raise SourceError(redact(gh_error(f"gh api {repo}: {r.stderr or ''}")))
            commits[name] = r.stdout.strip()
        short = "/".join(c[:7] for c in commits.values())
        return Release(version=f"main@{short}", tag="main", commits=commits), None

    def download(self, release: Release, dest: Path) -> None:
        """Nothing to stage: the helper installs the commits from git."""

    def verify(self, dest: Path, release: Release) -> None:
        """Git installs are checked by git (the commit id)."""


def make_source(cfg, **kw) -> Source:
    """The source for ``cfg.update`` (an ``UpdateConfig``)."""
    if cfg.channel == "main" or cfg.source == "git":
        return GitMain(token_env_file=cfg.token_env_file, **{k: v for k, v in kw.items()
                                                             if k == "run"})
    return GitHubReleases(cfg.repo, token_env_file=cfg.token_env_file, **kw)
