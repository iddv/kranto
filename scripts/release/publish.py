#!/usr/bin/env python3
"""Write the release manifest, then publish: push the tags and create the GitHub Release.

``manifest``: ``dist/manifest.json`` from the wheels in ``dist/`` and ``SHA256SUMS``, checked
on the way: exactly the three distributions (Kranto, the server, the page), one version, every
hash in ``SHA256SUMS`` matching the file.

``publish``: push the tag in both checkouts (their ``origin``: the owner's own remotes), then
``gh release create --draft`` with the five assets (and ``install.sh``), then publish the draft, so
``releases/latest`` never shows a release whose assets are still uploading. Re-running after a
failure is safe: a tag already on the remote at the same commit is not pushed again, and an
existing draft gets its assets re-uploaded.

``--hold`` (a stable release or a promotion,) publishes it as a GitHub
prerelease: installs on the stable channel and the installer read only non-prereleases, so it
reaches them when ``gate.py promote --now`` releases it after rc_check. Its tag stays
``vX.Y.Z``. ``--prerelease`` is a nightly build. The title says the line: "Kranto 0.7.0.dev12
(nightly)", "Kranto 0.7.1 (stable)", "Kranto 0.7.0" (a promotion: a new stable minor).

    publish.py manifest --dist DIR --version V --tag T --repo R --afk DIR --brb DIR
    publish.py publish  --dist DIR --version V --tag T --repo R --afk DIR --brb DIR
                        --notes FILE [--prerelease | --hold]

Standard library plus ``git`` and ``gh``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

NAMES = ("kranto", "kranto.page")
WHEEL = re.compile(r"^(kranto|kranto.page)-([^-]+)-py3-none-any\.whl$")


class PublishError(Exception):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sums(path: Path) -> dict[str, str]:
    """``SHA256SUMS`` (``<hash>  <name>`` lines, as sha256sum writes them) as {name: hash}."""
    out = {}
    for line in path.read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip().lstrip("*")] = digest.lower()
    return out


def check_set(dist: Path, version: str) -> list[Path]:
    """The three wheels in ``dist``, or why the set is wrong."""
    wheels = sorted(dist.glob("*.whl"))
    found = {}
    for w in wheels:
        m = WHEEL.match(w.name)
        if not m:
            raise PublishError(f"unexpected file in the set: {w.name}")
        if m[2] != version:
            raise PublishError(f"{w.name} is not version {version}")
        found[m[1]] = w
    if set(found) != set(NAMES):
        raise PublishError(f"the set must be exactly {', '.join(NAMES)}; found "
                           f"{', '.join(sorted(found)) or 'nothing'}")
    sums = read_sums(dist / "SHA256SUMS")
    for name in NAMES:
        w = found[name]
        if sums.get(w.name) != sha256(w):
            raise PublishError(f"{w.name}: its hash does not match SHA256SUMS")
    return [found[n] for n in NAMES]


def manifest(dist: Path, version: str, tag: str, repo: str, commits: dict[str, str],
             now: datetime | None = None) -> dict:
    wheels = check_set(dist, version)
    return {
        "version": version, "tag": tag,
        "published_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": ">=3.12",
        "pins": {"kranto": version, "kranto.page": version},
        "commits": commits,
        "wheels": [{"name": w.name, "sha256": sha256(w), "size": w.stat().st_size}
                   for w in wheels],
        "notes_url": f"https://github.com/{repo}/releases/tag/{tag}",
        "verify": "sha256",
    }


def run(*cmd: str, cwd: Path | None = None) -> str:
    r = subprocess.run(list(cmd), capture_output=True, text=True, check=False, cwd=cwd)
    if r.returncode != 0:
        raise PublishError(f"{' '.join(cmd[:4])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def push_tag(repo_dir: Path, tag: str) -> str:
    local = run("git", "-C", str(repo_dir), "rev-parse", f"{tag}^{{commit}}")
    remote = run("git", "-C", str(repo_dir), "ls-remote", "origin", f"refs/tags/{tag}^{{}}",
                 f"refs/tags/{tag}")
    shas = {line.split()[0] for line in remote.splitlines() if line.strip()}
    if shas:
        if local in shas:
            return f"{repo_dir.name}: {tag} already on origin"
        raise PublishError(f"{repo_dir.name}: origin has {tag} at another commit")
    run("git", "-C", str(repo_dir), "push", "origin", f"refs/tags/{tag}")
    return f"{repo_dir.name}: pushed {tag}"


def title(version: str, tag: str) -> str:
    """The release's title by its line."""
    if re.fullmatch(r"v\d+\.\d+\.\d+-dev\d+", tag):
        return f"Kranto {version} (nightly)"
    if re.fullmatch(r"v\d+\.\d+\.0", tag):
        return f"Kranto {version}"
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return f"Kranto {version} (stable)"
    return f"Kranto {version}"


def publish(dist: Path, version: str, tag: str, repo: str, afk: Path, brb: Path, notes: Path,
            prerelease: bool) -> list[str]:
    wheels = check_set(dist, version)
    assets = [str(w) for w in wheels] + [str(dist / "SHA256SUMS"), str(dist / "manifest.json")]
    if (afk / "install.sh").is_file():     # the installer, from the tagged tree (WZ D1)
        assets.append(str(afk / "install.sh"))
    done = [push_tag(brb, tag), push_tag(afk, tag)]
    exists = subprocess.run(["gh", "release", "view", tag, "-R", repo, "--json", "isDraft"],
                            capture_output=True, text=True, check=False)
    if exists.returncode == 0:
        if not json.loads(exists.stdout).get("isDraft"):
            raise PublishError(f"{tag} is already published on {repo}")
        run("gh", "release", "upload", tag, "-R", repo, "--clobber", *assets)
        done.append(f"re-uploaded the assets of the draft {tag}")
    else:
        run("gh", "release", "create", tag, "-R", repo, "--draft", "--verify-tag",
            "--title", title(version, tag), "--notes-file", str(notes),
            *(["--prerelease"] if prerelease else []), *assets)
        done.append(f"created the draft {tag} with {len(assets)} assets")
    run("gh", "release", "edit", tag, "-R", repo, "--draft=false")
    done.append(f"published https://github.com/{repo}/releases/tag/{tag}")
    return done


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("step", choices=("manifest", "publish"))
    p.add_argument("--dist", required=True, type=Path)
    p.add_argument("--version", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", default="iddv/kranto")
    p.add_argument("--afk", required=True, type=Path)
    p.add_argument("--brb", required=True, type=Path)
    p.add_argument("--notes", type=Path)
    p.add_argument("--prerelease", action="store_true")
    p.add_argument("--hold", action="store_true",
                   help="a stable release or promotion, held: a GitHub prerelease until "
                        "gate.py promote --now releases it after rc_check")
    args = p.parse_args(argv)
    try:
        if args.step == "manifest":
            commits = {"kranto": run("git", "-C", str(args.afk), "rev-parse", "HEAD"),
                       "kranto.page": run("git", "-C", str(args.brb), "rev-parse", "HEAD")}
            m = manifest(args.dist, args.version, args.tag, args.repo, commits)
            (args.dist / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
            print(json.dumps(m, indent=2))
            return 0
        if not args.notes or not args.notes.is_file():
            raise PublishError("publish needs --notes FILE")
        for line in publish(args.dist, args.version, args.tag, args.repo, args.afk, args.brb,
                            args.notes, args.prerelease or args.hold):
            print(line)
        return 0
    except PublishError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
