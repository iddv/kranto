"""What the doctor and ``kranto status`` say about cubs.

The doctor: bubblewrap works (else no cub runs; red when the owner allowed running them
without it); the systemd user scope works (else "rlimits only": memory as an address-space
limit, no pids cap); no ``cubs.STOP``; every installed cub's tree hashes to its pin.
``kranto status``: one line, ``cubs: 2 installed, 1 in practice, 0 paused; a systemd scope caps…``.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from ...stored.cubs import Grants
from .. import tickets
from . import files, sandbox
from . import settings as cub_settings


def _rows(db: Path, store=None) -> list[dict]:
    """The newest registry row of each cub: from ``store`` when the caller has one open (the
    doctor), else read from the file without writing (``kranto status`` runs beside the
    server)."""
    if store is not None:
        try:
            return [dict(r) for r in store.query(
                "SELECT c.* FROM cubs c WHERE c.id = (SELECT MAX(id) FROM cubs d WHERE "
                "d.cub = c.cub)")]
        except sqlite3.Error:         # a database from before the cub runtime
            return []
    if not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT c.* FROM cubs c WHERE c.id = (SELECT MAX(id) FROM cubs d "
                                "WHERE d.cub = c.cub)").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def status_line(cfg, store=None) -> str:
    rows = [r for r in _rows(cfg.db_path, store) if r["state"] != "removed"]
    installed = [r for r in rows if r["state"] == "installed"]
    paused = [r for r in rows if r["state"] == "paused"]
    dry = 0
    for r in installed:
        asks = Grants.load(r["grants"]).requests
        live = cub_settings.live_kinds(cfg, r["cub"])
        if asks and any(k not in live for k in asks):
            dry += 1
    head = (f"{len(installed)} installed, {dry} in practice, {len(paused)} paused" if rows
            else "none installed")
    caps = ("a systemd scope caps their memory, processes and CPU"
            if sandbox.limits_mode() == "scope" else "process limits cap them (no systemd scope)")
    line = f"{head}; {caps}"
    if not cub_settings.enabled(cfg):
        line += "; cubs are off (cubs.enabled: false)"
    if tickets.stop_file().exists():
        line += f"; STOPPED: {tickets.stop_file()} exists"
    return line


def doctor(cfg, store=None) -> list[tuple[str, str, str]]:
    """``(status, name, detail)`` rows, status ``ok``, ``warn`` or ``FAIL``."""
    out: list[tuple[str, str, str]] = []
    if sandbox.sandboxed():
        out.append(("ok", "post writers", "run in a sandbox (bubblewrap works)"))
    elif os.environ.get(sandbox.ALLOW_UNSANDBOXED) == "1":
        out.append(("FAIL", "post writers", f"bubblewrap does not work and "
                                            f"{sandbox.ALLOW_UNSANDBOXED}=1: they run on your "
                                            "machine itself, with your files and network"))
    else:
        out.append(("warn", "post writers", "bubblewrap does not work here: no post writer runs "
                                            "until it does (install bubblewrap)"))
    mode = sandbox.limits_mode()
    out.append(("ok", "writer limits", "memory, processes and CPU are capped (a systemd user "
                                       "scope)")
               if mode == "scope" else
               ("warn", "writer limits", "only a memory limit, no cap on processes (no systemd "
                                         "user manager)"))
    if tickets.stop_file().exists():
        out.append(("FAIL", "cubs.STOP", f"{tickets.stop_file()} exists: no cub runs and every "
                                         "approval of a cub is practice; remove it to resume"))
    for r in _rows(cfg.db_path, store):
        if r["state"] != "installed":
            continue
        src = files.cub_dir(cfg, r["cub"]) / "src"
        if not src.is_dir():
            out.append(("FAIL", f"cub {r['cub']}", "its folder is missing"))
        elif files.tree_hash(src) != r["tree_hash"]:
            out.append(("FAIL", f"cub {r['cub']}", "its files changed since you approved them "
                                                   "(kranto cub update to look at the change)"))
        else:
            out.append(("ok", f"cub {r['cub']}", f"{r['version']}, pinned"))
    return out
