#!/usr/bin/env python3
"""Write the release manifest, then publish: push the tag and create the GitHub Release.

A release is one of two shapes, built from the same tree (``build.sh --shape``):

- ``final`` (every release after the crossing): one wheel, the product's distribution
  (``product.DIST``); ``manifest.json`` has ``"shape": 2`` and pins that one distribution;
- ``compat`` (the one nightly that crosses an install made before the rename over): the three
  wheels the old update helper installs (``legacy.COMPAT_DISTS``, see ``compat_wheels.py``);
  ``"shape": 1`` and the pins the old helper compares, the server's and the page's old names.

``manifest``: ``dist/manifest.json`` from the wheels in ``dist/`` and ``SHA256SUMS``, checked
on the way: exactly one of the two shapes, one version, every hash in ``SHA256SUMS`` matching
the file. ``build.sh`` writes it; this is its one writer.

``publish``: the shape guard (``guards.py shape``: a final release only after a release that
carries the helper for both shapes, a compat release never after a final one), then push the tag
(the checkout's ``origin``), then ``gh release create --draft`` with the wheels, ``SHA256SUMS``,
``manifest.json`` and ``install.sh``, then publish the draft, so ``releases/latest`` never shows
a release whose assets are still uploading. Every release goes to one repository (``--repo``,
default public.toml's ``repo``). Re-running after a failure is safe: a tag already on the remote
at the same commit is not pushed again, and an existing draft gets its assets re-uploaded.

``--hold`` (a stable release or a promotion) publishes it as a GitHub prerelease: installs on
the stable channel and the installer read only non-prereleases, so it reaches them when
``gate.py promote --now`` releases it after rc_check. Its tag stays ``vX.Y.Z``.
``--prerelease`` is a nightly build. The title says the line: "<Name> 0.7.0.dev12 (nightly)",
"<Name> 0.7.1 (stable)", "<Name> 0.7.0" (a promotion: a new stable minor).

    publish.py manifest --dist DIR --version V --tag T --src DIR [--repo R] [--shape S]
    publish.py publish  --dist DIR --version V --tag T --src DIR [--repo R] [--shape S]
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guards  # noqa: E402
import names  # noqa: E402

SHAPES = ("compat", "final")
SHAPE_NUMBER = {"compat": 1, "final": 2}
WHEEL = re.compile(r"^([A-Za-z0-9_.]+)-([^-]+)-py3-none-any\.whl$")


class PublishError(Exception):
    pass


def shape_dists(root: Path = names.ROOT) -> dict[str, dict[str, tuple[str, ...]]]:
    """Each shape's distributions (in the manifest's order) and the ones its pins name."""
    legacy, product = names.legacy(root), names.product(root)
    return {
        "compat": {"dists": tuple(legacy.COMPAT_DISTS),
                   "pins": (legacy.COMPAT_SERVER, legacy.COMPAT_PAGE)},
        "final": {"dists": (product.DIST,), "pins": (product.DIST,)},
    }


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


def check_set(dist: Path, version: str, shape: str | None = None) -> tuple[str, list[Path]]:
    """(the set's shape, its wheels in the manifest's order), or why the set is wrong."""
    shapes = shape_dists()
    known = {d for s in shapes.values() for d in s["dists"]}
    found: dict[str, Path] = {}
    for w in sorted(dist.glob("*.whl")):
        m = WHEEL.match(w.name)
        if not m or m[1] not in known:
            raise PublishError(f"unexpected file in the set: {w.name}")
        if m[2] != version:
            raise PublishError(f"{w.name} is not version {version}")
        found[m[1]] = w
    which = [s for s, d in shapes.items() if set(d["dists"]) == set(found)]
    if not which:
        raise PublishError(
            "the set must be exactly one of the two shapes (final: "
            f"{', '.join(shapes['final']['dists'])}; compat: "
            f"{', '.join(shapes['compat']['dists'])}); found "
            f"{', '.join(sorted(found)) or 'nothing'}")
    got = which[0]
    if shape and shape != got:
        raise PublishError(f"the set is the {got} shape, not {shape}")
    sums_path = dist / "SHA256SUMS"
    if not sums_path.is_file():
        raise PublishError("SHA256SUMS is missing")
    sums = read_sums(sums_path)
    wheels = [found[n] for n in shapes[got]["dists"]]
    for w in wheels:
        if sums.get(w.name) != sha256(w):
            raise PublishError(f"{w.name}: its hash does not match SHA256SUMS")
    return got, wheels


def manifest(dist: Path, version: str, tag: str, repo: str, commit: str,
             shape: str | None = None, now: datetime | None = None) -> dict:
    got, wheels = check_set(dist, version, shape)
    commit_key = shape_dists()["final"]["dists"][0]
    return {
        "version": version, "shape": SHAPE_NUMBER[got], "tag": tag,
        "published_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": ">=3.12",
        "pins": {d: version for d in shape_dists()[got]["pins"]},
        "commits": {commit_key: commit},
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


def releases(repo: str) -> list[dict]:
    """The repository's releases (drafts too), newest first, as GitHub's API lists them."""
    out = run("gh", "api", f"repos/{repo}/releases?per_page=100")
    rows = json.loads(out or "[]")
    if not isinstance(rows, list):
        raise PublishError(f"gh api {repo}/releases did not answer a list")
    return rows


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
    name = names.product().NAME
    if re.fullmatch(r"v\d+\.\d+\.\d+-dev\d+", tag):
        return f"{name} {version} (nightly)"
    if re.fullmatch(r"v\d+\.\d+\.0", tag):
        return f"{name} {version}"
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return f"{name} {version} (stable)"
    return f"{name} {version}"


def publish(dist: Path, version: str, tag: str, repo: str, src: Path, notes: Path,
            prerelease: bool, shape: str | None = None,
            known: list[dict] | None = None) -> list[str]:
    """``known``: the repository's releases (default: read through gh), for the shape guard."""
    got, wheels = check_set(dist, version, shape)
    why = guards.shape_refusal(got, tag, releases(repo) if known is None else known)
    if why:
        raise PublishError(why)
    assets = [str(w) for w in wheels] + [str(dist / "SHA256SUMS"), str(dist / "manifest.json")]
    if (src / "install.sh").is_file():     # the installer, from the tagged tree
        assets.append(str(src / "install.sh"))
    done = [push_tag(src, tag)]
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
        done.append(f"created the draft {tag} ({got}) with {len(assets)} assets")
    run("gh", "release", "edit", tag, "-R", repo, "--draft=false")
    done.append(f"published https://github.com/{repo}/releases/tag/{tag}")
    return done


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("step", choices=("manifest", "publish"))
    p.add_argument("--dist", required=True, type=Path)
    p.add_argument("--version", required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--repo", default="", help="OWNER/NAME (default: public.toml's repo)")
    p.add_argument("--src", required=True, type=Path, help="the checkout the set was built from")
    p.add_argument("--shape", choices=SHAPES, default=None,
                   help="the shape the set must be (default: whichever it is)")
    p.add_argument("--notes", type=Path)
    p.add_argument("--prerelease", action="store_true")
    p.add_argument("--hold", action="store_true",
                   help="a stable release or promotion, held: a GitHub prerelease until "
                        "gate.py promote --now releases it after rc_check")
    args = p.parse_args(argv)
    repo = args.repo or names.repo()
    try:
        if args.step == "manifest":
            commit = run("git", "-C", str(args.src), "rev-parse", "HEAD")
            m = manifest(args.dist, args.version, args.tag, repo, commit, args.shape)
            (args.dist / "manifest.json").write_text(json.dumps(m, indent=2) + "\n")
            print(json.dumps(m, indent=2))
            return 0
        if not args.notes or not args.notes.is_file():
            raise PublishError("publish needs --notes FILE")
        for line in publish(args.dist, args.version, args.tag, repo, args.src, args.notes,
                            args.prerelease or args.hold, args.shape):
            print(line)
        return 0
    except PublishError as exc:
        print(f"publish: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
