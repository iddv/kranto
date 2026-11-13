"""The update helper's shared ground: standard library only, no the server import.

This module is the one piece of the updater that runs *outside* the environment it replaces
(section 4.1): ``uv tool install --force`` rebuilds the tool's venv, and a
Python running from that venv cannot be trusted to import anything afterwards. So it is
written for any Python 3.10 or newer, copied to ``<home>/update/apply.py`` before a run and
started there by ``systemd-run``. The check (``check.py``) imports the same helpers from the
package, so a wheel set is verified, and an installation described, the same way by both.

Here: version ordering, redaction, the wheel-set check (``SHA256SUMS``, the manifest's pins,
exactly the three distributions at one version), what an environment has installed (from
its ``*.dist-info``: the version and ``direct_url.json``, which says git commit or wheel
path), the files under ``<home>/update/``, and the helper itself (``Helper``, ``main``):

    requested -> draining -> backing_up -> stopping -> installing -> starting -> verifying
      -> done;  a failure while installing, starting or verifying -> rolling_back ->
      rolled_back (the previous version is back) | failed (it is not; ``detail`` says what
      to do by hand). A precondition or the drain refusing -> cancelled (nothing changed).

    python3 <home>/update/apply.py --home H --to vX.Y.Z|previous [--when after-build|now]
        --port P [--unit kranto.service] [--keep 3] [--ignore-pid PID]

``KRANTO_UPDATE_FAIL=install|start|verify|selfcheck|rollback`` makes that step fail on purpose
(the end-to-end test's forced failure); it is honoured only when set.

The self-check: once the new version answers as itself, it reads every
page on this install's own data (``route_check``: every GET ``/api/selfcheck/paths`` lists,
read-only, within ``SELFCHECK_S``); any answer of 500 or above, or none, rolls it back like a
failed start, the reason saying which page and the error's id (``selfcheck`` in the state and
the history). ``kranto doctor --routes`` runs the same check on the running server.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036 - the helper runs on the system Python
    raise SystemExit("the kranto update helper needs Python 3.10 or newer")

try:
    from .. import legacy, product
except ImportError:      # the copy under <home>/update/, which launch puts beside these two
    import legacy  # type: ignore[no-redef]
    import product  # type: ignore[no-redef]

# A release has one of two shapes. ``final``: one wheel, the distribution ``kranto``, installed
# as the uv tool ``kranto``. ``compat``: the three wheels an install made before the rename
# knows (its helper installs nothing else), installed as its old tool; it exists for one
# release, the one that crosses such an install over, and its helper (this one) then moves
# the install to the final shape: stop, uninstall the old tool, install ``kranto``.
FINAL_DIST = product.DIST
COMPAT = legacy.COMPAT_DISTS                      # (the meta-package, the server, the page)
NAMES = (FINAL_DIST, *COMPAT)
SHAPES = {"final": (FINAL_DIST,), "compat": COMPAT}
TOOLS = {"final": product.DIST, "compat": legacy.TOOL}
COMPAT_EXTRAS = ("mcp",)                           # the old meta-package's only extra
WHEEL = re.compile(r"^([A-Za-z0-9_.]+)-([^-]+)-py3-none-any\.whl$")
EXTRAS = "connections,notify"
REPOS = {FINAL_DIST: product.REPO}


class SetError(Exception):
    """A staged wheel set that must not be installed."""


# -- versions ----------------------------------------------------------------------------------

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-?rc(\d+))?(?:[.-]dev(\d+))?(?:\+.*)?$")


def vkey(version: str | None) -> tuple:
    """A sort key for the versions Kranto uses: ``X.Y.Z`` (stable), ``X.Y.0.devN`` (a nightly
    build, or its tag form ``vX.Y.0-devN``), ``X.Y.ZrcN`` (or ``vX.Y.Z-rcN``, the retired rc
    tags), ``X.Y.Z.devN+local`` (a git build). dev < rc < final within a base, so
    ``0.6.2 < 0.7.0.dev12 < 0.7.0 < 0.8.0.dev1``; anything else sorts
    lowest."""
    m = _VERSION.match((version or "").strip())
    if not m:
        return (-1,)
    base = tuple(int(m[i]) for i in (1, 2, 3))
    if m[5] is not None:
        return (*base, 0, int(m[4] or 0), int(m[5]))
    if m[4] is not None:
        return (*base, 1, int(m[4]), 0)
    return (*base, 2, 0, 0)


def tag_version(tag: str) -> str:
    """``v0.2.0-rc1`` -> ``0.2.0rc1``, ``v0.7.0-dev12`` -> ``0.7.0.dev12`` (the wheels' PEP 440
    version)."""
    return tag.lstrip("v").replace("-rc", "rc").replace("-dev", ".dev")


def is_prerelease(version: str) -> bool:
    """A nightly build (``.devN``, ``-devN``) or an old rc: never offered on ``stable`` and
    never installed by itself."""
    return "rc" in version or "dev" in version


def line_of(version: str | None) -> str:
    """The release line a version belongs to: ``nightly`` for a build from main (and the
    retired rc tags, which were builds from main too), ``stable`` otherwise."""
    return "nightly" if version and is_prerelease(version) else "stable"


# -- redaction ---------------------------------------------------------------------------------

_SECRETS = [
    re.compile(r"(?i)(authorization:\s*)(\S+\s+)?\S+"),
    re.compile(r"(?i)\b(token[=:\s]+)\S+"),
    re.compile(r"\b(gh[pousr]_)[A-Za-z0-9]{10,}"),
    re.compile(r"\b(github_pat_)[A-Za-z0-9_]{10,}"),
]


def redact(text: object) -> str:
    """``text`` with anything token-shaped replaced, for the log, the cache and the API.
    The values of ``GH_TOKEN`` and ``GITHUB_TOKEN`` in this process are removed too."""
    out = str(text)
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(name)
        if value and len(value) >= 8:
            out = out.replace(value, "[redacted]")
    for p in _SECRETS:
        out = p.sub(lambda m: (m.group(1) or "") + "[redacted]", out)
    return out


# -- the wheel set ------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sums(path: Path) -> dict[str, str]:
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            out[name.strip().lstrip("*")] = digest.lower()
    return out


def wheels_in(folder: Path, version: str | None = None) -> dict[str, Path]:
    """{distribution: wheel} for Kranto's wheels in ``folder`` (at ``version`` if given)."""
    out = {}
    for w in sorted(Path(folder).glob("*.whl")):
        m = WHEEL.match(w.name)
        if m and m[1] in NAMES and (version is None or m[2] == version):
            out[m[1]] = w
    return out


