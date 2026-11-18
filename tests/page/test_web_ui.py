"""The web UI's toolchain: the page links the Vite build from its
manifest at this version's immutable address, a Kranto without a build says in one line how to
get one,
the wheel carries the build and never the sources, the supply chain stays pinned and small,
the component sources never write HTML, and ``brb ui`` sends the server's CSP."""
import json
import re
import threading
import tomllib
import urllib.request
from pathlib import Path

import pytest

from kranto.page.ui import api
from kranto.page.ui import server as server_mod
from kranto.page.ui.routes import static as static_routes
from kranto.page.ui.server import make_server

from .app_common import make_home

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "kranto" / "page" / "ui" / "web"
BUILT = (static_routes.APP_DIR / ".vite" / "manifest.json").is_file()


@pytest.fixture
def app(tmp_path):
    return api.App(None, "fake", make_home(tmp_path).home)


def page(app) -> str:
    code, ctype, body = api.handle("GET", "/", app=app)
    assert code == 200 and ctype.startswith("text/html")
    return body.decode()


def fake_build(d: Path, css=("app-c0ffee.css",)) -> Path:
    (d / ".vite").mkdir(parents=True)
    (d / "app-b4d9e1.js").write_text("export {};\n")
    for c in css:
        (d / c).write_text("html{}\n")
    (d / ".vite" / "manifest.json").write_text(json.dumps({static_routes.ENTRY: {
        "file": "app-b4d9e1.js", "isEntry": True, "src": static_routes.ENTRY,
        **({"css": list(css)} if css else {})}}))
    return d


def test_a_build_is_linked_at_this_versions_address(app, tmp_path, monkeypatch):
    monkeypatch.setattr(static_routes, "APP_DIR", fake_build(tmp_path / "app"))
    html, v = page(app), static_routes.VERSION
    assert f'<script type="module" src="static/v{v}/app/app-b4d9e1.js"></script>' in html
    assert f'<link rel="stylesheet" href="static/v{v}/app/app-c0ffee.css">' in html
    # theme.js first in the head (no flash of the wrong theme), the styles in the head, the
    # module in the body: the page is the build's
    assert html.index(f'src="static/v{v}/theme.js"') < html.index("app-c0ffee.css") < html.index("</head>")
    assert "<script>" not in html and html.count("<script") == 2
    for path in (f"/static/v{v}/app/app-b4d9e1.js", "/static/v0.0.1/app/app-c0ffee.css"):
        code, ctype, body, headers = api.handle_with_headers("GET", path, app=app)
        assert code == 200 and "immutable" in headers["cache-control"], path
        assert ctype.split(";")[0] in ("text/javascript", "text/css")
    # Vite's manifest and anything below app/ are never served
    for bad in (f"/static/v{v}/app/.vite/manifest.json", "/static/app/.vite/manifest.json",
                f"/static/v{v}/app/x/y.js", "/static/v1/app/../api.py"):
        assert api.handle("GET", bad, app=app)[0] == 404, bad


def test_every_page_a_person_reads_draws_in_the_chosen_appearance(app, tmp_path, monkeypatch):
    """Appearance reset: a page served without theme.js drew in the
    OS's scheme whatever Settings › Appearance said. Every HTML page Kranto serves to read loads
    theme.js in its head."""
    monkeypatch.setattr(static_routes, "APP_DIR", fake_build(tmp_path / "app"))
    for path in ("/", "/help"):
        code, ctype, body = api.handle("GET", path, app=app)
        html = body.decode()
        assert code == 200 and ctype.startswith("text/html"), path
        assert re.search(r'<script src="static/(v[^/]+/)?theme\.js"></script>', html), path
        assert html.index("theme.js") < html.index("</head>"), path


def test_a_build_without_css_links_only_its_module(app, tmp_path, monkeypatch):
    monkeypatch.setattr(static_routes, "APP_DIR", fake_build(tmp_path / "app", css=()))
    html = page(app)
    assert "/app/app-b4d9e1.js" in html and 'href="static/v' + static_routes.VERSION + \
        '/app/' not in html


def test_without_a_build_the_page_says_how_to_get_one(app, tmp_path, monkeypatch):
    """A Kranto installed from git, or a checkout nobody built, has no page to draw: "/" says so
    in one line with where to install a release (the owner's decision, 2026-10-15), never a
    blank page; so does a manifest that is broken or names a path."""
    monkeypatch.setattr(static_routes, "APP_DIR", tmp_path / "none")
    code, ctype, body = api.handle("GET", "/", app=app)
    assert code == 503 and ctype.startswith("text/html")
    text = body.decode()
    assert "installed without its web page" in text and static_routes.INSTALL in text
    assert "scripts/dev/build_ui.py" in text and "<script" not in text
    assert static_routes.INSTALL.endswith("kranto/blob/main/docs/setup.md#2-install")
    d = fake_build(tmp_path / "broken")
    monkeypatch.setattr(static_routes, "APP_DIR", d)
    for bad in ("{", json.dumps({"other.ts": {"file": "x.js"}}),
                json.dumps({static_routes.ENTRY: {"file": "../../api.py"}}),
                json.dumps({static_routes.ENTRY: {"file": "a.js", "css": ["<x>.css"]}})):
        (d / ".vite" / "manifest.json").write_text(bad)
        assert api.handle("GET", "/", app=app) == (code, ctype, body), bad


