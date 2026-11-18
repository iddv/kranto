"""The page's own server as one plain function: ``handle(method, path, query, body)``.

The server's ``kranto serve`` mounts it at ``/brb/`` (``brb ui``'s own stdlib server, ``server.py``,
calls it too). The function knows nothing about either server: it takes the path below its
mount point and returns ``(status, content_type, body_bytes)``. Guards stay with the server:
loopback only, and no cross-origin POST (both servers refuse with 403). Who is calling is the
server's to say too: it checks the request's token and passes ``identity``; a write acts as
that caller, never as the body's ``origin``.

What it serves since the factory left (cut 3): the page's document and assets, the
one activity read across Kranto (the server's runs and the open sessions), the console and Open in
Claude Code (``api/term…``), Kranto's own traces (``api/trace…``), Details, the feedback sheet, the
live feed (``api/stream``) and a header for a host that still reads one. Everything else the page
shows comes from the server's own API. It never opens ``loop.db`` or a task folder.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs

from .. import paths, rowsafe
from .http import HttpError, _file, _json  # noqa: F401  (HttpError: callers import it here)
from .routes import ROUTES
from .routes.base import Req, route
from .routes.static import APP_PAGE, MOVED, STATIC, TYPES, UI_DIR  # noqa: F401
from .routes.trace import read_needs_identity  # noqa: F401  (the host asks it of a GET)

API_VERSION = 7                 # a host checks this before it mounts the API (2: chat;
                                # 3: configure takes kranto_url, cards come from its API;
                                # 4: stream() serves /api/stream, the live feed; 5: the trace
                                # reads, which a host identifies: read_needs_identity; 6:
                                # configure takes kranto_data, api/activity, change activity;
                                # 7: the factory left: no builds, loop, projects or maintenance)
HOST = "127.0.0.1"
# the origins a token may carry (the server's tokens and ``brb ui``'s): the page and the command
# line write here; an assistant's token (mcp, agent:<name>) acts through the server's verbs
WRITERS = ("ui", "cli")
ORIGIN = re.compile(r"ui|cli|mcp|agent:[A-Za-z0-9_.-]{1,40}")
# the console's settings in loop.yaml that the page writes (``POST api/term/settings``)
TERM_KEY = re.compile(r"term\.[a-z_.]{1,60}")
log = logging.getLogger(__name__)


def _iso(t) -> str | None:
    if not t:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(t)))


def session_row(view: dict, now: float | None = None) -> dict:
    """An Open in Claude Code session that runs (its terminal's view, ``term.service``), as one
    row of the activity read."""
    now = now or time.time()
    tid = view["tid"]
    started = view.get("created")
    title = view.get("title") or "a session"
    usd = view.get("usd")
    return {"id": f"session:{tid}", "uuid": tid, "kind": "session",
            "title": f"Open in Claude Code · {title}", "words": None, "state": "running",
            "trigger": {"origin": "ui", "by": None, "at": _iso(started)}, "subject": None,
            "feature": "session", "started": _iso(started), "finished": None,
            "elapsed_s": round(now - started, 1) if started else None,
            "usd": round(float(usd), 4) if usd else 0.0, "calls": None, "tokens": None,
            "progress": None, "trace": f"#/sessions/{tid}/trace", "stoppable": False,
            "stopping": False, "needs": None, "error": None, "why": None, "verb": None}


class App:
    def __init__(self, root: Path | None = None, harness: str = "claude-code",
                 loop_home: Path | None = None, kranto_url: str | None = None):
        # ``root`` and ``harness`` are kept for callers of the old signature (``brb ui``, the
        # tests); nothing reads a task folder any more
        self.root = Path(root).resolve() if root else None
        self.harness = harness
        self.loop_home = loop_home        # None: $KRANTO_LOOP_HOME, else ~/kranto-loop (loop.yaml)
        self.kranto_url = kranto_url  # the host's URL: everything but the page's own reads
        self._term = None
        self.kranto_data: Path | None = None   # the host's data folder (its activity.json)

    @property
    def term(self):
        """Open in Claude Code's sessions and the console (``kranto.page.term.service.Term``),
        made on first use."""
        if self._term is None:
            from ..term.service import Term
            self._term = Term(self)
        return self._term

    def loop_cfg(self):
        """The page's settings file, ``loop.yaml`` (the console's ``term`` and ``ask``, the
        trace's, feedback's): read, never the build loop's ledger."""
        from ..settings.store import Config
        return Config(self.loop_home)

    def afk_url(self) -> str | None:
        if self.kranto_url:
            return self.kranto_url
        try:
            return self.loop_cfg()["kranto"].get("url")
        except Exception:                          # noqa: BLE001 - no settings: no server
            return None

    def header(self) -> dict:
        """``GET api/header``: what a host's header read before the factory left; every count
        is 0, for a host that still reads one."""
        return {"api_version": API_VERSION, "paused": False, "running": 0, "queued": 0,
                "revising": 0, "needs_you": 0, "open_ideas": 0, "onboarding": []}

    # ---- the console's settings (loop.yaml's ``term``) --------------------------------------
    def term_setting(self, body: dict) -> dict:
        """``POST api/term/settings`` ``{key, value}`` (or ``{key, clear: true}``: back to the
        default): a key under ``term.``, checked by ``settings.write.check`` and written to
        loop.yaml."""
        from ..settings import write as settings
        key = str(body.get("key") or "")
        if not TERM_KEY.fullmatch(key) or key not in settings.RULES:
            raise HttpError(400, "only the console's settings (term.…) are written here")
        try:
            value = settings.UNSET if body.get("clear") is True \
                else settings.check(key, body.get("value"))
        except ValueError as e:
            raise HttpError(400, str(e))
        settings.write(paths.LoopLayout(self.loop_cfg().home).settings, tuple(key.split(".")),
                       value)
        log.info("loop.yaml: %s %s (%s)", key, "back to the default" if value is settings.UNSET
                 else f"set to {value!r}", body.get("origin") or "ui")
        return {"ok": True, "key": key,
                "value": None if value is settings.UNSET else value}

    # ---- what Kranto is doing: one read across Kranto -------------------------
    ACTIVITY_TTL = 2.0

    def activity(self, q: dict) -> dict:
        """``GET api/activity``: the server's runs (its ``/api/activity``, through ``afk``) with
        the open sessions; cached ``ACTIVITY_TTL`` (the header, the sheet and every line on a
        page share one read), and never past a change of the server's mirror (a Dismiss, a Stop or
        a run's mark: the live feed's re-read gets the answer it was told about)."""
        from urllib.parse import urlencode
        keep = {k: str(q[k]) for k in ("subject", "kind", "limit", "all", "hours", "run")
                if q.get(k) not in (None, "")}
        key = urlencode(sorted(keep.items()))
        hit = getattr(self, "_activity", {}).get(key)
        now = time.time()
        if hit and now - hit[0] < self.ACTIVITY_TTL and hit[0] >= self._afk_mirror_at():
            return hit[1]
        out = self._activity_read(keep, key)
        cache = getattr(self, "_activity", None)
        if cache is None:
            cache = self._activity = {}
        if len(cache) > 32:
            cache.clear()
        cache[key] = (now, out)
        return out

    def _afk_mirror_at(self) -> float:
        """When the server last rewrote its ``activity.json`` (0: not known here)."""
        if not self.kranto_data:
            return 0.0
        try:
            return (Path(self.kranto_data) / "activity.json").stat().st_mtime
        except OSError:
            return 0.0

    def _activity_read(self, keep: dict, key: str) -> dict:
        if keep.get("run"):
            return self._activity_run(keep["run"])
        afk_error = None
        try:
            afk = self.afk("GET", "/api/activity" + (f"?{key}" if key else ""))
        except HttpError as e:
            afk, afk_error = {}, ("the server's runs show after its next update" if e.code == 404
                                  else f"the server's runs could not be read: {e}")
        running: list[dict] = []
        if self._term is not None:
            try:
                for tid in self._term.running():
                    lv = self._term.live.get(tid)
                    if lv is not None and lv.console:
                        continue        # the console is always there; its turns are the runs
                    running.append(session_row(self._term.get(tid)))
            except Exception:                      # noqa: BLE001 - the rest still shows
                pass
        subject = keep.get("subject")
        if subject:
            k, _, i = subject.partition(":")
            running = [r for r in running if (r.get("subject") or {}).get("kind") == k
                       and str((r.get("subject") or {}).get("id")) == i]
        if keep.get("kind"):
            running = [r for r in running if r["kind"] == keep["kind"]]
        limit = max(1, min(int(keep.get("limit") or 50), 500))
        allrun = (afk.get("running") or []) + running
        allrecent = sorted(afk.get("recent") or [],
                           key=lambda r: r.get("finished") or "", reverse=True)[:limit]
        waiting = afk.get("waiting") or []
        failing = afk.get("failing") or []
        incidents = [i for i in afk.get("incidents") or [] if isinstance(i, dict)]
        quiet = None if allrun else (afk.get("quiet") or "Nothing is running.")
        return {"seq": afk.get("seq", 0), "running": allrun, "waiting": waiting,
                "next": afk.get("next") or [], "recent": allrecent,
                "folded": afk.get("folded") or [], "failing": failing, "incidents": incidents,
                "counts": {"running": len(allrun), "waiting": len(waiting),
                           "failed_recent": sum(1 for r in allrecent
                                                if r.get("state") == "failed"),
                           "failing": len(failing), "building": 0,
                           "incidents": len(incidents)},
                "quiet": quiet, "scheduler": afk.get("scheduler", False),
                "paused": False, "afk_error": afk_error, "now": afk.get("now"),
                # the status bar's word and why, as the server works it out; None from a
                # the server before it, or without one
                "health": afk.get("health") if isinstance(afk.get("health"), dict) else None}

    def _activity_run(self, rid: str) -> dict:
        """One run with its marks (the live afk trace's head line), by its id or uuid."""
        uuid = rid.split(":", 1)[1] if rid.startswith("afk:") else rid
        if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", uuid):
            raise HttpError(404, "no such run")
        return self.afk("GET", f"/api/activity?run={uuid}")

    def activity_stop(self, body: dict) -> dict:
        """``POST api/activity/stop {id}``: the owner's Stop, where the run can stop. The server's
        run at its next step; a session by End."""
        rid = str(body.get("id") or "")
        src, _, rest = rid.partition(":")
        self._activity = {}
        if src == "afk" and re.fullmatch(r"[A-Za-z0-9-]{8,64}", rest):
            return self.afk("POST", f"/api/activity/{rest}/stop", {})
        if src == "session" and rest:
            return {**self.term.end(rest), "stopping": True}
        raise HttpError(404, "no such run, or it cannot be stopped")

    def afk(self, method: str, path: str, body: dict | None = None, owner: bool = False) -> dict:
        """The server's API on loopback: the page never touches its files. A state-changing call
        carries the server's own origin, as its guard requires, and the UI's token.
        ``owner``: a read that is the owner's only (a run's model calls, for its agent trace)
        carries the token too."""
        import urllib.error
        import urllib.request

        from ..tokens import Store
        url = self.afk_url()
        if not url:
            raise HttpError(503, "the server's API is not known here (no server URL)")
        base = url.rstrip("/")
        data = json.dumps(body or {}).encode() if method == "POST" else None
        secret = Store().value("ui") if method == "POST" or owner else None
        req = urllib.request.Request(base + path, data=data, method=method, headers={
            "Accept": "application/json", "Content-Type": "application/json",
            **({"Origin": base} if method == "POST" else {}),
            **({"Authorization": f"Bearer {secret}"} if secret else {})})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("error") or f"HTTP {e.code}"
            except ValueError:
                msg = f"HTTP {e.code}"
            raise HttpError(e.code, f"the server: {msg}")
        except (OSError, ValueError) as e:
            raise HttpError(502, f"the server's API at {base}: {type(e).__name__}: {e}")


