"""Is a recorded process still the one that was started? The same rule as the page's
``proc.py``: a pid alone can be recycled, so a record keeps the pid and the process's start
time (``/proc/<pid>/stat``), and only that pair is the same process. Stdlib only."""
from __future__ import annotations

import os


def _stat(pid: int) -> tuple[int, str] | None:
    """``(start time, state)`` from ``/proc/<pid>/stat``, or None when there is no such
    process."""
    try:
        with open(f"/proc/{int(pid)}/stat") as fh:
            rest = fh.read().rsplit(")", 1)[1].split()
        return int(rest[19]), rest[0]
    except (OSError, ValueError, IndexError):
        return None


def start_time(pid: int) -> int | None:
    """The process's start time (clock ticks since boot), which a recycled pid never shares."""
    st = _stat(pid)
    return st[0] if st else None


def running(pid: int | None, start: int | None = None) -> bool:
    """``pid`` runs (a zombie does not) and, when ``start`` is known, is the same process."""
    if not pid:
        return False
    st = _stat(pid)
    if st is None or st[1] == "Z":
        return False
    return start is None or st[0] == start


def me() -> dict:
    """``{"pid", "start"}`` of this process: what a job that is one of its threads records."""
    return {"pid": os.getpid(), "start": start_time(os.getpid())}
