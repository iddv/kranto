#!/usr/bin/env python3
"""Which merged pull requests had no green checks on the commit that was merged?

    audit_merges.py OWNER/REPO [--since YYYY-MM-DD | --days N] [--issue]

A merge is green when the PR's head commit (the one `merge_when_green.sh` merges with
``--match-head-commit``) had at least one check, every check run completed with success,
skipped or neutral, and every status succeeded. Prints one line per merge that was not.
``--issue`` files one issue in the repo listing them (nothing is filed when every merge was
green). Exit 0 when every merge was green, 1 otherwise. Reads GitHub through ``gh``.
Standard library only; the same file is in the server and the page.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta

PASS = {"SUCCESS", "SKIPPED", "NEUTRAL"}


def gh(*args: str, run=subprocess.run) -> str:
    r = run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"audit_merges: gh {' '.join(args[:3])}: {r.stderr.strip()}")
    return r.stdout


def merged_since(repo: str, since: str, gh=gh) -> list[dict]:
    out = gh("pr", "list", "-R", repo, "--state", "merged", "--limit", "500",
             "--search", f"merged:>={since}",
             "--json", "number,title,mergedAt,mergedBy,headRefOid,statusCheckRollup")
    return sorted(json.loads(out), key=lambda p: p["mergedAt"])


def verdict(pr: dict) -> str | None:
    """None when the merged head was green, else why not."""
    latest: dict[tuple, dict] = {}            # a rerun replaces the run it reran
    for c in pr.get("statusCheckRollup") or []:
        key = (c.get("workflowName") or "", c.get("name") or c.get("context") or "?")
        when = c.get("startedAt") or c.get("completedAt") or ""
        if key not in latest or when >= (latest[key].get("startedAt")
                                         or latest[key].get("completedAt") or ""):
            latest[key] = c
    checks = list(latest.values())
    if not checks:
        return "no checks"
    bad = []
    for c in checks:
        name = c.get("name") or c.get("context") or "?"
        if c.get("__typename") == "StatusContext" or "state" in c and "conclusion" not in c:
            if (c.get("state") or "").upper() != "SUCCESS":
                bad.append(f"{name} {(c.get('state') or '?').lower()}")
            continue
        if (c.get("status") or "").upper() != "COMPLETED":
            bad.append(f"{name} {(c.get('status') or '?').lower()}")
        elif (c.get("conclusion") or "").upper() not in PASS:
            bad.append(f"{name} {(c.get('conclusion') or '?').lower()}")
    if not bad and not any((c.get("conclusion") or c.get("state") or "").upper() == "SUCCESS"
                           for c in checks):
        return "no check succeeded"
    return ", ".join(bad) or None


def report(repo: str, prs: list[dict]) -> tuple[list[str], str]:
    lines = []
    for p in prs:
        why = verdict(p)
        if why:
            who = (p.get("mergedBy") or {}).get("login") or "?"
            lines.append(f"- #{p['number']} merged {p['mergedAt'][:16].replace('T', ' ')} by "
                         f"{who} at {p['headRefOid'][:10]}: {why}")
    head = (f"{repo}: {len(prs)} merged, {len(lines)} without green checks on the merged "
            "commit")
    return lines, head


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--since", help="YYYY-MM-DD")
    g.add_argument("--days", type=int, default=7)
    ap.add_argument("--issue", action="store_true", help="file an issue when any was red")
    a = ap.parse_args(argv)
    since = a.since or (datetime.now(UTC) - timedelta(days=a.days)).strftime("%Y-%m-%d")
    lines, head = report(a.repo, merged_since(a.repo, since))
    print(f"{head} (since {since})")
    print("\n".join(lines))
    if lines and a.issue:
        body = (f"Merged since {since} without every check green on the merged commit:\n\n"
                + "\n".join(lines) + "\n\nThe rule (CONTRIBUTING): merge only with "
                "`scripts/ci/merge_when_green.sh`; a red check gets one rerun, then it is a "
                "flake to fix in its own PR. Found by the weekly audit "
                "(`scripts/ci/audit_merges.py`).\n")
        gh("issue", "create", "-R", a.repo, "--title",
           f"CI audit: {len(lines)} merge(s) without green checks since {since}",
           "--body", body)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