# ---- the one function ------------------------------------------------------------------------
_default: App | None = None


def configure(root: str | Path | None = None, harness: str = "claude-code",
              loop_home: str | Path | None = None, kranto_url: str | None = None,
              kranto_data: str | Path | None = None, builds: bool = False) -> App:
    """The app ``handle`` serves when it is given none. ``kranto_url``: the host's base URL.
    ``kranto_data``: the host's data folder, whose ``activity.json`` the live feed watches
    (ACT: a run of the server's shows as it goes); never read, only stat'ed. ``root`` and
    ``builds`` are accepted from a host of before the cut and ignored: nothing builds here."""
    global _default
    try:
        from ..box import handoff
        handoff.mark_dotenv()    # the processes Kranto starts tell the watcher's key
    except (ImportError, AttributeError):
        pass
    _default = App(Path(root).expanduser() if root else None, harness,
                   Path(loop_home).expanduser() if loop_home else None,
                   kranto_url=kranto_url)
    _default.kranto_data = Path(kranto_data) if kranto_data else None
    # each error kept once by its id: the server's file when it is here, else the loop home's
    rowsafe.configure(loop_home)
    return _default


def default_app() -> App:
    return _default or configure()


def stop_terms(reason: str = "restart") -> list[str]:
    """The server's stop (the server stopping.py, through host_api): the open Claude Code
    sessions end with their reason written first. Nothing when none was ever opened."""
    if _default is None or _default._term is None:
        return []
    return _default._term.shutdown(reason)


