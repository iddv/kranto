"""Where Claude Code keeps its files: the config dir (``$CLAUDE_CONFIG_DIR``, else
``~/.claude``) and a working directory's key under its ``projects/`` (the path with every
character outside [A-Za-z0-9] replaced by "-"), and making a stored session resumable from
another directory (``prepare_resume``: Continue in your own terminal)."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# -- resuming a session from another directory (build v3) -------------------------------
# Claude Code keeps each session as ``<config>/projects/<project key>/<session id>.jsonl``,
# where the project key is the working directory with every character other than
# [A-Za-z0-9] replaced by "-", and ``--resume <id>`` looks in the current directory's
# project only. A design task's forks run in their own copies of the head's workspace, so
# before a resume the harness copies the session file (and those of its lineage, in case a
# forked session refers back to its parent's) into this directory's project store. If the
# resume still fails, the run reports ``resume_failed`` and the executor reruns it as a
# fresh session seeded with the head's diff.

def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def project_key(path: Path | str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _global_config_dir() -> Path:
    """``config_dir()``, for functions whose ``config_dir`` argument shadows it."""
    return config_dir()


def find_session(session_id: str, root: Path | None = None) -> Path | None:
    """The stored session file for ``session_id`` in any project, or None."""
    root = (root or config_dir()) / "projects"
    if not root.is_dir():
        return None
    return next(iter(sorted(root.glob(f"*/{session_id}.jsonl"))), None)


def prepare_resume(session_id: str, workspace: Path, lineage=(), config_dir: Path | None = None,
                   sources=()) -> dict:
    """Make ``session_id`` (and the ``lineage`` sessions) resumable from ``workspace``:
    copy each stored session file found in another project into the workspace's project
    store (both for the path as given and its resolved form). ``config_dir``: the config
    dir the resuming run uses (default: the process-global one); ``sources``: further config
    dirs to look in, after ``config_dir`` (a fork into a config dir of its own). Returns
    ``{"copied": [ids], "missing": [ids]}``; never raises."""
    cfg = Path(config_dir) if config_dir is not None else _global_config_dir()
    root = cfg / "projects"
    search = [cfg, *(Path(s) for s in sources if s)]
    workspace = Path(workspace)
    targets = list(dict.fromkeys([root / project_key(workspace),
                                  root / project_key(workspace.resolve())]))
    copied, missing = [], []
    for sid in dict.fromkeys([session_id, *lineage]):
        if not sid:
            continue
        try:
            if all((t / f"{sid}.jsonl").exists() for t in targets):
                continue
            src = next((f for f in (find_session(sid, c) for c in search) if f), None)
            if src is None:
                missing.append(sid)
                continue
            for t in targets:
                t.mkdir(parents=True, exist_ok=True)
                if not (t / src.name).exists():
                    shutil.copy2(src, t / src.name)
                side = src.parent / sid          # per-session side files, when there are any
                if side.is_dir() and not (t / sid).exists():
                    shutil.copytree(side, t / sid)
            copied.append(sid)
        except OSError:
            missing.append(sid)
    return {"copied": copied, "missing": missing}
