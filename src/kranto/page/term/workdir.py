"""The session's working directory: like cd'ing into the folder, never the
live one.

- **a project** (a repo Kranto keeps a clone of) and **a build whose out/ is a git repo**: a
  ``git clone --shared`` of it on a branch ``term/<tid>``. The session can edit and commit
  there; its commits go into the copy's own ``.git``, and the source's objects are read
  through git's alternates, bound read-only. Not a ``git worktree``: a worktree writes its
  objects, refs and config into the source's ``.git``, which Kranto's own git reads later, so the
  sandbox would need that writable. The copy has no remote: nothing can be pushed from it
  (and the sandbox has no credentials anyway).
- **a build without git**: a copy of ``out/`` (no ``.git``, venvs, caches, big or
  secret-shaped files; text through the secret scan, as chat's copy), made a repo with one
  commit so the session's changes are a diff too.
- **an idea**: a scratch folder holding its context files.

``diff`` is what ``kranto_propose kind=patch`` sends: the branch's commits since the base, read
with the host's hardened git (``gitcmd``)."""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import gitcmd

IDENT = ("-c", "user.name=kranto", "-c", "user.email=kranto@localhost")
MAX_DIFF = 400_000


class WorkdirError(RuntimeError):
    """The working directory could not be made; the message says why."""


def _git(*args: str, cwd: Path) -> str:
    return gitcmd.git(*args, cwd=cwd, error=WorkdirError)


def is_repo(p: Path) -> bool:
    return (Path(p) / ".git").is_dir()


def shared_clone(source: Path, dest: Path, branch: str) -> dict:
    """``dest`` as a shared clone of ``source`` on ``branch`` (new, from the source's HEAD):
    ``{"kind": "clone", "base", "branch", "objects"}``; ``objects`` is what must be bound
    read-only for the copy to read its history."""
    source, dest = Path(source).resolve(), Path(dest)
    if not is_repo(source):
        raise WorkdirError(f"{source} is not a git repository")
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git("clone", "-q", "--shared", "--no-checkout", str(source), str(dest), cwd=dest.parent)
    _git("remote", "remove", "origin", cwd=dest)
    _git("checkout", "-q", "-b", branch, cwd=dest)
    _git("config", "user.name", "kranto", cwd=dest)
    _git("config", "user.email", "kranto@localhost", cwd=dest)
    base = _git("rev-parse", "HEAD", cwd=dest).strip()
    return {"kind": "clone", "base": base, "branch": branch,
            "objects": [str(source / ".git" / "objects")]}


def copied(source: Path, dest: Path, branch: str) -> dict:
    """``dest`` as a copy of a folder without git, made a repo with one commit on ``branch``."""
    from .text import copy_out
    if Path(dest).exists():
        shutil.rmtree(dest)
    Path(dest).mkdir(parents=True)
    copy_out(Path(source), Path(dest))
    _git("init", "-q", "-b", branch, cwd=dest)
    _git("config", "user.name", "kranto", cwd=dest)
    _git("config", "user.email", "kranto@localhost", cwd=dest)
    _git("add", "-A", cwd=dest)
    _git(*IDENT, "commit", "-q", "--allow-empty", "-m", "the build's out/, as delivered",
         cwd=dest)
    base = _git("rev-parse", "HEAD", cwd=dest).strip()
    return {"kind": "copy", "base": base, "branch": branch, "objects": []}


def scratch(dest: Path) -> dict:
    Path(dest).mkdir(parents=True, exist_ok=True)
    return {"kind": "scratch", "base": None, "branch": "", "objects": []}


def make(source: Path | None, dest: Path, branch: str) -> dict:
    """The working directory for a subject whose files are at ``source`` (None: scratch)."""
    if source is None:
        return scratch(dest)
    if is_repo(source):
        return shared_clone(source, dest, branch)
    if Path(source).is_dir():
        return copied(source, dest, branch)
    raise WorkdirError(f"{source} is not a folder")


def diff(ws: Path, base: str, branch: str) -> dict:
    """The branch's change since ``base``: ``{"commits", "stat", "diff", "dirty", "cut"}``
    (``dirty``: files changed but not committed, which the patch leaves out)."""
    ws = Path(ws)
    if not base or not is_repo(ws):
        raise WorkdirError("this session has no branch to propose")
    log = _git("log", "--format=%h %s", f"{base}..{branch}", cwd=ws).strip()
    text = _git("diff", "--no-color", f"{base}..{branch}", cwd=ws)
    stat = _git("diff", "--stat", "--no-color", f"{base}..{branch}", cwd=ws).strip()
    dirty = _git("status", "--porcelain", "--untracked-files=normal", cwd=ws).strip()
    cut = len(text) > MAX_DIFF
    return {"commits": [ln for ln in log.splitlines() if ln], "stat": stat,
            "diff": text[:MAX_DIFF], "dirty": [ln[3:] for ln in dirty.splitlines()],
            "cut": cut}


def remove(ws: Path) -> None:
    shutil.rmtree(ws, ignore_errors=True)
