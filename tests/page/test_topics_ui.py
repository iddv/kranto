"""Settings › Watching and the Topics tab (PLAN.md 1.5, 2, 3): the pages are in-app routes with
a vertical menu; the key is never kept by the page. (Build this from a topic, the builds' and
projects' pages and the Building step left with the factory, CUT.)"""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, nodes, src

UI = Path(api.__file__).parent
JS = everything()
OBS_GRADE = '<Grade target="observation" id={o.id}'



# -- the pages -----------------------------------------------------------------------------
def test_topic_pages_are_in_app_routes_with_a_vertical_menu():
    ts = src("pages/topics/topics.ts")
    pages = re.search(r"export const TPAGES: \[string, string\]\[\] = (\[.*?\]);", ts).group(1)
    assert [w for _, w in re.findall(r'\["([a-z]*)", "([^"]+)"\]', pages)
            if w != "Builds"] == ["Overview", "Evidence", "Themes", "Ideas", "Sources", "Map"]
    # its pages are its children in the side nav (UI-v4.md 2.1), with their counts (W3: read from
    # /api/today and /api/topics/<id>, so they show before the topic is visited): pressed in
    # lib/app/chrome.test.ts ("is one tree: Desk, Topics with their pages, …")
    assert 'import { TODAY_API, type Today } from "../../pages/topics/topics";' in src("lib/app/chrome.ts")
    assert "TCOUNTS" not in JS
    # moved: pages/topics, one list for a topic's pages, registered by their route's node
    reg = src("pages/index.ts")
    # every topic is Watch › Topics in either layout: the old Topics list went (track)
    assert 'import("./topics/TopicsList.svelte")' not in reg
    assert 'for (const [sub] of TPAGES) register("topics/:id" + (sub ? "/" + sub : ""), { list: topicList, pane: sub === "map" ? lazy(() => import("./library/MapPane.svelte")) : topicPane });' in reg
    # under the doors a topic's pages are Watch's (WT): #/watch/topic/<id>[/sources|/evidence|/map]
    assert {n["route"] for n in nodes()} >= {"watch/topic/:id", "watch/topic/:id/sources", "watch/topic/:id/evidence", "watch/topic/:id/map"}
    # each of them a route of its own (lib/nodes.json)
    assert {n["route"] for n in nodes()} >= {"topics/:id" + ("/" + k if k else "") for k in re.findall(r'\["([a-z]*)", "', pages)}
    topic = src("pages/topics/TopicList.svelte")
    assert "subnav" not in topic and "tab" not in topic and "<nav" not in topic
    assert "vTopic" not in JS and '"topics"' in re.search(r"const VIEWS = new Set\(\[(.*?)\]\)", JS).group(1), "the old pages are gone"
    for page in ("TopicList", "TopicOverview", "TopicThemes", "TopicIdeas", "TopicSources", "TopicPane", "TopicCard"):
        assert '<script lang="ts">' in src(f"pages/topics/{page}.svelte"), page
    card = src("pages/topics/TopicCard.svelte")
    assert 'TOPICS_API = "/api/topics"' in ts
    # Scout more is scout.ts's (the head and the Edit sheet share it,)
    assert "`/api/topics/${x.id}/scout`" in src("pages/topics/scout.ts") and "scoutMore(btn, x," in card
    # Pause and Resume are topicedit.ts's (the card's ⋯ and Watch › Topics' row ⋯ share it,)
    assert "`/api/topics/${x.id}/status`" in src("pages/topics/topicedit.ts") and "pauseTopic(btn, x)" in card
    # first run, Settings › Watching and Add topic moved: pages/welcome, pages/settings
    moved = "".join(src(f) for f in ("pages/welcome/AddTopic.svelte", "pages/settings/keys.svelte.ts", "pages/settings/KeyField.svelte"))
    for endpoint in ('"/api/topics", { name, description: desc, scout: true }', "`/api/topics/${t.id}/scout`",
                     'SETUP_API = "/api/setup"', 'PROVIDER_API = "/api/setup/provider"', '"/api/setup/check"'):
        assert endpoint in moved, endpoint
    # All topics is the library: its lists say so in their head
    obs = src("pages/library/ObsList.svelte")
    assert '{topic ? topic.name : "All topics"}' in obs
    # Evidence is the library's list with the topic fixed and a grade on each row
    assert '{:else if sub === "evidence"}\n  <ObsList {view} topic={t} />' in topic
    assert "obsQuery(topic ? { ...r.q, topic: String(topic.id) } : r.q)" in obs
    assert "grade={gradeOf(o, k)}" in obs and OBS_GRADE in src("pages/library/ObsLine.svelte")


