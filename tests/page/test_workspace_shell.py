"""The workspace shell: the frame's five regions,
the route table (NODES) covering every route the app had, the keys it adds, the status bar
that carries Today's service line, Open in Claude Code's place, and the breakpoints. Read here: the
routes (lib/nodes.json) and the key map (lib/keys.json) as the JSON they are, the frame
(App.svelte) and the stylesheet whole. What the app does with them is pressed in Vitest: the routes,
the redirects, Not found, a list's links and its scroll, and c in lib/app/route.test.ts; the keys in
lib/keyboard.test.ts and lib/app/rows.test.ts; the service line in lib/app/chrome.test.ts; a press
in lib/app/data.test.ts; a page kept across draws in lib/pages.test.ts."""
import re

import pytest

from .webui import css, everything, keymap, nodes, src

JS = everything()
CSS = css()
HTML = src("App.svelte")
BAR = src("shell/StatusBar.svelte")
NODES = nodes()
KEYMAP = keymap()
ROUTER = src("lib/router.ts")
SELS = dict(re.findall(r'(\w): "([a-z/]+)"', re.search(r"export const SELS[^=]*= \{(.*?)\};", ROUTER, re.S).group(1)))




def match(route: str):
    """matchRoute() in app.js, as Python: segment by segment, ':x' is any one segment, the
    first entry wins; the node and the list get the parameters filled in."""
    path = [p for p in route.split("/") if p]
    for n in NODES:
        pat = n["route"].split("/") if n["route"] else []
        if len(pat) != len(path) or not all(p.startswith(":") or p == q for p, q in zip(pat, path)):
            continue
        params = iter(q for p, q in zip(pat, path) if p.startswith(":"))
        node = re.sub(r":\w+", lambda _, params=params: next(params), n["node"]) if "node" in n else None
        return {**n, "node": node}
    return None


# every route of the workspace's table that the cut kept: (the route, its node, the object in the pane)
ROUTES = [
    ("review", "review", None), ("needs", "needs", None), ("post", "post", None),
    ("topics", "topics", None), ("topics/new", "topics/new", None), ("topics/2", "topics/2", None),
    *[(f"topics/2/{p}", f"topics/2/{p}", None) for p in ("evidence", "themes", "ideas", "sources", "map")],
    ("topics/2/watches", "topics/2", None),   # watches retired: the topic itself
    # Watch is topic-first: a topic's page and its Sources, Evidence and Map
    ("watch/topic/2", "topics/2", None), *[(f"watch/topic/2/{p}", f"topics/2/{p}", None) for p in ("sources", "evidence", "map")],
    ("ideas", "ideas", None), ("ideas/i0a1b2c3d", "ideas", "idea"), ("ideas/card:6", "ideas", "idea"),
    ("library", "library", None), ("library/o/665", "library", "observation"), ("library/map", "library/map", None),
    ("library/clusters", "library/clusters", None), ("library/clusters/3", "library/clusters", "theme"),
    ("library/rollups", "library/rollups", None),
    # Settings: the Overview and its pages; a source and a site's page stay on Sources
    ("settings", "settings", None), ("settings/sources", "settings/sources", None), ("settings/sources/new", "settings/sources", None),
    ("settings/sources/12", "settings/sources", "source"), ("settings/connections/github", "settings/sources", "connection"),
    *[(f"settings/{p}", f"settings/{p}", None) for p in ("watching", "posting", "prompts", "spend", "privacy",
                                                          "assistant", "system", "appearance")],
]


@pytest.mark.parametrize("route,node,obj", ROUTES)
def test_every_route_has_a_node_and_its_object(route, node, obj):
    m = match(route)
    assert m and not m.get("redirect") and not m.get("stage"), route
    assert m["node"] == node and m.get("object") == obj, (route, m)
    if obj:      # an object route names the list its pane sits beside: its home node's list
        assert match(m["list"])["node"] == node, route


