"""Installing, updating, stopping and removing a cub.

An install is a job of steps, each a ``cub_installs`` row: ``queued``, ``fetching``,
``fetched``, ``inspected``, ``awaiting_confirm`` (the owner reads the dialog), then
``placing``, ``placed``, ``pinned``, ``installed``; or ``cancelled``, or ``failed`` with why.

``fetch`` runs steps 1 to 5: a git checkout at the asked ref (no credential ever, 300 s) or a
folder's copy, the tree's checks, the one validator, the inventory and the words, and leaves
the tree in ``cubs/.staged/<job>/src`` with ``staged.json``. ``install`` (the owner's confirm)
runs 6 to 9: the venv built outside the sandbox (``uv``, hashes required, wheels only), the
staged folder renamed into ``cubs/<id>``, its tree hash checked against step 4's, and the pin and
the registry row written in one transaction. No code of the cub runs before step 9; nothing
unpinned ever runs.

An update is a fetch from the recorded source, with the files' diff and the permission delta;
applying it keeps the topics the owner narrowed and, when the delta grew, puts every kind back
to dry before the new version is pinned. Stop kills the process, pauses the cub and expires its
open tickets; remove does the same, records ``removed`` and moves the folder to
``cubs/.removed`` for 30 days (its tickets, calls, runs and pins stay for ever; its key-value
rows until ``--purge``).

The page's house confirm (the ``ui`` door) is the web layer's to check; the command line's
``--yes`` reaches the same functions with door ``cli``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from bears_cub.schema import HOST_RANGE

from ...store import iso, utcnow
from ...stored.cubs import CubSource, Grants, InstallDetail
from .. import events, tickets
from ..manifest import ManifestError, grants_of, manifest_hash, version_key
from . import files, inspect, registry
from . import settings as cub_settings

log = logging.getLogger("kranto.core.cubs")
STEPS = ("queued", "fetching", "fetched", "inspected", "awaiting_confirm", "placing", "placed",
         "pinned", "installed")
TERMINAL = ("installed", "cancelled", "failed", "removed")
GIT_TIMEOUT_S = 300
VENV_TIMEOUT_S = 600
YAML_MAX = 64 * 1024
INDEX_NAME = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+/[A-Za-z0-9_.-]+")
SHA = re.compile(r"[0-9a-f]{7,40}")
# a tag, a branch or a commit: never one that git could read as an option (``-u<command>``)
REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,99}")
_LOCK = threading.Lock()


class InstallError(Exception):
    """Refused or failed, in words; ``code`` for the page (400, 403, 404, 409)."""

    def __init__(self, words: str, code: int = 400) -> None:
        super().__init__(words)
        self.words, self.code = words, code


# -- the job's record ---------------------------------------------------------------------------


def _step(store: Any, job_id: str, kind: str, cid: str | None, step: str,
          detail: dict[str, Any] | None = None) -> None:
    store.insert("cub_installs", {"job_id": job_id, "cub": cid, "kind": kind, "step": step,
                                  "detail": InstallDetail.write(detail) if detail else None,
                                  "created_at": iso(utcnow())})


def _staged(cfg: Any, job_id: str) -> Path:
    return files.root(cfg) / ".staged" / job_id


def _record(cfg: Any, job_id: str) -> dict[str, Any] | None:
    p = _staged(cfg, job_id) / "staged.json"
    try:
        got = json.loads(p.read_text())
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def _job_now(store: Any, cfg: Any, job_id: str) -> dict[str, Any]:
    """A job whose step this module has just written: it is there."""
    got = job(store, cfg, job_id)
    assert got is not None
    return got


def job(store: Any, cfg: Any, job_id: str) -> dict[str, Any] | None:
    """A job as the page polls it: its state, its error, and once inspected, the cub."""
    rows = [dict(r) for r in store.query("SELECT * FROM cub_installs WHERE job_id = ? "
                                         "ORDER BY id", (job_id,))]
    if not rows:
        return None
    last = rows[-1]
    detail = InstallDetail.load(last["detail"]).extra
    out = {"id": job_id, "kind": rows[0]["kind"], "state": last["step"],
           "target": rows[0]["cub"] or InstallDetail.load(rows[0]["detail"]).extra.get("source"),
           "created_at": rows[0]["created_at"], "updated_at": last["created_at"]}
    if last["step"] in ("failed", "cancelled"):
        out["error"] = detail.get("why")
    rec = _record(cfg, job_id)
    if rec is not None and last["step"] in ("inspected", "awaiting_confirm", "placing"):
        out["cub"] = {k: rec[k] for k in ("id", "title", "version", "trust", "manifest", "hash",
                                          "tree_hash", "sha", "source", "inventory", "words")}
        for k in ("delta", "diff"):
            if rec.get(k) is not None:
                out["cub"][k] = rec[k]
        out["needs"] = rec["needs"]
    if last["step"] == "queued" and _age_s(last["created_at"]) > 60:
        out["state"], out["error"] = "failed", "the job never started"
    return out


def _age_s(at: str) -> float:
    from datetime import datetime
    return (utcnow() - datetime.fromisoformat(at.replace("Z", "+00:00"))).total_seconds()


def jobs(store: Any, cfg: Any, limit: int = 20, unreadable: bool = False) -> list[dict[str, Any]]:
    """The newest install jobs. One that cannot be read is kept once by its error's id and left
    out; ``unreadable`` lists it as "Couldn't read this job" instead (the page's list, RCA A3)."""
    from ...rowsafe import each, is_unreadable
    ids = [r["job_id"] for r in store.query(
        "SELECT job_id, MAX(id) AS last FROM cub_installs GROUP BY job_id ORDER BY last DESC "
        "LIMIT ?", (int(limit),))]
    out = each(ids, lambda i: job(store, cfg, i), "job", ident=lambda i: i)
    return [j for j in out if j is not None and (unreadable or not is_unreadable(j))]


# -- where a cub comes from -----------------------------------------------------------------------


def set_source(rt: Any, cid: str, source: str, ref: str | None = None) -> dict[str, Any]:
    """``kranto cub source ID SOURCE``: where a cub's updates are read from from now on (a cub
    whose folder is gone). Only ``cubs.source`` and ``source_kind`` change, in a
    new row; the installed copy, its pin, its grants and its version stay. The next look for
    an update (the daily ``cubs.updates``, or ``kranto cub update``) reads the new place."""
    row = registry.latest(rt.store, cid)
    if row is None or row["state"] == "removed":
        raise InstallError(f"no cub {cid}", 404)
    spec = parse_source(source, ref)
    if spec["kind"] == "folder" and not Path(str(spec.get("path") or "")).is_dir():
        raise InstallError(f"{source} is not a folder here")
    new = {k: v for k, v in spec.items() if k != "kind" and v is not None}
    return registry.append(rt.store, row, source_kind=spec["kind"], source=new,
                           note=f"source set to {source}")


def parse_source(source: str, ref: str | None = None) -> dict[str, Any]:
    """``{kind: folder|git, path|url, ref, subdirectory}``; an index name is refused until the
    index opens. A git URL may end in ``#subdirectory=cubs/x`` (as pip writes it): the cub is
    that folder of the repository, for a repository that holds several."""
    s = str(source or "").strip()
    if not s:
        raise InstallError("say where the cub is: a folder or a git URL")
    if re.match(r"(http|git)://", s):
        raise InstallError("a cub's git URL is https:// or ssh://, never http:// or git://")
    if s.startswith(("https://", "ssh://", "git@", "file://")):
        if ref is not None and (not REF.fullmatch(ref) or ".." in ref):
            raise InstallError("--ref is a tag, a branch or a commit")
        url, _, frag = s.partition("#")
        sub = None
        if frag:
            m = re.fullmatch(r"subdirectory=([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)", frag)
            if not m or any(part in (".", "..") for part in m.group(1).split("/")):
                raise InstallError("after # a cub's git URL takes subdirectory=path/in/the/repo, "
                                   "a relative path with no . or .. in it")
            sub = m.group(1)
        return {"kind": "git", "url": url, "ref": ref, "subdirectory": sub}
    path = Path(s).expanduser()
    if path.is_dir():
        if ref is not None:
            raise InstallError("--ref is for a git URL; a folder is read as it is now")
        return {"kind": "folder", "path": str(path.resolve())}
    if INDEX_NAME.fullmatch(s):
        raise InstallError("the cub index opens at Kranto 0.7: install from a folder or a git URL "
                           "for now")
    raise InstallError(f"{s} is not a folder here nor a git URL", 404)


TRUST = {"folder": "owner", "git": "unreviewed"}


def _git(args: list[str], cwd: Path) -> str:
    # none of the owner's git or ssh configuration (aliases, rewrites, hosts, keys by name) and
    # never a prompt: a stranger's repository is fetched as by a fresh account
    env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")},
           "GIT_ASKPASS": "true", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -F /dev/null"}
    try:
        p = subprocess.run(["git", "-c", "credential.helper=", "-c", "advice.detachedHead=false",
                            "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never",
                            *args], cwd=cwd, capture_output=True, text=True,
                           timeout=GIT_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        raise InstallError(f"git {args[0]} took longer than {GIT_TIMEOUT_S} s") from None
    except OSError:
        raise InstallError("git is not installed here") from None
    if p.returncode != 0:
        raise InstallError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()[-240:]}")
    return p.stdout


def checkout(url: str, ref: str | None, dest: Path) -> str:
    """``url`` at ``ref`` (a tag, a branch or a commit; none: its default branch) in ``dest``,
    shallow where the server allows it; the commit's sha."""
    if ref is not None and (not REF.fullmatch(ref) or ".." in ref):
        raise InstallError("--ref is a tag, a branch or a commit")
    if url.startswith("-"):
        raise InstallError("not a git URL")
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    _git(["init", "-q"], dest)
    _git(["remote", "add", "--", "origin", url], dest)
    try:
        _git(["fetch", "-q", "--depth", "1", "--", "origin", ref or "HEAD"], dest)
        _git(["checkout", "-q", "--detach", "FETCH_HEAD"], dest)
    except InstallError:
        if not ref:
            raise
        _git(["fetch", "-q", "--", "origin"], dest)          # a server that will not fetch a sha
        _git(["checkout", "-q", "--detach", ref], dest)      # (REF: never read as an option)
    sha = _git(["rev-parse", "HEAD"], dest).strip()
    if ref and SHA.fullmatch(ref) and not sha.startswith(ref):
        raise InstallError(f"asked for commit {ref}, got {sha}")
    return sha


# -- steps 1 to 5: fetch and inspect --------------------------------------------------------------


def start(rt: Any, source: str | None = None, *, ref: str | None = None, kind: str = "add",
          cid: str | None = None, background: bool = True) -> dict[str, Any]:
    """Record a fetch job and run it: in a thread of this process for the page (no request
    waits on git), inline for the command line. Returns the job."""
    if kind == "update":
        row = registry.latest(rt.store, cid or "")
        if row is None or row["state"] == "removed":
            raise InstallError(f"no cub {cid} is installed", 404)
        src = CubSource.load(row["source"]).extra
        if row["source_kind"] == "folder":
            source, ref = src.get("path"), None
        elif row["source_kind"] == "git":
            source, ref = src.get("url"), src.get("ref")
            if src.get("subdirectory"):              # the same folder of that repository
                source = f"{source}#subdirectory={src['subdirectory']}"
        else:
            raise InstallError(f"{cid} came from {row['source_kind']}: it updates from there")
    spec = parse_source(source or "", ref)
    job_id = uuid.uuid4().hex[:12]
    files.ensure_root(rt.cfg)
    _step(rt.store, job_id, kind, cid, "queued", {"source": source, "ref": ref})
    if background:
        threading.Thread(target=_fetch_logged, args=(rt, job_id, spec, kind, cid),
                         name=f"cub-fetch-{job_id}", daemon=True).start()
    else:
        # inline: the job the fetch answers, which is the one staged already when the same
        # update was (the command line then names that job)
        return _fetch_logged(rt, job_id, spec, kind, cid) or _job_now(rt.store, rt.cfg, job_id)
    return _job_now(rt.store, rt.cfg, job_id)


def _fetch_logged(rt: Any, job_id: str, spec: dict[str, Any], kind: str,
                  cid: str | None) -> dict[str, Any] | None:
    try:
        return fetch(rt, job_id, spec, kind=kind, cid=cid)
    except Exception:  # noqa: BLE001 - recorded as failed; the thread must not die silently
        log.exception("cub fetch %s", job_id)
        _step(rt.store, job_id, kind, cid, "failed", {"why": "Kranto failed while fetching"})
        return None


def fetch(rt: Any, job_id: str, spec: dict[str, Any], *, kind: str = "add",
          cid: str | None = None) -> dict[str, Any]:
    """Steps 2 to 5 for a job recorded ``queued``."""
    cfg, store = rt.cfg, rt.store
    work = files.root(cfg) / ".work" / job_id
    staged = _staged(cfg, job_id)

    def fail(why: str) -> dict[str, Any]:
        shutil.rmtree(work, ignore_errors=True)
        if staged.exists():
            files.make_writable(staged)
            shutil.rmtree(staged, ignore_errors=True)
        _step(store, job_id, kind, cid, "failed", {"why": why})
        return _job_now(store, cfg, job_id)

    try:
        _step(store, job_id, kind, cid, "fetching")
        repo, sha = work / "repo", None
        if spec["kind"] == "git":
            sha = checkout(spec["url"], spec.get("ref"), repo)
        else:
            inspect.walk(Path(spec["path"]))           # judge the folder before copying it
            inspect.copy_tree(Path(spec["path"]), repo)
        top = repo
        if spec.get("subdirectory"):
            top = repo / spec["subdirectory"]
            # a real folder of the checkout: no link anywhere on the way to it
            if top.resolve() != repo.resolve() / spec["subdirectory"] or not top.is_dir():
                return fail(f"{spec['subdirectory']} is not a folder of that repository")
        tree = work / "tree"
        inspect.copy_tree(top, tree)
        paths = inspect.walk(tree)
        yaml_path = tree / "cub.yaml"
        if "cub.yaml" not in paths:
            return fail("no cub.yaml at the top of the folder")
        if yaml_path.stat().st_size > YAML_MAX:
            return fail(f"cub.yaml is over {YAML_MAX // 1024} KiB")
        _step(store, job_id, kind, cid, "fetched", {"sha": sha, "files": len(paths)})

        from .. import registry as core_registry
        raw = core_registry.load_cub_yaml(yaml_path.read_text(encoding="utf-8"))
        digest = manifest_hash(raw)
        m = core_registry.validate_cub(json.loads(json.dumps(raw)), files=set(paths),
                                       update_of=cid if kind == "update" else None)
        current = registry.latest(store, m["id"])
        if kind == "update" and current is None:
            return fail(f"no cub {cid} is installed")
        cur: dict[str, Any] = current or {}
        if kind == "add" and current is not None and current["state"] != "removed":
            return fail(f"{m['id']} is installed already: update it (kranto cub update {m['id']})")
        if kind == "add" and any(f.id == m["id"] for f in core_registry.first_party()):
            return fail(f"{m['id']} is one of Kranto's own features")
        if kind == "update":
            if m["id"] != cid:
                return fail(f"the cub.yaml there is {m['id']}, not {cid}")
            if version_key(m["version"]) <= version_key(cur["version"]) and \
                    files.tree_hash(tree) != cur["tree_hash"]:
                return fail(f"its files changed but its version did not grow ({m['version']}, "
                            f"installed {cur['version']}): raise the version")
        if m.get("requirements"):
            from ..manifest import check_requirements
            check_requirements((tree / m["requirements"]).read_text(encoding="utf-8"))
        grants = grants_of(m)
        trust = TRUST[spec["kind"]] if kind == "add" else cur["trust"]
        inv = inspect.inventory(tree, paths)
        from . import sandbox
        weak = cub_settings.weak_limits(cfg, trust, sandbox.limits_mode())
        if weak:                         # said before the install, not at its first run
            inv["findings"].append({"level": "warn", "text": weak[0].upper() + weak[1:]})
        th = files.tree_hash(tree)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.mkdir(mode=0o700)
        tree.rename(staged / "src")
        shutil.rmtree(work, ignore_errors=True)
        rec = {"job": job_id, "kind": kind, "id": m["id"], "title": m.get("title") or m["id"],
               "version": m["version"], "trust": trust, "manifest": m, "hash": digest,
               "tree_hash": th, "sha": sha,
               "source": {k: v for k, v in spec.items() if v is not None},
               "inventory": inv, "grants": grants,
               "words": inspect.words(m, grants, trust=trust, cap_usd=_cap(cfg, m, trust)),
               "needs": "house"}
        if kind == "update":
            old = Grants.load(cur["grants"]).wire()
            rec["delta"] = inspect.delta(old, grants)
            rec["diff"] = inspect.diff(files.cub_dir(cfg, cid or m["id"]) / "src",
                                       staged / "src")
            rec["needs"] = "house" if rec["delta"]["grown"] or rec["delta"]["high_trust"] \
                else "confirm"
        (staged / "staged.json").write_text(json.dumps(rec, default=str))
        os.chmod(staged / "staged.json", 0o600)
        _step(store, job_id, kind, m["id"], "inspected",
              {"findings": len(inv["findings"]), "files": inv["files"]})
        if kind == "update" and th == cur["tree_hash"]:
            files.make_writable(staged)
            shutil.rmtree(staged, ignore_errors=True)
            _step(store, job_id, kind, m["id"], "cancelled", {"why": "up to date"})
            return _job_now(store, cfg, job_id)
        if kind == "update":
            # one staged update per cub (live had three for the newsletter): the
            # same files staged already are that job; an older, different one is superseded
            cancel_stale(store, cfg, cid)
            for old_id in awaiting_updates(store, cfg, cid):
                prev = _record(cfg, old_id) or {}
                if prev.get("tree_hash") == th and prev.get("hash") == digest:
                    files.make_writable(staged)
                    shutil.rmtree(staged, ignore_errors=True)
                    _step(store, job_id, kind, m["id"], "cancelled",
                          {"why": f"the same update is staged already (job {old_id})",
                           "same_as": old_id})
                    return _job_now(store, cfg, old_id)
            for old_id in awaiting_updates(store, cfg, cid):
                cancel(store, cfg, old_id, why=f"superseded by job {job_id}")
        _step(store, job_id, kind, m["id"], "awaiting_confirm")
        return _job_now(store, cfg, job_id)
    except (InstallError, inspect.TreeError, ManifestError) as exc:
        return fail(str(exc))
    except OSError as exc:
        return fail(f"a file could not be read or moved ({exc.strerror or exc})")


def _cap(cfg: Any, m: dict[str, Any], trust: str) -> float | None:
    asked = (m.get("model") or {}).get("monthly_usd")
    if asked is not None:
        return float(asked)
    own = cub_settings.cub_value(cfg, m["id"], "monthly_usd", trust=trust)
    return float(own) if own is not None else None


def awaiting_ids(store: Any, cid: str | None = None) -> list[tuple[str, str]]:
    """``(job, cub)`` of every update job whose last step is ``awaiting_confirm``, newest
    first; of one cub when ``cid``."""
    rows = store.query(
        "SELECT c.job_id, c.cub FROM cub_installs c WHERE c.kind = 'update' "
        "AND c.step = 'awaiting_confirm' AND c.id = (SELECT MAX(x.id) FROM cub_installs x "
        "WHERE x.job_id = c.job_id)" + (" AND c.cub = ?" if cid is not None else "") +
        " ORDER BY c.id DESC", (cid,) if cid is not None else ())
    return [(r["job_id"], r["cub"]) for r in rows]


def stale_why(store: Any, cfg: Any, job_id: str, cid: str) -> str | None:
    """Why an update waiting for the confirm offers nothing any more, or None: its staged
    folder is gone, or what it staged is installed already. Live had three identical update
    jobs of the newsletter (staged before); each press applied one and the page
    offered the next, "Update to 1.2.0…" again, so the button looked dead."""
    rec = _record(cfg, job_id)
    if rec is None:
        return "its staged folder is gone: look for the update again"
    current = registry.latest(store, cid)
    if current is None or current["state"] == "removed":
        return f"{cid} is not installed"
    if rec.get("tree_hash") == current["tree_hash"] or \
            version_key(rec["version"]) <= version_key(current["version"]):
        return f"{current['version']} is installed"
    return None


def awaiting_updates(store: Any, cfg: Any, cid: str | None) -> list[str]:
    """The update jobs of ``cid`` waiting for the owner's confirm that still offer something,
    newest first."""
    return [j for j, _ in awaiting_ids(store, cid or "")
            if stale_why(store, cfg, j, cid or "") is None]


def cancel_stale(store: Any, cfg: Any, cid: str | None = None) -> list[str]:
    """Cancel every update job waiting for a confirm that offers nothing (``stale_why``), of
    one cub or all; the jobs cancelled."""
    out = []
    for job_id, c in awaiting_ids(store, cid):
        why = stale_why(store, cfg, job_id, c or "")
        if why is not None:
            cancel(store, cfg, job_id, why=why)
            out.append(job_id)
    return out


def cancel(store: Any, cfg: Any, job_id: str, why: str = "cancelled by the owner") -> dict[str,
           Any]:
    j = job(store, cfg, job_id)
    if j is None:
        raise InstallError("no such job", 404)
    if j["state"] in TERMINAL or j["state"] in ("placing", "placed", "pinned"):
        raise InstallError(f"the job is {j['state']}", 409)
    staged = _staged(cfg, job_id)
    if staged.exists():
        files.make_writable(staged)
        shutil.rmtree(staged, ignore_errors=True)
    _step(store, job_id, j["kind"], (j.get("cub") or {}).get("id"), "cancelled", {"why": why})
    return _job_now(store, cfg, job_id)


# -- steps 6 to 9: place and pin ------------------------------------------------------------------


def _awaiting(rt: Any, job_id: str, kind: str, cid: str | None) -> dict[str, Any]:
    j = job(rt.store, rt.cfg, job_id)
    if j is None:
        raise InstallError("no such job", 404)
    if j["kind"] != kind:
        raise InstallError(f"job {job_id} is an {j['kind']}, not an {kind}", 409)
    if j["state"] != "awaiting_confirm":
        raise InstallError(f"job {job_id} is {j['state']}, not waiting for your confirm", 409)
    rec = _record(rt.cfg, job_id)
    if rec is None:
        raise InstallError("the job's staged folder is gone: fetch it again", 409)
    if cid is not None and rec["id"] != cid:
        raise InstallError(f"job {job_id} is for {rec['id']}, not {cid}", 409)
    return rec


def build_venv(staged: Path, requirements: str) -> None:
    """The cub's packages, outside the sandbox and with the network: ``uv`` from PyPI, every
    package pinned by its hash, wheels only. ``venv/.ok`` holds the requirements' hash."""
    from . import sandbox
    uv = shutil.which("uv")
    if uv is None:
        raise InstallError("installing a cub's packages needs uv (https://docs.astral.sh/uv/)")
    venv = staged / "venv"
    env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TMPDIR")},
           "UV_LINK_MODE": "copy", "UV_NO_CONFIG": "1"}
    steps = ([uv, "venv", "-q", "--python", sandbox.base_python(), str(venv)],
             [uv, "pip", "install", "-q", "--python", str(venv / "bin" / "python"),
              "--require-hashes", "--only-binary", ":all:", "--index-url",
              "https://pypi.org/simple", "-r", str(staged / "src" / requirements)])
    for argv in steps:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=VENV_TIMEOUT_S,
                               env=env)
        except subprocess.TimeoutExpired:
            raise InstallError(f"its packages took longer than {VENV_TIMEOUT_S} s") from None
        if p.returncode != 0:
            last = ((p.stderr or p.stdout).strip().splitlines() or ["uv failed"])[-1]
            raise InstallError(f"its packages did not install: {last[:240]}")
    (venv / ".ok").write_text(files.file_hash(staged / "src" / requirements))


