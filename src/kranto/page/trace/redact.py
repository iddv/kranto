"""Redact on read: every string a trace returns passes through here; the
files are never changed.

Four rules, at token level (never whole lines: one key in a 200-line test output blanks one
key, not the output):

1. **Secret-shaped strings**: the shapes ``report.py``, the server's ``scrub`` and the pre-push
   scan (``loop/secrets.py``) know (keys, tokens, private key blocks, JWTs, ``Bearer`` and
   ``Authorization:`` values, URL user info, token query parameters), e-mail addresses and
   phone numbers, and a high-entropy value after a secret-sounding name. Each becomes
   ``[redacted: <kind>]``.
2. **Environment values**: the value of every variable in Kranto's own environment whose name
   sounds secret (token, secret, key, password, credential, auth) and is 12 characters or
   more, matched as written, URL-encoded and base64-encoded. Compared, never printed.
3. **Known token paths**: what a tool read from or wrote to a credentials file (Kranto's tokens,
   a broker's keys, gh's and ssh's folders, Claude's credentials, ``.env`` files, keys and
   certificates, ``/proc/*/environ``) is replaced whole: ``[redacted: the contents of
   <name>]``, whatever it looks like.
4. **Personal data**, only when sharing (``share=True``: the CLI's ``--share``, an export):
   the host name, the login and the home path become ``<host>``, ``<you>`` and ``~``, and
   ``@handles`` become ``[user]``. The page keeps real paths: the owner reads their own
   machine.

The kinds that fired are counted (``Counter``), never the values. A ``@handle`` is not
redacted in the page: in code it is a decorator (``@dataclass``), and a trace is mostly code.
"""
from __future__ import annotations

import base64
import math
import os
import re
import socket
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from kranto import legacy

ENV_NAME = re.compile(r"(?i)token|secret|key|password|passwd|credential|auth")
ENV_MIN = 12

_SHAPES: list[tuple[str, re.Pattern, int]] = [
    # (kind, pattern, the group to replace: 0 is the whole match)
    ("private key", re.compile(
        r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----(?:.{0,20000}?-----END [A-Z ]{0,20}PRIVATE "
        r"KEY-----|.{0,20000})", re.S), 0),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), 0),
    ("API key", re.compile(r"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{20,}"), 0),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{20,})"),
     0),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), 0),
    ("AWS key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("Google key", re.compile(r"\b(?:AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])|"
                              r"ya29\.[A-Za-z0-9_-]{20,})"), 0),
    ("Stripe key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}"), 0),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), 0),
    ("authorization header", re.compile(
        r"(?i)\b(?:authorization|dpop)\s*[:=]\s*(?:bearer|basic|token|dpop)?\s*"
        r"([A-Za-z0-9._~+/=-]{12,})"), 1),
    ("bearer token", re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{16,})"), 1),
    ("URL credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://([^/\s:@'\"]+:[^/\s@'\"]+)@"), 1),
    ("token parameter", re.compile(
        r"(?i)\b(?:client_secret|access_token|refresh_token|code_verifier|app_password|"
        r"device_code|api_key|apikey)=([^&\s\"'()\[\]]{6,})(?=[&\s\"'#]|$)"), 1),
]
_NAMED = re.compile(
    r"(?i)(?<![A-Za-z])(?:token|secret|password|passwd|api[_-]?key|client[_-]?secret|private[_-]?key)"
    r"\w*[\"']?\s*[:=]\s*[\"']?([^\s\"',;]{16,})")
_EMAIL = re.compile(r"(?<![\w.%+-])(?!git@)[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}"
                    r"\.[A-Za-z]{2,24}\b")
_PHONE = re.compile(
    r"(?<![\w.:/-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}"
    r"(?![\w.:/-])|(?<![\w.])\+\d{9,14}(?![\w.])|"
    r"(?<![\w.:/+-])\+\d{1,3}[ .-]\d{2,5}[ .-]\d{4,8}(?![\w.:/-])")
_USER = re.compile(r"(?<![\w/`])@[A-Za-z0-9_][A-Za-z0-9_.-]{1,30}[A-Za-z0-9_](?![\w.-]*/)(?!\w)")
_HOME_ANY = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")
_REDACTED = re.compile(r"\[redacted: [^\]]{1,60}\]")
ENTROPY_MIN = 3.5

# rule 3: paths whose contents are never shown
_SECRET_DIRS = (*(f"~/.config/{d.name}/{s}" for d in legacy.config_dirs()
                  for s in ("tokens", "brokers")), "~/.config/gh", "~/.ssh")
_SECRET_FILES = ("~/.claude/.credentials.json",)
_SECRET_NAME = re.compile(r"(?i)^(?:\.env(?:\..*)?|.*\.pem|.*\.key|id_(?:rsa|dsa|ecdsa|ed25519)|"
                          r".*credentials.*|\.netrc|\.pypirc)$")
_PROC_ENV = re.compile(r"^/proc/[^/]+/environ$")


def entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def _env_values(env) -> list[tuple[str, str]]:
    """``(the text to find, kind)`` for each secret-sounding variable's value."""
    out: dict[str, str] = {}
    for name, value in (env or {}).items():
        if not value or len(value) < ENV_MIN or not ENV_NAME.search(name):
            continue
        if value.startswith("/") and "/" in value[1:] and " " not in value:
            continue                       # a path (a socket, a file): nothing to hide
        out[value] = "environment value"
        q = quote(value, safe="")
        if q != value:
            out[q] = "environment value"
        try:
            out[base64.b64encode(value.encode()).decode().rstrip("=")] = "environment value"
        except ValueError:
            pass
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


