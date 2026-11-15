"""Feedback: an issue on Kranto's release repository, filed as the person who writes it (FB).

The page's Feedback sheet writes the issue (the kind, the person's words, and the details it
showed them, scrubbed in the page); this module answers the two things only the machine
knows, and files.

``status``: where it goes (``feedback.repo``, ``iddv/kranto`` by default) and how:
``ready`` when the person's own ``gh`` is installed, logged in and reaches that repository
(File it), else ``missing``, ``signed_out`` or ``no_access`` (Open on GitHub: the browser's
prefilled new-issue page, submitted by the person). ``reachable``: whether GitHub answers
from this machine at all (no network: the page says so and keeps the draft). It also gives
the page what its scrub needs to know about this machine (the paths that become ``<home>``
and the like, the host name, the login), which the page already shows elsewhere.

``file``: the issue, through ``gh api`` as the login ``gh`` has. Never Kranto's GitHub App,
never a token file, never a relay: the issue is the person's. What is filed is what the
page's confirm showed: the title and the body are scrubbed again here (``kranto.page.report``),
and when that scrub would change a word, nothing is filed and the scrubbed text goes back to
the page, which shows it in a new confirm. Labels: ``feedback`` and the kind, those of them
the repository has (GitHub drops labels a person without push access sets; the body names
the kind either way). No model call.
"""
from __future__ import annotations

import re
import socket
import threading
import time

from .gh import Gh, PublishError
from .settings.write import REPO_NAME
from .upstream import REPOS

# Kranto's release repository, where updates come from (the watcher's)
DEFAULT_REPO = REPOS["watcher"]
KINDS = {"bug": "Bug", "idea": "Idea", "question": "Question"}
LABEL = "feedback"
MAX_TITLE = 120
MAX_BODY = 60000
CACHE_S = 300
# what gh says when GitHub cannot be reached at all (no network, no DNS, a proxy refusing)
OFFLINE = re.compile(r"(?i)error connecting|could not resolve|no such host|network is "
                     r"unreachable|connection refused|timed? ?out|dial tcp|temporary failure")


