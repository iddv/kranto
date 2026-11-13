"""the page mounted at /brb/ (approach (a)): the adapter, mounted and not,
the loopback-only rule, the version check, the guard on the mount, and Pause.

the page is not a dependency of the server, so these tests stand in a small fake for
``kranto.page.host_api`` (``brbfake``): the adapter calls ``API_VERSION``, ``configure``,
``handle`` and, when the page has them, ``handle_with_headers`` and ``stream``."""

import json
import types
from dataclasses import replace

import pytest

from kranto import config as afk_config
from kranto.config import (
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    ConfigError,
    IngestConfig,
    MapConfig,
)
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, web_client

BASE = "http://127.0.0.1:8765"


class FakeApi(types.ModuleType):
    """``kranto.page.host_api``'s mount (``handle``, ``configure``, ``API_VERSION``): records each
    call; answers like the real one."""

    def __init__(self, version=1):
        super().__init__("kranto.page.host_api")
        self.API_VERSION = version
        self.calls: list[tuple] = []
        self.configured = None
        self.paused = False

    def configure(self, root=None, harness="claude-code", loop_home=None):
        self.configured = (root, harness, loop_home)

    def handle(self, method, path, query=None, body=None):
        self.calls.append((method, path, query, body))
        if path == "/api/header":
            return 200, "application/json", json.dumps(
                {"api_version": 1, "paused": self.paused, "running": 1, "queued": 2,
                 "needs_you": 3, "open_ideas": 4}).encode()
        if path == "/api/loop/pause":
            self.paused = bool(body.get("paused"))
            return 200, "application/json", b'{"ok": true}'
        if path == "/":
            return 200, "text/html; charset=utf-8", b"<!doctype html><title>Kranto</title>"
        if path == "/api/echo":
            return 200, "application/json", json.dumps(
                {"method": method, "query": query,
                 "body": body.decode() if isinstance(body, bytes) else body}).encode()
        return 404, "application/json", b'{"error": "not found"}'


@pytest.fixture
def fake_api(monkeypatch):
    return brbfake.install(monkeypatch, FakeApi())


def runtime(tmp_path, store, embedder, make_client, enabled=True):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(),
                 builds=BuildsConfig(enabled=enabled),
                 brb=BrbConfig(enabled=enabled, root=str(tmp_path / "tasks")))
    return open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))


@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    return runtime(tmp_path, store, embedder, make_client)


def client(rt, **kw):
    return web_client(create_app(rt, **kw), BASE)


def test_mounted_routes_to_handle(rt, fake_api):
    with client(rt) as web:
        page = web.get("/brb/")
        assert page.status_code == 200 and "<title>Kranto</title>" in page.text
        assert page.headers["content-type"].startswith("text/html")
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert web.get("/brb", follow_redirects=False).headers["location"] == "/brb/"
        assert web.get("/", follow_redirects=False).headers["location"] == "/brb/"
        r = web.get("/brb/api/echo?dir=%2Ftmp%2Fx&since=3").json()
        assert r == {"method": "GET", "query": "dir=%2Ftmp%2Fx&since=3", "body": ""}
        r = web.post("/brb/api/echo", json={"id": "i1234abcd"}).json()
        assert r["method"] == "POST" and json.loads(r["body"]) == {"id": "i1234abcd"}
        assert web.get("/brb/api/nothing").status_code == 404
    assert fake_api.configured == (str(rt.cfg.root / "tasks"), "claude-code", None)