def shape_of(found: dict[str, Path] | set[str] | list[str]) -> str:
    """``final`` (the one wheel) or ``compat`` (the three old ones), for a verified set."""
    return "final" if FINAL_DIST in found else "compat"


def pins_for(shape: str, version: str) -> dict[str, str]:
    """What a set's manifest pins: the final wheel, or the old pair the old helper compares."""
    if shape == "final":
        return {FINAL_DIST: version}
    return {legacy.COMPAT_SERVER: version, legacy.COMPAT_PAGE: version}


def verify_set(folder: Path, version: str) -> dict[str, Path]:
    """The wheels of ``version`` in ``folder``, checked: the set is exactly one shape (the one
    ``kranto`` wheel, or the three old ones), every hash matches ``SHA256SUMS``, and the
    manifest (when there is one) names the same version, the shape's pins and the same hashes.
    Raises ``SetError`` otherwise."""
    folder = Path(folder)
    stray = []
    for w in folder.glob("*.whl"):
        m = WHEEL.match(w.name)
        if not m or m[1] not in NAMES or m[2] != version:
            stray.append(w.name)
    if stray:
        raise SetError(f"unexpected wheels in the set: {', '.join(sorted(stray))}")
    found = wheels_in(folder, version)
    if set(found) not in [set(names) for names in SHAPES.values()]:
        raise SetError(f"the set for {version} must be the one {FINAL_DIST} wheel or exactly "
                       f"{', '.join(COMPAT)}; found {', '.join(sorted(found)) or 'nothing'}")
    shape = shape_of(found)
    sums_path = folder / "SHA256SUMS"
    if not sums_path.is_file():
        raise SetError("SHA256SUMS is missing")
    sums = read_sums(sums_path)
    for w in found.values():
        if sums.get(w.name) != sha256(w):
            raise SetError(f"{w.name}: its SHA-256 does not match SHA256SUMS")
    mpath = folder / "manifest.json"
    if mpath.is_file():
        try:
            m = json.loads(mpath.read_text())
        except ValueError as exc:
            raise SetError(f"manifest.json does not parse: {exc}") from exc
        if not isinstance(m, dict):
            raise SetError("manifest.json is not an object")
        if m.get("version") != version:
            raise SetError(f"manifest.json is for {m.get('version')}, not {version}")
        if m.get("shape") is not None and m.get("shape") != (2 if shape == "final" else 1):
            raise SetError(f"manifest.json says shape {m.get('shape')}; the wheels are {shape}")
        if m.get("pins") != pins_for(shape, version):
            raise SetError(f"manifest.json pins {m.get('pins')}, not {version}")
        listed = {w.get("name"): w.get("sha256") for w in m.get("wheels") or []
                  if isinstance(w, dict)}
        for w in found.values():
            if listed.get(w.name) != sums[w.name]:
                raise SetError(f"manifest.json disagrees with SHA256SUMS on {w.name}")
    return found


def _req(name: str, extras) -> str:
    """``name`` or ``name[a,b]``."""
    extras = sorted(set(extras or ()))
    return name + (f"[{','.join(extras)}]" if extras else "")


def final_extras(kranto_extras=()) -> list[str]:
    """The final wheel's extras: the defaults and whatever the install had (``mcp``)."""
    return sorted({*EXTRAS.split(","), *(kranto_extras or ())})


def install_args(found: dict[str, Path], kranto_extras=()) -> list[str]:
    """The ``uv tool install`` arguments for a verified set (direct paths, never names), keeping
    the extras the install had. ``final``: ``kranto[connections,mcp,notify] @ file:///…whl``,
    the tool ``kranto``. ``compat``: the old helper's own line (the server and the page by
    ``--with``, their commands too, the meta-package last), the old tool."""
    if shape_of(found) == "final":
        uri = Path(found[FINAL_DIST]).resolve().as_uri()
        return [f"{_req(FINAL_DIST, final_extras(kranto_extras))} @ {uri}"]
    meta, server, page = COMPAT
    extras = [x for x in (kranto_extras or ()) if x in COMPAT_EXTRAS]
    last = (f"{_req(meta, extras)} @ {Path(found[meta]).resolve().as_uri()}"
            if extras else str(found[meta]))
    return ["--with-executables-from", f"{server},{page}",
            "--with", str(found[server]), "--with", str(found[page]), last]


def git_requirements(commits: dict[str, str], extras: str = EXTRAS,
                     kranto_extras=()) -> list[str]:
    """``kranto`` at the spec's commit, as a requirement line (the ``main`` channel)."""
    want = sorted({*extras.split(","), *(kranto_extras or ())} - {""})
    return [f"{_req(FINAL_DIST, want)} @ git+https://github.com/{REPOS[FINAL_DIST]}"
            f"@{commits[FINAL_DIST]}"]


def git_install_args(commits: dict[str, str], extras: str = EXTRAS, *,
                     overrides: Path | None = None, kranto_extras=()) -> list[str]:
    """The ``uv tool install`` arguments for a git spec (the ``main`` channel's install): one
    distribution at one commit. (``overrides`` is accepted for older callers; one requirement
    needs none.)"""
    return git_requirements(commits, extras, kranto_extras)


def receipt_extras(env: Path) -> list[str]:
    """The extras the tool's main package was installed with (``uv tool install
    "kranto[mcp] @ …"``, or the old meta-package's), from its ``uv-receipt.toml``; an update
    keeps them."""
    try:
        text = (Path(env) / "uv-receipt.toml").read_text()
    except OSError:
        return []
    names = (FINAL_DIST, legacy.COMPAT_META)
    try:
        import tomllib

        reqs = (tomllib.loads(text).get("tool") or {}).get("requirements") or []
        for r in reqs:
            if isinstance(r, dict) and r.get("name") in names:
                return sorted(str(x) for x in r.get("extras") or [])
        return []
    except ImportError:  # Python 3.10: the receipt's one-line inline table
        for name in names:
            m = re.search(r'\{\s*name\s*=\s*"' + re.escape(name)
                          + r'"\s*,\s*extras\s*=\s*\[([^\]]*)\]', text)
            if m:
                return sorted(re.findall(r'"([^"]+)"', m.group(1)))
        return []
    except ValueError:
        return []


def tool_env_of(tool_dir: Path) -> Path:
    """The uv tool environment this install lives in: ``kranto``, else the old tool when only
    it exists (an install that has not crossed yet), else ``kranto`` (none yet)."""
    tool_dir = Path(tool_dir)
    for name in (TOOLS["final"], TOOLS["compat"]):
        if (tool_dir / name).is_dir():
            return tool_dir / name
    return tool_dir / TOOLS["final"]


# -- what an environment has installed ----------------------------------------------------------


