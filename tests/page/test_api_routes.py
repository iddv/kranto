"""Characterisation of ``api.handle``'s routing: every route, GET and POST,
driven on the fake app, with what it answers: the status, the content type and the shape (a
JSON object's top-level keys, or its error text). The snapshot in
``fixtures/api_routes.json`` pins today's matching order, so moving the ``if`` chains into a
route table (and the handlers into modules) can't send a request somewhere else.

``KRANTO_SNAPSHOT=write pytest tests/page/test_api_routes.py`` rewrites the snapshot: only for a
change that means to move a route, and the diff says which.
"""
import json
import os
import re
from pathlib import Path

import pytest

from kranto.page.ui import api

from .app_common import make_home

SNAPSHOT = Path(__file__).parent / "fixtures" / "api_routes.json"

# The page's own routes (ui/routes/__init__.py), and a sample of the factory's, which answer 404
# since the cut (cut 3)
GET = [
    "/", "/index.html", "/static/theme.js", "/static/kranto.css", "/static/brand/favicon-16.png",
    "/static/nope.js", "/static/../api.py", "/static/", "/help",
    "/api/activity", "/api/details", "/api/header",
    "/api/feedback/issue",
    "/api/term", "/api/term/session?tid=deadbeef", "/api/term/session", "/api/term/console",
    "/api/term/patch?tid=x&n=1",
    "/api/traces", "/api/traces?limit=x", "/api/traces?source=build", "/api/traces?source=nope",
    "/api/trace", "/api/trace?trace=build:nope/1", "/api/trace?trace=session:deadbeef",
    "/api/trace?trace=nope", "/api/trace/spans?trace=build:nope/1", "/api/trace/spans",
    "/api/trace/span?trace=build:nope/1", "/api/trace/payload?trace=build:nope/1&span=x",
    "/api/trace/download", "/api/trace/compare?a=x&b=y", "/api/trace/nope", "/api/tracer",
    # gone with the factory
    "/classic", "/loop", "/loop/feed.xml", "/history", "/api/kranto", "/api/loop",
    "/api/loop/settings", "/api/models", "/api/spend/breakdown", "/api/prompts",
    "/api/capabilities", "/api/extensions", "/api/plugins", "/api/maintain/summary",
    "/api/projects", "/api/project?id=nope", "/api/changes", "/api/actions", "/api/outcomes",
    "/api/build?dir=nope", "/api/builds", "/api/run", "/api/events", "/api/text", "/api/info",
    "/api/chat", "/api/github/app", "/api/claude/login", "/api/nothing", "/nothing", "",
]

POST = [
    ("/api/activity/stop", {}), ("/api/term/settings", {}),
    ("/api/term/settings", {"key": "loop.paused", "value": True}),
    ("/api/feedback/issue", {}), ("/api/term/open", {}), ("/api/term/end", {}),
    ("/api/term/answer", {"tid": "deadbeef", "n": "x"}),
    # gone with the factory
    ("/api/act", {}), ("/api/act", {"kind": "nope"}), ("/api/loop/add", {}), ("/api/new", {}),
    ("/api/start", {"dir": "nope"}), ("/api/stop", {"dir": "nope"}), ("/api/models", {}),
    ("/api/prompts", {}), ("/api/spend", {"daily_usd": "x"}), ("/api/maintain/act", {}),
    ("/api/github/app", {}), ("/api/chat/send", {}), ("/api/nothing", {}), ("/nothing", {}),
]

# a token's caller: the owner's doors write anywhere; mcp and agents only run actions
AS = [("/api/term/settings", {}, {"origin": "mcp"}),
      ("/api/act", {"kind": "nope"}, {"origin": "agent:helper"}),
      ("/api/nothing", {}, {"origin": "ui"})]

OTHER = [("PUT", "/"), ("DELETE", "/api/act"), ("HEAD", "/api/header"), ("HEAD", "/nothing")]


@pytest.fixture
def app(tmp_path):
    cfg = make_home(tmp_path)
    yield api.App(None, "fake", cfg.home)


