#!/usr/bin/env python3
"""A cut that must carry a commit, and the commit list a release is read by (C4: 0.5.21 was cut
while its fix's checks on main were still running, so it took the
newest green commit before the fix and shipped nothing; it was called done unread).

    guards.py wait REPO SHA CHECKOUT [--base BRANCH] [--timeout S] [--interval S]
        waits, bounded and saying so, until SHA is in CHECKOUT's origin/BRANCH (main, or a
        stable line's release/X.Y) and every check on it is green (it fetches the branch as it
        waits); exit 0, 1 red, 4 timed out
    guards.py contains CHECKOUT REF SHA
        exit 0 when REF (a head or a tag) holds SHA, 1 when it does not
    guards.py log PREVIOUS NEW NAME=CHECKOUT... [--markdown]
        ``git log --oneline PREVIOUS..NEW`` of each checkout, plain or as the notes' section
    guards.py previous TAG < tags
        the release before TAG on its line, from the tags on stdin (one a line): for a nightly
        (vX.Y.0-devN) the newest nightly before it, else the newest stable before it; for a
        stable tag the newest stable before it (rc_check.sh's default previous)
    guards.py big REPO PR [--labels a,b] | big --diff FILE
        the hints that a pull request may be ``big`` (it changes what a person
        sees or must do, for everyone): a setting's default changed, a config default changed,
        a route or a page removed, a migration that drops or renames, a command removed, a
        help.md heading gone. Exit 0 with no hint or with the PR labelled ``big`` or
        ``not-big``; exit 3 when a hint tripped and it carries neither (merge_when_green.sh
        refuses the merge then)
    guards.py jobs REPO PR
        the checks a merge of that pull request requires (``merge_when_green.sh --require``):
        the page's seven; the server's test and gitleaks, and sandbox when the pull request
        touches a path of ``.github/workflows/cubs-sandbox.yml`` (the cub runtime's closure)

``cut_local.sh --must-include REPO@SHA`` runs ``wait`` before it picks a head and ``contains``
after (and, with ``--from-tag``, ``contains`` on the rc's tag instead of waiting). The empty
release is refused by ``decide.py`` (nothing since the previous tag in either repo).
Standard library plus git and gh (through ``scripts/ci/checks.py``).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

GREEN, RED, TIMED_OUT = 0, 1, 4
SHA = re.compile(r"^[0-9a-f]{7,40}$")
NAMES = ("kranto", "kranto.page")


class GuardError(Exception):
    pass


def parse_must(spec: str) -> tuple[str, str]:
    """``the server@4b1f506`` or ``iddv/kranto@4b1f506`` -> ("kranto", "4b1f506")."""
    repo, sep, sha = spec.partition("@")
    name = repo.rsplit("/", 1)[-1]
    if not sep or name not in NAMES or not SHA.match(sha.lower()):
        raise GuardError(f"--must-include takes the server@SHA or the page@SHA (7 to 40 hex), "
                         f"not '{spec}'")
    return name, sha.lower()


def git(checkout: Path | str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True,
                          check=False)


def resolve(checkout: Path | str, sha: str, run=git) -> str | None:
    """The full commit id of ``sha`` in the checkout, or None when it has no such commit."""
    r = run(checkout, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def contains(checkout: Path | str, ref: str, sha: str, run=git) -> bool:
    full = resolve(checkout, sha, run)
    return full is not None and run(checkout, "merge-base", "--is-ancestor", full,
                                    ref).returncode == 0


def _checks():
    path = Path(__file__).resolve().parent.parent / "ci" / "checks.py"
    spec = importlib.util.spec_from_file_location("release_checks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def where(repo: str, checkout: Path | str, sha: str, *, run=git, base: str = "main",
          green: Callable[[str, str], tuple[int, str]] | None = None) -> tuple[int | None, str]:
    """One look: (GREEN | RED | None for "not yet", why). Fetches ``origin <base>`` first."""
    f = run(checkout, "fetch", "--quiet", "origin",
            f"+refs/heads/{base}:refs/remotes/origin/{base}")
    if f.returncode != 0:
        return None, f"could not fetch {repo} {base} ({(f.stderr or '').strip()[:120]})"
    full = resolve(checkout, sha, run)
    if full is None:
        return None, f"{sha} is not in {repo} yet"
    if run(checkout, "merge-base", "--is-ancestor", full, f"origin/{base}").returncode != 0:
        return None, (f"{sha} is not in {repo} {base} yet (a squash merge makes a new commit: "
                      "name the merge commit, not the pull request's head)")
    if green is None:
        checks = _checks()
        green = lambda r, s: checks.green(r, s)  # noqa: E731
    code, why = green(repo, full)
    if code == GREEN:
        return GREEN, f"{repo}@{full[:10]} is in {base} and green"
    if code == RED:
        return RED, f"{repo}@{full[:10]} is in {base} and its checks failed: {why}"
    return None, f"{repo}@{full[:10]} is in {base}; its checks are not done: {why}"


def wait(repo: str, checkout: Path | str, sha: str, *, base: str = "main",
         timeout: float = 2700,
         interval: float = 30, run=git, green=None, sleep=time.sleep, now=time.monotonic,
         say=print) -> tuple[int, str]:
    """Poll ``where`` until GREEN or RED, at most ``timeout`` seconds; say each new state with
    the time left."""
    deadline = now() + timeout
    said = None
    while True:
        code, why = where(repo, checkout, sha, run=run, base=base, green=green)
        if code is not None:
            return code, why
        left = deadline - now()
        if left <= 0:
            return TIMED_OUT, f"gave up after {timeout:g}s: {why}"
        if why != said:
            say(f"waiting for {repo}@{sha[:10]} (up to {left:.0f}s more): {why}")
            said = why
        sleep(min(interval, max(left, 0)))


def log(previous: str, new: str, checkouts: dict[str, Path | str], *, markdown: bool = False,
        run=git) -> str:
    """Each checkout's ``git log --oneline previous..new``; an empty one says so."""
    out = ["## Commits", "", f"`git log --oneline {previous}..{new}` in each repository:"] \
        if markdown else []
    for name, checkout in checkouts.items():
        r = run(checkout, "log", "--oneline", "--no-decorate", f"{previous}..{new}")
        if r.returncode != 0:
            raise GuardError(f"git log {previous}..{new} in {name}: {r.stderr.strip()[:200]}")
        lines = r.stdout.strip().splitlines()
        if markdown:
            out += ["", f"{name}:", "", "```", *(lines or ["(no commits)"]), "```"]
        else:
            out += [f"{name} {previous}..{new}: {len(lines)} commit(s)",
                    *(f"  {ln}" for ln in lines)]
    return "\n".join(out) + "\n"


