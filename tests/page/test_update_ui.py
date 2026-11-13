"""Updates in Kranto UI: the header pill, one Needs you row,
and Settings › System › Updates. the server's /api/status carries ``update``; /api/update the rest. What the
pill, the row and the page do is pressed in Vitest (lib/app/chrome.test.ts, lib/app/data.test.ts,
lib/app/today.test.ts, pages/today/today.svelte.test.ts, pages/settings/updates.svelte.test.ts);
here, what holds for their files."""
from .webui import nodes as ui_nodes
from .webui import src


def test_the_pill_offers_the_update_and_says_each_step():
    # installed → available and what's new, each step while it runs, a rollback: pressed in
    # lib/app/chrome.test.ts ("offers an update, says its step while it runs, and a rollback") and
    # lib/app/today.test.ts ("says each step of a running update on the header's pill")
    # the pill is its word; the versions are its tooltip and Settings › Updates'
    assert 'id="hd-update" href="#/settings/updates" title={u.title + (u.detail ? ": " + u.detail : "")}' in src("shell/Header.svelte")


# Needs you's one update row, first, counted, none while one runs; Try again and Open log after a
# rollback: pressed in pages/today/today.svelte.test.ts ("Today's helpers", "lists Needs you in
# its order…", "says an update rolled back with Try again…").


def test_restart_to_update_only_where_the_server_can():
    # Today's row: pressed in pages/today/today.svelte.test.ts ("says an update rolled back with
    # Try again, Restart to update only where Kranto can…"); the pane's in
    # pages/settings/updates.svelte.test.ts ("says How to update where this Kranto cannot apply
    # one…"); updApply's post in lib/app/data.test.ts ("restarts, rolls back after asking…")
    assert ">How to update</a>" in src("pages/front/Needs.svelte")
    assert ">How to update</a>" in src("pages/settings/UpdatesPane.svelte")


# The page reloads when the new version answers, keeps the last read through the restart, and
# reads /api/status every 5 s while an update runs: pressed in lib/app/data.test.ts ("keeps the
# last status while Kranto restarts, and reloads the page…") and lib/app/today.test.ts ("reads
# the server's status every 5 s while an update runs…").


def test_settings_updates_is_a_page_with_its_groups():
    """Moved into components: pages/settings/Updates*.svelte; their behaviour is tested
    in updates.svelte.test.ts (the groups, Check for updates, the forms and their Save, the actions)."""
    nodes = ui_nodes()
    # Updates is a group of Settings › System; its old route redirects there
    assert {"route": "settings/updates", "redirect": "settings/system"} in nodes
    assert "[UpdatesList]" in src("pages/settings/SystemList.svelte")
    page, pane = src("pages/settings/UpdatesList.svelte"), src("pages/settings/UpdatesPane.svelte")
    for group in ('key="version" word="Version"', 'key="auto" word="Automatic updates"', 'key="channel" word="Channel"'):
        assert group in page
    assert ">Check for updates<" in page and 'title="Recent updates"' in page
    assert 'name="upd-auto"' in pane and 'id="upd-window"' in pane and 'id="upd-channel"' in pane
    assert 'UPD_API + "/settings"' in pane
    assert "Restart to update" in pane and "`Roll back to ${to}`" in pane and ">Cancel<" in pane
    # the presses that the header's pill and Today's row share stay in one place: the app's
    # updApply, updRollback and updCancel (lib/app/data.test.ts "restarts, rolls back after
    # asking, and lets a waiting one go…"), which the pane calls
    assert "updApply(" in pane and "updRollback(" in pane and "updCancel(" in pane