def install(rt: Any, job_id: str, *, door: str, topics: list[int] | None = None) -> dict[str, Any]:
    """The owner's confirm of an add: steps 6 to 9. Returns the cub's registry row."""
    cfg, store = rt.cfg, rt.store
    with _LOCK:
        rec = _awaiting(rt, job_id, "add", None)
        cid, m = rec["id"], rec["manifest"]
        _step(store, job_id, "add", cid, "placing", {"door": door})
    grants = dict(rec["grants"])
    grants["reads_topics"] = _topics(store, m, topics)
    staged, dest = _staged(cfg, job_id), files.cub_dir(cfg, cid)
    try:
        if dest.exists():
            raise InstallError(f"cubs/{cid} exists already: run kranto doctor")
        if m.get("requirements"):
            build_venv(staged, m["requirements"])
        (staged / "staged.json").unlink()
        staged.rename(dest)
    except (InstallError, OSError) as exc:
        # nothing placed; the staged folder stays until cubs.gc (a day) for a look
        _step(store, job_id, "add", cid, "failed", {"why": _why(exc)})
        raise InstallError(_why(exc), 409) from None
    return _pin(rt, job_id, "add", rec, grants, dest)


def _why(exc: Exception) -> str:
    return exc.words if isinstance(exc, InstallError) else \
        f"a file could not be moved ({getattr(exc, 'strerror', None) or exc})"


