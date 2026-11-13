#!/usr/bin/env python3
"""Decide the next Kranto release: one version for the server, the page and Kranto (lockstep), on
one of the two lines (the owner's decisions of 2026-10-24).

- **nightly** (the default): every cut from ``main``. Numbered toward the next stable minor:
  while the newest stable tag is ``v0.6.x`` nightly is ``v0.7.0-devN`` (wheel ``0.7.0.devN``),
  ``N`` the newest existing dev tag for that target plus one, never a date. ``previous`` is the
  nightly before it for the same target, else the newest stable tag.
- **promotion** (``--from-tag vX.Y.0-devN``): the owner's choice to make a nightly build stable.
  Version ``X.Y.0``, cut from the dev tag's own commits; ``previous`` is the newest stable tag;
  ``branch`` is the ``release/X.Y`` the cut creates in both repos. Time never decides it.
- **stable** (``--line stable``): a fix cut from ``release/X.Y`` (the checkout's HEAD), the
  newest stable minor's patch plus one; ``previous`` the newest tag of that minor.

Tags read: ``vX.Y.Z``, ``vX.Y.0-devN`` and the retired ``vX.Y.Z-rcN`` (still parsed, never
cut: ``--prerelease rcN`` is refused).

With ``--repo`` and ``--brb-repo`` (``cut_local.sh`` passes both), a release is cut only when
every check on both commits being cut is green (``scripts/ci/checks.py``).

**rc_check** (``rc_check.required``): the release's changes since ``previous`` touch the update,
the install, the packaging, a migration or the service unit (``RC_PATHS``), or it is a
promotion (always). The check runs on the published build itself (``rc_check.sh TAG
PREVIOUS``) before the owner's install takes a nightly, and before a held stable is released.

**Never an empty release**: when neither head has a commit since ``previous``,
nothing is cut.

Prints one JSON object: ``line``, ``version`` (PEP 440: ``0.7.0.dev12``), ``tag``
(``v0.7.0-dev12``), ``previous``, ``prerelease`` (a nightly), ``held`` (a stable or promotion:
published as a prerelease until it is released), ``branch``, ``commits``, ``since``,
``rc_check``. Standard library only.

    decide.py --afk DIR --brb DIR [--line nightly|stable] [--from-tag vX.Y.0-devN] [--plan]
              [--repo OWNER/NAME --brb-repo OWNER/NAME]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(rc|dev)(\d+))?$")
DEV_TAG = re.compile(r"^v(\d+)\.(\d+)\.0-dev(\d+)$")
# The version every package carried before the first tag.
# with no tag yet: the first nightly is v0.7.0-dev1, above every release an install may run
BEFORE_TAGS = (0, 6, 0)
LINES = ("nightly", "stable")


class DecideError(Exception):
    pass


def parse(tag: str) -> tuple[int, int, int, str | None, int | None] | None:
    """``v0.2.0`` -> (0, 2, 0, None, None); ``v0.7.0-dev12`` -> (0, 7, 0, "dev", 12);
    ``v0.2.0-rc1`` -> (0, 2, 0, "rc", 1); anything else None."""
    m = TAG.match(tag.strip())
    if not m:
        return None
    return (int(m[1]), int(m[2]), int(m[3]), m[4], int(m[5]) if m[5] else None)


def newest_stable(tags: list[str]) -> tuple[int, int, int] | None:
    stable = [p[:3] for p in map(parse, tags) if p and p[3] is None]
    return max(stable) if stable else None


def tag_of(base: tuple[int, int, int]) -> str:
    return "v" + ".".join(map(str, base))


def nightly_target(tags: list[str]) -> tuple[int, int, int]:
    """The stable minor nightly builds toward: the newest stable tag's minor plus one."""
    s = newest_stable(tags) or BEFORE_TAGS
    return (s[0], s[1] + 1, 0)


def dev_numbers(tags: list[str], target: tuple[int, int, int]) -> list[int]:
    return sorted(p[4] for p in map(parse, tags)
                  if p and p[3] == "dev" and p[:3] == target and p[4] is not None)


def next_nightly(tags: list[str]) -> tuple[str, str, str | None]:
    """(PEP 440 version, tag, previous) of the next nightly build."""
    target = nightly_target(tags)
    have = dev_numbers(tags, target)
    n = (have[-1] if have else 0) + 1
    base = ".".join(map(str, target))
    stable = newest_stable(tags)
    previous = f"v{base}-dev{have[-1]}" if have else (tag_of(stable) if stable else None)
    return f"{base}.dev{n}", f"v{base}-dev{n}", previous


