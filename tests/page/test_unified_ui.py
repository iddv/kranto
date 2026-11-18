"""The unified UI (DESIGN-v3.md, phase 1): ``api.handle`` as one plain function,
its pages and static files, and the rules the page's sources keep. The snapshot, the loop's words
and the builds' pages left with the factory."""
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kranto.page.ui import api
from kranto.page.ui.routes import static as static_routes
from kranto.page.ui.server import make_server

from .app_common import make_home
from .webui import everything, src

UI = Path(api.__file__).parent


def call(app, method, path, query=None, body=None):
    code, ctype, data = api.handle(method, path, query,
                                   json.dumps(body).encode() if body is not None else None,
                                   app=app)
    return code, ctype, (json.loads(data) if ctype.startswith("application/json") else data)


@pytest.fixture
def app(tmp_path):
    """Hosted, as the server mounts it: the host passes its own URL."""
    return api.App(None, "fake", make_home(tmp_path).home, kranto_url="http://127.0.0.1:9")


# -- the one function -----------------------------------------------------------------------
def test_handle_serves_the_pages_and_static_files(app):
    code, ctype, html = call(app, "GET", "/")
    assert code == 200 and ctype.startswith("text/html") and b"<title>Kranto</title>" in html
    v = static_routes.VERSION.encode()
    assert b"<script>" not in html
    assert b'<script type="module" src="static/v' + v + b'/app/app-' in html          # the build
    for a in (b"theme.js", b"kranto.css", b"looks.css"):                  # this version's address
        assert b'"static/v' + v + b"/" + a + b'"' in html and b'"static/' + a + b'"' not in html
    # the old pages forward into the app (O-2), relative to wherever the UI is mounted
    for page, to in (("/classic", b"./#/"), ("/classic/", b"../#/"),
                     ("/loop", b"./#/"), ("/loop/", b"../#/")):
        code, ctype, body = call(app, "GET", page)
        assert code == 200 and ctype.startswith("text/html"), page
        assert b'http-equiv="refresh" content="0; url=' + to + b'"' in body, page
        assert b"<script" not in body and b"<style>" not in body
    for gone in ("classic.js", "classic.css", "loop.js", "loop.css"):
        assert call(app, "GET", "/static/" + gone)[0] == 404, gone
    for name, kind in (("theme.js", "text/javascript"), ("kranto.css", "text/css")):
        code, ctype, _ = call(app, "GET", "/static/" + name)
        assert code == 200 and ctype.startswith(kind), name
    for bad in ("/static/../api.py", "/static/%2e%2e/api.py", "/static/nope.js", "/static/"):
        assert call(app, "GET", bad)[0] == 404, bad


def test_the_versioned_static_path_serves_the_same_files_and_may_be_cached_for_good(app):
    """S-3b (review F-6): static/v<version>/ is the page's own address for its scripts and
    styles; any version segment serves today's file; handle_with_headers marks it immutable,
    and nothing else."""
    plain = call(app, "GET", "/static/theme.js")
    for path in (f"/static/v{static_routes.VERSION}/theme.js", "/static/v0.0.1/theme.js"):
        assert call(app, "GET", path) == plain, path
        code, ctype, body, headers = api.handle_with_headers("GET", path, app=app)
        assert (code, body) == (200, plain[2]) and "immutable" in headers["cache-control"]
    for path in ("/", "/static/theme.js", "/api/header", "/static/v1/nope.js"):
        assert api.handle_with_headers("GET", path, app=app)[3] == {}, path
    # the old page's module is gone (the build is the page)
    for bad in ("/static/v1/../api.py", "/static/v1/x/y/z.js", "/static/v/theme.js",
                "/static/ui/main.js", f"/static/v{static_routes.VERSION}/ui/main.js"):
        assert call(app, "GET", bad)[0] == 404, bad
    assert call(app, "GET", "/nothing")[0] == 404
    assert call(app, "PUT", "/")[0] == 405
    assert call(app, "GET", "/api/header", "x=1")[2]["api_version"] == api.API_VERSION