def _topics(store: Any, m: dict[str, Any], topics: list[int] | None) -> list[int] | None:
    """The topics a cub that reads the library is narrowed to (None: all of them)."""
    if not topics:
        return None
    if "library" not in (m.get("reads") or []) and "topics" not in (m.get("reads") or []):
        raise InstallError("only a cub that reads the library is narrowed to topics")
    if not all(isinstance(t, int) and not isinstance(t, bool) for t in topics):
        raise InstallError("topics are topic ids")
    known = {r["id"] for r in store.query("SELECT id FROM topics")}
    missing = [t for t in topics if t not in known]
    if missing:
        raise InstallError(f"no topic {', '.join(map(str, missing))}", 404)
    return sorted(set(topics))


def _quarantine(cfg: Any, path: Path, why: str) -> Path:
    to = files.root(cfg) / ".work" / f"{why}-{path.name}-{int(time.time())}-" \
        f"{uuid.uuid4().hex[:6]}"
    to.parent.mkdir(parents=True, exist_ok=True)
    files.make_writable(path)
    path.rename(to)
    return to


def _pin(rt: Any, job_id: str, kind: str, rec: dict[str, Any], grants: dict[str, Any], dest: Path,
         *,
         restore: Path | None = None) -> dict[str, Any]:
    """Steps 7 to 9: the placed tree's hash against step 4's, then the pin and the row in one
    transaction, then the event and the runtime's reload. ``restore``: the folder an update
    replaced, put back if this fails."""
    cfg, store, cid = rt.cfg, rt.store, rec["id"]
    m = rec["manifest"]

    def undo(why: str) -> None:
        bad = _quarantine(cfg, dest, "bad")
        if restore is not None:
            restore.rename(dest)
            files.make_read_only(dest / "src")
        _step(store, job_id, kind, cid, "failed", {"why": why, "kept": str(bad)})

    if files.tree_hash(dest / "src") != rec["tree_hash"]:
        undo("the tree changed while staging")
        raise InstallError("the tree changed while staging", 409)
    files.make_read_only(dest / "src")
    if (dest / "venv").exists():
        files.make_read_only(dest / "venv")
    _step(store, job_id, kind, cid, "placed")
    now = iso(utcnow())
    row = {"cub": cid, "state": "installed", "version": m["version"], "trust": rec["trust"],
           "source_kind": rec["source"]["kind"], "source": CubSource.write(rec["source"]),
           "sha": rec.get("sha"), "tree_hash": rec["tree_hash"], "manifest_hash": rec["hash"],
           "grants": Grants.write(grants), "bears_range": m.get(HOST_RANGE),
           "note": None, "created_at": now}
    try:
        with store.tx():
            store.insert("cub_pins", {"cub": cid, "version": m["version"], "trust": rec["trust"],
                                      "manifest_hash": rec["hash"],
                                      "tree_hash": rec["tree_hash"], "created_at": now})
            row["id"] = store.insert("cubs", row)
            _step(store, job_id, kind, cid, "pinned")
    except Exception as exc:  # noqa: BLE001 - nothing unpinned may stay in place
        undo(f"the pin was not written ({type(exc).__name__})")
        raise InstallError("the pin was not written", 409) from None
    (dest / "cub.json").write_text(json.dumps({"row": dict(row), "manifest": m,
                                               "inventory": rec["inventory"]}, default=str))
    os.chmod(dest / "cub.json", 0o600)
    _step(store, job_id, kind, cid, "installed", {"version": m["version"]})
    verb = "installed" if kind == "add" else "updated"
    events.core_publish(store, f"cub.{verb}", {"cub": cid, "version": m["version"]})
    _reload(rt)
    return row


