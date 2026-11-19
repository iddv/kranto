"""The cub runtime: one process per cub at most, started on demand (a job, an
event batch, an action, a page read), kept up ``cubs.idle_s`` after its last request, then
asked to stop; ``cubs.max_running`` processes at once.

Before every spawn: the cub is ``installed`` (not paused or removed), ``cubs.enabled``
and ``cubs.<id>.enabled`` are on, ``~/.config/kranto/cubs.STOP`` does not exist, a job or a
delivery waits while the scheduler is held, the vendored tree hashes to its pin and the venv
was built from its requirements. A changed tree pauses the cub ("its files changed since you
approved them"). Three runs in a row that crashed, missed their deadline, broke the protocol,
flooded or never said hello pause it too, as does a refused hello, a ticket flood, or its
monthly cap reached twice in a day. Resume is the owner's.

Every job is a ``runs`` row and a ``job.finished`` event; every delivery, action and read a
``cub_calls`` row of service ``host``. The ``cubs-reaper`` thread stops idle processes, kills
one past its deadline whose reader died, kills every cub within 10 s of the STOP file, and kills
this home's ``kranto-cub-<home6>-*`` scopes no process of the table owns (another Kranto on the
same account keeps its own).
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from ... import __version__
from ...store import iso, utcnow
from .. import events, tickets
from ..context import record_run
from ..manifest import SPEAKS, Feature, ManifestError, action_method, job_method, version_key
from . import files, logs, registry, sandbox, schedule
from . import settings as cub_settings
from .host import CubHost
from .process import CubFailed, CubProcess, HelloRefused, kill_unit, leftover_units, scope_prefix

log = logging.getLogger("kranto.core.cubs")
DEADLINES = {"event.deliver": 120, "action.run": 30, "read.run": 10}
READ_TTL = 10
STALE_S = 300
PAUSE_AFTER = 3
DELIVERY_BATCH = 100
POISON_AFTER = 8
REAP_EVERY = 10
STOP_ALL_S = 20
STOPPED = "stopped by the owner"


class CubUnavailable(ValueError):
    """The cub cannot take the request now: ``code`` 409 (halted, paused, off), 503 (busy or
    every slot taken); ``words`` say why."""

    def __init__(self, words: str, code: int = 409) -> None:
        super().__init__(words)
        self.code = code


class CubRunner:
    """The code of an installed cub's ``Feature``: each callable forwards to the runtime."""

    def __init__(self, runtime: CubRuntime, cid: str) -> None:
        self.runtime, self.cid = runtime, cid

    def job(self, kind: str, method: str):
        def run(ctx):
            return self.runtime.run_job(self.cid, kind, method, trigger="owner")
        return run

    def action(self, kind: str, method: str):
        def run(ctx, fields):
            return self.runtime.action(self.cid, kind, method, fields,
                                       door=getattr(ctx, "door", None) or "ui",
                                       subject=getattr(ctx, "subject", None))
        return run

    def read(self, name: str):
        def run(ctx, params):
            return self.runtime.page_read(self.cid, name, params)
        return run

    def deliver(self, kind: str, method: str):
        def run(ctx, event):              # a cub's deliveries are batches: deliver_all
            raise RuntimeError("a cub's events are delivered in batches by its runtime")
        return run

    def mode(self, ctx) -> str:
        return self.runtime.mode_word(self.cid)


class CubJob:
    """A cub job as the scheduler sees it: off while the cub (or cubs) is off or paused, its
    ``when`` setting is false, or this machine cannot cap it (``weak_limits``: every start would
    be refused until a setting changes, so it is not tried once a minute); due by its interval,
    or by its ``at``/``days`` slot."""

    def __init__(self, runtime: CubRuntime, cid: str, job: dict) -> None:
        self.runtime, self.cid, self.job = runtime, cid, job
        self.kind = job["kind"]
        self.method = job_method(job)

    @property
    def every_hours(self) -> float:
        cub = self.runtime.installed.get(self.cid)
        if cub is None or cub.state != "installed" or self.runtime.off(cub) \
                or self.runtime.weak_limits(cub):
            return 0
        when = self.job.get("when")
        if when:
            from .. import settings as feature_settings
            if not feature_settings.section(self.runtime.rt.cfg, self.cid).get(when):
                return 0
        return float(self.job["every_hours"])

    def due(self, store, now: datetime) -> bool | None:
        """The scheduler's due check for an ``at`` job; None: due by the interval."""
        if not self.job.get("at") or self.every_hours <= 0:
            return None if not self.job.get("at") else False
        return schedule.at_due(store, self.kind, self.job["at"], self.job.get("days") or [], now)

    def next_at(self, store, now: datetime):
        if not self.job.get("at") or self.every_hours <= 0:
            return None
        return schedule.at_next(store, self.kind, self.job["at"], self.job.get("days") or [],
                                now)

    def run(self):
        return self.runtime.run_job(self.cid, self.kind, self.method, trigger="schedule")


