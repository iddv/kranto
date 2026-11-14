#!/usr/bin/env python3
"""The promotion gate (with the owner's decisions of 2026-10-24): stable is
always a choice the owner makes, never a matter of time.

Nothing here counts days or hours, and nothing is promoted, offered or flagged as ready because
time passed. What it does:

- ``tick`` (hourly, the maintainer's ``kranto-release-gate.timer``; and at once when the owner
  presses Promote, which starts the unit): writes the **candidate** to the owner's install
  (``<home>/update/candidate.json``), the facts the Needs you row shows whenever nightly is
  ahead of stable: the nightly build (the one the owner's install runs, else the newest), the
  pull requests since the last stable with the ``big`` ones named, each setting whose stable
  default keeps the old behaviour, and the **health checks**, which block the press:

  1. a rollback of this build (the owner's ``update/history.jsonl``; other installs'
     ``kranto.updates_by_day``);
  2. an error first seen on a build after the last stable, up to this one, that still occurs
     (seen in the last 24 hours): the owner's ``<home>/data/errors.jsonl``, and the telemetry
     store's ``kranto.errors_by_signature`` when it exists (else the daily reports'
     ``kranto.errors_by_version``). A signature marked ``known`` (with a reason) does not block;
  3. ``kranto doctor --routes`` on the owner's install, when it runs this build;
  4. every page on the odd installs (``scripts/dev/odd_walk.sh`` with the installed Kranto).

  A check that cannot read its source is said as blind, never assumed clean; a blind check does
  not block (the owner's Q4). Until the relay is redeployed the telemetry store has no error
  reports, and the candidate says so.

  Then, when ``<home>/update/promote.json`` (``{tag, by, at}``, written by the press) names the
  current candidate and nothing blocks: a clone of the server's main cuts the promotion
  (``cut_local.sh --from-tag vX.Y.0-devN``: ``vX.Y.0`` held, ``release/X.Y`` made),
  ``rc_check.sh`` checks it against the latest stable, and ``promote --now`` releases it.
  Each step is written to the candidate (``promoting``, ``promoted``, ``failed`` with the log);
  a failure leaves the held release held and nothing half-promoted. Kranto never cuts from
  inside the server: it writes the file and starts this unit.
- ``promote --now --tag T --reason WHY``: release a held stable at once (``hotfix.sh --stable``
  after rc_check, and the operator, as at the switch). Said in the notes and logged.
- ``known SIGNATURE --reason WHY``: an error the operator has looked at; it no longer blocks.
- ``offer TAG``: a nightly cut_local published unoffered for its rc_check ("being checked"
  opens its notes) is offered, only when rc_check.sh passed on it here.
- ``withdraw TAG --reason WHY``: a nightly that must not be installed (its rc_check failed):
  "**Do not install:**" opens its notes, and the updater never offers it.
- ``status``: the candidate and each check's reading, and what could not be read.
- ``hours``: prints 0 (the hours are retired; a stale caller holds nothing).

Every promotion and every ``known``/``withdraw`` is logged, one JSON line each, in
``$XDG_STATE_HOME/kranto-release/gate.jsonl``.

Settings: ``REPO`` (public.toml's repo: the one repository), ``KRANTO_GATE_HOME`` (the
owner's kranto home, ~/kranto-kb), ``KRANTO_BIN`` (Kranto), ``GATE_CLICKHOUSE``
(the telemetry store's ClickHouse HTTP address, set by the gate's unit; unset or ``off``: not
read),
``GATE_PORT`` (8942: rc_check's and the odd walk's scratch ports, this and the next),
``GATE_WORK`` (~/.cache/kranto-release/gate). Standard library plus gh and git.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

# the held line's start, in the notes of every release waiting for stable: notes.py's HELD_LINE
# and, for the releases held before the two lines, the staged rollout's
HELD_PREFIXES = ("**Held for stable:**", "**Staged rollout:**")
WITHDRAWN = "**Do not install:**"
STABLE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
NIGHTLY = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-dev(\d+)$")
STILL_OCCURS = timedelta(hours=24)
SCHEMA = 1


class GateError(Exception):
    pass


def _repo() -> str:
    """public.toml's repo (scripts/release/names.py)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import names
    return names.repo()