def promotion(tags: list[str], from_tag: str) -> tuple[str, str, str | None, str]:
    """(version, tag, previous, branch) of the promotion of a nightly build to stable."""
    m = DEV_TAG.match(from_tag.strip())
    if not m:
        raise DecideError(f"a promotion is cut from a nightly build's tag (vX.Y.0-devN), not "
                          f"{from_tag!r}")
    base = (int(m[1]), int(m[2]), 0)
    tag = tag_of(base)
    if tag in tags:
        raise DecideError(f"{tag} already exists: {from_tag} was promoted before")
    stable = newest_stable(tags)
    if stable is not None and base <= stable:
        raise DecideError(f"{from_tag} builds toward {tag}, not newer than the stable "
                          f"{tag_of(stable)}")
    return ".".join(map(str, base)), tag, tag_of(stable) if stable else None, \
        f"release/{base[0]}.{base[1]}"


def next_fix(tags: list[str]) -> tuple[str, str, str, str]:
    """(version, tag, previous, branch) of the next fix on the stable line."""
    stable = newest_stable(tags)
    if stable is None:
        raise DecideError("there is no stable release yet, so no stable line to fix")
    minor = stable[:2]
    patch = max(p[2] for p in map(parse, tags) if p and p[3] is None and p[:2] == minor)
    base = (*minor, patch + 1)
    return ".".join(map(str, base)), tag_of(base), tag_of((*minor, patch)), \
        f"release/{minor[0]}.{minor[1]}"


# What the scratch rc check (rc_check.sh: install the previous release, update, roll back,
# update again) can find a fault in: the paths of each repo whose change needs it.
RC_PATHS = {
    "kranto": (
        "src/kranto/update/",
        "src/kranto/launcher.py",
        "src/kranto/store.py",
        "scripts/release/",
        "packages/kranto/",
        "pyproject.toml",
    ),
    "kranto.page": (
        "src/kranto/page/loop/ledger.py",
        "src/kranto/page/den/store.py",
        "scripts/build_ui.py",
        "pyproject.toml",
    ),
}


def rc_reasons(repo: Path, name: str, previous: str | None) -> list[str]:
    """The files changed since ``previous`` under ``RC_PATHS[name]``; none before the first
    release, which has nothing to update from."""
    if previous is None or previous not in tags_of(repo):
        return []
    changed = git(repo, "diff", "--name-only", f"{previous}..HEAD").splitlines()
    return [f"{name}: {f}" for f in changed if f.startswith(RC_PATHS[name])]


def commits_since(repo: Path, previous: str | None) -> int | None:
    """Commits on HEAD since ``previous`` (a tag); None before the first release or when this
    repo lacks the tag (nothing to compare with)."""
    if previous is None or previous not in tags_of(repo):
        return None
    return int(git(repo, "rev-list", "--count", f"{previous}..HEAD"))


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise DecideError(f"git {' '.join(args)} in {repo}: {r.stderr.strip()}")
    return r.stdout.strip()


def tags_of(repo: Path) -> list[str]:
    return [t for t in git(repo, "tag", "--list", "v*").splitlines() if parse(t)]


