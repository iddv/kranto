"""Open in Claude Code's routes. ``POST api/term/open`` is the only route that
starts a process; it answers a one-time ticket for the terminal's WebSocket
(``/brb/term/ws/<tid>?ticket=``, served by Kranto's host: ``term.asgi``). Every POST is the
owner's: the host's guard lets no other token write anywhere but ``api/act``."""
from __future__ import annotations

from ..http import HttpError
from .base import Prefix, ok, route


def _term(app, r) -> tuple[int, str, bytes]:
    from ...term.door import DoorError
    from ...term.service import TermError
    try:
        return route(TERM_ROUTES, app, r)
    except TermError as e:
        if e.extra:
            from ..http import _json
            return _json(e.code, {"error": str(e), **e.extra})
        raise HttpError(e.code, str(e))
    except DoorError as e:
        raise HttpError(e.code, str(e))


def _tid(r) -> str:
    return str(r.data.get("tid") or "")


def _int(v, name: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HttpError(400, f"{name} must be a number")


def _list(app, r):
    from ...term import asgi
    return {**app.term.list(), "socket": asgi.served()}


def _open(app, r):
    from ...term import asgi
    if not asgi.served():
        raise HttpError(503, "Open in Claude Code needs Kranto itself (kranto up): `brb ui` "
                             "alone has no terminal.")
    q = r.data
    return app.term.open(q.get("subject"), cols=_int(q.get("cols") or 100, "cols"),
                         rows=_int(q.get("rows") or 30, "rows"))


def _harness(r) -> str:
    return str(r.data.get("harness") or "")


def _console_state(app, r):
    from ...term import asgi
    return {**app.term.console_state(), "socket": asgi.served()}


def _console_open(app, r):
    from ...term import asgi
    if not asgi.served():
        raise HttpError(503, "The console needs Kranto itself (kranto up): `brb ui` alone has no "
                             "terminal.")
    q = r.data
    return app.term.open_console(q.get("harness") or None,
                                 cols=_int(q.get("cols") or 100, "cols"),
                                 rows=_int(q.get("rows") or 30, "rows"))


TERM_ROUTES = [
    # the console: your own assistant docked in the page, one per harness
    ("GET", "/api/term/console", ok(_console_state)),
    # what it last said, for the phone's read-and-approve sheet
    ("GET", "/api/term/console/last", ok(lambda a, r: a.term.console_last(_harness(r) or None))),
    ("POST", "/api/term/console/open", ok(_console_open)),
    ("POST", "/api/term/console/new", ok(lambda a, r: a.term.console_new(_harness(r)))),
    ("POST", "/api/term/console/end", ok(lambda a, r: a.term.console_end(
        _harness(r), fresh=r.data.get("fresh") is True))),
    ("POST", "/api/term/console/resume", ok(lambda a, r: a.term.console_resume(
        _harness(r), str(r.data.get("session") or "")))),
    ("POST", "/api/term/console/here", ok(lambda a, r: a.term.console_here(
        str(r.data.get("route") or ""), str(r.data.get("title") or "")))),
    ("POST", "/api/term/console/settings", ok(lambda a, r: a.term.console_settings(r.data))),
    ("GET", ("/api/term", "/api/term/"), ok(_list)),
    ("GET", "/api/term/session", ok(lambda a, r: a.term.get(_tid(r)))),
    ("POST", "/api/term/open", ok(_open)),
    ("POST", "/api/term/end", ok(lambda a, r: a.term.end(_tid(r)))),
    ("POST", "/api/term/net", ok(lambda a, r: a.term.net(
        _tid(r), str(r.data.get("host") or ""), r.data.get("allow") is True))),
    ("POST", "/api/term/answer", ok(lambda a, r: a.term.decide(
        _tid(r), _int(r.data.get("n"), "n"), r.data.get("confirm") is True))),
    ("POST", "/api/term/outside", ok(lambda a, r: a.term.outside(_tid(r)))),
]

ROUTES = [
    ("GET", Prefix("/api/term"), _term),
    ("POST", Prefix("/api/term"), _term),
]
