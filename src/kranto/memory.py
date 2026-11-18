"""Kranto's memory: the caps it runs under and how close it is to them (MEM, 2026-10-20).

A stranger's first read grew Kranto to 7.6 GB and, with a CLI run beside it, took a 16 GB box
down for eight hours. The embedder was fixed (``embed.py``); this is the defence in depth, so
that whatever grows next is held and said:

- ``kranto.service`` carries ``MemoryHigh`` (the kernel reclaims and slows Kranto above it) and
  ``MemoryMax`` (the kernel's OOM killer acts inside Kranto's group, never the machine's) with
  ``OOMPolicy=continue`` (a build killed for memory does not stop the server; a server killed
  for it is restarted by ``Restart=on-failure``). The defaults are the smaller of 4 GiB and half
  this machine's memory for the max, and three quarters of that for the high mark. A drop-in
  (``systemctl --user edit Kranto``, ``[Service]`` ``MemoryMax=6G``) overrides them and
  survives updates, which rewrite ``kranto.service`` only.
- A server started in the foreground (``kranto up --foreground``, a home without systemd for
  the service) and ``python -m kranto run`` put themselves in a ``systemd-run --user --scope`` with
  the same
  caps when this machine has a user systemd and they are not capped already.
- The server checks its use every scheduler tick: one log line when it crosses 80% of its cap
  and one when it is back under; ``/api/health`` carries it (Settings › System shows it).
"""

from __future__ import annotations

import ctypes
import gc
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("kranto.memory")

MiB = 1 << 20
MAX_CAP = 4 << 30                 # the default MemoryMax, at most
WARN_AT = 0.8                     # of the lowest cap: the log line and the page's warning
SCOPED_ENV = "KRANTO_SCOPED"       # set inside the scope this module made (no second one)
NO_SCOPE_ENV = "KRANTO_NO_SCOPE"   # 1: never make one (the person caps it themselves)


