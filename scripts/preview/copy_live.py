"""The preview's copy of live's data, read-only on live.

    python3 -I copy_live.py --src-home ~/kranto-kb --src-loop ~/kranto-loop --root ~/kranto-preview
    \
        --port 8766 [--fresh]

What it does, in order:

1. ``rsync`` live's home into ``<root>/home`` and live's loop home into ``<root>/loop``, without
   ``.env``, ``data/secrets``, ``backups``, ``update``, ``telemetry``, the databases (step 2), the
   lock files and the console's sessions (``term``, ``chat``, ``inbox``) and ``trace.db``.
   ``~/tasks`` is not copied: ``<root>/tasks`` starts empty.
2. Each SQLite database through SQLite's online backup, the source opened ``mode=ro``.
3. The copy's settings point at the copy: every string naming a live folder is rewritten to the
   copy's, the port is the preview's, notifications and the heartbeat are off, usage reports are
   off, the update check and the automatic update are off, and ``preview: {enabled: true,
   copied_at}`` is written. Then the copy's config files are read again: a live folder still
   named there stops the copy (exit 3).

``--fresh``: no source; ``<root>/home`` (made empty beforehand by ``kranto.make_home``) gets the
same switch and its own ``<root>/loop`` and ``<root>/tasks`` (``kranto-preview fresh``, for
walking Welcome). Prints one JSON line with what it did. Never writes under the sources.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

# the names of a home made before the rename (kranto.legacy), from this checkout's source
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from kranto import legacy, product  # noqa: E402

HOME_EXCLUDES = [".env", "data/secrets", "backups/", "update/", "telemetry/", "*.lock",
                 "data/*.db", "data/*.db-*", "data/update.json",
                 *(f"{n}.bak*" for n in (product.HOME_FILE, *legacy.HOME_FILES)),
                 "tasks/", "*.jsonl"]
LOOP_EXCLUDES = ["term/", "chat/", "inbox/", "trace.db", "trace.db-*", "*.lock", "daemon.pid",
                 "daemon.log", "loop.db", "loop.db-*", ".env"]
DATABASES = {"home": [f"data/{product.DB_FILE}", f"data/{legacy.DB_FILE}"], "loop": ["loop.db"]}


def rsync(src: Path, dst: Path, excludes: list[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = ["rsync", "-a", "--delete", "--delete-excluded"]
    for e in excludes:
        cmd += ["--exclude", e]
    subprocess.run([*cmd, f"{src}/", f"{dst}/"], check=True)


def backup_db(src: Path, dst: Path) -> str:
    """``src`` copied through the online backup, opened read-only; the copy's integrity."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(dst) + suffix).unlink(missing_ok=True)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
        return d.execute("pragma integrity_check").fetchone()[0]
    finally:
        d.close()
        s.close()


def rewrite(value, swaps: list[tuple[str, str]]):
    """Every string in a YAML tree with live's folders swapped for the copy's."""
    if isinstance(value, dict):
        return {k: rewrite(v, swaps) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite(v, swaps) for v in value]
    if isinstance(value, str):
        for old, new in swaps:
            if value == old or value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def swaps_for(user_home: Path, src_home: Path | None, src_loop: Path | None, root: Path,
              src_tasks: Path | None) -> list[tuple[str, str]]:
    pairs = []
    for src, dst in ((src_home, root / "home"), (src_loop, root / "loop"),
                     (src_tasks, root / "tasks")):
        if src is None:
            continue
        absolute = str(src.resolve())
        pairs.append((absolute, str(dst)))
        if absolute.startswith(str(user_home) + "/"):
            pairs.append(("~" + absolute[len(str(user_home)):], str(dst)))
    return sorted(pairs, key=lambda p: -len(p[0]))         # the longest name first


def live_named(text: str, user_home: Path, sources: list[Path]) -> list[str]:
    found = []
    for src in sources:
        absolute = str(src.resolve())
        names = [absolute]
        if absolute.startswith(str(user_home) + "/"):
            names.append("~" + absolute[len(str(user_home)):])
        for n in names:
            # a name followed by the end, a slash or a quote: not a longer sibling's prefix
            for tail in ("/", '"', "'", "\n", " "):
                if n + tail in text:
                    found.append(n)
                    break
    return sorted(set(found))


def config_of(home: Path) -> Path | None:
    found = legacy.home_file(home)
    return found if found.is_file() else None