def _reload(rt: Any) -> None:
    if getattr(rt, "cubs", None) is not None:
        rt.cubs.load()


# -- updates --------------------------------------------------------------------------------------


def apply_update(rt: Any, job_id: str, cid: str, *, door: str) -> dict[str, Any]:
    """The owner's confirm of an update (step 4)."""
    cfg, store = rt.cfg, rt.store
    from ... import preview
    if preview.enabled(getattr(cfg, "root", None)):
        raise InstallError("This is the preview: cubs are not updated here", 409)
    with _LOCK:
        rec = _awaiting(rt, job_id, "update", cid)
        _step(store, job_id, "update", cid, "placing", {"door": door})
    current = registry.latest(store, cid)
    if current is None:
        raise InstallError(f"no cub {cid} is installed", 404)
    old = Grants.load(current["grants"])
    grants = dict(rec["grants"])
    reads = set(grants.get("reads") or [])
    if old.reads_topics and reads & {"library", "topics"}:
        grants["reads_topics"] = old.reads_topics              # the narrowing is kept
    if rec["delta"]["grown"] and cub_settings.live_kinds(cfg, cid):
        try:
            cub_settings.write(cfg, f"cubs.{cid}.live", [])      # dry first, again
        except ValueError as exc:
            _step(store, job_id, "update", cid, "failed", {"why": str(exc)})
            raise InstallError(f"its kinds could not be put back to practice ({exc})",
                               409) from None
    staged, dest = _staged(cfg, job_id), files.cub_dir(cfg, cid)
    old_dir = files.root(cfg) / ".work" / f"old-{cid}-{int(time.time())}-{job_id[:6]}"
    with updating(cfg, cid):
        if getattr(rt, "cubs", None) is not None:
            rt.cubs._end(cid, "update")
        try:
            if rec["manifest"].get("requirements"):
                build_venv(staged, rec["manifest"]["requirements"])
            (staged / "staged.json").unlink()
            if dest.exists():                     # a folder a crash lost is simply replaced
                files.make_writable(dest)
                dest.rename(old_dir)
            staged.rename(dest)
        except (InstallError, OSError) as exc:
            if old_dir.exists() and not dest.exists():
                old_dir.rename(dest)
            if dest.exists():
                files.make_read_only(dest / "src")
            _step(store, job_id, "update", cid, "failed", {"why": _why(exc)})
            raise InstallError(_why(exc), 409) from None
        if (old_dir / "log").exists() and not (dest / "log").exists():
            (old_dir / "log").rename(dest / "log")
        row = _pin(rt, job_id, "update", rec, grants, dest,
                   restore=old_dir if old_dir.exists() else None)
    # any other job staged for this cub at this version or older offers nothing now
    cancel_stale(store, cfg, cid)
    return row