def _query(query) -> dict:
    if query is None:
        return {}
    if isinstance(query, (bytes, str)):
        query = parse_qs(query.decode() if isinstance(query, bytes) else query)
    return {k: (v[0] if isinstance(v, list) and v else v) for k, v in dict(query).items()}


def _body(body) -> dict:
    if isinstance(body, dict):
        return body
    if not body:
        return {}
    try:
        out = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HttpError(400, "body must be JSON")
    if not isinstance(out, dict):
        raise HttpError(400, "body must be a JSON object")
    return out


def handle(method: str, path: str, query=None, body=None, app: App | None = None,
           identity: dict | None = None) -> tuple[int, str, bytes]:
    """One request: ``path`` is below the mount point (``/api/activity``, ``/``). ``query``
    is a dict or a query string; ``body`` is the raw JSON body (or a dict). Returns
    ``(status, content_type, body)``. Never raises.

    ``identity``: the caller a server found from the request's token (``{"origin":
    "ui"|"mcp"|"cli"|"agent:<name>", "actions"}``; the server's guard, or ``brb ui``'s). A write
    then acts as that caller, whatever the body's ``origin`` says (a mismatch is logged); a
    read that ``read_needs_identity`` names (a trace) is the owner's only. None
    is a call from inside this process (the tests, a host with ``api.require_token: false``):
    the body's ``origin`` is taken, as before."""
    app = app or default_app()
    try:
        if method in ("GET", "HEAD"):
            if identity is None:                     # in-process, or a host that sends none
                return _get(app, path or "/", _query(query))
            return _get(app, path or "/", _query(query), identity)
        if method == "POST":
            return _post(app, path or "/", _body(body), identity)
        return _json(405, {"error": "method not allowed"})
    except HttpError as e:
        return _json(e.code, {"error": str(e)})
    except SystemExit as e:
        return _json(400, {"error": str(e)})
    except Exception as e:                       # noqa: BLE001
        # the details go to the log once by the error's id, never to the client;
        # the answer is Kranto's error JSON: the id, the version, Send this error
        rec = rowsafe.note(e, f"{method} {_pattern(path)}", kind="response")
        from .. import __version__
        return _json(500, {"error": rowsafe.said(rec["id"]), "error_id": rec["id"],
                           "exception": rec["exception"], "version": __version__,
                           "report": f"/api/errors/{rec['id']}"})