@pytest.mark.built_ui
@pytest.mark.skipif(not BUILT, reason="the web UI is not built: python3 scripts/dev/build_ui.py")
def test_the_real_build_is_linked_and_served(app):
    b = static_routes.built()
    assert b and re.fullmatch(r"app-[A-Za-z0-9_-]+\.js", b["js"])
    html = page(app)
    assert f'src="static/v{static_routes.VERSION}/app/{b["js"]}"' in html
    code, ctype, body = api.handle("GET", f"/static/v{static_routes.VERSION}/app/{b['js']}",
                                   app=app)
    assert code == 200 and ctype.startswith("text/javascript") and len(body) > 1000


def test_the_wheel_carries_the_build_and_never_the_sources():
    wheel = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"][
        "targets"]["wheel"]
    assert "src/kranto/page/ui/static/app/**" in wheel["artifacts"]
    assert "src/kranto/page/ui/web/**" in wheel["exclude"]
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "/src/kranto/page/ui/static/app/" in ignored and "/src/kranto/page/ui/web/node_modules/" in ignored


def test_the_supply_chain_is_pinned_and_small():
    """Exact versions, at most nine direct dependencies, a v3 lockfile whose every package
    comes from the npm registry with an integrity hash. Nine: the seven of the
    build and its checks, and Open in Claude Code's terminal, xterm.js and its fit addon (one
    project, the page's only runtime code from outside)."""
    pkg = json.loads((WEB / "package.json").read_text())
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert len(deps) <= 9, sorted(deps)
    for name, v in deps.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", v), f"{name}@{v} is not an exact version"
    lock = json.loads((WEB / "package-lock.json").read_text())
    assert lock["lockfileVersion"] == 3
    root = lock["packages"][""]
    assert {**root.get("dependencies", {}), **root.get("devDependencies", {})} == deps
    for path, p in lock["packages"].items():
        if not path:
            continue
        assert p["resolved"].startswith("https://registry.npmjs.org/"), path
        assert p["integrity"].startswith("sha512-"), path


def test_the_component_sources_never_write_html():
    """Svelte escapes every expression; nothing may bypass it."""
    sources = [f for f in (WEB / "src").rglob("*") if f.suffix in (".ts", ".svelte", ".js")]
    assert sources
    sinks = ("{@html", "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
             "eval(", "new Function", "srcdoc", "javascript:")
    for f in sources:
        text = f.read_text()
        for sink in sinks:
            assert sink not in text, f"{sink} in {f.relative_to(WEB)}"


def test_component_styles_use_tokens_only():
    """A component's colours are kranto.css's tokens (CONVENTIONS.md): no #hex, rgb( or hsl(
    literal in a <style> or a style attribute, so every theme and both bases hold (test_looks
    checks the tokens' contrast)."""
    literal = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    files = list((WEB / "src").rglob("*.svelte"))
    assert len(files) >= 10
    for f in files:
        text = f.read_text()
        for style in re.findall(r"<style[^>]*>(.*?)</style>", text, re.S) + re.findall(r'style="([^"]*)"', text):
            assert not literal.search(style), f.name


def test_svelte_runs_in_runes_mode_and_dev_stays_on_loopback():
    assert "runes: true" in (WEB / "svelte.config.js").read_text()
    cfg = (WEB / "vite.config.ts").read_text()
    assert 'host: "127.0.0.1"' in cfg and "0.0.0.0" not in cfg and "strictPort: true" in cfg
    assert "polyfill: false" in cfg                  # no inline script for the CSP to refuse


def test_brb_ui_sends_krantos_csp(app, tmp_path):
    srv = make_server(None, port=0, harness="fake", loop_home=app.loop_home)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path in ("/", "/api/header", "/static/theme.js"):
            with urllib.request.urlopen(base + path, timeout=30) as r:
                csp = r.headers["Content-Security-Policy"]
            assert csp == server_mod.PAGE_CSP, path
            assert "script-src 'self';" in csp and "unsafe-inline" not in csp.split(
                "style-src")[0], path
    finally:
        srv.shutdown()
        srv.server_close()


def test_krantos_csp_is_the_same_policy():
    """The page meets one policy under either server: brb ui's is the server's, read from its
    source when the checkout sits beside this one (CI checks out the page alone)."""
    afk = ROOT.parent / "kranto" / "src" / "kranto" / "web" / "app.py"
    if not afk.is_file():
        pytest.skip("no server checkout beside this one")
    text = afk.read_text()
    block = text[text.index('"Content-Security-Policy": (') + 28:]
    block = block[:block.index("),")]
    policy = "".join(re.findall(r'^\s*"([^"]*)"', block, re.M))
    assert policy == server_mod.PAGE_CSP
