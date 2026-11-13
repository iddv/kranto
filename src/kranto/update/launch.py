"""Start the update helper outside the environment it replaces (section 4.1).

``launch`` copies ``apply.py`` (standard library only) to ``<home>/update/apply.py``, with the
two name modules it reads (``product.py``, ``legacy.py``) beside it, and runs it on the system
Python as a transient user unit:

    systemd-run --user --unit=kranto-update --collect --description="kranto update to 0.2.0"
      --setenv=KRANTO_HOME=<home> --setenv=KRANTO_UNIT=kranto.service --setenv=PATH=<PATH> ...
      /usr/bin/python3 <home>/update/apply.py --home <home> --to v0.2.0 --when after-build
      --port 8765

so it survives the service's restart and the venv's replacement; ``--collect`` removes the
unit whatever happens; its journal is ``journalctl --user -u kranto-update``. ``kranto update``
and ``POST /api/update`` both come here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .. import legacy
from .apply import FINAL, cancel_path, helper_unit, read_json, state_path, update_dir, write_json

# what the helper's copy needs beside it: it imports these two when it is not in the package
HELPER_FILES = ("apply.py", "../product.py", "../legacy.py")

PASS_ENV = ("HOME", "PATH", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "KRANTO_UPDATE_FAIL",
            "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


class LaunchError(Exception):
    pass


def _run(cmd: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def system_python(which: Callable = shutil.which, tool_dir: Path | None = None) -> str | None:
    """A Python outside the tool's environment: /usr/bin/python3, else python3 on PATH when
    it does not live in the tool dir."""
    if Path("/usr/bin/python3").exists():
        return "/usr/bin/python3"
    found = which("python3")
    if found and not (tool_dir and str(Path(found).resolve()).startswith(str(tool_dir))):
        return found
    return None


def why_not(env: dict | None = None, which: Callable = shutil.which) -> str | None:
    """None when this process can launch the helper (systemd-run and a Python outside the
    venv), else why not."""
    if not which("systemd-run"):
        return "systemd-run is not on PATH"
    if not which("systemctl"):
        return "systemctl is not on PATH"
    if system_python(which) is None:
        return "no Python outside the tool's environment (/usr/bin/python3)"
    return None


def running(home: Path) -> bool:
    """An update whose state is not final (and whose helper is alive)."""
    st = read_json(state_path(home), None) or {}
    if st.get("state", "idle") in (*FINAL, "idle"):
        return False
    pid = st.get("pid")
    if pid:
        from ..proc import running as _running
        return _running(pid, st.get("start"))
    try:   # launched, the helper not started yet: give it two minutes
        import time

        return time.time() - state_path(home).stat().st_mtime < 120
    except OSError:
        return False


def launch(home: Path, to: str, *, when: str = "after-build", port: int = 8765,
           unit: str | None = None, keep: int = 3, ignore_pids: tuple[int, ...] = (),
           env: dict | None = None, run: Callable = _run,
           which: Callable = shutil.which) -> dict:
    """Start the helper; returns {"unit", "to", "when"}. Raises LaunchError."""
    home = Path(home)
    env = dict(os.environ if env is None else env)
    unit = unit or legacy.unit_name(env)
    from .. import preview
    if preview.enabled(home, env):
        raise LaunchError("this is the preview: it is never updated (kranto-preview refresh "
                          "builds it again from its branch)")
    reason = why_not(env, which)
    if reason:
        raise LaunchError(reason)
    if running(home):
        raise LaunchError("an update is already running")
    name = helper_unit(unit)
    active = run(["systemctl", "--user", "is-active", name]).stdout.strip()
    if active in ("active", "activating"):
        raise LaunchError(f"{name} is already running")
    run(["systemctl", "--user", "reset-failed", name])
    d = update_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    helper = d / "apply.py"
    here = Path(__file__).parent
    for rel in HELPER_FILES:
        src = (here / rel).resolve()
        shutil.copy2(src, d / src.name)
    cancel_path(home).unlink(missing_ok=True)
    python = system_python(which)
    cmd = ["systemd-run", "--user", f"--unit={name}", "--collect",
           f"--description=kranto update to {to}",
           f"--setenv=KRANTO_HOME={home}", f"--setenv=KRANTO_UNIT={unit}"]
    cmd += [f"--setenv={k}={env[k]}" for k in PASS_ENV if env.get(k)]
    cmd += [python, str(helper), "--home", str(home), "--to", to, "--when", when,
            "--port", str(port), "--unit", unit, "--keep", str(keep)]
    cmd += [x for pid in ignore_pids for x in ("--ignore-pid", str(pid))]
    write_json(state_path(home), {"state": "requested", "to": to, "when": when, "unit": unit,
                                  "detail": "starting the helper", "pid": None})
    r = run(cmd)
    if r.returncode != 0:
        write_json(state_path(home), {"state": "cancelled", "to": to, "when": when,
                                      "reason": "systemd-run failed: "
                                                + (r.stderr or r.stdout).strip()[:300]})
        raise LaunchError("systemd-run failed: " + (r.stderr or r.stdout).strip()[:300])
    return {"unit": name, "to": to, "when": when}