_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(rc|dev)(\d+))?$")


def tag_key(tag: str) -> tuple | None:
    """dev < rc < final within a base, as the updater sorts; None for another tag."""
    m = _TAG.match(tag.strip())
    if not m:
        return None
    rank = {"dev": 0, "rc": 1, None: 2}[m[4]]
    return (int(m[1]), int(m[2]), int(m[3]), rank, int(m[5] or 0))


def previous(tag: str, tags: list[str]) -> str | None:
    """The release before ``tag`` on its line (see the module's ``previous``)."""
    me = tag_key(tag)
    if me is None:
        return None
    older = sorted((t.strip() for t in tags if (k := tag_key(t)) and k < me), key=tag_key)
    stable = [t for t in older if tag_key(t)[3] == 2]
    if "-dev" in tag:
        dev = [t for t in older if tag_key(t)[3] == 0]
        return (dev or stable or [None])[-1]
    return (stable or [None])[-1]


# -- big -----------------------------------------------------------------------

BIG_LABELS = ("big", "not-big")
NEEDS_LABEL = 3


def _files(diff: str) -> list[tuple[str, bool, list[str], list[str]]]:
    """(path, deleted, removed lines, added lines) for each file of a unified diff."""
    out: list[tuple[str, bool, list[str], list[str]]] = []
    path, deleted, rem, add = None, False, [], []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            if path is not None:
                out.append((path, deleted, rem, add))
            parts = line.split(" b/", 1)
            path, deleted, rem, add = (parts[1] if len(parts) > 1 else line), False, [], []
        elif line.startswith("deleted file mode"):
            deleted = True
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("-"):
            rem.append(line[1:])
        elif line.startswith("+"):
            add.append(line[1:])
    if path is not None:
        out.append((path, deleted, rem, add))
    return out


_SETTING = re.compile(r'"([\w.]+)"\s*:\s*Setting\(\s*"(\w+)"\s*,\s*([^,)]+)')
_SETTING_KW = re.compile(r"\b(default|default_stable)\s*=\s*([^,)]+)")
_CONFIG_FIELD = re.compile(r"^    (\w+): [^=]+ = (.+?)\s*(#.*)?$")
_ROUTE = re.compile(r'Route\("([^"]+)"')
_SUBPARSER = re.compile(r'add_parser\("([\w-]+)"')
_HEADING = re.compile(r"^#{1,4} +(.+?)\s*(\{#[\w-]+\})?\s*$")
_DROP = re.compile(r"\b(DROP\s+(TABLE|COLUMN|INDEX|VIEW)|RENAME\s+(TO|COLUMN)"
                   r"|ALTER\s+TABLE\s+\S+\s+DROP)\b", re.I)