def vkey(tag_or_version: str | None) -> tuple:
    """dev < rc < final within a base (the updater's order), for tags and wheel versions;
    anything else sorts lowest."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-?rc(\d+))?(?:[.-]dev(\d+))?(?:\+.*)?$",
                 str(tag_or_version or "").strip())
    if not m:
        return (-1,)
    base = (int(m[1]), int(m[2]), int(m[3]))
    if m[5] is not None:
        return (*base, 0, int(m[4] or 0), int(m[5]))
    if m[4] is not None:
        return (*base, 1, int(m[4]), 0)
    return (*base, 2, 0, 0)


def base_of(v: str | None) -> tuple:
    return vkey(v)[:3]


def version_of(tag: str) -> str:
    """``v0.7.0-dev12`` -> ``0.7.0.dev12``; ``v0.7.0`` -> ``0.7.0`` (the wheel's version)."""
    return tag.removeprefix("v").replace("-dev", ".dev").replace("-rc", "rc")


def _now() -> datetime:
    return datetime.now(UTC)


def _when(ts: str) -> datetime:
    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(cmd: list[str], timeout: float = 120, env: dict | None = None,
        cwd: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              check=False, env=env, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", f"{type(exc).__name__}: {exc}")


class GitHub:
    def __init__(self, repo: str, run=run):
        self.repo, self.run = repo, run

    def _gh(self, *args: str) -> str:
        r = self.run(["gh", *args])
        if r.returncode != 0:
            raise GateError(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:300]}")
        return r.stdout

    def releases(self) -> list[dict]:
        return json.loads(self._gh("api", f"repos/{self.repo}/releases?per_page=100") or "[]")

    def body(self, tag: str) -> str:
        return self._gh("release", "view", tag, "-R", self.repo, "--json", "body",
                        "-q", ".body")

    def edit_notes(self, tag: str, body: str, *extra: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(body)
        try:
            self._gh("release", "edit", tag, "-R", self.repo, *extra, "--notes-file", f.name)
        finally:
            os.unlink(f.name)

    def promote(self, tag: str, body: str) -> None:
        self.edit_notes(tag, body, "--prerelease=false", "--latest")

    def merged(self, repo: str, since: str) -> list[dict]:
        """The pull requests into main merged after ``since``, with their labels."""
        return json.loads(self._gh("pr", "list", "-R", repo, "--state", "merged", "--base",
                                   "main", "--limit", "300", "--search", f"merged:>{since}",
                                   "--json", "number,title,mergedAt,labels") or "[]")


# -- the releases -----------------------------------------------------------------------------

def held(releases: list[dict]) -> tuple[list[dict], str | None]:
    """(the held stable releases newer than the latest released one, newest first; the latest
    released stable tag)."""
    out = [r for r in releases if not r.get("draft") and STABLE.match(r.get("tag_name") or "")]
    promoted = [r["tag_name"] for r in out if not r.get("prerelease")]
    latest = max(promoted, key=vkey, default=None)
    waiting = [r for r in out if r.get("prerelease")
               and (latest is None or vkey(r["tag_name"]) > vkey(latest))]
    return sorted(waiting, key=lambda r: vkey(r["tag_name"]), reverse=True), latest


def nightlies(releases: list[dict], after: str | None) -> list[dict]:
    """The published nightly builds newer than the stable ``after``, newest first; withdrawn
    ones left out."""
    out = [r for r in releases if not r.get("draft") and NIGHTLY.match(r.get("tag_name") or "")
           and WITHDRAWN not in (r.get("body") or "")
           and (after is None or vkey(r["tag_name"]) > vkey(after))]
    return sorted(out, key=lambda r: vkey(r["tag_name"]), reverse=True)


def installed_version(kranto: str, run=run) -> str | None:
    r = run([kranto, "--version"], timeout=60)
    m = re.match(r"^Kranto (\S+)", r.stdout or "")
    return m[1] if r.returncode == 0 and m else None


def history(home: Path) -> list[dict]:
    try:
        lines = (Path(home) / "update" / "history.jsonl").read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            h = json.loads(line)
        except ValueError:
            continue
        if isinstance(h, dict):
            out.append(h)
    return out


def nightly_since(hist: list[dict]) -> str | None:
    """When the owner's install last moved onto the nightly line (information only, never a
    gate): the finish of the first update to a nightly build after its last stable one."""
    since = None
    for h in hist:
        if h.get("state") != "done" or not isinstance(h.get("to"), str):
            continue
        since = (since or h.get("finished")) if ".dev" in h["to"] else None
    return since


# -- the checks -------------------------------------------------------------------------------

class Check:
    """One health check's reading: ``ok`` True, False (blocks the press) or None (could not
    read: blind, said, not blocking)."""

    def __init__(self, name: str, ok: bool | None, said: str, found: list | None = None):
        self.name, self.ok, self.said, self.found = name, ok, said, list(found or [])

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "said": self.said, "found": self.found}


def clickhouse(url: str) -> Callable[[str], list[dict]] | None:
    """A query function on the telemetry store's ClickHouse (HTTP, loopback, no credential), or None
    when it is off. Raises GateError when it does not answer."""
    if not url or url == "off":
        return None

    def query(sql: str) -> list[dict]:
        q = urllib.parse.urlencode({"query": sql + " FORMAT JSONEachRow"})
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/?{q}", timeout=20) as r:
                text = r.read().decode()
        except OSError as exc:
            raise GateError(f"ClickHouse at {url}: {exc}") from exc
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return query


def check_rollback(build: str, hist: list[dict], query) -> Check:
    version = version_of(build)
    mine = [h for h in hist if h.get("state") == "rolled_back" and h.get("to") == version]
    if mine:
        return Check("rollback", False, f"{version} was rolled back on your install "
                     f"({mine[-1].get('finished') or mine[-1].get('started') or 'when unknown'}: "
                     f"{mine[-1].get('reason') or 'see its log'})",
                     [{"where": "your install", "at": mine[-1].get("finished")}])
    if query is None:
        return Check("rollback", True, "no rollback of it on your install (other installs: "
                     "not read)")
    try:
        rows = query("SELECT day, sum(rolled_back) AS n FROM kranto.updates_by_day WHERE "
                     f"version = '{build.removeprefix('v')}' GROUP BY day HAVING n > 0")
    except GateError as exc:
        return Check("rollback", True, f"no rollback of it on your install; other installs: "
                     f"blind ({exc})")
    if rows:
        return Check("rollback", False, f"{version} was rolled back on another install "
                     f"({rows[0].get('day')})", rows)
    return Check("rollback", True, "no rollback of it on your install or another")


def _errors_log(home: Path) -> list[dict]:
    try:
        lines = (Path(home) / "data" / "errors.jsonl").read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("signature"), str) \
                and isinstance(e.get("version"), str) and isinstance(e.get("at"), str):
            out.append(e)
    return out


