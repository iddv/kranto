"""The audit of the page's web UI lockfile, with named exceptions.

    python3 scripts/ci/npm_audit.py [--dir DIR] [--level high] [--allow FILE]
                                    [--report FILE] [--today YYYY-MM-DD]

Runs ``npm audit --json`` in DIR (default ``src/kranto/page/ui/web``) and fails on every advisory
at LEVEL or above, as ``npm audit --audit-level=LEVEL`` does, except the ones named in FILE
(default ``scripts/ci/npm_audit_allow.json``). Each exception names the advisory (its GHSA id),
the package, why it cannot reach a person who installs Kranto, and the day after which it fails
again (``until``), so it is looked at again rather than forgotten. A package flagged only through
another (npm's ``via`` names a package, not an advisory) carries that package's advisories and
passes or fails with them. ``--report`` reads a saved ``npm audit --json`` instead of running npm
(the tests).

Standard library only. Exit 0: nothing at LEVEL, or only excused advisories; 1: an advisory not
excused, or excused past its day; 2: npm's report could not be read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ("info", "low", "moderate", "high", "critical")


def advisories(report: dict) -> dict[str, dict]:
    """Every advisory in an ``npm audit --json`` report (version 2), by its GHSA id."""
    out: dict[str, dict] = {}
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if not isinstance(via, dict):
                continue                    # a package's name: its own advisories are listed
            url = str(via.get("url") or "")
            key = url.rstrip("/").rsplit("/", 1)[-1] or str(via.get("source"))
            out[key] = {"package": via.get("name") or name, "severity": via.get("severity"),
                        "title": via.get("title"), "range": via.get("range"), "url": url}
    return out


def judge(report: dict, allow: list[dict], level: str,
          today: dt.date) -> tuple[list[str], list[str]]:
    """(the lines that fail, the lines said for the record)."""
    floor = LEVELS.index(level)
    excused = {a["id"]: a for a in allow}
    bad, said = [], []
    found = advisories(report)
    for key, a in sorted(found.items()):
        sev = a["severity"] if a["severity"] in LEVELS else "critical"
        if LEVELS.index(sev) < floor:
            continue
        what = f"{key} {a['package']} {a['range']} ({sev}): {a['title']}"
        ex = excused.get(key)
        if ex is None:
            bad.append(what)
        elif dt.date.fromisoformat(ex["until"]) < today:
            bad.append(f"{what}: excused until {ex['until']}, look at it again")
        else:
            said.append(f"excused until {ex['until']}: {what} ({ex['why']})")
    for key in sorted(set(excused) - set(found)):
        said.append(f"{key} is no longer reported: remove it from the exceptions")
    return bad, said


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dir", default=str(ROOT / "src/kranto/page/ui/web"))
    p.add_argument("--level", default="high", choices=LEVELS)
    p.add_argument("--allow", default=str(ROOT / "scripts/ci/npm_audit_allow.json"))
    p.add_argument("--report")
    p.add_argument("--today", default=dt.datetime.now(dt.UTC).date().isoformat())
    a = p.parse_args(argv)
    if a.report:
        text = Path(a.report).read_text()
    else:
        text = subprocess.run(["npm", "audit", "--json"], cwd=a.dir, capture_output=True,
                              text=True, check=False).stdout
    try:
        report = json.loads(text)
        if not isinstance(report, dict) or "error" in report:
            raise ValueError(report.get("error") if isinstance(report, dict) else report)
    except ValueError as exc:
        print(f"npm_audit: npm's report could not be read: {exc}", file=sys.stderr)
        return 2
    allow = json.loads(Path(a.allow).read_text())["exceptions"]
    bad, said = judge(report, allow, a.level, dt.date.fromisoformat(a.today))
    for line in said:
        print(f"npm_audit: {line}")
    for line in bad:
        print(f"npm_audit: FAIL {line}", file=sys.stderr)
    if not bad:
        print(f"npm_audit: nothing at {a.level} or above that is not excused")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