def test_versioned_static_files_are_cached_for_good_and_gzipped(rt, fake_api):
    """the page's handle_with_headers marks its static/v<version>/ files immutable (S-3b):
    the mount passes that on and gzips them for a client that accepts it; every other
    answer keeps no-store, and an older the page (no handle_with_headers) changes nothing."""
    import gzip
    big = b"export const x = 1;\n" * 400

    def with_headers(method, path, query=None, body=None, identity=None):
        if path == "/static/v9.9.9/app/app-c0ffee.js":
            return 200, "text/javascript; charset=utf-8", big, {
                "cache-control": "public, max-age=31536000, immutable"}
        return (*fake_api.handle(method, path, query, body), {})
    fake_api.handle_with_headers = with_headers
    with client(rt) as web:
        r = web.get("/brb/static/v9.9.9/app/app-c0ffee.js", headers={"accept-encoding": "gzip"})
        assert r.status_code == 200 and r.content == big           # decoded by the client
        assert "immutable" in r.headers["cache-control"]
        assert r.headers["content-encoding"] == "gzip" and r.headers["vary"] == "accept-encoding"
        raw = web.get("/brb/static/v9.9.9/app/app-c0ffee.js",
                      headers={"accept-encoding": "identity"})
        assert "content-encoding" not in raw.headers and raw.content == big
        page = web.get("/brb/")
        assert page.headers["cache-control"] == "no-store"
    assert len(gzip.compress(big)) < len(big) // 10


class FakeStream:
    """the page's live feed: a few events, then the end; remembers that it was closed."""

    def __init__(self, chunks):
        self.chunks, self.closed = list(chunks), False

    def __iter__(self):
        return self

    def __next__(self):
        if not self.chunks:
            raise StopIteration
        return self.chunks.pop(0)

    def close(self):
        self.closed = True


