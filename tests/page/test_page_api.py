"""The page's own server after the factory left (cut 3): ``POST api/term/settings``
writes the console's settings (``term.…``) and nothing else, ``api/header`` answers zeros for a
host that still reads it, every route of the factory answers 404, and only the page's and the
command line's tokens write here (an assistant acts through the server's verbs)."""
import json

import pytest
import yaml

from kranto.page.ui import api

from .app_common import make_home

UI = {"origin": "ui", "name": "ui", "actions": None}
CLI = {"origin": "cli", "name": "cli", "actions": None}
MCP = {"origin": "mcp", "name": "mcp", "actions": None}
AGENT = {"origin": "agent:RC", "name": "RC", "actions": None}


@pytest.fixture
def app(tmp_path):
    cfg = make_home(tmp_path)
    return api.App(None, "fake", cfg.home)


def call(app, method, path, body=None, who=None):
    code, _, data = api.handle(method, path, None,
                               json.dumps(body).encode() if body is not None else None,
                               app=app, identity=who)
    return code, json.loads(data) if data[:1] in (b"{", b"[") else data


def saved(app) -> dict:
    return yaml.safe_load((app.loop_cfg().home / "loop.yaml").read_text()) or {}


def test_term_settings_writes_a_console_key(app):
    code, out = call(app, "POST", "/api/term/settings",
                     {"key": "term.allow_api_key", "value": True}, UI)
    assert code == 200 and out == {"ok": True, "key": "term.allow_api_key", "value": True}
    assert saved(app)["term"]["allow_api_key"] is True
    code, out = call(app, "POST", "/api/term/settings",
                     {"key": "term.allow_api_key", "clear": True}, CLI)
    assert code == 200 and out["value"] is None
    assert "allow_api_key" not in (saved(app).get("term") or {})


@pytest.mark.parametrize("body", [
    {"key": "build.policy", "value": "v5", "confirm": True},
    {"key": "build.allow_api_key", "value": True, "confirm": True},
    {"key": "concurrency", "value": 2},
    {"key": "maintain.enabled", "value": False},
    {"key": "term.no_such_key", "value": 1},
    {"key": "", "value": 1},
])
def test_term_settings_refuses_every_other_key(app, body):
    before = (app.loop_cfg().home / "loop.yaml").read_text()
    code, out = call(app, "POST", "/api/term/settings", body, UI)
    assert code == 400 and "error" in out
    assert (app.loop_cfg().home / "loop.yaml").read_text() == before


def test_term_settings_checks_the_value(app):
    code, out = call(app, "POST", "/api/term/settings",
                     {"key": "term.allow_api_key", "value": "yes"}, UI)
    assert code == 400 and "true or false" in out["error"]
    assert "term" not in saved(app)


def test_the_header_answers_zeros(app):
    code, out = call(app, "GET", "/api/header")
    assert code == 200
    assert out == {"api_version": api.API_VERSION, "paused": False, "running": 0, "queued": 0,
                   "revising": 0, "needs_you": 0, "open_ideas": 0, "onboarding": []}


REMOVED = ["/api/kranto", "/api/loop", "/api/loop/settings", "/api/act", "/api/actions",
           "/api/maintain/summary", "/api/projects", "/api/build", "/api/builds", "/api/prompts",
           "/api/spend/breakdown", "/api/claude/login", "/api/capabilities", "/api/outcomes",
           "/api/models", "/api/trace/compare", "/loop/feed.xml"]


@pytest.mark.parametrize("path", REMOVED)
def test_every_removed_route_answers_404(app, path):
    assert call(app, "GET", path)[0] == 404
    assert call(app, "POST", path, {}, UI)[0] == 404


@pytest.mark.parametrize("who", [MCP, AGENT])
def test_an_assistants_token_cannot_write_to_the_page(app, who):
    code, out = call(app, "POST", "/api/term/settings",
                     {"key": "term.allow_api_key", "value": True}, who)
    assert code == 403 and "does not write" in out["error"]
    assert "term" not in saved(app)
    assert call(app, "POST", "/api/activity/stop", {"id": "session:x"}, who)[0] == 403


@pytest.mark.parametrize("who", [UI, CLI])
def test_the_page_and_the_command_line_write(app, who):
    code, _ = call(app, "POST", "/api/term/settings",
                   {"key": "term.daily_usd", "value": 2}, who)
    assert code == 200 and saved(app)["term"]["daily_usd"] == 2.0


def test_a_token_of_no_known_origin_is_refused(app):
    code, out = call(app, "POST", "/api/term/settings",
                     {"key": "term.daily_usd", "value": 2}, {"origin": "evil one"})
    assert code == 403