def test_ideas_come_through_one_import_point_with_a_fallback():
    cards = src("pages/ideas/cards.ts")          # moved
    # the list's one read (the dispatch cards and one card are their own reads; Later and Pass
    # mark /api/ideas stale)
    assert 'export const IDEAS_API = "/api/ideas?embedding=ref";' in cards
    assert JS.count('"/api/ideas?embedding=ref"') == 1
    assert JS.count("read<") and cards.count("(IDEAS_API, 30000)") == 1
    # the API's cards, else the snapshot's: pressed in pages/topics/topics.svelte.test.ts ("come
    # through the server's ideas API, else the loop's snapshot; …")
    # the server's links say #/ideas/card:N (the loop's own ledger ids left with it, CUT)
    assert "String(i.card.number) === id.slice(5)" not in JS


def test_the_key_is_never_kept_by_the_page():
    # moved: the key's form is KeyField.svelte, Settings › Keys' and the welcome step's
    field = src("pages/settings/KeyField.svelte")
    assert '<KeyField k={s!.key} done={s!.done} only="keys" />' in src("pages/welcome/KeysStep.svelte")
    assert 'type="password" autocomplete="off"' in field and "bind:value" not in field
    # cleared once it is sent: pressed in pages/settings/keys.svelte.test.ts ("tests and keeps a key
    # once, clears the field and keeps nothing of it")
    assert "KEYBASE.v" in field and not re.search(r"KEY[A-Z]*(\.v)? = (keyIn|v\b)|= v;|STATE\.key|\$state<string", field)
    # the periodic redraw leaves the page alone while the field holds something: pressed in
    # lib/app/topics.test.ts ("leaves the page be while the key field holds something, …")
    assert not re.search(r"sessionStorage|document\.cookie", JS)
    # the only things the page stores are its appearance: light or dark, the sidebar theme and a
    # custom theme's colours (Settings › Appearance, UI-v4.md 1.2, AP), and the width of
    # Claude Code's split, and which list groups the viewer folded or opened (UP #7, R4:
    # the names of groups, never their rows), and Feedback's draft (FB: the person's own words, kept in this
    # browser while the sheet is closed, cleared once filed), and when the viewer last opened
    # Activity (a time, so the top bar's red dot goes; never a run), and the
    # last topic looked at in Watch (WT: its id, so the Watch door comes back to it)
    uses = re.findall(r"localStorage\.\w+\(([^,)]*)", JS)
    assert uses and set(uses) == {"THEME_KEY", "LOOK_KEY", "LOOK_CUSTOM_KEY", "TERMW_KEY",
                                  "FOLD_KEY", "OPEN_KEY", "DRAFT_KEY", "SEEN_KEY", "WATCH_KEY"}, uses
    assert 'const WATCH_KEY = "kranto.watch.topic";' in JS
    assert 'export const SEEN_KEY = "kranto.activity.seen";' in JS
    assert 'const DRAFT_KEY = "kranto.feedback.draft";' in JS
    # the appearance's keys are the product's name and the key (lib/legacy.ts, which also reads a
    # browser's keys from before the rename once)
    assert 'const THEME_KEY = newKey("theme");' in JS
    assert 'const LOOK_KEY = newKey("look");' in JS and 'const LOOK_CUSTOM_KEY = newKey("look.custom");' in JS
    assert "export const newKey = (name: BrowserKey): string => `${COMMAND}.${name}`;" in JS


# Pause says Paused only when both halves are (STATUS.md: hostForm only checked that the request
# succeeded): pressed in lib/app/data.test.ts ("asks before Pause, then says Paused only when both
# halves read back paused"); the notice a redirect brings in lib/app/topics.test.ts ("say the
# notice a form redirects with")


# -- topics and the library in the workspace (WORKSPACE.md 8, W3) ----------------------------
CSS = css()


def test_an_evidence_row_is_one_line_with_signal_sentence_source_and_grade():
    # one row everywhere: the old module's obsLine went with Today
    line = src("pages/library/ObsLine.svelte")
    assert "{n2(o.signal)}" in line and "firstSentence(o.summary)" in line
    assert '"#/settings/sources/" + o.source_id' in line and "{#snippet aside()}" in line
    # the library's moved rows, a topic's Evidence and Overview too
    obs = src("pages/library/ObsList.svelte")
    assert "<ObsLine {o} mute tick isNew={!!o.new}" in obs and "grade={gradeOf(o, k)}" in obs
    assert OBS_GRADE in src("pages/library/ObsLine.svelte")
    assert "<ObsLine {o} mute tick isNew={!!o.new}" in src("pages/topics/TopicOverview.svelte")
    # one 31 px row: 100 rows are 3100 px (the row's height includes its border)
    assert "height: 31px; padding: 0 12px 0 16px; border-top: 0; border-bottom: 1px solid" in CSS and "* { box-sizing: border-box; }" in CSS


