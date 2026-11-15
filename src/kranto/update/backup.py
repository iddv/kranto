"""``kranto backup DIR``: what a deploy or an update backs up first (``ops/deploy/backup.py`` and
``counts.py``, ported into the package, without the 635 MB venv
copy: the update's previous spec reinstalls the code).

Into ``DIR`` (created 0700): both databases through SQLite's backup API (consistent while
they are being written) with ``PRAGMA integrity_check``, the kranto config, the loop's
``loop.yaml``, the unit and its drop-ins, the tool's ``uv-receipt.toml``, the versions, and
``counts-before.json`` (every table's row count), and the operator's ``capabilities/``
folder. Never the ``.env``, ``data/secrets/``, ``~/.config/kranto/*.env`` or ``targets/``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from .. import config as config_mod
from .. import paths


def tool_dir(user_home: Path | None = None) -> Path:
    """The uv tool environment Kranto lives in (``$UV_TOOL_DIR``/kranto, or the old tool on an
    install that has not crossed yet)."""
    from .apply import tool_env_of
    base = os.environ.get("UV_TOOL_DIR")
    return tool_env_of(Path(base) if base else
                       Path(user_home or Path.home()) / ".local" / "share" / "uv" / "tools")


def table_counts(db: Path) -> dict[str, int]:
    """Every table's row count, read-only (an absent database: {})."""
    if not Path(db).exists():
        return {}
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        out = {}
        for t in sorted(tabs):
            try:
                out[t] = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.OperationalError:  # a virtual table whose module is not loaded
                continue
        return out
    finally:
        c.close()


def lower_counts(before: dict, after: dict) -> list[str]:
    """Tables with fewer rows after than before (counts only grow; a warning, not a
    failure: retention purges by design)."""
    out = []
    for db, tables in before.items():
        for t, n in tables.items():
            m = (after.get(db) or {}).get(t)
            if m is not None and m < n:
                out.append(f"{db}.{t} {n} -> {m}")
    return out


def _sqlite_copy(src: Path, dest: Path) -> str:
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dest)
    try:
        s.backup(d)
        ok = d.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        d.close()
        s.close()
    os.chmod(dest, 0o600)
    return ok


def backup(dest: Path, home: Path, *, unit: str = "kranto.service",
           user_home: Path | None = None, versions: dict | None = None) -> dict:
    """Back up the kranto home ``home`` into ``dest``. Returns what was written:
    ``{"dir", "databases": {name: {"integrity", "bytes"}}, "files": [...], "counts": {...}}``.
    Raises RuntimeError when a database's copy fails its integrity check."""
    loop_home = paths.loop_home
    user_home = Path(user_home or Path.home())
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    cfg_path = config_mod.config_path(Path(home))
    if cfg_path is None:
        raise RuntimeError(f"{home} is not a Kranto home (no kranto.yaml)")
    cfg = config_mod.load(Path(home), dotenv=False)
    lh = loop_home(cfg.brb.loop_home) if cfg.brb.enabled else None
    dbs = {"kranto.db": cfg.db_path}
    if lh is not None:
        dbs["loop.db"] = paths.LoopLayout(lh).db
    out: dict = {"dir": str(dest), "databases": {}, "files": []}
    counts: dict = {}
    for name, src in dbs.items():
        if not src.exists():
            continue
        counts["afk" if name == "kranto.db" else "loop"] = table_counts(src)
        ok = _sqlite_copy(src, dest / name)
        out["databases"][name] = {"integrity": ok, "bytes": (dest / name).stat().st_size,
                                  "from": str(src)}
        if ok != "ok":
            raise RuntimeError(f"the copy of {src} failed its integrity check: {ok}")
    unit_dir = user_home / ".config" / "systemd" / "user"
    files = [cfg_path, unit_dir / unit, tool_dir(user_home) / "uv-receipt.toml"]
    if lh is not None:
        files.append(paths.LoopLayout(lh).settings)
    for src in files:
        if src.is_file():
            shutil.copy2(src, dest / src.name)
            out["files"].append(str(src))
    dropins = unit_dir / f"{unit}.d"
    if dropins.is_dir():
        (dest / f"{unit}.d").mkdir(exist_ok=True)
        for f in sorted(dropins.glob("*.conf")):
            shutil.copy2(f, dest / f"{unit}.d" / f.name)   # EnvironmentFile= paths, not values
            out["files"].append(str(f))
    # the adopted repos' profiles (the page's the policy of a repo Kranto did not
    # build lives here, not in the repo); the clones and baseline records can be made again
    if lh is not None and (lh / "maintain" / "repos").is_dir():
        shutil.copytree(lh / "maintain" / "repos", dest / "maintain-repos", symlinks=False,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("onboard", "baseline", "__pycache__"))
        out["files"].append(str(lh / "maintain" / "repos"))
    # the operator's capabilities (the page's): small folders Kranto can't fetch
    # again; ``targets/`` (the owner's own, often large, programs) is left out on purpose
    caps = Path(home) / "capabilities"
    if caps.is_dir():
        shutil.copytree(caps, dest / "capabilities", symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".git"))
        out["files"].append(str(caps))
    # the owner's own data nothing can make again: prompt versions, the regression corpus,
    # the plugins and MCP servers added (their pinned copies), and the chat threads
    owned = [(Path(home) / name, name) for name in ("prompts", "corpus", "plugins",
                                                     "mcp-servers")]
    if lh is not None:
        owned.append((lh / "chat", "loop-chat"))
    for src, name in owned:
        if src.is_dir():
            shutil.copytree(src, dest / name, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", ".git"))
            out["files"].append(str(src))
    (dest / "counts-before.json").write_text(json.dumps(counts, indent=1) + "\n")
    out["counts"] = {k: sum(v.values()) for k, v in counts.items()}
    if versions:
        (dest / "versions.json").write_text(json.dumps(versions, indent=1) + "\n")
    # what the update helper reads to count again after the update (the databases' paths)
    (dest / "backup.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def prune(folder: Path, prefix: str, keep: int) -> list[str]:
    """Remove all but the newest ``keep`` entries of ``folder`` named ``prefix*`` (by name:
    they carry a UTC timestamp). Returns what was removed."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    entries = sorted(p for p in folder.iterdir() if p.name.startswith(prefix))
    gone = []
    for p in entries[:-keep] if keep > 0 else entries:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
        gone.append(p.name)
    return gone
