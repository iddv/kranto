"""Who is calling: every write needs a kranto token, and the token says who acts.

The guard refuses a write without a current token (401), lets an mcp or agent token run only
actions (``POST /brb/api/act``), and hands the caller to the mounted the page, which acts as
that caller whatever the body says. A browser gets its cookie only from a one-time code
(``kranto open``); fetching a page hands out nothing. Token values are made at runtime by the
store, and none may reach a log, a response or the index."""

import json
import logging
import re
import stat
from pathlib import Path

import pytest

from kranto import launcher, tokens
from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.runtime import open_runtime
from kranto.update import apply
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, sign_in, web_client
from .test_brb_mount import FakeApi

BASE = "http://127.0.0.1:8765"


class IdentityApi(FakeApi):
    """The page's ``api.handle`` with ``identity``: records who the host said was calling."""

    def handle(self, method, path, query=None, body=None, identity=None):
        self.calls.append((method, path, query, body, identity))
        if path == "/api/act":
            return 200, "application/json", json.dumps(
                {"by": (identity or {}).get("origin")}).encode()
        return super().handle(method, path, query, body)


@pytest.fixture
def fake_api(monkeypatch):
    return brbfake.install(monkeypatch, IdentityApi())


def runtime(tmp_path, store, embedder, make_client, require=True, brb=True):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(require_token=require),
                 builds=BuildsConfig(enabled=brb),
                 brb=BrbConfig(enabled=brb, root=str(tmp_path / "tasks")))
    return open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))


@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    return runtime(tmp_path, store, embedder, make_client)


def bare(app):
    """A client with the page's Origin but no credential (a local process, curl)."""
    return web_client(app, BASE, signed_in=False)


def bearer(name):
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def test_a_write_without_a_token_is_refused(rt, fake_api, caplog):
    app = create_app(rt, port=8765)
    with bare(app) as web, caplog.at_level(logging.WARNING):
        for path, kw in (("/pause", {"data": {"reason": "x"}}), ("/api/hold", {"json": {}}),
                         ("/brb/api/act", {"json": {"kind": "stop", "origin": "ui"}}),
                         ("/brb/api/loop/close", {"json": {"id": "i1", "origin": "ui"}})):
            r = web.post(path, **kw)
            assert r.status_code == 401 and "not signed in" in r.json()["error"], path
        r = web.post("/pause", data={"reason": "x"},
                     headers={"authorization": "Bearer " + "0" * 43})
        assert r.status_code == 401 and "not a current" in r.json()["error"]
        assert web.get("/api/status").status_code == 200          # reads stay open
        assert web.get("/").status_code == 200
    assert rt.store.pause_reason() is None
    assert not [c for c in fake_api.calls if c[0] == "POST"]
    assert "refused POST /pause: it carries no kranto token" in caplog.text


def test_a_browsers_refused_save_says_how_to_sign_in_without_token_words(rt, fake_api):
    """A signed-out browser's save failed with "it carries no kranto token … 'Authorization:
    Bearer' …": a stranger in a browser is told what to do, a script keeps the technical words."""
    app = create_app(rt, port=8765)
    with bare(app) as web:
        said = web.post("/pause", data={"reason": "x"}).json()["error"]
        assert said.startswith("This browser is not signed in: run `kranto open` on the machine "
                               "Kranto runs on")
        assert "token" not in said.lower() and "bearer" not in said.lower()
        web.cookies.set(tokens.cookie_name(8765), "0" * 43)
        stale = web.post("/pause", data={"reason": "x"}).json()["error"]
        web.cookies.clear()
        assert "kranto open" in stale and "token" not in stale.lower()
        script = web.post("/pause", data={"reason": "x"},
                          headers={"authorization": "Bearer " + "0" * 43}).json()["error"]
        assert "Authorization: Bearer" in script