@pytest.mark.parametrize("route", ["welcome", "welcome/topics", "welcome/finish", "hello", "home", "activity"])
def test_the_welcome_steps_and_the_splash_are_the_stage(route):
    assert match(route)["stage"] is True


@pytest.mark.parametrize("old,new", [("", "home"), ("today", "needs"), ("overview", "home"),
                                     # watches retired: their old pages land on Watch
                                     ("settings/watches", "watch"), ("settings/watches/new", "watch"),
                                     ("library/watches", "watch"), ("library/watches/new", "watch"), ("watch/watches", "watch"),
                                     # the chat went
                                     ("chat", "home"), ("chat/new", "home"), ("chat/c1a2b3c4d", "home"),
                                     # the old Settings entries, and the factory's pages after the cut
                                     ("settings/keys", "settings/watching"), ("settings/models", "settings/watching"),
                                     ("settings/rules", "settings"), ("settings/mcp", "settings"),
                                     ("settings/connections", "settings/watching"), ("settings/maintenance", "settings"),
                                     ("settings/github", "settings"), ("settings/projects", "settings"),
                                     ("settings/building", "settings"), ("settings/tools", "settings"),
                                     ("settings/publishing", "settings"),
                                     ("settings/updates", "settings/system"), ("settings/health", "settings/system"),
                                     ("settings/learning", "settings/grades"), ("settings/access", "settings/privacy"),
                                     ("welcome/repos", "welcome"), ("welcome/building", "welcome"),
                                     ("welcome/publishing", "welcome"), ("ideas/new", "ideas")])
def test_old_routes_redirect(old, new):
    assert match(old)["redirect"] == new and match(new) and not match(new).get("redirect")


@pytest.mark.parametrize("old", ["projects", "projects/p1a2b3c4d", "projects/p1a2b3c4d/charter", "builds",
                                 "builds/receipts", "builds/receipts/summary", "builds/receipts/trace",
                                 "builds/receipts/build/2", "build", "build/projects", "build/repos",
                                 "topics/2/builds", "loop/l1/trace"])
def test_the_factorys_pages_say_they_left(old):
    """CUT: an old link to a build's or a project's page lands on the home (or Ideas) and says
    why, never Not found."""
    m = match(old)
    assert m and m["redirect"] in ("home", "ideas") and "not part of Kranto any more" in m["said"], old


def test_anything_else_is_not_found_in_the_stage():
    # settings/<one word> is a feature's or a cub's Settings page, which says when
    # there is none
    for route in ("nope", "builds/a/b/c/d", "library/o", "settings/x/y"):
        assert match(route) is None, route


def test_every_object_away_from_home_has_a_sel_key():
    """sel= opens an object beside a list that is not its home (an observation on Today, a
    build on a topic's Builds); every object with an id has a one-letter key."""
    homes = {n["route"].rsplit("/", 1)[0] for n in NODES if n.get("object") and n["route"].endswith((":key", ":id", ":n"))}
    assert homes == set(SELS.values()), homes ^ set(SELS.values())
    assert len(set(SELS)) == len(SELS)


def test_the_frame_has_five_regions_and_no_footer():
    for region in ('<header class="hd" id="top">', '<nav id="nav" aria-label="Sections">', '<main id="list"', '<div id="rows"',
                   '<section id="detail"', '<div id="dscroll"', '<div id="term"', '<footer id="bar">'):
        assert region in HTML, region
    frame = HTML[HTML.index('<div id="app">'):HTML.index('<div id="scrim"')]
    assert all(f'id="{x}"' in frame for x in ("top", "nav", "list", "detail", "bar")), "#app is the frame"
    # the two splitters are #app's other children, separators between the panes
    assert frame.index('id="nav"') < frame.index('<Splitter col="nav" />') < frame.index('id="list"') \
        < frame.index('<Splitter col="detail" />') < frame.index('id="detail"')
    split = src("shell/Splitter.svelte")
    assert 'id={"split-" + col}' in split and 'role="separator"' in split and 'tabindex="0"' in split
    assert 'id="foot"' not in HTML and '"shell"' not in HTML and 'class="col"' not in HTML
    assert "tablist" not in JS + HTML