def new_errors_here(home: Path, stable: str | None, build: str, now: datetime,
                    known: dict) -> list[dict]:
    """The owner's install's errors first seen on a version after ``stable`` and up to
    ``build``, still occurring (seen in the last 24 hours), not marked known."""
    by: dict[str, dict] = {}
    for e in _errors_log(home):
        s = by.setdefault(e["signature"], {"signature": e["signature"], "first": e["version"],
                                           "last": e["at"], "what": e.get("where") or
                                           e.get("exception") or "",
                                           "message": e.get("message") or ""})
        if vkey(e["version"]) < vkey(s["first"]):
            s["first"] = e["version"]
        if e["at"] > s["last"]:
            s["last"] = e["at"]
    out = []
    for s in by.values():
        if s["signature"] in known:
            continue
        if not (stable is None or vkey(s["first"]) > vkey(stable)) \
                or vkey(s["first"]) > vkey(build):
            continue
        try:
            recent = now - _when(s["last"]) <= STILL_OCCURS
        except ValueError:
            continue
        if recent:
            out.append({**s, "where": "your install"})
    return out


# an error that is the install's setup, not the release: a model key refused. Read
# from its words as recorded: the activity's incident (``activity:auth:<provider>``, the server
# ``activity/incidents.py``), a 401/402/403 or the key's own words, and the scrubbed template
# the error reports keep ("HTTP <n> from <x> <x> key <x>.")
AUTH = re.compile(r"\bauth:|HTTP (?:<n>|40[123]) from .*\bkey\b|api[ _-]?key|\bkey\b.*"
                  r"(?:expired|invalid|refused)|unauthori[sz]ed|insufficient credit|"
                  r"\bno credits?\b", re.I)
PROVIDER_NAMES = {"openrouter": "OpenRouter", "anthropic": "Claude API", "xai": "xAI",
                  "claude_code": "Claude Code"}


def is_setup(e: dict) -> bool:
    """Whether an error found is the install's setup (a model key refused), not a regression."""
    return bool(AUTH.search(" ".join(str(e.get(k) or "") for k in ("what", "message", "where"))))


def setup_words(setup: list[dict]) -> str:
    """"your install's OpenRouter key is refused (not this release): renew it in Settings ›
    Watching, then the gate checks again"."""
    text = " ".join(f"{e.get('what') or ''} {e.get('message') or ''}" for e in setup).lower()
    name = next((n for k, n in PROVIDER_NAMES.items() if k in text), None)
    key = f"your install's {name} key" if name else "your install's model key"
    return (f"{key} is refused (not this release): renew it in Settings › Watching, then the "
            "gate checks again")


