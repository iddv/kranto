"""The themes (Settings › Appearance, AP; the whole page, TH), read from the stylesheets themselves: every
theme is a complete token set on both bases (kranto.css's light and dark, plus the theme's own tokens from
static/looks.css: the sidebar, the accent and, but for the default and High contrast, a page tinted in
its hue), and every pair the UI draws meets WCAG 2.1 AA there: body text 4.5:1, icons,
focus rings, badges and fills 3:1. High contrast holds its text to AAA (7:1). The picker, the
first-paint script and the pages all name the same themes, and none of them is called by another
product's name. No browser: a pure-Python parser over the CSS.

``python tests/page/test_looks.py`` prints every theme's numbers."""
import re
from pathlib import Path

import pytest

from kranto.page.ui import api

from .webui import css, everything, src, static

UI = Path(api.__file__).parent
CSS = css()
LOOKS_CSS = static("looks.css")
JS = everything()
THEME_JS = static("theme.js")
HEX = r"#[0-9a-fA-F]{6}\b"


def tokens(body: str) -> dict[str, str]:
    return {k: v.lower() for k, v in re.findall(r"--([a-z0-9-]+):\s*(" + HEX + ")", body)}


def body_of(selector: str, css: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
    assert m, selector
    return m.group(1)


MEDIA = CSS.index("@media (prefers-color-scheme: dark)")
BASE = {"light": tokens(body_of(":root", CSS)) | tokens(body_of(":root", CSS[CSS.index("/* the library's map"):])),
        "dark": tokens(body_of(":root[data-theme=dark]", CSS)) | tokens(body_of(":root[data-theme=dark]", CSS[CSS.index("/* the library's map"):]))}
IDS = re.findall(r":is\(:root, \.pv\)\[data-look=([a-z]+)\] \{", LOOKS_CSS)
BUILT_IN = [i for i in IDS if i not in ("kranto", "custom")]


def look(id: str) -> dict[str, dict[str, str]]:
    sel = f":is(:root, .pv)[data-look={id}]"
    light, dark = body_of(sel, LOOKS_CSS), body_of(sel + "[data-theme=dark]", LOOKS_CSS)
    media = LOOKS_CSS[LOOKS_CSS.index(sel + "[data-theme=dark]"):]
    media = media[media.index("@media (prefers-color-scheme: dark)"):]
    return {"light": light, "dark": dark, "dark-os": body_of(sel + ":not([data-theme=light])", media)}


def resolved(id: str, base: str) -> dict[str, str]:
    """What the page draws with: the base's tokens, then the theme's (its light block applies on both
    bases; its dark block wins on the dark one)."""
    b = look(id)
    out = BASE[base] | tokens(b["light"])
    return out | tokens(b["dark"]) if base == "dark" else out


def lum(c: str) -> float:
    def f(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(int(c[i:i + 2], 16) / 255) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT, UI_, AAA = 4.5, 3.0, 7.0
SIDE = ("side-bg", "side-text", "side-muted", "side-hover", "side-active", "side-active-text", "side-bar", "side-border",
        "side-badge", "side-badge-text", "side-dot", "side-link", "side-new", "side-wait", "side-focus")
ACCENT = ("link", "primary", "primary-text", "focus", "meter", "sel", "selbar")
SURFACES = ("bg", "box", "subtle", "head")       # the page, a card, hover, a card's head and the header
MORE_SURFACES = ("inset", "btn", "sel")          # code and wells, a button, the selected row
# a tinted theme (TH) colours the whole page, not only the sidebar: its surfaces, borders and ink, and
# the scrollbars' thumbs (--scroll on the page, --side-scroll in the navigator; the default and High
# contrast keep the browser's own)
PAGE = ("bg", "box", "subtle", "head", "inset", "border", "border-2", "btn", "btn-border", "counter", "text", "muted", "ink3")
SCROLL = ("scroll", "side-scroll")
# (label, fg, bg, minimum): the content, as tests/page/test_palette.py checks the default, then the sidebar
PAIRS = [(f"{fg} on {bg}", fg, bg, TEXT) for fg in ("text", "muted", "ink3", "link") for bg in SURFACES + MORE_SURFACES]
PAIRS += [(f"status {fg} on {bg}", fg, bg, TEXT) for fg in ("blue", "violet", "green", "amber", "red") for bg in SURFACES + MORE_SURFACES]
PAIRS += [(f"flash {k}'s border on the page", k, "bg", UI_) for k in ("blue", "amber", "red")]
PAIRS += [(f"focus ring on {s}", "focus", s, UI_) for s in ("subtle", "inset", "btn", "sel")]
PAIRS += [(f"flash {k}: {fg} on {k}-wash", fg, f"{k}-wash", TEXT) for k in ("blue", "violet", "green", "amber", "red") for fg in (k, "text")]
PAIRS += [
    ("text on inset (code)", "text", "inset", TEXT), ("muted on inset", "muted", "inset", TEXT), ("text on counter", "text", "counter", TEXT),
    ("text on a button", "text", "btn", TEXT), ("text on a selected row", "text", "sel", TEXT), ("muted on a selected row", "muted", "sel", TEXT),
    ("primary button text", "primary-text", "primary", TEXT),
    *[(f"chip on {p}", "chip-text", p, TEXT) for p in ("blue-pastel", "violet-pastel", "green-pastel", "amber-pastel", "red-pastel")],
    ("meter on box", "meter", "box", UI_), ("meter on inset", "meter", "inset", UI_), ("selection bar on box", "selbar", "box", UI_),
    *[(f"focus ring on {s}", "focus", s, UI_) for s in ("bg", "box", "head")],
    ("status green on inset", "green", "inset", UI_), ("status red on inset", "red", "inset", UI_),
    # the sidebar
    ("sidebar text", "side-text", "side-bg", TEXT), ("sidebar muted", "side-muted", "side-bg", TEXT),
    ("sidebar text on hover", "side-text", "side-hover", TEXT), ("sidebar muted on hover", "side-muted", "side-hover", TEXT),
    ("current row's text", "side-active-text", "side-active", TEXT), ("sidebar link", "side-link", "side-bg", TEXT),
    ("sidebar new count", "side-new", "side-bg", TEXT), ("sidebar waiting count", "side-wait", "side-bg", TEXT),
    ("badge's number", "side-badge-text", "side-badge", TEXT), ("badge on the sidebar", "side-badge", "side-bg", UI_),
    ("dot on the sidebar", "side-dot", "side-bg", UI_), ("focus ring on the sidebar", "side-focus", "side-bg", UI_),
    # the navigator as icons: its counts are badges, the sidebar's own colours turned round
    ("icon badge: new", "side-bg", "side-new", TEXT), ("icon badge: waiting", "side-bg", "side-wait", TEXT),
    ("icon badge: a size", "side-text", "side-hover", TEXT), ("icon badge: Desk's", "side-badge-text", "side-badge", TEXT),
    ("a topic's letter", "side-text", "side-hover", TEXT), ("the current topic's letter", "side-active-text", "side-active", TEXT),
]
# High contrast: the words are AAA, wherever they sit
AAA_PAIRS = [(f"{fg} on {bg}", fg, bg) for fg in ("text", "muted") for bg in (*SURFACES, *MORE_SURFACES)] + [("sidebar text", "side-text", "side-bg")]


def numbers(id: str, base: str) -> list[tuple[str, float, float]]:
    P = resolved(id, base)
    out = [(w, ratio(P[fg], P[bg]), need) for w, fg, bg, need in PAIRS]
    # the current row stands out: its bar or its fill against the sidebar
    out.append(("current row against the sidebar", max(ratio(P["side-bar"], P["side-bg"]), ratio(P["side-active"], P["side-bg"])), UI_))
    if id == "contrast":
        out += [(w + " (AAA)", ratio(P[fg], P[bg]), AAA) for w, fg, bg in AAA_PAIRS]
    return out


CASES = [(i, b) for i in IDS if i != "custom" for b in ("light", "dark")]


@pytest.mark.parametrize("id,base", CASES)
def test_every_pair_meets_its_minimum_in_every_theme_on_both_bases(id, base):
    low = [(w, round(r, 2), need) for w, r, need in numbers(id, base) if r < need]
    assert not low, f"{id} on {base}: {low}"


def test_there_are_at_least_ten_themes_besides_the_default_and_custom():
    assert len(BUILT_IN) >= 10 and len(set(IDS)) == len(IDS)
    assert IDS[0] == "kranto" and IDS[-1] == "custom" and "contrast" in BUILT_IN


@pytest.mark.parametrize("id", [i for i in IDS if i != "custom"])
def test_a_theme_is_a_whole_token_set_on_both_bases(id):
    b = look(id)
    light, dark, dark_os = tokens(b["light"]), tokens(b["dark"]), tokens(b["dark-os"])
    assert dark == dark_os, "the chosen dark and the OS's dark agree"
    assert set(light) == set(dark), "both bases set the same tokens"
    assert set(SIDE) | set(ACCENT) <= set(light), set(SIDE) | set(ACCENT) - set(light)
    assert not set(light) - set(SIDE) - set(ACCENT) - set(SCROLL) - set(BASE["light"]), "nothing the base does not define"
    for base in ("light", "dark"):
        assert set(BASE[base]) <= set(resolved(id, base)), "every token kranto.css defines, with the theme's on top"
    for part, scheme in (("light", "light"), ("dark", "dark"), ("dark-os", "dark")):
        assert f"color-scheme: {scheme};" in b[part], (id, part)          # form controls and scrollbars follow
        assert re.search(r"--side-scheme: (light|dark);", b[part]), (id, part)


TINTED = [i for i in BUILT_IN if i != "contrast"]


def rgb(c: str) -> tuple[int, ...]:
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


@pytest.mark.parametrize("id", TINTED)
def test_a_tinted_theme_colours_the_whole_page_in_quiet_neutrals(id):
    """Choosing a theme changes the page, the panes and the cards, not only the sidebar: each sets the
    page's own tokens on both bases, in the theme's hue, as tinted neutrals (no saturated fills), a
    light page with near-white cards on the light base and a deep page with lighter panes on the dark."""
    for base in ("light", "dark"):
        P = tokens(look(id)[base])
        assert set(PAGE) | set(SCROLL) <= set(P), (base, set(PAGE) | set(SCROLL) - set(P))
        assert P["bg"] != BASE[base]["bg"] and P["box"] != BASE[base]["box"], "the page is the theme's, not the base's"
        for s in ("bg", "box", "subtle", "head", "inset", "btn"):
            r = rgb(P[s])
            assert max(r) - min(r) <= 32, (base, s, P[s])           # a tint, never a fill: no more than the default's navy
        if base == "light":
            assert lum(P["bg"]) > 0.82 and lum(P["box"]) > 0.95 and lum(P["box"]) > lum(P["bg"]), (P["bg"], P["box"])
        else:
            assert lum(P["bg"]) < 0.02 and lum(P["bg"]) < lum(P["box"]) < 0.03, (P["bg"], P["box"])
        assert ratio(P["sel"], P["box"]) > 1.12, "the selected row stands out from a card"
        assert ratio(P["subtle"], P["box"]) > 1.04, "a hover shows"
    css = LOOKS_CSS[LOOKS_CSS.index("/* the scrollbars"):]
    assert ":root[data-look] { scrollbar-color: var(--scroll) transparent; }" in css
    assert ":root[data-look] nav#nav { scrollbar-color: var(--side-scroll) transparent; }" in css


@pytest.mark.parametrize("id", ["kranto", "contrast"])
def test_the_default_and_high_contrast_keep_the_browsers_scrollbars(id):
    for part in look(id).values():
        assert not set(tokens(part)) & set(SCROLL)


def test_the_default_is_the_base_exactly():
    """The lavender default is html with no data-look: kranto.css alone. Its block in looks.css exists
    only for its card in the picker and repeats the base's values."""
    alias = body_of(":root", CSS[CSS.index("/* the navigator's tokens"):])
    expect = {"side-bg": "bg", "side-text": "text", "side-muted": "muted", "side-hover": "subtle", "side-active": "blue-wash",
              "side-active-text": "text", "side-bar": "blue", "side-border": "border", "side-link": "link", "side-new": "blue",
              "side-wait": "amber", "side-focus": "focus", "link": "link", "primary": "primary", "primary-text": "primary-text",
              "focus": "focus", "meter": "meter", "sel": "blue-wash", "selbar": "blue"}
    for base in ("light", "dark"):
        P = tokens(look("kranto")[base])
        for k, v in expect.items():
            assert P[k] == BASE[base][v], (base, k)
        # its card in the picker draws the base's own page, whichever theme the page around it has
        for k in (*PAGE, "green", "green-wash"):
            assert P[k] == BASE[base][k], (base, k)
    for k in ("side-bg", "side-text", "side-hover", "side-active", "side-bar", "side-border"):
        assert f"--{k}: var(--" in alias, k
    # the navigator draws with the side tokens, and the badge and dot only under a theme
    for rule in (r"nav#nav \{[^}]*background: var\(--side-bg\)", r"#nav \.ni\.on \{[^}]*var\(--side-active\)[^}]*var\(--side-bar\)",
                 r"#nav \.ni:hover \{[^}]*var\(--side-hover\)", r":root\[data-look\] #nav \.ct\.hot \{[^}]*var\(--side-badge\)",
                 r":root\[data-look\] #nav \.ni \.live \{[^}]*var\(--side-dot\)", r"#nav \.ni \.live \{ display: none; \}"):
        assert re.search(rule, CSS), rule


# a custom theme's page (TH), worked out as app.js's customPage does, from the table it keeps
_CP = re.search(r"const CUSTOM_PAGE[^=]*= \{(.*?)\};\n", JS, re.S).group(1)
CUSTOM_PAGE = {b: {k: (float(L), float(S)) for k, L, S in re.findall(r'"?([a-z0-9-]+)"?: \[([\d.]+), ([\d.]+)\]', re.search(b + r": \{(.*?)\}", _CP, re.S).group(1))}
               for b in ("l", "d")}
CUSTOM_SEL = {b: (float(t), w, re.findall(HEX, more)) for b, t, w, more in
              re.findall(r'([ld]): \[([\d.]+), "(#[0-9a-f]{6})", \[(.*?)\]\]', re.search(r"const CUSTOM_SEL[^=]*= \{(.*?)\};", JS).group(1))}


def _hex(a) -> str:
    return "#" + "".join(f"{int(max(0, min(255, v)) + 0.5):02x}" for v in a)


def _mix(a: str, b: str, t: float) -> str:
    return _hex([x + (y - x) * t for x, y in zip(rgb(a), rgb(b))])


def _hsl_of(c: str) -> tuple[float, float]:
    r, g, b = (v / 255 for v in rgb(c))
    hi, lo = max(r, g, b), min(r, g, b)
    d, l = hi - lo, (hi + lo) / 2
    if not d:
        return 0.0, 0.0
    h = ((g - b) / d) % 6 if hi == r else (b - r) / d + 2 if hi == g else (r - g) / d + 4
    return (h * 60 + 360) % 360, d / (1 - abs(2 * l - 1))


def _hsl_hex(h: float, s: float, l: float) -> str:
    a = s * min(l, 1 - l)
    k = lambda n: (n + h / 30) % 12
    return _hex([(l - a * max(-1, min(k(n) - 3, 9 - k(n), 1))) * 255 for n in (0, 8, 4)])


def custom_page(side: str, accent: str) -> dict[str, dict[str, str]]:
    h, s = _hsl_of(side)
    if s < 0.12:
        h, s = _hsl_of(accent)
        s *= 0.5
    k, out = min(1, s / 0.45), {}
    for b in ("l", "d"):
        P = out[b] = {t: _hsl_hex(h, S / 100 * k, L / 100) for t, (L, S) in CUSTOM_PAGE[b].items()}
        share, toward, more = CUSTOM_SEL[b]
        on, ink = [P[t] for t in ("bg", "box", "subtle", "head", "inset")], [P["text"], P["muted"], P["ink3"], *more]
        P["link"], P["sel"] = toward, P["subtle"]
        found = False
        for i in range(21):
            x = _mix(accent, toward, i / 20)
            if found or min(ratio(x, y) for y in on) < 4.5:
                continue
            for j in range(8):
                sel = _mix(x, P["box"], share + j * (1 - share) / 8)
                if min(ratio(y, sel) for y in [*ink, x]) >= 4.5:
                    P["link"], P["sel"], found = x, sel, True
                    break
    return out


CUSTOM_SAMPLES = [("#3f0f40", "#6b2e8c"), ("#ffffff", "#1f5fd1"), ("#000000", "#ff0000"), ("#808080", "#808080")]
CUSTOM_SAMPLES += [(_hsl_hex(h, s, l), _hsl_hex((h + d) % 360, a, al)) for h in range(0, 360, 15) for s in (1.0, 0.5)
                   for l, d, a, al in ((0.25, 40, 0.8, 0.5), (0.85, 0, 1.0, 0.45))]


def test_a_custom_theme_has_a_page_in_its_hue_that_reads_whatever_the_colours():
    """Every hue, saturated or grey, dark or pale sidebar: the worked-out page meets every pair the
    built-in themes meet on both bases (the sidebar's own pairs are the user's, checked before Save)."""
    low = []
    for side, accent in CUSTOM_SAMPLES:
        pg = custom_page(side, accent)
        for base, b in (("light", "l"), ("dark", "d")):
            P = BASE[base] | pg[b]
            P |= {"primary": P["link"], "focus": P["link"], "meter": P["link"], "selbar": P["link"],
                  "primary-text": max(("#ffffff", "#000000"), key=lambda c: ratio(c, P["link"]))}
            low += [(side, accent, base, w, round(ratio(P[fg], P[bg]), 2)) for w, fg, bg, need in PAIRS
                    if not (fg.startswith("side-") or bg.startswith("side-")) and ratio(P[fg], P[bg]) < need]
    assert not low, low[:10]
    # the seed's page is plum on both bases, lighter cards on a tinted page
    pg = custom_page("#3f0f40", "#6b2e8c")
    assert lum(pg["l"]["box"]) > lum(pg["l"]["bg"]) > 0.82 and 0.02 > lum(pg["d"]["box"]) > lum(pg["d"]["bg"])
    assert 280 < _hsl_of(pg["l"]["bg"])[0] < 320 and 280 < _hsl_of(pg["d"]["bg"])[0] < 320


def test_the_custom_theme_reads_only_its_worked_out_colours():
    b = look("custom")
    for part in b.values():
        assert not re.search(HEX, part), "custom has no colours of its own"
        assert all(v.startswith("var(--c-") for v in re.findall(r"--[a-z-]+:\s*([^;]+);", part))
    # the colours it reads are the ones the app works out, and theme.js sets them before the first paint
    read = set(re.findall(r"var\(--c-([a-z0-9-]+)\)", LOOKS_CSS))
    made = set(re.findall(r'"--c-([a-z0-9-]+)":', JS)) | {f"{t}-{b}" for b in ("l", "d") for t in CUSTOM_PAGE[b]}
    assert read == made, (read ^ made)
    assert set(CUSTOM_PAGE["l"]) == set(CUSTOM_PAGE["d"]) == set(PAGE) | {"scroll"}
    assert r"/^--c-[a-z0-9-]+$/" in THEME_JS and "html.style.setProperty(k, vars[k])" in THEME_JS
    # the selected row's faintest ink is the base's amber
    assert CUSTOM_SEL["l"][2] == [BASE["light"]["amber"]]
    # Save waits on the checks; the five colours are the user's
    pane = src("pages/settings/AppearancePane.svelte")
    assert 'id="save-custom" type="button" disabled={!t.ok}' in pane and "if (!t.ok) return;" in pane
    assert re.search(r'CUSTOM_FIELDS[^=]*= \[\["side", "Sidebar"\], \["active", "Current row"\], \["text", "Sidebar text"\], \["accent", "[^"]+"\], \["badge", "Badge"\]\]', JS)


def test_the_picker_the_palette_and_the_first_paint_name_the_same_themes():
    names = re.findall(r'\["([a-z]+)", "([^"]+)", "[^"]+"\]', re.search(r"const LOOKS[^=]*= \[(.*?)\];\n", JS, re.S).group(1))
    assert [i for i, _ in names] == IDS[:-1]
    first_paint = re.search(r"const LOOKS = \[(.*?)\];", THEME_JS).group(1)
    assert re.findall(r'"([a-z]+)"', first_paint) == BUILT_IN + ["custom"]
    # no other product's theme names or brand
    taken = {"aubergine", "hoth", "monument", "choco mint", "ochin", "work hard", "nocturne", "dagobah", "banana", "sweet treat",
             "mood indigo", "sea glass", "clementine", "jade", "lagoon", "barbra", "haiti", "slack"}
    for i, w in names:
        assert i not in taken and w.lower() not in taken, w
    assert "slack" not in LOOKS_CSS.lower() and "slack" not in THEME_JS.lower()
    # the palette has a command a theme, and the top bar's ◐ switches light and dark only
    pal = re.search(r"\nfunction palCommands\(.*?\n}\n", JS, re.S).group(0)
    assert 'title: "Theme: " + lw' in pal and "lookChoices()" in pal and "setLook(id)" in pal
    # ⌘K again right after esc: the key reaches the closed palette's field first, and the old close
    # event arrives after the new palette opened; neither may touch the new palette's state
    opener = re.search(r"\nexport function openPalette\(.*?\n}\n", src("lib/shell.svelte.ts"), re.S).group(0)
    assert '?.open) return;' in opener and "ui.palette = { text };" in opener, "a new palette object each time"
    closed = re.search(r"\n  function closed\(.*?\n  }\n", src("shell/Palette.svelte"), re.S).group(0)
    assert "if (d?.open) return;" in closed and "ui.palette = null;" in closed
    head = src("shell/Header.svelte")
    # ◐ flips what you see, and is Auto again when the flip is the device's own scheme (QA B18:
    # a press from Auto stored a fixed scheme for good)
    assert "const to = flipTo();" in head and "L.setTheme(to)" in head and "THEME_NEXT" not in JS
    flip = re.search(r"\nexport function flipTo\(.*?\n}\n", src("lib/theme.ts"), re.S).group(0)
    assert '=== deviceDark() ? "auto" : want' in flip


def test_the_picker_is_a_keyboard_radio_group_that_applies_at_once():
    # moved: pages/settings/LookGrid.svelte; appearance.svelte.test.ts presses it
    grid = src("pages/settings/LookGrid.svelte")
    assert 'role="radiogroup"' in grid and 'role="radio"' in grid and "aria-checked=" in grid and "onkeydown={lookKeys}" in grid
    assert "tabindex={i === at ? 0 : -1}" in grid, "one stop in the tab order: the arrows move inside"
    keys = grid[grid.index("function lookKeys("):]
    for k in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End", "e.stopPropagation()"):
        assert k in keys, k
    pick = grid[grid.index("function pickLook("):grid.index("function lookKeys(")]
    assert "setLook(id);" in pick and "app()?.render();" in pick
    assert re.search(r"\.look:focus-visible \{[^}]*outline: 2px solid var\(--focus\)", CSS)
    assert re.search(r"\.look\[aria-checked=true\] \{", CSS)


def test_every_page_applies_the_choice_before_the_first_paint():
    html = (UI / "app.html").read_text()
    theme, own, looks = (html.index('src="static/theme.js"'), html.index('href="static/kranto.css"'), html.index('href="static/looks.css"'))
    assert theme < own < looks
    for name in ("looks.css",):
        code, ctype, _ = api.handle("GET", "/static/" + name, None, None, app=api.App(Path("/nonexistent/t"), "fake", Path("/nonexistent/h")))
        assert code == 200 and ctype.startswith("text/css")


ROW, BADGE = "current row's text", "badge's number"


def table() -> str:
    out = []
    for id in [i for i in IDS if i != "custom"]:
        for base in ("light", "dark"):
            n = numbers(id, base)
            worst = min(n, key=lambda x: x[1] / x[2])
            pick = {w: r for w, r, _ in n}
            out.append(f"| {id} | {base} | {pick['text on box']:.1f} | {pick['muted on box']:.1f} | {pick['link on box']:.1f} | "
                       f"{pick['primary button text']:.1f} | {pick['sidebar text']:.1f} | {pick['sidebar muted']:.1f} | "
                       f"{pick[ROW]:.1f} | {pick[BADGE]:.1f} | "
                       f"{min(r for w, r, _ in n if w.startswith('flash')):.1f} | {min(r for w, r, _ in n if w.startswith('status') and w.endswith('box')):.1f} | "
                       f"{worst[0]} {worst[1]:.2f} (needs {worst[2]}) |")
    return "\n".join(out)


def page_table() -> str:
    """The page's own surfaces (TH): the least of each kind of ink over the page, a card, hover, the
    head, an inset, a button and the selected row."""
    out, on = [], SURFACES + MORE_SURFACES
    for id in [i for i in IDS if i != "custom"]:
        for base in ("light", "dark"):
            P, n = resolved(id, base), numbers(id, base)
            least = lambda fgs, P=P: min(ratio(P[fg], P[bg]) for fg in fgs for bg in on)
            page = [x for x in n if any(x[0].endswith(" on " + s) for s in on) or "border on the page" in x[0]]
            worst = min(page, key=lambda x: x[1] / x[2])
            out.append(f"| {id} | {base} | {P['bg']} / {P['box']} | {least(('text',)):.1f} | {least(('muted', 'ink3')):.1f} | {least(('link',)):.1f} | "
                       f"{least(('blue', 'violet', 'green', 'amber', 'red')):.1f} | {min(r for w, r, _ in n if w.startswith('flash')):.1f} | "
                       f"{least(('focus',)):.1f} | {worst[0]} {worst[1]:.2f} (needs {worst[2]}) |")
    return "\n".join(out)


if __name__ == "__main__":
    print("| theme | base | text | muted | link | button | side text | side muted | current row | badge | flashes (min) | status on card (min) | tightest pair |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    print(table())
    print("\nThe page's surfaces (page, card, hover, head, inset, button, selected row): the least ratio of each ink over all seven\n")
    print("| theme | base | page / card | text | muted (and ink3) | link | status pills | flashes | focus ring | tightest page pair |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print(page_table())