def _pattern(path: str) -> str:
    """A path as its pattern for the error's record: its words, never an id or a name."""
    parts = [p if not p or re.fullmatch(r"[a-z][a-z_-]{0,30}", p) else "…" for p in
             (path or "/").split("?")[0].split("/")]
    return "/".join(parts)[:80]


# what the post-update self-check leaves out of the mount's reads, each with
# its reason: what reaches GitHub or another site, or runs a program, and the live feed
SELFCHECK_EXCLUDED = {
    "/api/feedback/issue": "runs gh and reaches github.com",
    "/api/stream": "the live feed: it never ends",
}


def selfcheck_paths(app: App | None = None) -> list[str]:
    """Every GET of this API the self-check reads (the server's ``/api/selfcheck/paths``, under
    ``/brb``): each route that takes nothing, never ``SELFCHECK_EXCLUDED``."""
    from .routes import ROUTES
    out = [p for method, p, _ in ROUTES if method == "GET" and isinstance(p, str)
           and p.startswith("/api/") and not p.endswith("/") and p not in SELFCHECK_EXCLUDED]
    return list(dict.fromkeys(out))


def handle_with_headers(method: str, path: str, query=None, body=None, app: App | None = None,
                        identity: dict | None = None) -> tuple[int, str, bytes, dict]:
    """``handle``, plus the response headers the host should add: the page's versioned
    scripts and styles (``static/v<version>/...``) may be cached for good; everything else
    says nothing (the host keeps ``no-store``)."""
    from .routes.static import IMMUTABLE, VERSIONED
    status, ctype, data = handle(method, path, query, body, app, identity)
    headers = {}
    if status == 200 and method in ("GET", "HEAD") and VERSIONED.fullmatch(path or ""):
        headers["cache-control"] = IMMUTABLE
    return status, ctype, data, headers