def site_packages(env: Path) -> list[Path]:
    return sorted(Path(env).glob("lib/python3*/site-packages"))


def _dist_info(env: Path, name: str) -> Path | None:
    for sp in site_packages(env):
        for d in sp.glob(f"{name}-*.dist-info"):
            if d.name.split("-")[0].lower().replace("_", "-") == name:
                return d
    return None


def _metadata_version(dist: Path) -> str | None:
    try:
        for line in (dist / "METADATA").read_text(errors="replace").splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
            if not line.strip():
                break
    except OSError:
        return None
    return None


def installed(env: Path | None = None) -> dict:
    """What the environment ``env`` (default: this Python's) has installed:

    ``{"version": Kranto's version, "versions": {name: version}, "channel": ..., "spec": ...}``

    The shape is ``final`` when the ``kranto`` distribution is there, ``compat`` when the old
    ones are (an install that has not crossed yet, or the crossing release itself); the
    version is the one of the distribution that holds the code. ``spec`` is what reinstalls
    it: ``{"kind": "wheels", "dir", "version", "shape", "tool"}`` when every distribution
    came from one folder of wheels; ``{"kind": "git", "commits": {name: sha}, "extras", ...}``
    when the final distribution came from git; ``{"kind": "local", ...}`` for an editable,
    an old git install or anything else (the helper cannot reinstall it). ``channel`` is the
    line the installed wheels belong to (``stable`` or ``nightly``, by version), ``main`` for
    git, ``dev`` otherwise."""
    env = Path(env or sys.prefix)
    versions, urls = {}, {}
    for name in NAMES:
        d = _dist_info(env, name)
        if d is None:
            continue
        versions[name] = _metadata_version(d)
        try:
            urls[name] = json.loads((d / "direct_url.json").read_text())
        except (OSError, ValueError):
            urls[name] = None
    shape = "final" if FINAL_DIST in versions else "compat"
    version = versions.get(FINAL_DIST) or versions.get(legacy.COMPAT_SERVER)
    kinds, commits, dirs = set(), {}, set()
    for name in SHAPES[shape]:
        u = urls.get(name)
        if not u:
            kinds.add("unknown" if versions.get(name) else "missing")
            continue
        if u.get("vcs_info"):
            kinds.add("git")
            commits[name] = u["vcs_info"].get("commit_id")
        elif str(u.get("url", "")).endswith(".whl"):
            kinds.add("wheels")
            dirs.add(str(Path(u["url"].removeprefix("file://")).parent))
        else:
            kinds.add("local")
    if kinds == {"wheels"} and len(dirs) == 1:
        spec = {"kind": "wheels", "dir": dirs.pop(), "version": version, "shape": shape,
                "tool": TOOLS[shape]}
        channel = line_of(version)
    elif shape == "final" and kinds == {"git"} and commits.get(FINAL_DIST):
        spec = {"kind": "git", "commits": commits, "extras": EXTRAS, "shape": shape,
                "tool": TOOLS[shape]}
        channel = "main"
    else:
        spec = {"kind": "local", "kinds": sorted(kinds), "shape": shape}
        channel = "dev"
    kranto_extras = receipt_extras(env)
    if kranto_extras and spec["kind"] in ("wheels", "git"):
        spec["kranto_extras"] = kranto_extras
    return {"version": version, "versions": versions, "channel": channel, "spec": spec,
            "env": str(env)}


# -- the files under <home>/update ------------------------------------------------------------


def update_dir(home: Path) -> Path:
    return Path(home) / "update"


def releases_dir(home: Path) -> Path:
    return update_dir(home) / "releases"


def state_path(home: Path) -> Path:
    return update_dir(home) / "state.json"


def history_path(home: Path) -> Path:
    return update_dir(home) / "history.jsonl"


def previous_path(home: Path) -> Path:
    return update_dir(home) / "previous.json"


def cache_path(home: Path) -> Path:
    return Path(home) / "data" / "update.json"


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def history(home: Path, n: int = 5) -> list[dict]:
    """The last ``n`` finished updates, newest first."""
    try:
        lines = history_path(home).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= n:
            break
    return out


def cancel_path(home: Path) -> Path:
    return update_dir(home) / "cancel"


def lock_path(home: Path) -> Path:
    return update_dir(home) / "lock"


def helper_unit(unit: str) -> str:
    """The transient unit the helper runs as: ``kranto-update`` for ``kranto.service``."""
    return unit.removesuffix(".service") + "-update"


# -- the helper --------------------------------------------------------------------------------

FINAL = ("done", "rolled_back", "failed", "cancelled")
DRAIN_JOB_S = 120          # a running ingest is cut after this, as a plain restart would cut it
STOP_GUARD_S = 120         # processes from the tool dir must be gone this long after the stop
SLOW_STOP_S = 12           # a server since STOP has exited by then (stopping.HARD_EXIT_S)
VERIFY_S = 120             # the new version answers within this
LANE_S = 60                # and its loop lane ticks within this
INSTALL_S = 900
FREE_BYTES = 2 * 1024 ** 3
POLL_S = 5.0


class StepFailed(Exception):
    """A step that did not work; ``str`` is the reason shown everywhere."""


class Refused(Exception):
    """The update did not start (a precondition, or cancelled while draining): nothing
    changed."""


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: UP017 - 3.10


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")  # noqa: UP017 - 3.10


def _run(cmd: list[str], env: dict | None = None, timeout: float = 120) -> \
        subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


def cli_token(env: dict, unit: str) -> str | None:
    """The command line's token (``kranto/tokens.py``: ``~/.config/kranto/tokens/cli.token``,
    or the old config folder when only it exists; ``tokens.<unit>`` for another unit;
    ``$KRANTO_TOKENS_DIR`` when set); None when there is none (a server from before tokens
    takes the helper's writes without one)."""
    if env.get("KRANTO_TOKENS_DIR"):
        d = Path(env["KRANTO_TOKENS_DIR"]).expanduser()
    else:
        d = legacy.unit_store("tokens", {**env, "KRANTO_UNIT": unit})
    try:
        return (d / "cli.token").read_text().strip() or None
    except OSError:
        return None


def _http(method: str, url: str, body: dict | None = None, timeout: float = 10,
          headers: dict | None = None) -> tuple[int, dict | None]:
    """A request to the local server, with the same-origin headers its guard wants (and the
    command line's token, from ``Helper.api``)."""
    origin = url.split("/api/", 1)[0].split("/brb/", 1)[0]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Origin": origin, "Content-Type": "application/json", "Accept": "application/json",
        **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (OSError, ValueError):
        return 0, None
    try:
        return code, json.loads(raw or b"null")
    except ValueError:
        return code, None