def waits_why(rec: dict[str, Any]) -> str | None:
    """Why a staged update waits for the owner's press, or None when it may apply by itself
    (the owner's rule of 2026-10-23, under ``cubs.auto_update``): it adds no permission and no
    send (the delta did not grow) and this Kranto is inside its ``kranto`` range. Trust, the
    sandbox and every ticket's own confirm are the same either way."""
    from ... import __version__
    from ..manifest import in_range
    added = (rec.get("delta") or {}).get("added") or {}
    n = sum(len(items) for items in added.values())
    if "requests" in added:
        return "asks to send something new" if n == 1 else \
            f"asks to send something new and for {n - 1} more permission" \
            f"{'' if n == 2 else 's'}"
    if n:
        return "asks for one more permission" if n == 1 else f"asks for {n} more permissions"
    rng = (rec.get("manifest") or {}).get(HOST_RANGE)
    if rng and not in_range(__version__, rng):
        return f"needs a newer Kranto ({rng})"
    return None


class updating:
    """``cubs/.jobs/<id>.updating`` while a cub's folder is swapped: the runtime starts no
    process of it meanwhile (in this process or the server's), so a half-swapped tree is never
    taken for a changed one. A marker a crash left is removed by ``recover``."""

    def __init__(self, cfg: Any, cid: str) -> None:
        self.path = files.updating_marker(cfg, cid)

    def __enter__(self) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()))
        return self

    def __exit__(self, *exc: Any) -> None:
        self.path.unlink(missing_ok=True)


