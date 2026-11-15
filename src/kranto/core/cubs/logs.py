"""A cub's log: ``<home>/cubs/<id>/log/<YYYY-MM-DD>.log``, mode 0600, one
JSON object a line: ``{ts, run, src: stderr|log|host, level, msg, data?}``. Every line is
scrubbed (secret shapes, personal data) before it is written. Per run: the cub's stderr up to
256 KiB, then one line saying it was cut; its ``log`` calls up to 600, then one line saying the
rest were dropped. Kept 14 days or 20 MiB, whichever is smaller (``rotate``)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

from ...scrub import scrub
from ...store import iso, utcnow
from . import files

STDERR_BYTES = 256 * 1024
LOG_CALLS = 600
KEEP_DAYS = 14
KEEP_BYTES = 20 * 1024 * 1024
_lock = threading.Lock()


def _dir(cfg, cid: str) -> Path:
    return files.cub_dir(cfg, cid) / "log"


def _clean(value):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def write(cfg, cid: str, *, run: str | None, src: str, level: str, msg: str,
          data: dict | None = None, now: datetime | None = None) -> None:
    """One line in today's file; never raises (a log that cannot be written is not a run that
    failed)."""
    now = now or utcnow()
    line = {"ts": iso(now), "run": run, "src": src, "level": level,
            "msg": scrub(str(msg))[:4000]}
    if data:
        line["data"] = _clean(data)
    try:
        d = _dir(cfg, cid)
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        path = d / f"{now.date().isoformat()}.log"
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass


class RunLog:
    """One run's lines, with its caps."""

    def __init__(self, cfg, cid: str, run: str | None) -> None:
        self.cfg, self.cid, self.run = cfg, cid, run
        self.stderr_bytes = 0
        self.stderr_cut = False
        self.calls = 0
        self.dropped = False

    def host(self, msg: str, level: str = "info", **data) -> None:
        write(self.cfg, self.cid, run=self.run, src="host", level=level, msg=msg, data=data)

    def stderr(self, text: str) -> None:
        if self.stderr_cut:
            return
        self.stderr_bytes += len(text.encode("utf-8", "replace"))
        if self.stderr_bytes > STDERR_BYTES:
            self.stderr_cut = True
            write(self.cfg, self.cid, run=self.run, src="host", level="warning",
                  msg="stderr truncated (256 KiB a run)")
            return
        write(self.cfg, self.cid, run=self.run, src="stderr", level="info", msg=text)

    def call(self, level: str, msg: str, data: dict | None) -> None:
        self.calls += 1
        if self.calls > LOG_CALLS:
            if not self.dropped:
                self.dropped = True
                write(self.cfg, self.cid, run=self.run, src="host", level="warning",
                      msg=f"log: {LOG_CALLS} lines, the rest dropped")
            return
        write(self.cfg, self.cid, run=self.run, src="log", level=level, msg=msg, data=data)


def read(cfg, cid: str, *, since: datetime | None = None, run: str | None = None,
         limit: int = 200) -> list[dict]:
    """The newest ``limit`` lines (oldest first), of one run or since a time."""
    d = _dir(cfg, cid)
    if not d.is_dir():
        return []
    out: list[dict] = []
    cut = iso(since) if since else None
    for path in sorted(d.glob("*.log")):
        if since and path.stem < since.date().isoformat():
            continue
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if (run and line.get("run") != run) or (cut and str(line.get("ts") or "") < cut):
                continue
            out.append(line)
    return out[-max(1, min(limit, 5000)):]


def rotate(cfg, cid: str, now: datetime | None = None) -> int:
    """Remove log files past 14 days, then the oldest while the folder is over 20 MiB.
    Returns how many were removed."""
    d = _dir(cfg, cid)
    if not d.is_dir():
        return 0
    now = now or utcnow()
    keep_from = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    paths = sorted(d.glob("*.log"))
    removed = 0
    for p in paths:
        if p.stem < keep_from:
            p.unlink(missing_ok=True)
            removed += 1
    paths = sorted(p for p in d.glob("*.log") if p.exists())
    while paths and sum(p.stat().st_size for p in paths) > KEEP_BYTES and len(paths) > 1:
        paths.pop(0).unlink(missing_ok=True)
        removed += 1
    return removed
