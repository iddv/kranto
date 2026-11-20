"""The command a cub runs under: bubblewrap, inside a systemd user
scope where the machine has one, rlimits beneath, nothing of the host's but what it needs.

Inside the sandbox a cub sees the system read-only, its own folder and its venv's packages
read-only, the SDK (and the YAML reader the SDK needs) read-only, a private ``/tmp`` of a fixed
size, no home, no network, no secret, no ``/proc`` and an environment of five variables. No
path it can read names the user's home: an interpreter from outside the system's directories
(a uv-managed Python) appears at ``/opt/kranto/python``, with the files that name its own path
shown rewritten (one that cannot move stays at its own path: ``python_mount``). Values from
the manifest never reach the command line but the entry file's name, which the schema's pattern
has checked.

Without bubblewrap a cub does not run; ``KRANTO_ALLOW_UNSANDBOXED=1`` runs it on the host for a
developer's own machine (the doctor says so in red). Without a systemd user manager (a
container, a CI runner's system service) the memory cap is ``RLIMIT_AS`` and the pids cap is
not enforced: ``limits_mode()`` says which, and the doctor and ``kranto status`` show it.

The server does not import kranto.page, so this mirrors the rules of the page's
``harness/isolation.py`` (the base interpreter, its install root, merged-/usr symlinks)
rather than calling it.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import os
import resource
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

from kranto import product

ALLOW_UNSANDBOXED = "KRANTO_ALLOW_UNSANDBOXED"
# A test, or the doctor, may force the rlimits path (as on a host without a user manager).
FORCE_RLIMITS = "KRANTO_CUBS_RLIMITS"
SYSTEM_DIRS = ("/usr", "/bin", "/lib", "/lib64", "/sbin")
SYSTEM_FILES = ("/etc/ld.so.cache", "/etc/localtime")
SDK_AT = "/opt/kranto/sdk"
# where an interpreter from outside the system's directories appears (a uv-managed Python)
PYTHON_AT = "/opt/kranto/python"
VIEW_MAX = 4 * 1024 * 1024      # files of the interpreter's tree read for its own path
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


def _system(path: str) -> bool:
    return any(path == s or path.startswith(s + "/") for s in SYSTEM_DIRS)


def python_root(exe: str) -> str | None:
    """The base interpreter's install root when it lives outside the system's directories (a
    uv-managed Python under the user's home), else None (``/usr/bin/python3.12`` comes with
    ``/usr``)."""
    root = os.path.dirname(os.path.dirname(os.path.realpath(exe)))
    return None if _system(root) else root


def in_home(path: str) -> bool:
    return path == str(Path.home()) or path.startswith((str(Path.home()) + "/", "/home/"))


@functools.cache
def python_mount(exe: str) -> tuple[str, str] | None:
    """``(host root, path inside)`` for an interpreter from outside the system's directories,
    else None. It appears at ``PYTHON_AT`` when it starts from there (uv's Pythons are built to
    move); one built for its own path only (a library path written into the binary, as
    setup-python's) stays at that path, and ``python_shows_home`` says when that path names the
    user's home (``kranto doctor`` warns)."""
    root = python_root(exe)
    if root is None:
        return None
    return (root, PYTHON_AT) if _starts_at_neutral(exe, root) else (root, root)


def python_shows_home(exe: str) -> bool:
    m = python_mount(exe)
    return m is not None and m[1] != PYTHON_AT and in_home(m[0])


def python_inside(exe: str) -> str:
    """The base interpreter's path inside the sandbox."""
    m = python_mount(exe)
    if m is None:
        return exe
    return f"{m[1]}/{os.path.relpath(os.path.realpath(exe), m[0])}"


def python_binds(exe: str) -> list[str]:
    """bwrap arguments that show the base interpreter (nothing for a system one)."""
    m = python_mount(exe)
    if m is None:
        return []
    root, at = m
    out = ["--ro-bind", root, at]
    if at == PYTHON_AT:
        for copy, inside in python_view(root):
            out += ["--ro-bind", copy, inside]
    return out


def _starts_at_neutral(exe: str, root: str) -> bool:
    bwrap = bwrap_path()
    if bwrap is None:
        return True                  # no sandbox here: nothing is shown anywhere
    inside = f"{PYTHON_AT}/{os.path.relpath(os.path.realpath(exe), root)}"
    files = [x for f in SYSTEM_FILES if os.path.exists(f) for x in ("--ro-bind", f, f)]
    view = [x for copy, at in python_view(root) for x in ("--ro-bind", copy, at)]
    return _probe([bwrap, "--unshare-all", "--die-with-parent", "--clearenv", "--ro-bind",
                   "/usr", "/usr", *_system_links(), *files, "--ro-bind", root, PYTHON_AT,
                   *view, "--dev", "/dev", "--", inside, "-I", "-S", "-B", "-c",
                   "import encodings, sys; sys.exit(sys.prefix != " + repr(PYTHON_AT) + ")"])


def _cache() -> Path:
    """The user's own cache folder for what the sandbox shows in place of host files."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / product.CONFIG_DIR / "sandbox"


def _view_dir(root: str) -> Path:
    return _cache() / "python" / hashlib.sha256(root.encode()).hexdigest()[:16]


def _shown(data: bytes, name: str, root: str) -> bytes:
    """What the sandbox reads instead of a file that names the interpreter's own path: a
    text file with ``PYTHON_AT`` in its place; bytecode empty (Python then reads the source,
    which is shown rewritten); any other binary with the path padded to its length."""
    if b"\0" not in data:
        return data.replace(root.encode(), PYTHON_AT.encode())
    if name.endswith(".pyc"):
        return b""
    pad = PYTHON_AT + "/" * (len(root) - len(PYTHON_AT))
    return data.replace(root.encode(), pad.encode())


def _empty_dir() -> str:
    d = _cache() / "empty"
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise SandboxRequired(f"cannot make {d}: {exc}") from None
    return str(d)


def hide_bytecode(host: str, inside: str) -> list[str]:
    """bwrap arguments putting an empty read-only folder over every ``__pycache__`` under
    ``host`` (bound at ``inside``): Python's bytecode records the host path of its source.
    The cub runs with ``-B`` and compiles from the source instead."""
    out: list[str] = []
    for dirpath, dirs, _names in os.walk(host):
        if "__pycache__" in dirs:
            rel = os.path.relpath(os.path.join(dirpath, "__pycache__"), host)
            out += ["--ro-bind", _empty_dir(), f"{inside}/{rel}"]
    return out


@functools.cache
def python_view(root: str) -> tuple[tuple[str, str], ...]:
    """``(host file, path inside)`` for each file under the interpreter's root that names the
    root itself (uv writes it into sysconfig's data, and Python into that file's bytecode):
    a rewritten copy, kept in the user's cache, is bound over it, so nothing in the sandbox
    names the user's home."""
    needle, out, view = root.encode(), [], _view_dir(root)
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path) or os.path.getsize(path) > VIEW_MAX:
                    continue
                data = Path(path).read_bytes()
            except OSError:
                continue
            if needle not in data:
                continue
            rel = os.path.relpath(path, root)
            copy, shown = view / rel, _shown(data, name, root)
            try:
                if not copy.is_file() or copy.read_bytes() != shown:
                    copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    tmp = copy.with_name(f".{name}.{os.getpid()}.tmp")
                    tmp.write_bytes(shown)
                    os.replace(tmp, copy)
            except OSError as exc:
                raise SandboxRequired(f"cannot keep the sandbox's view of Python in {view}: "
                                      f"{exc}") from None
            out.append((str(copy), f"{PYTHON_AT}/{rel}"))
    return tuple(sorted(out))


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
                       *_system_links(), "--dev", "/dev", "--", "/usr/bin/true"]):
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
                       "/usr", *_system_links(), "--dev", "/dev", "--", "/usr/bin/true"]):
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
    run = [python_inside(py), "-I", "-S", "-B", "-u", f"{SDK_AT}/bears_cub/_run.py",
           "--sdk", SDK_AT,
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
    cmd += python_binds(py)
    # no /proc: its mountinfo names the host path of every bind (the cub's folder, the SDK,
    # the interpreter), and with them the user's home
    cmd += ["--dev", "/dev",
            "--size", str(limits.tmp_mb * 1024 * 1024), "--tmpfs", "/tmp", "--dir", "/tmp/home",
            "--ro-bind", str(src), "/cub/src"]
    if venv is not None:
        # its packages only: the venv's pyvenv.cfg, links and scripts name host paths
        site = str(venv / venv_site(venv).removeprefix("/cub/venv/"))
        cmd += ["--ro-bind", site, venv_site(venv), *hide_bytecode(site, venv_site(venv))]
    # the directories bwrap made for the binds (/etc, /opt, /cub) sit on its root tmpfs: the
    # root is made read-only last, so the only place a cub writes is its sized /tmp
    cmd += ["--ro-bind", sdk["bears_cub"], f"{SDK_AT}/bears_cub",
            *hide_bytecode(sdk["bears_cub"], f"{SDK_AT}/bears_cub"),
            "--ro-bind", sdk["yaml"], f"{SDK_AT}/yaml",
            *hide_bytecode(sdk["yaml"], f"{SDK_AT}/yaml"), "--remount-ro", "/",
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
