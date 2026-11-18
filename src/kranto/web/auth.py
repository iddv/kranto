"""Who is calling (OI): the token on a request decides who acts, never its body.

``GuardMiddleware`` asks ``Auth.check`` about every state-changing request after the Host and
Origin checks. The caller is the token it carries (``tokens.Store``):

- ``Authorization: Bearer <token>``: kranto mcp, the command line, a named agent;
- the session cookie (``kranto_session_<port>``, HttpOnly, SameSite=Strict): the browser. Only
  the UI's token is taken from a cookie.

With ``api.require_token`` (the default) a write without a current token is refused (401).
MCP, console and agent tokens may only run verbs (``POST /api/verbs/<kind>``, where
``core.verbs``'s ladder applies); an agent token may also post the page's ``api/act`` (the
build loop's, gone since the cut; a version of the page from before it applies the token's limits
there). An agent token's ``actions`` name verbs; a name from before (a build loop's action)
is ignored and the token still signs in. Every other write is the owner's (the UI or the
command line). Most reads stay open on loopback: the page draws before it is signed in,
``kranto status`` and the update's health check read without a token, and nothing such a read
returns is a secret. Two kinds of read are checked as a write is (``check_read``): the owner's
reads (a trace, the runs, what the browser read, what the console's assistant said), and the
reads that do something (``SIGNED_READS``: a live web search and a page fetch, which any
current token may make); a browser makes them only from Kranto's own page, never from another
site or another port of this machine. A ``browser:<name>`` token (the browser extension's) may
write ``POST /api/browser/captures`` and nothing
else, and no other token may write there.

**Signing a browser in.** The page is served to anyone on loopback and never sets the cookie,
so fetching the HTML hands out nothing. ``kranto open`` (and ``kranto up``) prints a link with a
one-time code that expires in 10 minutes: ``/auth/open?code=…`` sets the cookie and goes to
the page; the page's sign-in box takes the same code (``POST /auth/code``).
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .. import legacy
from .. import tokens as tokens_mod

log = logging.getLogger(__name__)

IDENTITY = "kranto.identity"      # the request scope's key: the caller, once checked
OWNER = ("ui", "cli")            # may write anywhere
ACT_PATHS = ("/brb/api/act",)    # all an mcp, console or agent token may write, with
VERB_PREFIX = "/api/verbs/"      # the server's verbs (core.verbs: the ladder applies there)
ASSISTANT_DOORS = ("mcp", "console")   # their build-loop actions go through the verbs too
# writes that need no token: they are how a browser gets one (the page's sign-in box, and the
# browser extension's pairing; each still needs its one-time code)
PAIR_PATH = "/api/browser/pair"
SIGNIN_PATHS = ("/auth/code", PAIR_PATH)
# all a browser:<name> token may write: the pages its extension read
BROWSER_PATHS = ("/api/browser/captures",)
BROWSER_PREFIX = "browser:"
# reads that carry file contents and prompts: a build's agent trace (the page decision
# D-4; the page's api.read_needs_identity says the same of its own paths), and the runs whose
# model calls a trace of the analyst or a cub is made of
# and the pages the owner read in their browser, with their text (the capture log), and what
# the console's assistant last said (the phone's read-and-approve sheet)
OWNER_READS = ("/brb/api/traces", "/brb/api/trace", "/api/runs", "/api/browser/captures",
               "/brb/api/term/console/last")
# reads that do something: a live web search (it costs what the search backend charges) and a
# fetch of a page from this machine. Any current token may make them (the page, the command
# line, kranto mcp's kranto_search and kranto_fetch, an agent); nobody signed out may
SIGNED_READS = ("/api/websearch", "/api/websearch/fetch")
# what a browser's Sec-Fetch-Site may say on a signed read: from this page, or typed in the
# address bar; "same-site" is another port of this machine, which the cookie would ride
OWN_FETCH_SITES = ("same-origin", "none")
COOKIE_MAX_AGE = 400 * 86400     # the longest browsers keep a cookie
SIGNIN_HINT = ("run 'kranto open' on the machine Kranto runs on and open the link it prints, "
               "or paste its code into the page")
# a browser's refusal, in the words a stranger reads (no token, no Bearer: those are a script's)
BROWSER_SIGNED_OUT = ("This browser is not signed in: run `kranto open` on the machine Kranto "
                      "runs on, and open the link it prints or paste its code into the page.")
BROWSER_STALE = ("This browser is not signed in any more (its sign-in was renewed): run "
                 "`kranto open` on the machine Kranto runs on, and open the link it prints or "
                 "paste its code into the page.")


def _signed_out_words(request: Request, why: str | None, what: str = "") -> str:
    """Why a request with no current sign-in was refused: a browser (no ``Authorization``
    header) is told in a stranger's words; a script that sent a bearer token gets the
    technical reason and how agents sign in."""
    if (request.headers.get("authorization") or "")[:7].lower() != "bearer ":
        words = BROWSER_STALE if why and "cookie" in why else BROWSER_SIGNED_OUT
        return f"{what} {words}".strip() if what else words
    lead = f"not signed in: {why}."
    return (f"{lead} {what} Scripts and agents send 'Authorization: Bearer' with their own "
            "token (kranto token add agent:<name>).").replace("  ", " ")


def _json(status: int, error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


def old_cookie_name(port: int | None = None) -> str:
    """The session cookie's name before the rename (``legacy.COOKIE``), with the same port
    suffix as ``tokens.cookie_name``: still accepted when the new one is absent."""
    return f"{legacy.COOKIE}_{int(port)}" if port else legacy.COOKIE


def is_owner(identity: dict | None) -> bool:
    return bool(identity) and identity.get("origin") in OWNER


class Auth:
    def __init__(self, store: tokens_mod.Store, require: bool = True, port: int | None = None):
        self.store, self.require, self.port = store, require, port
        self.cookie = tokens_mod.cookie_name(port)
        # a browser signed in before the rename carries the old name until it expires; new
        # sign-ins set only the new one
        self.old_cookie = old_cookie_name(port)
        self.last_used: dict[str, float] = {}

    # -- who is calling --------------------------------------------------------------------
    def identify(self, request: Request) -> tuple[dict | None, str | None]:
        """``(identity, why not)``: the caller, or None with why (no token, not current)."""
        authz = request.headers.get("authorization") or ""
        if authz[:7].lower() == "bearer ":
            ident = self.store.identify(authz[7:].strip())
            return ({**ident, "via": "bearer"}, None) if ident else \
                (None, "its bearer token is not a current kranto token")
        value = request.cookies.get(self.cookie) or request.cookies.get(self.old_cookie)
        if value:
            ident = self.store.identify(value)
            if ident and ident["origin"] == "ui":
                return {**ident, "via": "cookie"}, None
            return None, "its session cookie is not current (the UI's token was rotated)"
        return None, "it carries no kranto token"

    def check(self, request: Request) -> Response | None:
        """None when this write may go on (the caller in ``scope[IDENTITY]``), else the
        refusal."""
        path = request.url.path
        if path in SIGNIN_PATHS:
            return None
        ident, why = self.identify(request)
        request.scope[IDENTITY] = ident
        if ident is None:
            if not self.require:
                return None                      # api.require_token: false, the old way
            log.warning("refused %s %s: %s", request.method, path, why)
            return _json(401, _signed_out_words(request, why))
        self.last_used[ident["origin"]] = time.time()
        if str(ident.get("origin") or "").startswith(BROWSER_PREFIX):
            if path in BROWSER_PATHS and request.method == "POST":
                return None
            log.warning("refused %s %s: a browser token only sends captures", request.method,
                        path)
            return _json(403, f"the {ident['origin']} token only sends what its browser read "
                              f"(POST {BROWSER_PATHS[0]}); this is the owner's")
        if path in BROWSER_PATHS:
            return _json(403, "captures come from a paired browser's extension, with its own "
                              "token (Settings › Browser)")
        if not is_owner(ident) and path not in ACT_PATHS and not (
                path.startswith(VERB_PREFIX) and request.method == "POST"):
            log.warning("refused %s %s: an %s token only runs actions", request.method, path,
                        ident["origin"])
            return _json(403, f"the {ident['origin']} token only runs actions (POST "
                              "/brb/api/act, POST /api/verbs/<kind>); this is the owner's")
        if ident["origin"] in ASSISTANT_DOORS and path in ACT_PATHS:
            # an assistant acts through the verbs' door, where the owner's ladder decides;
            # never around it through the page's api/act (the build loop's, gone since the
            # cut: a version of the page from before it still answers there)
            log.warning("refused %s %s: an %s token runs verbs", request.method, path,
                        ident["origin"])
            return _json(403, f"the {ident['origin']} token runs Kranto's verbs: POST "
                              "/api/verbs/<kind> (kranto mcp does this; update it)")
        return None

    @staticmethod
    def owner_read(path: str) -> bool:
        """A GET that is the owner's only (a trace), unlike every other read."""
        p = (path or "").rstrip("/")
        return p in OWNER_READS or p.startswith(("/brb/api/trace/", "/api/runs/"))

    @staticmethod
    def signed_read(path: str) -> bool:
        """A GET that does something (a live search, a fetch): any current token, never
        signed out."""
        return (path or "").rstrip("/") in SIGNED_READS

    def guarded_read(self, path: str) -> bool:
        """A GET the guard checks as it checks a write (``check_read``)."""
        return self.owner_read(path) or self.signed_read(path)

    @staticmethod
    def from_elsewhere(request: Request) -> bool:
        """Whether a browser says this read comes from another page than Kranto's own: its
        ``Sec-Fetch-Site`` is not same-origin (another port of this machine is "same-site",
        and the SameSite cookie rides it), or its ``Origin``/``Referer`` names another host.
        A client that sends none of the three (the command line, a script) is not a page."""
        site = (request.headers.get("sec-fetch-site") or "").lower()
        if site and site not in OWN_FETCH_SITES:
            return True
        host = (request.headers.get("host") or "").lower()
        return any(came and urlparse(came).netloc.lower() != host
                   for came in (request.headers.get("origin"), request.headers.get("referer")))

    @staticmethod
    def _read_words(path: str) -> tuple[str, str]:
        """What a guarded read is, in the refusal's words: (as a sentence's start, inside)."""
        p = (path or "").rstrip("/")
        if p.startswith("/api/browser/"):
            return "What your browser read", "what your browser read"
        if p in SIGNED_READS:
            return "A web search or a page fetch", "a web search or a page fetch"
        if p.startswith("/brb/api/term/"):
            return "What the console's assistant said", "what the console's assistant said"
        return "A trace", "a trace"

    def check_read(self, request: Request) -> Response | None:
        """None when this guarded read may go on (the caller in ``scope[IDENTITY]``), else
        the refusal: 403 from another site's page, 401 without a token (when tokens are
        required), 403 for one that may not make it (an agent's or MCP's on an owner's read,
        a browser extension's anywhere)."""
        path = request.url.path
        ident, why = self.identify(request)
        request.scope[IDENTITY] = ident
        lead, inside = self._read_words(path)
        if (ident or {}).get("via") != "bearer" and self.from_elsewhere(request):
            # a bearer token is never sent by a browser on its own; a cookie is
            log.warning("refused %s %s: from another site's page", request.method, path)
            return _json(403, f"cross-origin request refused: {inside} is made from Kranto's "
                              "own page")
        if ident is None:
            if not self.require:
                return None
            log.warning("refused %s %s: %s", request.method, path, why)
            verb = "made" if self.signed_read(path) else "read"
            return _json(401, _signed_out_words(request, why, f"{lead} is {verb} signed in."))
        self.last_used[ident["origin"]] = time.time()
        origin = str(ident.get("origin") or "")
        if self.signed_read(path) and not origin.startswith(BROWSER_PREFIX):
            return None
        if not is_owner(ident):
            log.warning("refused %s %s: an %s token may not read it", request.method, path,
                        origin)
            if self.signed_read(path):
                return _json(403, f"the {origin} token only sends what its browser read; "
                                  f"{inside} is not its to make")
            return _json(403, f"{inside} is the owner's to read; the {origin} token does not "
                              "read it")
        return None

    # -- signing in ------------------------------------------------------------------------
    def _signed_in(self, response: Response, value: str) -> Response:
        response.set_cookie(self.cookie, value, max_age=COOKIE_MAX_AGE, path="/",
                            httponly=True, samesite="strict")
        return response

    async def open_link(self, request: Request):
        """``GET /auth/open?code=…[&next=/#/…]``: the link ``kranto open`` prints."""
        value = await run_in_threadpool(self.store.redeem, request.query_params.get("code"))
        if not value:
            return HTMLResponse(
                "<!doctype html><title>Kranto</title><p>This sign-in link has expired or was "
                "used already. Run <code>kranto open</code> again and open the new link.</p>",
                status_code=400)
        nxt = request.query_params.get("next") or "/"
        if not re.fullmatch(r"/(?!/)[\w./#?=&%-]{0,300}", nxt):
            nxt = "/"
        log.info("a browser signed in with a one-time code")
        return self._signed_in(RedirectResponse(nxt, status_code=303), value)

    async def code(self, request: Request):
        """``POST /auth/code {code}``: the page's sign-in box."""
        try:
            body = await request.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        value = await run_in_threadpool(self.store.redeem, str(code or "").strip())
        if not value:
            return _json(400, "that code has expired or was used already: run 'kranto open' "
                              "again")
        log.info("a browser signed in with a one-time code")
        return self._signed_in(JSONResponse({"ok": True, "origin": "ui"}), value)

    async def signout(self, request: Request):
        response = JSONResponse({"ok": True})
        response.delete_cookie(self.cookie, path="/")
        if request.cookies.get(self.old_cookie):
            response.delete_cookie(self.old_cookie, path="/")
        return response

    def whoami(self, request: Request):
        """``GET /api/whoami``: who this request is, and whether writes need a token."""
        ident, _ = self.identify(request)
        return JSONResponse({"origin": (ident or {}).get("origin"),
                             "via": (ident or {}).get("via"),
                             "require_token": self.require,
                             "signin": "kranto open"})

    # -- the tokens (Settings › Privacy & access; kranto token) --------------------------------
    def _rows(self) -> list[dict]:
        """Every token, its ``actions`` read against the verbs' table: a name that is no verb
        (a build loop's action, from before the cut) is left out of ``actions`` and listed in
        ``ignored``; the file is never rewritten and the token still signs in."""
        out = []
        for t in self.store.list():
            kept, ignored = known_actions(t.get("actions"))
            out.append({**t, "actions": kept, "ignored": ignored,
                        "last_used": self.last_used.get(t["name"])})
        return out

    def list_tokens(self, request: Request):
        return JSONResponse({"tokens": self._rows(), "require_token": self.require,
                             "default_actions": default_agent_actions()})

    def _owner(self, request: Request) -> Response | None:
        if self.require and not is_owner(request.scope.get(IDENTITY)):
            return _json(403, "only the owner manages tokens")
        return None

    async def add_token(self, request: Request):
        if (refused := self._owner(request)) is not None:
            return refused
        body = await _body(request)
        name = str(body.get("name") or "").strip()
        if name and ":" not in name:
            name = "agent:" + name
        try:
            actions = check_actions(body.get("actions"))
            path = self.store.add(name, actions, str(body.get("note") or ""))
        except tokens_mod.TokenError as exc:
            return _json(400, str(exc))
        log.info("token added: %s", name)
        return JSONResponse({"name": name, "file": str(path), "tokens": self._rows()})

    async def change_token(self, request: Request):
        if (refused := self._owner(request)) is not None:
            return refused
        name, what = request.path_params["name"], request.path_params["what"]
        try:
            if what == "revoke":
                if not self.store.revoke(name):
                    return _json(404, f"no token {name}")
            elif what == "rotate":
                self.store.rotate(name)
            elif what == "actions":
                body = await _body(request)
                self.store.set_actions(name, check_actions(body.get("actions")))
            else:
                return _json(404, "not found")
        except tokens_mod.TokenError as exc:
            return _json(400, str(exc))
        log.info("token %s: %s", what, name)
        response = JSONResponse({"ok": True, "tokens": self._rows()})
        if what == "rotate" and name == "ui" and \
                (request.scope.get(IDENTITY) or {}).get("via") == "cookie":
            self._signed_in(response, self.store.value("ui") or "")   # this browser stays in
        return response

    def routes(self) -> list[Route]:
        return [Route("/auth/open", self.open_link),
                Route("/auth/code", self.code, methods=["POST"]),
                Route("/auth/signout", self.signout, methods=["POST"]),
                Route("/api/whoami", self.whoami),
                Route("/api/tokens", self.list_tokens),
                Route("/api/tokens", self.add_token, methods=["POST"]),
                Route("/api/tokens/{name}/{what}", self.change_token, methods=["POST"])]


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


