"""The command a cub runs under: bubblewrap, inside a systemd user
scope where the machine has one, rlimits beneath, nothing of the host's but what it needs.

Inside the sandbox a cub sees the system read-only, its own folder and venv read-only, the SDK
(and the YAML reader the SDK needs) read-only, a private ``/tmp`` of a fixed size, no home, no
network, no secret and an environment of five variables. Values from the manifest never reach
the command line but the entry file's name, which the schema's pattern has checked.

Without bubblewrap a cub does not run; ``KRANTO_ALLOW_UNSANDBOXED=1`` runs it on the host for a
developer's own machine (the doctor says so in red). Without a systemd user manager (a
container, a CI runner's system service) the memory cap is ``RLIMIT_AS`` and the pids cap is
not enforced: ``limits_mode()`` says which, and the doctor and ``kranto status`` show it.

the server does not import kranto.page, so this mirrors the rules of the page's
``harness/isolation.py`` (the base interpreter, its install root, merged-/usr symlinks)
rather than calling it.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import resource
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

ALLOW_UNSANDBOXED = "KRANTO_ALLOW_UNSANDBOXED"
# A test, or the doctor, may force the rlimits path (as on a host without a user manager).
FORCE_RLIMITS = "KRANTO_CUBS_RLIMITS"
SYSTEM_DIRS = ("/usr", "/bin", "/lib", "/lib64", "/sbin")
SYSTEM_FILES = ("/etc/ld.so.cache", "/etc/localtime")
SDK_AT = "/opt/kranto/sdk"
NOFILE = 256
FSIZE = 64 * 1024 * 1024


class SandboxRequired(RuntimeError):
    """A cub would run outside bubblewrap."""


@dataclass(frozen=True)
class Limits:
    """The limits one cub runs under (``cubs.<id>.*`` with the tier's ceilings)."""

    memory_mb: int = 512
    pids: int = 64
    cpu_pct: int = 100
    tmp_mb: int = 64
    cpu_s: int = 1210            # RLIMIT_CPU's soft limit: twice the longest deadline, plus


def base_python() -> str:
    """The interpreter behind Kranto's venv: the sandbox runs this one, so Kranto's own venv (and
    its packages) is never mounted."""
    return getattr(sys, "_base_executable", None) or sys.executable


def python_dirs(exe: str) -> list[str]:
    """Directories the base interpreter needs outside ``/usr``: its install root, and the
    install root of every link on the way to the real binary (a uv-managed Python)."""
    dirs = {sys.base_prefix}
    for _ in range(16):
        dirs.add(os.path.dirname(os.path.dirname(exe)))
        if not os.path.islink(exe):
            break
        exe = os.path.normpath(os.path.join(os.path.dirname(exe), os.readlink(exe)))
    return sorted(d for d in dirs
                  if d and not any(d == s or d.startswith(s + "/") for s in SYSTEM_DIRS))


def sdk_dirs() -> dict[str, str]:
    """The host's own ``bears_cub`` package and the ``yaml`` package it reads ``cub.yaml``
    with: bound read-only at ``/opt/kranto/sdk``, so the protocol a cub speaks is the host's."""
    out = {}
    for name in ("bears_cub", "yaml"):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.submodule_search_locations:
            raise SandboxRequired(f"the {name} package is not installed beside Kranto")
        out[name] = str(Path(list(spec.submodule_search_locations)[0]).resolve())
    return out


def _probe(cmd: list[str], env: dict | None = None) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30, env=env).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.cache
def bwrap_path() -> str | None:
    """bubblewrap, if it runs here (a probe that starts and exits)."""
    exe = shutil.which("bwrap") or ("/usr/bin/bwrap" if os.path.exists("/usr/bin/bwrap")
                                    else None)
    if exe and _probe([exe, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                       *_system_links(), "--proc", "/proc", "--dev", "/dev", "--",
                       "/usr/bin/true"]):
        return exe
    return None


@functools.cache
def userns_flags() -> list[str]:
    """``--unshare-user --disable-userns`` where this bwrap takes them (0.8 and later): the
    cub may not make a user namespace of its own, the kernel's widest door for an
    unprivileged process. An older bwrap: none (the cub runs as before)."""
    exe = bwrap_path()
    flags = ["--unshare-user", "--disable-userns"]
    if exe and _probe([exe, "--unshare-all", *flags, "--die-with-parent", "--ro-bind", "/usr",
                       "/usr", *_system_links(), "--proc", "/proc", "--dev", "/dev", "--",
                       "/usr/bin/true"]):
        return flags
    return []


def scope_env() -> dict[str, str]:
    """What ``systemd-run --user`` needs to reach the user manager, and nothing else."""
    keep = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    env = {k: os.environ[k] for k in keep if os.environ.get(k)}
    env["PATH"] = "/usr/bin:/bin"
    return env


@functools.cache
def _scope_works() -> bool:
    exe = shutil.which("systemd-run")
    return bool(exe) and _probe([exe, "--user", "--scope", "-q", "--collect", "--", "true"],
                                env=scope_env())


