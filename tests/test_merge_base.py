"""scripts/ci/merge_base.sh: merging the base in makes the usage reports' field page again
instead of stopping on its conflict, and stops on any other conflict. Local repositories only."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "merge_base.sh"
PAGE = "docs/privacy/what-kranto-sends.md"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout


def write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


@pytest.fixture
def clone(tmp_path):
    """A PR branch whose page and the base's page changed the same line."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "oss", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "checkout", "-q", "-b", "oss")
    write(work, PAGE, "fields: a\n")
    write(work, "README.md", "hello\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "base")
    git(work, "push", "-q", "origin", "oss")
    git(work, "checkout", "-q", "-b", "pr")
    write(work, PAGE, "fields: a, pr\n")
    git(work, "commit", "-q", "-am", "pr adds a field")
    git(work, "checkout", "-q", "oss")
    write(work, PAGE, "fields: a, other\n")
    git(work, "commit", "-q", "-am", "another PR merged first")
    git(work, "push", "-q", "origin", "oss")
    git(work, "checkout", "-q", "pr")
    return work


def run(work: Path, regen: str = "printf 'fields: a, other, pr\\n'") -> subprocess.CompletedProcess:
    env = {**os.environ, "REGEN_PAGE": regen, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["bash", str(SCRIPT), "oss"], cwd=work, env=env, capture_output=True,
                          text=True, check=False)


def test_a_conflict_only_in_the_page_is_made_again_and_merged(clone):
    got = run(clone)
    assert got.returncode == 0, got.stderr
    assert (clone / PAGE).read_text() == "fields: a, other, pr\n"
    parents = git(clone, "log", "-1", "--format=%P").split()
    assert len(parents) == 2                                     # a merge, never a rebase
    assert git(clone, "status", "--porcelain") == ""


def test_any_other_conflict_stops_with_the_merge_open(clone):
    write(clone, "README.md", "mine\n")
    git(clone, "commit", "-q", "-am", "pr edits the readme")
    git(clone, "checkout", "-q", "oss")
    write(clone, "README.md", "theirs\n")
    git(clone, "commit", "-q", "-am", "base edits the readme")
    git(clone, "push", "-q", "origin", "oss")
    git(clone, "checkout", "-q", "pr")
    got = run(clone)
    assert got.returncode == 1 and "README.md conflicts" in got.stderr
    assert "README.md" in git(clone, "diff", "--name-only", "--diff-filter=U")


def test_nothing_to_settle_is_a_plain_merge(clone):
    git(clone, "checkout", "-q", "-b", "quiet", "origin/oss")
    write(clone, "other.txt", "x\n")
    git(clone, "add", ".")
    git(clone, "commit", "-q", "-m", "unrelated")
    got = run(clone, regen="false")
    assert got.returncode == 0 and "merged" in got.stdout


def test_the_page_in_the_tree_is_the_generators():
    from kranto.telemetry import docs
    assert (ROOT / PAGE).read_text() == docs.page(), (
        "run: scripts/dev/telemetry_lists.py (or merge_base.sh after merging the base in)")