class CubRuntime:
    def __init__(self, rt, scheduler=None, *, http_transport=None, resolver=None,
                 searchers: dict | None = None) -> None:
        self.rt = rt
        self.scheduler = scheduler
        self.installed: dict[str, registry.Installed] = {}
        self.processes: dict[str, CubProcess] = {}
        self._starting: set[str] = set()             # scopes spawned, not yet in the table
        self._locks: dict[str, threading.Lock] = {}
        self._table = threading.RLock()
        self._failures: dict[str, int] = {}
        self._poison: dict[tuple, int] = {}
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._stop = threading.Event()
        self._reaper: threading.Thread | None = None
        self._http_transport = http_transport
        self._http: Any = None                    # an httpx.Client, made on first use
        self._searchers = searchers or {}
        self.resolver = resolver or _resolve
        self.limits_mode = sandbox.limits_mode()
        self._top: int | None = None
        self.scope_prefix = scope_prefix(files.root(rt.cfg))

    # -- loading --------------------------------------------------------------------------------

    def fresh(self) -> None:
        """Load again when the registry changed under this process: the command line installs,
        stops and removes cubs in its own process, and the server sees it at its next call (the
        reaper's tick at the latest, which then stops a stopped cub's process)."""
        try:
            top = self.rt.store.query_one("SELECT MAX(id) AS n FROM cubs")["n"]
        except Exception:  # noqa: BLE001 - a database without the table: nothing installed
            return
        if top != self._top:
            self.load()

    def start(self) -> None:
        """Load the registry, recover what a crash left, start the reaper."""
        if files.root(self.rt.cfg).exists():
            from . import install
            install.recover(self.rt)
            self.recover()
        self.load()
        self._wait_again()
        if self._reaper is None:
            self._reaper = threading.Thread(target=self._reap_loop, name="cubs-reaper",
                                            daemon=True)
            self._reaper.start()

    def load(self) -> None:
        """Every installed and paused cub, its manifest validated and its Feature built."""
        cfg = self.rt.cfg
        found: dict[str, registry.Installed] = {}
        self._top = self.rt.store.query_one("SELECT MAX(id) AS n FROM cubs")["n"]
        for cid, row in registry.latest_rows(self.rt.store).items():
            if row["state"] == "removed":
                continue
            cub = registry.installed(cfg, row)
            try:
                cub.manifest = registry.read_manifest(cub)
            except ManifestError as exc:
                if cub.state == "installed":
                    cub = self._pause_row(cub, f"its cub.yaml no longer validates: {exc}")
                try:
                    cub.manifest = json.loads((cub.dir / "cub.json").read_text())["manifest"]
                except (OSError, ValueError, KeyError):
                    log.warning("cub %s: no manifest to show (%s)", cid, exc)
                    continue
            cub.manifest = registry.shown_manifest(cid, cub.manifest)
            cub.feature = Feature.from_manifest(cub.manifest, CubRunner(self, cid),
                                                trust=cub.trust, grants=cub.grants.wire())
            found[cid] = cub
        with self._table:
            self.installed = found
        registry.set_loaded(tuple(c.feature for c in found.values()))

    def jobs(self) -> list[CubJob]:
        self.fresh()
        return [CubJob(self, cid, j) for cid, cub in sorted(self.installed.items())
                for j in cub.manifest.get("jobs", [])]

    # -- settings and state ---------------------------------------------------------------------

    def cub_value(self, cub: registry.Installed, name: str):
        return cub_settings.cub_value(self.rt.cfg, cub.id, name, trust=cub.trust)

    def cap_usd(self, cub: registry.Installed) -> float | None:
        """The model cap: the owner's ``cubs.<id>.monthly_usd``, else what the manifest asks,
        else the trust's default (the owner's own cubs: none; others: $5)."""
        own = cub_settings.own_value(self.rt.cfg, cub.id, "monthly_usd")
        if own is not None:
            return float(own)
        asked = cub.grants.model.monthly_usd
        if asked is not None:
            return float(asked)
        return self.cub_value(cub, "monthly_usd")

    def live_kinds(self, cub: registry.Installed) -> list[str]:
        return [k for k in cub_settings.live_kinds(self.rt.cfg, cub.id)
                if k in cub.grants.requests]

    def outside_range(self, cub: registry.Installed) -> str | None:
        from ..manifest import in_range
        if cub.bears_range and not in_range(__version__, cub.bears_range):
            return f"Kranto {__version__} is outside its range ({cub.bears_range})"
        return None

    def kind_modes(self, cub: registry.Installed) -> dict[str, str]:
        live = set(self.live_kinds(cub))
        dry_all = self.outside_range(cub) or tickets.stop_file().exists()
        return {k: ("live" if k in live and not dry_all else "dry")
                for k in cub.grants.requests}

    def off(self, cub: registry.Installed) -> str | None:
        """Why the owner's switches keep the cub from running, or None."""
        if not cub_settings.enabled(self.rt.cfg):
            return "features are off (cubs.enabled: false)"
        if not cub_settings.cub_enabled(self.rt.cfg, cub.id):
            return f"{cub.id} is off (cubs.{cub.id}.enabled: false)"
        if tickets.stop_file().exists():
            return f"cubs.STOP exists ({tickets.stop_file()})"
        return None

    def weak_limits(self, cub: registry.Installed) -> str | None:
        """Why a cub that is not the owner's does not start where only rlimits apply (no pids
        cap, no CPU quota), or None."""
        return cub_settings.weak_limits(self.rt.cfg, cub.trust, self.limits_mode)

    def halted(self, cub: registry.Installed) -> str | None:
        """Why a call inside a run is refused now (-32003), or None."""
        current = self.installed.get(cub.id)
        if current is None or current.state != "installed":
            return f"{cub.id} is {current.state if current else 'removed'}"
        return self.off(cub)

    def mode_word(self, cid: str) -> str:
        """The word on its tag: off while not enabled, paused, live when every kind it
        may ask for is live, else practice (the owner's word for dry: an approval sends
        nothing); outside its Kranto range it says so."""
        cub = self.installed.get(cid)
        if cub is None:
            return "off"
        if cub.state == "paused":
            return "paused"
        if self.off(cub):
            return "off"
        outside = self.outside_range(cub)
        if outside:
            return f"practice ({outside})"
        modes = self.kind_modes(cub)
        if modes and all(m == "live" for m in modes.values()):
            return "live"
        # the owner's word for dry: an approval in practice sends nothing
        return "practice"

    # -- pause and resume -----------------------------------------------------------------------

    def _pause_row(self, cub: registry.Installed, note: str) -> registry.Installed:
        row = registry.latest(self.rt.store, cub.id)
        registry.append(self.rt.store, row, state="paused", note=note[:300])
        cub.state, cub.note = "paused", note[:300]
        events.core_publish(self.rt.store, "cub.paused", {"cub": cub.id})
        logs.write(self.rt.cfg, cub.id, run=None, src="host", level="warning",
                   msg=f"paused: {note}")
        return cub

    def pause(self, cub: registry.Installed, note: str) -> None:
        """The core pauses a cub: its process is stopped, nothing of it runs until the
        owner resumes it; its open tickets stay open."""
        current = self.installed.get(cub.id) or cub
        if current.state != "installed":
            return
        self._pause_row(current, note)
        proc = self.processes.get(cub.id)
        if proc is None or not proc.busy:
            self._end(cub.id, "stop")
        # a run in flight finishes: its further calls are refused (-32003), and its process
        # is stopped when it answers (request's end)
        registry.set_loaded(tuple(c.feature for c in self.installed.values()))

    def resume(self, cid: str) -> registry.Installed:
        cub = self.installed.get(cid)
        if cub is None:
            raise CubUnavailable(f"no cub {cid}", 404)
        if tickets.stop_file().exists():
            raise CubUnavailable(f"remove {tickets.stop_file()} first: the file stops every "
                                 "cub whatever the page says")
        if cub.state == "paused":
            row = registry.latest(self.rt.store, cid)
            registry.append(self.rt.store, row, state="installed", note=None)
        self._failures.pop(cid, None)
        self.load()
        return self.installed[cid]

    def capped(self, cub: registry.Installed, cap: float) -> None:
        """The cub's monthly cap refused a call. ``spend.capped`` is said once a cap a day (a
        loop against the same cap is refused, -32002, without a word each time); the cap
        reached a second time in a day (the owner raised it, and it was spent again) is a
        loop: the cub is paused. Spending against a cap alone never pauses."""
        since = iso(utcnow() - timedelta(days=1))
        caps = {e["payload"].get("cap_usd") for e in
                events.read(self.rt.store, kinds=["spend.capped"], limit=500)
                if e["payload"].get("feature") == cub.id and e["ts"] >= since}
        if cap in caps:
            return
        events.core_publish(self.rt.store, "spend.capped", {"feature": cub.id, "cap_usd": cap})
        if caps:
            self.pause(cub, "its monthly cap was reached twice in a day")

    # -- spawning -------------------------------------------------------------------------------

    def _lock(self, cid: str) -> threading.Lock:
        with self._table:
            return self._locks.setdefault(cid, threading.Lock())

    def _check_files(self, cub: registry.Installed) -> None:
        src = cub.dir / "src"
        if not src.is_dir():
            self.pause(cub, "its folder is missing")
            raise CubUnavailable("its folder is missing")
        if files.tree_hash(src) != cub.tree_hash:
            self.pause(cub, "its files changed since you approved them")
            raise CubUnavailable("its files changed since you approved them")
        if not files.venv_ok(cub.dir, cub.requirements):
            self.pause(cub, "its packages are not the ones it was installed with")
            raise CubUnavailable("its packages are not the ones it was installed with")

    def _hello(self, cub: registry.Installed, run_uuid: str):
        def check(p: dict) -> dict:
            if p.get("api") not in SPEAKS:
                raise HelloRefused(-32010, f"this Kranto speaks {', '.join(SPEAKS)}",
                                   {"speaks": list(SPEAKS)},
                                   pause=f"protocol {p.get('api')} not spoken: it needs a "
                                         "newer Kranto")
            if p.get("id") != cub.id or p.get("version") != cub.version \
                    or p.get("manifest_hash") != cub.manifest_hash:
                raise HelloRefused(-32005, "the cub.yaml this process read is not the one "
                                           "approved", pause="the cub.yaml this process read "
                                                             "is not the one approved")
            have = p.get("handlers") if isinstance(p.get("handlers"), dict) else {}
            missing = [f"{k}: {n}" for k, names in self._wanted(cub).items() for n in names
                       if n not in (have.get(k) or [])]
            if missing:
                raise HelloRefused(-32602, "handlers the manifest names are missing",
                                   {"missing": missing},
                                   pause=f"its entry file lacks {', '.join(missing)}")
            floor = cub_settings.values(self.rt.cfg).get("cubs.min_sdk")
            if floor and version_key(str(p.get("sdk"))) < version_key(floor):
                raise HelloRefused(-32010, f"its SDK {p.get('sdk')} is older than {floor}",
                                   {"min_sdk": floor},
                                   pause=f"its SDK {p.get('sdk')} is older than the {floor} "
                                         "this Kranto asks for")
            return self.hello_result(cub, run_uuid)
        return check

    def _wanted(self, cub: registry.Installed) -> dict[str, list[str]]:
        m = cub.manifest
        return {"jobs": [job_method(j) for j in m.get("jobs", [])],
                "events": [s["method"] for s in (m.get("events") or {}).get("subscribe", [])
                           if s.get("method")],
                "actions": [action_method(a) for a in m.get("actions", [])],
                "reads": list(m.get("provides", [])),
                "stages": [s["id"] for s in m.get("stages", []) if s.get("kind") == "code"]}

    def hello_result(self, cub: registry.Installed, run_uuid: str) -> dict:
        per_day = {k: tickets.KINDS[k].per_day for k in cub.grants.requests
                   if k in tickets.KINDS}
        own = self.cub_value(cub, "tickets_per_day")
        if own is not None:
            per_day = {k: min(v, own) for k, v in per_day.items()}
        return {"api": "cub/1", "host": "kranto", "host_version": __version__,
                "speaks": list(SPEAKS), "trust": cub.trust, "mode": self.kind_modes(cub),
                "granted": cub.grants.wire(),
                "limits": {"line_bytes": 1048576,
                           "kv_bytes": self.cub_value(cub, "kv_mb") * 1024 * 1024,
                           "kv_keys": 10000, "calls_per_day": self.cub_value(cub, "calls_per_day"),
                           "model_per_hour": 60, "search_per_hour": 30, "http_per_hour": 60,
                           "tickets_per_day": per_day},
                "deprecations": [], "run": {"uuid": run_uuid, "started_at": iso(utcnow())},
                "tz": schedule.local_zone(), "now": iso(utcnow())}

    def _limits(self, cub: registry.Installed) -> sandbox.Limits:
        lim = cub_settings.limits(self.rt.cfg, cub.id, cub.trust)
        longest = max([int(j.get("deadline_s", 600)) for j in cub.manifest.get("jobs", [])]
                      + [120])
        return sandbox.Limits(memory_mb=lim["memory_mb"], pids=lim["pids"],
                              cpu_pct=lim["cpu_pct"], tmp_mb=lim["tmp_mb"],
                              cpu_s=2 * longest + 10)

    def _spawn(self, cub: registry.Installed, run_uuid: str, run_log) -> CubProcess:
        sandbox.require_sandbox()
        limits = self._limits(cub)
        unit = f"{self.scope_prefix}{cub.id.replace('_', '-')}-{run_uuid[:8]}"
        venv = cub.dir / "venv" if cub.requirements else None
        argv = sandbox.argv(src=cub.dir / "src", entry=cub.entry, venv=venv, unit=unit,
                            limits=limits, mode=self.limits_mode)
        proc = CubProcess(cid=cub.id, argv=argv, env=sandbox.env_for(self.limits_mode),
                          preexec=sandbox.rlimits(limits, self.limits_mode), unit=unit,
                          mode=self.limits_mode, hello=self._hello(cub, run_uuid),
                          stderr=run_log.stderr, cwd="/tmp")
        run_log.host("spawn", mode=self.limits_mode, unit=unit)
        proc.run_log = run_log
        with self._table:
            self._starting.add(unit)              # the reaper leaves it until it is in the table
        try:
            proc.start()
        except BaseException as exc:
            with self._table:
                self._starting.discard(unit)
            if isinstance(exc, CubFailed):
                run_log.host(exc.words, level="warning")
                if exc.pause:
                    self.pause(cub, exc.pause)
            raise
        run_log.host("hello")
        return proc

    def _slot(self, cid: str) -> None:
        """Room for one more process: ``cubs.max_running`` at once; an idle one is stopped
        to make room, else the request waits for another time."""
        cap = cub_settings.values(self.rt.cfg)["cubs.max_running"]
        with self._table:
            alive = {k: p for k, p in self.processes.items() if p.alive}
            if cid in alive or len(alive) < cap:
                return
            idle = [k for k, p in alive.items() if not p.busy]
        if idle:
            self._end(min(idle, key=lambda k: alive[k].last_used), "idle")
            return
        raise CubUnavailable(f"{cap} cubs are running (cubs.max_running): later", 503)

    def _process(self, cub: registry.Installed, run_uuid: str, run_log) -> CubProcess:
        proc = self.processes.get(cub.id)
        if proc is not None and proc.alive:
            if proc.ping():
                return proc
            run_log.host("no pong: a fresh process", level="warning")
            proc.kill()
        self._slot(cub.id)
        proc = self._spawn(cub, run_uuid, run_log)
        with self._table:
            self.processes[cub.id] = proc
            self._starting.discard(proc.unit)
        return proc

    def _end(self, cid: str, why: str, *, kill: bool = False,
             grace_s: float | None = None) -> None:
        """End one cub's process: ``shutdown`` (``kill``: SIGTERM at once); ``grace_s``
        shortens the waits (the server's stop)."""
        with self._table:
            proc = self.processes.pop(cid, None)
        if proc is None:
            return
        if kill:
            proc.kill() if grace_s is None else proc.kill(grace_s)
        elif grace_s is None:
            proc.shutdown(why)
        else:
            proc.shutdown(why, grace_s=grace_s, term_grace_s=grace_s)

    # -- requests -------------------------------------------------------------------------------

    def preflight(self, cid: str, kind: str) -> registry.Installed:
        self.fresh()
        cub = self.installed.get(cid)
        if cub is None:
            raise CubUnavailable(f"no cub {cid}", 404)
        if cub.state != "installed":
            raise CubUnavailable(f"{cid} is {cub.state}" + (f": {cub.note}" if cub.note else ""))
        off = self.off(cub) or self.weak_limits(cub)
        if off:
            raise CubUnavailable(off)
        if kind in ("job", "deliver") and self.scheduler is not None \
                and self.scheduler.hold is not None:
            raise CubUnavailable("the scheduler is held (an update is draining)")
        if files.updating_marker(self.rt.cfg, cid).exists():
            raise CubUnavailable(f"{cid} is being updated", 503)
        self._check_files(cub)
        return cub

    def request(self, cid: str, method: str, params: dict, *, kind: str, deadline_s: float,
                wait_s: float | None = None) -> tuple[dict, str, int]:
        """One host→cub request under the cub's lock: ``(result, run_uuid, ms)``. Raises
        ``CubUnavailable`` (before anything ran) or ``CubFailed`` (the run failed)."""
        cub = self.preflight(cid, kind)
        lock = self._lock(cid)
        if not lock.acquire(timeout=wait_s if wait_s is not None else -1):
            raise CubUnavailable(f"{cid} is busy", 503)
        run_uuid = params.get("run_uuid") or uuid.uuid4().hex
        run_log = logs.RunLog(self.rt.cfg, cid, run_uuid)
        started = time.monotonic()
        try:
            proc = self._process(cub, run_uuid, run_log)
            host = CubHost(self, cub, run_uuid=run_uuid, run_log=run_log,
                           stage=method == "stage.run")
            proc.run_log = run_log
            run_log.host(f"{method} {params.get('kind') or params.get('name') or ''}".strip())
            result = proc.request(method, {**params, "run_uuid": run_uuid}
                                  if method != "read.run" else params, deadline_s,
                                  host.dispatch)
        except CubFailed as exc:
            run_log.host(exc.words, level="warning")
            self._failed(cub, exc)
            raise
        finally:
            if self.installed.get(cid) is not None and self.installed[cid].state != "installed":
                self._end(cid, "stop")             # paused during the run: stopped after it
            lock.release()
        self._failures.pop(cid, None)
        ms = int((time.monotonic() - started) * 1000)
        run_log.host(f"{method} ok", ms=ms)
        return result, run_uuid, ms

    def _failed(self, cub: registry.Installed, exc: CubFailed) -> None:
        with self._table:
            proc = self.processes.get(cub.id)
            if proc is not None and not proc.alive:
                self.processes.pop(cub.id, None)
        if exc.pause:
            self.pause(cub, exc.pause)
            return
        if not exc.counts:
            return
        n = self._failures.get(cub.id, 0) + 1
        self._failures[cub.id] = n
        if n >= PAUSE_AFTER:
            self.pause(cub, f"{n} runs in a row failed (the last: {exc.words})")

    def _host_row(self, cid: str, op: str, status: str, ms: int, run_uuid: str | None,
                  detail: str | None) -> None:
        self.rt.store.insert("cub_calls", {"cub": cid, "service": "host", "op": op,
                                           "status": status, "run_uuid": run_uuid, "ms": ms,
                                           "detail": (detail or None) and detail[:300],
                                           "created_at": iso(utcnow())})

    def run_job(self, cid: str, kind: str, method: str, *, trigger: str = "schedule",
                topic_id: int | None = None, events_ids: list[int] | None = None) -> dict:
        """One job run: a ``runs`` row and ``job.finished``. A failed run raises (the
        scheduler backs off); a cub that cannot take it now leaves it due. Every run is an
        activity run (the scheduler's, or its own for the owner's Run now): its uuid is the
        run's, its host calls the run's trace."""
        from ... import activity
        with activity.run(self.rt.store, kind, origin="schedule" if trigger == "schedule"
                          else "press", by="ui" if trigger == "owner" else None):
            return self._run_job(cid, kind, method, trigger=trigger, topic_id=topic_id,
                                 events_ids=events_ids, run_uuid=activity.run_uuid(kind))

    def _run_job(self, cid: str, kind: str, method: str, *, trigger: str, topic_id, events_ids,
                 run_uuid: str) -> dict:
        cub = self.installed.get(cid)
        job = next((j for j in (cub.manifest.get("jobs", []) if cub else [])
                    if j["kind"] == kind), None)
        if job is None:
            raise CubUnavailable(f"{cid} has no job {kind}", 404)
        params = {"kind": kind, "method": method, "deadline_s": int(job.get("deadline_s", 600)),
                  "mode": self.kind_modes(cub), "trigger": trigger, "run_uuid": run_uuid}
        if topic_id is not None:
            params["topic_id"] = topic_id
        if events_ids:
            params["events"] = events_ids
        started = utcnow()
        try:
            out, run_uuid, _ = self.request(cid, "job.run", params, kind="job",
                                            deadline_s=params["deadline_s"])
        except CubUnavailable as exc:
            log.info("%s not run: %s", kind, exc)
            return {"status": "skipped", "line": str(exc), "recorded": False}
        except CubFailed as exc:
            words = "failed: interrupted (Kranto was stopping)" if self._stop.is_set() \
                else exc.words
            record_run(self.rt.store, kind, "failed", started, {}, words, run_uuid=run_uuid)
            raise RuntimeError(words) from None
        if self._stop.is_set():
            # cut short by the shutdown's cancel: failed, so the job is due again after the
            # restart (a weekly slot is not lost to an update); the cub's once() keys make a
            # second run of finished work harmless
            record_run(self.rt.store, kind, "failed", started, {},
                       "failed: interrupted (Kranto was stopping)", run_uuid=run_uuid)
            raise RuntimeError("failed: interrupted (Kranto was stopping)")
        status = out.get("status") if out.get("status") in ("ok", "degraded", "skipped") \
            else "ok"
        summary = out.get("summary") if isinstance(out.get("summary"), dict) else {}
        if len(json.dumps(summary)) > 4000:
            summary = {"note": "its summary was over 4,000 bytes"}
        if out.get("line"):
            summary = {**summary, "line": str(out["line"])[:200]}
        record_run(self.rt.store, kind, status, started, summary, run_uuid=run_uuid)
        self._drop_cache(cid)
        return {"status": status, **summary}

    def action(self, cid: str, kind: str, method: str, fields: dict, *, door: str,
               subject: dict | None = None) -> dict:
        params = {"kind": kind, "method": method, "fields": fields, "door": door,
                  "deadline_s": DEADLINES["action.run"],
                  "mode": self.kind_modes(self.installed[cid]) if cid in self.installed else {}}
        if subject is not None:
            params["subject"] = subject
        try:
            out, run_uuid, ms = self.request(cid, "action.run", params, kind="action",
                                             deadline_s=DEADLINES["action.run"], wait_s=30)
        except CubFailed as exc:
            self._host_row(cid, "action", "error", 0, None, exc.words)
            words = "it did not answer in 30 s" if exc.kind == "deadline" else exc.words
            raise CubUnavailable(words, 502) from None
        self._host_row(cid, "action", "ok", ms, run_uuid, kind)
        for name in out.get("refresh") or []:
            self._drop_cache(cid, name)
        return {k: out[k] for k in ("ok", "say", "refresh") if k in out}

    def read(self, cid: str, name: str, params: dict) -> dict:
        """A page read, cached 10 s; a read that fails or is slow answers the last one for 5
        minutes, marked ``stale``."""
        key = (cid, name, json.dumps(params, sort_keys=True, default=str))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < READ_TTL:
            return hit[1]
        try:
            out, run_uuid, ms = self.request(cid, "read.run", {"name": name,
                                                              "params": {k: str(v) for k, v in
                                                                         params.items()},
                                                              "deadline_s": 10},
                                             kind="read", deadline_s=DEADLINES["read.run"],
                                             wait_s=10)
        except (CubFailed, CubUnavailable) as exc:
            words = exc.words if isinstance(exc, CubFailed) else str(exc)
            self._host_row(cid, "read", "error", 0, None, f"{name}: {words}")
            if hit and time.monotonic() - hit[0] < STALE_S:
                return {**hit[1], "stale": True}
            raise CubUnavailable(f"{name}: {words}", 502) from None
        if len(json.dumps(out)) > 262144:
            self._host_row(cid, "read", "error", ms, run_uuid, f"{name}: over 256 KiB")
            raise CubUnavailable("the cub's answer did not fit (256 KiB)", 502)
        self._host_row(cid, "read", "ok", ms, run_uuid, name)
        self._cache[key] = (time.monotonic(), out)
        return out

    def page_read(self, cid: str, name: str, params: dict) -> dict:
        """A read as the pages get it: every ticket it names that is no longer open is
        named as none, so no list offers a dialog on it; the read of the cub's Needs you rows
        (``ui.today_rows``, its primary one of its asks) has the core's asks in place of the
        cub's own rows of tickets; its tile's count is those asks' (``core.asks``)."""
        from .. import asks
        out = asks.overlay(self.rt.store, cid, self.read(cid, name, params))
        cub = self.installed.get(cid)
        ui = (cub.manifest.get("ui") or {}) if cub is not None else {}
        kinds = list(cub.grants.requests) if cub is not None else []
        needs = [r for r in ui.get("today_rows") or [] if r.get("group") == "needs_you"
                 and r.get("primary") in kinds]
        if any(r.get("read") == name for r in needs):
            out = asks.needs_rows(self.rt, cid, out)
        tile = ui.get("tile") or {}
        if needs and tile.get("count") == name and isinstance(out, dict) and "count" in out:
            out = {**out, "count": asks.count(self.rt.store, cid)}
        return out

    def _drop_cache(self, cid: str, name: str | None = None) -> None:
        for key in [k for k in self._cache if k[0] == cid and (name is None or k[1] == name)]:
            self._cache.pop(key, None)

    # -- deliveries -----------------------------------------------------------------------------

    def deliver_all(self) -> dict[str, int]:
        """Push each cub's new events to its handlers in batches of at most 100 (protocol): the
        cursor moves to what the cub handled; a batch that fails 8 times on the
        same first event is skipped, and said."""
        done: dict[str, int] = {}
        self.fresh()
        for cid, cub in list(self.installed.items()):
            if cub.state != "installed" or self.off(cub):
                continue
            for sub in cub.grants.events.subscribe:
                if not sub.get("method"):
                    continue
                kind = sub["kind"]
                batch = events.take(self.rt.store, cid, kind,
                                    min_trust=sub.get("min_trust", "unreviewed"),
                                    limit=DELIVERY_BATCH)
                if not batch:
                    continue
                payload = [{k: e[k] for k in ("id", "ts", "kind", "feature", "trust",
                                              "subject_kind", "subject_id", "payload")}
                           for e in batch]
                first = batch[0]["id"]
                params = {"kind": kind, "method": sub["method"], "events": payload,
                          "deadline_s": DEADLINES["event.deliver"], "mode": self.kind_modes(cub)}
                try:
                    out, run_uuid, ms = self.request(cid, "event.deliver", params,
                                                     kind="deliver",
                                                     deadline_s=DEADLINES["event.deliver"])
                except CubUnavailable:
                    continue
                except CubFailed as exc:
                    key = (cid, kind, first)
                    self._poison[key] = self._poison.get(key, 0) + 1
                    self._host_row(cid, "deliver", "error", 0, None, f"{kind}: {exc.words}")
                    if self._poison[key] >= POISON_AFTER:
                        events.advance(self.rt.store, cid, kind, batch[-1]["id"])
                        ids = ",".join(str(e["id"]) for e in batch)[:200]
                        self._host_row(cid, "deliver", "skipped", 0, None,
                                       f"events deliver skipped after {POISON_AFTER} failures: "
                                       f"{ids}")
                        self._poison.pop(key, None)
                    continue
                handled = out.get("handled")
                if isinstance(handled, int) and handled >= first:
                    last = min(handled, batch[-1]["id"])
                    events.advance(self.rt.store, cid, kind, last)
                    done[f"{cid}:{kind}"] = sum(1 for e in batch if e["id"] <= last)
                self._poison.pop((cid, kind, first), None)
                self._host_row(cid, "deliver", "ok", ms, run_uuid, kind)
                self._drop_cache(cid)
        return done

    # -- the reaper and the end -----------------------------------------------------------------

    def busy(self) -> list[str]:
        """Cubs with a request in flight (what an update's drain waits for)."""
        with self._table:
            return sorted(k for k, p in self.processes.items() if p.alive and p.busy)

    def reap(self) -> None:
        self.fresh()
        stop = tickets.stop_file().exists()
        idle_s = cub_settings.values(self.rt.cfg)["cubs.idle_s"]
        now = time.monotonic()
        with self._table:
            procs = dict(self.processes)
        for cid, proc in procs.items():
            if not proc.alive:
                with self._table:
                    if self.processes.get(cid) is proc:
                        self.processes.pop(cid, None)
                continue
            cub = self.installed.get(cid)
            # removed, stopped by the owner (at once, busy or not), or paused by the core (a
            # run in flight finishes first)
            gone = cub is None or cub.state == "paused" and (
                not proc.busy or (cub.note or "").startswith(STOPPED))
            if stop or gone or self.off(cub):
                self._end(cid, "stop", kill=True)
            elif proc.deadline_at is not None and now > proc.deadline_at + 8:
                self._end(cid, "deadline", kill=True)
            elif not proc.busy and now - proc.last_used > idle_s:
                threading.Thread(target=self._end, args=(cid, "idle"), daemon=True).start()
        if self.limits_mode == "scope":
            units = leftover_units(self.scope_prefix)
            # read after the listing: a scope listed while its cub was still saying hello is
            # in the table or in _starting by now, never killed as left behind
            with self._table:
                mine = {p.unit for p in self.processes.values() if p.unit} | self._starting
            for unit in units:
                if unit not in mine:
                    kill_unit(unit)

    def _reap_loop(self) -> None:
        while not self._stop.wait(REAP_EVERY):
            try:
                self.reap()
            except Exception:  # noqa: BLE001 - the reaper must outlive any one failure
                log.exception("the cubs reaper raised")

    def stop_all(self, why: str = "host", budget_s: float = STOP_ALL_S) -> list[str]:
        """At the server's shutdown: idle processes get ``shutdown``, busy ones
        ``cancel`` then ``shutdown``, all at once; SIGTERM then SIGKILL, and each
        ``kranto-cub-*`` scope emptied, within ``budget_s`` in all (the server's stop gives it
        ``stopping.CUBS_S``). Returns the cubs whose process was still alive at the end."""
        self._stop.set()
        deadline = time.monotonic() + budget_s

        def left() -> float:
            return max(0.0, deadline - time.monotonic())

        with self._table:
            procs = dict(self.processes)
        for proc in procs.values():
            if proc.busy and proc.deadline_at is not None:
                proc.deadline_at = min(proc.deadline_at, time.monotonic())
        # a quarter of the budget to exit when asked, a quarter after SIGTERM; the rest for
        # SIGKILL and the scope
        grace = budget_s / 4
        threads = [threading.Thread(target=self._end, args=(cid, why),
                                    kwargs={"grace_s": grace}, daemon=True,
                                    name=f"cub-{cid}-stop") for cid in procs]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=left())
        killers = [threading.Thread(target=proc.kill, args=(min(0.5, left()),), daemon=True,
                                    name=f"cub-{cid}-kill")
                   for cid, proc in procs.items() if proc.alive]
        for t in killers:
            t.start()
        for t in killers:
            t.join(timeout=left())
        return sorted(cid for cid, proc in procs.items() if proc.alive)

    # -- recovery and the daily sweep -----------------------------------------------------------

    def recover(self) -> None:
        """What a crash can leave: a cub folder without an installed or paused row is
        quarantined; an installed cub whose folder is missing is paused; stale scopes killed."""
        cfg, store = self.rt.cfg, self.rt.store
        root = files.root(cfg)
        rows = registry.latest_rows(store)
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if d.name.startswith(".") or not d.is_dir():
                continue
            row = rows.get(d.name)
            if row is None or row["state"] == "removed":
                to = root / ".work" / f"orphan-{d.name}-{int(time.time())}"
                to.parent.mkdir(parents=True, exist_ok=True)
                files.make_writable(d)
                d.rename(to)
                log.warning("cub folder %s had no registry row: moved to %s", d.name, to)
        for cid, row in rows.items():
            if row["state"] == "installed" and not (root / cid / "src").is_dir():
                cub = registry.installed(cfg, row)
                self._pause_row(cub, "its folder is missing")
        if self.limits_mode == "scope":
            for unit in leftover_units(self.scope_prefix):
                kill_unit(unit)

    def gc(self) -> dict:
        """The daily ``cubs.gc``: logs rotated, staged folders older than a day, the work
        folder, removed cubs older than 30 days, open tickets past their time expired."""
        cfg = self.rt.cfg
        root = files.root(cfg)
        removed = 0
        now = time.time()
        for cid in list(self.installed):
            removed += logs.rotate(cfg, cid)
        from . import install
        # an update staged for the owner's press stays however long it waits; one that offers
        # nothing any more is cancelled first
        install.cancel_stale(self.rt.store, cfg)
        pending = {j for j, _ in install.awaiting_ids(self.rt.store)}
        for sub, age in ((".staged", 86400), (".work", 86400), (".removed", 30 * 86400)):
            for d in (root / sub).iterdir() if (root / sub).is_dir() else []:
                try:
                    if sub == ".staged" and d.name in pending:
                        continue
                    if now - d.stat().st_mtime > age:
                        files.make_writable(d)
                        shutil.rmtree(d) if d.is_dir() else d.unlink()
                        removed += 1
                except OSError:
                    log.warning("cubs.gc could not remove %s", d)
        expired = tickets.expire_due(self.rt.store)
        waiting = self._wait_again()
        interrupted = install.recover(self.rt, idle_s=3600)
        return {"removed": removed, "expired": expired, "interrupted": len(interrupted),
                "waiting_again": waiting}

    def _wait_again(self) -> int:
        """A draft whose ask ran out of time under an earlier release waits again
        (``core.asks.wait_again``): at the start, and in the daily gc after its sweep. Never
        fatal: a failure is logged and the start goes on."""
        from .. import asks
        try:
            return len(asks.wait_again(self.rt.store, self.installed))
        except Exception:  # noqa: BLE001 - the cubs start whatever this finds
            log.exception("cubs: the drafts that ran out of time could not wait again")
            return 0

    def describe(self, cid: str) -> dict | None:
        """What ``GET /api/features`` adds for a cub."""
        self.fresh()
        cub = self.installed.get(cid)
        if cub is None:
            return None
        return {"state": cub.state, "live": self.live_kinds(cub),
                "source": {"kind": cub.source_kind, **cub.source, "sha": cub.sha},
                "update": None, "paused": {"note": cub.note} if cub.state == "paused" else None,
                "limits_mode": self.limits_mode, "mode": self.mode_word(cid)}

    # -- the services the host calls ------------------------------------------------------------

    def http_client(self):
        import httpx
        if self._http is None:
            self._http = httpx.Client(transport=self._http_transport, follow_redirects=False)
        return self._http

    def searcher(self, cid: str):
        return self._searchers.get(cid)


def _resolve(host: str) -> list[str]:
    import socket
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})

