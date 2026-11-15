"""The gitleaks job fails on a tool-attribution line in a pull request's commits, title or body
(scripts/ci/no_attribution.py; the owner's rule). The repo is a throwaway git repository; the
planted lines are built at run time so this file carries none."""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "ci" / "no_attribution.py"
spec = importlib.util.spec_from_file_location("ci_no_attribution", SCRIPT)
noattr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(noattr)

TRAILER = "Co-" + "Authored-By: " + "Claude Opus 5.5 <noreply@" + "anthropic.com>"
FOOTER = "Generated " + "with [" + "Claude Code](https://claude.com/claude-code)"
SESSION = "Claude" + "-Session: https://example.invalid/s/1"


def git(repo: Path, *args: str, date: str = "2026-10-20T08:00:00Z") -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit(repo: Path, msg: str, **kw) -> str:
    git(repo, "commit", "-q", "--allow-empty", "-m", msg, **kw)
    return git(repo, "rev-parse", "HEAD")


def repo_(tmp_path: Path) -> tuple[Path, str]:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path, commit(tmp_path, "base")


def test_a_planted_trailer_in_the_range_fails_and_names_the_commit(tmp_path, capsys):
    repo, base = repo_(tmp_path)
    commit(repo, "a clean change")
    bad = commit(repo, f"a change\n\n{TRAILER}\n")
    assert noattr.main([f"{base}..{bad}"], env={}, cwd=str(repo)) == 1
    out = capsys.readouterr().out
    assert f"attribution line in {bad[:7]}" in out and "Authored-By" in out


def test_each_kind_of_line_is_caught_in_any_case(tmp_path):
    for line in (TRAILER, TRAILER.lower(), FOOTER, SESSION):
        assert noattr.hits(f"subject\n\nbody\n{line}\n") == [line]
    assert noattr.hits("Co-authored-by: a person <p@example.invalid>\nclaude is a name") == []


def test_a_clean_range_passes(tmp_path, capsys):
    repo, base = repo_(tmp_path)
    head = commit(repo, "a clean change\n\nCo-authored-by: a person <p@example.invalid>")
    assert noattr.main([f"{base}..{head}"], env={"PR_TITLE": "t", "PR_BODY": "b"},
                       cwd=str(repo)) == 0
    assert "no attribution lines in 1 commit(s) and the pull request" in capsys.readouterr().out


def test_the_pull_requests_title_and_body_are_checked(tmp_path):
    repo, base = repo_(tmp_path)
    head = commit(repo, "clean")
    assert noattr.main([f"{base}..{head}"], env={"PR_BODY": f"what\n\n{FOOTER}"},
                       cwd=str(repo)) == 1


def test_all_skips_the_history_before_the_rule_was_checked(tmp_path):
    repo, _ = repo_(tmp_path)
    commit(repo, f"old\n\n{TRAILER}", date="2026-09-27T10:00:00Z")
    assert noattr.main(["--all"], env={}, cwd=str(repo)) == 0
    commit(repo, f"new\n\n{TRAILER}")
    assert noattr.main(["--all"], env={}, cwd=str(repo)) == 1


def test_the_gitleaks_job_runs_the_check_on_the_pull_requests_range():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    job = wf["jobs"]["gitleaks"]
    step = next(s for s in job["steps"] if "no_attribution.py" in s.get("run", ""))
    rng = next(s for s in job["steps"] if s.get("id") == "range")
    assert 'range="$PR_BASE..$PR_HEAD"' in rng["run"]
    assert "${{ steps.range.outputs.range }}" in step["run"]
    assert step["env"]["PR_TITLE"] == "${{ github.event.pull_request.title }}"
    assert step["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}"
    assert job["steps"][0]["with"]["fetch-depth"] == 0
