#!/usr/bin/env python3
"""The release notes: the line's opening (``--kind``), an optional opening section (--intro: a
milestone's "What 0.4.0 is"), the pull requests merged since the previous release, then the
pins, the install lines and how to verify the wheels (by ``--shape``: the one wheel, or the
crossing's three).

``--kind`` (decide.py's,):

- ``nightly``: "**Nightly build** N toward X.Y.0", and that stable gets a build only when the
  maintainer chooses to make it stable;
- ``promotion``: the held line, "**Stable X.Y.0**, from nightly build vX.Y.0-devN", then
  **## Big changes** (the merged pull requests labelled ``big`` since the previous stable) and,
  with ``--stable-defaults FILE`` (``kranto settings stable-defaults --json`` of the build),
  **## Off on stable** (each setting whose stable default keeps the old behaviour);
- ``fix``: the held line, "**Fix for stable X.Y**", and the pull requests merged into
  ``release/X.Y`` since the previous stable.

The previous release is ``--previous TAG``'s (decide.py's ``previous``: the previous nightly
for a nightly, the previous stable otherwise), looked up by its tag; with none, the last
``FIRST_DAYS`` days. Pull requests come from ``gh pr list --search merged:>TS``, so ``gh`` must
be logged in (or ``GH_TOKEN`` set) for the repository.

``--commits FILE`` appends the cut's commit list (``guards.py log --markdown``:
``git log --oneline <previous>..<tag>``). A held release's line (``HELD_LINE``) is replaced by
``gate.py`` when the release goes to stable.

**The attribution guard.** The notes must carry no tool attribution (the owner's rule): the
script fails when the rendered text holds a co-author or session trailer line, a generated-with
footer naming the tool, or the tool vendor's noreply address (``ATTRIBUTION``). A title that
only names a tool ("Claude Code harness: ...") is a title, not attribution, and passes.

    notes.py --tag v0.7.0-dev12 --version 0.7.0.dev12 --kind nightly|promotion|fix
             [--shape final|compat] [--previous TAG] [--from-tag vX.Y.0-devN]
             [--stable-defaults FILE] [--repo OWNER/NAME] [--since ISO] [--until ISO]
             [--intro FILE] [--commits FILE] --out notes.md

Standard library plus ``gh``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import names  # noqa: E402

FIRST_DAYS = 7
# gate.py finds this line by its start and replaces it when it releases the build to stable
HELD_LINE = ("**Held for stable:** stable installs get it when the maintainer releases it, "
             "after rc_check passed on it.")
NIGHTLY_LINE = ("**Nightly build** {n} toward {base}: every merge on main. Stable gets a build "
                "only when the maintainer chooses to make it stable.")
DEV_TAG = re.compile(r"^v(\d+\.\d+\.\d+)-dev(\d+)$")
ATTRIBUTION = [
    re.compile(r"^\s*Co-Authored-By:", re.I | re.M),
    re.compile(r"^\s*Claude-Session:", re.I | re.M),
    re.compile(r"Generated with \[?Claude Code", re.I),
    re.compile(r"noreply@anthropic\.com", re.I),
]


class NotesError(Exception):
    pass


def attribution_hits(text: str) -> list[str]:
    """The lines of ``text`` that are tool attribution (empty when there is none)."""
    hits = []
    for line in text.splitlines():
        if any(p.search(line) for p in ATTRIBUTION):
            hits.append(line.strip())
    return hits


def pr_lines(prs: list[dict]) -> list[str]:
    """``- title (#N)``, oldest merge first; a title is one line, trimmed."""
    rows = sorted(prs, key=lambda p: (p.get("mergedAt") or "", p["number"]))
    return [f"- {' '.join(str(p['title']).split())} (#{p['number']})" for p in rows]


def install_lines(version: str, tag: str, repo: str, shape: str = "final") -> list[str]:
    product = names.product()
    if shape == "compat":
        return [f"This release is the crossing: it updates an install made before the rename "
                f"(its own `{product.COMMAND} update` or the old command's) and installs both "
                f"commands. A new install takes the next release: `sh install.sh` refuses this "
                "one."]
    wheel = wheel_name(version)
    d = product.DIST
    return [
        "```",
        f"gh release download {tag} -R {repo} -p '*.whl' -p SHA256SUMS -p manifest.json \\",
        f"  -D {d}-{version}",
        f"cd {d}-{version} && sha256sum -c SHA256SUMS",
        f'uv tool install --force --python 3.12 "{d}[connections,notify,mcp] @ ./{wheel}"',
        f"{product.COMMAND} up",
        "```",
        f"Or, on an installation that already runs: `{product.COMMAND} update`.",
    ]


def wheel_name(version: str) -> str:
    """The release's one wheel."""
    return f"{names.product().DIST}-{version}-py3-none-any.whl"


def pins_line(version: str, tag: str, shape: str = "final") -> str:
    if shape == "compat":
        dists = ", ".join(f"`{d} {version}`" for d in names.legacy().COMPAT_DISTS)
        return (f"- Three wheels under the names an install made before the rename updates "
                f"with, {dists}; the repository is tagged `{tag}`.")
    return f"- One wheel, `{names.product().DIST} {version}`; the repository is tagged `{tag}`."


def opening(kind: str, tag: str, from_tag: str = "") -> list[str]:
    """The line's own words at the top of the notes."""
    if kind == "nightly":
        m = DEV_TAG.match(tag)
        return [NIGHTLY_LINE.format(n=m[2], base=m[1]) if m else "**Nightly build.**", ""]
    if kind == "promotion":
        return [HELD_LINE, "", f"**Stable {tag.lstrip('v')}**, from nightly build {from_tag}: "
                "the maintainer chose to make it stable.", ""]
    if kind == "fix":
        minor = ".".join(tag.lstrip("v").split(".")[:2])
        return [HELD_LINE, "", f"**Fix for stable {minor}**: what merged into release/{minor} "
                "since the previous stable release.", ""]
    return []


def big_section(big: list[dict], off: list[dict]) -> list[str]:
    """A promotion's ## Big changes, and ## Off on stable when a setting's stable default keeps
    the old behaviour."""
    out = ["## Big changes", ""]
    out += pr_lines(big) or ["- None: no pull request since the previous stable is labelled big."]
    if off:
        out += ["", "## Off on stable", ""]
        out += [f"- `{s['key']}`: stable keeps `{s.get('default_stable')}` (nightly: "
                f"`{s.get('default')}`)" for s in off]
    return [*out, ""]


def sdk_version() -> str | None:
    """The cub SDK's version in this tree (``sdk/pyproject.toml``)."""
    import tomllib
    sdk = Path(__file__).resolve().parents[2] / "sdk" / "pyproject.toml"
    try:
        return tomllib.loads(sdk.read_text())["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return None


def render(version: str, tag: str, repo: str, prs: list[dict], since: str,
           first: bool = False, intro: str = "", commits: str = "", kind: str = "",
           from_tag: str = "", big: list[dict] | None = None, off: list[dict] | None = None,
           sdk: str | None = None, shape: str = "final") -> str:
    out = [f"{names.product().NAME} {version}.", ""]
    out += opening(kind, tag, from_tag)
    if kind == "promotion":
        out += big_section(big or [], off or [])
    if intro.strip():                     # a milestone's own words first, then the usual list
        out += [intro.strip(), "", "## Changes", ""]
    out.append(f"Changes merged since {since[:10]}"
               + (" (the first release: the last week's changes)" if first else "") + ".")
    out += ["", "## Merged", ""]
    out += pr_lines(prs) or ["- No changes."]
    if commits.strip():
        out += ["", commits.strip()]
    out += ["", "## Pins", "", pins_line(version, tag, shape)]
    if sdk:                               # what a cub author pins their tests to
        out.append(f"- Cub authors: this release's SDK is `bears-cub-sdk {sdk}`: `pip install "
                   f"\"bears-cub-sdk @ git+https://github.com/{repo}.git@{tag}#subdirectory=sdk\"`.")
    out += ["", "## Install", ""]
    out += install_lines(version, tag, repo, shape)
    out += ["", "## Verify", "",
            "`SHA256SUMS` lists each wheel's SHA-256; `sha256sum -c SHA256SUMS` checks them. "
            "`manifest.json` names the wheels, their hashes and sizes, and the commit they were "
            f"built from. `{names.product().COMMAND} update` checks both before it installs "
            "anything.", ""]
    return "\n".join(out)


def gh_json(*args: str) -> object:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise NotesError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "null")


def previous_release(repo: str, tag: str) -> dict | None:
    """The published release of ``tag`` (decide.py's previous), or None."""
    try:
        rel = gh_json("api", f"repos/{repo}/releases/tags/{tag}")
    except NotesError:
        return None
    return rel if isinstance(rel, dict) and not rel.get("draft") else None


def _when(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def merged_since(repo: str, since: str, until: str | None = None, base: str = "main",
                 label: str = "") -> list[dict]:
    """The pull requests into ``base`` merged after ``since`` and, with ``until`` (the time of
    the commit being cut, a squash merge's own), not after it: a promotion cut from a nightly's
    commits lists what it holds, not what merged since. ``label``: only those labelled so."""
    args = ["pr", "list", "-R", repo, "--state", "merged", "--limit", "300", "--base", base,
            "--search", f"merged:>{since}", "--json", "number,title,mergedAt"]
    if label:
        args += ["--label", label]
    prs = gh_json(*args) or []
    if until:
        last = _when(until) + timedelta(seconds=5)       # mergedAt and the commit's own time
        prs = [p for p in prs if p.get("mergedAt") and _when(p["mergedAt"]) <= last]
    return prs


# A nightly that rc_check must check is published with this line first (v0.6.0-dev3
# was published, and offered to every nightly install, before its rc_check ran). The updater's
# pick() never offers a release whose notes hold "**Do not install:**"; ``kranto update --to``
# still installs it, which is how rc_check checks it. gate.py offer removes the line after
# rc_check passed and the maintainer checked that no one asked to hold it.
CHECKING_LINE = ("**Do not install:** being checked (rc_check) before it is offered; "
                 "`gate.py offer {tag}` offers it once the check passed.")


def checking(text: str, tag: str) -> str:
    return CHECKING_LINE.format(tag=tag) + "\n\n" + text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tag", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--kind", default="", choices=("", "nightly", "promotion", "fix"),
                   help="decide.py's kind: the opening lines by line")
    p.add_argument("--previous", default="", help="the previous release's tag (decide.py's)")
    p.add_argument("--from-tag", default="", help="a promotion's nightly build")
    p.add_argument("--stable-defaults", type=Path,
                   help="kranto settings stable-defaults --json of the build (a promotion)")
    p.add_argument("--repo", default="", help="OWNER/NAME (default: public.toml's repo)")
    p.add_argument("--shape", default="final", choices=("final", "compat"))
    p.add_argument("--since", help="ISO time (default: the previous release's published_at)")
    p.add_argument("--until", help="ISO time of the commit being cut")
    p.add_argument("--intro", type=Path, help="Markdown that opens the notes (a milestone's "
                                              "'What X.Y is'), before the changes")
    p.add_argument("--commits", type=Path, help="the cut's commit list (guards.py log "
                                                "--markdown), appended after the changes")
    p.add_argument("--checking", action="store_true",
                   help="published before rc_check: open with CHECKING_LINE, so no install is "
                        "offered it until gate.py offer removes it")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)
    args.repo = args.repo or names.repo()
    try:
        first = False
        since = args.since
        if not since:
            prev = previous_release(args.repo, args.previous) if args.previous else None
            if prev and prev.get("published_at"):
                since = prev["published_at"]
            else:
                first = True
                since = (datetime.now(UTC) - timedelta(days=FIRST_DAYS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
        base = "main"
        if args.kind == "fix":
            base = "release/" + ".".join(args.tag.lstrip("v").split(".")[:2])
        big: list[dict] = []
        off: list[dict] = []
        if args.kind == "promotion":
            with contextlib.suppress(NotesError):     # before the label exists: none
                big += merged_since(args.repo, since, None, label="big")
            if args.stable_defaults and args.stable_defaults.is_file():
                rows = json.loads(args.stable_defaults.read_text() or "[]")
                off = [s for s in rows if isinstance(s, dict) and "key" in s] \
                    if isinstance(rows, list) else []
        text = render(args.version, args.tag, args.repo,
                      merged_since(args.repo, since, args.until, base),
                      since, first, args.intro.read_text() if args.intro else "",
                      args.commits.read_text() if args.commits else "", args.kind,
                      args.from_tag, big, off, sdk_version(), args.shape)
        if args.checking:
            text = checking(text, args.tag)
    except NotesError as exc:
        print(f"notes: {exc}", file=sys.stderr)
        return 2
    hits = attribution_hits(text)
    if hits:
        print("notes: the release notes carry tool attribution; fix the pull request titles "
              "and run again:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        return 1
    args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
