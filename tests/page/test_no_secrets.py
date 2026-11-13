"""The repo itself passes the secret scan (``term.text``'s patterns, the old pre-push scan's): no
token shapes, no random values assigned to secret names, no key, env or database files. Test
secrets are built at runtime (GitGuardian watches the repo; a fake key is still a literal it flags).

Every tracked file is checked, including tests/page/fixtures/ and scripts/; untracked files (a local
.env, workspaces) are not the repo's."""
import shutil
import subprocess
from pathlib import Path

import pytest

from kranto.page.term import text as scan

ROOT = Path(__file__).resolve().parents[2]
LOCKFILES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
MAX_BYTES = 1_000_000


def tracked() -> list[str]:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def test_no_key_env_or_database_files_are_tracked():
    bad = [rel for rel in tracked() for kind, pat, ok in scan.BAD_FILES
           if pat.search(Path(rel).name) and not (ok and ok.search(Path(rel).name))]
    assert bad == []


def test_tracked_files_have_no_secret_shaped_values():
    hits = []
    for rel in tracked():
        p = ROOT / rel
        if (not p.is_file() or p.is_symlink() or p.name in LOCKFILES
                or p.stat().st_size > MAX_BYTES):
            continue
        raw = p.read_bytes()
        if b"\0" in raw[:8192]:
            continue                                   # binary
        hits += [f"{rel}:{n}" for n in sorted(scan.secret_lines(
            raw.decode("utf-8", errors="replace")))]
    assert hits == [], "\n".join(hits)