def settle_home(home: Path, *, port: int, root: Path, swaps, copied_at: str,
                commits: dict | None, fresh: bool) -> Path:
    cfg = config_of(home)
    if cfg is None:
        raise SystemExit(f"copy: no settings file in {home}")
    data = yaml.safe_load(cfg.read_text()) or {}
    data = rewrite(data, swaps)
    n = data.setdefault("notify", {})
    n["urls"] = []                         # nothing reaches the maintainer's phone from the preview
    n["heartbeat_every_hours"] = 0
    n["base_url"] = f"http://127.0.0.1:{port}"
    data["telemetry"] = {"mode": "off"}
    u = data.get("update") if isinstance(data.get("update"), dict) else {}
    data["update"] = {**u, "check_every_hours": 0, "auto": "off", "download": False}
    brb = data.get("brb") if isinstance(data.get("brb"), dict) else {}
    data["brb"] = {**brb, "loop_home": str(root / "loop"), "root": str(root / "tasks")}
    data["preview"] = {"enabled": True, "copied_at": copied_at,
                       **({"empty": True} if fresh else {}),
                       **({"commits": commits} if commits else {})}
    head = (f"# the preview's {'empty home' if fresh else 'copy of live'} "
            f"({copied_at}): written by scripts/preview/copy_live.py\n")
    cfg.write_text(head + yaml.safe_dump(data, sort_keys=False))
    return cfg


def settle_loop(loop: Path, *, port: int, swaps) -> Path | None:
    path = loop / "loop.yaml"
    if not path.is_file():
        return None
    data = rewrite(yaml.safe_load(path.read_text()) or {}, swaps)
    if isinstance(data.get("kranto"), dict):
        data["kranto"]["url"] = f"http://127.0.0.1:{port}"
    if isinstance(data.get("feed"), dict) and "ui_url" in data["feed"]:
        data["feed"]["ui_url"] = f"http://127.0.0.1:{port}/brb/"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src-home", type=Path)
    p.add_argument("--src-loop", type=Path)
    p.add_argument("--src-tasks", type=Path, default=Path("~/tasks").expanduser())
    p.add_argument("--root", type=Path, required=True, help="where the copy goes")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--commits", default=None, help='JSON {"kranto": sha, "kranto.page": sha}')
    p.add_argument("--fresh", action="store_true", help="an empty home, no source")
    a = p.parse_args(argv)
    user_home = Path(os.environ.get("HOME") or Path.home())
    root = a.root.expanduser().resolve()
    copied_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    commits = json.loads(a.commits) if a.commits else None
    out: dict = {"root": str(root), "copied_at": copied_at}
    if a.fresh:
        home = root / "home"
        swaps: list = []
        sources: list[Path] = []
        for d in ("loop", "tasks"):
            (root / d).mkdir(parents=True, exist_ok=True)
        if config_of(home) is None:
            raise SystemExit(f"copy --fresh: make the home {home} first (kranto.make_home)")
    else:
        if not (a.src_home and a.src_loop):
            raise SystemExit("copy: --src-home and --src-loop are needed (or --fresh)")
        src_home, src_loop = a.src_home.expanduser().resolve(), a.src_loop.expanduser().resolve()
        for s in (src_home, src_loop):
            if root == s or s in root.parents or root in s.parents:
                raise SystemExit(f"copy: {root} and {s} overlap; the copy goes elsewhere")
        home, loop = root / "home", root / "loop"
        rsync(src_home, home, HOME_EXCLUDES)
        rsync(src_loop, loop, LOOP_EXCLUDES)
        (root / "tasks").mkdir(parents=True, exist_ok=True)
        out["databases"] = {}
        for where, src_dir, dst_dir in (("home", src_home, home), ("loop", src_loop, loop)):
            for rel in DATABASES[where]:
                if (src_dir / rel).is_file():
                    out["databases"][f"{where}/{rel}"] = backup_db(src_dir / rel, dst_dir / rel)
        sources = [src_home, src_loop] + ([a.src_tasks] if a.src_tasks else [])
        swaps = swaps_for(user_home, src_home, src_loop, root, a.src_tasks)
        out["loop_yaml"] = str(settle_loop(loop, port=a.port, swaps=swaps))
    cfg = settle_home(home, port=a.port, root=root, swaps=swaps, copied_at=copied_at,
                      commits=commits, fresh=a.fresh)
    out["config"] = str(cfg)
    # read the copy's settings again: a live folder still named there stops it here
    left = []
    for path in [cfg, *([root / "loop" / "loop.yaml"] if not a.fresh else [])]:
        if path.is_file():
            left += [f"{path.name}: {n}" for n in live_named(path.read_text(), user_home,
                                                               sources)]
    if left:
        print(json.dumps({**out, "error": "live folders still named", "named": left}))
        return 3
    if shutil.which("du"):
        du = subprocess.run(["du", "-sh", str(root)], capture_output=True, text=True).stdout
        out["size"] = du.split()[0] if du else None
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