def test_a_trace_is_read_by_the_owner_only(rt, fake_api, caplog):
    """A build's agent trace holds file contents and prompts (the page D-4): its GET needs
    the owner's token or cookie, and the page is told who reads; every other read stays open."""
    app = create_app(rt, port=8765)
    store = tokens.Store()
    store.add("agent:RC")
    paths = ("/brb/api/traces", "/brb/api/trace?trace=build:x/1", "/brb/api/trace/spans",
             "/brb/api/trace/payload?span=s")
    with bare(app) as web, caplog.at_level(logging.WARNING):
        for path in paths:
            r = web.get(path)
            assert r.status_code == 401 and "not signed in" in r.json()["error"], path
            assert web.head(path).status_code == 401, path
            r = web.get(path, headers=bearer("agent:RC"))
            assert r.status_code == 403 and "the owner's" in r.json()["error"], path
            assert web.get(path, headers=bearer("mcp")).status_code == 403, path
        assert not [c for c in fake_api.calls if c[1].startswith("/api/trace")]
        web.get("/brb/api/tracer")                                  # not a trace: open
        assert [c for c in fake_api.calls if c[1] == "/api/tracer"]
        assert web.get("/brb/api/traces", headers=bearer("ui")).status_code not in (401, 403)

    def readers():                     # IdentityApi's rows: (method, path, query, body, who)
        return [c[4] for c in fake_api.calls if len(c) == 5 and c[1] == "/api/traces"]
    assert len(readers()) == 1 and readers()[0]["origin"] == "ui"   # the page is told who
    with web_client(app, BASE) as signed:                           # the page's cookie
        assert signed.get("/brb/api/traces").status_code not in (401, 403)
    assert len(readers()) == 2 and readers()[1]["via"] == "cookie"


def test_a_spoofed_ui_origin_acts_as_its_token(rt, fake_api, caplog):
    app = create_app(rt, port=8765)
    store = tokens.Store()
    store.add("agent:RC")
    with bare(app) as web:
        body = {"kind": "stop_round", "origin": "ui", "confirm": True,
                "subject": {"kind": "build", "id": "beliefline"}}
        r = web.post("/brb/api/act", json=body, headers=bearer("agent:RC"))
        assert r.status_code == 200 and r.json() == {"by": "agent:RC"}
        # an assistant never reaches api/act around the ladder, verbs or not
        r = web.post("/brb/api/act", json=body, headers=bearer("mcp"))
        assert r.status_code == 403 and "/api/verbs/<kind>" in r.json()["error"]
    who = [c[4] for c in fake_api.calls if c[0] == "POST"]
    assert [w["origin"] for w in who] == ["agent:RC"] and who[0]["via"] == "bearer"


def no_origin(app):
    """A client that sends no Origin or Referer (an agent's curl, a script)."""
    from starlette.testclient import TestClient
    return TestClient(app, base_url=BASE)


def test_a_bearer_write_needs_no_origin(rt, fake_api):
    app = create_app(rt, port=8765)
    tokens.Store().add("agent:helper")
    body = {"kind": "add_idea", "subject": {"kind": "new"}, "fields": {"text": "x"}}
    with no_origin(app) as web:
        r = web.post("/brb/api/act", json=body, headers=bearer("agent:helper"))
        assert r.status_code == 200 and r.json() == {"by": "agent:helper"}
        foreign = {**bearer("agent:helper"), "origin": "https://evil.example"}
        assert web.post("/brb/api/act", json=body, headers=foreign).status_code == 200
        assert web.post("/pause", data={"reason": "cli"}, headers=bearer("cli")).status_code \
            == 200
        # the token's limits still hold, and a token that is not current gets no exemption
        r = web.post("/pause", data={"reason": "x"}, headers=bearer("agent:helper"))
        assert r.status_code == 403 and "only runs actions" in r.json()["error"]
        r = web.post("/brb/api/act", json=body, headers={"authorization": "Bearer " + "0" * 43})
        assert r.status_code == 403 and r.text == "cross-origin request refused"
    assert rt.store.pause_reason() == "cli"


def test_a_cookie_write_still_needs_its_origin(rt, fake_api):
    app = create_app(rt, port=8765)
    with no_origin(app) as web:
        sign_in(web, app)
        body = {"kind": "retry"}
        r = web.post("/brb/api/act", json=body)
        assert r.status_code == 403 and r.text == "cross-origin request refused"
        r = web.post("/pause", data={"reason": "x"}, headers={"origin": "https://evil.example"})
        assert r.status_code == 403 and r.text == "cross-origin request refused"
        r = web.post("/brb/api/act", json=body, headers={"origin": BASE})
        assert r.status_code == 200 and r.json() == {"by": "ui"}
    assert rt.store.pause_reason() is None