class FeedbackError(RuntimeError):
    """Nothing was filed; the message says why, in words the page shows."""

    def __init__(self, message: str, status: int = 409, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def repo_of(cfg) -> str:
    """``feedback.repo`` when it is an owner/name, else Kranto's release repository."""
    try:
        r = str(((cfg.get("feedback") if cfg is not None else None) or {}).get("repo") or "")
    except AttributeError:
        r = ""
    return r if REPO_NAME.fullmatch(r) else DEFAULT_REPO


def reachable(host: str = "github.com", port: int = 443, timeout: float = 3.0,
              connect=socket.create_connection) -> bool:
    """Whether a connection to GitHub opens from this machine (one TCP connect, nothing
    sent)."""
    try:
        connect((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


class GitHubError(RuntimeError):
    """``gh api`` said no (moved here from the factory's ``maintain.github``, CUT)."""


_TOKEN_SHAPES = re.compile(r"\b(gh[pousr]_[A-Za-z0-9_.-]{16,}|github_pat_[A-Za-z0-9_]{20,})")


def _clean(text: str, limit: int = 300) -> str:
    """An error line safe to show: anything token-, key- or JWT-shaped removed."""
    s = " ".join(str(text or "").split())
    s = re.sub(r"-----BEGIN[^-]*-----.*?-----END[^-]*-----", "[key]", s)
    s = re.sub(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", "[jwt]", s)
    return _TOKEN_SHAPES.sub("[token]", s)[:limit]


def _gh_api(gh: Gh, path: str, *, payload: dict | None = None, paginate: bool = False) -> str:
    """One ``gh api`` call as the person's login: a GET, or a POST of ``payload``."""
    import json
    import os
    import tempfile
    args = ["api"] + (["-X", "POST"] if payload is not None else []) + \
        (["--paginate"] if paginate else [])
    tmp = None
    if payload is not None:
        fd, tmp = tempfile.mkstemp(prefix="kranto-gh-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        args += ["--input", tmp]
    try:
        code, out, err = gh._run([*args, path], None)
    finally:
        if tmp:
            os.unlink(tmp)
    if code != 0:
        raise GitHubError(f"gh api {'POST' if payload is not None else 'GET'} "
                          f"{path.split('?')[0]}: {(err or out or '').strip()[:300]}")
    return out


def _create_issue(gh: Gh, repo: str, title: str, body: str, labels) -> dict:
    import json
    r = json.loads(_gh_api(gh, f"repos/{repo}/issues", payload={
        "title": title, "body": body, "labels": list(labels)}) or "{}")
    return {"number": r.get("number"), "url": r.get("html_url")}


def probe(gh: Gh, repo: str) -> dict:
    """``{"gh", "login", "offline"}``: what the person's ``gh`` can do with ``repo``. Two
    reads: the login, then the repository (a 404 is no access; GitHub hides private
    repositories from those who cannot see them)."""
    try:
        code, out, err = gh._run(["api", "user", "-q", ".login"], None)
    except (OSError, ValueError):                 # gh is not installed (or not runnable)
        return {"gh": "missing", "login": None, "offline": False}
    if code != 0:
        if OFFLINE.search(err or out or ""):
            return {"gh": "unknown", "login": None, "offline": True}
        return {"gh": "signed_out", "login": None, "offline": False}
    login = (out or "").strip() or None
    code, out, err = gh._run(["api", f"repos/{repo}", "-q", ".has_issues"], None)
    if code != 0:
        if OFFLINE.search(err or out or ""):
            return {"gh": "unknown", "login": login, "offline": True}
        return {"gh": "no_access", "login": login, "offline": False}
    if (out or "").strip() != "true":
        return {"gh": "no_access", "login": login, "offline": False}
    return {"gh": "ready", "login": login, "offline": False}


LINES = {
    "ready": "File it files the issue on {repo} as {login}, through your gh, after you read it.",
    "missing": "gh is not installed here, so Open on GitHub opens GitHub's new-issue page with "
               "everything filled in; you click Submit there.",
    "signed_out": "Your gh is not logged in (gh auth login), so Open on GitHub opens GitHub's "
                  "new-issue page with everything filled in; you click Submit there.",
    "no_access": "Your gh ({login}) cannot open issues on {repo}, so Open on GitHub opens "
                 "GitHub's new-issue page; you click Submit there, signed in to GitHub.",
    "offline": "GitHub can't be reached from this machine right now. Your draft is kept: send "
               "it when you are back online.",
}

_lock = threading.Lock()
_cache: dict = {}


def status(cfg, *, gh: Gh | None = None, reach=None, fresh: bool = False,
           now=time.monotonic) -> dict:
    """What the sheet shows about where its issue goes (cached ``CACHE_S``; ``fresh`` past
    it). Never a token: a login, a repository, words."""
    from . import __version__
    from .report import places
    reach = reach or reachable
    repo = repo_of(cfg)
    key = repo
    with _lock:
        hit = _cache.get(key)
        if hit and not fresh and now() - hit[0] < CACHE_S:
            out = dict(hit[1])
        else:
            out = None
    if out is None:
        online = reach()
        p = probe(gh or Gh(), repo) if online else {"gh": "unknown", "login": None,
                                                    "offline": True}
        online = online and not p["offline"]
        state = p["gh"]
        line = LINES["offline" if not online else state if state in LINES else "missing"]
        out = {"repo": repo, "gh": state, "login": p["login"], "reachable": online,
               "can_file": online and state == "ready",
               "line": line.format(repo=repo, login=p["login"] or "you")}
        with _lock:
            _cache[key] = (now(), dict(out))
    out["kinds"] = [{"id": k, "word": w} for k, w in KINDS.items()]
    out["labels"] = [LABEL]
    out["version"] = __version__
    out["places"] = [[path, label] for path, label in places(cfg)]
    out["host"] = socket.gethostname()
    return out


def forget() -> None:
    """The next status reads afresh (after a filing, and in tests)."""
    with _lock:
        _cache.clear()


def checked(title, body, kind) -> tuple[str, str, str]:
    """The request's title, body and kind, or ``FeedbackError`` (400) saying what is wrong."""
    if kind not in KINDS:
        raise FeedbackError("kind is one of " + ", ".join(KINDS), 400)
    if not isinstance(title, str) or not title.strip():
        raise FeedbackError("the issue needs a title: a few words of what happened", 400)
    if not isinstance(body, str) or not body.strip():
        raise FeedbackError("the issue needs a body: what happened, or what you would like",
                            400)
    title = " ".join(title.split())
    if len(title) > MAX_TITLE:
        raise FeedbackError(f"the title is at most {MAX_TITLE} characters", 400)
    if len(body) > MAX_BODY:
        raise FeedbackError(f"the body is at most {MAX_BODY:,} characters", 400)
    return title, body, kind


def file(cfg, title, body, kind, *, gh: Gh | None = None, login: str | None = None) -> dict:
    """File the issue as ``gh``'s login: ``{"repo", "number", "url", "labels", "dropped"}``.
    ``FeedbackError`` when nothing was filed: 400 a bad request, 409 the scrub found more
    (``title``, ``body`` in its extra: what it would file), 503 GitHub can't be reached."""
    from . import report
    title, body, kind = checked(title, body, kind)
    gh = gh or Gh()
    repo = repo_of(cfg)
    try:
        t2 = report.scrub(title, cfg, login)
        b2 = report.scrub(body, cfg, login)
    except report.ReportError as e:
        raise FeedbackError(str(e) + "; nothing was filed", 500) from None
    if t2 != title or b2 != body:
        raise FeedbackError("Kranto found more to remove before filing (a path, a token, a "
                            "name): read the issue again as it would be filed.", 409,
                            title=t2, body=b2)
    want = [LABEL, kind]
    try:
        names = _gh_api(gh, f"repos/{repo}/labels?per_page=100", paginate=True)
        have = set(re.findall(r'"name":\s*"((?:[^"\\]|\\.)*)"', names))
    except (GitHubError, PublishError, OSError) as e:
        if OFFLINE.search(str(e)):
            raise FeedbackError(LINES["offline"], 503) from None
        have = set()
    labels = [x for x in want if x in have]
    try:
        r = _create_issue(gh, repo, title, body, labels)
    except (GitHubError, PublishError, OSError) as e:
        if OFFLINE.search(str(e)):
            raise FeedbackError(LINES["offline"], 503) from None
        raise FeedbackError(f"GitHub did not take the issue: {_clean(str(e))}. Your draft is "
                            "kept; Open on GitHub sends it from the browser instead.",
                            502) from None
    if not r.get("number") or not r.get("url"):
        raise FeedbackError("GitHub's answer named no issue; your draft is kept.", 502)
    forget()
    return {"repo": repo, "number": r["number"], "url": r["url"], "labels": labels,
            "dropped": [x for x in want if x not in labels]}