class Redactor:
    """``text(s)`` and ``value(obj)`` return the redacted copy and count what fired in
    ``self.counts``. ``env``: the environment whose secret values are hidden (default:
    this process's); ``home``: the home whose ``~/…`` token paths count (default: the
    user's); ``kranto_home``: the kranto home (its ``.env`` and ``data/secrets``)."""

    def __init__(self, env=None, home: str | Path | None = None,
                 kranto_home: str | Path | None = None, share: bool = False,
                 login: str | None = None, host: str | None = None):
        self.env = _env_values(os.environ if env is None else env)
        self.home = str(Path(home) if home is not None else Path.home())
        bh = kranto_home if kranto_home is not None else os.environ.get("KRANTO_HOME")
        self.kranto_home = str(Path(bh).expanduser()) if bh else None
        self.share = share
        self.login = login if login is not None else (os.environ.get("USER") or "")
        self.host = host if host is not None else _hostname()
        self.counts: Counter = Counter()

    # -- rule 3 -----------------------------------------------------------------------------
    def secret_path(self, p) -> bool:
        """A path whose contents a trace never shows."""
        s = str(p or "").strip().strip("'\"")
        if not s:
            return False
        if s.startswith("~/"):
            s = self.home + s[1:]
        s = os.path.normpath(s)
        if _PROC_ENV.match(s):
            return True
        for d in _SECRET_DIRS:
            full = self.home + d[1:]
            if s == full or s.startswith(full + "/"):
                return True
        if any(s == self.home + f[1:] for f in _SECRET_FILES):
            return True
        if self.kranto_home and (s == os.path.join(self.kranto_home, ".env") or s.startswith(
                os.path.join(self.kranto_home, "data", "secrets") + "/")):
            return True
        return bool(_SECRET_NAME.match(os.path.basename(s)))

    def secret_paths_in(self, command: str) -> list[str]:
        """The secret paths a shell command names (any word of it)."""
        out = []
        for w in re.split(r"[\s;|&<>()=]+", str(command or "")):
            w = w.strip("'\"")
            if ("/" in w or w.startswith(".")) and self.secret_path(w):
                out.append(w)
        return out

    def contents_of(self, path: str) -> str:
        self.counts["token file"] += 1
        return f"[redacted: the contents of {os.path.basename(str(path).rstrip('/')) or path}]"

    # -- rules 1, 2 and 4 -------------------------------------------------------------------
    def text(self, s) -> str:
        if not isinstance(s, str) or not s:
            return s
        out = s
        for value, kind in self.env:
            if value in out:
                self.counts[kind] += out.count(value)
                out = out.replace(value, f"[redacted: {kind}]")
        for kind, pat, group in _SHAPES:
            out = self._sub(pat, out, kind, group)
        out = _NAMED.sub(self._named, out)
        out = self._sub(_EMAIL, out, "email", 0)
        out = self._sub(_PHONE, out, "phone", 0)
        if self.share:
            out = self._personal(out)
        return out

    def _sub(self, pat: re.Pattern, s: str, kind: str, group: int) -> str:
        def rep(m: re.Match) -> str:
            whole = m.group(0)
            if _REDACTED.fullmatch(whole):
                return whole
            self.counts[kind] += 1
            if group == 0:
                return f"[redacted: {kind}]"
            a, b = m.span(group)
            base = m.start(0)
            return whole[:a - base] + f"[redacted: {kind}]" + whole[b - base:]
        return pat.sub(rep, s)

    def _named(self, m: re.Match) -> str:
        v = m.group(1)
        classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
        if v.startswith(("[redacted", "/", "~", "./", "$", "{", "(", "<")) or classes < 2 \
                or entropy(v) < ENTROPY_MIN:
            return m.group(0)                  # a path, a placeholder, a word: not a secret
        self.counts["secret value"] += 1
        a, b = m.span(1)
        base = m.start(0)
        whole = m.group(0)
        return whole[:a - base] + "[redacted: secret value]" + whole[b - base:]

    def _personal(self, s: str) -> str:
        out = _USER.sub("[user]", s)
        if self.home and self.home != "/":
            out = out.replace(self.home, "~")
            out = out.replace(re.sub(r"[^A-Za-z0-9]", "-", self.home), "-~")  # a project key
        out = _HOME_ANY.sub("~", out)
        if self.host and len(self.host) > 2:
            out = re.sub(r"(?<![\w.-])" + re.escape(self.host) + r"(?![\w-])", "<host>", out)
        if self.login and len(self.login) > 1:
            out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(self.login) + r"(?![A-Za-z0-9])",
                         "<you>", out)
        return out

    def value(self, v):
        """``v`` with every string in it redacted (dicts, lists, keys kept)."""
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, dict):
            return {k: self.value(x) for k, x in v.items()}
        if isinstance(v, list):
            return [self.value(x) for x in v]
        return v

    def report(self) -> list[dict]:
        """``[{kind, n}]``, most first."""
        return [{"kind": k, "n": n} for k, n in self.counts.most_common()]


def _hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def redact(s: str, **kw) -> tuple[str, list[dict]]:
    """One string, with a fresh ``Redactor``: ``(text, [{kind, n}])``."""
    r = Redactor(**kw)
    return r.text(s), r.report()
