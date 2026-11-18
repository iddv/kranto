"""The term door: how a session reaches Kranto, and why it can change nothing by itself.

- **The socket.** Each session has its own unix socket, ``run/api.sock``, bound into its sandbox
  at ``/run/kranto/api.sock`` (nothing else of Kranto's loopback is reachable from inside). Every
  request, GETs included, must carry the session's token (``run/token``, 0600, minted at the
  session's first start, one per session, compared in constant time). The socket is served
  while Kranto runs and the session is not ended for good, so ``kranto mcp --term <tid>`` works
  in your own terminal too (Continue outside).
- **Reads**: the session's proposals (``GET /api/proposals``), its last list
  (``GET /api/describe``), and a few of the server's own reads under ``/afk`` (``AFK_READS``: the
  idea cards, the home, Post, the topics), a GET through ``term.afk.call``; nothing else, and
  never a write.
- **Writes are proposals.** ``POST /api/act`` and ``POST /api/propose`` (what an MCP action
  tool sends) store a proposal of one of the server's verbs (``topic.add``, ``source.approve``: a
  dotted name) on the session and answer ``{"proposed": n}``; ``confirm: true`` is ignored.
  Nothing runs until the owner presses Confirm on the card in the page (``decide``), which runs
  it through the server's verbs' door as the owner (``POST /api/verbs/<kind>``); the server says
  whether the verb exists.
- **A described list**: a session about described sources (subject kind
  ``sources``) may send a list back, ``POST /api/describe {text}``, at most ``MAX_DESCRIBES``
  times; it goes to the server's resolver with the session's own topic, like a list pasted on Add
  source, and is checked and approved there (``GET /api/describe``: how it went). Nothing is
  approved by it; any other session is refused.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import socketserver
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

VERB = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")      # the server's verbs: topic.add
MAX_KIND = 80
# The server's reads a session's MCP may ask for, under /afk on the socket (GET only): the idea
# cards, one card, the home, Post, the topics. The query keys passed on; nothing else.
AFK_PREFIX = "/afk/api/"
AFK_READS = tuple(re.compile(p) for p in (r"/api/home", r"/api/post", r"/api/ideas",
                                          r"/api/ideas/\d{1,9}", r"/api/topics",
                                          r"/api/topics/\d{1,9}"))
AFK_QUERY = ("embedding", "state", "q", "limit", "kind")
MAX_BODY = 256 * 1024
MAX_PROPOSALS = 200
MAX_WHY = 2000
MAX_DESCRIBES = 5            # lists a sources session may send back (each is one model call)
MAX_DESCRIBE_TEXT = 16000    # what the server's resolver reads of one


class DoorError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# -- the token ------------------------------------------------------------------------------------
def token_path(run: Path) -> Path:
    return Path(run) / "token"


def mint(run: Path) -> str:
    """The session's token, made once (kept across restarts of the session)."""
    p = token_path(run)
    if p.is_file():
        return p.read_text().strip()
    Path(run).mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value


def revoke(run: Path) -> None:
    token_path(run).unlink(missing_ok=True)


# -- proposals ----------------------------------------------------------------------------------
def proposal(body: dict) -> dict:
    """A proposal from a session's request (``api/act``'s body or ``api/propose``'s), checked
    for shape only; the action's own checks run when the owner confirms it."""
    if not isinstance(body, dict):
        raise DoorError(400, "a JSON object")
    kind = str(body.get("kind") or "")
    if len(kind) > MAX_KIND or not VERB.match(kind):
        raise DoorError(400, f"unknown action {kind!r}: a session proposes one of Kranto's verbs "
                             "(topic.add, source.approve, ...)")
    subj, fields = body.get("subject") or {}, body.get("fields") or {}
    if not isinstance(subj, dict) or not isinstance(fields, dict):
        raise DoorError(400, "subject and fields are JSON objects")
    if len(json.dumps(fields)) > 20000:
        raise DoorError(413, "the fields are too large")
    why = str(body.get("why") or "")[:MAX_WHY]
    return {"kind": kind, "title": kind, "confirm_class": False,
            "subject": {"kind": str(subj.get("kind") or "new")[:20],
                        "id": None if subj.get("id") is None else str(subj.get("id"))[:200]},
            "fields": fields, "why": why, "status": "proposed", "result": None, "at": time.time(),
            "asked_confirm": body.get("confirm") is True}


