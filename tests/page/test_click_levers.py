"""The click levers CLICKS-v4.md measured (fleet2 track U7): Spend with its breakdowns first (S11), the model key
tested on paste (S01) (Today's top 20 and New idea left with the cut);
and two fixes: mute is its own control, apart from the source link, and Today's Spend box and
the header's chip show the same week from the same source."""
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, src

UI = Path(api.__file__).parent
JS = everything()
CSS = css()




def test_evidence_cuts_at_top_with_a_show_all_link():
    # the Library's Observations (a moved page,), a topic's Evidence too: the cut is
    # always the first rows, no pages under it, Show all: pressed in
    # pages/library/observations.svelte.test.ts ("reads a page of the library, a search by
    # meaning, or the first 20", "cuts a page at the top 20 with Show all, and pages the rest")
    lib = src("pages/library/ObsList.svelte")
    assert '<a id="show-all" href={href(base, { ...r.q, top: "" })}>{`Show all ${d.total}`}</a>' in lib


# -- the mute control -----------------------------------------------------------------------
def test_mute_is_its_own_control_apart_from_the_source_link():
    # one row everywhere (the Library's, a topic's, Today's: took the old module's obsLine);
    # mute in the end cell by the grade, the source cell the source link only: pressed in
    # pages/library/observations.svelte.test.ts ("groups the rows by their new flag, each with its
    # tick, mute and grade")
    assert "function obsLine(" not in JS
    # no mute on the row; Mute is on the observation's sheet and the source's
    line = src("pages/library/ObsLine.svelte")
    assert 'class="btn sm mute"' not in line and "muteMenu(" not in line
    assert "muteMenu(e.currentTarget" in src("pages/library/ObsPane.svelte")
    assert ".c-end .btn.mute" not in CSS
    assert ".row.cr" not in CSS
    assert "button.linkish.mute" not in CSS


# -- Spend: dollars only on Settings › Spend (the owner's ruling, 2026-10-09) --------------------
def test_no_spend_chip_and_today_keeps_only_a_quiet_tokens_line():
    assert "function spendChip" not in JS and "hd-spend" not in JS
    header = src("shell/Header.svelte")
    assert "chip spend" not in header and "cents(" not in header
    today = src("pages/front/Needs.svelte")       # Today is Needs you since the cut
    bar = src("shell/StatusBar.svelte")
    assert "cents(" not in today + bar and "money(" not in today + bar and '"Spend"' not in today
    # the status bar's tokens today, the builds' and the watcher's, never dollars: pressed in
    # lib/app/chrome.test.ts ("says the service in one word, today's tokens and the server's health")


def test_spend_opens_with_the_breakdowns_first():
    # W5: the breakdown is the list, By topic first, the caps last: pressed in
    # pages/settings/spend.svelte.test.ts ("lists where it went first, then the caps; …"); the caps
    # are the pane with nothing selected: lib/app/topics.test.ts ("opens with nothing selected on
    # Totals and caps: …")
    assert '{"route": "settings/spend", "node": "settings/spend"}' in JS, "no row selected on open: S11 is one click"


# -- S16 and S01 -------------------------------------------------------------------------------
def test_the_key_is_tested_on_paste_and_never_kept():
    # moved: the key's form is KeyField.svelte, Settings › Keys' and the welcome step's;
    # tested on a paste and after a pause in typing, the same press as the button: pressed in
    # pages/settings/keys.svelte.test.ts ("presses Test and save on a paste, and after a pause in
    # typing something key-length")
    field = src("pages/settings/KeyField.svelte")
    # never echoed or logged: nothing in the page writes it to the console (test_topics_ui
    # checks it is never kept)
    assert "console." not in field
