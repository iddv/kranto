"""Who is calling (OI): the token on a request decides who acts, never its body.

``GuardMiddleware`` asks ``Auth.check`` about every state-changing request after the Host and
Origin checks. The caller is the token it carries (``tokens.Store``):

- ``Authorization: Bearer <token>``: kranto mcp, the command line, a named agent;
- the session cookie (``kranto_session_<port>``, HttpOnly, SameSite=Strict): the browser. Only
  the UI's token is taken from a cookie.

With ``api.require_token`` (the default) a write without a current token is refused (401).
MCP, console and agent tokens may only run verbs (``POST /api/verbs/<kind>``, where
``core.verbs``'s ladder applies); an agent token may also post the page's ``api/act`` (the
build loop's, gone since the cut; a the page from before it applies the token's limits
there). An agent token's ``actions`` name verbs; a name from before (a build loop's action)
is ignored and the token still signs in. Every other write is the owner's (the UI or the
command line). Reads stay open
on loopback: the page draws before it is signed in, ``kranto status`` and the update's health
check read without a token, and nothing a read returns is a secret. A ``browser:<name>``
token (the browser extension's,) may write ``POST /api/browser/captures`` and nothing
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

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

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
# and the pages the owner read in their browser, with their text (the capture log)
OWNER_READS = ("/brb/api/traces", "/brb/api/trace", "/api/runs", "/api/browser/captures")
COOKIE_MAX_AGE = 400 * 86400     # the longest browsers keep a cookie
SIGNIN_HINT = ("run 'kranto open' on the machine Kranto runs on and open the link it prints, "
               "or paste its code into the page")


def _json(status: int, error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status)


def is_owner(identity: dict | None) -> bool:
    return bool(identity) and identity.get("origin") in OWNER


class Auth:
    def __init__(self, store: tokens_mod.Store, require: bool = True, port: int | None = None):
        self.store, self.require, self.port = store, require, port
        self.cookie = tokens_mod.cookie_name(port)
        self.last_used: dict[str, float] = {}

    # -- who is calling --------------------------------------------------------------------
    def identify(self, request: Request) -> tuple[dict | None, str | None]:
        """``(identity, why not)``: the caller, or None with why (no token, not current)."""
        authz = request.headers.get("authorization") or ""
        if authz[:7].lower() == "bearer ":
            ident = self.store.identify(authz[7:].strip())
            return ({**ident, "via": "bearer"}, None) if ident else \
                (None, "its bearer token is not a current kranto token")
        value = request.cookies.get(self.cookie)
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
            return _json(401, f"not signed in: {why}. In a browser, {SIGNIN_HINT}. Scripts "
                              "and agents send 'Authorization: Bearer' with their own token "
                              "(kranto token add agent:<name>).")
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
            # cut: a the page from before it still answers there)
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

    def check_read(self, request: Request) -> Response | None:
        """None when this owner-only read may go on (the caller in ``scope[IDENTITY]``), else
        the refusal: 401 without a token (when tokens are required), 403 for one that is not
        the owner's (an agent's, MCP's)."""
        ident, why = self.identify(request)
        request.scope[IDENTITY] = ident
        # what is read, in the refusal's words: a trace, or the pages your browser read
        mine = request.url.path.startswith("/api/browser/")
        what = "What your browser read" if mine else "A trace"
        if ident is None:
            if not self.require:
                return None
            log.warning("refused %s %s: %s", request.method, request.url.path, why)
            return _json(401, f"not signed in: {why}. {what} is read signed in: in a "
                              f"browser, {SIGNIN_HINT}.")
        self.last_used[ident["origin"]] = time.time()
        if not is_owner(ident):
            log.warning("refused %s %s: an %s token reads no trace", request.method,
                        request.url.path, ident["origin"])
            return _json(403, f"{'what your browser read' if mine else 'a trace'} is the "
                              f"owner's to read; the {ident['origin']} token does not read it")
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
