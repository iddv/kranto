"""The sandbox for code a model or a stranger wrote: bubblewrap, else a network namespace.

Where bubblewrap works, the code sees only its work dir, the system and the base Python
install read-only (not the venv), an empty private /tmp and no network unless asked, so it
cannot reach the den, the page package or anything else of the user's.
``isolation()`` reports which level the machine has. Without bubblewrap, such code does not
run (``require_sandbox``) unless the owner sets ``$KRANTO_ALLOW_UNSANDBOXED=1``; then it runs
in a network namespace only, or on the host.

Moved from ``problems/tsp/contract.py``: TSP's solver was the first user.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SYSTEM_DIRS = ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/localtime")


def base_python() -> str:
    """The interpreter behind the venv. Under bwrap the solver runs this one, so the venv
    (whose site-packages may hold a non-editable install of the page) is never mounted."""
    return getattr(sys, "_base_executable", None) or sys.executable


def _python_dirs(exe: str) -> list[str]:
    """Directories the base interpreter needs: its install root, and the install root of
    every link on the way from ``exe`` to the real binary (uv links through a
    version-alias directory)."""
    dirs = {sys.base_prefix}
    for _ in range(16):
        dirs.add(os.path.dirname(os.path.dirname(exe)))
        if not os.path.islink(exe):
            break
        exe = os.path.normpath(os.path.join(os.path.dirname(exe), os.readlink(exe)))
    return sorted(d for d in dirs if not any(d == s or d.startswith(s + "/") for s in SYSTEM_DIRS))


# What a sandboxed process needs to resolve names and verify TLS when it has network.
NET_FILES = ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl",
             "/etc/ca-certificates", "/etc/pki")


def bwrap_cmd(exe: str, work: Path, ro: tuple = (), interp: str | None = None,
               env: tuple = (), network: bool = False, hide: tuple = (),
               extra: tuple = (), clearenv: bool = True, binds: tuple = (),
               etc: bool = False, home: str | None = None,
               work_at: str | None = None, chdir: str | None = None) -> list[str]:
    """bwrap up to and including the interpreter. ``ro`` adds read-only binds (e.g. a
    per-task venv), ``env`` extra ``(name, value)`` settings; defaults are the solver's.
    ``network`` shares the host network (and DNS/TLS config) but keeps the filesystem
    private: home, the den and held-back tests stay invisible either way. For the worker
    sandbox (``box/sandbox.py``): ``hide`` puts an empty tmpfs over directories before
    anything is bound (so binds under them stay visible), ``extra`` adds raw bwrap
    arguments before the workspace bind, and ``clearenv=False`` keeps the caller's
    environment (the worker's credentials stay out of the command line).

    The exam's contract: ``binds`` are ``(src, dst, read_only)`` triples, so a
    directory can appear at a path other than its own (``/work/product``, ``/work/exam``);
    ``etc`` binds ``/etc`` read-only (``getpass``, ``localhost`` and TLS behave as on a user's
    machine); ``home`` is a private tmpfs used as ``HOME``; ``work_at`` binds ``work`` there
    instead of at its own path, and ``chdir`` is where the process starts (default: the
    work dir)."""
    cmd = [exe, "--unshare-all"] + (["--share-net"] if network else []) + [
           "--die-with-parent", "--new-session"] + (["--clearenv"] if clearenv else []) + [
           "--setenv", "PATH", "/usr/bin:/bin", "--proc", "/proc", "--dev", "/dev",
           "--tmpfs", "/tmp"]
    for d in hide:
        cmd += ["--tmpfs", str(d)]
    for d in SYSTEM_DIRS:
        if os.path.lexists(d):
            # Merged-/usr systems have /bin etc. as symlinks; recreate them as symlinks.
            cmd += (["--symlink", os.readlink(d), d] if os.path.islink(d)
                    else ["--ro-bind", d, d])
    if etc:
        cmd += ["--ro-bind", "/etc", "/etc"]
        for f in NET_FILES:              # a symlink out of /etc (resolv.conf into /run)
            rp = os.path.realpath(f)
            if os.path.exists(f) and not rp.startswith("/etc/"):
                cmd += ["--ro-bind", rp, rp]
    for d in _python_dirs(base_python()):
        cmd += ["--ro-bind", d, d]
    if network and not etc:
        for f in NET_FILES:
            if os.path.exists(f):        # resolv.conf is often a symlink into /run
                cmd += ["--ro-bind", os.path.realpath(f), f]
    for d in ro:
        cmd += ["--ro-bind", str(d), str(d)]
    if home:
        cmd += ["--tmpfs", str(home), "--setenv", "HOME", str(home)]
    for src, dst, read_only in binds:
        cmd += ["--ro-bind" if read_only else "--bind", str(src), str(dst)]
    for k, v in env:
        cmd += ["--setenv", k, v]
    cmd += list(extra)
    at = str(work_at or work)
    return cmd + ["--bind", str(work), at, "--chdir", str(chdir or at),
                  interp or base_python()]


def _probe(cmd: list[str]) -> bool:
    """The probe ran and succeeded within 30 s (a hung bwrap counts as unavailable)."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.cache
def isolation() -> str:
    """The strongest solver isolation this machine supports: ``bwrap`` (private
    filesystem view, private /tmp, no network), ``netns`` (no network only) or ``none``.
    The console's box needs more (``nested_userns``): ``box/sandbox.available`` asks both."""
    exe = shutil.which("bwrap")
    if exe:
        with tempfile.TemporaryDirectory(prefix="kranto.page-probe-") as tmp:
            probe = bwrap_cmd(exe, Path(tmp)) + ["-I", "-c", "pass"]
            if _probe(probe):
                return "bwrap"
    exe = shutil.which("unshare")
    if exe and _probe([exe, "-rn", "true"]):
        return "netns"
    return "none"


NESTED = ("--user", "--map-current-user", "--pid", "--fork", "--mount", "--mount-proc")


@functools.cache
def nested_userns() -> bool:
    """Whether a command inside bubblewrap may make the user, pid and mount namespace the
    console's shell prefix (``kranto-shell``) gives each command. Ubuntu's AppArmor (24.04 and
    later, ``kernel.apparmor_restrict_unprivileged_userns`` 1) may refuse it while bubblewrap
    itself works: ``isolation()`` says only what bubblewrap does."""
    exe, unshare = shutil.which("bwrap"), shutil.which("unshare")
    if not (exe and unshare):
        return False
    with tempfile.TemporaryDirectory(prefix="kranto.page-probe-") as tmp:
        return _probe(bwrap_cmd(exe, Path(tmp), interp=unshare) + [*NESTED, "--", "true"])


def apparmor_restricts() -> bool:
    try:
        return Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns").read_text() \
            .strip() == "1"
    except OSError:
        return False


def box_refusal() -> str | None:
    """Where bubblewrap works and the nested namespace is refused, the one line that says so
    and what to do; else None."""
    if isolation() != "bwrap" or nested_userns():
        return None
    if apparmor_restricts():
        return ("AppArmor refuses the user namespace Open in Claude Code's sandbox gives each "
                "command (kernel.apparmor_restrict_unprivileged_userns is 1). To allow it: "
                "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 (lasts until a "
                "restart; add the line to /etc/sysctl.d/ to keep it), then restart Kranto.")
    return ("this machine refuses the user namespace Open in Claude Code's sandbox gives each "
            "command inside bubblewrap (a container, or a kernel setting): run Kranto on the "
            "host, or allow unprivileged user namespaces, then restart Kranto.")


ALLOW_UNSANDBOXED = "KRANTO_ALLOW_UNSANDBOXED"


class SandboxRequired(RuntimeError):
    """Code a model or a stranger wrote would run outside bubblewrap."""


def require_sandbox(what: str) -> None:
    """Refuse to run ``what`` without bubblewrap, unless the owner allowed it
    (``$KRANTO_ALLOW_UNSANDBOXED=1``). Silently running it on the host (or in a network
    namespace only) was the old fallback."""
    if isolation() == "bwrap" or os.environ.get(ALLOW_UNSANDBOXED) == "1":
        return
    raise SandboxRequired(
        f"{what} runs code that a model or another person wrote, and bubblewrap (bwrap) does "
        "not work on this machine (kranto doctor says why). Install it, or set "
        f"{ALLOW_UNSANDBOXED}=1 to run such code without its sandbox.")


def sandbox_cmd(work: Path, ro: tuple = (), interp: str | None = None,
                env: tuple = (), network: bool = False, **contract) -> list[str]:
    """The command line up to the interpreter for code a model or a stranger wrote (repo
    tests, the exam, a solver), at the strongest isolation here, with extra read-only dirs
    and a chosen interpreter. ``network`` keeps the
    private filesystem but allows network (the factory's default for repo tests; the bench
    and TSP solvers keep it off for determinism). ``contract``: ``bwrap_cmd``'s ``binds``,
    ``etc``, ``home``, ``work_at``, ``chdir``, ``extra`` (bwrap only)."""
    level = isolation()
    py = interp or sys.executable
    if level == "bwrap":
        return bwrap_cmd(shutil.which("bwrap"), work, ro, interp, env, network, **contract)
    require_sandbox("This run")
    if level == "netns" and not network:
        return [shutil.which("unshare"), "-rn", py]
    return [py]
