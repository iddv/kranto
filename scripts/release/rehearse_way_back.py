"""Rehearse the update's way back on a scratch HOME, from local wheels: an install made before
the rename crosses to the old-shape release, goes back, crosses again, moves to the
one-wheel release, goes back and forward again; forced failures roll back; an update
killed while it installs is put back by hand from its RECOVER.txt.

    python scripts/release/rehearse_way_back.py --work DIR --old SET --k0 SET --k1 SET
        [--port 10063]

Run it under a memory cap (``systemd-run --user --scope -p MemoryMax=3G -- ...``). SET is a
folder holding one release's wheels and SHA256SUMS, named by its tag (``v0.6.0-dev18``).

How it stays away from the machine's real install:

- everything runs in bubblewrap, with HOME and the passwd entry's home both set to DIR/home (a
  version from before the rename manages a unit only from the login home); the real home is
  read-only, DIR is writable, the config, local and old data folders are hidden, the user's
  bus is hidden;
- ``systemctl``, ``systemd-run``, ``journalctl`` and ``loginctl`` are shims first on PATH: they
  refuse every unit but the rehearsal's own and its update helper's, never call the real ones,
  and run a unit by starting its ExecStart with its Environment= lines inside this run's cap;
  ``gh`` answers the update check with an empty release list (the sets are staged by hand);
- before and after, the real unit files (the old and the new name, and their drop-ins) are
  hashed, read-only; any difference fails the run.

Every command it runs has both the old and the new variable names. No model is called: the
home's model key names a variable nobody sets, every job is off, no Claude Code is on PATH.
One JSON object per step is printed and kept in DIR/report.json.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import pwd
import re
import shlex
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
FINAL = ("done", "rolled_back", "failed", "cancelled")


# -- the shims (standard library only: they run on the system Python, with -I) ---------------


def _shim_cfg(sdir: Path) -> dict:
    return json.loads((sdir / "shim.json").read_text())


def _shim_log(cfg: dict, entry: dict) -> None:
    ours = {k: v for k, v in os.environ.items() if k.startswith(tuple(cfg["prefixes"]))
            or k in cfg["renamed"]}
    with open(cfg["log"], "a") as f:
        f.write(json.dumps({"t": round(time.time(), 2), **entry, "env": ours}) + "\n")


def _state_path(cfg: dict, unit: str) -> Path:
    return Path(cfg["state"]) / f"{unit}.json"


def _read_state(cfg: dict, unit: str) -> dict:
    try:
        return json.loads(_state_path(cfg, unit).read_text())
    except (OSError, ValueError):
        return {}


def _write_state(cfg: dict, unit: str, st: dict) -> None:
    p = _state_path(cfg, unit)
    tmp = p.with_name(f".{p.name}.{os.getpid()}")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, p)


def _alive(pid) -> bool:
    if not pid:
        return False
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError, ValueError):
        return False


def _active(cfg: dict, unit: str) -> bool:
    st = _read_state(cfg, unit)
    return bool(st.get("active")) and _alive(st.get("pid"))


def _unit_files(cfg: dict, unit: str) -> list[Path]:
    base = Path(cfg["home"]) / ".config" / "systemd" / "user" / unit
    return [base] + sorted((base.parent / f"{unit}.d").glob("*.conf"))


def _unit_service(cfg: dict, unit: str) -> tuple[list[str], dict[str, str]]:
    """The unit's ExecStart (the last one, an empty one resets) and Environment=, %h expanded."""
    home = cfg["home"]
    command: list[str] = []
    env: dict[str, str] = {}
    for f in _unit_files(cfg, unit):
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if not sep:
                continue
            if key == "Environment":
                for word in shlex.split(value):
                    k, eq, v = word.partition("=")
                    if eq:
                        env[k] = v.replace("%h", home)
            elif key == "ExecStart":
                words = shlex.split(value.replace("%h", home))
                if words:
                    words[0] = words[0].lstrip("-@:+!")
                command = words
    return command, env


def _base_env(cfg: dict) -> dict[str, str]:
    return {"HOME": cfg["home"], "USER": cfg["user"], "LANG": "C.UTF-8",
            "PATH": "/usr/local/bin:/usr/bin:/bin", "XDG_RUNTIME_DIR": cfg["run"],
            "HF_HUB_OFFLINE": "1", "INVOCATION_ID": os.urandom(16).hex()}


