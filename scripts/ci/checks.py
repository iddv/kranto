#!/usr/bin/env python3
"""Are the checks on one commit green? The one rule every merge and every release follows.

A commit is green when it has at least one check, every check run is completed with
``success``, ``skipped`` or ``neutral`` (at least one ``success``), every commit status is
``success``, and every name in ``--require`` is among them and succeeded (a skipped required
check is red: it did not run). Anything queued or in progress is pending; anything else
(failure, cancelled, timed out, action required) is red.

    checks.py green REPO SHA [--require a,b]     exit 0 green, 1 red, 3 pending
    checks.py wait REPO SHA [--require a,b] [--timeout S] [--interval S]
                                                 waits while pending; exit 0 green, 1 red,
                                                 4 timed out
    checks.py unstarted REPO RUN_ID              exit 0 when every red job of the run was
                                                 cancelled before a runner took it, else 1
    checks.py newest-green REPO CHECKOUT [--depth N]
                                                 prints the newest first-parent commit of the
                                                 checkout's HEAD whose checks are all green

Reads GitHub through ``gh api`` (the caller's login, or ``GH_TOKEN``). Standard library only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

PASS = {"success", "skipped", "neutral"}
GREEN, RED, PENDING, TIMED_OUT = 0, 1, 3, 4


class ChecksError(Exception):
    pass


def gh_api(path: str, run=subprocess.run) -> dict:
    r = run(["gh", "api", "-H", "Accept: application/vnd.github+json", path],
            capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise ChecksError(f"gh api {path}: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout)


def checks_of(repo: str, sha: str, api=gh_api) -> list[dict]:
    """Every check on ``sha``: the latest run of each check (``name``, ``status``,
    ``conclusion``) and each commit status as a check of its own."""
    runs = api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100").get("check_runs") or []
    out = [{"name": r.get("name"), "status": r.get("status"),
            "conclusion": r.get("conclusion"), "url": r.get("html_url")} for r in runs]
    for s in (api(f"repos/{repo}/commits/{sha}/status").get("statuses") or []):
        state = s.get("state")
        out.append({"name": s.get("context"),
                    "status": "completed" if state != "pending" else "in_progress",
                    "conclusion": "success" if state == "success" else state,
                    "url": s.get("target_url")})
    return out


def verdict(checks: list[dict], require: tuple[str, ...] = ()) -> tuple[int, str]:
    """(GREEN | RED | PENDING, one line saying why)."""
    if not checks:
        return PENDING, "no checks yet"
    red = [c for c in checks if c["status"] == "completed" and c["conclusion"] not in PASS]
    if red:
        return RED, "red: " + ", ".join(f"{c['name']} ({c['conclusion']})" for c in red)
    pending = [c["name"] for c in checks if c["status"] != "completed"]
    if pending:
        return PENDING, "pending: " + ", ".join(pending)
    missing = [n for n in require if n not in {c["name"] for c in checks}]
    if missing:
        return PENDING, "required checks not reported yet: " + ", ".join(missing)
    # a required check that was skipped did not run: a pull request from a fork skips the
    # the server jobs, and their "skipped" must never stand in for the tests
    unrun = sorted({c["name"] for c in checks if c["name"] in require}
                   - {c["name"] for c in checks if c["conclusion"] == "success"})
    if unrun:
        return RED, "required checks did not run: " + ", ".join(unrun)
    if not any(c["conclusion"] == "success" for c in checks):
        return RED, "no check succeeded (all skipped or neutral)"
    return GREEN, "green: " + ", ".join(sorted(c["name"] for c in checks))


def unstarted(repo: str, run_id: str, api=gh_api) -> bool:
    """Whether every red job of a workflow run never started: cancelled before any runner took
    it (no runner, no step ran). Nothing ran, so nothing failed: ``merge_when_green.sh`` reruns
    it without counting it as the one rerun a red check gets."""
    jobs = api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100").get("jobs") or []
    red = [j for j in jobs if j.get("status") == "completed" and j.get("conclusion") not in PASS]
    return bool(red) and all(j.get("conclusion") == "cancelled" and not j.get("runner_name")
                             and not j.get("steps") for j in red)


def green(repo: str, sha: str, require: tuple[str, ...] = (), api=gh_api) -> tuple[int, str]:
    return verdict(checks_of(repo, sha, api), require)


def newest_green(repo: str, shas: list[str], api=gh_api) -> str | None:
    """The first of ``shas`` (a branch's first-parent history, newest first) whose checks are
    all green, or None. A release cuts from it: the head is often still being checked, and a
    push run waiting behind another is cancelled when a newer push arrives."""
    for sha in shas:
        if green(repo, sha, api=api)[0] == GREEN:
            return sha
    return None


def wait(repo: str, sha: str, require: tuple[str, ...] = (), timeout: float = 3600,
         interval: float = 30, api=gh_api, sleep=time.sleep, now=time.monotonic,
         say=print) -> tuple[int, str]:
    """Poll until the checks are no longer pending. A green set is read twice, ``interval``
    apart, so a workflow whose run appears a little later is not missed."""
    deadline = now() + timeout
    last = said = None
    while True:
        code, why = green(repo, sha, require, api)
        if code == RED:
            return code, why
        if code == GREEN:
            if last == why:
                return code, why
            last = why
        else:
            last = None
        if why != said:
            say(f"{repo}@{sha[:10]}: {why}")
            said = why
        if now() >= deadline:
            return TIMED_OUT, f"timed out after {timeout:g}s; {why}"
        sleep(interval)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("command", choices=("green", "wait", "unstarted", "newest-green"))
    p.add_argument("repo", help="owner/name")
    p.add_argument("sha", help="the commit; for unstarted, a workflow run's id; for "
                               "newest-green, a checkout of the branch")
    p.add_argument("--depth", type=int, default=30, help="newest-green: commits to look at")
    p.add_argument("--require", default="", help="check names that must be present, comma "
                                                 "separated")
    p.add_argument("--timeout", type=float, default=3600)
    p.add_argument("--interval", type=float, default=30)
    a = p.parse_args(argv)
    require = tuple(n.strip() for n in a.require.split(",") if n.strip())
    try:
        if a.command == "newest-green":
            shas = subprocess.run(["git", "-C", a.sha, "rev-list", "--first-parent", "-n",
                                   str(a.depth), "HEAD"], capture_output=True, text=True,
                                  check=True).stdout.split()
            sha = newest_green(a.repo, shas)
            if sha is None:
                print(f"checks: none of the last {len(shas)} commits of {a.repo} is green",
                      file=sys.stderr)
                return RED
            print(sha)
            return 0
        if a.command == "unstarted":
            yes = unstarted(a.repo, a.sha)
            print(f"{a.repo} run {a.sha}: " + ("its red jobs never started" if yes else
                                               "a red job ran (or none is red)"))
            return 0 if yes else 1
        if a.command == "green":
            code, why = green(a.repo, a.sha, require)
        else:
            code, why = wait(a.repo, a.sha, require, a.timeout, a.interval)
    except ChecksError as e:
        print(f"checks: {e}", file=sys.stderr)
        return 2
    print(f"{a.repo}@{a.sha[:10]}: {why}")
    return code


if __name__ == "__main__":
    sys.exit(main())
