"""Kranto brand on the server's side (UI-v4.md section 1.4): every server-rendered page links
the favicon, the files are in the static directory, and the README opens with the name."""
from pathlib import Path

import kranto.web.app as web

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(web.__file__).parent


def test_the_base_template_links_the_favicon_and_the_files_exist():
    base = (WEB / "templates" / "base.html").read_text()
    for name in ("favicon.ico", "favicon-32.png", "favicon-16.png", "icon-180.png"):
        assert f'href="/static/{name}"' in base, name
        assert (WEB / "static" / name).is_file(), name
    assert base.index('rel="icon"') < base.index("</head>")
    # one Kranto everywhere: the simplified mark is retired to docs/brand/history/
    assert "mark-navy.svg" not in base and not (WEB / "static" / "mark-navy.svg").exists()


def test_the_mark_is_one_svg_and_no_bear_picture_is_shipped():
    """One plain mark (the page's static/brand/mark.svg) and the icons drawn from it; docs/brand/
    holds the page that describes them and the README's wordmark (light and dark), nothing else;
    and the README opens with the wordmark, named."""
    brand = ROOT / "src" / "kranto" / "page" / "ui" / "static" / "brand"
    assert (brand / "mark.svg").is_file() and (brand / "icon-512.png").is_file()
    docs_brand = ROOT / "docs" / "brand"
    assert sorted(p.name for p in docs_brand.rglob("*")) == [
        "README.md", "wordmark-dark.svg", "wordmark.svg"]
    for svg in ("wordmark.svg", "wordmark-dark.svg"):
        text = (docs_brand / svg).read_text()
        assert "<image" not in text and 'aria-label="kranto"' in text, svg
    head = (ROOT / "README.md").read_text().split("\n\n", 1)[0]
    assert head.startswith("<picture>") and 'alt="kranto"' in head and "docs/brand/wordmark" in head


def test_the_shared_look_uses_the_v4_palette():
    css = (WEB / "static" / "kranto-afk.css").read_text()
    assert "--ink: #1c1c4b" in css and "--accent: #3d44d4" in css and "--bg: #0b0b2a" in css
    assert "color: var(--b-primary-text)" in css
