"""The merge and release discipline (CONTRIBUTING, "Merging and releasing"): checks.py's rule
for a green commit, merge_when_green.sh, decide.py's gate and the weekly merge audit. GitHub is
a fake: an injected API, or a fake ``gh`` first on PATH."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / "scripts" / "ci"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(f"ci_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


checks = _load(CI / "checks.py")
audit = _load(CI / "audit_merges.py")
decide = _load(ROOT / "scripts" / "release" / "decide.py")


def run_(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


# -- checks.py ---------------------------------------------------------------------------------

def test_a_commit_is_green_only_when_every_check_passed():
    V = checks.verdict
    assert V([])[0] == checks.PENDING                                 # nothing reported yet
    assert V([run_("fast"), run_("slow", "in_progress", None)])[0] == checks.PENDING
    assert V([run_("fast"), run_("slow", conclusion="failure")]) == \
        (checks.RED, "red: slow (failure)")
    assert V([run_("fast"), run_("slow", conclusion="cancelled")])[0] == checks.RED
    assert V([run_("fast", conclusion="skipped")])[0] == checks.RED   # nothing actually ran
    assert V([run_("fast"), run_("docker", conclusion="skipped")])[0] == checks.GREEN
    assert V([run_("fast")], require=("fast", "slow")) == \
        (checks.PENDING, "required checks not reported yet: slow")
    assert V([run_("fast"), run_("slow")], require=("fast", "slow"))[0] == checks.GREEN


def test_a_skipped_required_check_never_counts_as_passing():
    """A fork's pull request skips the server jobs; a hosted job that succeeds beside them
    must not make the skipped `test` look green."""
    V = checks.verdict
    fork = [run_("test", conclusion="skipped"), run_("gitleaks", conclusion="skipped"),
            run_("fork")]
    assert V(fork)[0] == checks.GREEN                     # nothing required: as before
    assert V(fork, require=("test", "gitleaks")) == \
        (checks.RED, "required checks did not run: gitleaks, test")
    assert V(fork, require=("fork",))[0] == checks.GREEN
    # a rerun's earlier skipped entry beside its success is fine
    assert V([run_("test", conclusion="skipped"), run_("test")], require=("test",))[0] == \
        checks.GREEN


def test_statuses_count_as_checks():
    def api(path):
        if path.endswith("/status"):
            return {"statuses": [{"context": "GitGuardian", "state": "failure"}]}
        return {"check_runs": [run_("fast")]}
    code, why = checks.green("o/r", "abc", api=api)
    assert code == checks.RED and "GitGuardian (failure)" in why


def test_wait_reads_a_green_set_twice_and_stops_at_red():
    seq = iter([[], [run_("fast", "queued", None)], [run_("fast")], [run_("fast")]])
    sleeps = []
    code, why = checks.wait("o/r", "abc", api=lambda p: (
        {"statuses": []} if p.endswith("/status") else {"check_runs": next(seq)}),
        sleep=sleeps.append, interval=5, say=lambda m: None)
    assert code == checks.GREEN and sleeps == [5, 5, 5]
    code, _ = checks.wait("o/r", "abc", api=lambda p: (
        {"statuses": []} if p.endswith("/status") else
        {"check_runs": [run_("fast", conclusion="failure")]}), sleep=sleeps.append,
        say=lambda m: None)
    assert code == checks.RED


def test_wait_times_out():
    t = iter(range(0, 10_000, 30))
    code, why = checks.wait("o/r", "abc", timeout=60, interval=30, sleep=lambda s: None,
                            now=lambda: next(t), say=lambda m: None,
                            api=lambda p: {"statuses": []} if p.endswith("/status") else
                            {"check_runs": [run_("slow", "in_progress", None)]})
    assert code == checks.TIMED_OUT and "pending: slow" in why


# the page run 38937485289 (2026-10-16 17:09): fast, lint and gitleaks waited six minutes for a
# runner and were cancelled without one; slow was cancelled after it had started
NEVER_STARTED = [
    {"name": "browser", "status": "completed", "conclusion": "success",
     "runner_name": "example-host-kranto.page-3", "steps": [{}] * 9},
    {"name": "lint", "status": "completed", "conclusion": "cancelled", "runner_name": "",
     "steps": []},
    {"name": "fast", "status": "completed", "conclusion": "cancelled", "runner_name": "",
     "steps": []},
    {"name": "lab", "status": "completed", "conclusion": "skipped", "runner_name": None,
     "steps": []},
]
STARTED = {"name": "slow", "status": "completed", "conclusion": "cancelled",
           "runner_name": "example-host-kranto.page", "steps": [{}] * 8}


def test_a_job_no_runner_took_is_unstarted_one_that_ran_is_not():
    def api(jobs):
        return lambda path: {"jobs": jobs}
    assert checks.unstarted("o/r", "1", api=api(NEVER_STARTED))
    assert not checks.unstarted("o/r", "1", api=api([*NEVER_STARTED, STARTED]))
    failed = {**STARTED, "conclusion": "failure"}
    assert not checks.unstarted("o/r", "1", api=api([failed]))
    assert not checks.unstarted("o/r", "1", api=api(NEVER_STARTED[:1]))   # nothing red


# -- decide.py's gate ----------------------------------------------------------------------------

def _repo(path: Path) -> Path:
    path.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.name", "t"],
                ["config", "user.email", "t@example.invalid"],
                ["commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", "-C", str(path), *cmd], check=True)
    return path


def test_a_release_is_cut_only_from_green_commits(tmp_path):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    asked = []

    def green(repo, sha):
        asked.append(repo)
        return (repo != "o/brb", "red: slow (failure)" if repo == "o/brb" else "green")
    with pytest.raises(decide.DecideError, match=r"kranto.page at \w+ is not green \(red: slow"):
        decide.decide(afk, brb, green=green, repos=("o/afk", "o/brb"))
    assert asked == ["o/afk", "o/brb"]
    out = decide.decide(afk, brb, green=lambda r, s: (True, "green"), repos=("o/afk", "o/brb"))
    assert out["release"] and out["checked"]


def _change(repo: Path, *files: str) -> None:
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + "x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change"], check=True)


def _tag(tag: str, *repos: Path) -> None:
    for r in repos:
        subprocess.run(["git", "-C", str(r), "tag", "-a", tag, "-m", "v"], check=True)


def test_rc_check_only_when_the_release_touches_what_it_checks(tmp_path):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    _tag("v0.3.71", afk, brb)
    # pages and typed reads: no rc_check, the cut's smoke is the check
    _change(brb, "src/kranto/page/ui/web/src/pages/projects/Projects.svelte")
    _change(afk, "src/kranto/web/types.py")
    out = decide.decide(afk, brb)
    assert out["tag"] == "v0.4.0-dev1" and out["rc_check"] == {"required": False, "why": []}
    _tag("v0.4.0-dev1", afk, brb)
    # a migration in the server's store and the loop ledger's: rc_check on the published build,
    # one cut (no rc tag first)
    _change(afk, "src/kranto/store.py")
    _change(brb, "src/kranto/page/loop/ledger.py", "src/kranto/page/ideas/editor.py")
    out = decide.decide(afk, brb)
    assert out["tag"] == "v0.4.0-dev2" and out["previous"] == "v0.4.0-dev1"
    assert out["rc_check"]["why"] == ["kranto: src/kranto/store.py",
                                      "kranto.page: src/kranto/page/loop/ledger.py"]
    _tag("v0.4.0-dev2", afk, brb)
    # the owner's promotion of dev2: always checked, cut from the tag's commits
    out = decide.decide(afk, brb, from_tag="v0.4.0-dev2")
    assert (out["tag"], out["previous"], out["kind"]) == ("v0.4.0", "v0.3.71", "promotion")
    assert out["rc_check"]["required"] and out["held"]


def test_decide_needs_both_repos_for_the_gate(tmp_path):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    with pytest.raises(SystemExit):
        decide.main(["--afk", str(afk), "--brb", str(brb), "--repo", "o/afk"])


# -- audit_merges.py -----------------------------------------------------------------------------

def test_the_audit_names_merges_whose_merged_commit_was_not_green():
    ok = {"__typename": "CheckRun", "workflowName": "test", "name": "pytest",
          "status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": "2026-10-12T10:00:00Z"}
    prs = [
        {"number": 1, "mergedAt": "2026-10-12T11:00:00Z", "headRefOid": "a" * 40,
         "mergedBy": {"login": "o"}, "statusCheckRollup": [ok]},
        {"number": 2, "mergedAt": "2026-10-12T12:00:00Z", "headRefOid": "b" * 40,
         "mergedBy": {"login": "o"}, "statusCheckRollup": [
             {**ok, "conclusion": "FAILURE", "startedAt": "2026-10-12T09:00:00Z"},
             ok]},                                           # a rerun that passed: green
        {"number": 3, "mergedAt": "2026-10-12T13:00:00Z", "headRefOid": "c" * 40,
         "mergedBy": {"login": "o"}, "statusCheckRollup": [{**ok, "conclusion": "CANCELLED"}]},
        {"number": 4, "mergedAt": "2026-10-12T14:00:00Z", "headRefOid": "d" * 40,
         "mergedBy": {"login": "o"}, "statusCheckRollup": []},
        {"number": 5, "mergedAt": "2026-10-12T15:00:00Z", "headRefOid": "e" * 40,
         "mergedBy": {"login": "o"}, "statusCheckRollup": [
             ok, {"__typename": "StatusContext", "context": "GitGuardian", "state": "PENDING"}]},
    ]
    lines, head = audit.report("o/r", prs)
    assert head == "o/r: 5 merged, 3 without green checks on the merged commit"
    assert [ln.split()[1] for ln in lines] == ["#3", "#4", "#5"]
    assert lines[0].endswith("pytest cancelled") and lines[1].endswith("no checks")
    assert lines[2].endswith("GitGuardian pending")


# -- merge_when_green.sh with a fake gh ---------------------------------------------------------

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_GH_STATE"]
a = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(" ".join(a) + "\n")
def state(name):
    return json.load(open(os.path.join(d, name)))
if a[:2] == ["pr", "view"] and "state,isDraft" in a:
    print("OPEN false")
elif a[:2] == ["pr", "diff"]:
    p = os.path.join(d, "diff.txt")
    print(open(p).read() if os.path.exists(p) else "")
elif a[:2] == ["pr", "view"] and "labels" in a:
    print("\n".join(state("labels.json")) if os.path.exists(os.path.join(d, "labels.json")) else "")
elif a[:2] == ["pr", "view"] and "headRefOid" in a:
    heads = state("heads.json")
    print(heads.pop(0) if len(heads) > 1 else heads[0])
    json.dump(heads, open(os.path.join(d, "heads.json"), "w"))
elif a[0] == "api" and a[-1].endswith("/status"):
    print(json.dumps({"statuses": []}))
elif a[0] == "api" and "/check-runs" in a[-1]:
    print(json.dumps({"check_runs": state("checks.json")}))
elif a[0] == "api" and "/jobs" in a[-1]:
    print(json.dumps({"jobs": state("jobs.json")}))
elif a[:2] == ["pr", "merge"]:
    print("merged")
elif a[:2] == ["run", "list"]:
    print("\n".join(str(i) for i in state("runs.json")))
elif a[:2] == ["run", "rerun"]:
    after = os.path.join(d, "after_rerun.json")
    if os.path.exists(after):
        os.replace(after, os.path.join(d, "checks.json"))
else:
    sys.exit(f"fake gh: unexpected {a}")
'''


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    gh = bin_ / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    st = tmp_path / "state"
    st.mkdir()

    def run(heads, checks_, *args, runs=(), after_rerun=None, repo="o/r", jobs=(), diff="",
            labels=()):
        (st / "heads.json").write_text(json.dumps(heads))
        (st / "diff.txt").write_text(diff)
        (st / "labels.json").write_text(json.dumps(list(labels)))
        (st / "checks.json").write_text(json.dumps(checks_))
        (st / "runs.json").write_text(json.dumps(list(runs)))
        (st / "jobs.json").write_text(json.dumps(list(jobs)))
        if after_rerun is not None:
            (st / "after_rerun.json").write_text(json.dumps(after_rerun))
        (st / "calls.log").write_text("")
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
               "FAKE_GH_STATE": str(st), "MERGE_INTERVAL": "0",
               "MERGE_STATE_DIR": str(tmp_path / "marks")}
        r = subprocess.run(["bash", str(CI / "merge_when_green.sh"), repo, "7", *args],
                           capture_output=True, text=True, env=env)
        calls = (st / "calls.log").read_text().splitlines()
        run.reruns = [c for c in calls if c.startswith("run rerun")]
        return r, [c for c in calls if c.startswith("pr merge")]
    return run


SHA = "1234567890" * 4


def test_merges_green_at_the_exact_head(fake_gh):
    r, merges = fake_gh([SHA], [run_("fast"), run_("slow")], "--require", "fast,slow")
    assert r.returncode == 0, r.stderr
    assert merges == [f"pr merge 7 -R o/r --squash --match-head-commit {SHA}"]
    assert "--admin" not in merges[0]


BIG_DIFF = """diff --git a/src/kranto/core/shell.py b/src/kranto/core/shell.py
--- a/src/kranto/core/shell.py
+++ b/src/kranto/core/shell.py
@@ -1,3 +1,3 @@
-    "shell.layout": Setting("enum", "classic", choices=LAYOUTS),
+    "shell.layout": Setting("enum", "new", choices=LAYOUTS),
"""


def test_a_diff_that_may_be_big_waits_for_its_label(fake_gh):
    """#247 turned the New layout on for everyone with no word; a default
    changed now merges only once its author said big or not-big."""
    r, merges = fake_gh([SHA], [run_("test")], diff=BIG_DIFF)
    assert r.returncode == 2 and not merges
    assert "the default of shell.layout changed" in r.stderr and "label it big" in r.stderr
    for label in ("big", "not-big"):
        r, merges = fake_gh([SHA], [run_("test")], diff=BIG_DIFF, labels=[label])
        assert r.returncode == 0 and merges, r.stderr
        assert f"labelled {label}" in r.stdout


def test_jobs_no_runner_took_are_rerun_without_spending_the_one_rerun(fake_gh, tmp_path):
    red = [run_("fast", conclusion="cancelled"), run_("browser")]
    r, merges = fake_gh([SHA], red, runs=[51], jobs=NEVER_STARTED,
                        after_rerun=[run_("fast"), run_("browser")])
    assert r.returncode == 0, r.stderr                 # no --rerun-once needed: nothing ran
    assert fake_gh.reruns == ["run rerun 51 -R o/r --failed"]
    assert "never started" in r.stdout and not (tmp_path / "marks").exists()
    assert merges == [f"pr merge 7 -R o/r --squash --match-head-commit {SHA}"]
    # a runner that never comes: three free reruns, then red
    r, merges = fake_gh([SHA], red, runs=[52], jobs=NEVER_STARTED)
    assert r.returncode == 1 and merges == [] and len(fake_gh.reruns) == 3
    # a job that ran and was cancelled is a red check: the one rerun, with --rerun-once only
    r, merges = fake_gh([SHA], red, runs=[53], jobs=[STARTED])
    assert r.returncode == 1 and fake_gh.reruns == []
    r, merges = fake_gh([SHA], red, "--rerun-once", runs=[53], jobs=[STARTED])
    assert r.returncode == 1 and fake_gh.reruns == ["run rerun 53 -R o/r --failed"]
    assert "flake to fix" in r.stderr


def test_a_merge_never_waits_for_a_release(fake_gh, tmp_path, monkeypatch):
    # the freeze is gone (finding 1): stable is cut from its rc's tag, so a fleet note
    # announcing an rc stops nothing
    notes = tmp_path / "home" / "work" / "MQ.NOTES.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("- 19:01 UTC **RM rc in flight: 0.3.72**. Please merge nothing.\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    r, merges = fake_gh([SHA], [run_("fast"), run_("slow")], repo="iddv/kranto")
    assert r.returncode == 0, r.stderr
    assert merges == [f"pr merge 7 -R iddv/kranto --squash --match-head-commit {SHA}"]
    assert not (CI / "freeze.py").exists()


def test_refuses_red_and_a_moved_head(fake_gh):
    r, merges = fake_gh([SHA], [run_("fast"), run_("slow", conclusion="failure")])
    assert r.returncode == 1 and merges == [] and "red: slow (failure)" in r.stdout + r.stderr
    r, merges = fake_gh([SHA, "f" * 40], [run_("fast")])
    assert r.returncode == 2 and merges == [] and "head moved" in r.stderr


def test_a_missing_required_check_is_not_green(fake_gh):
    r, merges = fake_gh([SHA], [run_("fast")], "--require", "fast,slow", "--timeout", "0")
    assert r.returncode == 4 and merges == []


def test_a_red_check_gets_one_rerun_then_merges_green(fake_gh):
    red = [run_("fast"), run_("slow", conclusion="failure")]
    r, merges = fake_gh([SHA], red, "--rerun-once", runs=[41],
                        after_rerun=[run_("fast"), run_("slow")])
    assert r.returncode == 0, r.stderr
    assert fake_gh.reruns == ["run rerun 41 -R o/r --failed"]
    assert merges == [f"pr merge 7 -R o/r --squash --match-head-commit {SHA}"]


def test_rerun_once_is_safe_to_call_again_after_an_outer_timeout(fake_gh):
    red = [run_("fast"), run_("slow", conclusion="failure")]
    # the first call reruns, then is cut off while the rerun is still going
    pending = [run_("fast"), run_("slow", status="in_progress", conclusion=None)]
    r, merges = fake_gh([SHA], red, "--rerun-once", "--timeout", "0", runs=[41],
                        after_rerun=pending)
    assert r.returncode == 4 and merges == []
    assert fake_gh.reruns == ["run rerun 41 -R o/r --failed"]
    # called again once the rerun came back red: it is not rerun a second time
    r, merges = fake_gh([SHA], red, "--rerun-once", runs=[41])
    assert r.returncode == 1 and merges == [] and fake_gh.reruns == []
    assert "already rerun once" in r.stdout and "flake to fix" in r.stderr
    # a new head is a new commit: its red run gets its own one rerun
    r, merges = fake_gh(["f" * 40], red, "--rerun-once", runs=[42])
    assert r.returncode == 1 and fake_gh.reruns == ["run rerun 42 -R o/r --failed"]


def test_the_scripts_are_executable_and_stdlib_only():
    for p in CI.iterdir():
        if p.suffix in (".json", ".txt"):              # a check's baseline: data, not a script
            continue
        assert p.stat().st_mode & stat.S_IXUSR, p
        if p.suffix == ".py":
            src = p.read_text()
            imports = {ln.split()[1].split(".")[0] for ln in src.splitlines()
                       if ln.startswith(("import ", "from ")) and "__future__" not in ln}
            assert imports <= set(sys.stdlib_module_names), (p, imports)