STREAM_PATH = "/api/stream"


def stream(path: str, query=None, app: App | None = None, last: str | None = None):
    """The live feed (``ui/live.py``): for ``/api/stream``, an iterator of server-sent-event
    bytes that blocks between events, for the host to write as they come; None for every
    other path (``handle`` answers those). ``last``: the ``Last-Event-ID`` a reconnecting
    page sends. When every stream place is taken, a stream that says ``busy`` and ends (the
    page polls; a 503 was an error in its console). A loopback GET like every read: it
    needs no token and carries no secret."""
    if (path or "").rstrip("/") != STREAM_PATH:
        return None
    from . import live
    q = _query(query)
    seen = q.get("last") or last
    try:
        seen = int(seen) if seen not in (None, "") else None
    except (TypeError, ValueError):
        seen = None
    try:
        return live.HUB.stream(app or default_app(), seen)
    except live.Busy as e:
        return live.busy_events(str(e))


def caller(identity: dict | None, body: dict, path: str) -> str | None:
    """The origin a write acts as: the token's (``identity``), never the body's; a body that
    claims another is logged, without any token. None: no identity (an in-process call). Only
    the page and the command line write here; an assistant acts through the server's verbs."""
    if identity is None:
        return None
    origin = str(identity.get("origin") or "")
    if not ORIGIN.fullmatch(origin):
        raise HttpError(403, "that token does not act here")
    claimed = body.get("origin")
    if claimed is not None and claimed != origin:
        log.warning("POST %s: the body says origin %r, the token is %s: acting as %s", path,
                    str(claimed)[:40], origin, origin)
    if origin not in WRITERS:
        raise HttpError(403, f"the {origin} token does not write to the page; an assistant "
                             "acts through Kranto's verbs")
    return origin


def _get(app: App, path: str, q: dict, identity: dict | None = None
         ) -> tuple[int, str, bytes]:
    return route(ROUTES, app, Req("GET", path, q, identity))


def _post(app: App, path: str, body: dict, identity: dict | None = None
          ) -> tuple[int, str, bytes]:
    origin = caller(identity, body, path)
    if origin is not None:
        body = {**body, "origin": origin}
    return route(ROUTES, app, Req("POST", path, body, identity))