def check_errors(home: Path, stable: str | None, build: str, now: datetime, query,
                 known: dict) -> tuple[Check, list[str]]:
    """(the check, what was blind). An error that is the install's setup (``is_setup``) does
    not block; the check says it in its own words."""
    blind: list[str] = []
    found = new_errors_here(home, stable, build, now, known)
    remote = "not read"
    if query is not None:
        lo, hi = base_of(stable) if stable else (-1,), base_of(build)
        try:
            tables = {r.get("name") for r in query("SHOW TABLES FROM Kranto")}
            if "errors_by_signature" in tables:
                # an alias named like a column replaces it in WHERE: "AS last_seen" compared
                # a String with a DateTime (ClickHouse NO_COMMON_TYPE, HTTP 500), so its own name
                rows = query("SELECT signature, type, route_or_job, message, first_version, "
                             "toString(last_seen) AS seen FROM kranto.errors_by_signature "
                             "WHERE last_seen >= now() - INTERVAL 24 HOUR")
                remote = "error reports"
                # nightly builds report X.Y.Z until the relay knows their tags: compared by base
                for r in rows:
                    if r.get("signature") in known:
                        continue
                    if lo < base_of(r.get("first_version")) <= hi:
                        found.append({"signature": r.get("signature"),
                                      "first": r.get("first_version"),
                                      "last": r.get("seen"),
                                      "what": f"{r.get('type')} in {r.get('route_or_job')}",
                                      "message": r.get("message") or "",
                                      "where": "error reports"})
            else:
                blind.append("error reports: not in the telemetry store yet (#336's tables, and "
                             "the relay is not redeployed), so this check reads your install's "
                             "own log and the daily reports only")
                rows = query("SELECT fingerprint, min(version) AS first, max(day) AS last "
                             "FROM kranto.errors_by_version GROUP BY fingerprint "
                             "HAVING last >= today() - 1")
                remote = "daily reports"
                for r in rows:
                    if r.get("fingerprint") in known:
                        continue
                    if lo < base_of(r.get("first")) <= hi:
                        found.append({"signature": r.get("fingerprint"), "first": r.get("first"),
                                      "last": r.get("last"), "what": r.get("fingerprint"),
                                      "where": "daily reports"})
        except GateError as exc:
            blind.append(f"the telemetry store's reports: blind ({exc})")
            remote = "blind"
    else:
        blind.append("the telemetry store's reports: not read (GATE_CLICKHOUSE unset or off)")
    setup = [e for e in found if is_setup(e)]
    found = [e for e in found if not is_setup(e)]
    note = f"; {setup_words(setup)}" if setup else ""
    if found:
        first = found[0]
        more = f" and {len(found) - 1} more" if len(found) > 1 else ""
        return Check("errors", False, f"{len(found)} new error{'s' if len(found) > 1 else ''} "
                     f"still occurring: {first['what']} (first seen on {first['first']}, "
                     f"{first['where']}){more}{note}", found), blind
    return Check("errors", True, f"no new error of this release still occurring (your "
                 f"install's log; {remote}){note}", [{**e, "setup": True} for e in setup]), blind


def check_routes(kranto: str, installed: str | None, build: str, run=run) -> Check:
    if installed != version_of(build):
        return Check("pages", None, f"your install runs {installed or 'nothing readable'}, not "
                     f"{version_of(build)}: its pages are read at the press (rc_check)")
    helptext = run([kranto, "doctor", "--help"], timeout=60).stdout or ""
    if "--routes" not in helptext:
        return Check("pages", None, "this Kranto has no doctor --routes")
    r = run([kranto, "doctor", "--routes"], timeout=900)
    tail = " ".join((r.stdout or r.stderr or "").strip().splitlines()[-1:])[:200]
    if r.returncode == 0:
        return Check("pages", True, f"kranto doctor --routes passed{': ' + tail if tail else ''}")
    return Check("pages", False, f"kranto doctor --routes failed (exit {r.returncode}): {tail}")


def check_odd(kranto: str, installed: str | None, build: str, work: Path, port: int,
              repo: str, run=run) -> Check:
    """Every page on the odd installs, served by the installed build (its own odd_walk.sh, from
    a shallow clone of its tag), under a 3 GB cap."""
    if installed != version_of(build):
        return Check("odd installs", None, f"your install runs {installed or 'nothing'}, not "
                     f"{version_of(build)}: the odd installs are read at the press (rc_check)")
    src = work / f"src-{build}"
    if not (src / "scripts" / "dev" / "odd_walk.sh").is_file():
        r = run(["git", "clone", "--quiet", "--depth", "1", "--branch", build,
                 f"https://github.com/{repo}", str(src)], timeout=300)
        if r.returncode != 0:
            return Check("odd installs", None, f"could not fetch {build}'s odd walk: "
                         f"{(r.stderr or '').strip()[:160]}")
    from shutil import which
    exe = which(kranto) or kranto
    r = run(["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=3G", "--", "bash",
             str(src / "scripts" / "dev" / "odd_walk.sh"), str(port), exe],
            timeout=1800, env={**os.environ, "ODD_DIR": str(work / f"odd-{build}")})
    tail = " ".join((r.stdout or r.stderr or "").strip().splitlines()[-1:])[:200]
    if r.returncode == 0:
        return Check("odd installs", True, f"every page on the odd installs answered: {tail}")
    return Check("odd installs", False, f"the odd installs failed (exit {r.returncode}): {tail}")


