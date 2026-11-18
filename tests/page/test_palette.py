"""Kranto palette, read from kranto.css itself: every foreground and
background pair the UI uses meets its WCAG 2.1 minimum in both themes (4.5:1 for text, 3:1
for icons, focus rings and meter fills), the two dark blocks agree, and the brand assets the
shell links to are served. U/palette.py, as a test."""
import re
from pathlib import Path

import pytest

from kranto.page.ui import api

from .webui import css, everything, src, static

UI = Path(api.__file__).parent
CSS = css()
HTML = (UI / "app.html").read_text()


def block(selector: str, css: str = CSS) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
    assert m, selector
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", m.group(1)))


LIGHT = block(":root")
DARK = block(":root[data-theme=dark]")
DARK_OS = block(":root:not([data-theme=light])",
                CSS[CSS.index("@media (prefers-color-scheme: dark)"):])


def lum(c: str) -> float:
    def f(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(int(c[i:i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT, NONTEXT = 4.5, 3.0
SURFACES = ("bg", "box", "subtle", "head")     # the page, a box, hover, a box head and the header
PAIRS = [(fg, bg, TEXT) for fg in ("text", "muted", "ink3", "link", "blue", "violet", "green", "amber", "red")
         for bg in SURFACES]                     # ink3: the workspace's mono meta
PAIRS += [
    ("text", "inset", TEXT), ("muted", "inset", TEXT), ("text", "counter", TEXT), ("text", "btn", TEXT),
    ("text", "blue-wash", TEXT), ("text", "violet-wash", TEXT),       # the current nav entry, a chip
    ("muted", "violet-wash", TEXT), ("muted", "blue-wash", TEXT),     # the palette's selected row's detail
    ("blue", "blue-wash", TEXT), ("violet", "violet-wash", TEXT), ("green", "green-wash", TEXT),
    ("amber", "amber-wash", TEXT), ("red", "red-wash", TEXT),         # ink on its own flash
    ("text", "amber-wash", TEXT), ("text", "red-wash", TEXT), ("text", "green-wash", TEXT),
    ("primary-text", "primary", TEXT),
    *[("chip-text", p, TEXT) for p in ("blue-pastel", "violet-pastel", "green-pastel",
                                       "amber-pastel", "red-pastel")],   # chips, pressed glyphs
    ("meter", "bg", NONTEXT), ("meter", "box", NONTEXT), ("meter", "inset", NONTEXT),
    ("focus", "bg", NONTEXT), ("focus", "box", NONTEXT), ("focus", "head", NONTEXT),
    ("green", "inset", NONTEXT), ("red", "inset", NONTEXT),            # a status icon on a pressed row
]


@pytest.mark.parametrize("name,P", [("light", LIGHT), ("dark", DARK)])
def test_every_pair_meets_its_minimum(name, P):
    low = [(fg, bg, round(ratio(P[fg], P[bg]), 2), need) for fg, bg, need in PAIRS
           if ratio(P[fg], P[bg]) < need]
    assert not low, f"{name}: {low}"


def test_the_two_dark_blocks_agree_and_cover_every_light_token():
    assert DARK == DARK_OS
    assert set(DARK) == set(LIGHT)


def test_the_light_theme_reads_as_pastel():
    """The owner asked for pastel from the logo (the reviewer's change 1): a lavender page,
    box heads in the blue wash, and the logo's hues as ink and as pastel."""
    bg = LIGHT["bg"]
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    assert b > r and b > g and bg.lower() != "#ffffff", "a faint lavender page"
    assert LIGHT["head"] == LIGHT["blue-wash"]
    assert re.search(r"\.box-h \{[^}]*background: var\(--head\)", CSS)
    assert re.search(r"header\.hd \{[^}]*background: var\(--head\)", CSS)
    assert (LIGHT["blue"], LIGHT["violet"], LIGHT["text"]) == ("#3d44d4", "#6a3fd6", "#1c1c4b")
    assert (DARK["bg"], DARK["blue"], DARK["violet"]) == ("#0b0b2a", "#aeb6ff", "#cdb8ff")
    # pressed states and chips are pastel with navy ink, plus aria-pressed: never colour alone
    for rule in (r"\.chip\[aria-pressed=true\] \{[^}]*var\(--violet-pastel\)",
                 r"\.btn\[aria-pressed=true\] \{[^}]*var\(--blue-pastel\)",
                 r"\.grade button\[aria-pressed=true\] \{[^}]*var\(--green-pastel\)",
                 r"\.grade button\.dn\[aria-pressed=true\] \{[^}]*var\(--red-pastel\)"):
        assert re.search(rule, CSS), rule


def test_the_terminal_lifts_any_colour_under_aa_against_its_background():
    """Open in Claude Code's terminal is dark in both themes, but the program picks its colours:
    Claude Code in its light theme draws near-black text on it (BG: "dark text on black"). xterm's
    minimumContrastRatio lifts every colour under 4.5:1 against the cell it is drawn on."""
    m = re.search(r"minimumContrastRatio:\s*([\d.]+)", src("term/TerminalPanel.svelte"))
    assert m and float(m.group(1)) >= 4.5
    assert ratio(DARK["term-fg"], DARK["term-bg"]) >= 4.5 and ratio(LIGHT["term-fg"], LIGHT["term-bg"]) >= 4.5


def test_the_theme_choice_is_applied_before_the_first_paint():
    js = static("theme.js")
    assert 'localStorage.getItem("kranto.theme")' in js and 'setAttribute("data-theme", t)' in js
    assert HTML.index('src="static/theme.js"') < HTML.index('href="static/kranto.css"')
    app = everything()
    assert "data-theme-choice={k}" in src("pages/settings/AppearancePane.svelte")
    assert '[["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]]' in app


def test_the_shell_links_the_favicon_and_the_manifest():
    for ref in ("static/brand/favicon.ico", "static/brand/favicon-32.png",
                "static/brand/favicon-16.png", "static/brand/icon-180.png",
                "static/manifest.webmanifest"):
        assert f'href="{ref}"' in HTML, ref
        assert (UI / ref).is_file(), ref
    for n in ("icon-192.png", "icon-512.png", "mark.svg", "favicon-48.png"):
        assert (UI / "static" / "brand" / n).is_file(), n
    # one mark everywhere: the top bar draws static/brand/mark.svg's shapes inline
    mark = (UI / "static" / "brand" / "mark.svg").read_text()
    assert 'rx="14"' in mark and 'rx="14"' in src("shell/Brand.svelte")
    # the .ico carries its own 16, 32 and 48 px frames (its directory: 6 bytes, then 16 per frame)
    ico = (UI / "static" / "brand" / "favicon.ico").read_bytes()
    n = int.from_bytes(ico[4:6], "little")
    assert {ico[6 + 16 * i] for i in range(n)} >= {16, 32, 48}


def test_brand_assets_are_served_and_nothing_else_one_level_down(tmp_path):
    app = api.App(tmp_path / "tasks", "fake", tmp_path / "home")
    for name, kind in (("brand/favicon.ico", "image/x-icon"), ("brand/icon-192.png", "image/png"),
                       ("brand/favicon-48.png", "image/png"), ("theme.js", "text/javascript"),
                       ("manifest.webmanifest", "application/manifest+json")):
        code, ctype, _ = api.handle("GET", "/static/" + name, None, None, app=app)
        assert code == 200 and ctype.startswith(kind), name
    for bad in ("/static/brand/../app.html", "/static/brand/", "/static/brand", "/static/x/main.js",
                "/static/brand/brand/icon-192.png", "/static/brand/nope.png", "/static/ui/",
                "/static/ui/../app.html", "/static/ui/ui/main.js", "/static/app.js"):
        assert api.handle("GET", bad, None, None, app=app)[0] == 404, bad
