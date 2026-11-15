#!/usr/bin/env python3
"""Fail on a tool-attribution line in the commits a push or pull request brings, and in the
pull request's title and body (the owner's rule: no co-author trailer naming an AI tool, no
session link, no "generated with" footer, in any repo).

    no_attribution.py RANGE            e.g. BASE..HEAD, as the gitleaks job computes it
    no_attribution.py --all            every commit since SINCE (older history is the
                                       owner's decision, not rewritten here)

The pull request's title and body are read from the environment (``PR_TITLE``, ``PR_BODY``)
when set: a squash merge's commit is the title and the commits' messages. Prints one line per
hit (the commit or "pull request", and the line) and exits 1; exits 0 when clean. Standard
library only; the same file is in the server and the page.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

SINCE = "2026-10-09"          # the rule has held in both repos' commits since this day
PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"co-authored-by:\s*claude",
    r"claude-session:",
    r"generated\s+with\s+\[?claude",
    r"claude\.ai/code",
)]


def hits(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if any(p.search(ln) for p in PATTERNS)]


def commits(rev: str, cwd: str | None = None) -> list[tuple[str, str]]:
    """(short hash, message) of each commit in ``rev`` (a range, or ``--all``)."""
    args = ["--all", f"--since={SINCE}"] if rev == "--all" else [rev]
    out = subprocess.run(["git", "log", "--format=%h%x00%B%x01", *args], cwd=cwd,
                         capture_output=True, text=True, check=True).stdout
    found = []
    for rec in out.split("\x01"):
        if "\x00" in rec:
            sha, msg = rec.split("\x00", 1)
            found.append((sha.strip(), msg))
    return found


def main(argv: list[str], env=os.environ, cwd: str | None = None) -> int:
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    found = commits(argv[0], cwd)
    bad = [(sha, h) for sha, msg in found for h in hits(msg)]
    pr = "\n".join(env.get(k, "") for k in ("PR_TITLE", "PR_BODY"))
    bad += [("pull request", h) for h in hits(pr)]
    for where, line in bad:
        print(f"attribution line in {where}: {line}")
    if bad:
        print("No tool attribution in commits or pull requests: reword the commit "
              "(git commit --amend, or a rebase) and the pull request, then push again.")
        return 1
    also = " and the pull request" if pr.strip() else ""
    print(f"no attribution lines in {len(found)} commit(s){also}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
