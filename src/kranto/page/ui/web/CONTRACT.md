# The page's DOM contract

The browser smoke (`tests/page/test_browser_smoke.py`), the click stories (the click audit replayed on
every release candidate) and the page-source tests find things by these ids, roles and classes.
Every page kept them when it moved out of the old hand-written module into components,
so those ran unchanged through the migration. `tests/page/test_ui_contract.py` checks that each one below is still written by
the sources it names; change this file and its users together.

## The shell (`App.svelte`, `src/shell/`, `src/ui/DialogHost.svelte`)

| Selector | What it is |
|---|---|
| `#app` | the frame: five regions and two splitters in one grid |
| `#top` | the top bar (`header.hd`) |
| `#menu` | ☰, the navigator's drawer under 1180 px |
| `#hd-search` | the search button: the palette |
| `#hd-activity` | what Kranto is doing, one item for both lanes (`data-state`: quiet, running, paused, failed): Activity |
| `#pause` | Pause and Resume |
| `#theme` | ◐, light or dark |
| `#nav` | the navigator (`nav`, `aria-label="Sections"`) |
| `#nav-icons` | ‹ and ›: the navigator as icons |
| `.ni` | a navigator entry; `.on` the current one |
| `.ng` | a navigator heading; `.add` its "+ add" |
| `#split-nav` | the navigator's splitter (`role="separator"`) |
| `#split-detail` | the detail pane's splitter |
| `#list` | the list pane (`main`) |
| `#page-head` | the page's one head (`shell/PageHead.svelte`), the column's first child, once a page: the crumb, the glyph and title, at most one primary, ⋯ and the gear (`#page-gear`), the facts (`#page-facts`), the lede, the Activity line, one flash, the subnav (`.doornav`) |
| `#list-h` | the list's head: paused, the sign-in line, the flash |
| `#signin` | the sign-in line |
| `#signin-code` | its field |
| `#signin-go` | its button |
| `#undo` | a flash's Undo |
| `#rows` | the list (the old module draws its rows) |
| `#detail` | the detail pane (`section`) |
| `#dscroll` | the detail pane's scroller (the old module draws the pane) |
| `#term` | Open in Claude Code's panel: docked in `#detail` (glance), its right split (focus) |
| `#bar` | the status bar (`footer`) |
| `#key-hint` | the key hint, while a chord or a split is held |
| `#scrim` | the drawer's backdrop |
| `#dlg` | the one dialog (`ui/DialogHost.svelte`): every confirm and form, and the ? sheet |
| `#pal` | the palette (`dialog.pal`) |
| `#pal-q` | its field (`role="combobox"`) |
| `#pal-list` | its results (`role="listbox"`, options `role="option"`) |

## The pages (`src/pages/`, `src/ui/`, and the one popover `src/ui/popover.ts`)

| Selector | What it is |
|---|---|
| `li.row` | a list row; `.lr` one that opens in the pane; `.focus` the j/k row; `.sel` the selected one |
| `.wl` | a list's box, with its toolbar `.tb` |
| `.dh` | the pane's head |
| `.dback` | "‹ Back to the list" |
| `#dlg-t` | a dialog's title (`ui/DialogFrame.svelte`) |
| `#dlg-ok` | a dialog's main button |
| `.pop` | a popover (`.menu`: a ⋯ or a row's menu) |
| `.grade` | a grade control |
| `#model-key` | Welcome's model key field |
| `#key-save` | its Test and save |
