"""The repo holds no secret-shaped values and no key, env or database files.

Test secrets are built at runtime (tests/test_scrub.py): GitGuardian and gitleaks watch the
repo, and a fake key written out is still a literal they flag. The token shapes mirror
the page's pre-push scan (src/kranto/page/loop/secrets.py). Only tracked files are checked, so a
local ``.env`` or a workspace in the checkout does not fail the suite.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALLOW = "pragma: allowlist secret"
MAX_BYTES = 2_000_000

TOKENS = [
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("OpenRouter key", re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}")),
    ("OpenAI key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9]{32,}\b")),
    ("xAI key", re.compile(r"\bxai-[A-Za-z0-9]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private key block", re.compile(r"-----BEGIN ([A-Z]+ )?PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
]
BAD_NAMES = re.compile(
    r"(^\.env(\.[\w-]+)?$|^id_(rsa|dsa|ecdsa|ed25519)$|\.(pem|key|p12|pfx|jks|keystore)$"
    r"|^(\.netrc|\.pypirc|\.npmrc)$|\.(db|sqlite|sqlite3|db-wal|db-shm)$)")
GOOD_NAMES = re.compile(r"\.(example|sample|template|dist)$")


def tracked() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def test_no_key_env_or_database_files_are_tracked():
    bad = [p for p in tracked()
           if BAD_NAMES.search(Path(p).name) and not GOOD_NAMES.search(Path(p).name)]
    assert bad == []


def test_tracked_files_have_no_secret_shaped_values():
    hits = []
    for rel in tracked():
        path = ROOT / rel
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BYTES:
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:8192]:
            continue                                   # binary
        for n, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if ALLOW in line:
                continue
            hits += [f"{rel}:{n} {kind}" for kind, pat in TOKENS if pat.search(line)]
    assert hits == [], "\n".join(hits)