def test_evidence_groups_by_the_new_flag_with_the_filters_in_the_toolbar():
    obs = src("pages/library/ObsList.svelte")      # a topic's Evidence is this list
    assert "d.results.filter((o) => o.new)" in obs and "d.results.filter((o) => !o.new)" in obs
    assert '<Group id="ev-new" title="New since your last visit"' in obs and '"Seen before"' in obs
    assert '<span class="tbn filters"><FilterBar r={{ path: base.split("/"), q: r.q, sel: null }} base={base}' in obs
    assert "<BulkBar" not in obs   # no bulk grading
    assert "<Pager {base} q={r.q} at={qq.at} {pages} />" in obs and "cutLine" in obs
    # the toolbar may wrap: the group heads stick under it (its height: pressed in
    # lib/app/topics.test.ts, "keeps the group heads under a toolbar that wraps")
    assert ".grp .ghd { position: sticky; top: var(--tbh, 36px);" in CSS
    # an observation open in the pane and not on this page is pinned at the top
    assert 'view.w.object === "observation"' in obs and 'title="Open in the pane"' in obs


def test_the_observation_pane_and_cited_by_from_the_cards_citations():
    # the Library's moved pane, shown away from home too (sel=o<id>: Today, a topic's
    # Evidence): the old module's copy is gone
    pane = src("pages/library/ObsPane.svelte")
    assert 'id: "grade"' not in pane   # the grade is a line under the title
    for part in ('id: "summary"', 'id: "source"', 'id: "cited"', 'id: "hood"', 'id: "nearby"', 'id: "judgment"',
                 "citedBy(o.id, o.cited_by?.ideas)", "mapTheme(o.id)", "muteMenu(", '"signal " + n2(o.signal)'):
        assert part in pane, part
    assert 'const AWAY = ["source", "connection", "observation", "theme", "idea"];' in JS
    # Cited by, the cards the server names (cited_by, CON L2), else the cards' citations and evidence:
    # pressed in pages/library/observations.svelte.test.ts ("lists the cards that cite it, …",
    # "lists what the server says cites it, …") and
    # pages/topics/topics.svelte.test.ts ("come through the server's ideas API, …")
    # the theme only from the map when it is loaded: what Library › Map read, never a read of
    # its own, nothing invented: pressed in pages/library/map.svelte.test.ts ("names an
    # observation's theme from the map once it is read, …")


def test_the_outline_is_a_table_of_contents_not_tabs():
    pane = src("ui/Pane.svelte")                     # every pane's outline
    assert '<nav class="toc" aria-label="On this page"><span class="toc-h">On this page</span><ol>' in pane
    # an anchor never changes the route: pressed in pages/topics/topics.svelte.test.ts ("jumps to a
    # section from the outline without changing the route")
    assert 'role: "tab' not in JS and "tablist" not in JS
    rules = re.findall(r"\n(\.toc[^{]*)\{([^}]*)\}", CSS)
    assert rules and not any("border" in body or "background" in body or "underline" in body and "none" not in body for _, body in rules)
    assert '.toc a[aria-current]::before { content: "▸ "; }' in CSS and ".toc a[aria-current] { color: var(--text); font-weight: 600; }" in CSS
    # the scroll-spy marks the outline: pressed in lib/app/rows.test.ts ("marks the outline's
    # section the pane is scrolled to")
    assert 'document.querySelector("#dscroll .dh")' in JS and not re.search(r"[.\"]decide\b", JS)     # W5: the old sticky bar is gone


def test_approve_on_a_proposal_posts_the_topic():
    # the topic's, a wildcard's none: pressed in pages/topics/topics.svelte.test.ts ("approves a
    # proposal from its row for the topic, a wildcard with no topic")
    line = src("pages/topics/Proposals.svelte")
    assert "approveSource(e.currentTarget, p, tid, name)" in line and ">Approve</button>" in line and 'class="ptick"' in line
    s = src("pages/topics/TopicSourceRows.svelte")   # moved (the rows' one component)
    assert '<Proposals title="Proposed" tid={t.id} rows={proposed} ticked={ticks()} approve name={t.name}>' in s and 'id="watch-these"' in s
    assert "watchTicked(id, rows, tk)" in s and "delete TICKS[id]" in s
    pane = src("pages/settings/SourcePane.svelte")          # moved
    assert 'label: "Approve and watch"' in pane and "approveSource(b, s, t" in pane