def test_mcp_and_agent_tokens_only_run_actions(rt, fake_api):
    app = create_app(rt, port=8765)
    tokens.Store().add("agent:RC")
    with bare(app) as web:
        for who in ("mcp", "agent:RC"):
            for path in ("/pause", "/brb/api/loop/close", "/brb/api/spend", "/api/tokens",
                         "/api/hold"):
                r = web.post(path, json={}, headers=bearer(who))
                assert r.status_code == 403 and "only runs actions" in r.json()["error"], path
        # the owner's doors write anywhere
        assert web.post("/pause", data={"reason": "cli"}, headers=bearer("cli")).status_code \
            == 200
    assert rt.store.pause_reason() == "cli"


def test_a_cookie_counts_only_for_the_ui(rt, fake_api):
    app = create_app(rt, port=8765)
    auth = app.state.app.auth
    assert auth.cookie == "kranto_session_8765"
    with bare(app) as web:
        web.cookies.set(auth.cookie, tokens.Store().value("mcp"))
        assert web.post("/pause", data={"reason": "x"}).status_code == 401
        web.cookies.set(auth.cookie, tokens.Store().value("ui"))
        r = web.post("/brb/api/act", json={"kind": "retry", "origin": "mcp"})
        assert r.status_code == 200 and r.json() == {"by": "ui"}