def _checks():
    """scripts/ci/checks.py, loaded by path (this script runs from a checkout)."""
    path = Path(__file__).resolve().parent.parent / "ci" / "checks.py"
    spec = importlib.util.spec_from_file_location("release_checks", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gh_green(repo: str, sha: str) -> tuple[bool, str]:
    """Every check on ``sha`` in ``repo`` is green (through gh)."""
    checks = _checks()
    try:
        code, why = checks.green(repo, sha)
    except checks.ChecksError as e:
        raise DecideError(str(e)) from e
    return code == checks.GREEN, why


# the page's web UI is built by Vite at release (build.sh); the machine cutting needs this Node.
NODE_FLOOR = (22, 12)


def node_version() -> tuple[int, int] | None:
    """The ``node`` on PATH as (major, minor), or None."""
    try:
        out = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return None
    m = re.fullmatch(r"v(\d+)\.(\d+)\.\d+", out)
    return (int(m[1]), int(m[2])) if m else None


def decide(
    afk: Path,
    brb: Path,
    *,
    line: str = "nightly",
    from_tag: str = "",
    prerelease: str = "",
    green: Callable[[str, str], tuple[bool, str]] | None = None,
    repos: tuple[str, str] = ("iddv/kranto", "iddv/kranto"),
    node: Callable[[], tuple[int, int] | None] = node_version,
    plan: bool = False,
) -> dict:
    """``green(repo, sha) -> (ok, why)``: when given, both commits must be green. A the page
    with a web UI (``src/kranto/page/ui/web``) needs ``node()`` at NODE_FLOOR or newer to build it.
    ``plan`` is accepted for hotfix.sh: nothing is refused for an rc any more."""
    if prerelease:
        raise DecideError(
            "--prerelease rcN is retired: every nightly is a prerelease and is "
            "checked on itself (rc_check.sh TAG), so cut it with no flag"
        )
    if line not in LINES:
        raise DecideError(f"line must be nightly or stable, not {line!r}")
    if (brb / "src" / "kranto" / "page" / "ui" / "web" / "package.json").is_file():
        v = node()
        if v is None or v < NODE_FLOOR:
            found = ".".join(map(str, v)) if v else "none"
            raise DecideError(
                f"building the page's web UI needs Node "
                f"{'.'.join(map(str, NODE_FLOOR))} or newer on this machine "
                f"(found {found}); users of the release never need it"
            )
    tags = sorted(set(tags_of(afk)) | set(tags_of(brb)))
    branch = None
    if from_tag:
        version, tag, previous, branch = promotion(tags, from_tag)
        line, kind = "stable", "promotion"
    elif line == "stable":
        version, tag, previous, branch = next_fix(tags)
        kind = "fix"
    else:
        version, tag, previous = next_nightly(tags)
        kind = "nightly"
    if tag in tags:
        raise DecideError(f"{tag} already exists")
    since = {"kranto": commits_since(afk, previous), "kranto.page": commits_since(brb, previous)}
    if previous and all(n == 0 for n in since.values()):
        raise DecideError(
            f"nothing was merged since {previous} in either repo (both heads are "
            f"at {previous}): an empty release is refused"
        )
    why = rc_reasons(afk, "kranto", previous) + rc_reasons(brb, "kranto.page", previous)
    if kind == "promotion":
        why = [f"a promotion to stable ({from_tag} -> {tag})", *why]
    commits = {
        "kranto": git(afk, "rev-parse", "HEAD"),
        "kranto.page": git(brb, "rev-parse", "HEAD"),
    }
    if green is not None:
        for (name, sha), repo in zip(commits.items(), repos, strict=True):
            ok, said = green(repo, sha)
            if not ok:
                raise DecideError(
                    f"{name} at {sha[:10]} is not green ({said}); a release is "
                    "cut only from commits whose checks all passed"
                )
    return {
        "release": True,
        "line": line,
        "kind": kind,
        "version": version,
        "tag": tag,
        "previous": previous,
        "from": from_tag or None,
        "branch": branch,
        "prerelease": kind == "nightly",
        "held": kind != "nightly",
        "since": since,
        "rc_check": {"required": bool(why), "why": why},
        "commits": commits,
        "checked": green is not None,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--afk", required=True, type=Path, help="the the server checkout")
    p.add_argument("--brb", required=True, type=Path, help="the the page checkout")
    p.add_argument("--line", default="nightly", choices=LINES)
    p.add_argument("--from-tag", default="", help="vX.Y.0-devN: promote this nightly build")
    p.add_argument("--prerelease", default="", help="retired (refused with the reason)")
    p.add_argument("--bump", default="", help="retired: the line decides the number")
    p.add_argument("--plan", action="store_true", help="accepted for hotfix.sh")
    p.add_argument(
        "--stable-branch",
        action="store_true",
        help="print the stable line's branch (release/X.Y) and stop",
    )
    p.add_argument("--repo", default="", help="the server's OWNER/NAME: check its commit is green")
    p.add_argument(
        "--brb-repo", default="", help="the page's OWNER/NAME: check its commit is green"
    )
    args = p.parse_args(argv)
    if bool(args.repo) != bool(args.brb_repo):
        p.error("--repo and --brb-repo go together")
    try:
        if args.stable_branch:
            print(next_fix(sorted(set(tags_of(args.afk)) | set(tags_of(args.brb))))[3])
            return 0
        result = decide(
            args.afk,
            args.brb,
            line=args.line,
            from_tag=args.from_tag.strip(),
            prerelease=args.prerelease.strip(),
            green=gh_green if args.repo else None,
            repos=(args.repo, args.brb_repo),
            plan=args.plan,
        )
    except DecideError as exc:
        print(f"decide: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
