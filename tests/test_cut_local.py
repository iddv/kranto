"""cut_local.sh: the two lines, a promotion from a nightly build's own commits,
a fix from the stable line's branch, and one cut at a time.

A promotion (``--from-tag vX.Y.0-devN``) checks out the nightly build's tag in both repos; what
merged after it is not in it, so main never waits for a promotion. A nightly is cut from main's
newest green commits, a fix (``--line stable``) from release/X.Y's. Two local repos stand in
for GitHub (``RELEASE_GIT_BASE``), a fake ``gh`` says every check is green, and the cut stops
at the build (the repos have no packages), after the commits are chosen and tagged."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUT = ROOT / "scripts" / "release" / "cut_local.sh"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
running = [s for s in os.environ.get("FAKE_RUNNING", "").split(",") if s]
red = [s for s in os.environ.get("FAKE_RED", "").split(",") if s]
if a[:2] == ["auth", "status"]:
    sys.exit(0)
if a[0] == "api" and a[-1].endswith("/status"):
    print(json.dumps({"statuses": []}))
elif a[0] == "api" and "/pulls/" in a[1]:                # a merged PR's body (pairing.py)
    slug, n = a[1].removeprefix("repos/").split("/pulls/")
    print(json.loads(os.environ.get("FAKE_BODIES", "{}")).get(f"{slug}#{n}", ""))
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


def setup(tmp: Path) -> tuple[dict, dict, dict]:
    """Both repos: v0.1.0, then a nightly build (v0.2.0-dev1), then a merge after it."""
    rc, head = {}, {}
    for name in ("afk", "brb"):
        r = tmp / "origin" / "o" / name
        r.mkdir(parents=True)
        for cmd in (["init", "-q", "-b", "main"], ["config", "user.name", "t"],
                    ["config", "user.email", "t@example.invalid"]):
            git(r, *cmd)
        commit(r, f"first ({name})")                  # each repo its own commits
        git(r, "tag", "-a", "v0.1.0", "-m", "v")
        rc[name] = commit(r, f"in the nightly build ({name} #1)")
        git(r, "tag", "-a", "v0.2.0-dev1", "-m", "v")
        head[name] = commit(r, f"merged after the nightly build ({name} #2)")
    bin_ = tmp / "bin"
    bin_.mkdir()
    tool(bin_, "gh", FAKE_GH)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
           "REPO": "o/afk", "BRB_REPO": "o/brb", "RELEASE_GIT_BASE": f"file://{tmp / 'origin'}",
           "RELEASE_LOCK": str(tmp / "lock"), "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig")}
    return rc, head, env


def cut(tmp: Path, env: dict, work: str, *args: str) -> tuple[subprocess.CompletedProcess, Path]:
    w = tmp / work
    r = subprocess.run(["bash", str(CUT), *args], env={**env, "RELEASE_WORK": str(w)},
                       capture_output=True, text=True, timeout=120)
    return r, w


def test_a_promotion_holds_the_nightly_builds_commits_not_mains(tmp_path):
    rc, head, env = setup(tmp_path)
    r, w = cut(tmp_path, env, "promote", "--from-tag", "v0.2.0-dev1")
    assert r.returncode != 0                               # chosen and tagged; the build stops
    d = json.loads((w / "decide.json").read_text())
    assert (d["version"], d["tag"], d["kind"], d["branch"]) == ("0.2.0", "v0.2.0", "promotion",
                                                               "release/0.2")
    assert d["held"] and not d["prerelease"] and d["rc_check"]["required"]
    assert d["commits"] == {"kranto": rc["afk"], "kranto.page": rc["brb"]}
    for name, repo in (("afk", "kranto"), ("brb", "kranto.page")):
        assert git(w / repo, "rev-parse", "v0.2.0^{commit}") == rc[name]
    # a nightly from main's head: the next build toward 0.2.0, with the merge after dev1
    r, w = cut(tmp_path, env, "from-main")
    d = json.loads((w / "decide.json").read_text())
    assert (d["tag"], d["previous"], d["kind"]) == ("v0.2.0-dev2", "v0.2.0-dev1", "nightly")
    assert d["prerelease"] and not d["held"]
    assert d["commits"] == {"kranto": head["afk"], "kranto.page": head["brb"]}


def test_a_fix_is_cut_from_the_stable_lines_branch(tmp_path):
    rc, head, env = setup(tmp_path)
    r, _ = cut(tmp_path, env, "no-branch", "--line", "stable")
    assert r.returncode == 2 and "has no release/0.1 yet" in r.stderr
    fixes = {}
    for name in ("afk", "brb"):
        o = tmp_path / "origin" / "o" / name
        git(o, "branch", "release/0.1", "v0.1.0")
        git(o, "checkout", "-q", "release/0.1")
        fixes[name] = commit(o, f"a cherry-pick ({name} #3)")
        git(o, "checkout", "-q", "main")
    r, w = cut(tmp_path, env, "fix", "--line", "stable")
    d = json.loads((w / "decide.json").read_text())
    assert (d["tag"], d["previous"], d["kind"], d["held"]) == ("v0.1.1", "v0.1.0", "fix", True)
    assert d["commits"] == {"kranto": fixes["afk"], "kranto.page": fixes["brb"]}
    assert "release/0.1's newest green commit is" in r.stdout


def test_a_cut_from_main_takes_its_newest_green_commit(tmp_path):
    # 2026-10-17 00:14: the page main's head 4caad92 pending behind 6e72922 queued, and so on
    # while merges flowed; a cut from the head would wait for hours
    rc, head, env = setup(tmp_path)
    r, w = cut(tmp_path, {**env, "FAKE_RUNNING": head["brb"]}, "busy")
    d = json.loads((w / "decide.json").read_text())
    assert d["commits"] == {"kranto": head["afk"], "kranto.page": rc["brb"]}
    assert "main's newest green commit is" in r.stdout
    r, w = cut(tmp_path, {**env, "FAKE_RUNNING": ",".join([head["afk"], rc["afk"]])}, "older")
    d = json.loads((w / "decide.json").read_text())
    assert d["commits"]["kranto"] == git(tmp_path / "origin" / "o" / "afk", "rev-parse",
                                           "v0.1.0^{commit}")


def test_from_tag_takes_a_nightly_builds_tag_only_and_rc_is_retired(tmp_path):
    _, _, env = setup(tmp_path)
    for args in (["--from-tag", "v0.1.0"], ["--from-tag", "v0.1.1-rc1"],
                 ["--from-tag", "v0.2.0-dev1", "--line", "stable"]):
        r, _ = cut(tmp_path, env, "bad", *args)
        assert r.returncode == 2 and "--from-tag" in r.stderr, args
    r, _ = cut(tmp_path, env, "missing", "--from-tag", "v0.2.0-dev9")
    assert r.returncode == 2 and "has no tag v0.2.0-dev9" in r.stderr
    for args in (["--prerelease", "rc1"], ["--bump", "minor"]):
        r, _ = cut(tmp_path, env, "retired", *args)
        assert r.returncode == 2 and "retired" in r.stderr


FAST = {"RELEASE_MUST_INCLUDE_WAIT": "3", "RELEASE_MUST_INCLUDE_INTERVAL": "1"}


def test_must_include_cuts_from_a_head_that_holds_the_fix(tmp_path):
    # 0.5.21: the fix's merge commit was still being checked on main, so the
    # newest green commit was the one before it, and the release shipped without the fix
    rc, head, env = setup(tmp_path)
    afk = tmp_path / "origin" / "o" / "afk"
    fix = commit(afk, "The fix")
    r, w = cut(tmp_path, {**env, **FAST, "FAKE_RUNNING": fix}, "racing",
               "--must-include", f"kranto@{fix[:7]}")
    assert r.returncode == 1 and not (w / "decide.json").exists()     # waited, then refused
    assert f"waiting for o/afk@{fix[:7]}" in r.stdout and "up to" in r.stdout
    assert "its checks are not done" in r.stdout and "nothing was cut" in r.stderr
    r, w = cut(tmp_path, {**env, **FAST}, "green", "--must-include", f"o/kranto@{fix[:7]}")
    d = json.loads((w / "decide.json").read_text())
    assert d["commits"]["kranto"] == fix
    assert f"HEAD holds {fix[:7]}" in r.stdout
    r, w = cut(tmp_path, {**env, **FAST, "FAKE_RED": fix}, "red",
               "--must-include", f"kranto@{fix}")
    assert r.returncode == 1 and "its checks failed" in r.stderr


def test_must_include_refuses_a_commit_not_in_main_and_an_rc_without_it(tmp_path):
    rc, head, env = setup(tmp_path)
    afk = tmp_path / "origin" / "o" / "afk"
    git(afk, "checkout", "-q", "-b", "pr-head")
    pr_head = commit(afk, "a pull request's own head, never on main")
    git(afk, "checkout", "-q", "main")
    r, _ = cut(tmp_path, {**env, **FAST}, "unmerged", "--must-include", f"kranto@{pr_head}")
    assert r.returncode == 1 and "name the merge commit" in r.stdout
    r, w = cut(tmp_path, {**env, **FAST}, "dev-lacks", "--from-tag", "v0.2.0-dev1",
               "--must-include", f"kranto@{head['afk']}")
    assert r.returncode == 1 and "does not hold" in r.stderr
    assert not (w / "decide.json").exists()
    r, _ = cut(tmp_path, env, "bad-spec", "--must-include", "parallax@abc1234")
    assert r.returncode == 2 and "kranto@SHA or kranto.page@SHA" in r.stderr


def test_an_empty_release_is_refused(tmp_path):
    # 0.5.21: `git log v0.5.20..v0.5.21` was empty in both repos
    _, _, env = setup(tmp_path)
    for name in ("afk", "brb"):
        git(tmp_path / "origin" / "o" / name, "tag", "-a", "v0.2.0-dev2", "-m", "v")
    r, w = cut(tmp_path, env, "empty")
    assert r.returncode == 2 and "an empty release is refused" in r.stderr
    assert not (w / "decide.json").read_text().strip()
    commit(tmp_path / "origin" / "o" / "brb", "one change in one repo")
    r, w = cut(tmp_path, env, "one-repo")
    assert json.loads((w / "decide.json").read_text())["since"] == {"kranto": 0,
                                                                     "kranto.page": 1}


def test_plan_says_whether_rc_check_is_needed_and_builds_nothing(tmp_path):
    _, _, env = setup(tmp_path)
    afk = tmp_path / "origin" / "o" / "afk"
    (afk / "pyproject.toml").write_text("[project]\nname = 'x'\n")    # packaging: rc_check's
    git(afk, "add", "pyproject.toml")
    commit(afk, "packaging")
    r, w = cut(tmp_path, env, "plan", "--plan")
    assert r.returncode == 0, r.stderr
    d = json.loads((w / "decide.json").read_text())
    assert d["rc_check"] == {"required": True, "why": ["kranto: pyproject.toml"]}
    assert d["tag"] == "v0.2.0-dev2"                    # one cut: no rc first
    assert "plan: nothing built or published" in r.stdout and not (w / "dist").exists()


def test_one_cut_at_a_time(tmp_path):
    _, _, env = setup(tmp_path)
    with open(tmp_path / "lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r, w = cut(tmp_path, {**env, "RELEASE_LOCK_WAIT": "1"}, "second")
    assert r.returncode == 2 and "another cut still holds" in r.stderr
    assert not w.exists()                                  # nothing cloned, nothing decided
