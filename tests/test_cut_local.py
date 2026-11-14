"""cut_local.sh: the two lines, a promotion from a nightly build's own commit, a fix from the
stable line's branch, the shape guard, and one cut at a time.

A promotion (``--from-tag vX.Y.0-devN``) checks out the nightly build's tag; what merged after
it is not in it, so main never waits for a promotion. A nightly is cut from main's newest green
commit, a fix (``--line stable``) from release/X.Y's. A local repository stands in for GitHub
(``RELEASE_GIT_BASE``), a fake ``gh`` says every check is green and lists the releases
(``FAKE_RELEASES``), and the cut stops at the shape guard or the build (the repository has no
package), after the commit is chosen."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUT = ROOT / "scripts" / "release" / "cut_local.sh"
NAME = subprocess.run(["python3", str(ROOT / "scripts" / "release" / "names.py"), "dist"],
                      capture_output=True, text=True, check=True).stdout.strip()

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
running = [s for s in os.environ.get("FAKE_RUNNING", "").split(",") if s]
red = [s for s in os.environ.get("FAKE_RED", "").split(",") if s]
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if a[0] == "api" and a[-1].endswith("/status"):
    print(json.dumps({"statuses": []}))
elif a[0] == "api" and "/releases" in a[1]:
    print(os.environ.get("FAKE_RELEASES", "[]"))
elif a[0] == "api" and "/check-runs" in a[-1]:
    busy = any(s in a[-1] for s in running)          # this commit's run is still going
    failed = any(s in a[-1] for s in red)
    print(json.dumps({"check_runs": [{"name": "test", "status": "in_progress" if busy else
                                      "completed", "conclusion": None if busy else
                                      "failure" if failed else "success"}]}))
else:
    sys.exit(f"fake gh: unexpected {a}")
'''


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit(repo: Path, msg: str) -> str:
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def tool(d: Path, name: str, text: str) -> None:
    p = d / name
    p.write_text(text)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def setup(tmp: Path) -> tuple[str, str, dict]:
    """The repository: v0.7.0, then a nightly build (v0.8.0-dev1), then a merge after it."""
    r = tmp / "origin" / "o" / NAME
    r.mkdir(parents=True)
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.name", "t"],
                ["config", "user.email", "t@example.invalid"]):
        git(r, *cmd)
    commit(r, "first")
    git(r, "tag", "-a", "v0.7.0", "-m", "v")
    rc = commit(r, "in the nightly build (#1)")
    git(r, "tag", "-a", "v0.8.0-dev1", "-m", "v")
    head = commit(r, "merged after the nightly build (#2)")
    bin_ = tmp / "bin"
    bin_.mkdir()
    tool(bin_, "gh", FAKE_GH)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
           "REPO": f"o/{NAME}", "RELEASE_GIT_BASE": f"file://{tmp / 'origin'}",
           "RELEASE_LOCK": str(tmp / "lock"), "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig")}
    return rc, head, env


def origin(tmp: Path) -> Path:
    return tmp / "origin" / "o" / NAME


def cut(tmp: Path, env: dict, work: str, *args: str) -> tuple[subprocess.CompletedProcess, Path]:
    w = tmp / work
    r = subprocess.run(["bash", str(CUT), *args], env={**env, "RELEASE_WORK": str(w)},
                       capture_output=True, text=True, timeout=120)
    return r, w


def test_a_promotion_holds_the_nightly_builds_commit_not_mains(tmp_path):
    rc, head, env = setup(tmp_path)
    r, w = cut(tmp_path, env, "promote", "--from-tag", "v0.8.0-dev1")
    assert r.returncode != 0                               # chosen; the guard or build stops
    d = json.loads((w / "decide.json").read_text())
    assert (d["version"], d["tag"], d["kind"], d["branch"]) == ("0.8.0", "v0.8.0", "promotion",
                                                               "release/0.8")
    assert d["held"] and not d["prerelease"] and d["rc_check"]["required"]
    assert d["commit"] == rc
    # a nightly from main's head: the next build toward 0.8.0, with the merge after dev1
    r, w = cut(tmp_path, env, "from-main")
    d = json.loads((w / "decide.json").read_text())
    assert (d["tag"], d["previous"], d["kind"]) == ("v0.8.0-dev2", "v0.8.0-dev1", "nightly")
    assert d["prerelease"] and not d["held"]
    assert d["commit"] == head


def test_a_fix_is_cut_from_the_stable_lines_branch(tmp_path):
    rc, head, env = setup(tmp_path)
    r, _ = cut(tmp_path, env, "no-branch", "--line", "stable")
    assert r.returncode == 2 and "has no release/0.7 yet" in r.stderr
    o = origin(tmp_path)
    git(o, "branch", "release/0.7", "v0.7.0")
    git(o, "checkout", "-q", "release/0.7")
    fix = commit(o, "a cherry-pick (#3)")
    git(o, "checkout", "-q", "main")
    r, w = cut(tmp_path, env, "fix", "--line", "stable")
    d = json.loads((w / "decide.json").read_text())
    assert (d["tag"], d["previous"], d["kind"], d["held"]) == ("v0.7.1", "v0.7.0", "fix", True)
    assert d["commit"] == fix
    assert "release/0.7's newest green commit is" in r.stdout


def test_a_cut_from_main_takes_its_newest_green_commit(tmp_path):
    # 2026-10-17 00:14: main's head pending behind another queued, and so on while merges
    # flowed; a cut from the head would wait for hours
    rc, head, env = setup(tmp_path)
    newest = commit(origin(tmp_path), "another merge (#4)")
    r, w = cut(tmp_path, {**env, "FAKE_RUNNING": newest}, "busy")
    d = json.loads((w / "decide.json").read_text())
    assert d["commit"] == head
    assert "main's newest green commit is" in r.stdout
    # both newer ones still running: the nightly build's own commit, so nothing new to cut
    r, w = cut(tmp_path, {**env, "FAKE_RUNNING": ",".join([newest, head])}, "older")
    assert f"main's newest green commit is {rc[:7]}" in r.stdout
    assert r.returncode == 2 and "an empty release is refused" in r.stderr


def test_from_tag_takes_a_nightly_builds_tag_only_and_rc_is_retired(tmp_path):
    _, _, env = setup(tmp_path)
    for args in (["--from-tag", "v0.7.0"], ["--from-tag", "v0.7.1-rc1"],
                 ["--from-tag", "v0.8.0-dev1", "--line", "stable"]):
        r, _ = cut(tmp_path, env, "bad", *args)
        assert r.returncode == 2 and "--from-tag" in r.stderr, args
    r, _ = cut(tmp_path, env, "missing", "--from-tag", "v0.8.0-dev9")
    assert r.returncode == 2 and "has no tag v0.8.0-dev9" in r.stderr
    for args in (["--prerelease", "rc1"], ["--bump", "minor"]):
        r, _ = cut(tmp_path, env, "retired", *args)
        assert r.returncode == 2 and "retired" in r.stderr


FAST = {"RELEASE_MUST_INCLUDE_WAIT": "3", "RELEASE_MUST_INCLUDE_INTERVAL": "1"}


def test_must_include_cuts_from_a_head_that_holds_the_fix(tmp_path):
    # 0.5.21: the fix's merge commit was still being checked on main, so the
    # newest green commit was the one before it, and the release shipped without the fix
    rc, head, env = setup(tmp_path)
    fix = commit(origin(tmp_path), "The fix")
    r, w = cut(tmp_path, {**env, **FAST, "FAKE_RUNNING": fix}, "racing",
               "--must-include", f"{NAME}@{fix[:7]}")
    assert r.returncode == 1 and not (w / "decide.json").exists()     # waited, then refused
    assert f"waiting for o/{NAME}@{fix[:7]}" in r.stdout and "up to" in r.stdout
    assert "its checks are not done" in r.stdout and "nothing was cut" in r.stderr
    r, w = cut(tmp_path, {**env, **FAST}, "green", "--must-include", f"o/{NAME}@{fix[:7]}")
    d = json.loads((w / "decide.json").read_text())
    assert d["commit"] == fix
    assert f"HEAD holds {fix[:7]}" in r.stdout
    r, w = cut(tmp_path, {**env, **FAST, "FAKE_RED": fix}, "red",
               "--must-include", f"{NAME}@{fix}")
    assert r.returncode == 1 and "its checks failed" in r.stderr


def test_must_include_refuses_a_commit_not_in_main_and_an_rc_without_it(tmp_path):
    rc, head, env = setup(tmp_path)
    o = origin(tmp_path)
    git(o, "checkout", "-q", "-b", "pr-head")
    pr_head = commit(o, "a pull request's own head, never on main")
    git(o, "checkout", "-q", "main")
    r, _ = cut(tmp_path, {**env, **FAST}, "unmerged", "--must-include", f"{NAME}@{pr_head}")
    assert r.returncode == 1 and "name the merge commit" in r.stdout
    r, w = cut(tmp_path, {**env, **FAST}, "dev-lacks", "--from-tag", "v0.8.0-dev1",
               "--must-include", f"{NAME}@{head}")
    assert r.returncode == 1 and "does not hold" in r.stderr
    assert not (w / "decide.json").exists()
    for spec in ("parallax@abc1234", f"{NAME}.page@abc1234"):
        r, _ = cut(tmp_path, env, "bad-spec", "--must-include", spec)
        assert r.returncode == 2 and f"takes {NAME}@SHA" in r.stderr, spec


def test_an_empty_release_is_refused(tmp_path):
    # 0.5.21: `git log v0.5.20..v0.5.21` was empty
    _, _, env = setup(tmp_path)
    git(origin(tmp_path), "tag", "-a", "v0.8.0-dev2", "-m", "v")
    r, w = cut(tmp_path, env, "empty")
    assert r.returncode == 2 and "an empty release is refused" in r.stderr
    assert not (w / "decide.json").read_text().strip()
    commit(origin(tmp_path), "one change")
    r, w = cut(tmp_path, env, "one")
    assert json.loads((w / "decide.json").read_text())["since"] == 1


def test_plan_says_whether_rc_check_is_needed_and_builds_nothing(tmp_path):
    _, _, env = setup(tmp_path)
    o = origin(tmp_path)
    (o / "pyproject.toml").write_text("[project]\nname = 'x'\n")    # packaging: rc_check's
    git(o, "add", "pyproject.toml")
    commit(o, "packaging")
    r, w = cut(tmp_path, env, "plan", "--plan")
    assert r.returncode == 0, r.stderr
    d = json.loads((w / "decide.json").read_text())
    assert d["rc_check"] == {"required": True, "why": ["pyproject.toml"]}
    assert d["tag"] == "v0.8.0-dev2"                    # one cut: no rc first
    assert "plan: nothing built or published" in r.stdout and not (w / "dist").exists()


def test_the_shape_guard_stops_a_cut_before_the_build(tmp_path):
    """A final cut with no release before it that carries the two-shape helper, and a compat
    cut once a final release exists, stop before anything is built."""
    _, _, env = setup(tmp_path)
    r, w = cut(tmp_path, env, "final-first")
    assert r.returncode == 2 and "no release before v0.8.0-dev2" in r.stderr
    assert "nothing was built" in r.stderr and not (w / "dist").exists()
    final = [{"tag_name": "v0.8.0-dev1", "draft": False,
              "assets": [{"name": f"{NAME}-0.8.0.dev1-py3-none-any.whl"}]}]
    r, w = cut(tmp_path, {**env, "FAKE_RELEASES": json.dumps(final)}, "compat-late",
               "--shape", "compat")
    assert r.returncode == 2 and "a final release exists (v0.8.0-dev1)" in r.stderr
    assert not (w / "dist").exists()
    for args in (["--shape", "compat", "--from-tag", "v0.8.0-dev1"],
                 ["--shape", "compat", "--line", "stable"], ["--shape", "other"]):
        r, _ = cut(tmp_path, env, "bad-shape", *args)
        assert r.returncode == 2 and ("compat shape" in r.stderr or "--shape" in r.stderr), args


def test_one_cut_at_a_time(tmp_path):
    _, _, env = setup(tmp_path)
    with open(tmp_path / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r, w = cut(tmp_path, {**env, "RELEASE_LOCK_WAIT": "1"}, "second")
    assert r.returncode == 2 and "another cut still holds" in r.stderr
    assert not w.exists()                                  # nothing cloned, nothing decided