def test_the_live_feed_streams_through_the_mount(rt, fake_api):
    """the page's ``api.stream``: ``/brb/api/stream`` is written as server-sent events
    through the guard's middleware, each chunk as it comes, with no-store and the page's
    policy; the feed is closed after; every place taken is a 503; anything else is
    ``handle``'s as before."""
    feeds: list = []

    def stream(path, query=None, app=None, last=None):
        if path.rstrip("/") != "/api/stream":
            return None
        if query == "full=1":
            err = Exception("8 live streams are open; poll instead")
            err.code = 503
            raise err
        feeds.append(FakeStream([b"retry: 3000\n\n",
                                 f'event: host\ndata: {{"last": "{last}"}}\n\n'.encode(),
                                 b'id: 1\nevent: change\ndata: {"kinds": ["builds"]}\n\n']))
        return feeds[-1]
    fake_api.stream = stream
    with client(rt) as web:
        with web.stream("GET", "/brb/api/stream", headers={"last-event-id": "4"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["cache-control"] == "no-store"
            assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
            chunks = list(r.iter_bytes())
        body = b"".join(chunks)
        assert body.startswith(b"retry: 3000\n\n") and b'"last": "4"' in body
        assert b'event: change\ndata: {"kinds": ["builds"]}' in body
        assert feeds[0].closed
        busy = web.get("/brb/api/stream?full=1")
        assert busy.status_code == 503 and "poll" in busy.json()["error"]
        assert web.get("/brb/api/echo").json()["method"] == "GET"
        # the guard holds on the stream as on every route
        assert web.get("/brb/api/stream", headers={"host": "evil.example"}).status_code == 400
    assert not any(c[1] == "/api/stream" for c in fake_api.calls)


def test_an_older_page_has_no_live_feed(rt, fake_api):
    with client(rt) as web:
        assert web.get("/brb/api/stream").status_code == 404     # handle's answer, as before
    assert ("GET", "/api/stream", "", b"") in fake_api.calls


def test_mounted_page_is_told_where_the_ideas_api_is(rt, fake_api, monkeypatch):
    """A the page that accepts ``kranto_url`` gets this server's URL; an older one is
    configured as before."""
    with client(rt, port=8765):
        pass
    assert fake_api.configured == (str(rt.cfg.root / "tasks"), "claude-code", None)
    seen = {}

    def configure(root=None, harness="claude-code", loop_home=None, kranto_url=None):
        seen["url"] = kranto_url

    monkeypatch.setattr(fake_api, "configure", configure)
    with client(rt, port=8765):
        pass
    assert seen["url"] == "http://127.0.0.1:8765"
    with client(rt, bind_host="::1", port=9000):
        pass
    assert seen["url"] == "http://[::1]:9000"
    with client(rt):
        pass
    assert seen["url"] is None


def test_mounted_page_is_told_where_the_activity_file_is(rt, fake_api, monkeypatch):
    """ACT: a the page that takes ``kranto_data`` watches its ``activity.json`` for the
    live feed; an older one is configured as before (the first test above)."""
    seen = {}

    def configure(root=None, harness="claude-code", loop_home=None, kranto_url=None,
                  kranto_data=None):
        seen["data"] = kranto_data

    monkeypatch.setattr(fake_api, "configure", configure)
    with client(rt, port=8765):
        pass
    assert seen["data"] == str(rt.cfg.data_dir)


def test_mount_refuses_cross_origin_posts(rt, fake_api):
    with client(rt) as web:
        for origin in ("http://evil.example", "http://127.0.0.1:9999"):
            r = web.post("/brb/api/start", json={"dir": "/x"}, headers={"origin": origin})
            assert r.status_code == 403
        r = web.post("/brb/api/start", json={}, headers={"origin": ""})
        assert r.status_code == 403
        r = web.get("/brb/", headers={"host": "evil.example"})
        assert r.status_code == 400
    assert not [c for c in fake_api.calls if c[1] == "/api/start"]


def test_mount_refuses_cross_origin_chat_posts(rt, fake_api):
    """the page's project chat (API version 2) sits behind the same guard: a chat message or
    an action card's click from another origin, or with no origin, never reaches it."""
    with client(rt) as web:
        for path in ("/brb/api/chat/send", "/brb/api/chat/act", "/brb/api/chat/stop"):
            for origin in ("http://evil.example", "http://127.0.0.1:9999", ""):
                r = web.post(path, json={"id": "c1234abcd", "text": "hi", "n": 1},
                             headers={"origin": origin})
                assert r.status_code == 403, (path, origin)
        r = web.post("/brb/api/echo", json={"text": "hi"}, headers={"origin": BASE})
        assert r.status_code == 200
    assert not [c for c in fake_api.calls if c[1].startswith("/api/chat")]


def test_mounts_api_version_2(rt, fake_api):
    fake_api.API_VERSION = 2
    with client(rt) as web:
        assert web.get("/brb/").status_code == 200


def test_shared_header_on_kranto_pages(rt, fake_api):
    with client(rt) as web:
        page = web.get("/connections").text
    for tab in ('href="/brb/#/today">Today', 'href="/brb/#/ideas"',
                'href="/brb/#/settings"', "/static/kranto-afk.css",
                'href="/brb/#/library"'):
        assert tab in page, tab
    assert "/brb/#/chat" not in page                 # the project chat went (the page)
    assert "/brb/#/builds" not in page and "building" not in page     # builds left (CUT)
    assert not [c for c in fake_api.calls if c[1] == "/api/header"]   # no builds' figures
    assert 'action="/pause"' in page and 'name="next" value="/connections"' in page
    assert "Kranto afk, still watching" not in page
    assert 'aria-label="Settings pages"' in page


def test_kranto_pages_draw_in_the_appearance_chosen(rt, fake_api):
    """QA B18 (the owner's B2, "appearance resets when you click on some things"): a page the server
    draws itself (connecting an account, its continuation, the install page) followed only the
    OS's scheme. It loads static/theme.js before its styles, and its colours follow data-theme."""
    with client(rt) as web:
        page = web.get("/connections").text
        js = web.get("/static/theme.js")
        css = web.get("/static/style.css").text + web.get("/static/kranto-afk.css").text
    assert page.index('<script src="/static/theme.js"></script>') < page.index("/static/style.css")
    assert js.status_code == 200 and 'localStorage.getItem("kranto.theme")' in js.text
    assert css.count(":root[data-theme=dark]") == 2
    assert css.count(":root:not([data-theme=light])") == 2


def test_old_pages_redirect_to_their_hash_routes_when_mounted(rt, fake_api):
    """UI-v4.md 2.3: with Kranto UI mounted, the server's old page addresses answer 302 to
    the hash route that replaced them, their query kept; their forms still post where they
    did. /topics and a strike's /grade/... link (pages until) go there too."""
    want = {"/library": "/brb/#/library",
            "/library?topic=2&q=solar": "/brb/#/library?topic=2&q=solar",
            "/ideas": "/brb/#/ideas", "/health": "/brb/#/settings/health",
            "/watches": "/brb/#/watch", "/clusters": "/brb/#/library/clusters",
            "/map": "/brb/#/library/map", "/rollups?q=x": "/brb/#/library/rollups?q=x",
            "/obs/244": "/brb/#/library/o/244", "/obs/nope": "/brb/#/library",
            "/topics": "/brb/#/settings", "/topics?msg=hi": "/brb/#/settings?msg=hi",
            "/grade/message/7": "/brb/#/settings/health?message=7",
            "/grade/observation/5": "/brb/#/library/o/5",
            "/grade/idea/3": "/brb/#/ideas/card:3",
            "/grade/cluster/c-1": "/brb/#/library/clusters",
            "/grade/message/x": "/brb/#/settings/health",
            "/grade/nope/1": "/brb/#/settings/health"}
    with client(rt) as web:
        for path, to in want.items():
            r = web.get(path, follow_redirects=False)
            assert (r.status_code, r.headers["location"]) == (302, to), path
        # watches are retired: their old page opens Watch, and nothing takes their form
        assert web.post("/watches", data={"query": ""}, follow_redirects=False).status_code == 405
        assert web.get("/connections").status_code == 200
        assert web.get("/", follow_redirects=False).headers["location"] == "/brb/"


def test_not_mounted_when_disabled(tmp_path, store, embedder, make_client, fake_api):
    rt = runtime(tmp_path, store, embedder, make_client, enabled=False)
    with client(rt) as web:
        assert web.get("/brb/").status_code == 404
        page = web.get("/library").text
        assert "still watching" in page and "/brb/#" not in page
        for path in ("/", "/ideas", "/health", "/watches", "/map", "/clusters", "/rollups",
                     "/topics", "/obs/1", "/grade/message/1"):
            r = web.get(path, follow_redirects=False)
            assert r.status_code == 200 and "Kranto is one app" in r.text, path
    assert fake_api.calls == [] and fake_api.configured is None


def test_not_mounted_without_page(rt, monkeypatch):
    # import kranto.page fails, also where an earlier test already imported its UI (the doctor's)
    brbfake.missing(monkeypatch)
    app = create_app(rt)
    assert app.state.app.brb.state == "missing"
    with web_client(app, BASE) as web:
        assert web.get("/brb/").status_code == 404
        page = web.get("/library").text
        assert "Kranto is one app" in page and "the page is not installed here" in page


def test_only_on_loopback(rt, fake_api):
    for host in ("0.0.0.0", "192.168.1.20", "::"):
        app = create_app(rt, bind_host=host)
        assert app.state.app.brb.state == "not_loopback"
        with web_client(app, BASE) as web:
            assert web.get("/brb/").status_code == 404
    for host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        assert create_app(rt, bind_host=host).state.app.brb.mounted


def test_too_old_says_so(rt, fake_api):
    fake_api.API_VERSION = 0
    with client(rt) as web:
        r = web.get("/brb/")
        assert r.status_code == 503 and "the page is too old" in r.text
        page = web.get("/library")
        assert page.status_code == 200 and "Kranto is one app" in page.text
        assert "the page is too old" in page.text
    assert fake_api.calls == []


def test_pause_is_watchings_alone(rt, fake_api):
    """Builds left Kranto (CUT): Pause pauses the watcher and never calls the loop's pause."""
    with client(rt) as web:
        r = web.post("/pause", data={"reason": "night", "next": "/library"},
                     follow_redirects=False)
        assert r.headers["location"] == "/library"
        assert rt.store.pause_reason() == "night"
        page = web.get("/connections").text
        assert ">Paused<" in page and 'action="/resume"' in page
        r = web.post("/resume", data={"next": "//evil.example/"}, follow_redirects=False)
        assert r.headers["location"] == "/brb/#/settings/health"   # never off this site
        assert rt.store.pause_reason() is None
    assert not [c for c in fake_api.calls if c[1] == "/api/loop/pause"]


def test_pause_answers_json_to_the_kranto_ui(rt, fake_api):
    """Kranto UI's hostForm asks for JSON: ``{"ok", "error"}``."""
    headers = {"accept": "application/json"}
    with client(rt) as web:
        r = web.post("/pause", data={"reason": "x"}, headers=headers, follow_redirects=False)
        assert r.status_code == 200 and r.json() == {"ok": True, "error": None}
        r = web.post("/resume", headers=headers, follow_redirects=False)
        assert r.status_code == 200 and r.json() == {"ok": True, "error": None}


def test_form_redirects_go_to_the_kranto_ui_when_mounted(rt, fake_api, tmp_path, store,
                                                         embedder, make_client):
    from kranto.ideate import cards

    idea = store.insert("ideas", {
        "snapshot_id": None, "fingerprint": "f", "lineage_id": None, "origin": "cross_source",
        "evidence_key": "k", "input_ids": "[]", "title": "t", "card": "{}", "score": 0.1,
        "status": "shown", "dropped": "[]", "created_at": "2026-10-07T00:00:00Z"})
    assert cards.list_ideas(store)
    off = runtime(tmp_path, store, embedder, make_client, enabled=False)
    for app_rt, want in ((rt, {
            "topics": "/brb/#/settings?msg=", "connections": "/brb/#/settings/connections?msg=",
            "health": "/brb/#/settings/health?msg="}),
            (off, {"topics": "/topics?msg=", "connections": "/connections?msg=",
                   "health": "/health?msg="})):
        with client(app_rt) as web:
            # the grade forms (POST /ideas/<id>/verdict, POST /grade) are retired
            for gone in (web.post(f"/ideas/{idea}/verdict", data={"verdict": "useful"},
                                  follow_redirects=False),
                         web.post("/grade", data={"target": "idea", "target_id": str(idea),
                                                  "grade": "useful"}, follow_redirects=False)):
                assert gone.status_code in (404, 405)
            got = {
                "topics": web.post("/topics", data={"name": ""}, follow_redirects=False),
                "connections": web.post("/connections/mastodon/credentials",
                                        data={"token": ""}, follow_redirects=False),
                "health": web.post("/run/ingest", follow_redirects=False),
            }
        for key, prefix in want.items():
            r = got[key]
            assert r.status_code == 303, (key, r.status_code, r.text)
            assert r.headers["location"].startswith(prefix), (key, r.headers["location"])


def test_brb_config(tmp_path):
    base = (tmp_path / "kranto.yaml")
    head = "llm:\n  base_url: x\n  api_key_env: K\n  models: {judge: a, reason: b}\n"
    base.write_text(head)
    assert afk_config.load(tmp_path).brb == BrbConfig()
    base.write_text(head + "brb:\n  enabled: true\n  loop_home: ~/kranto-loop\n")
    cfg = afk_config.load(tmp_path).brb
    assert cfg.enabled and cfg.loop_home == "~/kranto-loop" and cfg.root is None
    for bad in ("brb: {enabled: yes please}", "brb: {nope: 1}", "brb: {harness: gpt}"):
        base.write_text(head + bad + "\n")
        with pytest.raises(ConfigError):
            afk_config.load(tmp_path)
    assert replace(BrbConfig(), enabled=True).harness == "claude-code"