def _start(cfg: dict, unit: str, command: list[str], env: dict[str, str]) -> int:
    if _active(cfg, unit):
        return 0
    if not command:
        print(f"{unit}: no ExecStart", file=sys.stderr)
        return 1
    journal = Path(cfg["journal"]) / f"{unit}.log"
    _write_state(cfg, unit, {"active": False, "starting": True})
    with open(journal, "a") as out:
        out.write(f"-- start {time.strftime('%H:%M:%S')}: {' '.join(command)[:300]}\n")
        out.flush()
        subprocess.Popen([sys.executable, "-I", str(HERE), "--supervise", cfg["sdir"], unit,
                          "--", *command], env=env, stdin=subprocess.DEVNULL, stdout=out,
                         stderr=out, start_new_session=True)
    for _ in range(100):
        if _read_state(cfg, unit).get("pid"):
            return 0
        time.sleep(0.05)
    return 1


def _stop(cfg: dict, unit: str, wait_s: float = 15) -> None:
    st = _read_state(cfg, unit)
    pid = st.get("pid")
    if not _alive(pid):
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return
    end = time.time() + wait_s
    while time.time() < end and _alive(pid):
        time.sleep(0.1)
    if _alive(pid):
        with contextlib.suppress(OSError):
            os.kill(int(pid), signal.SIGKILL)
        end = time.time() + 5
        while time.time() < end and _alive(pid):
            time.sleep(0.1)
    for _ in range(50):            # the supervisor records the end
        if not _read_state(cfg, unit).get("active"):
            break
        time.sleep(0.05)


def supervise(sdir: str, unit: str, command: list[str]) -> int:
    """A unit's process, as systemd would hold it: its pid, its end and how it ended."""
    cfg = _shim_cfg(Path(sdir))
    child = subprocess.Popen(command, env=os.environ.copy(), stdin=subprocess.DEVNULL)
    st = {"active": True, "pid": child.pid, "sup": os.getpid(), "started": time.time(),
          "enabled": _read_state(cfg, unit).get("enabled", False)}
    prev = _read_state(cfg, unit)
    st["enabled"] = prev.get("enabled", False)
    _write_state(cfg, unit, st)
    signal.signal(signal.SIGTERM, lambda *a: child.terminate())
    code = child.wait()
    st = {**_read_state(cfg, unit), "active": False, "ended": time.time()}
    if code < 0:
        st.update(ExecMainCode="2", ExecMainStatus=str(-code),
                  Result="success" if -code == signal.SIGTERM else "signal")
    else:
        st.update(ExecMainCode="1", ExecMainStatus=str(code),
                  Result="success" if code == 0 else "exit-code")
    _write_state(cfg, unit, st)
    return 0


