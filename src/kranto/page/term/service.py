"""Open in Claude Code's sessions, held by ``App.term`` (the owner's D6, D8).

- **One session per subject** (a described batch of sources; ``subject``): Open attaches to it
  when it runs, resumes its conversation in a fresh process when it ended (``--resume``), or
  starts one. Each session has its folder ``<loop home>/term/<tid>/`` (``launch`` lists it).
- **Limits** (settings ``term``): at most ``max_sessions`` running (a further Open is refused
  with the list); a session nobody watches and that prints nothing for ``idle_min`` is ended
  (its folder and conversation stay: Open resumes); the spend caps (``daily_usd``,
  ``term.daily_usd``) are checked at Open and at every meter reading, and end it when reached.
- **End** stops the process (SIGTERM, SIGKILL after 3 s, reaped) and removes the working copy
  and its branch, unless a proposal still refers to them. A session that exits by itself
  (``/exit``) or is ended for idleness, the cap or a restart keeps everything.
- **The token** is read from Kranto's own environment at each start and handed over through a
  pipe (``launch.env``); without one, Open says how to make one. Nothing is copied. The
  watcher's Claude API key (from Kranto's ``.env``) is used only once the owner chose it
  (``term.allow_api_key``, Use the API key); until then Open says what it would bill. On an API
  key a sources session runs on the watcher's reason model (``term.model`` wins), not the CLI's
  default.
- **Refusals**: a credit, auth or usage refusal in the transcript (``meter.refusal``) is the
  session's ``error``, shown in the page, until a later reply succeeds.
- **The network**: ``term.net_hosts`` plus the hosts the owner allowed for this session; any
  other host is refused, recorded (``net.jsonl``) and asked about in the page.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
import uuid
from pathlib import Path

from .. import claude_cli, proc
from ..settings.store import DEFAULTS as SETTINGS_DEFAULTS
from . import console, launch, meter, workdir
from . import door as D
from .pty import Pty
from .store import Store, valid_tid
from .subject import SubjectError, resolve, write_context

TICKET_S = 30
TICK_S = 2.0
# why a session ended, in the page's words ("exit" and "idle" are worded by ``ended_words``)
ENDED = {"owner": "Ended by you", "cap": "Ended: today's spend cap was reached",
         "restart": "Ended when Kranto restarted", "error": "Claude Code could not start",
         "outside": "Continued outside"}
# the token Kranto keeps itself (``claude_login``) is read at every start: no drop-in, no restart
NO_TOKEN = ("Open in Claude Code needs a Claude token: kranto setup claude adds one, and the "
            "next Open uses it.")
# the console under "Kranto's only" configuration (``config: kranto``) needs the same token; under
# your own configuration it uses your own Claude Code login instead
CONSOLE_NO_TOKEN = ("The console with Kranto's only configuration needs a Claude token: kranto "
                    "setup claude adds one, or choose Your own under Settings › Assistant.")
NET_REFUSAL = "Kranto: this host is not allowed for this session yet; the owner can allow it in the page"


class TermError(Exception):
    def __init__(self, code: int, msg: str, **extra):
        super().__init__(msg)
        self.code = code
        self.extra = extra


class Live:
    """A session running in this process."""

    def __init__(self, tid: str, pty: Pty, proxy, reading: meter.Reading, transcript: Path):
        self.tid, self.pty, self.proxy = tid, pty, proxy
        self.reading, self.transcript = reading, transcript
        self.reason: str | None = None
        self.ending = False
        self.console = False                  # the console: never reaped, its own cap


class Term:
    def __init__(self, app, environ=None):
        self.app = app
        self.environ = environ                       # tests: the token's environment
        self.live: dict[str, Live] = {}
        self.tickets: dict[str, tuple[str, float]] = {}
        self.doors: dict[str, D.Door] = {}
        self.serves = True                           # False: `kranto term` (Kranto serves them)
        self.lock = threading.RLock()
        self._reaper: threading.Thread | None = None
        self._ticking = threading.Lock()            # one tick at a time (see tick)
        self._recovered = False
        self._reason: tuple[float, str] | None = None   # the watcher's reason model, when read

    # -- settings and state ------------------------------------------------------------------
    def cfg(self) -> dict:
        return {**SETTINGS_DEFAULTS["term"], **(self.app.loop_cfg().get("term") or {})}

    @property
    def store(self) -> Store:
        root = self.app.loop_cfg().layout.term
        if getattr(self, "_store", None) is None or self._store.root != root:
            self._store = Store(root)
        return self._store

    def sandboxed(self) -> bool:
        return launch.boxed()

    def status(self) -> dict:
        """Whether Open is offered (``launch.offered``), and if not, why (the words the page
        shows)."""
        cfg = self.cfg()
        box = self.sandboxed()
        on, why = launch.offered(cfg, self.environ, box)
        cred, held = launch.login(cfg, self.environ)
        if on and not claude_cli.find():
            why = "Open in Claude Code needs the claude CLI on Kranto's PATH."
        elif on and held is not None:
            why = launch.WATCHERS_KEY
        elif on and cred is None:
            why = NO_TOKEN
        return {"enabled": on, "available": why is None, "why": why,
                "ask": "api_key" if on and held is not None else None,
                "on": launch.on_words(cred or held, cfg.get("model")) if on else None,
                "sources_on": launch.on_words(cred or held, self.model_for("sources", cred or held))
                if on else None,
                "sandboxed": box, "max_sessions": int(cfg["max_sessions"]),
                "running": len(self.running())}

    def model_for(self, kind: str, cred) -> str | None:
        """The session's ``--model``: ``term.model``; else, on an API key, a sources session's
        is the watcher's reason model; else none (the CLI's default)."""
        m = self.cfg().get("model")
        if m or cred is None or cred.kind != "api_key" or kind != "sources":
            return m
        return self.reason_model()

    def reason_model(self) -> str:
        """The watcher's reason model in Claude Code's names (the server's GET
        /api/settings/models, kept 5 minutes); ``launch.SOURCES_MODEL`` when it can't be read
        or is not a Claude model."""
        now = time.monotonic()
        if self._reason and now - self._reason[0] < 300:
            return self._reason[1]
        from .afk import AfkError, afk_url, call
        m = None
        url = afk_url(self.app.loop_cfg())
        try:
            roles = (call(url, "GET", "/api/settings/models", timeout=5) or {}).get("roles") \
                if url else None
            m = next((r.get("model") for r in roles if isinstance(r, dict)
                      and r.get("role") == "reason"), None) if isinstance(roles, list) else None
        except AfkError:
            m = None
        m = str(m or "")
        m = next((i for i, r, _ in launch.MODELS if m == r), m)    # a router's name
        if "/" in m:
            m = m.rsplit("/", 1)[1].replace(".", "-")
        m = m if m.startswith("claude-") else launch.SOURCES_MODEL
        self._reason = (now, m)
        return m

    def running(self) -> list[str]:
        return [t for t, lv in self.live.items() if lv.pty.alive]

    def _recover(self) -> None:
        """Records a gone server left running: ended by the restart (Open resumes them). A
        session another live server runs (``runner``) is left to it."""
        if self._recovered:
            return
        self._recovered = True
        me = proc.me()
        for r in self.store.all():
            if r.get("state") != "running" or r.get("tid") in self.live:
                continue
            run = r.get("runner") or {}
            if run and run != me and proc.running(run.get("pid"), run.get("start")):
                continue
            self.store.update(r["tid"], state="ended", reason="restart", pid=None)
        for r in self.store.all():
            if not r.get("removed"):
                self.serve(r["tid"])

    # -- the page's view ---------------------------------------------------------------------
    def view(self, r: dict) -> dict:
        lv = self.live.get(r["tid"])
        running = bool(lv and lv.pty.alive)
        if lv is not None and not running:
            # it ended a moment ago: the page heard it (the exit frame) before ``_exited``
            # wrote the reason and the code into the record
            r = {**r, "reason": lv.reason or "exit", "code": lv.pty.code}
        state = "running" if running else ("removed" if r.get("removed") else "ended")
        net = r.get("net") or {}
        if net.get("asked"):
            # a question a session asked before its host was quiet (a record from before
            # 0.3.67 asked about Claude Code's own updater and telemetry) is not a card
            quiet = self.quiet()
            net = {**net, "asked": [h for h in net["asked"] if not quiet(h)]}
        return {"tid": r["tid"], "subject": r.get("subject"), "title": r.get("title"),
                "state": state, "reason": None if running else r.get("reason"),
                "words": "Running" if running else
                ("Ended for good" if r.get("removed") else self.ended_words(r)),
                "created": r.get("created"), "updated": r.get("updated"),
                "usd": round(float(r.get("usd") or 0), 4), "tokens": r.get("tokens"),
                "viewers": lv.pty.viewers if running else 0,
                "sandboxed": r.get("sandboxed"), "cwd": r.get("cwd"),
                "branch": (r.get("work") or {}).get("branch") or None,
                "session": r.get("session"), "net": net, "batches": r.get("batches") or [],
                "on": r.get("on"), "refused": (r.get("refused") or {}).get("text"),
                "proposals": [{k: p.get(k) for k in ("n", "kind", "title", "confirm_class",
                                                     "subject", "fields", "why", "status",
                                                     "result", "patch", "at")}
                              for p in r.get("proposals") or []]}

    def ended_words(self, r: dict) -> str:
        """Why the session ended, from its record's reason and exit code. The program's own
        exit (``exit``) is told apart from a signal: bwrap reports a program killed by signal N
        as 128 + N, and a program killed itself reads as -N."""
        reason, code = r.get("reason"), r.get("code")
        if reason == "exit" or (reason is None and code is not None):
            sig = -code if isinstance(code, int) and code < 0 else \
                code - 128 if isinstance(code, int) and 128 < code <= 128 + 64 else None
            if sig:
                return f"The session was stopped unexpectedly (signal {sig})"
            return "Claude Code exited" + (f" with code {code}" if code else "")
        if reason == "idle":
            return f"Ended after {self.cfg()['idle_min']:g} minutes idle"
        if reason == "error" and r.get("error"):
            return f"{ENDED['error']}: {str(r['error'])[:200]}"
        return ENDED.get(reason, "Ended")

    def list(self) -> dict:
        self._recover()
        return {"sessions": [self.view(r) for r in self.store.all()
                             if not r.get("removed") and not r.get("console")],
                **self.status()}

    def get(self, tid: str) -> dict:
        self._recover()
        r = self.store.get(tid) if valid_tid(tid) else None
        if r is None:
            raise TermError(404, "no such session")
        return self.view(r)

    # -- open --------------------------------------------------------------------------------
    def open(self, subject, cols: int = 100, rows: int = 30) -> dict:
        """Attach, resume or start the subject's session; returns its view and a one-time
        ticket for the terminal's socket."""
        self._recover()
        st = self.status()
        if not st["available"]:
            raise TermError(503, st["why"], **({"ask": st["ask"]} if st["ask"] else {}))
        try:
            sub = resolve(self.app, subject)
        except SubjectError as e:
            raise TermError(404, str(e))
        with self.lock:
            rec = self.store.by_subject(sub.key)
            if rec and rec["tid"] in self.live and self.live[rec["tid"]].pty.alive:
                return {**self.view(rec), "ticket": self.ticket(rec["tid"])}
            self._check_caps()
            run = [t for t in self.running() if not self.live[t].console]
            if len(run) >= int(self.cfg()["max_sessions"]):
                raise TermError(429, f"{len(run)} sessions are open: end one first",
                                sessions=[self.view(self.store.get(t)) for t in run
                                          if self.store.get(t)])
            rec = rec or self._create(sub)
            self._start(rec, sub, cols, rows)
            return {**self.view(self.store.get(rec["tid"])), "ticket": self.ticket(rec["tid"])}

    def _create(self, sub) -> dict:
        tid = self.store.new_tid()
        d = self.store.dir(tid)
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        branch = f"term/{tid}"
        try:
            work = workdir.make(sub.source, d / "ws", branch)
        except workdir.WorkdirError as e:
            shutil.rmtree(d, ignore_errors=True)
            raise TermError(500, f"Could not make the session's folder: {e}")
        rec = {"tid": tid, "key": sub.key, "subject": {"kind": sub.kind, "id": sub.id},
               "title": sub.title, "project": sub.project, "session": str(uuid.uuid4()),
               "created": time.time(), "state": "new", "reason": None, "cwd": str(d / "ws"),
               "work": work, "source": str(sub.source) if sub.source else None,
               "usd": 0.0, "tokens": {"in": 0, "out": 0}, "days": {},
               "net": {"allowed": [], "asked": []}, "proposals": [],
               "topic": sub.topic, "batches": []}
        return self.store.put(rec)

    def spec(self, rec: dict, sandboxed: bool | None = None, cred=None) -> launch.Spec:
        """The session's launch: the same for the page and ``kranto term open``. ``cred``: the
        credential it starts with (default: Kranto's own, ``launch.login``), for its model."""
        tdir = self.store.dir(rec["tid"])
        work = rec.get("work") or {}
        resume = _transcript(tdir / "claude", Path(rec["cwd"]), rec["session"]).is_file()
        kind = (rec.get("subject") or {}).get("kind") or "idea"
        cred = cred or launch.login(self.cfg(), self.environ)[0]
        return launch.Spec(
            tid=rec["tid"], session=rec["session"], resume=resume, tdir=tdir,
            cwd=Path(rec["cwd"]), kind=kind,
            title=rec.get("title") or "", branch=work.get("branch") or "",
            model=self.model_for(kind, cred),
            sandboxed=self.sandboxed() if sandboxed is None else sandboxed,
            read_only=tuple(work.get("objects") or ()), mcp=True,
            tools=launch.SOURCES_TOOLS if (rec.get("subject") or {}).get("kind") == "sources"
            else launch.TOOLS)

    def prepare(self, rec: dict, sub=None, serve: bool = True, cred=None) -> launch.Spec:
        """The session's folders, ready for a start: context, config dir with the folder's
        trust answered, run/, meter/."""
        spec = self.spec(rec, cred=cred)
        if sub is not None:
            write_context(sub, spec.context)
        spec.context.mkdir(parents=True, exist_ok=True)
        Path(rec["cwd"]).mkdir(parents=True, exist_ok=True)
        _config_dir(spec.claude_dir, Path(rec["cwd"]))
        spec.run.mkdir(parents=True, exist_ok=True)
        (spec.run / "term-shell").unlink(missing_ok=True)   # an older session's own copy
        spec.meter.mkdir(parents=True, exist_ok=True)
        (spec.meter / "status.json").unlink(missing_ok=True)
        if serve:
            self.serve(rec["tid"])
        return spec

    def _start(self, rec: dict, sub, cols: int, rows: int) -> None:
        cred, held = launch.login(self.cfg(), self.environ)
        if held is not None:
            raise TermError(503, launch.WATCHERS_KEY, ask="api_key")
        if cred is None:
            raise TermError(503, NO_TOKEN)
        spec = self.prepare(rec, sub, cred=cred)
        proxy = self._proxy(rec["tid"]) if spec.sandboxed else None
        r, w = os.pipe()
        try:
            os.write(w, cred.value.encode())
        finally:
            os.close(w)
        try:
            argv = launch.argv(spec, proxy.dir if proxy else None)
            env = launch.env(spec, cred.var, r, self.environ)
            tid = rec["tid"]
            pty = Pty(argv, env=env, cwd=spec.cwd, pass_fds=(r,), cols=cols, rows=rows,
                      on_exit=lambda code, tid=tid: self._exited(tid, code), name=f"term-{tid}")
            self.live[tid] = Live(tid, pty, proxy, meter.Reading(),
                                  _transcript(spec.claude_dir, spec.cwd, spec.session))
            pty.start()
        except Exception as e:
            self.live.pop(rec["tid"], None)
            if proxy is not None:
                proxy.__exit__(None, None, None)
            self.store.update(rec["tid"], state="ended", reason="error", error=str(e)[:300])
            raise TermError(500, f"Claude Code could not start: {e}")
        finally:
            os.close(r)
        self.store.update(rec["tid"], state="running", reason=None, error=None, refused=None,
                          sandboxed=spec.sandboxed, pid=pty.pid, runner=proc.me(),
                          started=time.time(), resumed=spec.resume,
                          on=launch.on_words(cred, spec.model), login=cred.kind,
                          pinned=spec.model)
        self._reap_loop()

    def quiet(self):
        """Whether a host is Claude Code's own background traffic (``term.quiet_hosts``)."""
        from ..box import netproxy
        return netproxy.allowlist(self.cfg().get("quiet_hosts") or [])

    def _proxy(self, tid: str):
        from ..box import netproxy, sandbox
        if sandbox.net_mode() != "proxy":
            return None
        base = list(self.cfg().get("net_hosts") or [])

        def ok(host: str) -> bool:
            r = self.store.get(tid) or {}
            return netproxy.allowlist(base + list((r.get("net") or {}).get("allowed") or []))(host)

        quiet = self.quiet()

        def refused(host: str, target: str) -> None:
            if quiet(host):                          # Claude Code's own background traffic
                self._net_log(tid, "quiet", str(host).strip("[]").lower().rstrip("."), target)
            else:
                self._net_asked(tid, host, target)
        px = netproxy.Proxy(host_ok=ok, on_refuse=refused, refusal=NET_REFUSAL)
        px.__enter__()
        return px

    # -- the network's approvals ----------------------------------------------------------
    def _net_asked(self, tid: str, host: str, target: str) -> None:
        host = str(host).strip("[]").lower().rstrip(".")[:253]
        with self.store.lock:
            r = self.store.get(tid)
            if r is None:
                return
            net = r.get("net") or {"allowed": [], "asked": []}
            if host not in net["asked"] and host not in net["allowed"] and len(net["asked"]) < 50:
                net["asked"].append(host)
                self.store.update(tid, net=net)
        self._net_log(tid, "refused", host, target)

    def _net_log(self, tid: str, verdict: str, host: str, target: str = "",
                 by: str | None = None) -> None:
        try:
            with open(self.store.dir(tid) / "net.jsonl", "a") as f:
                f.write(json.dumps({"ts": time.time(), "verdict": verdict, "host": host,
                                    "target": target[:300], "by": by}) + "\n")
        except OSError:
            pass

    def net(self, tid: str, host: str, allow: bool, by: str = "ui") -> dict:
        """The owner's answer to a host the session asked for: Allow opens it for this
        session only; Deny forgets the question (the next try asks again)."""
        host = str(host or "").strip().lower().rstrip(".")
        with self.store.lock:
            r = self.store.get(tid) if valid_tid(tid) else None
            if r is None:
                raise TermError(404, "no such session")
            net = r.get("net") or {"allowed": [], "asked": []}
            if host not in net["asked"] and not (allow and host in net["allowed"]):
                raise TermError(400, "the session did not ask for that host")
            net["asked"] = [h for h in net["asked"] if h != host]
            if allow and host not in net["allowed"]:
                net["allowed"].append(host)
            self.store.update(tid, net=net)
        self._net_log(tid, "allowed" if allow else "denied", host, by=by)
        return self.get(tid)

    # -- tickets (the terminal's socket) -------------------------------------------------------
    def ticket(self, tid: str) -> str:
        now = time.time()
        with self.lock:
            for k in [k for k, (_, exp) in self.tickets.items() if exp < now]:
                self.tickets.pop(k, None)
            t = secrets.token_urlsafe(24)
            self.tickets[t] = (tid, now + TICKET_S)
            return t

    def redeem(self, tid: str, ticket: str) -> Live | None:
        """The running session a ticket opens, once; None for a wrong, used or old one."""
        with self.lock:
            got = self.tickets.pop(str(ticket or ""), None)
        if not got or got[0] != tid or got[1] < time.time():
            return None
        lv = self.live.get(tid)
        return lv if lv and lv.pty.alive else None

    # -- the end -------------------------------------------------------------------------------
    def end(self, tid: str, reason: str = "owner", remove: bool | None = None) -> dict:
        """Stop the session. ``remove`` (default: an End from the owner) also removes the
        working copy, unless a proposal refers to it, and the record leaves the list."""
        if not valid_tid(tid) or self.store.get(tid) is None:
            raise TermError(404, "no such session")
        remove = (reason == "owner") if remove is None else remove
        lv = self.live.get(tid)
        if lv is not None:
            lv.reason = lv.reason or reason
            lv.pty.kill()
            lv.pty.wait(5)
        rec = self.store.get(tid)
        fields = {"state": "ended", "reason": rec.get("reason") if rec.get("state") == "ended"
                  and lv is None else reason, "pid": None}
        if remove:
            keep = any((p.get("kind") == "patch" and p.get("status") in ("proposed", "running"))
                       for p in rec.get("proposals") or [])
            if not keep:
                workdir.remove(Path(rec["cwd"]))
            fields.update(removed=time.time(), kept=keep)
            self.unserve(tid)
        self.store.update(tid, **fields)
        return self.view(self.store.get(tid))

    def shutdown(self, reason: str = "restart", wait_s: float = 2.0) -> list[str]:
        """The server's stop: each running session's record says why it ended before its
        program is signalled, so the page reads the stop's reason rather than the next start's
        guess (``_recover``). Open resumes each, as after any restart. Returns the sessions it
        ended."""
        ended = []
        for tid, lv in list(self.live.items()):
            if not lv.pty.alive:
                continue
            lv.reason = reason
            self.store.update(tid, state="ended", reason=reason, pid=None)
            ended.append(tid)
        deadline = time.monotonic() + wait_s
        for tid in ended:
            lv = self.live.get(tid)
            if lv is not None:
                lv.pty.kill()
                lv.pty.wait(max(0.0, deadline - time.monotonic()))
        return ended

    def _exited(self, tid: str, code: int) -> None:
        lv = self.live.get(tid)
        reason = (lv.reason if lv else None) or "exit"
        if lv is not None:
            self._meter_step(lv)
            if lv.proxy is not None:
                lv.proxy.__exit__(None, None, None)
        try:
            self.store.update(tid, state="ended", reason=reason, code=code, pid=None)
        except KeyError:
            pass
        self.live.pop(tid, None)

    # -- the term door: the session's socket, and its proposals --------------------------------
    def serve(self, tid: str) -> D.Door | None:
        """The session's socket, served from now until it is ended for good."""
        if not self.serves:
            return None
        with self.lock:
            d = self.doors.get(tid)
            if d is not None and d.srv is not None:
                return d
            run = self.store.dir(tid) / "run"
            d = D.Door(self, tid, run / "api.sock", D.mint(run)).start()
            self.doors[tid] = d
            return d

    def unserve(self, tid: str) -> None:
        d = self.doors.pop(tid, None)
        if d is not None:
            d.stop()
        D.revoke(self.store.dir(tid) / "run")

    def propose(self, tid: str, body: dict) -> dict:
        """A session asks for an action: it is stored as a card for the owner (``decide``);
        nothing runs. Raises ``door.DoorError``."""
        p = D.proposal(body)
        rec = self.store.get(tid)
        if rec is None or rec.get("removed"):
            raise D.DoorError(404, "this session has ended")
        with self.store.lock:
            rec = self.store.get(tid)
            props = rec.get("proposals") or []
            waiting = sum(1 for x in props if x["status"] == "proposed")
            if waiting >= 20 or len(props) >= D.MAX_PROPOSALS:
                raise D.DoorError(429, "too many proposals wait for the owner already")
            p["n"] = len(props) + 1
            props.append(p)
            self.store.update(tid, proposals=props)
        return {"proposed": p["n"], "status": "proposed",
                "say": f"Proposed to the owner as card {p['n']} ({p['title']}). Nothing has "
                       "happened yet: the owner confirms or dismisses it in the page. Ask "
                       "kranto_proposals later for the outcome."}

    def describe(self, tid: str, body: dict) -> dict:
        """A described-sources session writes its list back: the text goes to
        the server's ``POST /api/sources/from-text`` with the session's own topic, through the same
        resolver, checks and approval as a list pasted in the page. Only a ``sources`` session
        may, at most ``MAX_DESCRIBES`` times; nothing is approved. Raises ``door.DoorError``."""
        from .afk import AfkError, afk_url, call
        rec = self.store.get(tid)
        if rec is None or rec.get("removed"):
            raise D.DoorError(404, "this session has ended")
        if (rec.get("subject") or {}).get("kind") != "sources":
            raise D.DoorError(403, "only a session about described sources can describe sources")
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise D.DoorError(400, "text: the list, one source per line")
        if len(text) > D.MAX_DESCRIBE_TEXT:
            raise D.DoorError(413, f"the list is longer than {D.MAX_DESCRIBE_TEXT} characters")
        sent = rec.get("described") or []
        if len(sent) >= D.MAX_DESCRIBES:
            raise D.DoorError(429, f"this session has sent {len(sent)} lists already")
        url = afk_url(self.app.loop_cfg())
        if not url:
            raise D.DoorError(503, "the server is not known here")
        try:
            out = call(url, "POST", "/api/sources/from-text",
                       {"text": text, "topic": rec.get("topic")})
        except AfkError as e:
            raise D.DoorError(502, str(e))
        job = out.get("job") or {}
        with self.store.lock:
            rec = self.store.get(tid)
            self.store.update(tid, described=[*(rec.get("described") or []),
                                              {"started": job.get("started"), "at": time.time()}])
        return {"job": _job_summary(job)}

    def described(self, tid: str) -> dict:
        """The session's last list: the server's latest batch job when it is the one this session
        started (its start time), summarised; once done, its batch is kept on the session so the
        page shows it under Found by Claude Code."""
        from .afk import AfkError, afk_url, call
        rec = self.store.get(tid) or {}
        mine = [d.get("started") for d in rec.get("described") or []]
        if not mine:
            raise D.DoorError(404, "this session has not sent a list yet")
        url = afk_url(self.app.loop_cfg())
        try:
            job = (call(url, "GET", "/api/sources/from-text") or {}).get("job") or {} \
                if url else {}
        except AfkError as e:
            raise D.DoorError(502, str(e))
        if job.get("started") not in mine:
            # The server runs one list at a time; a newer one (pasted in the page) replaced it
            return {"job": {"state": "unknown", "say": "the server is resolving another list now; "
                            "the owner sees yours on the Add source page"}}
        res = job.get("result") if isinstance(job.get("result"), dict) else None
        if job.get("state") == "done" and res and res.get("call_id") is not None:
            with self.store.lock:
                rec = self.store.get(tid)
                got = rec.get("batches") or []
                if res["call_id"] not in got:
                    self.store.update(tid, batches=[*got, res["call_id"]])
        return {"job": _job_summary(job)}

    def proposals(self, tid: str) -> dict:
        rec = self.store.get(tid) or {}
        return {"proposals": [{k: p.get(k) for k in ("n", "kind", "title", "status", "result")}
                              for p in rec.get("proposals") or []]}

    def decide(self, tid: str, n: int, confirm: bool, by: dict | None = None) -> dict:
        """The owner's press on a card: Dismiss, or Confirm, which runs the verb through
        the server's verbs' door as the owner (``POST /api/verbs/<kind>``, the command line's
        token). A proposal of a kind from before the build loop left (an action, a patch) is
        no longer available: Dismiss only."""
        with self.store.lock:
            rec = self.store.get(tid) if valid_tid(tid) else None
            if rec is None:
                raise TermError(404, "no such session")
            props = rec.get("proposals") or []
            p = next((x for x in props if x.get("n") == n), None)
            if p is None:
                raise TermError(404, "no such proposal")
            if p["status"] != "proposed":
                raise TermError(409, f"this proposal is {p['status']} already")
            p["status"] = "running" if confirm else "dismissed"
            p["decided"] = time.time()
            self.store.update(tid, proposals=props)
        if not confirm:
            return {"proposal": p}
        from .afk import afk_url, call
        try:
            if not D.VERB.match(str(p.get("kind") or "")):
                raise ValueError("this proposal is no longer available: dismiss it")
            url = afk_url(self.app.loop_cfg())
            if not url:
                raise ValueError("the server is not known here")
            subj = p.get("subject") or {}
            body = {"fields": p.get("fields") or {}, "client": "term"}
            if subj.get("id") is not None:
                body["subject"] = subj
            out = call(url, "POST", f"/api/verbs/{p['kind']}", body) or {}
            status = "done"
            result = {k: out.get(k) for k in ("say", "url", "what", "page") if out.get(k)}
        except Exception as e:                           # noqa: BLE001 - shown on the card
            status, result = "failed", {"error": str(e)[:500]}
        with self.store.lock:
            rec = self.store.get(tid)
            props = rec.get("proposals") or []
            for x in props:
                if x.get("n") == n:
                    x.update(status=status, result=result)
                    p = x
            self.store.update(tid, proposals=props)
        return {"proposal": p}

    # -- continue outside (the owner's D3) -------------------------------------------------------
    def outside(self, tid: str, config_dir: Path | None = None) -> dict:
        """Continue in your own terminal: the page's process ends (two processes on one
        conversation would fork it), the transcript is copied where your own Claude Code
        finds it (``config_dir``, default yours: ``$CLAUDE_CONFIG_DIR`` or ``~/.claude``), and
        two commands come back: ``plain``, your own Claude Code in the session's folder with
        Kranto's tools (reads and proposals, through the session's socket, while Kranto runs),
        your permissions; and ``kranto``, the same limits as in the page."""
        from ..box import claude_dirs
        rec = self.store.get(tid) if valid_tid(tid) else None
        if rec is None or rec.get("removed"):
            raise TermError(404, "no such session")
        if tid in self.live:
            self.end(tid, "outside", remove=False)
        else:
            self.store.update(tid, reason="outside")
        cwd = Path(rec["cwd"])
        got = claude_dirs.prepare_resume(rec["session"], cwd, config_dir=config_dir,
                                         sources=[self.store.dir(tid) / "claude"])
        if got["missing"]:
            raise TermError(409, "this session has no conversation yet: type something in it "
                                 "first")
        self.serve(tid)
        mcp = launch.compact({"mcpServers": {"kranto": {
            "type": "stdio", "command": "kranto", "args": ["mcp", "--term", tid]}}})
        return {"tid": tid, "cwd": str(cwd), "session": rec["session"],
                "branch": (rec.get("work") or {}).get("branch") or None,
                "plain": f"cd {_q(cwd)} && claude --resume {rec['session']} "
                         f"--mcp-config '{mcp}'",
                "kranto": f"kranto term open {tid}"}

    # -- the console (term/console.py) ------------------------------------------------------
    def console_cfg(self) -> dict:
        return console.settings(self.app.loop_cfg().data)

    def _console_rec(self, harness: str) -> dict | None:
        return self.store.by_subject(f"console:{harness}")

    def console_state(self) -> dict:
        """What the panel's head needs: the harnesses installed, the one it opens, the
        settings, and each harness's conversation (running, ended, none)."""
        self._recover()
        cfg = self.console_cfg()
        have = console.installed(self.environ)
        h = console.chosen(self.app.loop_cfg().data, self.environ)
        convs = {}
        for name in console.ORDER:
            rec = self._console_rec(name)
            v = self.view(rec) if rec else None
            convs[name] = v
            if rec and v is not None:                 # ⋯ › Previous sessions
                v["previous"] = [
                    {k: p.get(k) for k in ("session", "ended", "started", "usd")}
                    for p in rec.get("previous") or [] if isinstance(p, dict)
                    and p.get("session")]
        return {"settings": cfg, "harness": h,
                "harnesses": [{"id": k, "name": v["name"], "installed": k in have,
                               "models": [{"id": i, "name": n} for i, n in v["models"]],
                               "extras": v["extras"]} for k, v in console.HARNESSES.items()],
                "conversations": convs, "plugin": console.plugin_dir() is not None,
                "head": console.head_words(h, cfg["model"].get(h), cfg["permission"])
                if h else None,
                # with your own configuration, the MCP servers it loads besides Kranto's (Q2)
                "outside": console.outside_servers(h, cfg["config"], self.environ) if h else [],
                "why": None if h else ("No assistant is installed on Kranto's PATH: install "
                                       "Claude Code (or Codex) and open this panel again.")}

    def console_last(self, harness: str | None = None) -> dict:
        """What the console last said (``console.last_reply``), for the phone's sheet: read
        from its own transcript, never from the screen; ``said`` null with ``why`` when there is
        nothing to read."""
        h = harness or console.chosen(self.app.loop_cfg().data, self.environ)
        if h not in console.HARNESSES:
            return {"harness": None, "said": None, "why": "no assistant is installed"}
        rec = self._console_rec(h)
        if rec is None:
            return {"harness": h, "said": None, "why": "no conversation yet"}
        spec = self.console_spec(rec)
        return {"harness": h, **console.last_reply(
            console.transcript(spec, rec.get("session"), self.environ))}

    def open_console(self, harness: str | None = None, cols: int = 100, rows: int = 30) -> dict:
        """Attach to the harness's running console, or start it (resumed when it had a
        conversation); returns its view and a one-time ticket for the terminal's socket."""
        self._recover()
        have = console.installed(self.environ)
        h = harness or console.chosen(self.app.loop_cfg().data, self.environ)
        if h not in console.HARNESSES:
            raise TermError(400, "harness is claude or codex")
        if h not in have:
            raise TermError(503, f"{console.HARNESSES[h]['name']} is not installed on Kranto's "
                                 "PATH", harness=h)
        with self.lock:
            rec = self._console_rec(h)
            if rec and rec["tid"] in self.live and self.live[rec["tid"]].pty.alive:
                return {**self.view(rec), "ticket": self.ticket(rec["tid"]), "harness": h}
            if rec is None:
                rec = self._console_create(h)
            elif rec.get("removed"):
                rec = self.store.update(rec["tid"], removed=None)
            self._console_start(rec, have[h], cols, rows)
            return {**self.view(self.store.get(rec["tid"]) or rec),
                    "ticket": self.ticket(rec["tid"]), "harness": h}

    def _console_create(self, h: str) -> dict:
        tid = self.store.new_tid()
        d = self.store.dir(tid)
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        rec = {"tid": tid, "key": f"console:{h}", "subject": {"kind": "console", "id": h},
               "title": console.HARNESSES[h]["name"], "harness": h, "console": True,
               "session": str(uuid.uuid4()) if h == "claude" else None,
               "created": time.time(), "state": "new", "reason": None,
               "cwd": str(console.kranto_home()), "usd": 0.0, "tokens": {"in": 0, "out": 0},
               "days": {}, "net": {"allowed": [], "asked": []}, "proposals": [],
               "batches": []}
        return self.store.put(rec)

    def console_spec(self, rec: dict, binary: str = "") -> console.Spec:
        cfg = self.console_cfg()
        h = str(rec.get("harness") or (rec.get("subject") or {}).get("id") or "claude")
        loop = self.app.loop_cfg()
        add = [p for p in (getattr(loop, "home", None), getattr(self.app, "root", None)) if p]
        spec = console.Spec(
            tid=rec["tid"], harness=h, tdir=self.store.dir(rec["tid"]), cwd=Path(rec["cwd"]),
            session=rec.get("session"), model=cfg["model"].get(h),
            permission=cfg["permission"], config=cfg["config"],
            add_dirs=tuple(str(p) for p in dict.fromkeys(add) if str(p) != rec["cwd"]),
            plugin=console.plugin_dir() if h == "claude" else None, binary=binary,
            kranto_url=self._kranto_url())
        if h == "claude":
            t = console.transcript(spec, spec.session, self.environ)
            spec.resume = bool(t and t.is_file())
        else:
            spec.resume = bool(rec.get("started"))
        return spec

    def _kranto_url(self) -> str | None:
        """This Kranto's own address (the server's URL in loop.yaml), for the console's server."""
        try:
            from .afk import afk_url
            return afk_url(self.app.loop_cfg()) or None
        except Exception:                             # noqa: BLE001 - its default then
            return None

    def _console_start(self, rec: dict, binary: str, cols: int, rows: int) -> None:
        spec = self.console_spec(rec, binary)
        spec.meter.mkdir(parents=True, exist_ok=True)
        (spec.meter / "status.json").unlink(missing_ok=True)
        token: tuple[str, int] | None = None
        fds: tuple[int, ...] = ()
        r: int | None = None
        if spec.claude_dir is not None:              # kranto-scoped: Kranto's Claude token, piped
            cred, held = launch.login(self.cfg(), self.environ)
            if cred is None:
                raise TermError(503, launch.WATCHERS_KEY if held else CONSOLE_NO_TOKEN)
            _config_dir(spec.claude_dir, spec.cwd)
            r, w = os.pipe()
            try:
                os.write(w, cred.value.encode())
            finally:
                os.close(w)
            token, fds = (cred.var, r), (r,)
        tid = rec["tid"]
        try:
            pty = Pty(console.argv(spec), env=console.env(spec, self.environ, token),
                      cwd=spec.cwd, pass_fds=fds, cols=cols, rows=rows,
                      on_exit=lambda code, tid=tid: self._exited(tid, code),
                      name=f"console-{tid}")
            lv = Live(tid, pty, None, meter.Reading(),
                      console.transcript(spec, spec.session, self.environ) or Path("/dev/null"))
            lv.console = True
            self.live[tid] = lv
            pty.start()
        except Exception as e:
            self.live.pop(tid, None)
            self.store.update(tid, state="ended", reason="error", error=str(e)[:300])
            raise TermError(500, f"{console.HARNESSES[spec.harness]['name']} could not "
                                 f"start: {e}")
        finally:
            if r is not None:
                os.close(r)
        self.store.update(tid, state="running", reason=None, error=None, refused=None,
                          sandboxed=False, pid=pty.pid, runner=proc.me(), started=time.time(),
                          resumed=spec.resume, model=spec.model, permission=spec.permission,
                          config=spec.config)
        self._reap_loop()

    def console_new(self, harness: str) -> dict:
        """New conversation: types the harness's own command (``/clear``, ``/new``) into it;
        the old conversation stays in its ``/resume`` list."""
        rec = self._console_rec(harness)
        lv = self.live.get(rec["tid"]) if rec else None
        if rec is None or lv is None or not lv.pty.alive:
            raise TermError(409, "the console is not running")
        lv.pty.write((str(console.HARNESSES[harness]["new"]) + "\r").encode())
        return self.view(rec)

    def console_end(self, harness: str, fresh: bool = False) -> dict:
        """End this session's process; its conversation stays, and Open resumes it.
        ``fresh`` (the panel's End this session,): the next Open starts a **new**
        conversation, and the ended one joins ``previous`` (⋯ › Previous sessions resumes it)."""
        rec = self._console_rec(harness)
        if rec is None:
            raise TermError(404, "no console for that harness")
        out = self.end(rec["tid"], "owner", remove=False)
        if fresh:
            self._console_set_aside(self.store.get(rec["tid"]) or rec)
            out = self.view(self.store.get(rec["tid"]) or rec)
        return out

    PREVIOUS_KEEP = 20

    def _console_set_aside(self, rec: dict) -> dict:
        """The record's conversation into ``previous`` (newest first) and a new one in its
        place: Claude Code a new session id, Codex a start that does not resume."""
        prev = [p for p in rec.get("previous") or [] if isinstance(p, dict)]
        if rec.get("session") or rec.get("started"):
            prev = [{"session": rec.get("session"), "ended": time.time(),
                     "started": rec.get("started"), "usd": round(float(rec.get("usd") or 0), 4)},
                    *[p for p in prev if p.get("session") != rec.get("session")
                      or not rec.get("session")]][:self.PREVIOUS_KEEP]
        h = str(rec.get("harness") or "claude")
        return self.store.update(rec["tid"], previous=prev, started=None, usd=0.0,
                                 session=str(uuid.uuid4()) if h == "claude" else None,
                                 last_session_change=time.time())

    def console_resume(self, harness: str, session: str) -> dict:
        """⋯ › Previous sessions: the conversation ``session`` becomes the console's again (the
        one running now joins ``previous``); the panel's Open resumes it."""
        rec = self._console_rec(harness)
        if rec is None:
            raise TermError(404, "no console for that harness")
        prev = [p for p in rec.get("previous") or [] if isinstance(p, dict)]
        hit = next((p for p in prev if p.get("session") and p.get("session") == session), None)
        if hit is None:
            raise TermError(404, "no such previous session")
        lv = self.live.get(rec["tid"])
        if lv is not None and lv.pty.alive:
            self.end(rec["tid"], "owner", remove=False)
        rec = self.store.get(rec["tid"]) or rec
        rest = [p for p in prev if p is not hit]
        if rec.get("session") and rec.get("session") != session:
            rest = [{"session": rec.get("session"), "ended": time.time(),
                     "started": rec.get("started"),
                     "usd": round(float(rec.get("usd") or 0), 4)}, *rest][:self.PREVIOUS_KEEP]
        self.store.update(rec["tid"], previous=rest, session=session,
                          started=hit.get("started") or time.time(),
                          usd=float(hit.get("usd") or 0), last_session_change=time.time())
        return self.view(self.store.get(rec["tid"]) or rec)

    def console_here(self, route: str, title: str) -> dict:
        """The page the owner is on, for the status line (never sent to the model)."""
        words = " ".join(str(title or route or "").split())[:80]
        for name in console.ORDER:
            rec = self._console_rec(name)
            if rec:
                try:
                    (self.store.dir(rec["tid"]) / "meter").mkdir(parents=True, exist_ok=True)
                    (self.store.dir(rec["tid"]) / "meter" / "here.txt").write_text(words)
                except OSError:
                    pass
        return {"ok": True}

    def console_settings(self, body: dict) -> dict:
        """Settings › Assistant's console rows, into ``loop.yaml``'s ``ask:``."""
        from ..settings.write import write
        path = self.app.loop_cfg().layout.settings
        cur = self.console_cfg()
        changes: dict[tuple[str, str], object] = {}
        if "open" in body:
            if not isinstance(body["open"], bool):
                raise TermError(400, "open is true or false")
            changes[("ask", "open")] = body["open"]
        if "harness" in body:
            if body["harness"] not in console.HARNESSES:
                raise TermError(400, "harness is claude or codex")
            changes[("ask", "harness")] = body["harness"]
        if "permission" in body:
            if body["permission"] not in console.PERMISSIONS:
                raise TermError(400, f"permission is {', '.join(console.PERMISSIONS)}")
            changes[("ask", "permission")] = body["permission"]
        if "config" in body:
            if body["config"] not in console.CONFIGS:
                raise TermError(400, "config is own or Kranto")
            changes[("ask", "config")] = body["config"]
        if "model" in body:
            m = body["model"]
            if not isinstance(m, dict) or set(m) - set(console.HARNESSES) or \
                    not all(v is None or (isinstance(v, str) and len(v) < 80) for v in m.values()):
                raise TermError(400, "model is {harness: model or null}")
            merged = {**cur["model"], **{k: v for k, v in m.items() if v}}
            for k, v in m.items():
                if v is None:
                    merged.pop(k, None)
            changes[("ask", "model")] = merged
        if "daily_usd" in body:
            d = body["daily_usd"]
            if d is not None and (isinstance(d, bool) or not isinstance(d, int | float) or d <= 0):
                raise TermError(400, "daily_usd is a number of dollars, or null for no cap")
            changes[("ask", "daily_usd")] = d
        if not changes:
            raise TermError(400, "nothing to set")
        try:
            for keys, value in changes.items():
                write(path, keys, value)
        except (OSError, ValueError) as e:
            raise TermError(500, f"could not save: {e}")
        running = set(self.running())
        recs = [self._console_rec(h) for h in console.ORDER]
        # whose configuration and the permission mode are read at the start: a running console
        # takes them when restarted (the owner's Q2: the page offers it)
        moved = any(changes.get(("ask", k), cur[k]) != cur[k] for k in ("config", "permission"))
        restart = bool(moved and any(r and r["tid"] in running for r in recs))
        return {**self.console_state(), "restart": restart}

    # -- the reaper and the meter -----------------------------------------------------------------
    def _reap_loop(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        self._reaper = proc.thread(self._reap_forever, "term-reaper")

    def _reap_forever(self) -> None:
        while True:
            time.sleep(TICK_S)
            try:
                if not self.tick():
                    return
            except Exception:                         # noqa: BLE001 - next tick tries again
                pass

    def tick(self, now: float | None = None) -> bool:
        """One step: meter every running session, end the idle and the over-cap ones.
        False when nothing runs (the reaper stops; the next start restarts it). A tick waits for
        one in progress (the reaper's and a caller's): two meter steps on one transcript would
        each see half of a reading."""
        with self._ticking:
            now = now or time.time()
            idle = float(self.cfg()["idle_min"]) * 60
            live = [lv for lv in list(self.live.values()) if lv.pty.alive]
            for lv in live:
                self._meter_step(lv)
                if not lv.console and lv.pty.idle_s(now) >= idle:
                    self._end_async(lv.tid, "idle")
            subjects = [lv for lv in live if not lv.console]
            if subjects and self._over_cap():
                for lv in subjects:
                    self._end_async(lv.tid, "cap")
            cap = self.console_cfg()["daily_usd"]
            if cap and self.spent_today(console_only=True) >= cap:
                for lv in live:
                    if lv.console:
                        self._end_async(lv.tid, "cap")
            return bool(live)

    def _end_async(self, tid: str, reason: str) -> None:
        lv = self.live.get(tid)
        if lv is None or lv.ending:
            return
        lv.ending = True
        proc.thread(lambda: self.end(tid, reason, remove=False), f"term-end-{tid}")

    def _meter_step(self, lv: Live) -> None:
        if lv.console:
            self._console_session_step(lv)
        was = lv.reading.refusal
        d = lv.reading.step(self.store.dir(lv.tid) / "meter", lv.transcript)
        if lv.reading.refusal != was:
            # the Claude API refused the session's last request (credit, auth, usage), or a
            # later reply came through: the record says so, and the page shows it
            text = lv.reading.refusal
            try:
                self.store.update(lv.tid, error=text, refused={"text": text, "at": time.time()}
                                  if text else None)
            except KeyError:
                pass
        if not d:
            return
        with self.store.lock:
            r = self.store.get(lv.tid)
            if r is None:
                return
            day = time.strftime("%Y-%m-%d")
            days = r.get("days") or {}
            days[day] = round(float(days.get(day) or 0) + d["usd"], 6)
            tk = r.get("tokens") or {"in": 0, "out": 0}
            self.store.update(lv.tid, usd=round(float(r.get("usd") or 0) + d["usd"], 6),
                              days=days, model=lv.reading.model,
                              tokens={"in": tk["in"] + d["in"], "out": tk["out"] + d["out"]})
        # the spend stays in the session's record (``days``): the build loop's ledger
        # (loop.db) is never written since the build loop left

    def _console_session_step(self, lv: Live) -> None:
        """``/clear`` starts a new conversation in the same process: the status line's
        ``session_id`` says which, and the record (what Open resumes) and the meter follow."""
        sid = meter.status(self.store.dir(lv.tid) / "meter").get("session_id")
        if not isinstance(sid, str) or not sid:
            return
        r = self.store.get(lv.tid)
        if r is None or r.get("session") == sid:
            return
        self.store.update(lv.tid, session=sid, last_session_change=time.time())
        t = console.transcript(self.console_spec({**r, "session": sid}), sid, self.environ)
        if t is not None:
            lv.transcript = t
            lv.reading = meter.Reading(usd=lv.reading.usd)

    def spent_today(self, console_only: bool = False) -> float:
        day = time.strftime("%Y-%m-%d")
        return sum(float((r.get("days") or {}).get(day) or 0) for r in self.store.all()
                   if not console_only or r.get("console"))

    def _over_cap(self) -> bool:
        cap = self.cfg().get("daily_usd")
        return bool(cap and self.spent_today() >= float(cap))

    def _check_caps(self) -> None:
        if self._over_cap():
            raise TermError(400, "Today's spend has reached its cap (daily_usd or "
                                 "term.daily_usd); Open in Claude Code waits until tomorrow.")


def _job_summary(job: dict) -> dict:
    """A batch job as a session reads it: its state and, once done, each line's status, line
    and reason (no rows: the session needs what happened, not Kranto's records)."""
    res = job.get("result") if isinstance(job.get("result"), dict) else None
    out = {"state": job.get("state"), "elapsed_s": job.get("elapsed_s"),
           "error": job.get("error")}
    if res:
        out.update(message=res.get("message"), batch=res.get("call_id"),
                   lines=[{k: x.get(k) for k in ("status", "from", "label", "why")}
                          for x in res.get("lines") or []],
                   say="The owner reviews and approves these on the Add source page; nothing "
                       "is watched until they do.")
    return out


def _q(p) -> str:
    import shlex
    return shlex.quote(str(p))


def _transcript(claude_dir: Path, cwd: Path, session: str) -> Path:
    from ..box.claude_dirs import project_key
    return Path(claude_dir) / "projects" / project_key(Path(cwd)) / f"{session}.jsonl"


def _config_dir(d: Path, cwd: Path) -> None:
    """The session's own Claude Code config dir: its sessions and the folder's trust answer
    (the trust dialog's default is "No, exit"); never a credentials file."""
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    (d / ".credentials.json").unlink(missing_ok=True)
    p = d / ".claude.json"
    try:
        state = json.loads(p.read_text())
        state = state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        state = {}
    state.update(hasCompletedOnboarding=True, theme=state.get("theme") or "dark",
                 autoUpdates=False)
    projects = state.setdefault("projects", {})
    for key in dict.fromkeys([str(cwd), str(Path(cwd).resolve())]):
        projects.setdefault(key, {}).update(hasTrustDialogAccepted=True,
                                            hasCompletedProjectOnboarding=True)
    state.pop("mcpServers", None)
    p.write_text(json.dumps(state, indent=1))