def shape(code: int, ctype: str, data: bytes, tmp: str) -> list:
    kind = ctype.split(";")[0]
    out: list = [code, kind]
    if kind == "application/json":
        body = json.loads(data)
        if isinstance(body, dict) and set(body) == {"error"}:
            out.append("error: " + re.sub(r"\S*" + re.escape(tmp) + r"\S*", "<tmp>",
                                          str(body["error"]))[:160])
        elif isinstance(body, dict):
            out.append(sorted(body))
        else:
            out.append(type(body).__name__)
    return out


def snapshot(app, tmp: str) -> dict:
    seen = {}
    for path in GET:
        p, _, q = path.partition("?")
        seen[f"GET {path}"] = shape(*api.handle("GET", p, q or None, None, app=app), tmp)
    for path, body in POST:
        key = f"POST {path} {json.dumps(body, sort_keys=True)}"
        seen[key] = shape(*api.handle("POST", path, None, json.dumps(body).encode(), app=app),
                          tmp)
    for path, body, who in AS:
        key = f"POST {path} {json.dumps(body, sort_keys=True)} as {who['origin']}"
        seen[key] = shape(*api.handle("POST", path, None, json.dumps(body).encode(), app=app,
                                      identity=who), tmp)
    for who in ({"origin": "agent:helper"}, {"origin": "mcp"}, {"origin": "ui"}):
        seen[f"GET /api/traces as {who['origin']}"] = shape(
            *api.handle("GET", "/api/traces", None, None, app=app, identity=who), tmp)
    for method, path in OTHER:
        seen[f"{method} {path}"] = shape(*api.handle(method, path, None, None, app=app), tmp)
    seen["POST /api/act (not JSON)"] = shape(*api.handle("POST", "/api/act", None, b"{", app=app),
                                             tmp)
    seen["POST /api/act (a list)"] = shape(*api.handle("POST", "/api/act", None, b"[]", app=app),
                                           tmp)
    return seen


def test_every_route_answers_as_it_did(app, tmp_path):
    got = snapshot(app, str(tmp_path))
    if os.environ.get("KRANTO_SNAPSHOT") == "write":
        SNAPSHOT.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n")
    want = json.loads(SNAPSHOT.read_text())
    assert list(got) == list(want), "the requests changed: rewrite the snapshot"
    moved = {k: (want[k], got[k]) for k in want if want[k] != got[k]}
    assert not moved, json.dumps(moved, indent=1, ensure_ascii=False)


def test_a_500_says_little_and_logs_the_rest(app, monkeypatch, caplog):
    """An unexpected error answers Kranto's error JSON: its id, its type, the version
    and the report's address; the message (a path, a command line) goes to the server's log,
    once for the id however often it happens."""
    import logging

    from kranto.page import __version__, rowsafe

    monkeypatch.setattr(rowsafe, "_seen", {})
    from kranto import rowsafe as server_rowsafe  # the page's logs through the server's
    monkeypatch.setattr(server_rowsafe, "_seen", {}, raising=False)

    def boom():
        raise RuntimeError("git failed in /home/someone/private/repo")
    monkeypatch.setattr(app, "header", boom)
    with caplog.at_level(logging.ERROR):
        answers = [api.handle("GET", "/api/header", app=app) for _ in range(3)]
    for code, ctype, data in answers:
        assert code == 500 and ctype.startswith("application/json")
        body = json.loads(data)
        assert body["exception"] == "RuntimeError" and body["version"] == __version__
        assert f"(error {body['error_id']})" in body["error"] and "/home/someone" not in data.decode()
        assert body["report"] == f"/api/errors/{body['error_id']}"
    assert len({json.loads(d)["error_id"] for _, _, d in answers}) == 1
    logged = [r for r in caplog.records if "/home/someone/private" in r.getMessage()
              or (r.exc_info and "/home/someone/private" in str(r.exc_info[1]))]
    assert len(logged) == 1 and "GET /api/header" in logged[0].getMessage()