ACTION_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,79}")


def _verb_kinds(door: str | None = None) -> list[str]:
    """The verbs' own table (``core.verbs``): every verb's kind, or those open to ``door``."""
    from ..core import verbs
    return [v.kind for v in verbs.all_verbs() if door is None or door in v.doors]


def default_agent_actions() -> list[str]:
    """What an agent token may run when its ``actions`` is null: every verb an agent's door
    takes, from the verbs' own table (the ladder still decides each press)."""
    return _verb_kinds("agent")


def known_actions(stored) -> tuple[list[str] | None, list[str]]:
    """A token file's ``actions`` as read now: ``(the verbs it names, the names ignored)``.
    Never assumes the stored shape: null stays null (the default); a list keeps its verbs and
    ignores anything else (an old build loop action such as ``publish`` or ``b.retry``, a
    number); any other value reads as null."""
    if not isinstance(stored, list):
        return None, []
    known = set(_verb_kinds())
    kept = [x for x in stored if isinstance(x, str) and x in known]
    return list(dict.fromkeys(kept)), [str(x) for x in stored
                                       if not (isinstance(x, str) and x in known)]


def check_actions(raw) -> list[str] | None:
    """An agent's actions from a request: null (the default) or a list of verbs' kinds."""
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(x, str) and ACTION_NAME.fullmatch(x)
                                            for x in raw):
        raise tokens_mod.TokenError("actions is null (the default) or a list of verbs' kinds")
    known = set(_verb_kinds())
    bad = [x for x in raw if x not in known]
    if bad:
        raise tokens_mod.TokenError(f"no such verb: {', '.join(bad)}")
    return list(dict.fromkeys(raw))