# -- the self-check --------------------------------------------------------

SELFCHECK_PATHS = "/api/selfcheck/paths"
SELFCHECK_S = 180          # every read of the self-check within this
SELFCHECK_ONE_S = 30       # one read that takes longer did not answer


def get_any(url: str, timeout: float) -> tuple[int, dict | None]:
    """One local GET: ``(status, the JSON object)``, the body of an error's answer too (its error
    id); ``(0, None)`` when nothing answered in time."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            raw = exc.read()
        except OSError:
            raw = b""
    except (OSError, ValueError):
        return 0, None
    try:
        body = json.loads(raw or b"null")
    except ValueError:
        body = None
    return code, body if isinstance(body, dict) else None


def route_check(base: str, *, get: Callable = get_any, clock: Callable = time.monotonic,
                budget_s: float = SELFCHECK_S, one_s: float = SELFCHECK_ONE_S) -> dict:
    """Every GET the server lists (``/api/selfcheck/paths``: each list's first page, every topic,
    the home, each cub's page data, the activity, the builds UI's reads), read once, read-only,
    on this install's own data, within ``budget_s``. ``ok`` is False when any answered 500 or
    above, or did not answer within ``one_s``: ``failed`` names them (the path, the status, the
    error's id from Kranto's error answer). A server without the list (before 0.5.23) is not
    checked (``skipped``); the reads the budget did not reach are counted (``unchecked``), not
    failed."""
    start = clock()
    code, body = get(base + SELFCHECK_PATHS, one_s)
    if code == 404:
        return {"ok": True, "skipped": "this version has no self-check", "checked": 0, "of": 0,
                "failed": [], "unchecked": 0, "seconds": 0.0}
    paths = (body or {}).get("paths") if code == 200 else None
    if not isinstance(paths, list):
        return {"ok": False, "checked": 1, "of": 1, "unchecked": 0,
                "failed": [{"path": SELFCHECK_PATHS, "status": code,
                            "error_id": (body or {}).get("error_id"),
                            "exception": (body or {}).get("exception")}],
                "seconds": round(clock() - start, 1)}
    failed: list[dict] = []
    checked = 0
    for p in [x for x in paths if isinstance(x, str) and x.startswith("/")]:
        left = budget_s - (clock() - start)
        if left <= 0:
            break
        code, body = get(base + p, max(1.0, min(one_s, left)))
        checked += 1
        if code == 0 or code >= 500:
            failed.append({"path": p, "status": code, "error_id": (body or {}).get("error_id"),
                           "exception": (body or {}).get("exception")})
    return {"ok": not failed, "checked": checked, "of": len(paths), "failed": failed[:20],
            "unchecked": len(paths) - checked, "seconds": round(clock() - start, 1)}


def selfcheck_words(res: dict, version: str | None) -> str:
    """What a failed self-check says: ``0.5.23 broke on your data: GET /api/topics/7 answered
    500 (error 1a2b3c4d); 2 more``."""
    f = (res.get("failed") or [{}])[0]
    said = f"answered {f.get('status')}" if f.get("status") else "did not answer"
    more = len(res.get("failed") or []) - 1
    return (f"{version or 'the new version'} broke on your data: GET {f.get('path')} {said}"
            + (f" (error {f['error_id']})" if f.get("error_id") else "")
            + (f"; {more} more" if more > 0 else ""))


def tool_processes(roots: list[str], ignore: set[int]) -> list[tuple[int, str]]:
    """Processes running from the tool's environment or its scripts (``/proc``): what must not
    be running when the environment is replaced. ``roots`` are path prefixes."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        pid = int(d.name)
        if pid in ignore or pid == os.getpid():
            continue
        try:
            argv = [a.decode(errors="replace") for a in
                    (d / "cmdline").read_bytes().split(b"\0") if a]
        except OSError:
            continue
        if any(a.startswith(r) for a in argv[:2] for r in roots):
            out.append((pid, " ".join(Path(a).name if "/" in a else a for a in argv)[:120]))
    return out


def ppid_of(pid: int) -> int | None:
    """A process's parent (``/proc/<pid>/stat``), or None when it is gone."""
    try:
        stat = (Path("/proc") / str(pid) / "stat").read_text()
        return int(stat.rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def descends(pid: int, root: int, ppid: Callable[[int], int | None] = ppid_of) -> bool:
    """Whether ``pid`` is a child, grandchild, … of ``root``."""
    for _ in range(64):
        parent = ppid(pid)
        if parent is None or parent <= 1:
            return False
        if parent == root:
            return True
        pid = parent
    return False


def table_counts(db: Path) -> dict[str, int]:
    if not Path(db).exists():
        return {}
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        out = {}
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                              "AND name NOT LIKE 'sqlite_%'").fetchall():
            try:
                out[t] = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.OperationalError:
                continue
        return out
    finally:
        c.close()