# -- the owner's switches -------------------------------------------------------------------------


def _live_row(store: Any, cid: str) -> dict[str, Any]:
    row = registry.latest(store, cid)
    if row is None or row["state"] == "removed":
        raise InstallError(f"no cub {cid} is installed", 404)
    return row


def stop(rt: Any, cid: str, note: str | None = None) -> dict[str, Any]:
    """Stop: the process killed at once, the cub paused, its open tickets expired."""
    from .runtime import STOPPED
    row = _live_row(rt.store, cid)
    words = STOPPED + (f": {note[:200]}" if note else "")
    if getattr(rt, "cubs", None) is not None:
        rt.cubs._end(cid, "stop", kill=True)
    new = registry.append(rt.store, row, state="paused", note=words) \
        if row["state"] != "paused" or row["note"] != words else row
    tickets.expire_all(rt.store, cub=cid, note="it was stopped")
    events.core_publish(rt.store, "cub.stopped", {"cub": cid})
    _reload(rt)
    return new


def resume(rt: Any, cid: str) -> dict[str, Any]:
    row = _live_row(rt.store, cid)
    if tickets.stop_file().exists():
        raise InstallError(f"remove {tickets.stop_file()} first: the file stops every cub "
                           "whatever the page says", 409)
    new = registry.append(rt.store, row, state="installed", note=None) \
        if row["state"] == "paused" else row
    events.core_publish(rt.store, "cub.resumed", {"cub": cid})
    if getattr(rt, "cubs", None) is not None:
        rt.cubs._failures.pop(cid, None)
    _reload(rt)
    return new