# -- the candidate ----------------------------------------------------------------------------

def state_dir() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "kranto-release"


def log_path() -> Path:
    return state_dir() / "gate.jsonl"


def log(entry: dict, path: Path | None = None) -> None:
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _read(path: Path, default):
    try:
        v = json.loads(path.read_text())
    except (OSError, ValueError):
        return default
    return v if isinstance(v, type(default)) else default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=1) + "\n")
    tmp.replace(path)


def stable_defaults(kranto: str, run=run) -> list[dict]:
    """The settings whose stable default keeps the old behaviour, from the installed Kranto
    (``kranto settings stable-defaults --json``); none when it has no such command."""
    r = run([kranto, "settings", "stable-defaults", "--json"], timeout=60)
    if r.returncode != 0:
        return []
    try:
        rows = json.loads(r.stdout or "[]")
    except ValueError:
        return []
    return [s for s in rows if isinstance(s, dict) and "key" in s] if isinstance(rows, list) \
        else []


class Gate:
    """The gate on the owner's machine. ``odd`` and ``routes``: (build, installed) -> Check, for
    the slow checks (default check_odd and check_routes)."""

    def __init__(self, gh: GitHub, home: Path, *, kranto: str = "kranto", run: Callable = run,
                 query: Callable | None = None, now: Callable[[], datetime] = _now,
                 state: Path | None = None, port: int = 8942, odd: Callable | None = None,
                 routes: Callable | None = None) -> None:
        self.gh, self.home, self.kranto, self.run, self.query, self.now = \
            gh, Path(home), kranto, run, query, now
        self.state = state or state_dir()
        self.port, self.odd, self.routes = port, odd, routes

    @property
    def candidate_path(self) -> Path:
        return Path(self.home) / "update" / "candidate.json"

    @property
    def promote_path(self) -> Path:
        return Path(self.home) / "update" / "promote.json"

    def known(self) -> dict:
        return _read(self.state / "known.json", {})

    def _cached(self, name: str, build: str, fn: Callable[[], Check]) -> Check:
        """A slow check (pages, odd installs) runs once per build; its answer is kept."""
        cache = _read(self.state / "checks.json", {})
        hit = (cache.get(build) or {}).get(name)
        if isinstance(hit, dict) and hit.get("ok") is not None:
            return Check(name, hit["ok"], hit.get("said") or "", hit.get("found") or [])
        c = fn()
        if c.ok is not None:
            cache = {build: {**(cache.get(build) or {}), name: c.as_dict()}}   # this build only
            _write(self.state / "checks.json", cache)
        return c

    def candidate(self, *, slow: bool = True) -> dict:
        """The candidate's facts and checks (the shape of ``candidate.json``)."""
        now = self.now()
        rels = self.gh.releases()
        _, stable = held(rels)
        ahead = nightlies(rels, stable)
        out: dict = {"schema": SCHEMA, "at": _iso(now), "stable": stable}
        if not ahead:
            return {**out, "state": "none",
                    "said": f"nightly is not ahead of stable {stable or '(none yet)'}: "
                            "nothing to promote"}
        installed = installed_version(self.kranto, self.run)
        mine = next((r for r in ahead if version_of(r["tag_name"]) == installed), None)
        rel = mine or ahead[0]
        build = rel["tag_name"]
        m = NIGHTLY.match(build)
        to = f"v{m[1]}.{m[2]}.0"
        hist = history(self.home)
        stable_rel = next((r for r in rels if r.get("tag_name") == stable), None)
        since = (stable_rel or {}).get("published_at") or "1970-01-01T00:00:00Z"
        until = rel.get("published_at")
        prs, big = {}, []
        for repo, name in [(self.gh.repo, "kranto")]:          # the one repository
            try:
                rows = self.gh.merged(repo, since)
            except GateError:
                rows = []
            rows = [p for p in rows if not until or (p.get("mergedAt") or "") <= until]
            rows.sort(key=lambda p: p.get("mergedAt") or "")
            prs[name] = [{"number": p["number"], "title": p.get("title") or ""} for p in rows]
            big += [{"repo": name, "number": p["number"], "title": p.get("title") or ""}
                    for p in rows if any((lb or {}).get("name") == "big"
                                         for lb in p.get("labels") or [])]
        known = self.known()
        checks = [check_rollback(build, hist, self.query)]
        err, blind = check_errors(self.home, stable, build, now, self.query, known)
        checks.append(err)
        routes = self.routes or (lambda b, i: check_routes(self.kranto, i, b, self.run))
        odd = self.odd or (lambda b, i: check_odd(self.kranto, i, b, self.state / "work",
                                                  self.port + 1, self.gh.repo, self.run))
        if slow:
            checks.append(self._cached("pages", build, lambda: routes(build, installed)))
            checks.append(self._cached("odd installs", build, lambda: odd(build, installed)))
        blocking = [c.said for c in checks if c.ok is False]
        blind += [f"{c.name}: {c.said}" for c in checks if c.ok is None]
        setup = [e for e in err.found if e.get("setup")]
        if setup:              # the install's own trouble, said apart from the release's
            out["setup"] = setup_words(setup)
        return {**out, "state": "blocked" if blocking else "candidate", "tag": build,
                "version": version_of(build), "to": to, "installed": installed,
                "published_at": until, "nightly_since": nightly_since(hist),
                "prs": prs, "count": sum(len(v) for v in prs.values()), "big": big,
                "off_on_stable": stable_defaults(self.kranto, self.run),
                "checks": [c.as_dict() for c in checks], "blocking": blocking, "blind": blind}

    # -- the press ------------------------------------------------------------------------

    def tick(self, say=print) -> int:
        """Write the candidate; carry out a pressed promotion. 0, or 1 when a promotion
        failed."""
        asked = _read(self.promote_path, {})
        cur = _read(self.candidate_path, {})
        if cur.get("state") == "promoting" and not asked:
            say("gate: a promotion is marked running but nothing asked for it; re-forming")
        cand = self.candidate()
        if not asked:
            _write(self.candidate_path, cand)
            say(f"gate: {cand['state']}: {cand.get('tag') or cand.get('said')}")
            return 0
        self.promote_path.unlink(missing_ok=True)
        tag = asked.get("tag")
        if cand.get("state") != "candidate" or tag != cand.get("tag"):
            why = (f"{tag} is no longer the candidate (it is {cand.get('tag') or 'none'})"
                   if tag != cand.get("tag") else "a health check blocks it: "
                   + "; ".join(cand.get("blocking") or []))
            _write(self.candidate_path, {**cand, "refused": {"tag": tag, "why": why,
                                                             "at": _iso(self.now())}})
            say(f"gate: the press for {tag} was refused: {why}")
            return 0
        return self.promotion(cand, asked, say)

    def _step(self, cand: dict, asked: dict, step: str, **more) -> None:
        _write(self.candidate_path, {**cand, "state": "promoting", "step": step,
                                     "asked": asked, **more})

    def promotion(self, cand: dict, asked: dict, say=print) -> int:
        build, to, stable = cand["tag"], cand["to"], cand["stable"]
        work = self.state / "work" / f"promote-{to}-{self.now().strftime('%Y%m%dT%H%M%SZ')}"
        work.mkdir(parents=True, exist_ok=True)

        def failed(step: str, why: str, logf: Path) -> int:
            _write(self.candidate_path, {**cand, "state": "failed", "step": step,
                                         "asked": asked, "reason": why, "log": str(logf)})
            log({"at": _iso(self.now()), "tag": to, "from": build, "how": "promotion",
                 "failed": step, "why": why, "by": asked.get("by"), "log": str(logf)})
            say(f"gate: the promotion of {build} to {to} stopped at {step}: {why} ({logf})")
            return 1

        self._step(cand, asked, "cutting", log=str(work / "cut.log"))
        src = work / "kranto"
        r = self.run(["git", "clone", "--quiet", f"https://github.com/{self.gh.repo}",
                      str(src)], timeout=600)
        if r.returncode != 0:
            return failed("cutting", f"git clone: {(r.stderr or '').strip()[:200]}",
                          work / "cut.log")
        cap = ["systemd-run", "--user", "--scope", "-q", "-p", "MemoryMax=3G", "--"]
        r = self.run([*cap, "bash", str(src / "scripts/release/cut_local.sh"), "--from-tag",
                      build], timeout=3600,
                     env={**os.environ, "RELEASE_WORK": str(work / "cut")})
        (work / "cut.log").write_text((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            last = (r.stderr or r.stdout or "").strip().splitlines()
            return failed("cutting", last[-1] if last else f"exit {r.returncode}",
                          work / "cut.log")
        self._step(cand, asked, "rc_check", log=str(work / "rc_check.log"))
        r = self.run([*cap, "bash", str(src / "scripts/release/rc_check.sh"), to,
                      stable or ""], timeout=3600,
                     env={**os.environ, "PORT": str(self.port),
                          "ODD_PORT": str(self.port + 1), "E2E_DIR": str(work / "rc_check")})
        (work / "rc_check.log").write_text((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            fails = [ln for ln in (r.stdout or "").splitlines() if ln.startswith("FAIL")]
            return failed("rc_check", fails[0] if fails else f"exit {r.returncode}",
                          work / "rc_check.log")
        self._step(cand, asked, "releasing")
        checks = "; ".join(f"{c['name']}: {c['said']}" for c in cand.get("checks") or [])
        how = (f"from nightly {build} by {asked.get('by') or 'the owner'}, pressed "
               f"{asked.get('at') or 'now'}; rc_check passed against {stable}; {checks}")
        try:
            promote(self.gh, tag=to, now_reason=how, say=say, chosen=True, now=self.now)
        except GateError as exc:
            return failed("releasing", str(exc), work / "cut.log")
        _write(self.candidate_path, {**cand, "state": "promoted", "asked": asked,
                                     "promoted": {"tag": to, "at": _iso(self.now())}})
        say(f"gate: {to} is stable (promoted from {build})")
        return 0


# -- the notes' lines -------------------------------------------------------------------------

def promoted_line(how: str, at: datetime) -> str:
    return f"**Promoted to stable** {at.strftime('%Y-%m-%d %H:%M')} UTC: {how}."


def new_body(body: str, line: str) -> str:
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith(HELD_PREFIXES):
            lines[i] = line
            return "\n".join(lines) + "\n"
    head, rest = (lines[:2], lines[2:]) if len(lines) >= 2 else (lines, [])
    return "\n".join([*head, line, "", *rest]) + "\n"


def promote(gh: GitHub, *, tag: str, now_reason: str, run=run, now=_now,
            log_to: Path | None = None, say=print, chosen: bool = False) -> int:
    """Release the held stable ``tag`` at once. 0 released (or already), 1 refused (said
    why). ``chosen``: the owner's press (the tick), not the operator's word."""
    if not now_reason.strip():
        say("gate: --now needs --reason (it is said in the release's notes and logged)")
        return 1
    rels = gh.releases()
    _, latest = held(rels)
    rel = next((r for r in rels if r.get("tag_name") == tag and not r.get("draft")), None)
    if rel is None:
        say(f"gate: {tag} is not a published release of {gh.repo}")
        return 1
    if not STABLE.match(tag):
        say(f"gate: {tag} is not a stable tag (vX.Y.Z); a nightly build is promoted by cutting "
            "it (the owner's press: gate.py tick)")
        return 1
    if not rel.get("prerelease"):
        say(f"gate: {tag} is already released (not a prerelease)")
        return 0
    if latest and vkey(tag) <= vkey(latest):
        say(f"gate: {tag} is older than the latest stable {latest}; not released")
        return 1
    at = now()
    how = now_reason.strip() if chosen else f"by the operator ({now_reason.strip()})"
    gh.promote(tag, new_body(gh.body(tag), promoted_line(how, at)))
    log({"at": _iso(at), "tag": tag, "repo": gh.repo, "by": getpass.getuser(),
         "how": "press" if chosen else "now", "reason": now_reason.strip()}, log_to)
    say(f"gate: {tag} released to stable {how}")
    return 0


def withdraw(gh: GitHub, tag: str, reason: str, log_to: Path | None = None, say=print) -> int:
    if not NIGHTLY.match(tag):
        say(f"gate: withdraw takes a nightly build's tag (vX.Y.0-devN), not {tag}")
        return 1
    if not reason.strip():
        say("gate: withdraw needs --reason")
        return 1
    body = gh.body(tag)
    if WITHDRAWN in body:
        say(f"gate: {tag} is already withdrawn")
        return 0
    gh.edit_notes(tag, f"{WITHDRAWN} {reason.strip()}\n\n{body}")
    log({"at": _iso(_now()), "tag": tag, "how": "withdraw", "reason": reason.strip(),
         "by": getpass.getuser()}, log_to)
    say(f"gate: {tag} withdrawn: no install is offered it")
    return 0


# notes.py's CHECKING_LINE opens a nightly published before its rc_check
CHECKING = "**Do not install:** being checked (rc_check)"


def passed_dir() -> Path:
    """Where rc_check.sh leaves a tag's pass (``$RC_PASSED_DIR``)."""
    return Path(os.environ.get("RC_PASSED_DIR") or
                Path.home() / ".cache" / "kranto-release" / "passed")


def offer(gh: GitHub, tag: str, passed: Path | None = None, log_to: Path | None = None,
          say=print) -> int:
    """Offer a nightly that was published unoffered for its rc_check: only when rc_check.sh
    passed on it here, the "being checked" line is taken out of its notes, and installs on the
    nightly line are offered it from their next check. 0 offered, 1 refused (said why)."""
    if not NIGHTLY.match(tag):
        say(f"gate: offer takes a nightly build's tag (vX.Y.0-devN), not {tag}")
        return 1
    body = gh.body(tag)
    if not body.startswith(CHECKING):
        say(f"gate: {tag} is not waiting for its check" +
            (" (it is withdrawn: its notes open with Do not install)" if WITHDRAWN in body
             else ": it is offered already"))
        return 1 if WITHDRAWN in body else 0
    stamp = (passed or passed_dir()) / tag
    if not stamp.is_file():
        say(f"gate: rc_check.sh has not passed on {tag} here ({stamp}): run it first; {tag} "
            "stays unoffered")
        return 1
    gh.edit_notes(tag, body.split("\n\n", 1)[1] if "\n\n" in body else "")
    log({"at": _iso(_now()), "tag": tag, "how": "offer", "checked": stamp.read_text().strip(),
         "by": getpass.getuser()}, log_to)
    say(f"gate: {tag} is offered: rc_check passed on it at {stamp.read_text().strip()}")
    return 0


def mark_known(state: Path, signature: str, reason: str, say=print) -> int:
    if not reason.strip():
        say("gate: known needs --reason")
        return 1
    known = _read(state / "known.json", {})
    known[signature] = {"reason": reason.strip(), "by": getpass.getuser(), "at": _iso(_now())}
    _write(state / "known.json", known)
    log({"at": _iso(_now()), "signature": signature, "how": "known", "reason": reason.strip(),
         "by": getpass.getuser()}, state / "gate.jsonl")
    say(f"gate: {signature} marked known; it no longer blocks a promotion")
    return 0


def status(gate: Gate, say=print) -> int:
    rels = gate.gh.releases()
    waiting, latest = held(rels)
    say(f"gate: latest stable {latest or 'none'}; held: "
        f"{', '.join(r['tag_name'] for r in waiting) or 'none'}")
    c = gate.candidate()
    if c["state"] == "none":
        say(f"  {c['said']}")
        return 0
    say(f"  candidate {c['tag']} -> {c['to']} ({c['state']}); your install runs "
        f"{c.get('installed') or 'nothing readable'}; {c['count']} "
        f"PR{'' if c['count'] == 1 else 's'} since {latest}; "
        f"big: {', '.join('#' + str(b['number']) for b in c['big']) or 'none'}")
    if c.get("nightly_since"):
        say(f"  on nightly since {c['nightly_since']} (information, never a gate)")
    for ch in c["checks"]:
        word = {True: "ok", False: "BLOCKS", None: "blind"}[ch["ok"]]
        say(f"  {ch['name']}: {word}: {ch['said']}")
    if c.get("setup"):
        say(f"  your install: {c['setup']}")
    for b in c["blind"]:
        say(f"  could not read: {b}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hours")
    sub.add_parser("status")
    sub.add_parser("tick")
    c = sub.add_parser("candidate")
    c.add_argument("--quick", action="store_true", help="skip the pages and the odd installs")
    pr = sub.add_parser("promote")
    pr.add_argument("--tag")
    pr.add_argument("--now", action="store_true", help="release a held stable at once; needs "
                                                       "--tag and --reason")
    pr.add_argument("--reason", default="")
    k = sub.add_parser("known")
    k.add_argument("signature")
    k.add_argument("--reason", default="")
    w = sub.add_parser("withdraw")
    w.add_argument("tag")
    w.add_argument("--reason", default="")
    o = sub.add_parser("offer", help="offer a nightly published unoffered, once rc_check passed")
    o.add_argument("tag")
    a = p.parse_args(argv)
    try:
        if a.cmd == "hours":
            print("0")            # retired: nothing is held for hours
            return 0
        gh = GitHub(os.environ.get("REPO") or _repo())
        if a.cmd == "known":
            return mark_known(state_dir(), a.signature, a.reason)
        if a.cmd == "withdraw":
            return withdraw(gh, a.tag, a.reason)
        if a.cmd == "offer":
            return offer(gh, a.tag)
        if a.cmd == "promote":
            if not a.now or not a.tag:
                print("gate: time never promotes a release: the owner presses Promote to stable "
                      "(gate.py tick carries it out), or the operator releases a held stable "
                      "with promote --now --tag T --reason WHY", file=sys.stderr)
                return 1
            return promote(gh, tag=a.tag, now_reason=a.reason)
        gate = Gate(gh, Path(os.environ.get("KRANTO_GATE_HOME") or Path.home() / "kranto-kb"),
                    kranto=os.environ.get("KRANTO_BIN", "kranto"),
                    query=clickhouse(os.environ.get("GATE_CLICKHOUSE", "off")),
                    port=int(os.environ.get("GATE_PORT", "8942")))
        if a.cmd == "status":
            return status(gate)
        if a.cmd == "candidate":
            print(json.dumps(gate.candidate(slow=not a.quick), indent=1))
            return 0
        return gate.tick()
    except GateError as e:
        print(f"gate: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