class Helper:
    """One update (or rollback). Every outside effect goes through an attribute, so the tests
    pass fakes: ``run`` (systemctl, uv, Kranto), ``http`` (the local server), ``procs`` (the
    /proc guard), ``sleep``, ``clock``, ``which``, ``free_bytes``."""

    def __init__(self, home: Path, to: str, *, when: str = "after-build", port: int = 8765,
                 unit: str | None = None, keep: int = 3, env: dict | None = None,
                 ignore_pids: set[int] | None = None,
                 run: Callable = _run, http: Callable = _http, procs: Callable = tool_processes,
                 sleep: Callable = time.sleep, clock: Callable = time.monotonic,
                 which: Callable = shutil.which, free_bytes: Callable | None = None,
                 check_routes: Callable = route_check,
                 ppid: Callable[[int], int | None] = ppid_of) -> None:
        self.home = Path(home)
        self.ppid = ppid
        self.to = to
        self.when = when
        self.port = port
        self.keep = keep
        self.env = dict(os.environ if env is None else env)
        legacy.adopt_env(self.env)            # a unit written before the rename names old ones
        self.unit = unit or legacy.unit_name(self.env)
        self.env.update(KRANTO_HOME=str(self.home), KRANTO_UNIT=self.unit)
        user = Path(self.env.get("HOME") or Path.home())
        self.tool_dir = Path(self.env.get("UV_TOOL_DIR") or
                             user / ".local" / "share" / "uv" / "tools")
        self.bin_dir = Path(self.env.get("UV_TOOL_BIN_DIR") or user / ".local" / "bin")
        self.tool_env = tool_env_of(self.tool_dir)
        self.ignore = set(ignore_pids or ())
        self.run, self.http, self.procs = run, http, procs
        self.check_routes = check_routes
        self.sleep, self.clock, self.which = sleep, clock, which
        self.free_bytes = free_bytes or (lambda p: shutil.disk_usage(p).free)
        self.fail = {s.strip() for s in (self.env.get("KRANTO_UPDATE_FAIL") or "").split(",")
                     if s.strip()}
        self.base = f"http://127.0.0.1:{port}"
        self.st: dict = {}
        self.log_path = update_dir(self.home) / "log" / f"{_stamp()}.log"
        self.overrides = update_dir(self.home) / "git-overrides.txt"
        self.old: dict = {}
        self.backup_dir: Path | None = None
        self.prev_before = None

    # -- the record ------------------------------------------------------------------------

    def log(self, msg: str) -> None:
        line = f"{_utc()} {redact(msg)}"
        print(line, flush=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def state(self, state: str | None = None, **kw) -> None:
        if state and state != self.st.get("state"):
            kw.setdefault("step_started", _utc())
            self.log(f"state {state}" + (f": {kw['detail']}" if kw.get("detail") else ""))
        elif kw.get("detail") and kw["detail"] != self.st.get("detail"):
            self.log(f"  {kw['detail']}")
        if state:
            self.st["state"] = state
        self.st.update({k: (redact(v) if isinstance(v, str) else v) for k, v in kw.items()})
        write_json(state_path(self.home), self.st)

    def finish(self, state: str, **kw) -> str:
        self.state(state, finished=_utc(), **kw)
        with open(history_path(self.home), "a") as f:
            f.write(json.dumps({k: self.st.get(k) for k in
                                ("state", "from", "to", "when", "started", "finished",
                                 "reason", "detail", "log", "stop", "warning", "selfcheck")})
                    + "\n")
        return state

    # -- what the steps call ---------------------------------------------------------------

    def sh(self, *cmd: str, timeout: float = 120) -> subprocess.CompletedProcess:
        r = self.run(list(cmd), env=self.env, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        self.log(f"$ {' '.join(cmd)} -> {r.returncode}" + (f"\n{out[-4000:]}" if out else ""))
        return r

    def systemctl(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        return self.sh("systemctl", "--user", *args, timeout=timeout)

    def api(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict | None]:
        token = cli_token(self.env, self.unit) if method not in ("GET", "HEAD") else None
        if token:                                 # writes say who they are (OI); never logged
            return self.http(method, self.base + path, body,
                             headers={"Authorization": f"Bearer {token}"})
        return self.http(method, self.base + path, body)

    def guard(self) -> list[tuple[int, str]]:
        roots = [str(self.tool_dir / t) + "/" for t in sorted(set(TOOLS.values()))]
        roots += [str(self.bin_dir / n) for n in (product.COMMAND, *legacy.COMMANDS)]
        return self.procs(roots, self.ignore)

    def cmd(self) -> str:
        """The installed command: ``kranto``, else the old one (a version from before the
        rename has only that; a broken link left by a swap does not count)."""
        new = self.bin_dir / product.COMMAND
        return str(new if new.exists() else self.bin_dir / legacy.COMMAND)

    def main_pid(self) -> int | None:
        r = self.systemctl("show", "-p", "MainPID", "--value", self.unit)
        try:
            pid = int((r.stdout or "").strip() or 0)
        except ValueError:
            return None
        return pid or None

    # -- the steps ---------------------------------------------------------------------------

    def target(self) -> dict:
        """What ``--to`` names: a verified wheel set, or the previous spec. The meta-package's
        extras (``kranto[mcp]``) are those of the install being replaced, or the ones the
        previous spec recorded."""
        current = receipt_extras(self.tool_env)
        if self.to == "previous":
            spec = read_json(previous_path(self.home), None)
            if not spec or spec.get("kind") not in ("wheels", "git"):
                raise Refused("there is no previous version recorded to roll back to")
            extras = spec.get("kranto_extras", current)
            if spec["kind"] == "wheels":
                try:
                    found = verify_set(Path(spec["dir"]), spec["version"])
                except SetError as exc:
                    raise Refused(f"the previous set does not verify: {exc}") from exc
                shape = shape_of(found)
                return {**spec, "shape": shape, "tool": TOOLS[shape],
                        "args": install_args(found, extras)}
            if not (spec.get("commits") or {}).get(FINAL_DIST):
                raise Refused("the previous version came from git in an older layout; "
                              "the helper cannot reinstall it")
            return {**spec, "shape": "final", "tool": TOOLS["final"],
                    "args": git_install_args(spec["commits"], spec.get("extras") or EXTRAS,
                                             kranto_extras=extras)}
        version = tag_version(self.to)
        folder = releases_dir(self.home) / self.to
        try:
            found = verify_set(folder, version)
        except SetError as exc:
            raise Refused(f"the staged set for {self.to} does not verify: {exc}") from exc
        shape = shape_of(found)
        return {"kind": "wheels", "dir": str(folder), "version": version, "shape": shape,
                "tool": TOOLS[shape], "args": install_args(found, current),
                "kranto_extras": current}

    def preconditions(self) -> dict:
        self.state("requested", detail="checking the preconditions")
        tgt = self.target()
        if not self.which("uv", path=self.env.get("PATH")):
            raise Refused("uv is not on the unit's PATH")
        free = self.free_bytes(self.tool_dir if self.tool_dir.exists() else self.home)
        if free < FREE_BYTES:
            raise Refused(f"only {free // 2**20} MB free where the tool lives; 2 GB needed")
        active = (self.systemctl("is-active", self.unit).stdout or "").strip()
        if active != "active":
            raise Refused(f"{self.unit} is {active or 'not running'}: nothing to update in place")
        self.old = installed(self.tool_env)
        if not self.old.get("version"):
            raise Refused(f"no Kranto installation in {self.tool_env}")
        return tgt

    def drain(self) -> None:
        self.state("draining", detail="holding new work")
        code, _ = self.api("POST", "/api/hold", {"reason": f"update to {self.st.get('to')}",
                                                 "stop_builds": self.when == "now"})
        if code != 200:
            raise Refused(f"the server did not take the hold (HTTP {code})")
        job_since = None
        while True:
            if cancel_path(self.home).exists():
                cancel_path(self.home).unlink(missing_ok=True)
                raise Refused("cancelled while waiting")
            code, view = self.api("GET", "/api/update")
            busy = (view or {}).get("busy") or {}
            waiting = []
            if busy.get("job") or busy.get("cubs"):
                # a cub with a request in flight is waited for as a job is (
                #); an idle cub process is not: the restart stops it
                job_since = job_since or self.clock()
                if self.clock() - job_since < DRAIN_JOB_S:
                    waiting.append(f"the server's {busy['job']} run" if busy.get("job") else
                                   f"cub {', '.join(busy['cubs'])}")
            if busy.get("builds") or busy.get("fixes"):
                waiting.append(", ".join(x for x in (
                    f"{busy['builds']} build{'s' if busy['builds'] != 1 else ''}"
                    if busy.get("builds") else "",
                    f"{busy['fixes']} fix{'es' if busy['fixes'] != 1 else ''}"
                    if busy.get("fixes") else "") if x))
            main = self.main_pid()
            # the server's own children go down with its unit at the stop (and the stop's guard
            # still waits for every process from the tool): the console's Claude Code runs
            # `kranto mcp` from the tool, and waiting for it held every update while the console
            # was open (live, 2026-10-27)
            others = [p for p in self.guard() if p[0] != main
                      and not (main and descends(p[0], main, self.ppid))]
            if others and not waiting:
                waiting.append(f"{len(others)} process{'es' if len(others) != 1 else ''} from "
                               f"the tool ({others[0][1]})")
            if not waiting:
                return
            self.state("draining", detail="waiting for " + "; ".join(waiting))
            self.sleep(POLL_S)

    def backup(self) -> None:
        self.state("backing_up", detail="both databases, the configs and the unit")
        dest = self.home / "backups" / f"update-{_stamp()}-from-{self.old.get('version')}"
        r = self.sh(self.cmd(), "backup", str(dest), timeout=900)
        if r.returncode != 0:
            raise Refused(f"the backup failed: {(r.stderr or r.stdout).strip()[-300:]}")
        self.backup_dir = dest
        self.prev_before = read_json(previous_path(self.home), None)
        spec = self.old["spec"]
        if spec.get("kind") in ("wheels", "git"):
            write_json(previous_path(self.home), {**spec, "version": self.old["version"],
                                                  "recorded": _utc()})
        self.state(backup=str(dest))

    def stop(self) -> None:
        self.state("stopping", detail=f"systemctl --user stop {self.unit}")
        start, since = self.clock(), int(time.time()) - 1
        r = self.systemctl("stop", self.unit, timeout=150)
        if r.returncode != 0:
            raise StepFailed(f"could not stop {self.unit}: {(r.stderr or '').strip()[:200]}")
        self.stop_result(self.clock() - start, self.stop_said(since))
        start = self.clock()
        while True:
            left = self.guard()
            if not left:
                return
            if self.clock() - start > STOP_GUARD_S:
                raise StepFailed(f"{left[0][1]} (pid {left[0][0]}) still runs from the tool "
                                 "after the stop")
            self.state("stopping", detail=f"waiting for {left[0][1]} (pid {left[0][0]})")
            self.sleep(POLL_S)

    def stop_said(self, since: int) -> str | None:
        """The old server's own account of its stop, from its journal since ``since`` (epoch
        seconds): its last ``stop:`` line ("done in 1.2 s, clean", "... cut off: the ingest
        job", "forced exit after 12.0 s ..."). None from a server before STOP, which says
        nothing."""
        r = self.sh("journalctl", "--user", "-u", self.unit, "--since", f"@{since}", "-o", "cat",
                    "--no-pager", "-q", timeout=30)
        marks = tuple(f" {pkg}.stop stop: " for pkg in (product.DIST, legacy.OLD_PACKAGE))
        said = [line.split(" stop: ", 1)[1].strip() for line in (r.stdout or "").splitlines()
                if any(m in line for m in marks) and ("done in" in line or "forced" in line)]
        return said[-1][:300] if said else None

    def stop_result(self, seconds: float, said: str | None = None) -> None:
        """How the old server ended, from systemd and its own ``stop:`` line: ``stop`` in the
        state and the history, and a ``warning`` when it did not stop on SIGTERM (systemd
        killed it at its stop timeout), when it took longer than ``SLOW_STOP_S``, or when it had
        to force its exit. A warning, not a rollback: the server that was slow is the old one."""
        r = self.systemctl("show", "-p", "Result", "-p", "ExecMainCode", "-p", "ExecMainStatus",
                           self.unit)
        props = dict(line.split("=", 1) for line in (r.stdout or "").splitlines() if "=" in line)
        result = props.get("Result") or "unknown"
        # ExecMainCode 2 is CLD_KILLED: the main process died of the signal in ExecMainStatus
        killed = result == "timeout" or (props.get("ExecMainCode") == "2"
                                          and props.get("ExecMainStatus") == "9")
        stop = {"seconds": round(seconds, 1), "result": result, "killed": killed}
        if said:
            stop["said"] = said
        self.state(stop=stop)
        self.log(f"stopped in {seconds:.1f} s, systemd result {result}"
                 + (f"; the server said: {said}" if said else ""))
        it_said = f"; it said: {said}" if said else ""
        if killed:
            self.state(warning=f"the old server did not stop on SIGTERM: systemd killed it after "
                               f"{seconds:.0f} s (result {result}){it_said}")
        elif seconds > SLOW_STOP_S or (said and said.startswith("forced")):
            self.state(warning=f"the old server was slow to stop: {seconds:.0f} s (a stop takes "
                               f"at most {SLOW_STOP_S} s){it_said}")
        else:
            return
        self.log(f"WARNING: {self.st['warning']}")

    def swap_out(self, tool: str) -> None:
        """Uninstall every Kranto tool but ``tool`` before ``tool`` is installed (the crossing,
        and its way back). Before, not after: uv's uninstall removes the commands of the same
        names even when the other tool has since taken them over."""
        for other in sorted(set(TOOLS.values()) - {tool}):
            if (self.tool_dir / other).is_dir():
                r = self.sh("uv", "tool", "uninstall", other, timeout=300)
                if r.returncode != 0 and (self.tool_dir / other).is_dir():
                    raise StepFailed(f"uv tool uninstall {other} failed: "
                                     f"{(r.stderr or r.stdout).strip()[-300:]}")

    def install(self, args: list[str], *, offline: bool = False, forward: bool = True,
                tool: str | None = None) -> None:
        if tool:
            self.swap_out(tool)
        cmd = ["uv", "tool", "install", "--force", "--python", "3.12",
               *(["--offline"] if offline else []), *args]
        r = self.sh(*cmd, timeout=INSTALL_S)
        if tool:
            self.tool_env = self.tool_dir / tool
        if forward and "install" in self.fail:
            raise StepFailed("forced: install")
        if r.returncode != 0:
            raise StepFailed(f"uv tool install failed: {(r.stderr or r.stdout).strip()[-300:]}")

    def start(self) -> None:
        r = self.sh(self.cmd(), "up", "--no-browser", timeout=300)
        if "start" in self.fail:
            raise StepFailed("forced: start")
        if r.returncode != 0:
            raise StepFailed(f"kranto up failed: {(r.stderr or r.stdout).strip()[-300:]}")

    def verify(self, want: dict) -> None:
        """The new version answers as itself, with the builds UI and a loop lane that ticks
        without errors; the installed distributions are the ones asked for."""
        have = installed(self.tool_env)
        if want.get("kind") == "wheels" and (
                have.get("version") != want.get("version")
                or (have.get("spec") or {}).get("kind") != "wheels"):
            raise StepFailed(f"installed {have.get('version')} "
                             f"({(have.get('spec') or {}).get('kind')}), not the "
                             f"{want.get('version')} wheels")
        if want.get("kind") == "git" and any(
                (have.get("spec") or {}).get("commits", {}).get(k) != v
                for k, v in (want.get("commits") or {}).items() if k == FINAL_DIST):
            raise StepFailed("the installed commits are not the ones asked for")
        if want.get("tool") and Path(have.get("env") or "").name != want["tool"]:
            raise StepFailed(f"the tool is {Path(have.get('env') or '').name}, not "
                             f"{want['tool']}")
        r = self.sh(self.cmd(), "--version", timeout=60)
        if r.returncode != 0 or (have.get("version") or "?") not in (r.stdout or ""):
            raise StepFailed(f"{Path(self.cmd()).name} --version says "
                             f"{(r.stdout or r.stderr).strip()[:120]}")
        server_version = have.get("version")
        deadline = self.clock() + VERIFY_S
        status = None
        while self.clock() < deadline:
            code, status = self.api("GET", "/api/status")
            if code == 200 and status and status.get("version") == server_version:
                break
            self.sleep(2)
        else:
            raise StepFailed(f"/api/status did not answer as {server_version} within "
                             f"{VERIFY_S} s")
        code, _ = self.api("GET", "/brb/api/header")
        if code != 200:
            raise StepFailed(f"the builds UI is not mounted (/brb/api/header: HTTP {code})")
        if (status.get("lanes") or {}).get("loop") is not None:
            deadline = self.clock() + LANE_S
            while True:
                lane = ((status or {}).get("lanes") or {}).get("loop") or {}
                if lane.get("errors"):
                    raise StepFailed(f"the loop lane failed: {lane.get('last_error')}")
                if lane.get("ticks", 0) >= 1 and lane.get("state") in ("idle", "ticking"):
                    break
                if self.clock() > deadline:
                    raise StepFailed(f"the loop lane did not tick within {LANE_S} s "
                                     f"({lane.get('state')}: {lane.get('detail')})")
                self.sleep(2)
                _, status = self.api("GET", "/api/status")
        if "verify" in self.fail:
            raise StepFailed("forced: verify")
        self.counts_after()
        self.selfcheck(have.get("version"))

    def selfcheck(self, version: str | None) -> None:
        """The new version reads every page on this install's own data (``route_check``,
        read-only, within ``SELFCHECK_S``): any answer of 500 or above, or none, rolls it back
       . What it found is kept in the state and the history
        (``selfcheck``): the paths, their statuses and the errors' ids, which the server kept in
        ``data/errors.jsonl`` for Send this error and the error reports."""
        self.state("verifying", detail="every page Kranto serves, read once on your data")
        res = self.check_routes(self.base)
        self.state(selfcheck={k: res.get(k) for k in ("ok", "checked", "of", "unchecked",
                                                      "failed", "seconds", "skipped")
                              if res.get(k) is not None})
        self.log(f"self-check: {res.get('checked')} of {res.get('of')} reads in "
                 f"{res.get('seconds')} s" + (f", {res['unchecked']} past the budget"
                                              if res.get("unchecked") else "")
                 + (f"; {res['skipped']}" if res.get("skipped") else "")
                 + "".join(f"\n  FAIL GET {f['path']}: {f['status'] or 'no answer'}"
                           + (f" (error {f['error_id']})" if f.get("error_id") else "")
                           for f in res.get("failed") or []))
        if "selfcheck" in self.fail:
            raise StepFailed("forced: selfcheck")
        if not res.get("ok"):
            raise StepFailed(selfcheck_words(res, version))

    def counts_after(self) -> None:
        """Counts only grow: a table with fewer rows than before is logged (retention purges
        by design, so a warning, not a failure)."""
        if not self.backup_dir:
            return
        before = read_json(self.backup_dir / "counts-before.json", {}) or {}
        info = read_json(self.backup_dir / "backup.json", {}) or {}
        after = {}
        for name, d in (info.get("databases") or {}).items():
            after["afk" if name == "kranto.db" else "loop"] = table_counts(Path(d["from"]))
        (self.backup_dir / "counts-after.json").write_text(json.dumps(after, indent=1) + "\n")
        lower = [f"{db}.{t} {n} -> {after.get(db, {}).get(t)}" for db, ts in before.items()
                 for t, n in ts.items() if after.get(db, {}).get(t, n) < n]
        self.log("counts after: " + ("no table lower" if not lower else
                                     "LOWER: " + "; ".join(lower)))

    def previous_install(self, spec: dict) -> tuple[list[str], str]:
        """The ``uv tool install`` arguments and the tool for the install being replaced."""
        extras = spec.get("kranto_extras") or ()
        if spec.get("kind") == "wheels":
            found = verify_set(Path(spec["dir"]), self.old["version"])
            shape = shape_of(found)
            return install_args(found, extras), TOOLS[shape]
        if spec.get("kind") == "git" and (spec.get("commits") or {}).get(FINAL_DIST):
            return (git_install_args(spec["commits"], spec.get("extras") or EXTRAS,
                                     kranto_extras=extras), TOOLS["final"])
        raise StepFailed(f"the previous install ({spec.get('kind')}) cannot be "
                         "reinstalled by the helper")

    def rollback(self, reason: str) -> str:
        self.state("rolling_back", reason=reason, detail=f"putting {self.old.get('version')} back")
        spec = self.old.get("spec") or {}
        manual = self.manual_lines(spec)
        try:
            if "rollback" in self.fail:
                raise StepFailed("forced: rollback")
            self.systemctl("stop", self.unit, timeout=150)
            args, tool = self.previous_install(spec)
            if spec.get("kind") == "wheels":
                try:
                    self.install(args, offline=True, forward=False, tool=tool)
                except StepFailed:
                    self.install(args, forward=False, tool=tool)
            else:
                self.install(args, forward=False, tool=tool)
            r = self.sh(self.cmd(), "up", "--no-browser", timeout=300)
            if r.returncode != 0:
                raise StepFailed(f"{Path(self.cmd()).name} up failed: "
                                 f"{(r.stderr or r.stdout).strip()[-300:]}")
            back = installed(self.tool_env)
            want = self.old.get("version")
            deadline = self.clock() + VERIFY_S
            while True:
                code, status = self.api("GET", "/api/status")
                if code == 200 and status and status.get("version") == want:
                    break
                if self.clock() > deadline:
                    raise StepFailed(f"the previous version did not answer within {VERIFY_S} s")
                self.sleep(2)
            if back.get("version") != self.old.get("version"):
                raise StepFailed(f"{back.get('version')} is installed, not "
                                 f"{self.old.get('version')}")
        except (StepFailed, SetError) as exc:
            self.log(f"rollback failed: {exc}")
            return self.finish("failed", reason=f"{reason}; the rollback failed too: {exc}",
                               detail=manual)
        if self.prev_before is not None:
            write_json(previous_path(self.home), self.prev_before)
        elif previous_path(self.home).exists():
            previous_path(self.home).unlink()
        return self.finish("rolled_back", reason=reason,
                           detail=f"{self.old.get('version')} is running again; the data was "
                                  "not touched")

    def manual_lines(self, spec: dict) -> str:
        """The fallback by hand (RUNBOOK), for ``failed``: uninstall the other tool when the
        update crossed shapes, reinstall the previous one, start it."""
        tool = spec.get("tool") or TOOLS[spec.get("shape") or "final"]
        if spec.get("kind") == "wheels":
            found = wheels_in(Path(spec["dir"]), self.old.get("version"))
            ok = set(found) in [set(n) for n in SHAPES.values()]
            if ok:
                tool = TOOLS[shape_of(found)]
            args = " ".join(f'"{a}"' if " " in a else a
                            for a in install_args(found, spec.get("kranto_extras") or ())) \
                if ok else f"{spec['dir']}/*.whl"
        elif spec.get("kind") == "git" and (spec.get("commits") or {}).get(FINAL_DIST):
            args = " ".join(f'"{a}"' if " " in a else a
                            for a in git_install_args(spec["commits"],
                                                      spec.get("extras") or EXTRAS,
                                                      kranto_extras=spec.get("kranto_extras")
                                                      or ()))
        else:
            args = "<the previous wheels or git spec>"
        others = [t for t in sorted(set(TOOLS.values()) - {tool})
                  if (self.tool_dir / t).is_dir()]
        swap = "".join(f"uv tool uninstall {t}; " for t in others)
        command = self.bin_dir / (product.COMMAND if tool == TOOLS["final"] else legacy.COMMAND)
        bk = f"; restore the databases from {self.backup_dir} only if the data is damaged" \
            if self.backup_dir else ""
        return (f"by hand: systemctl --user stop {self.unit}; {swap}uv tool install --force "
                f"--python 3.12 {args}; {command} up --no-browser{bk}")

    def prune(self) -> None:
        """Keep ``keep`` update backups and wheel sets, never the running or previous set."""
        backups = sorted(p for p in (self.home / "backups").glob("update-*") if p.is_dir())
        for p in backups[:-self.keep]:
            shutil.rmtree(p, ignore_errors=True)
            self.log(f"pruned {p}")
        keep_dirs = {str(Path(self.st.get("target_dir") or "")),
                     str(Path((read_json(previous_path(self.home), {}) or {}).get("dir") or ""))}
        sets = sorted((p for p in releases_dir(self.home).glob("v*") if p.is_dir()
                       and not p.name.endswith(".partial")), key=lambda p: vkey(p.name))
        for p in sets[:-self.keep]:
            if str(p) not in keep_dirs:
                shutil.rmtree(p, ignore_errors=True)
                self.log(f"pruned {p}")

    # -- the whole --------------------------------------------------------------------------

    def run_all(self) -> str:
        update_dir(self.home).mkdir(parents=True, exist_ok=True)
        lock = open(lock_path(self.home), "a")  # noqa: SIM115 - held for the whole run
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another kranto update is running", file=sys.stderr)
            lock.close()
            return "busy"
        try:
            return self._run_all()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    def _run_all(self) -> str:
        cancel_path(self.home).unlink(missing_ok=True)
        self.st = {"state": None, "to": tag_version(self.to) if self.to != "previous"
                   else "previous", "when": self.when, "started": _utc(), "unit": self.unit,
                   "log": str(self.log_path), "reason": None, "detail": None,
                   "pid": os.getpid()}
        self.state("requested", detail="starting")
        try:
            tgt = self.preconditions()
            to = tgt.get("version") or "previous"
            self.state(to=to, target_dir=tgt.get("dir"), **{"from": self.old.get("version")})
            self.drain()
            self.backup()
        except Refused as exc:
            self.api("DELETE", "/api/hold")
            self.log(f"not started: {exc}")
            return self.finish("cancelled", reason=str(exc), detail="nothing was changed")
        try:
            self.stop()
        except StepFailed as exc:
            # nothing is installed yet: the same version starts again
            self.systemctl("start", self.unit, timeout=150)
            return self.finish("cancelled", reason=str(exc),
                               detail="nothing was installed; Kranto was started again")
        try:
            self.state("installing", detail=f"uv tool install {to}")
            self.install(tgt["args"], tool=tgt.get("tool"))
            self.state("starting", detail="kranto up")
            self.start()
            self.state("verifying", detail="the new version answers, the lane ticks")
            self.verify(tgt)
        except (StepFailed, SetError) as exc:
            return self.rollback(str(exc))
        except Exception as exc:  # noqa: BLE001 - anything unforeseen still rolls back
            return self.rollback(f"{type(exc).__name__}: {exc}")
        self.prune()
        warning = self.st.get("warning")
        return self.finish("done", reason=None,
                           detail=f"{to} is running" + (f"; warning: {warning}" if warning else ""))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Kranto's update helper (run by systemd-run)")
    p.add_argument("--home", required=True)
    p.add_argument("--to", required=True,
                   help="vX.Y.Z or vX.Y.0-devN (a staged set) or previous")
    p.add_argument("--when", default="after-build", choices=("after-build", "now"))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--unit", default=None,
                   help="the unit to restart (default: this install's own)")
    p.add_argument("--keep", type=int, default=3)
    p.add_argument("--ignore-pid", type=int, action="append", default=[])
    args = p.parse_args(argv)
    state = Helper(Path(args.home), args.to, when=args.when, port=args.port, unit=args.unit,
                   keep=max(1, args.keep), ignore_pids=set(args.ignore_pid)).run_all()
    return {"done": 0, "rolled_back": 3, "failed": 4, "cancelled": 5}.get(state, 6)


if __name__ == "__main__":
    sys.exit(main())