def limits_mode() -> str:
    """``scope`` (a systemd user scope caps memory, pids and CPU) or ``rlimits``."""
    if os.environ.get(FORCE_RLIMITS) == "1":
        return "rlimits"
    return "scope" if _scope_works() else "rlimits"


def sandboxed() -> bool:
    return bwrap_path() is not None


def require_sandbox() -> None:
    if sandboxed() or os.environ.get(ALLOW_UNSANDBOXED) == "1":
        return
    raise SandboxRequired("a cub runs in bubblewrap (bwrap), which does not work on this "
                          "machine (kranto doctor says why). Install it, or set "
                          f"{ALLOW_UNSANDBOXED}=1 to run cubs without their sandbox.")


def _system_links() -> list[str]:
    """Merged-/usr systems have /bin, /lib, /lib64 and /sbin as links into /usr."""
    out: list[str] = []
    for d in SYSTEM_DIRS[1:]:
        if os.path.islink(d):
            out += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            out += ["--ro-bind", d, d]
    return out


def _tz() -> str:
    tz = os.environ.get("TZ")
    if tz:
        return tz
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def venv_site(venv: Path) -> str:
    """Where a cub's venv keeps its packages, inside the sandbox."""
    py = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return f"/cub/venv/lib/{py}/site-packages"


def argv(*, src: Path, entry: str, venv: Path | None, unit: str, limits: Limits,
         mode: str) -> list[str]:
    """The whole command for one cub process. ``unit``: the scope's name
    (``kranto-cub-<home6>-<id>-<run8>``); ``mode``: ``scope`` or ``rlimits``."""
    py = base_python()
    sdk = sdk_dirs()
    run = [py, "-I", "-S", "-B", "-u", f"{SDK_AT}/bears_cub/_run.py", "--sdk", SDK_AT,
           "--src", "/cub/src", "--entry", entry, "--manifest", "/cub/src/cub.yaml"]
    if venv is not None:
        run += ["--site", venv_site(venv)]
    exe = bwrap_path()
    if exe is None:
        require_sandbox()            # raises unless the owner allowed running without it
        host = [py, "-I", "-S", "-B", "-u", str(Path(sdk["bears_cub"]) / "_run.py"),
                "--sdk", str(Path(sdk["bears_cub"]).parent), "--src", str(src),
                "--entry", entry, "--manifest", str(src / "cub.yaml")]
        if venv is not None:
            host += ["--site", str(venv / "lib" / f"python{sys.version_info.major}."
                                   f"{sys.version_info.minor}" / "site-packages")]
        return host
    cmd = [exe, "--unshare-all", *userns_flags(), "--die-with-parent", "--new-session",
           "--clearenv",
           "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp/home",
           "--setenv", "LANG", "C.UTF-8", "--setenv", "TZ", _tz(),
           "--ro-bind", "/usr", "/usr", *_system_links()]
    for f in SYSTEM_FILES:
        if os.path.exists(f):
            cmd += ["--ro-bind", f, f]
    for d in python_dirs(py):
        cmd += ["--ro-bind", d, d]
    cmd += ["--proc", "/proc", "--dev", "/dev",
            "--size", str(limits.tmp_mb * 1024 * 1024), "--tmpfs", "/tmp", "--dir", "/tmp/home",
            "--ro-bind", str(src), "/cub/src"]
    if venv is not None:
        cmd += ["--ro-bind", str(venv), "/cub/venv"]
    # the directories bwrap made for the binds (/etc, /opt, /cub) sit on its root tmpfs: the
    # root is made read-only last, so the only place a cub writes is its sized /tmp
    cmd += ["--ro-bind", sdk["bears_cub"], f"{SDK_AT}/bears_cub",
            "--ro-bind", sdk["yaml"], f"{SDK_AT}/yaml", "--remount-ro", "/",
            "--chdir", "/tmp", *run]
    if mode == "scope":
        # bwrap starts with an empty environment (env -i): its own process, pid 1 inside,
        # would otherwise keep the user manager's address and the scope's id in
        # /proc/1/environ, where the cub can read them
        return ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--unit", unit,
                "-p", f"MemoryMax={limits.memory_mb}M", "-p", "MemorySwapMax=0",
                "-p", f"TasksMax={limits.pids}", "-p", f"CPUQuota={limits.cpu_pct}%",
                "-p", "OOMPolicy=kill", "--", "/usr/bin/env", "-i", *cmd]
    return cmd


def env_for(mode: str) -> dict[str, str]:
    """The environment the command starts with: for a scope, only what ``systemd-run`` needs
    to reach the user manager (``env -i`` then empties it for bwrap); else nothing. bwrap's
    ``--setenv`` gives the cub five variables of its own."""
    return scope_env() if mode == "scope" else {}


def rlimits(limits: Limits, mode: str):
    """The ``preexec_fn`` that sets the cub's rlimits, inherited through bwrap."""
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_NOFILE, (NOFILE, NOFILE))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FSIZE, FSIZE))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_s, limits.cpu_s + 5))
        if mode == "rlimits":
            mem = limits.memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    return apply


def site_packages() -> str:
    """Kranto's own site-packages (where ``bears_cub`` is installed)."""
    return sysconfig.get_paths()["purelib"]