def big_hints(diff: str) -> list[str]:
    """What in a pull request's diff may make it ``big``, one line each."""
    hints = []
    for path, deleted, rem, add in _files(diff):
        if path.endswith(".py"):
            was = {m[1]: (m[3].strip(), _SETTING_KW.findall(ln)) for ln in rem
                   if (m := _SETTING.search(ln))}
            now = {m[1]: (m[3].strip(), _SETTING_KW.findall(ln)) for ln in add
                   if (m := _SETTING.search(ln))}
            for key, before in was.items():
                if key in now and now[key] != before:
                    hints.append(f"{path}: the default of {key} changed")
        if path.endswith("src/kranto/config.py"):
            was = {m[1]: m[2] for ln in rem if (m := _CONFIG_FIELD.match(ln))}
            now = {m[1]: m[2] for ln in add if (m := _CONFIG_FIELD.match(ln))}
            for key, before in was.items():
                if key in now and now[key] != before:
                    hints.append(f"{path}: the default of {key} changed ({before} -> {now[key]})")
        if re.search(r"(^|/)web/[\w]+_api\.py$|(^|/)web/app\.py$"
                     r"|src/kranto/page/.*api.*\.py$", path):
            gone = {m[1] for ln in rem if (m := _ROUTE.search(ln))} - {
                m[1] for ln in add if (m := _ROUTE.search(ln))
            }
            hints += [f"{path}: the route {r} is removed" for r in sorted(gone)]
        if (
            deleted
            and "/ui/web/src/pages/" in path
            and path.endswith(".svelte")
            and not path.endswith(".test.ts")
        ):
            hints.append(f"{path}: a page is removed")
        if re.search(r"(store|ledger|migrations?)[\w/]*\.(py|sql)$", path):
            hints += [
                f"{path}: a migration that drops or renames ({ln.strip()[:60]})"
                for ln in add
                if _DROP.search(ln)
            ][:1]
        if path.endswith(("src/kranto/launcher.py", "src/kranto/cli.py", "src/kranto/page/cli.py")):
            gone = {m[1] for ln in rem if (m := _SUBPARSER.search(ln))} - {
                m[1] for ln in add if (m := _SUBPARSER.search(ln))
            }
            hints += [f"{path}: the command {c} is removed" for c in sorted(gone)]
        if path.endswith("help.md"):
            gone = {m[1] for ln in rem if (m := _HEADING.match(ln))} - {
                m[1] for ln in add if (m := _HEADING.match(ln))
            }
            hints += [f'{path}: the heading "{h}" is gone' for h in sorted(gone)]
    return hints


def big_verdict(hints: list[str], labels: list[str]) -> tuple[int, str]:
    """(0 or NEEDS_LABEL, what to say)."""
    if not hints:
        return 0, "big: no hint in the diff"
    have = [lb for lb in labels if lb in BIG_LABELS]
    shown = "; ".join(hints[:4]) + (f"; and {len(hints) - 4} more" if len(hints) > 4 else "")
    if have:
        return 0, f"big: labelled {have[0]} ({shown})"
    return NEEDS_LABEL, (
        f"{shown}: label it big (it changes what a person sees or must do, "
        "for everyone: say which setting keeps the old behaviour on stable, "
        "or that none does), or not-big with a sentence in the body saying why"
    )