def test_handle_never_raises(app):
    code, _, body = api.handle("POST", "/api/term/settings", None, b"{not json", app=app)
    assert code == 400 and b"JSON" in body
    code, _, body = api.handle("POST", "/api/term/settings", None, b"[1]", app=app)
    assert code == 400
    assert call(app, "POST", "/api/start", body={"dir": "/etc"})[0] == 404
    assert call(app, "GET", "/api/build", {"dir": "/etc"})[0] == 404
    assert call(app, "GET", "/api/events", {"dir": ["/etc"]})[0] == 404


def test_an_error_answers_its_id_and_never_its_words(app, monkeypatch):
    def boom(self):
        raise RuntimeError("words only the log may hold")
    monkeypatch.setattr(api.App, "header", boom)
    code, _, body = api.handle("GET", "/api/header", app=app)
    out = json.loads(body)
    assert code == 500 and "words only the log may hold" not in body.decode()
    assert re.fullmatch(r"[0-9a-f]{8}", out["error_id"]) and out["exception"] == "RuntimeError"


def test_the_page_never_writes_html():
    js = everything()
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in js, sink
    # every URL of the page's own API is relative: the page works at / and under /brb/.
    # The absolute ones are the server's, served next to /brb/ (section 5).
    assert not re.search(r"""["'`]/api/(?!status|catalog|sources|topics|connections|browser/|"""
                         r"""health|observations|map|clusters|themes/|rollups|feedback|review/|learning|grades/summary|evals|explain|setup|"""
                         r"""ideas|settings/|search\?|today|seen|spend/topics|prompts|archive|update|hold|whoami|tokens|watch/resume|"""
                         r"""telemetry/|features|f/|requests[/?]|tickets[/?]|asks\b|shell|home\b|cubs\b|broker\b|newsletter\b|post\b|"""
                         r"""activity/dismiss|errors/|verbs/recent|prepared\b|assistant/global|prose\b)""",
                         js)
    assert not re.search(r"""["'`]/(static/|loop["'`/]|classic)""", js)
    # links built from data (card evidence, a repo url) are http(s) or relative only
    assert "export const safeHref = " in js and "/^(https?:|#|" in js


def test_host_forms_report_a_half_that_did_not_change():
    """The server's pause and resume answer JSON to a request that asks for it, with 502 and
    the reason when only one half changed; hostForm reads that instead of trusting a
    followed redirect. A notice a server form redirects with (#/...?msg=) shows once."""
    # pressed in lib/app/data.test.ts and lib/app/route.test.ts
    js = everything()
    assert "r.q.msg" in js and '"emsg:" + r.q.message' in js


def test_settings_pages_for_sources_and_connections():
    """ section 4: one vertical menu, a page per entry, a source and a
    connection one level down; the server's JSON drives them; nothing shows a token."""
    js = everything()
    defs = src("pages/settings/pagedefs.ts")
    titles = re.findall(r'title: "([^"]+)"', defs)
    kept = [t for t in titles if t in ("Watching", "Posting", "Spend", "System", "Appearance")]
    assert kept == ["Watching", "Posting", "Spend", "System", "Appearance"], titles
    assert "function addTopic(" not in js and 'id: "add-topic", onclick' not in js
    assert "function vSettings(" not in js, "every Settings page is a moved component"
    for endpoint in ("/api/catalog", "/api/sources", "/api/sources/preview", "/api/connections",
                     "/api/topics", "/connections/${key}/start"):
        assert endpoint in js, endpoint
    for f in ("SourcesList", "SourcesPane", "SourcePane", "CatalogPane", "SrcLine", "ConnectionsList", "ConnectionsPane"):
        assert src(f"pages/settings/{f}.svelte"), f
    assert 'register("settings", {' in src("pages/index.ts") and 'register("settings/sources", {' in src("pages/index.ts")
    assert "ConnectionsList" not in src("pages/settings/SourcesList.svelte")
    assert "Approve and watch" in js and "Reddit's feeds stop on 13 Nov 2026" in js
    # (Feedback's scrub names them only to take them out of what it sends: FB)
    assert not re.search(r"access_token|refresh_token|client_secret", js.replace(src("ui/feedback.ts"), ""))
    assert "client_secret|access_token|refresh_token" in src("ui/feedback.ts")
    # A sign-in leaves for the provider by navigation, never a form post (form-action 'self').
    assert "location.href = x.authorize_url" in js