def shim(sdir: str, name: str, argv: list[str]) -> int:
    cfg = _shim_cfg(Path(sdir))
    allowed = set(cfg["units"])
    _shim_log(cfg, {"cmd": name, "argv": argv})

    def refuse(unit: str) -> int:
        _shim_log(cfg, {"cmd": name, "REFUSED": unit})
        print(f"rehearsal shim: {name} refuses {unit!r}: only the rehearsal's units "
              f"({', '.join(sorted(allowed))})", file=sys.stderr)
        return 1

    if name == "loginctl":
        return 0
    if name == "gh":
        # the update check's only call: the releases list, empty (the sets are staged by
        # hand), so no version asks GitHub; anything else is refused
        if argv[:1] == ["api"] and len(argv) > 1 and "/releases" in argv[1]:
            print("null" if argv[1].endswith("/releases/latest") else "[]")
            return 0
        print("rehearsal shim: gh is a stand-in here", file=sys.stderr)
        return 1
    if name == "journalctl":
        units = [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-u"]
        for u in units:
            if u not in allowed:
                return refuse(u)
            p = Path(cfg["journal"]) / f"{u}.log"
            if p.exists():
                print("\n".join(p.read_text(errors="replace").splitlines()[-3000:]))
        return 0
    if name == "systemd-run":
        unit, setenv, i = None, {}, 0
        while i < len(argv) and argv[i].startswith("-"):
            a = argv[i]
            if a == "--scope":
                return refuse("--scope")
            if a.startswith("--unit="):
                unit = a.split("=", 1)[1]
            elif a.startswith("--setenv="):
                k, _, v = a.split("=", 1)[1].partition("=")
                setenv[k] = v
            elif a in ("-p", "--property", "-E"):
                i += 1
            i += 1
        if not unit or unit not in allowed:
            return refuse(str(unit))
        if _active(cfg, unit):
            print(f"Unit {unit} is already active", file=sys.stderr)
            return 1
        env = {**_base_env(cfg), **setenv}
        rc = _start(cfg, unit, argv[i:], env)
        print(f"Running as unit: {unit}.service")
        return rc
    if name != "systemctl":
        return 1
    if "--user" not in argv:
        return refuse("(the system manager)")
    opts = {"--value": False, "--now": False}
    props: list[str] = []
    words: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-p", "--property"):
            props.append(argv[i + 1])
            i += 2
            continue
        if a in opts:
            opts[a] = True
        elif not a.startswith("-"):
            words.append(a)
        i += 1
    if not words:
        return 1
    verb, units = words[0], words[1:]
    if verb == "show-environment":
        print(f"HOME={cfg['home']}")
        return 0
    if verb == "daemon-reload":
        return 0
    for u in units:
        if u not in allowed and f"{u}.service" not in allowed:
            return refuse(u)
    rc = 0
    for u in units:
        st = _read_state(cfg, u)
        if verb == "is-active":
            on = _active(cfg, u)
            print("active" if on else ("failed" if st.get("Result") not in (None, "success")
                                       else "inactive"))
            rc = 0 if on else 3
        elif verb == "is-enabled":
            print("enabled" if st.get("enabled") else "disabled")
            rc = 0 if st.get("enabled") else 1
        elif verb in ("enable", "disable"):
            _write_state(cfg, u, {**st, "enabled": verb == "enable"})
            if opts["--now"] and verb == "enable":
                rc = _start(cfg, u, *_unit_service(cfg, u)[:1],
                            {**_base_env(cfg), **_unit_service(cfg, u)[1]})
            elif opts["--now"]:
                _stop(cfg, u)
        elif verb == "start":
            command, env = _unit_service(cfg, u)
            rc = _start(cfg, u, command, {**_base_env(cfg), **env})
        elif verb == "stop":
            _stop(cfg, u)
        elif verb == "restart":
            _stop(cfg, u)
            command, env = _unit_service(cfg, u)
            rc = _start(cfg, u, command, {**_base_env(cfg), **env})
        elif verb == "reset-failed":
            if not _active(cfg, u):
                _write_state(cfg, u, {"enabled": st.get("enabled", False)})
        elif verb == "show":
            on = _active(cfg, u)
            values = {"MainPID": str(st.get("pid") or 0) if on else "0",
                      "ActiveState": "active" if on else "inactive",
                      "Result": st.get("Result", "success"),
                      "ExecMainCode": st.get("ExecMainCode", "0"),
                      "ExecMainStatus": st.get("ExecMainStatus", "0")}
            for p in props or list(values):
                print(values.get(p, "") if opts["--value"] else f"{p}={values.get(p, '')}")
        elif verb == "cat":
            for f in _unit_files(cfg, u):
                if f.exists():
                    print(f"# {f}\n{f.read_text()}")
        else:
            print(f"rehearsal shim: systemctl {verb} is not simulated", file=sys.stderr)
            rc = 1
    return rc


# -- outside: the real unit's hashes, the sandbox, the report ---------------------------------


def real_unit_hashes(real_home: Path, names: list[str]) -> dict[str, str]:
    """sha256 of every real unit file with one of ``names`` and its drop-ins (read only)."""
    d = real_home / ".config" / "systemd" / "user"
    out = {}
    for n in names:
        for f in [d / n, *sorted((d / f"{n}.d").glob("*"))]:
            out[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() \
                else "absent"
    return out


def outer(a: argparse.Namespace) -> int:
    sys.path.insert(0, str(HERE.parents[2] / "src"))
    from kranto import legacy, product

    me = pwd.getpwuid(os.getuid())
    real_home = Path(me.pw_dir)
    work = Path(a.work).resolve()
    if work == real_home or real_home not in work.parents:
        raise SystemExit("--work must be a folder inside your home (it is the only one written)")
    if work.exists() and any(work.iterdir()):
        raise SystemExit(f"--work {work} is not empty: each rehearsal starts in a new folder")
    names = [legacy.UNIT, product.UNIT]
    before = real_unit_hashes(real_home, names)
    for d in ("home", "shim", "state", "journal", "run", "tools", "bin"):
        (work / d).mkdir(parents=True, exist_ok=True)
    unit = f"{product.COMMAND}-rehearsal.service"
    stem = unit.removesuffix(".service")
    assert unit not in names and stem not in [n.removesuffix(".service") for n in names]
    sdir = work / "shim"
    cfg = {"sdir": str(sdir), "home": str(work / "home"), "user": me.pw_name,
           "state": str(work / "state"), "journal": str(work / "journal"),
           "run": str(work / "run"), "log": str(work / "shim.log"),
           "units": [unit, f"{stem}-update", f"{stem}-update.service"],
           "prefixes": [product.ENV_PREFIX, *legacy.ENV_PREFIXES],
           "renamed": list(legacy.ENV_RENAMED)}
    (sdir / "shim.json").write_text(json.dumps(cfg, indent=1))
    for name in ("systemctl", "systemd-run", "journalctl", "loginctl", "gh"):
        p = sdir / name
        p.write_text(f"#!/bin/sh\nexec /usr/bin/python3 -I {shlex.quote(str(HERE))} --shim "
                     f"{shlex.quote(str(sdir))} {name} \"$@\"\n")
        p.chmod(0o755)
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit("uv is not on PATH")
    shutil.copy2(uv, sdir / "uv")
    passwd = work / "passwd"
    passwd.write_text("".join(
        f"{p.pw_name}:x:{p.pw_uid}:{p.pw_gid}:{p.pw_gecos}:"
        f"{work / 'home' if p.pw_uid == me.pw_uid else p.pw_dir}:{p.pw_shell}\n"
        for p in pwd.getpwall()))
    cache = real_home / ".cache" / "uv"
    cache.mkdir(parents=True, exist_ok=True)
    # hidden: the real config (units, tokens), the real tool environments and the old install's
    # data. ~/.local/bin stays visible, read-only and off PATH: a venv's interpreter may be
    # reached through it, and its commands cannot run without the hidden tool environments
    hide = [real_home / n for n in (".config", ".local/share", ".local/state", ".ssh",
                                    ".claude", ".npm")] + \
        [Path(h.replace("~", str(real_home), 1)) for h in legacy.live_homes()] + \
        [real_home / f"{legacy.COMMAND}-preview"]
    cmd = ["bwrap", "--dev-bind", "/", "/", "--ro-bind", str(real_home), str(real_home)]
    cmd += [x for h in hide if h.exists() and h not in [work, *work.parents]
            for x in ("--tmpfs", str(h))]
    cmd += ["--bind", str(work), str(work), "--bind", str(cache), str(cache),
            "--ro-bind", str(passwd), "/etc/passwd", "--tmpfs", f"/run/user/{os.getuid()}",
            "--chdir", str(work), "--"]
    env = {"HOME": str(work / "home"), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    inner_cmd = [sys.executable, str(HERE), "--inner", "--work", str(work), "--old", a.old,
                 "--k0", a.k0, "--k1", a.k1, "--port", str(a.port), "--unit", unit]
    t0 = time.time()
    r = subprocess.run(cmd + inner_cmd, env=env, check=False)
    # whatever the inner run left: every process a shim started
    shim_cfg = _shim_cfg(sdir)
    for u in shim_cfg["units"]:
        _stop(shim_cfg, u, 5)
    after = real_unit_hashes(real_home, names)
    steps = [json.loads(line) for line in (work / "steps.jsonl").read_text().splitlines()] \
        if (work / "steps.jsonl").exists() else []
    refused = [json.loads(line) for line in (work / "shim.log").read_text().splitlines()
               if '"REFUSED"' in line] if (work / "shim.log").exists() else []
    report = {"steps": steps, "real_units_before": before, "real_units_after": after,
              "real_units_same": before == after, "shim_refused": refused,
              "inner_exit": r.returncode, "minutes": round((time.time() - t0) / 60, 1),
              "ok": before == after and r.returncode == 0 and bool(steps)
              and all(s.get("ok") for s in steps)}
    (work / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "steps"}, indent=1))
    if before != after:
        print("FAIL: a real unit file changed", file=sys.stderr)
        return 3
    return 0 if report["ok"] else 1


# -- inside the sandbox: the steps ------------------------------------------------------------


class Run:
    def __init__(self, a: argparse.Namespace) -> None:
        sys.path.insert(0, str(HERE.parents[2] / "src"))
        from kranto import legacy, product
        self.legacy, self.product = legacy, product
        self.work = Path(a.work)
        self.port, self.unit = a.port, a.unit
        self.sets = {"old": Path(a.old), "k0": Path(a.k0), "k1": Path(a.k1)}
        self.tags = {k: p.name for k, p in self.sets.items()}
        self.versions = {k: t.lstrip("v").replace("-dev", ".dev") for k, t in self.tags.items()}
        self.home = self.work / "home"
        self.kb = self.work / "kb"
        self.bin = self.work / "bin"
        self.sdir = self.work / "shim"
        self.cfg = _shim_cfg(self.sdir)
        old, new = legacy.ENV_PREFIXES[0], product.ENV_PREFIX
        self.old_env = old
        self.env = {
            "HOME": str(self.home), "USER": self.cfg["user"], "LANG": "C.UTF-8",
            "PATH": f"{self.sdir}:{self.bin}:/usr/bin:/bin",
            "UV_TOOL_DIR": str(self.work / "tools"), "UV_TOOL_BIN_DIR": str(self.bin),
            "UV_CACHE_DIR": str(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "uv"),
            "UV_PYTHON_PREFERENCE": "only-system", "XDG_RUNTIME_DIR": str(self.work / "run"),
            "HF_HUB_OFFLINE": "1",
            old + "HOME": str(self.kb), new + "HOME": str(self.kb),
            old + "UNIT": self.unit, new + "UNIT": self.unit}
        self.cookie: str | None = None
        self.baseline: dict[str, int] = {}
        self.log = open(self.work / "log.txt", "a")  # noqa: SIM115 - the run's log

    # -- the little things -------------------------------------------------------------------

    def say(self, msg: str) -> None:
        msg = re.sub(r"code=[A-Za-z0-9_\-]+", "code=<hidden>", msg)
        self.log.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        self.log.flush()

    def sh(self, *cmd, timeout: float = 900, extra: dict | None = None,
           quiet: bool = False) -> subprocess.CompletedProcess:
        r = subprocess.run([str(c) for c in cmd], env={**self.env, **(extra or {})},
                           capture_output=True, text=True, timeout=timeout, check=False,
                           cwd=self.work)
        out = (r.stdout + r.stderr).strip()
        self.say(f"$ {' '.join(map(str, cmd))[:300]} -> {r.returncode}"
                 + ("" if quiet or not out else "\n" + out[-3000:]))
        return r

    def cmd(self, name: str | None = None) -> Path:
        if name:
            return self.bin / name
        new = self.bin / self.product.COMMAND
        return new if new.exists() else self.bin / self.legacy.COMMAND

    def http(self, path: str, cookie: str | None = None) -> tuple[int, object]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     headers={"Cookie": cookie} if cookie else {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except (OSError, ValueError):
            return 0, None

    def answering(self) -> str | None:
        code, body = self.http("/api/status")
        return body.get("version") if code == 200 and isinstance(body, dict) else None

    def state(self) -> dict:
        try:
            return json.loads((self.kb / "update" / "state.json").read_text())
        except (OSError, ValueError):
            return {}

    def counts(self) -> dict[str, int]:
        db = self.legacy.db_file(self.kb / "data")
        if not db.exists():
            return {}
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for (t,) in
                    c.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name NOT LIKE 'sqlite_%'").fetchall()}
        finally:
            c.close()

    def signed_in(self) -> bool | None:
        if not self.cookie:
            return None
        with_cookie, _ = self.http("/api/runs", self.cookie)
        without, _ = self.http("/api/runs")
        return with_cookie == 200 and without in (401, 403)

    def first_lines(self) -> dict[str, str]:
        out = {}
        for c in (self.product.COMMAND, self.legacy.COMMAND):
            if self.cmd(c).exists():
                r = self.sh(self.cmd(c), "status", timeout=180, quiet=True)
                out[c] = ((r.stdout or r.stderr).strip().splitlines() or [""])[0][:160]
        return out

    def status_update_line(self, name: str | None = None) -> str:
        r = self.sh(self.cmd(name), "status", timeout=180, quiet=True)
        lines = (r.stdout + r.stderr).splitlines()
        return next((ln for ln in lines if ln.startswith("update")), " | ".join(lines[-3:]))

    def settle(self, want: str | None, timeout: float = 1500) -> dict:
        end = time.time() + timeout
        st: dict = {}
        while time.time() < end:
            st = self.state()
            if st.get("state") in FINAL and _active(self.cfg, self.unit) and \
                    (want is None or self.answering() == want):
                break
            time.sleep(3)
        return st

    def record(self, step: str, expect: str, want: str, st: dict, rc: int | None,
               **extra) -> dict:
        now = self.counts()
        lower = {t: [n, now.get(t)] for t, n in self.baseline.items() if now.get(t, n) < n}
        seeded = {t: now.get(t) for t in ("sources",)}
        answering = self.answering()
        res = {"step": step, "expect": expect, "state": st.get("state"), "exit": rc,
               "from": st.get("from"), "to": st.get("to"), "reason": st.get("reason"),
               "want": want, "answering": answering, "unit_active": _active(self.cfg, self.unit),
               "signed_in": self.signed_in(), "tables_lower": lower, "seeded_rows": seeded,
               "commands": sorted(p.name for p in self.bin.iterdir()),
               "tools": sorted(p.name for p in (self.work / "tools").iterdir() if p.is_dir()),
               "status_first_lines": self.first_lines(),
               "recover_left": (self.kb / "update" / "RECOVER.txt").exists(), **extra}
        res["ok"] = (st.get("state") == expect or expect == st.get("state", "-")) and \
            answering == want and res["unit_active"] and not lower and \
            res["signed_in"] is not False and not res["recover_left"] and \
            all(v for k, v in extra.items() if k.startswith("check_"))
        self.say("STEP " + json.dumps(res))
        with open(self.work / "steps.jsonl", "a") as f:
            f.write(json.dumps(res) + "\n")
        print(json.dumps(res), flush=True)
        return res

    # -- the install before the rename ----------------------------------------------------------

    def install_old(self) -> None:
        meta, server, page = self.legacy.COMPAT_DISTS
        w = {p.name.split("-")[0]: p for p in self.sets["old"].glob("*.whl")}
        self.sh("uv", "tool", "install", "--force", "--python", "3.12",
                "--with-executables-from", f"{server},{page}", "--with", w[server],
                "--with", w[page], w[meta], timeout=1800)
        self.sh(self.cmd(), "up", "--port", self.port, "--no-browser", timeout=600)
        # the copy is a rehearsal: no job runs, no model key, no update check, no report
        import yaml
        cfg = self.legacy.home_file(self.kb)
        data = yaml.safe_load(cfg.read_text()) or {}
        data.setdefault("llm", {})["api_" + "key_env"] = "REHEARSAL_UNSET"
        for sec in ("ingest", "map", "ideas", "retention"):
            data.setdefault(sec, {})["every_hours"] = 0
        data.setdefault("deep_dive", {})["enabled"] = False
        n = data.setdefault("notify", {})
        n.update(urls=[], heartbeat_every_hours=0, base_url=f"http://127.0.0.1:{self.port}")
        data["update"] = {"channel": "nightly", "check_every_hours": 0, "download": False,
                          "auto": "off"}
        data["telemetry"] = {"mode": "off"}
        cfg.write_text(yaml.safe_dump(data, sort_keys=False))
        # the unit names two more of its variables, the old way, in a drop-in (the helper
        # must pass them to the old version on the way back)
        units = self.home / ".config" / "systemd" / "user"
        d = units / f"{self.unit}.d"
        d.mkdir(parents=True, exist_ok=True)
        old = self.old_env
        loop = [k for k, v in self.legacy.ENV_RENAMED.items()
                if v == self.product.ENV_PREFIX + "LOOP_HOME"][0]
        (d / "50-rehearsal.conf").write_text(
            f"[Service]\nEnvironment={old}CLAUDE_DIR={self.work / 'claude-store'}\n"
            f"Environment={loop}={self.kb / 'loop'}\n")
        self.sh("systemctl", "--user", "stop", self.unit)
        self.seed()
        self.sh("systemctl", "--user", "start", self.unit)
        self.wait_up(self.versions["old"])
        r = self.sh(self.cmd(), "open", "--no-browser", quiet=True)
        m = re.search(r"(http://127\.0\.0\.1:\d+/auth/open\?code=[^\s]+)", r.stdout)
        if m:
            self.cookie = self.signin(m.group(1))
        (self.work / "unit-before.txt").write_text((units / self.unit).read_text())
        self.baseline = self.counts()

    def seed(self) -> None:
        """Three sources in the scratch library (written while the server is stopped)."""
        db = self.legacy.db_file(self.kb / "data")
        c = sqlite3.connect(db)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for i in range(3):
            c.execute("INSERT INTO sources (kind, params, label, origin, created_at) "
                      "VALUES ('rss', ?, ?, 'manual', ?)",
                      (json.dumps({"url": f"https://example.invalid/feed{i}.xml"}),
                       f"rehearsal feed {i}", now))
        c.commit()
        c.close()

    def signin(self, link: str) -> str | None:
        class Keep(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            r = urllib.request.build_opener(Keep).open(link, timeout=20)
            headers = r.headers
        except urllib.error.HTTPError as exc:
            headers = exc.headers
        except OSError:
            return None
        got = headers.get_all("Set-Cookie") or []
        return "; ".join(h.split(";", 1)[0] for h in got) or None

    def wait_up(self, want: str, timeout: float = 180) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.answering() == want:
                return True
            time.sleep(2)
        return False

    # -- one update ------------------------------------------------------------------------------

    def stage(self, key: str) -> None:
        dst = self.kb / "update" / "releases" / self.tags[key]
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(self.sets[key], dst)

    def update(self, step: str, to: str, want: str, expect: str = "done",
               fail: str | None = None) -> dict:
        """``to``: a set's key (k0, k1, old) or ``previous``."""
        args = ["update", "--rollback", "--yes"] if to == "previous" else \
            ["update", "--to", self.tags[to], "--yes"]
        if to != "previous":
            self.stage(to)
        extra = {self.product.ENV_PREFIX + "UPDATE_FAIL": fail} if fail else None
        started = time.time()
        r = self.sh(self.cmd(), *args, timeout=1500, extra=extra)
        # exit 2: refused before anything started (nothing to wait for)
        st = self.state() if r.returncode == 2 else self.settle(want)
        return self.record(step, expect, want, st, r.returncode, forced=fail,
                           seconds=round(time.time() - started))

    def way_back_env_seen(self, since: float) -> dict:
        """What the old version's own `up` was started with on the way back, from the shim's
        log of the systemctl calls it made (the drop-in's two old names, and the home)."""
        seen: dict[str, str] = {}
        for line in (self.work / "shim.log").read_text().splitlines():
            e = json.loads(line)
            if e.get("t", 0) >= since and e.get("cmd") == "systemctl" and \
                    "enable" in (e.get("argv") or []):
                seen = e.get("env") or {}
        return seen

    def kill_during_install(self) -> dict:
        """The one-wheel release back to the old-shape one, killed while it installs
        (after the swap took the one-wheel release's tool away): status names
        RECOVER.txt, and its lines put the one-wheel release back."""
        p = subprocess.Popen([str(self.cmd()), "update", "--rollback", "--yes"], env=self.env,
                             stdout=self.log, stderr=self.log, cwd=self.work)
        end, killed = time.time() + 600, None
        recover = self.kb / "update" / "RECOVER.txt"
        from kranto.update.apply import STUB_MARK
        while time.time() < end:
            st = self.state()
            stub = self.cmd(self.product.COMMAND)
            stubbed = stub.is_file() and STUB_MARK in stub.read_text(errors="replace")[:200]
            if st.get("state") == "installing" and recover.exists() and stubbed:
                sup = _read_state(self.cfg, self.unit.removesuffix(".service") + "-update")
                pgid = os.getpgid(int(sup["sup"])) if _alive(sup.get("sup")) else None
                if pgid:
                    os.killpg(pgid, signal.SIGKILL)        # the helper and its uv, at once
                    killed = {"state": st.get("state"), "pid": st.get("pid")}
                break
            time.sleep(0.2)
        p.kill()
        p.wait()
        time.sleep(1)
        said = {c: self.sh(self.cmd(c), "status", timeout=120).stderr.strip()[:300]
                or "(no output)" for c in (self.product.COMMAND, self.legacy.COMMAND)
                if self.cmd(c).exists()}
        names = all(str(recover) in s for s in said.values()) and bool(said)
        text = recover.read_text() if recover.exists() else ""
        r = self.sh("sh", recover, timeout=1500) if text else None
        self.wait_up(self.versions["k1"])
        st = self.state()
        after = self.status_update_line()
        return self.record("k1-killed-while-installing-then-RECOVER", st.get("state", "-"),
                           self.versions["k1"], st, r.returncode if r else None,
                           killed=killed, status_said=said, check_status_names_recover=names,
                           check_recover_ran=bool(r and r.returncode == 0),
                           recover_lines=[ln for ln in text.splitlines()
                                          if ln and not ln.startswith("#")],
                           status_after=after)

    def back_to_old(self, step: str) -> dict:
        since = time.time()
        res = self.update(step, "previous", self.versions["old"])
        seen = self.way_back_env_seen(since)
        old = self.old_env
        loop = [k for k, v in self.legacy.ENV_RENAMED.items()
                if v == self.product.ENV_PREFIX + "LOOP_HOME"][0]
        want = {old + "HOME": str(self.kb), old + "UNIT": self.unit,
                old + "CLAUDE_DIR": str(self.work / "claude-store"), loop: str(self.kb / "loop")}
        extra = {"old_up_env": {k: seen.get(k) for k in want},
                 "check_old_up_had_every_unit_variable": all(seen.get(k) == v
                                                            for k, v in want.items())}
        # acceptance 2: the old command's status answers as itself
        first = res["status_first_lines"].get(self.legacy.COMMAND, "")
        extra["check_old_status_says_old_version"] = self.versions["old"] in first or \
            self.versions["old"] in self.sh(self.cmd(self.legacy.COMMAND), "status",
                                            quiet=True).stdout
        res.update(extra)
        res["ok"] = res["ok"] and all(v for k, v in extra.items() if k.startswith("check_"))
        with open(self.work / "steps.jsonl", "r+") as f:      # the last line, completed
            lines = f.read().splitlines()
            lines[-1] = json.dumps(res)
            f.seek(0)
            f.truncate()
            f.write("\n".join(lines) + "\n")
        print(json.dumps({"step": step, **extra}), flush=True)
        return res

    def all(self) -> None:
        v = self.versions
        self.install_old()
        st = {"state": "-"}
        self.record("old-installed", "-", v["old"], st, None)
        self.update("old-to-k0", "k0", v["k0"])
        self.update("k0-to-old-forced-start", "previous", v["k0"], "rolled_back", "start")
        self.back_to_old("k0-back-to-old")
        self.update("old-to-k0-again", "k0", v["k0"])
        self.update("k0-to-k1", "k1", v["k1"])
        self.update("k1-to-k0-forced-verify", "previous", v["k1"], "rolled_back", "verify")
        self.update("k1-back-to-k0", "previous", v["k0"])
        self.update("k0-to-k1-again", "k1", v["k1"])
        self.kill_during_install()
        self.sh("systemctl", "--user", "stop", self.unit)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--shim"]:
        return shim(argv[1], argv[2], argv[3:])
    if argv[:1] == ["--supervise"]:
        sep = argv.index("--")
        return supervise(argv[1], argv[2], argv[sep + 1:])
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--work", required=True)
    for k in ("old", "k0", "k1"):
        p.add_argument(f"--{k}", required=True, help="a release's folder, named by its tag")
    p.add_argument("--port", type=int, default=10063)
    p.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--unit", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.inner:
        Run(a).all()
        return 0
    return outer(a)


if __name__ == "__main__":
    sys.exit(main())