def pr_labels(repo: str, pr: str) -> list[str]:
    r = subprocess.run(
        ["gh", "pr", "view", pr, "-R", repo, "--json", "labels", "-q", ".labels[].name"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise GuardError(f"gh pr view {repo}#{pr}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.split()


def pr_diff(repo: str, pr: str) -> str:
    r = subprocess.run(
        ["gh", "pr", "diff", pr, "-R", repo], capture_output=True, text=True, check=False
    )
    if r.returncode != 0:
        said = (r.stderr or r.stdout).strip()
        if "exceeded the maximum number of files" in said:  # GitHub's diff stops at 300
            return pr_diff_by_files(repo, pr)
        raise GuardError(f"gh pr diff {repo}#{pr}: {said[:200]}")
    return r.stdout


def pr_diff_by_files(repo: str, pr: str) -> str:
    """The diff of a pull request too large for ``gh pr diff``, from the paged files API (up to
    3000 files, each with its patch; a file too large for a patch has none, as on the site)."""
    r = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{pr}/files?per_page=100",
            "--jq",
            ".[] | @json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise GuardError(f"gh api {repo}#{pr} files: {(r.stderr or r.stdout).strip()[:200]}")
    out = []
    for line in r.stdout.splitlines():
        f = json.loads(line)
        old = f.get("previous_filename") or f["filename"]
        out.append(f"diff --git a/{old} b/{f['filename']}")
        if f.get("status") == "removed":
            out.append("deleted file mode 100644")
        out += [f"--- a/{old}", f"+++ b/{f['filename']}"]
        out += (f.get("patch") or "").splitlines()
    return "\n".join(out) + "\n"


# One workflow, one list: every pull request needs all of ci.yml's jobs, the sandbox included
REQUIRED = ["test", "fast", "slow", "browser", "frontend", "lint", "gitleaks", "sandbox"]


def required_jobs(name: str = "", files: list[str] | None = None) -> list[str]:
    """The checks a pull request merges with: the same eight for every change."""
    return list(REQUIRED)


def pr_files(repo: str, pr: str) -> list[str]:
    r = subprocess.run(
        ["gh", "pr", "view", pr, "-R", repo, "--json", "files", "-q", ".files[].path"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise GuardError(f"gh pr view {repo}#{pr}: {(r.stderr or r.stdout).strip()[:200]}")
    return r.stdout.split()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait")
    w.add_argument("repo")
    w.add_argument("sha")
    w.add_argument("checkout", type=Path)
    w.add_argument("--base", default="main", help="the branch: main or release/X.Y")
    w.add_argument("--timeout", type=float, default=2700)
    w.add_argument("--interval", type=float, default=30)
    c = sub.add_parser("contains")
    c.add_argument("checkout", type=Path)
    c.add_argument("ref")
    c.add_argument("sha")
    lg = sub.add_parser("log")
    lg.add_argument("previous")
    lg.add_argument("new")
    lg.add_argument("checkouts", nargs="+", help="NAME=CHECKOUT")
    lg.add_argument("--markdown", action="store_true")
    j = sub.add_parser("jobs")
    j.add_argument("repo")
    j.add_argument("pr")
    pv = sub.add_parser("previous")
    pv.add_argument("tag")
    b = sub.add_parser("big")
    b.add_argument("repo", nargs="?")
    b.add_argument("pr", nargs="?")
    b.add_argument("--diff", type=Path, help="a unified diff file instead of the PR's")
    b.add_argument("--labels", default=None, help="the PR's labels, comma separated")
    a = p.parse_args(argv)
    try:
        if a.cmd == "big":
            if a.diff is None and not (a.repo and a.pr):
                raise GuardError("big takes REPO PR, or --diff FILE")
            diff = a.diff.read_text() if a.diff else pr_diff(a.repo, a.pr)
            labels = (
                a.labels.split(",")
                if a.labels is not None
                else (pr_labels(a.repo, a.pr) if a.repo and a.pr else [])
            )
            code, said = big_verdict(big_hints(diff), labels)
            print(said, file=sys.stdout if code == 0 else sys.stderr)
            return code
        if a.cmd == "previous":
            print(previous(a.tag, sys.stdin.read().split()) or "")
            return 0
        if a.cmd == "jobs":
            print(",".join(required_jobs(a.repo, pr_files(a.repo, a.pr))))
            return 0
        if a.cmd == "wait":
            # flushed: a cut's log and hotfix.sh show the waiting while it waits
            code, why = wait(
                a.repo,
                a.checkout,
                a.sha,
                base=a.base,
                timeout=a.timeout,
                interval=a.interval,
                say=lambda s: print(s, flush=True),
            )
            print(why, file=sys.stdout if code == GREEN else sys.stderr)
            return code
        if a.cmd == "contains":
            ok = contains(a.checkout, a.ref, a.sha)
            print(
                f"{a.ref} {'holds' if ok else 'does NOT hold'} {a.sha}",
                file=sys.stdout if ok else sys.stderr,
            )
            return 0 if ok else 1
        pairs = dict(s.split("=", 1) for s in a.checkouts)
        sys.stdout.write(log(a.previous, a.new, pairs, markdown=a.markdown))
        return 0
    except GuardError as e:
        print(f"guards: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