def test_every_section_and_settings_page_is_in_the_app():
    """The owner's rule: every section is a client-side route, so switching never reloads,
    and nothing in the app sends the owner to one of the server's server-rendered pages."""
    js = everything()
    views = re.search(r"const VIEWS = new Set\(\[(.*?)\]\)", js).group(1)
    assert {"review", "topics", "ideas", "library", "settings", "welcome", "news",
            "activity"} <= set(re.findall(r'"(\w+)"', views))
    assert "const TABS" not in js and "tabOf" not in js and 'class: "tab"' not in js
    jinja = (r"""["'`]/(library|watches|health|map|clusters|obs/|rollups|topics|connections)"""
             r"""(?![^"'`]*/(start|device|poll|callback|credentials))""")   # sign-ins: POSTs
    assert not re.findall(jinja, js), re.findall(jinja, js)
    assert "location.href = \"/" not in js
    lib = re.search(r"const LIB: \[string, string\]\[\] = (\[.*?\]);\n", js).group(1)
    assert [w for _, w in re.findall(r'\["([a-z]*)", "([^"]+)"\]', lib)] == [
        "Observations", "Map", "Clusters", "Rollups"]
    assert '"Library pages"' not in js
    for name in ("ObsList", "ObsPane", "MapList", "MapPane", "ClustersList", "ThemePane", "RollupsList",
                 "RollupPane"):
        assert f'import("./library/{name}.svelte")' in src("pages/index.ts"), name
    for endpoint in ("/api/health", "/api/map", "/api/clusters", "/api/feedback", "/api/rollups"):
        assert endpoint in js, endpoint
    assert "/api/watches" not in js  # watches are retired
    assert "the server's health page" not in js and "Open in the server" not in js
    assert "tablist" not in js and 'role: "tab"' not in js


def test_connection_pages_for_every_provider_flow():
    """ phases C and D: a page per provider drawn from the server's
    PROVIDER_INFO (its steps and fields), pasted secrets in password inputs and never
    kept, Bluesky only from 127.0.0.1, YouTube's own client before Connect."""
    js = everything()
    for endpoint in ("/api/connections/${p.key}/credentials", "/connections/${p.key}/device",
                     "/connections/${key}/device/poll", "/api/connections/${key}/credentials"):
        assert endpoint in js, endpoint
    how = re.search(r"const HOW: Record<string, string> = \{.*?\};", js).group(0)
    for flow in ("browser", "both", "paste", "client"):
        assert f"{flow}: " in how, flow
    pane = src("pages/settings/ConnectionsPane.svelte")
    assert 'type={f.secret ? "password" : "text"} autocomplete="off"' in pane
    assert "p.redirect_host" in js, "Bluesky's sign-in only from 127.0.0.1"
    assert "p.client_set" in js and "{ clear: true }" in js
    assert "device_steps" in js and "connections.github_client_id" in js


def test_the_default_app_opens_no_task_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "loop.yaml").write_text(f"tasks_dir: {tmp_path / 'tasks'}\n")
    monkeypatch.setattr(api, "_default", None)
    a = api.default_app()
    assert a.root is None and not (tmp_path / "tasks").exists()
    assert api.handle("GET", "/api/header")[0] == 200


# -- brb ui on its own still works -------------------------------------------------------------
def test_brb_ui_alone_serves_the_unified_page(app):
    srv = make_server(None, port=0, harness="fake", loop_home=app.loop_home)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/", timeout=30) as r:
            assert b'<script type="module" src="static/v' in r.read()
            assert r.headers["X-Frame-Options"] == "DENY"
        with urllib.request.urlopen(base + "/api/header", timeout=30) as r:
            assert json.loads(r.read())["api_version"] == api.API_VERSION
        req = urllib.request.Request(base + "/api/term/settings",
                                     b'{"key": "term.enabled", "value": true}',
                                     {"Content-Type": "application/json",
                                      "Origin": "http://elsewhere.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 403
        assert "term" not in (app.loop_home / "loop.yaml").read_text()
        req = urllib.request.Request(base + "/", method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200 and r.read() == b""
    finally:
        srv.shutdown()
        srv.server_close()
