"""Where installed cubs live on disk and the hashes that pin them.

``<home>/cubs/<id>/src`` is the vendored tree at the approved commit (read-only), ``venv`` its
packages (``venv/.ok`` holds the requirements' hash), ``log`` its log, ``cub.json`` a copy of
its registry row. ``.staged``, ``.jobs``, ``.work`` and ``.removed`` hold installs in progress,
fetch jobs, checkouts and quarantine, and removed cubs for 30 days.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

MAX_FILES = 3000
MAX_BYTES = 40 * 1024 * 1024


def root(cfg) -> Path:
    return Path(cfg.root) / "cubs"


def cub_dir(cfg, cid: str) -> Path:
    return root(cfg) / cid


def updating_marker(cfg, cid: str) -> Path:
    """Present while an update swaps the cub's folder: no process of it starts meanwhile."""
    return root(cfg) / ".jobs" / f"{cid}.updating"


def ensure_root(cfg) -> Path:
    r = root(cfg)
    for d in (r, r / ".staged", r / ".jobs", r / ".work", r / ".removed"):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    return r


def tree_hash(path: Path) -> str:
    """sha256 over the tree: every directory, file (its bytes and whether it is executable)
    and symlink (its target), by relative path in sorted order. Any change to a file, a name
    or a mode changes it."""
    h = hashlib.sha256()
    entries = []
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, path)
        for name in sorted(dirnames):
            full = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name))
            if os.path.islink(full):
                entries.append(("L", rel, os.readlink(full)))
            else:
                entries.append(("D", rel, ""))
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name))
            if os.path.islink(full):
                entries.append(("L", rel, os.readlink(full)))
                continue
            mode = os.lstat(full).st_mode
            fh = hashlib.sha256()
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    fh.update(chunk)
            entries.append(("F", rel, f"{'x' if mode & stat.S_IXUSR else '-'}{fh.hexdigest()}"))
    for kind, rel, extra in sorted(entries, key=lambda e: e[1]):
        h.update(f"{kind}\0{rel}\0{extra}\n".encode("utf-8", "surrogateescape"))
    return h.hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def venv_ok(cub: Path, requirements: str | None) -> bool:
    """The venv was built from these requirements (or the cub needs none)."""
    if not requirements:
        return True
    ok = cub / "venv" / ".ok"
    req = cub / "src" / requirements
    return ok.is_file() and req.is_file() and ok.read_text().strip() == file_hash(req)


def make_read_only(path: Path) -> None:
    """Directories 0500, files 0400 (executables 0500): the vendored tree is read-only on the
    host too, so an edit in place is refused and the tree hash says why."""
    for dirpath, dirnames, filenames in os.walk(path, topdown=False):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                mode = os.lstat(full).st_mode
                os.chmod(full, 0o500 if mode & stat.S_IXUSR else 0o400)
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                os.chmod(full, 0o500)
    os.chmod(path, 0o500)


def make_writable(path: Path) -> None:
    """Undo ``make_read_only`` (to move or delete a tree Kranto owns)."""
    if not path.exists():
        return
    os.chmod(path, 0o700)
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                os.chmod(full, 0o700)
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                os.chmod(full, 0o600)