def test_the_maps_list_pane_has_the_legend_and_the_pane_the_svg():
    # Library › Map is a moved page: its list and its pane are components
    m = src("pages/library/MapList.svelte")
    assert '<Group id="legend" title="Clusters"' in m and "@render swatch(cl.cluster)" in m
    assert "<Row go={href(base, { ...r.q, p: id })}" in m, "a point's row walks the map"
    pane = src("pages/library/MapPane.svelte")
    assert "mapView(d)" in pane and "mapHighlight(v" in pane and "el.replaceChildren(v.svg)" in pane
    assert 'register("library/map"' in src("pages/index.ts") and "library/map" not in src("pages/PaneEmpty.svelte")
    # j and k walk the points: pressed in lib/app/topics.test.ts ("walk the points of a map: …")


def test_the_topics_node_and_a_topics_pages_show_the_topic_in_the_pane():
    assert 't: "topic", u: "rollup"' in JS
    # moved: a Topics row is sel=t<id>, and the topics' pane draws that topic, or the
    # topic of the page it is on
    assert 'sel={"t" + t.id}' in src("pages/watch/Topics.svelte")
    pane = src("pages/topics/TopicPane.svelte")
    assert '(code[0] === "t" ? code.slice(1) : null)' in pane and '/^topics\\/[^/]+/.test(node) ? (node.split("/")[1] as string)' in pane
    card = src("pages/topics/TopicCard.svelte")
    for part in ('fact("New since your visit"', 'fact("Kept a day"', "x.tokens_month", "scout(e.currentTarget, x)", "pause(null, x)", 'id="topic-sources-link"'):
        assert part in card, part
    # Best sources is retired from the head (the owner's O-2): the page's Sources section is the one list
    assert "bestSources" not in card and '"Best sources"' not in card
    assert "export const topSources" in src("pages/topics/topics.ts")
    ov = src("pages/topics/TopicOverview.svelte")
    for group in ('<TopicSourceRows {t} at={view.tick} mode="top" />', 'id="ov-themes"', '"Ideas waiting"', 'id="ov-ev"'):
        assert group in ov, group
    assert ov.index("<TopicSourceRows") < ov.index('id="ov-themes"'), "Sources is the first section"
    # one component draws a topic's rows: the page's section, its Sources page and the Edit sheet
    # (SRC D4), which keeps no list, Add form or Save of its own for sources
    assert "<TopicSourceRows {t} at={view.tick} />" in src("pages/topics/TopicSources.svelte")
    edit = src("pages/topics/TopicEdit.svelte")
    assert '<TopicSourceRows {t} mode="edit" {close} />' in edit and "te-find" not in edit and "toggle(remove" not in edit
    assert 'sort: "signal", limit: "5"' in ov, "the top evidence by signal"


def test_add_topic_is_the_list_and_its_side_the_pane():
    # moved: pages/welcome/AddTopic.svelte is the list of topics/new and onboarding's step 2
    reg = src("pages/index.ts")
    assert 'register("topics/new", {\n  list: lazy(() => import("./welcome/AddTopic.svelte")),\n  pane: lazy(() => import("./welcome/AddTopicPane.svelte")),' in reg
    step = src("pages/welcome/AddTopic.svelte")
    assert '<List title="Add topic" crumb="Topics"' in step and "<aside><TopicAside {view} welcome /></aside>" in step
    assert "nameEl.focus()" in step, "the name takes the cursor on open"
    assert '"topics/new"' not in src("pages/PaneEmpty.svelte") and "topicStep" not in JS
    assert "<TopicAside {view} />" in src("pages/welcome/AddTopicPane.svelte")
    aside = src("pages/welcome/TopicAside.svelte")
    assert "<h2>Your topics so far</h2>" in aside and "<h2>What happens next</h2>" in aside
    # the proposals' group is the old module's, a topic's Sources' and Today's too
    assert "<Proposals title={`Proposed for “${T.name.trim()}”`} tid={T.id} rows={T.rows} ticked={T.ticked} busy={!!scouting} plain={welcome} />" in step
    assert "watchTicked(t.id, t.rows, t.ticked)" in step