def set_enabled(rt: Any, cid: str, on: bool) -> dict[str, Any]:
    _live_row(rt.store, cid)
    cub_settings.write(rt.cfg, f"cubs.{cid}.enabled", bool(on))
    events.core_publish(rt.store, "cub.enabled" if on else "cub.disabled", {"cub": cid})
    events.core_publish(rt.store, "settings.changed", {"feature": "cubs",
                                                       "key": f"cubs.{cid}.enabled"})
    return cub_settings.values(rt.cfg)


def set_mode(rt: Any, cid: str, kind: str, live: bool) -> dict[str, Any]:
    """A kind live or dry for a cub. Live is the page's house confirm (the web layer
    checks the door); dry is any door's. On the preview nothing goes live."""
    from ... import preview
    if live and preview.enabled(getattr(rt.cfg, "root", None)):
        raise InstallError(preview.NOTHING_SENT + ": a kind cannot go live here", 409)
    row = _live_row(rt.store, cid)
    asks = Grants.load(row["grants"]).requests
    if kind not in asks:
        raise InstallError(f"{cid} does not ask for {kind}", 404)
    if live:
        outside = cub_settings.outside_range(rt.store, cid)
        if outside:
            raise InstallError(f"{cid} runs in practice only: {outside}", 409)
    now = [k for k in cub_settings.raw_live(rt.cfg, cid) if not tickets.same_kind(k, kind)]
    if live:
        now.append(kind)
    cub_settings.write(rt.cfg, f"cubs.{cid}.live", now)
    events.core_publish(rt.store, "cub.mode_changed",
                        {"cub": cid, "kind": kind, "mode": "live" if live else "dry"})
    events.core_publish(rt.store, "settings.changed", {"feature": "cubs",
                                                       "key": f"cubs.{cid}.live"})
    return cub_settings.values(rt.cfg)


