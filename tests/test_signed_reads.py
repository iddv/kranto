"""Reads that do something, or show what is the owner's, need a sign-in and come from Kranto's
own page; a mode of usage reports that sends is chosen by a person, never by a token.

- A live web search (it costs what the backend charges) and a page fetch from this machine:
  any current token, never signed out, never from another site or another port.
- What the console's assistant last said, and an observation's raw model answer: the owner's.
- ``POST /api/settings/telemetry`` with ``basic`` or ``detailed``: the page's cookie only.
"""

from __future__ import annotations

from kranto import config as config_mod
from kranto import telemetry, tokens
from kranto.web.app import create_app

from .conftest import web_client
from .test_auth import fake_api, rt  # noqa: F401 - fixtures
from .test_web import rt as lib_rt  # noqa: F401 - fixture
from .test_websearch import fake, search_rt  # noqa: F401 - fixtures

BASE = "http://127.0.0.1:8765"
SEARCH = "/api/websearch?q=sync"
FETCH = "/api/websearch/fetch?url=https://page.example/a"
# another site, and another port of this machine: the browser's SameSite cookie rides the second
ELSEWHERE = ({"origin": "https://evil.example"},
             {"origin": "http://127.0.0.1:9999"},
             {"referer": "http://localhost:9999/x"},
             {"sec-fetch-site": "same-site"},
             {"sec-fetch-site": "cross-site"})


def bearer(name: str) -> dict:
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def bare(app):
    """Kranto's own page, not signed in (a local process, curl with the page's Origin)."""
    return web_client(app, BASE, signed_in=False)


# -- S4: the live search and the fetch ---------------------------------------------------------

def test_a_search_and_a_fetch_are_refused_signed_out(search_rt, fake):  # noqa: F811
    app = create_app(search_rt, port=8765)
    with bare(app) as web:
        for path in (SEARCH, FETCH):
            r = web.get(path)
            assert r.status_code == 401, path
            said = r.json()["error"]
            assert said.startswith("A web search or a page fetch is made signed in.")
            assert "kranto open" in said and "token" not in said.lower()
            assert web.get(path, headers={"authorization": "Bearer " + "0" * 43}).status_code \
                == 401
    assert search_rt.store.query_one("SELECT COUNT(*) AS n FROM api_spend")["n"] == 0


def test_a_search_and_a_fetch_are_refused_from_another_page(search_rt):  # noqa: F811
    app = create_app(search_rt, port=8765)
    with web_client(app, BASE) as web:                  # signed in: the cookie rides along
        for path in (SEARCH, FETCH):
            for headers in ELSEWHERE:
                r = web.get(path, headers=headers)
                assert r.status_code == 403, (path, headers)
                assert r.json()["error"].startswith("cross-origin request refused")
    assert search_rt.store.query_one("SELECT COUNT(*) AS n FROM api_spend")["n"] == 0


def test_a_search_and_a_fetch_answer_the_page_and_every_token(search_rt):  # noqa: F811
    app = create_app(search_rt, port=8765)
    store = tokens.Store()
    store.add("agent:helper")
    _, laptop = store.add_browser("laptop")
    with web_client(app, BASE) as web:
        assert web.get(SEARCH).json()["live"]                         # the page's Origin
        assert web.get(SEARCH, headers={"sec-fetch-site": "same-origin"}).status_code == 200
        assert web.get(SEARCH, headers={"sec-fetch-site": "none"}).status_code == 200
        assert "A page" in web.get(FETCH).json()["text"]
    with bare(app) as web:
        for name in ("ui", "cli", "mcp", "console", "agent:helper"):
            r = web.get(SEARCH + "&caller=research", headers=bearer(name))
            assert r.status_code == 200, name
        # a bearer token is never a browser's own: another Origin does not refuse it
        assert web.get(FETCH, headers={**bearer("mcp"), "origin": "https://x.example"}) \
            .status_code == 200
        r = web.get(SEARCH, headers={"authorization": "Bearer " + laptop})
        assert r.status_code == 403 and "Kranto no longer has" in r.json()["error"]


# -- C8: what the console said, an observation's raw model answer -------------------------------