def total_ram() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def default_caps(total: int | None = None) -> tuple[int, int]:
    """(MemoryHigh, MemoryMax) in bytes, whole MiB: max the smaller of 4 GiB and half the
    machine's memory, high three quarters of max."""
    total = total if total is not None else total_ram()
    cap = MAX_CAP if not total else min(MAX_CAP, total // 2)
    cap -= cap % MiB
    high = cap * 3 // 4
    return high - high % MiB, cap


def unit_lines(total: int | None = None) -> str:
    """The memory lines of ``kranto.service``."""
    high, cap = default_caps(total)
    return f"MemoryHigh={high // MiB}M\nMemoryMax={cap // MiB}M\nOOMPolicy=continue\n"


# -- where this process is ------------------------------------------------------------------

def cgroup_dir(proc: Path = Path("/proc/self/cgroup"),
               root: Path = Path("/sys/fs/cgroup")) -> Path | None:
    """This process's cgroup v2 directory, or None (cgroup v1, not Linux)."""
    try:
        for line in proc.read_text().splitlines():
            if line.startswith("0::"):
                d = root / line[3:].lstrip("/")
                return d if (d / "memory.current").exists() else None
    except OSError:
        return None
    return None


def _bytes(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return None if text in ("", "max") else int(text)


def caps_of(cg: Path | None, root: Path = Path("/sys/fs/cgroup")) -> tuple[int | None, int | None]:
    """(high, max) in force for ``cg``: the lowest set on it or any group above it."""
    high = cap = None
    d = cg
    while d is not None and d != root and root in d.parents:
        h, m = _bytes(d / "memory.high"), _bytes(d / "memory.max")
        high = h if h is not None and (high is None or h < high) else high
        cap = m if m is not None and (cap is None or m < cap) else cap
        d = d.parent
    return high, cap


def own_caps(cg: Path | None) -> bool:
    """Whether ``cg`` itself is capped (kranto.service, a scope): a cap on a group above it
    (the user's whole session or slice) is shared with everything else and does not count."""
    return cg is not None and any(_bytes(cg / f) is not None
                                  for f in ("memory.high", "memory.max"))


def rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


@dataclass(frozen=True)
class Use:
    rss: int | None               # this process
    current: int | None           # its group (the server and its children: builds, claude)
    high: int | None
    max: int | None
    group: str | None

    @property
    def used(self) -> int | None:
        return self.current if self.current is not None else self.rss

    @property
    def limit(self) -> int | None:
        caps = [c for c in (self.high, self.max) if c]
        return min(caps) if caps else None

    @property
    def level(self) -> str:
        """``ok``, ``high`` (past ``WARN_AT`` of the lowest cap) or ``uncapped``."""
        if self.limit is None:
            return "uncapped"
        return "high" if (self.used or 0) >= WARN_AT * self.limit else "ok"

    def words(self) -> str:
        used = _mb(self.used)
        if self.limit is None:
            return f"Kranto uses {used}; no memory cap is set for it"
        which = "MemoryHigh" if self.limit == self.high else "MemoryMax"
        where = f" ({self.group})" if self.group else ""
        line = f"Kranto uses {used} of its {_mb(self.limit)} {which}{where}"
        if self.level == "high":
            line += ("; above it the system slows kranto down, at MemoryMax it ends the "
                     "biggest process in Kranto's group. 'kranto status' and Settings › System "
                     "say more; a drop-in sets other caps (docs/memory.md)")
        return line

    def as_dict(self) -> dict:
        return {"level": self.level, "used_mb": _n(self.used), "rss_mb": _n(self.rss),
                "high_mb": _n(self.high), "max_mb": _n(self.max), "group": self.group,
                "words": self.words()}


def _n(b: int | None) -> int | None:
    return None if b is None else round(b / MiB)


def _mb(b: int | None) -> str:
    if b is None:
        return "an unknown amount"
    return f"{b / (1 << 30):.1f} GB" if b >= 1 << 30 else f"{round(b / MiB)} MB"


def use(cg: Path | None = None, root: Path = Path("/sys/fs/cgroup")) -> Use:
    cg = cg if cg is not None else cgroup_dir(root=root)
    high, cap = caps_of(cg, root) if cg is not None else (None, None)
    return Use(rss=rss(), current=_bytes(cg / "memory.current") if cg is not None else None,
               high=high, max=cap, group=cg.name if cg is not None else None)


_LIBC = None


def release() -> None:
    """After a job: collect, and hand glibc's free memory back to the system. Without it a map
    snapshot's working memory stayed with the server (measured on a real library: 746 MB after
    a snapshot, 535 MB after this; the next snapshot no higher). A no-op off glibc."""
    global _LIBC
    gc.collect()
    if _LIBC is None:
        try:
            _LIBC = ctypes.CDLL("libc.so.6")
            _LIBC.malloc_trim                                        # noqa: B018 - is it there
        except (OSError, AttributeError):
            _LIBC = False
    if _LIBC:
        _LIBC.malloc_trim(0)


class Watch:
    """Called every scheduler tick: logs when Kranto crosses ``WARN_AT`` of its cap and when it
    is back under, once each."""

    def __init__(self, read=use):
        self._read = read
        self.last: Use | None = None
        self._level: str | None = None

    def check(self) -> Use:
        u = self._read()
        if u.level == "high" and self._level != "high":
            log.warning("memory: %s", u.words())
        elif u.level == "ok" and self._level == "high":
            log.info("memory: back under %d%% of the cap: %s", WARN_AT * 100, u.words())
        self._level, self.last = u.level, u
        return u


# -- service.memory: the caps as a setting -------------------------------
# The owner asked the console to raise Kranto's memory and it edited the drop-in by hand: there
# was no setting. ``service.memory`` is that drop-in (``<unit>.d/30-memory.conf``), written by
# Kranto, applied at once (``daemon-reload``, then ``set-property --runtime``), and its use shown.
DROPIN = "30-memory.conf"
DROPIN_MARK = "# written by Kranto: Settings › System › Service › Memory (service.memory)"
MEMORY_GB = (1, 64)               # what the setting takes, in whole or half GB


class ServiceMemoryError(RuntimeError):
    pass


def dropin_path(user_home: Path | None = None, unit: str | None = None) -> Path:
    from .paths import unit_name
    return (Path(user_home or Path.home()) / ".config" / "systemd" / "user"
            / f"{unit or unit_name()}.d" / DROPIN)


def read_dropin(path: Path) -> tuple[int | None, int | None]:
    """(MemoryHigh, MemoryMax) in bytes from a drop-in's ``[Service]`` lines; None for each it
    does not set (or a file that is not there)."""
    try:
        text = path.read_text()
    except OSError:
        return None, None
    got: dict[str, int | None] = {}
    for line in text.splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and k in ("MemoryHigh", "MemoryMax"):
            got[k] = _size(v.strip())
    return got.get("MemoryHigh"), got.get("MemoryMax")


def _size(v: str) -> int | None:
    units = {"K": 1 << 10, "M": MiB, "G": 1 << 30, "T": 1 << 40}
    try:
        if v and v[-1].upper() in units:
            return int(float(v[:-1]) * units[v[-1].upper()])
        return int(v)
    except ValueError:
        return None


def caps_for_gb(gb: float) -> tuple[int, int]:
    """(MemoryHigh, MemoryMax) for a MemoryMax of ``gb``: high is 1 GB under it (a fifth of it
    below 5 GB), so 5 GB gives 4 GB and 5 GB, the owner's choice of 2026-10-28."""
    cap = int(gb * (1 << 30))
    cap -= cap % MiB
    high = cap - min(1 << 30, cap // 5)
    return high - high % MiB, cap


def in_service(unit: str | None = None) -> bool:
    """Whether this process runs in Kranto's own unit (only then is it Kranto's to change: a
    scratch copy or a foreground server never touches the service's caps)."""
    from .paths import unit_name
    cg = cgroup_dir()
    return cg is not None and cg.name == (unit or unit_name())


def service_memory(user_home: Path | None = None, unit: str | None = None) -> dict:
    """What Settings › System › Service › Memory shows: the setting (``auto``, or the GB of
    MemoryMax a drop-in sets), the caps in force, the use now, this machine's memory and the
    default it gives."""
    p = dropin_path(user_home, unit)
    d_high, d_max = read_dropin(p)
    ours = p.is_file() and DROPIN_MARK in p.read_text(errors="replace")
    u = use()
    dh, dm = default_caps()
    return {"setting": round(d_max / (1 << 30), 2) if d_max else "auto",
            "by_hand": p.is_file() and not ours, "dropin": str(p),
            "high_mb": _n(u.high), "max_mb": _n(u.max), "used_mb": _n(u.used),
            "ram_mb": _n(total_ram()), "default_high_mb": _n(dh), "default_max_mb": _n(dm),
            "dropin_high_mb": _n(d_high), "dropin_max_mb": _n(d_max),
            "applies": in_service(unit), "range_gb": list(MEMORY_GB), "words": u.words()}


def set_service_memory(gb: float | None, *, user_home: Path | None = None,
                       unit: str | None = None, run=subprocess.run,
                       here: bool | None = None) -> dict:
    """Set ``service.memory``: ``gb`` the MemoryMax in GB (MemoryHigh ``caps_for_gb``), or
    None for ``auto`` (the drop-in removed: the unit's own lines, from this machine's memory).
    Written, reloaded and applied to the running service at once; refused outside it."""
    from .paths import unit_name
    unit = unit or unit_name()
    if not (in_service(unit) if here is None else here):
        raise ServiceMemoryError(f"Kranto is not running as {unit} here, so there is no service "
                                 "memory to set (a server started by hand has its own caps)")
    if gb is not None:
        lo, hi = MEMORY_GB
        ram = total_ram()
        if not lo <= gb <= hi or (gb * 2) != int(gb * 2):
            raise ServiceMemoryError(f"memory is from {lo} to {hi} GB, in half GBs, or auto")
        if ram and gb * (1 << 30) > ram * 0.9:
            raise ServiceMemoryError(f"this machine has {_mb(ram)}: at most 90% of it")
    p = dropin_path(user_home, unit)
    if gb is None:
        p.unlink(missing_ok=True)
        high, cap = default_caps()
    else:
        high, cap = caps_for_gb(gb)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(f"{DROPIN_MARK}\n[Service]\nMemoryHigh={high // MiB}M\n"
                       f"MemoryMax={cap // MiB}M\n")
        tmp.replace(p)
    steps = [["systemctl", "--user", "daemon-reload"],
             ["systemctl", "--user", "set-property", "--runtime", unit,
              f"MemoryHigh={high // MiB}M", f"MemoryMax={cap // MiB}M"]]
    for argv in steps:
        try:
            r = run(argv, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ServiceMemoryError(f"written to {p}, not applied: {exc}") from exc
        if r.returncode != 0:
            raise ServiceMemoryError(f"written to {p}, not applied: {' '.join(argv[2:4])} said "
                                     f"{(r.stderr or r.stdout or '').strip()[:200]}")
    log.info("service.memory: %s (MemoryHigh %s, MemoryMax %s)",
             "auto" if gb is None else f"{gb:g} GB", _mb(high), _mb(cap))
    return {"high_mb": _n(high), "max_mb": _n(cap)}


# -- a capped scope for runs outside kranto.service ------------------------------------------

def scope_argv(argv: list[str], *, environ=os.environ, which=shutil.which,
               probe=None, capped=None) -> list[str] | None:
    """``argv`` inside a ``systemd-run --user --scope`` with Kranto's caps, or None when it needs
    none or cannot have one: already capped (kranto.service, a scope the person made, or ours),
    ``KRANTO_NO_SCOPE=1``, a systemd service's process (its group is the unit's, which moving
    out of would confuse systemd; ``INVOCATION_ID`` cannot tell, a shell started from a unit
    inherits it), or no user systemd to ask."""
    if environ.get(SCOPED_ENV) or environ.get(NO_SCOPE_ENV) == "1":
        return None
    if capped is None:
        cg = cgroup_dir()
        capped = own_caps(cg) or (cg is not None and cg.name.endswith(".service"))
    if capped:
        return None
    run = which("systemd-run")
    if run is None:
        return None
    high, cap = default_caps()
    head = [run, "--user", "--scope", "--quiet", "-p", f"MemoryHigh={high // MiB}M",
            "-p", f"MemoryMax={cap // MiB}M"]
    probe = probe or _probe
    if not probe(head):
        return None
    return head + ["--", "env", f"{SCOPED_ENV}=1", *argv]


def _probe(head: list[str]) -> bool:
    """Whether the user's systemd answers (a stranger's ``env -i`` shell, a container or a
    machine without it does not)."""
    try:
        return subprocess.run(head + ["--", "true"], capture_output=True,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def enter_scope(what: str) -> None:
    """Run this command again inside a capped scope, when it should be and can be (it
    replaces this process); otherwise return and run as is."""
    argv = scope_argv([sys.executable, *sys.argv])
    if argv is None:
        return
    high, cap = default_caps()
    print(f"{what}: running inside a memory cap (MemoryHigh {_mb(high)}, MemoryMax "
          f"{_mb(cap)}; KRANTO_NO_SCOPE=1 runs without)", file=sys.stderr, flush=True)
    os.execvp(argv[0], argv)
