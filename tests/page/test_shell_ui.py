"""The shell of Kranto UI (UI-v4.md 2.1 and 2.4, track U2; Svelte since): the sticky
header with its links, the side nav (no tabs anywhere), #/overview landing on the home, the one key
map (lib/keys.json) and the command palette. Read here: the key map as the JSON it is, and what
the files say whole. What they do is pressed in Vitest: action() in lib/keys.test.ts, the keys
carried out in lib/keyboard.test.ts, typing in lib/app/route.test.ts, the navigator's tree in
lib/app/chrome.test.ts, the routes and Not found in lib/app/route.test.ts, the palette's items
in lib/app/commands.test.ts, its ranking in lib/palette.test.ts and its keys in
shell/shell.test.ts."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import SRC, everything, keymap, nodes, src

UI = Path(api.__file__).parent
JS = everything()
KEYS_TS = src("lib/keys.ts")
HTML = (UI / "app.html").read_text()
APP = src("App.svelte")
HEADER = src("shell/Header.svelte")
NAV = src("shell/Nav.svelte")
BAR = src("shell/StatusBar.svelte")
PALETTE = src("shell/Palette.svelte")
KEYMAP = keymap()


def test_no_top_level_name_is_declared_twice():
    """Each module's own names: a second top-level const of the same name stops the whole
    page with a SyntaxError (the parallel tracks each add helpers)."""
    for f in sorted(SRC.rglob("*.ts")):
        names = re.findall(r"^(?:export )?(?:const|let|var|(?:async )?function)\s+([A-Za-z_$][\w$]*)",
                           f.read_text(), re.M)
        twice = sorted({n for n in names if names.count(n) > 1})
        assert not twice, (f.name, twice)


# -- the key map -----------------------------------------------------------------------------
def test_the_key_map_covers_the_sheet():
    """UI-v4.md 2.4's sheet, every key once, each with what it does and how it is carried out:
    a route (go), a shell verb (run), or a verb the page declares (page). Every run has its case
    and every g key its page: lib/keyboard.test.ts, lib/app/route.test.ts."""
    keys = [m["keys"] for m in KEYMAP]
    assert len(keys) == len(set(keys))
    # (g p and g b, Projects and Builds, and a build's r, a, s, b and z left with the factory, CUT)
    assert set(keys) == {"g h", "g a", "g w", "g t", "g r", "g i", "g n", "g s", "g l", "g 1…9", "/", "⌘K", "⌘J", "esc", ".",
                         "j", "k", "⇧j", "⇧k", "o", "tab", "enter", "[", "]", "1", "2", "0",
                         "a–f", "p", "l", "c", "⇧a", "n", "?",
                         "t", "e", "← →", "1–6", "f"}                       # a trace's
    assert {m["group"] for m in KEYMAP} == {"Go", "Find", "Move", "Grade", "Decide", "Lists",
                                            "Trace"}
    for m in KEYMAP:
        assert m["does"] and sum(k in m for k in ("go", "run", "page")) == 1, m


def test_the_page_is_the_build_and_the_key_map_only_decides():
    """The page is the build's one module (after theme.js, which sets the theme before
    the first paint); keys.js and main.js are gone; keys.ts decides and never acts."""
    assert '<script src="static/theme.js">' in HTML and HTML.count("<script") == 1
    assert "keys.js" not in HTML and "main.js" not in HTML
    assert not (UI / "static" / "keys.js").exists() and not (UI / "static" / "ui").exists()
    for sink in ("innerHTML", "document.", "fetch(", "localStorage"):
        assert sink not in KEYS_TS, "keys.ts only decides; the shell acts"
    assert 'import KEYS_JSON from "./keys.json";' in KEYS_TS


# -- the nav, the header, the routes ---------------------------------------------------------
def test_the_nav_is_one_tree_with_no_tablist():
    assert 'role: "tablist"' not in JS and 'role="tablist"' not in JS and "tablist" not in JS
    assert '<nav id="nav" aria-label="Sections">' in APP and 'id="tabs"' not in APP
    # the reviewer's change 2: a shortcut is in the entry's tooltip, never beside it
    assert "x.key ? `${x.w} (${x.key})` : null" in NAV
    assert 'class: "g"' not in NAV and "kbd" not in NAV
    assert "aria-expanded={x.open" in NAV and "navToggle(x.twist" in NAV, "a topic and the library expand"
    assert ">☰</button>" in HEADER and "navDrawer(!ui.navOpen)" in HEADER, "the drawer under 1180 px"
    # no second menu inside a page: Settings, a topic and the library draw none
    for name in ("library/ObsList", "library/MapList", "library/ClustersList", "library/RollupsList",
                 "topics/TopicList", "topics/TopicOverview", "topics/TopicThemes", "topics/TopicIdeas",
                 "topics/TopicSources"):
        page = src(f"pages/{name}.svelte")
        assert "<nav" not in page and "sided" not in page, name


def test_overview_and_today_land_on_the_home_and_needs_you():
    # the redirect keeps its filters and selection: lib/app/route.test.ts (Today left with the cut)
    assert {"route": "overview", "redirect": "home"} in nodes() and {"route": "today", "redirect": "needs"} in nodes()
    assert 'href: "#/overview"' not in JS and 'go("overview")' not in JS


def test_the_header_tells_and_links():
    assert '<a class="brand" href="#/home" aria-label="Kranto, Home">' in HEADER
    # the lanes are one item, what Kranto is doing, opening Activity, where a build's row opens its
    # trace; no build to say Revising of, no loop to be down (CUT)
    assert "<ActivityIndicator {lanes}" in HEADER and 'href="#/activity"' in src("shell/ActivityIndicator.svelte")
    assert 'fix: x.kind === "fix"' not in HEADER
    assert "{f.que} queued" not in HEADER and "hd-loop-down" not in HEADER + src("shell/StatusBar.svelte")
    # no spend chip: dollars live in Settings › Spend (the owner's ruling, 2026-10-09)
    assert "spendChip" not in JS and "#/settings/spend" not in HEADER
    assert 'id="pause"' in HEADER and "togglePause(" in HEADER
    assert 'openPalette("")' in HEADER and '"Chats"' not in HEADER, "no Chats since "


def test_the_status_bar_has_no_legacy_links():
    """The old footer (feed, shortcuts) went into the status bar: ? keys, and no links to the
    legacy pages (the feed stays on Health › Messages)."""
    assert 'id="foot"' not in APP and 'getElementById("foot")' not in JS
    assert "classic" not in BAR and "loop page" not in BAR and "keySheet()" in BAR and "? keys" in BAR


# -- the palette ------------------------------------------------------------------------------
def test_the_palette_is_one_combobox_over_every_group():
    assert '<dialog id="pal" class="pal"' in PALETTE and 'role="combobox"' in PALETTE and 'role="listbox"' in PALETTE
    # with the doors: the last things opened first, Settings by name or key, and Go to
    assert 'export const PGROUPS = ["Recent", "Ideas", "Evidence", "Sources", "Topics", "Settings", "Go to", "Commands"]' \
        in src("lib/palette.ts")
    assert 'api("/api/search?q=" + encodeURIComponent(want))' in PALETTE
    assert "chats" not in PALETTE.lower(), "no chats since "