def test_what_the_console_said_is_the_owners_to_read(rt, fake_api):  # noqa: F811
    app = create_app(rt, port=8765)
    tokens.Store().add("agent:helper")
    path = "/brb/api/term/console/last"
    with bare(app) as web:
        r = web.get(path)
        assert r.status_code == 401
        assert r.json()["error"].startswith("What the console's assistant said is read signed in")
        for name in ("mcp", "console", "agent:helper"):
            r = web.get(path, headers=bearer(name))
            assert r.status_code == 403 and "the owner's to read" in r.json()["error"], name
        assert web.get(path, headers=bearer("ui")).status_code not in (401, 403)
    with web_client(app, BASE) as web:
        for headers in ELSEWHERE:
            assert web.get(path, headers=headers).status_code == 403, headers
        assert web.get(path).status_code not in (401, 403)
    # only the two the owner made reached the page: the ui token's and the signed-in page's
    assert len([c for c in fake_api.calls
                if c[1] == "/api/term/console/last" and len(c) == 5]) == 2


def test_an_observations_raw_model_answer_is_the_owners(lib_rt):  # noqa: F811
    app = create_app(lib_rt, port=8765)
    obs_id = lib_rt.store.query_one("SELECT id FROM observations ORDER BY id LIMIT 1")["id"]
    path = f"/api/observations/{obs_id}"
    with web_client(app, BASE) as web:
        assert web.get(path).json()["call"]["response"] == '{"raw": true}'
        for headers in ELSEWHERE:
            call = web.get(path, headers=headers).json()["call"]
            assert call["response"] is None and call["model"] == "judge-model", headers
    with bare(app) as web:
        o = web.get(path).json()                    # the observation itself stays open
        assert o["call"]["response"] is None and o["call"]["model"] == "judge-model"
        assert o["summary"]
        assert web.get(path, headers=bearer("mcp")).json()["call"]["response"] is None
        assert web.get(path, headers=bearer("cli")).json()["call"]["response"] == '{"raw": true}'


# -- C2: a mode that sends is a person's choice ------------------------------------------------

def telemetry_rt(tmp_path, store, embedder, make_client, monkeypatch, require=True):
    """A home with its settings file (usage reports are a setting in it), not answered yet."""
    from .test_auth import runtime
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    config_mod.init_workspace(tmp_path)
    one = runtime(tmp_path, store, embedder, make_client, require=require)
    telemetry.configure(one.cfg.root)
    return one


def test_usage_reports_that_send_are_turned_on_from_the_page_only(tmp_path, store, embedder,
                                                                  make_client, monkeypatch):
    home_rt = telemetry_rt(tmp_path, store, embedder, make_client, monkeypatch)
    app = create_app(home_rt, port=8765)
    url = "/api/settings/telemetry"
    with bare(app) as web:
        for mode in telemetry.SENDING:
            # the command line's token (the guard lets it write anywhere) is refused here
            r = web.post(url, json={"mode": mode}, headers=bearer("cli"))
            assert r.status_code == 403, mode
            assert "Settings › Privacy & access" in r.json()["error"]
            assert "kranto telemetry basic" in r.json()["error"]
            for name in ("mcp", "console"):      # an assistant's: the guard refuses it first
                assert web.post(url, json={"mode": mode}, headers=bearer(name)).status_code \
                    == 403, name
        assert telemetry.effective(home_rt.cfg.root).mode not in telemetry.SENDING
        # a mode that keeps everything on this machine is not refused
        assert web.post(url, json={"mode": "local"}, headers=bearer("cli")).status_code == 200
        assert web.post(url, json={"mode": "off"}, headers=bearer("cli")).status_code == 200
    with web_client(app, BASE) as web:                       # the page, signed in
        for headers in ELSEWHERE[:2]:          # a browser's POST always says its Origin
            assert web.post(url, json={"mode": "basic"}, headers=headers).status_code == 403
        r = web.post(url, json={"mode": "basic"})
        assert r.status_code == 200 and r.json()["mode"] == "basic"
        assert web.post(url, json={"mode": "off"}).json()["mode"] == "off"


def test_with_tokens_not_required_nobody_turns_sending_on(tmp_path, store, embedder,
                                                          make_client, monkeypatch):
    rt_open = telemetry_rt(tmp_path, store, embedder, make_client, monkeypatch, require=False)
    app = create_app(rt_open, port=8765)
    with bare(app) as web:
        r = web.post("/api/settings/telemetry", json={"mode": "detailed"})
        assert r.status_code == 403
        assert web.post("/api/settings/telemetry", json={"mode": "off"}).status_code == 200
    with web_client(app, BASE) as web:                       # a browser that signed in
        assert web.post("/api/settings/telemetry", json={"mode": "basic"}).status_code == 200
