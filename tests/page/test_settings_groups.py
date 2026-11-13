"""Settings as lists and panes (WORKSPACE.md 2.12, 8 W5): every Settings page is a list of its
setting groups and real rows with no field in it; a group's form, with its Save, is in the detail
pane when the group is selected (sel=e<key>), and the page's context is the pane with nothing
selected. Also Settings › Prompts (PM-API.md), the default selections, Health's ?message=, the
welcome steps in the stage layout, and the CSS and markup of the pages that no longer exist.
What the pages do is pressed in Vitest beside them; here their files are read whole."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, src
from .webui import nodes as ui_nodes

UI = Path(api.__file__).parent
JS = everything()
CSS = css()




def nodes() -> list[dict]:
    return ui_nodes()


# Settings' pages (after the cut: no Building, Build tools or Publishing), by their
# key in the navigator's order: each page's list and pane, and the lists and panes it is made of
PAGES = {
    "watching": ("WatchingList.svelte", "WatchingPane.svelte",
                 ["KeysList", "ModelsList", "WatchReadList", "SearchList", "ConnectionsList"],
                 ["KeysPane", "ModelsPane", "WatchReadPane", "SearchPane", "ConnectionsPane"]),
    # open-source wave 2: the accounts a draft is sent with, what Kranto writes
    "posting": ("PostingList.svelte", "AccountsPane.svelte", ["ConnectionsList"], ["ConnectionsPane", "NewsletterPane"]),
    "sources": ("SourcesList.svelte", "SourcesPagePane.svelte", [], ["ConnectionsPane", "SourcesPane"]),
    "prompts": ("PromptsList.svelte", "PromptsPane.svelte", [], []),
    "spend": ("SpendList.svelte", "SpendPane.svelte", [], []),
    "privacy": ("PrivacyAccessList.svelte", "PrivacyAccessPane.svelte", ["PrivacyList", "AccessList"], ["PrivacyPane", "AccessPane"]),
    "system": ("SystemList.svelte", "SystemPane.svelte", ["ServiceList", "UpdatesList", "ActivitySetList", "HealthList", "GradesList"],
               ["ServicePane", "UpdatesPane", "HealthPane", "ActivitySetPane", "GradesPane"]),
    "assistant": ("AssistantList.svelte", "AssistantPane.svelte", [], []),
    "appearance": ("AppearanceList.svelte", "AppearancePane.svelte", [], []),
}


# pages that moved into components: their list and their pane (home and groups), registered
# by the route's node, and the Saves the pane carries (or the panes it opens, named in TYPES)
MOVED = {
    # an account's Test and Disconnect; a provider's Connect, its paste form's Save and Remove them
    "connections": ("settings/ConnectionsList.svelte", "settings/ConnectionsPane.svelte", ['id="test-account"', '>Disconnect</button>',
                    'id="connect"', 'id={"save-" + x.key}', 'id="clear-client"', 'id="device"']),
    # Sources (the node "settings") and Add source: a source's pane, a kind's form and its Add
    "": ("settings/SourcesList.svelte", "settings/SourcesPane.svelte", ['id="add"', 'id="preview"', 'id: "fetch-now"']),
    # the model key's Test and save (KeyField, onboarding's first step's too)
    "keys": ("settings/KeysList.svelte", "settings/KeysPane.svelte", ['id="key-save"']),
    "spend": ("settings/SpendList.svelte", "settings/SpendPane.svelte", ['id="save-cap"']),
    "models": ("settings/ModelsList.svelte", "settings/ModelsPane.svelte", ['id={"save-" + r.key}']),
    "updates": ("settings/UpdatesList.svelte", "settings/UpdatesPane.svelte", ['id="save-update"']),
    "health": ("settings/HealthList.svelte", "settings/HealthPane.svelte", ['id="run-ingest"']),
    "appearance": ("settings/AppearanceList.svelte", "settings/AppearancePane.svelte", ['id="save-custom"']),
    "access": ("settings/AccessList.svelte", "settings/AccessPane.svelte", ['id="add-agent-go"', 'id="save-actions"']),
    # the choice saves at once (UsageChoice, Welcome's too); no Save of its own
    "privacy": ("settings/PrivacyList.svelte", "settings/PrivacyPane.svelte", []),
    # PM-API.md: a prompt's additions and its full prompt (the server's prompts)
    "prompts": ("settings/PromptsList.svelte", "settings/PromptsPane.svelte", ['id="save-additions"', 'id="save-template"']),
}
# a moved page whose pane opens a pane per type of row: those panes carry its Saves
TYPES = {"": ("settings/SourcePane.svelte", "settings/CatalogPane.svelte"),
         "keys": ("settings/KeyField.svelte",)}


def test_a_moved_settings_page_is_a_list_and_a_pane_too():
    """Every list a Settings page is made of is setting groups and real rows with no field, and
    its pane carries its Saves (the lists keep their own <List>: alone they draw a page, inside one
    of the ten they draw their groups only, List's EMBED)."""
    for k, (lst, pane, saves) in MOVED.items():
        body, p = src("pages/" + lst), "".join(src("pages/" + f) for f in (pane, *TYPES.get(k, ())))
        for f in TYPES.get(k, ()):
            assert f"import {f.split('/')[-1].split('.')[0]} from \"./{f.split('/')[-1]}\"" in src("pages/" + pane), f
        # Sources is Watch's page with the doors on: its crumb says so (SRC D7)
        assert '<List title=' in body and ('crumb="Settings"' in body or (k == "" and "crumb={addCrumb}" in body)), k
        # no field in the list pane (a toolbar's filter is the only input there), and its rows are
        # setting groups that open in the pane, or its real rows (lessons, sources, kinds)
        assert not re.search(r'<(input(?! type="search")|textarea|select)\b', body), k
        assert "<SetRow " in body \
            or (k == "" and "<SrcLine {s} approve" in body and 'sel={s.available ? "epreset:" + s.key : null}' in body) \
            or (k == "connections" and '<Row sel={"eacct:" + a.id}' in body), k
        for save in saves:
            assert save in p and save not in body, (k, save)
    assert "function vSettings(" not in JS and "function paneGroup(" not in JS and "function paneSettings(" not in JS


def test_every_settings_page_is_a_list_with_its_panes():
    """The pages are registered by their route's node, in the navigator's order (pagedefs.ts);
    a page made of several lists draws them as Parts and opens their panes by the selection."""
    registry = src("pages/index.ts")
    defs = src("pages/settings/pagedefs.ts")
    assert re.findall(r'\{ key: "([a-z]+)", title:', defs) == list(PAGES)
    assert "export const SET: [string, string][] = SETTINGS_PAGES.map((p) => [p.key, p.title]);" in JS
    for k, (lst, pane, parts, panes) in PAGES.items():
        assert f'register("settings/{k}", {{\n  list: lazy(() => import("./settings/{lst}")),\n  pane: lazy(() => import("./settings/{pane}")),\n}});' in registry, k
        body, pb = src("pages/settings/" + lst), src("pages/settings/" + pane)
        for part in parts:
            assert f'import {part} from "./{part}.svelte";' in body and f"[{part}" in body, (k, part)
        for x in panes:
            assert f'import {x} from "./{x}.svelte";' in pb and f"<{x} {{view}} />" in pb, (k, x)
    assert 'register("settings", {\n  list: lazy(() => import("./settings/OverviewList.svelte")),' in registry


def test_a_group_row_is_its_state_its_name_and_its_value():
    row = src("ui/SetRow.svelte")                       # every Settings page's
    # the state's word beside its title too (UP #10)
    assert '<Row sel={"e" + key} title={word} meta={summary || null} stw={state}>' in row \
        and "<Glyph name={state[0]}" in row
    assert 'e: "setting"' in re.search(r"const NEEDSELS[^=]*= \{.*?\};", JS).group(0)
    # a group row has no number, no age, no end cell
    assert ".grp.sets { --tickw: 0px; --numw: 0px; --asidew: 0px; --endw: 0px; }" in CSS
    assert "paneSettings" not in src("pages/PaneEmpty.svelte"), "a Settings page's pane is its own page's"


def test_pages_open_with_their_main_group_selected():
    by = {n["route"]: n for n in nodes()}
    assert by["settings/watching"]["sel"] == "ekey" and by["settings/models"]["sel"] == "erole:afk:judge"
    assert by["settings/posting"]["sel"] == "enl" and by["settings/appearance"]["sel"] == "etheme"
    assert "sel" not in by["settings/prompts"]      # the factory's house rules left with it (CUT)
    # Spend opens on its breakdown with Totals and caps in the pane (S11 = 1): nothing selected
    assert "sel" not in by["settings/spend"] and "sel" not in by["settings"]
    # the route's sel on open, not on a phone (where a selection covers the list), and without
    # the server the first of the page's roles: pressed in lib/app/route.test.ts ("selects a settings
    # page's main group, but not on a phone…", "opens the first of the page's roles on Models
    # without the server")


def test_health_message_and_add_source_links_select_their_row():
    # ?message= and ?preset= / ?review= select their row: pressed in lib/app/route.test.ts
    # ("…Health's message and Add source's preset select theirs")
    # Health moved; a message's pane is Needs you's (pages/front), with its delivery
    health, lst = src("pages/settings/HealthPane.svelte"), src("pages/settings/HealthList.svelte")
    assert '{:else if k === "msg"}' in health and "<MessagePane {m} health more={delivery} />" in health
    assert "healthMessage" not in JS and "function paneMessage(" not in JS
    assert "MSG_SEEN" not in JS and "scrollIntoView" not in lst
    # a message has no grade: no bar on its pane, no cluster on its row
    assert "<GradeHead" not in src("pages/front/MessagePane.svelte") and "<Grade " not in lst
    # the catalog is the list; a kind's form is the pane (moved, pages/settings)
    assert 'sel={s.available ? "epreset:" + s.key : null}' in src("pages/settings/SourcesList.svelte")
    assert "{:else if id}\n  <CatalogPane {view} {id} />" in src("pages/settings/SourcesPane.svelte")
    cat = src("pages/settings/CatalogPane.svelte")
    assert 'k === "review" ? read<Sources>(SOURCES_API)' in cat and "String(view.w.r.q.topic" in cat


def test_the_key_field_is_still_a_password_never_kept():
    # moved: one form, KeyField.svelte, in Settings › Keys' Watching model pane (and onboarding's first step)
    field = src("pages/settings/KeyField.svelte")
    assert '<input id="model-key" type="password" autocomplete="off"' in field
    assert 'keyIn.value = "";' in field and "FORM" not in field
    pane = src("pages/settings/KeysPane.svelte")
    assert '{:else if id === "key"}' in pane and "<KeyField k={s.key} done={s.done} />" in pane
    assert 'const known = $derived(id === "key");' in pane and '{#if id && !known}' in pane


def test_models_save_only_on_save():
    # moved: pages/settings/Models*.svelte; models.svelte.test.ts holds the behaviour
    # a choice is kept, not written, Save is off until it changes, and only Save writes: pressed in
    # pages/settings/models.svelte.test.ts ("writes nothing until Save, then saves the role's choice")
    pane = src("pages/settings/ModelsPane.svelte")
    assert "L.api(AFK_MODELS, { role: r.role.role" in pane and "MODELS_API" not in pane   # the page's roles left
    # the first role is selected on open: S12 is Models, the select, Save
    assert 'key={"role:" + x.key}' in src("pages/settings/ModelsList.svelte")


def test_spend_is_the_only_page_with_dollars():
    # Spend moved: its dollars are in its own files
    spend = "".join(src(f) for f in ("pages/settings/SpendList.svelte", "pages/settings/SpendPane.svelte", "pages/settings/spend.svelte.ts"))
    for part in ("money(", "cents(", "capWord(", "usd("):
        assert part in spend, part
    for f in ("ModelsList", "ModelsPane", "UpdatesList", "UpdatesPane", "HealthList", "HealthPane", "PromptsList", "PromptsPane"):
        assert not re.search(r"money\(|cents\(|\$\d", src(f"pages/settings/{f}.svelte")), f


def test_prompts_page_follows_the_api():
    # moved: pages/settings/Prompts*.svelte and prompts.svelte.ts; prompts.svelte.test.ts
    # holds the behaviour
    lst, pane = src("pages/settings/PromptsList.svelte"), src("pages/settings/PromptsPane.svelte")
    ts = src("pages/settings/prompts.svelte.ts")
    # the server's /api/prompts directly (the page's own api/prompts left with the factory, CUT)
    assert "PGROUP_WORD: Record<string, string> = {}" in ts and 'export const PROMPTS_API = "/api/prompts";' in ts
    assert "HOUSE_API" not in ts
    # pressed in pages/settings/prompts.svelte.test.ts: the house rules first ("lists the house
    # rules first, then the prompts by their step"); the house rules saved and the licence set only
    # on Set ("saves the house rules, and sets the licence only on Set"); a prompt's additions and
    # full prompt from their drafts, only Save writing, and Reset ("saves additions and the full
    # prompt from their drafts, and resets"); Edit the full prompt only where it is editable, the
    # placeholders marked ("draws a prompt: about, placeholders, the full prompt and its diff…");
    # a checker's note, a changed default's three-way diff ("says a checker takes additions only,
    # and a default that changed"); a version opened in place, used again with no confirm and an
    # undo in the toast, its note kept ("opens a version in place, uses it again (undoable), and
    # keeps its note"), the house rules' versions ("says a version that can't be restored, and the
    # house rules' versions"); the preview against a real item ("previews against a real item; no
    # model is called")
    assert "No model is called." in ts
    # the preview's items are the app's (its builds, the loop's own ideas, topics, observations):
    # pressed in lib/app/commands.test.ts ("are the real builds, the loop's own ideas, the topics
    # and the newest observations")
    assert "app()?.previewSubjects(p)" in pane
    # the navigator's count of changed defaults reads the page's read, never asking itself
    # (the navigator's count of changed defaults left with the factory's prompts, CUT)
    assert "peek<Prompts>(PROMPTS_API)" not in JS and "let PROMPTS" not in JS
    # no sample prompt text: everything comes from the API
    for text in (JS, lst, pane, ts):
        assert "You are the product scout" not in text


def test_the_welcome_steps_draw_without_the_panes():
    by = {n["route"]: n for n in nodes()}
    for r in ("welcome", "welcome/topics", "welcome/finish", "hello"):
        assert by[r].get("stage") is True, r
    # moved: a stage route's page is its list (the stage is the list pane at full width)
    reg = src("pages/index.ts")
    assert 'register("welcome", { list: lazy(() => import("./welcome/Welcome.svelte")) });' in reg
    assert 'register("hello", { list: lazy(() => import("./welcome/Hello.svelte")) });' in reg
    # a stage has no pane: pressed in lib/app/route.test.ts ("replaces a redirect keeping its
    # filters and selection, and says Not found where there is no page")
    keys = src("pages/welcome/KeysStep.svelte")
    # its heading asks which model reads (no builds to choose it for any more)
    assert '<div class="narrow"><div class="ph"><h1>Which model reads for you?</h1></div>' in keys
    assert 'href="#/welcome/topics"' in keys and "{:else}<KeysStep {view} />" in src("pages/welcome/Welcome.svelte")


def test_no_decision_bar_jump_line_or_footer_left():
    for text in (JS, CSS):
        assert not re.search(r"[.\"]decide\b", text) and not re.search(r"[.\"]jump\b", text)
        assert "#foot" not in text and 'id: "foot"' not in text
    for gone in ("function row(", "function toggleRow(", "function listBar(", "function searchBar(", "function kvTable(", "function modelRow(", "function sourceRow("):
        assert gone not in JS, gone
    for gone in (".row.cr", ".divider", ".subnav", ".sided", ".preset.off", "table.srcs"):
        assert gone not in CSS, gone
    assert 'role: "tab' not in JS and "tablist" not in JS