def test_the_css_frame_and_its_breakpoints():
    app = re.search(r"\n#app \{([^}]*)\}", CSS).group(1)
    assert "grid-template-rows: 40px minmax(0, 1fr) 24px" in app
    assert "grid-template-columns: var(--nav-w, 224px) 6px minmax(320px, 1fr) 6px var(--detail-w, minmax(420px, 41%))" in app
    assert 'grid-template-areas: "top top top top top" "nav sn list sd detail" "bar bar bar bar bar"' in app
    assert "@media (max-width: 1179px)" in CSS and "@media (max-width: 759px)" in CSS
    assert "body.show-detail #detail" in CSS and "body.nav-open nav#nav" in CSS and "body.stage #app" in CSS
    assert "body:has(> #app) { overflow: hidden; }" in CSS, "the page never scrolls; the panes do"
    for token in ("--pane: var(--box)", "--sunk: var(--subtle)", "--ink: var(--text)", "--sel: var(--blue-wash)", "--run: var(--violet)"):
        assert token in CSS, token
    assert "fonts.googleapis" not in CSS + HTML and "@import" not in CSS, "system fonts only"


def test_the_keys_the_workspace_adds():
    by = {m["keys"]: m for m in KEYMAP}
    assert by["g l"]["go"] == "library"
    assert (by["["]["run"], by["]"]["run"]) == ("prevSection", "nextSection")
    assert (by["⇧j"]["run"], by["⇧k"]["run"]) == ("nextGroup", "prevGroup")
    assert by["o"]["run"] == "open" and by["enter"]["run"] == "primary", "o and enter are the shell's"
    # o opens the pane (a build or a project opened in full before the cut); tab puts the cursor there
    assert "the detail pane" in by["o"]["does"] and "open in full" not in by["o"]["does"]
    assert by["tab"]["run"] == "pane" and "the detail pane" in by["tab"]["does"]
    assert by["esc"]["run"] == "close" and "Claude Code" in by["esc"]["does"]


def test_the_status_bar_carries_todays_service_line():
    # the word opens Health, or the run its reason is about (the reason's own cell too)
    assert 'href={b.why ? b.why.href : "#/settings/health"}' in BAR and 'id="health-why"' in BAR
    assert "? keys</button>" in BAR and 'id="key-hint">{hint}' in BAR
    # no dollars outside Settings › Spend ($ only as Svelte's runes and template literals)
    assert not re.search(r"\$(?![{a-z])", BAR), "no dollars outside Settings › Spend"
    # the g chord's menu while it is pending (one menu: no builds to switch off since the cut)
    assert "if (ui.chord) return CHORD_HINT;" in BAR and "buildsOff" not in BAR


def test_no_page_writes_html():
    assert "outerHTML" not in JS and "innerHTML" not in JS


def test_c_opens_claude_code_and_says_how_to_turn_it_on_while_it_is_off():
    """c and every Open in Claude Code button open the terminal's panel on the subject;
    while term.enabled is off, one line from api/term says how to turn it on. No chat drawer."""
    assert "openDrawer" not in JS and "DRAWER" not in JS and "api/chat" not in JS and "chatHref" not in JS
    assert 'id: "chat-about"' not in JS and '"Chat about this"' not in JS
    assert 'id: "term-open"' not in JS                         # the build's button left with builds
    assert '{ label: "Open in Claude Code", key: "c"' in src("pages/ideas/verbs.ts")       # an idea's, in ⌘K and its menu
    state = src("term/state.svelte.ts")
    assert "termUi.why = j?.enabled ? null : j?.why || null;" in state


def test_the_ink3_token_is_in_every_palette_block():
    blocks = [CSS[CSS.index(":root {"):], CSS[CSS.index(":root[data-theme=dark] {"):], CSS[CSS.index(":root:not([data-theme=light]) {"):]]
    assert all("--ink3: #" in b[:b.index("}")] for b in blocks)