def test_the_cookie_bootstrap(rt, fake_api):
    app = create_app(rt, port=8765)
    store, name = tokens.Store(), app.state.app.auth.cookie
    with bare(app) as web:
        for path in ("/", "/brb/", "/brb/static/app.js", "/library", "/api/whoami"):
            assert "set-cookie" not in web.get(path, follow_redirects=False).headers, path
        assert web.get("/api/whoami").json() == {"origin": None, "via": None,
                                                 "require_token": True, "signin": "kranto open"}
        assert web.get("/auth/open?code=nothing-here").status_code == 400
        code = store.mint_code()
        r = web.get(f"/auth/open?code={code}&next=/%23/builds", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/#/builds"
        cookie = r.headers["set-cookie"]
        assert cookie.startswith(f"{name}=") and "HttpOnly" in cookie and "Path=/" in cookie
        assert re.search(r"SameSite=strict", cookie, re.I)
        assert web.get("/api/whoami").json()["origin"] == "ui"
        assert web.post("/pause", data={"reason": "signed in"}).status_code == 200
        web.cookies.clear()
        assert web.get(f"/auth/open?code={code}").status_code == 400     # one time only
        # off-site next is replaced
        r = web.get(f"/auth/open?code={store.mint_code()}&next=//evil.example/x",
                    follow_redirects=False)
        assert r.headers["location"] == "/"
        web.cookies.clear()
        # The page's sign-in box; an expired code is refused
        r = web.post("/auth/code", json={"code": store.mint_code()})
        assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
        web.cookies.clear()
        late = store.mint_code(ttl_s=-1)
        assert web.post("/auth/code", json={"code": late}).status_code == 400
        # a cross-site page cannot use the sign-in box either (the Origin check comes first)
        r = web.post("/auth/code", json={"code": store.mint_code()},
                     headers={"origin": "http://evil.example"})
        assert r.status_code == 403
    assert rt.store.pause_reason() == "signed in"


def test_require_token_off_keeps_the_old_way_and_doctor_warns(tmp_path, store, embedder,
                                                              make_client, fake_api):
    rt = runtime(tmp_path, store, embedder, make_client, require=False)
    app = create_app(rt, port=8765)
    with bare(app) as web:
        assert web.post("/pause", data={"reason": "old"}).status_code == 200
        web.post("/brb/api/act", json={"kind": "retry", "origin": "ui"})
    acts = [c for c in fake_api.calls if c[1] == "/api/act"]
    assert len(acts) == 1 and acts[0][4] is None                  # body origin, as before
    host = launcher.Host(home=tmp_path, run=lambda *a, **k: None)
    check = launcher.token_check(host, rt.cfg)
    assert check.status == launcher.WARN and "require_token is off" in check.detail
    check = launcher.token_check(host, runtime(tmp_path / "on", store, embedder, make_client).cfg)
    assert check.status == launcher.OK and "writes need a token" in check.detail


def test_the_tokens_api(rt, fake_api):
    app = create_app(rt, port=8765)
    with web_client(app, BASE) as web:
        r = web.post("/api/tokens", json={"name": "RC", "note": "a release check"})
        assert r.status_code == 200 and r.json()["name"] == "agent:RC"
        rows = web.get("/api/tokens").json()["tokens"]
        assert [t["name"] for t in rows] == ["cli", "console", "mcp", "ui", "agent:RC"]
        text = json.dumps(rows)
        for name in ("ui", "mcp", "cli", "agent:RC"):
            assert tokens.Store().value(name) not in text
        assert web.post("/api/tokens/agent%3ARC/actions", json={"actions": ["topic.add"]}) \
            .status_code == 200
        assert tokens.Store().identify(tokens.Store().value("agent:RC"))["actions"] == \
            ["topic.add"]
        # a build loop's action is no verb any more: refused when asked for anew
        r = web.post("/api/tokens/agent%3ARC/actions", json={"actions": ["retry"]})
        assert r.status_code == 400 and "no such verb: retry" in r.json()["error"]
        assert "topic.add" in web.get("/api/tokens").json()["default_actions"]
        assert web.post("/api/tokens/ui/revoke").status_code == 400          # rotate a door
        old = tokens.Store().value("ui")
        r = web.post("/api/tokens/ui/rotate")
        assert r.status_code == 200 and tokens.Store().value("ui") != old
        assert web.post("/pause", data={"reason": "still in"}).status_code == 200  # re-signed
        assert web.post("/api/tokens/agent%3ARC/revoke").status_code == 200
        assert tokens.Store().value("agent:RC") is None


def test_a_token_file_naming_old_build_actions_still_signs_in(rt, fake_api):
    """CUT (token files): an agent's ``actions`` written before the cut names the
    build loop's actions (``publish``, ``b.retry``). The token still signs in and runs verbs;
    the old names are ignored when read, and the file is not rewritten."""
    store = tokens.Store()
    store.add("agent:old", ["publish", "b.retry", "topic.add"])
    index = (tokens.tokens_dir() / "index.json")
    raw = json.loads(index.read_text())
    raw["tokens"]["agent:odd"] = {**raw["tokens"]["agent:old"], "actions": "everything"}
    before = json.dumps(raw)
    index.write_text(before)
    app = create_app(rt, port=8765)
    with bare(app) as web:
        assert web.get("/api/whoami", headers=bearer("agent:old")).json()["origin"] == \
            "agent:old"
        r = web.post("/api/verbs/nope.nothing", json={}, headers=bearer("agent:old"))
        assert r.status_code not in (401, 403)                 # past the guard: the verbs' door
    with web_client(app, BASE) as page:
        rows = {t["name"]: t for t in page.get("/api/tokens").json()["tokens"]}
    assert rows["agent:old"]["actions"] == ["topic.add"]
    assert rows["agent:old"]["ignored"] == ["publish", "b.retry"]
    assert rows["agent:odd"]["actions"] is None and rows["agent:odd"]["ignored"] == []
    assert json.loads(index.read_text())["tokens"]["agent:old"]["actions"] == \
        ["publish", "b.retry", "topic.add"]                     # never rewritten


def test_the_cli(tmp_path, capsys):
    host = launcher.Host(home=tmp_path, run=lambda *a, **k: None)
    assert launcher.main(["token", "add", "RC", "--note", "a release check"], host) == 0
    out = capsys.readouterr().out
    value = tokens.Store().value("agent:RC")
    assert "added agent:RC" in out and "Authorization: Bearer $(cat" in out and value not in out
    assert launcher.main(["token", "list"], host) == 0
    out = capsys.readouterr().out
    assert "agent:RC" in out and "ui" in out
    for name in ("ui", "mcp", "cli", "agent:RC"):
        assert tokens.Store().value(name) not in out
    assert launcher.main(["token", "add", "agent:RC"], host) == 2           # exists
    assert launcher.main(["token", "revoke", "RC"], host) == 0
    assert tokens.Store().value("agent:RC") is None


def test_token_add_names_the_file_where_kranto_tokens_dir_puts_it(tmp_path, capsys,
                                                                    monkeypatch):
    """The hint 'Authorization: Bearer $(cat …)' names the file in $KRANTO_TOKENS_DIR, not the
    default folder (a newcomer's install found the two the same, so it stays pinned)."""
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("KRANTO_TOKENS_DIR", str(elsewhere))
    host = launcher.Host(home=tmp_path / "h", run=lambda *a, **k: None)
    assert launcher.main(["token", "add", "agent:helper"], host) == 0
    out = capsys.readouterr().out
    assert f"$(cat {elsewhere}/agent-helper.token)" in out, out
    assert ".config/kranto" not in out


def test_the_update_helper_says_who_it_is(tmp_path, monkeypatch):
    seen = []
    tokens.Store().ensure_doors()
    h = apply.Helper(tmp_path, "v9.9.9", env={"KRANTO_TOKENS_DIR": str(tokens.tokens_dir())},
                     http=lambda m, u, b=None, timeout=10, headers=None: seen.append(
                         (m, (headers or {}).get("Authorization"))) or (200, {}))
    h.api("POST", "/api/hold", {"reason": "x"})
    h.api("GET", "/api/status")
    assert seen == [("POST", "Bearer " + tokens.Store().value("cli")), ("GET", None)]
    # a server from before tokens: no token file, the helper writes as it always did
    h = apply.Helper(tmp_path, "v9.9.9", env={"KRANTO_TOKENS_DIR": str(tmp_path / "none")},
                     http=lambda m, u, b=None, timeout=10: seen.append((m, "plain")) or (200, {}))
    h.api("POST", "/api/hold", {"reason": "x"})
    assert seen[-1] == ("POST", "plain")


def test_the_store_files_and_no_value_in_the_index(tmp_path):
    s = tokens.Store(tmp_path / "t")
    s.ensure_doors()
    assert stat.S_IMODE((tmp_path / "t").stat().st_mode) == 0o700
    index = (tmp_path / "t" / "index.json").read_text()
    for name in tokens.DOORS:
        assert stat.S_IMODE(s.path(name).stat().st_mode) == 0o600
        assert s.value(name) not in index
    code = s.mint_code()
    launch = tmp_path / "t" / "launch"
    assert code not in "".join(p.name + p.read_text() for p in launch.iterdir())
    assert s.redeem(code) == s.value("ui") and s.redeem(code) is None
    assert tokens.tokens_dir({"KRANTO_UNIT": "kranto-test.service"}, Path("/h")) == \
        Path("/h/.config/kranto/tokens.kranto-test")
    assert tokens.tokens_dir({}, Path("/h")) == Path("/h/.config/kranto/tokens")


def test_no_token_value_reaches_a_log(rt, fake_api, caplog):
    app = create_app(rt, port=8765)
    store = tokens.Store()
    store.add("agent:RC")
    values = [store.value(n) for n in ("ui", "mcp", "cli", "agent:RC")]
    with bare(app) as web, caplog.at_level(logging.DEBUG):
        web.post("/pause", data={"reason": "x"})
        web.post("/pause", data={"reason": "x"}, headers={"authorization": "Bearer wrong"})
        web.post("/pause", data={"reason": "x"}, headers=bearer("mcp"))
        web.post("/brb/api/act", json={"kind": "retry", "origin": "ui"}, headers=bearer("agent:RC"))
        web.get(f"/auth/open?code={store.mint_code()}")
        web.post("/auth/code", json={"code": store.mint_code()})
        sign_in(web, app)
        web.post("/api/tokens/agent%3ARC/rotate")
    assert "refused" in caplog.text
    for v in values + [store.value("agent:RC")]:
        assert v not in caplog.text


def test_tokens_py_is_the_same_in_both_repos():
    bb = pytest.importorskip("kranto.page.tokens")
    if not hasattr(bb, "__file__"):
        pytest.skip("the page is a stand-in here")
    assert Path(bb.__file__).read_bytes() == Path(tokens.__file__).read_bytes()