def remove(rt: Any, cid: str, *, purge: bool = False) -> dict[str, Any]:
    """the process killed, open tickets expired, the row ``removed``, the folder moved to
    ``cubs/.removed`` for 30 days; with ``purge`` its key-value rows and the folder go now.
    Its tickets, calls, runs, events, pins and rows stay; so do its settings in kranto.yaml."""
    cfg, store = rt.cfg, rt.store
    row = _live_row(store, cid)
    job_id = uuid.uuid4().hex[:12]
    _step(store, job_id, "remove", cid, "queued")
    if getattr(rt, "cubs", None) is not None:
        rt.cubs._end(cid, "remove", kill=True)
    tickets.expire_all(store, cub=cid, note="it was removed")
    registry.append(store, row, state="removed", note=None)
    src = files.cub_dir(cfg, cid)
    gone = None
    if src.exists():
        files.ensure_root(cfg)
        gone = files.root(cfg) / ".removed" / f"{cid}-{int(time.time())}-{job_id[:6]}"
        files.make_writable(src)
        src.rename(gone)
    if purge:
        store.query("DELETE FROM cub_kv WHERE cub = ?", (cid,))
        if gone is not None:
            shutil.rmtree(gone, ignore_errors=True)
    _step(store, job_id, "remove", cid, "removed", {"purged": purge})
    events.core_publish(store, "cub.removed", {"cub": cid})
    _reload(rt)
    return {"removed": True, "purged": purge, "kept": None if purge or gone is None
            else str(gone)}


# -- recovery after a crash ----------------------------------------------------------------


def recover(rt: Any, *, idle_s: float = 0) -> list[str]:
    """Every job a crash left mid-way: before the confirm, failed and its staged folder
    removed; while placing, a folder in place without its row is quarantined (never run
    unpinned code). The runtime's own ``recover`` handles folders and rows. ``idle_s``: only
    jobs whose last step is older (the daily sweep must not cut a fetch that is running)."""
    cfg, store = rt.cfg, rt.store
    said = [f"{j}: offers nothing now" for j in cancel_stale(store, cfg)]
    jobs_dir = files.root(cfg) / ".jobs"
    for left in jobs_dir.glob("*.updating") if jobs_dir.is_dir() and not idle_s else []:
        left.unlink(missing_ok=True)
    for j in jobs(store, cfg, limit=200):
        if j["state"] in TERMINAL or j["state"] == "awaiting_confirm" \
                or _age_s(j["updated_at"]) < idle_s:
            continue
        rows = store.query("SELECT cub FROM cub_installs WHERE job_id = ? AND cub IS NOT NULL "
                           "LIMIT 1", (j["id"],))
        cid = rows[0]["cub"] if rows else None
        staged = _staged(cfg, j["id"])
        if j["state"] in ("placing", "placed", "pinned") and cid:
            row = registry.latest(store, cid)
            dest = files.cub_dir(cfg, cid)
            pinned = row is not None and row["state"] != "removed" and dest.exists() and \
                files.tree_hash(dest / "src") == row["tree_hash"]
            if dest.exists() and not pinned:
                _quarantine(cfg, dest, "bad")
            if not pinned:
                _step(store, j["id"], j["kind"], cid, "failed",
                      {"why": "interrupted before the pin"})
                said.append(f"{j['id']}: interrupted before the pin")
                continue
            _step(store, j["id"], j["kind"], cid, "installed")
            continue
        if staged.exists():
            files.make_writable(staged)
            shutil.rmtree(staged, ignore_errors=True)
        _step(store, j["id"], j["kind"], cid, "failed", {"why": "interrupted"})
        said.append(f"{j['id']}: interrupted")
    return said
