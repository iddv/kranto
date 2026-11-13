"""Agent traces' routes: read-only, every string redacted on read.

A trace holds file contents and prompts, so its reads are the owner's (decision D-4): the host
identifies a GET on these paths as it does a POST (``read_needs_identity``) and answers 401
without one; here a token that is not the owner's (an agent's, MCP's, a build's own) is
refused. ``who`` None is a call from inside the process (the tests, a host with
``api.require_token: false``)."""
from __future__ import annotations

from ..http import HttpError
from .base import ok, route

OWNER = ("ui", "cli")
PATHS = ("/api/traces", "/api/trace")


def read_needs_identity(path: str) -> bool:
    """A GET the host must identify (and refuse without a token, when tokens are required)."""
    p = (path or "").rstrip("/")
    return p in PATHS or p.startswith("/api/trace/")


def _owner(r) -> None:
    if r.who is not None and (r.who or {}).get("origin") not in OWNER:
        raise HttpError(403, "a trace is the owner's to read: the page signed in, or the "
                             "command line")


def _svc(app):
    from ...trace.service import for_app
    return for_app(app)


def _int(v, name: str, default: int | None = None) -> int | None:
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HttpError(400, f"{name} must be a number")


def _since(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise HttpError(400, "since must be a time in seconds")


def _tid(r) -> str:
    t = str(r.data.get("trace") or "")
    if not t:
        raise HttpError(400, "trace is required (session:<tid>, afk:<uuid>)")
    return t


def _span(r) -> str:
    s = str(r.data.get("span") or "")
    if not s:
        raise HttpError(400, "span is required")
    return s


def _trace(app, r) -> tuple[int, str, bytes]:
    from ...trace.service import TraceError
    _owner(r)
    try:
        return route(TRACE_ROUTES, app, r)
    except TraceError as e:
        raise HttpError(e.code, str(e))


def _list(app, r):
    q = r.data
    return _svc(app).list(source=q.get("source") or None, key=q.get("key") or None,
                          state=q.get("state") or None, since=_since(q.get("since")),
                          limit=_int(q.get("limit"), "limit", 50), after=q.get("after"))


def _spans(app, r):
    q = r.data
    return _svc(app).spans(_tid(r), after=q.get("after") or None,
                           limit=_int(q.get("limit"), "limit"), parent=q.get("parent") or None,
                           filter=q.get("filter") or None, q=q.get("q") or None,
                           payloads=str(q.get("payloads") or "") in ("1", "true"))


def _payload(app, r):
    q = r.data
    return _svc(app).payload(_tid(r), _span(r), str(q.get("part") or "output"),
                             _int(q.get("offset"), "offset", 0))


def _download(app, r):
    import json
    body = _svc(app).download(_tid(r))
    data = json.dumps(body, ensure_ascii=False, indent=1).encode()
    return 200, "application/json; charset=utf-8", data


TRACE_ROUTES = [
    ("GET", ("/api/traces", "/api/traces/"), ok(_list)),
    ("GET", ("/api/trace", "/api/trace/"), ok(lambda a, r: _svc(a).summary(_tid(r)))),
    ("GET", "/api/trace/spans", ok(_spans)),
    ("GET", "/api/trace/span", ok(lambda a, r: _svc(a).span(_tid(r), _span(r)))),
    ("GET", "/api/trace/search", ok(lambda a, r: _svc(a).search(_tid(r), str(r.data.get("q") or "")))),
    ("GET", "/api/trace/payload", ok(_payload)),
    ("GET", "/api/trace/download", _download),
    ("GET", "/api/trace/follow", ok(lambda a, r: _svc(a).follow(_tid(r)))),
]

ROUTES = [
    ("GET", read_needs_identity, _trace),
]
