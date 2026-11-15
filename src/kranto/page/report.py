"""The scrub for anything Kranto files on GitHub as the person: the feedback sheet's issue
(``feedback.file``) and the new-issue page it opens instead when ``gh`` cannot file.

``scrub``: (1) the secret scan over whole lines (``term.text.redact``); (2) the patterns
the server's ``scrub`` uses for tokens, keys, e-mail addresses, phone numbers and ``@user``
handles; (3) paths: the home, the kranto home, the loop home and any ``/home/<user>/…`` become
``<home>/…``; (4) the host name and the login become ``<host>`` and ``<you>``. The URL stays
under ``MAX_URL`` characters (browsers and GitHub take about 8,000): the body is cut at a
paragraph boundary with a line saying so."""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path
from urllib.parse import quote

MAX_URL = 6000
CUT_NOTE = "\n\n(the rest is in the copied report)"
# the server/scrub.py's secret, e-mail, phone and user patterns (kept the same by hand)
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----.{0,20000}?-----END [A-Z ]{0,20}"
               r"PRIVATE KEY-----", re.S),
    re.compile(r"\bsk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_-]{20,200}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_.-]{16,4000}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,255}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,2000}\.eyJ[A-Za-z0-9_-]{8,2000}\.[A-Za-z0-9_-]{8,2000}"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,2000}"),
    re.compile(r"(?i)\b(?:authorization|dpop)\s*[:=]\s*(?:bearer|dpop|token)?\s*"
               r"[A-Za-z0-9._~+/=-]{12,4000}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,4000}"),
    re.compile(r"(?i)\b(?:client_secret|access_token|refresh_token|code_verifier|"
               r"app_password|device_code)=[^&\s\"']{6,4000}"),
]
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}")
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?![\w.])"
    r"|(?<![\w.])\+\d{9,14}(?![\w.])")
_USER = re.compile(r"(?<![\w/`])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}[A-Za-z0-9_](?![\w.-]*/)(?!\w)")
_HOME_ANY = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")


class ReportError(RuntimeError):
    """The report could not be scrubbed, so it is not offered."""


def places(cfg=None) -> list[tuple[str, str]]:
    """The paths that become labels, longest first: the tasks dir (``<tasks>``), the loop
    home (``<loop>``), the kranto home (``<Kranto>``), the home (``<home>``)."""
    out: list[tuple[str, str]] = []

    def add(p, label):
        try:
            s = str(Path(p).expanduser())
        except (TypeError, ValueError):
            return
        if s and s != "/" and (s, label) not in out:
            out.append((s, label))
    if cfg is not None:
        try:
            add(cfg.tasks_dir, "<tasks>")
            add(cfg.home, "<loop>")
        except Exception:                           # noqa: BLE001 - a bare config
            pass
    if os.environ.get("KRANTO_HOME"):
        add(os.environ["KRANTO_HOME"], "<kranto>")
    if os.environ.get("KRANTO_LOOP_HOME"):
        add(os.environ["KRANTO_LOOP_HOME"], "<loop>")
    add(Path.home(), "<home>")
    return sorted(out, key=lambda x: -len(x[0]))


def scrub(text: str, cfg=None, login: str | None = None, host: str | None = None) -> str:
    """``text`` with secrets, personal data, paths, the host and the login replaced."""
    from .term.text import redact
    try:
        out, _ = redact(text or "")
        for pat in _SECRETS:
            out = pat.sub("[secret]", out)
        out = _EMAIL.sub("[email]", out)
        out = _PHONE.sub("[phone]", out)
        out = _USER.sub("[user]", out)
        for path, label in places(cfg):
            out = out.replace(path, label)
        out = _HOME_ANY.sub("<home>", out)
        host = host or socket.gethostname()
        if host and len(host) > 2:
            out = re.sub(r"(?<![\w.-])" + re.escape(host) + r"(?![\w-])", "<host>", out)
        if login and len(login) > 1:
            out = re.sub(r"(?<![\w-])" + re.escape(login) + r"(?![\w-])", "<you>", out)
            out = out.replace(f"{login}[bot]", "<you>[bot]")
        return out
    except Exception as e:                          # noqa: BLE001 - said; nothing is offered
        raise ReportError(f"the report could not be scrubbed ({type(e).__name__})") from None


def scrubber(cfg=None, login: str | None = None, host: str | None = None):
    """A ``text -> text`` for the feedback sheet (``feedback.file``)."""
    return lambda text: scrub(text, cfg, login, host)


def new_issue_url(full: str, title: str, body: str) -> str:
    return (f"https://github.com/{full}/issues/new?title={quote(title, safe='')}"
            f"&body={quote(body, safe='')}")


def fit(full: str, title: str, body: str, limit: int = MAX_URL) -> tuple[str, str, bool]:
    """``(url, the body the url carries, cut)``: the body cut at a paragraph boundary with
    ``CUT_NOTE`` when the URL would pass ``limit``; the dedupe marker (the body's last
    paragraph) is kept whatever is cut."""
    url = new_issue_url(full, title, body)
    if len(url) <= limit:
        return url, body, False
    paras = [p for p in body.split("\n\n")]
    tail = paras[-1] if paras and paras[-1].strip().startswith("<!--") else ""
    head = paras[:-1] if tail else paras
    keep: list[str] = []
    for p in head:
        trial = "\n\n".join([*keep, p]) + CUT_NOTE + ("\n\n" + tail if tail else "")
        if len(new_issue_url(full, title, trial)) > limit:
            break
        keep.append(p)
    if not keep and head:                           # the first paragraph alone is too long
        room = max(200, limit - len(new_issue_url(full, title, CUT_NOTE + "\n\n" + tail)) - 200)
        keep = [head[0][:room // 3]]
    cut_body = "\n\n".join(keep) + CUT_NOTE + ("\n\n" + tail if tail else "")
    url = new_issue_url(full, title, cut_body)
    while len(url) > limit and keep:                # a wide character pushed it over
        keep[-1] = keep[-1][:-100]
        cut_body = "\n\n".join(keep) + CUT_NOTE + ("\n\n" + tail if tail else "")
        url = new_issue_url(full, title, cut_body)
    return url, cut_body, True


def build(full: str, title: str, body: str, cfg=None, login: str | None = None,
          host: str | None = None) -> dict:
    """``{"url", "title", "body" (what the url carries), "text" (all of it), "cut"}``, every
    part scrubbed. ``ReportError`` when the scrub cannot run."""
    title = scrub(" ".join((title or "").split())[:120], cfg, login, host)
    text = scrub(body or "", cfg, login, host)
    url, carried, cut = fit(full, title, text)
    return {"url": url, "title": title, "body": carried, "text": text, "cut": cut, "repo": full}