# -- the socket ---------------------------------------------------------------------------------
class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class Door:
    """One session's socket. ``term`` answers proposals (``Term.propose``); ``app`` the reads."""

    def __init__(self, term, tid: str, sock: Path, token: str):
        self.term, self.tid, self.sock, self.token = term, tid, Path(sock), token
        self.srv: _Server | None = None

    def start(self) -> Door:
        self.sock.unlink(missing_ok=True)
        door = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                door.handle(self, "GET")

            def do_POST(self):
                door.handle(self, "POST")

        # bound through the folder's descriptor: a unix socket's path is at most 107 bytes,
        # and a session's folder may be deeper than that
        dfd = os.open(self.sock.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            self.srv = _Server(f"/proc/self/fd/{dfd}/{self.sock.name}", H)
        finally:
            os.close(dfd)
        os.chmod(self.sock, 0o600)
        threading.Thread(target=self.srv.serve_forever, daemon=True,
                         name=f"term-door-{self.tid}").start()
        return self

    def stop(self) -> None:
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
            self.srv = None
        self.sock.unlink(missing_ok=True)

    def _authorised(self, h) -> bool:
        got = h.headers.get("Authorization") or ""
        return got.startswith("Bearer ") and hmac.compare_digest(
            got[7:].strip().encode(), self.token.encode())

    def handle(self, h, method: str) -> None:
        try:
            # the body is read before any answer, refusals included: a client still sending
            # it must get the refusal, not a broken pipe
            try:
                n = int(h.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            raw = h.rfile.read(n) if 0 < n <= MAX_BODY else b""
            if not self._authorised(h):
                raise DoorError(401, "this socket needs the session's token")
            u = urllib.parse.urlsplit(h.path)
            if method == "GET":
                code, ctype, data = self.read(u.path, u.query)
                return self._send(h, code, data, ctype)
            if n > MAX_BODY:
                raise DoorError(413, "too large")
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                raise DoorError(400, "a JSON body")
            if u.path in ("/api/act", "/api/propose"):
                out = self.term.propose(self.tid, body)
            elif u.path == "/api/describe":
                out = self.term.describe(self.tid, body)
            else:
                raise DoorError(404, f"{u.path}: a terminal session reads and proposes only")
            self._send(h, 200, json.dumps(out).encode())
        except DoorError as e:
            self._send(h, e.code, json.dumps({"error": str(e)}).encode())
        except Exception as e:                         # noqa: BLE001 - said, never raised
            self._send(h, 500, json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}).encode())

    def read(self, path: str, query: str) -> tuple[int, str, bytes]:
        if path == "/api/proposals":
            return 200, "application/json", json.dumps(self.term.proposals(self.tid)).encode()
        if path == "/api/describe":
            return 200, "application/json", json.dumps(self.term.described(self.tid)).encode()
        if path.startswith(AFK_PREFIX):
            return self.afk_read(path[len("/afk"):], query)
        raise DoorError(404, f"{path}: not one of Kranto's reads for a terminal session")

    def afk_read(self, path: str, query: str) -> tuple[int, str, bytes]:
        """One of the server's own reads (``AFK_READS``), a GET through ``term.afk.call``: the
        session's MCP reads the ideas, the home, Post and the topics as the page does. Only
        these GETs: never a write, never another path (a run's calls are the owner's)."""
        from .afk import AfkError, afk_url, call
        if not any(rx.fullmatch(path) for rx in AFK_READS):
            raise DoorError(404, f"{path}: not one of the server's reads for a terminal session")
        q = [(k, v) for k, v in urllib.parse.parse_qsl(query or "")
             if k in AFK_QUERY and len(v) <= 200][:8]
        url = afk_url(self.term.app.loop_cfg())
        if not url:
            raise DoorError(503, "the server is not known here")
        try:
            out = call(url, "GET", path + ("?" + urllib.parse.urlencode(q) if q else ""),
                       timeout=15)
        except AfkError as e:
            raise DoorError(e.code if e.code in (400, 404, 409) else 502, str(e))
        return 200, "application/json", json.dumps(out).encode()

    @staticmethod
    def _send(h, code: int, data: bytes, ctype: str = "application/json") -> None:
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
