"""Text a session is given: every outside text fenced as data (``fence``), the secret scan over
it (``redact``: a hit line becomes ``[redacted]``), and a folder copied without what must not
reach a session (``copy_out``: no .git, venvs, caches, big or secret-shaped files; text through
the scan).

Moved from ``chat/context.py`` (``fence``, ``redact``, ``copy_out``); the scan's patterns are
the pre-push scan's (``loop/secrets.py``: known token shapes, a long random value assigned to a
secret-sounding name, files that never belong in a repo), copied so the console needs nothing
of the build loop."""
from __future__ import annotations

import math
import os
import re
import shutil
from pathlib import Path

OUT_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", ".den", "dist", "build", ".tox"}
MAX_FILE = 1_000_000

# -- the secret scan (loop/secrets.py's patterns) -------------------------------------------------
BAD_FILES = [
    ("env file", re.compile(r"^\.env(\.[\w-]+)?$"), re.compile(r"\.(example|sample|template|dist)$")),
    ("private key file", re.compile(r"(^id_(rsa|dsa|ecdsa|ed25519)$|\.(pem|key|p12|pfx|jks|keystore)$)"), None),
    ("credentials file", re.compile(r"^(\.netrc|\.pypirc|\.npmrc|credentials(\.json)?|"
                                    r"service[-_]account.*\.json|client_secret.*\.json)$"), None),
    ("database file", re.compile(r"\.(db|sqlite|sqlite3|db-wal|db-shm)$"), None),
]
TOKENS = [
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]
NAMED = re.compile(r"""(?ix)
    (?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|
       client[_-]?secret|auth[_-]?key|credential)s?\w*
    ["']?\s*[:=]\s*[rbuf]?["']([^"'\s]{20,})["']""")
PLACEHOLDER = re.compile(r"(?i)example|changeme|change-me|your[_-]|xxxx|placeholder|dummy|"
                         r"\$\{|\{\{|<[^>]+>|not[_-]?a[_-]?secret|redacted|0123456789")
ALLOW = "pragma: allowlist secret"


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def _looks_random(v: str) -> bool:
    classes = sum(bool(re.search(p, v)) for p in (r"[a-z]", r"[A-Z]", r"\d"))
    return len(v) >= 20 and classes >= 2 and _entropy(v) >= 4.0 and not PLACEHOLDER.search(v)


def secret_lines(text: str) -> set[int]:
    """The numbers (from 1) of the lines of ``text`` that hold a secret-shaped value."""
    hits = set()
    for n, line in enumerate(text.splitlines(), 1):
        if ALLOW in line:
            continue
        if any(pat.search(line) for _, pat in TOKENS) or any(
                _looks_random(m.group(1)) for m in NAMED.finditer(line)):
            hits.add(n)
    return hits


# -- what a session reads ------------------------------------------------------------------------
def fence(name: str, text: str) -> str:
    """A document as data. Text that looks like a fence line is defused first, so content
    can never close its own fence."""
    body = (text or "").replace("<<<", "‹‹‹").replace(">>>", "›››").rstrip()
    return f'<<<document name="{name}">>>\n{body}\n<<<end>>>'


def redact(text: str) -> tuple[str, int]:
    hits = secret_lines(text or "")
    if not hits:
        return text, 0
    lines = text.splitlines()
    for n in hits:
        lines[n - 1] = "[redacted]"
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), len(hits)


def _skip(rel: tuple[str, ...], p: Path) -> bool:
    if any(part in OUT_SKIP_DIRS for part in rel[:-1]):
        return True
    return any(pat.search(p.name) and not (ok and ok.search(p.name)) for _, pat, ok in BAD_FILES)


def out_files(o: Path) -> list[Path]:
    keep = []
    for root, dirs, names in os.walk(o):
        dirs[:] = sorted(x for x in dirs if x not in OUT_SKIP_DIRS)
        for n in sorted(names):
            p = Path(root) / n
            rel = p.relative_to(o).parts
            if p.is_symlink() or _skip(rel, p):
                continue
            try:
                if p.stat().st_size > MAX_FILE:
                    continue
            except OSError:
                continue
            keep.append(p)
    return keep


def copy_out(o: Path, dest: Path) -> int:
    """Copy a folder into the session's (no .git, venvs, caches, big or secret-shaped files);
    text files go through the secret scan. Returns redacted lines."""
    if dest.exists():
        shutil.rmtree(dest)
    n = 0
    for p in out_files(o):
        t = dest / p.relative_to(o)
        t.parent.mkdir(parents=True, exist_ok=True)
        raw = p.read_bytes()
        if b"\0" in raw[:8192]:
            t.write_bytes(raw)
            continue
        text, k = redact(raw.decode("utf-8", errors="replace"))
        n += k
        t.write_text(text)
    return n
