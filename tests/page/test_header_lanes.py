"""The header says what Kranto is doing in one item, in place
of the two lane words it once drew (watching, building): "Quiet · next: reading your sources
at 18:00", "2 running · writing the News brief", "Paused", a red dot once when
something failed. One "Idle" beside a Pause that pauses everything read as "the whole app is
idle"; the item never says it. Pause's tooltip, its confirmation and its flash say what it stops.
Read here: the files' words. What they do is pressed in Vitest: the item's states in
lib/activity.test.ts and shell/shell.test.ts, the facts behind it in lib/app/chrome.test.ts,
Pause's question and its answer in lib/app/data.test.ts, the next read in lib/format.test.ts."""
from .webui import src

HEADER = src("shell/Header.svelte")
ITEM = src("shell/ActivityIndicator.svelte")
WORDS = src("lib/activity.ts")


def test_the_header_draws_one_item_for_both_lanes_and_no_bare_idle():
    assert "<ActivityIndicator {lanes}" in HEADER and 'id="hd-update"' in HEADER
    assert 'id="hd-activity"' in ITEM and 'href="#/activity"' in ITEM
    for word in ('word: "Paused"', "`${n} running`", "`Quiet · ${failed} failed`",
                 '"Quiet"', "next: ${lower(q.title)} at", "next: reading your sources at"):
        assert word in WORDS, word
    for gone in ('word="Watching"', 'word="No build running"', 'id="hd-watch"', 'id="hd-running"'):
        assert gone not in HEADER, gone
    assert "Idle" not in HEADER[HEADER.index("</script>"):], "no bare Idle in what it draws"
    assert "Idle" not in ITEM and "Idle" not in WORDS


def test_pause_says_what_it_stops():
    # no builds to pause since the cut: Pause stops reading sources and writing ideas
    assert "`Pause everything: stops ${f.pauses}.`" in HEADER and "build" not in HEADER.lower().split("</script>")[1]
    data = src("lib/app/data.ts")
    assert 'export const PAUSES = "reading sources and writing ideas";' in data and "buildsOff" not in data


def test_health_says_watching_and_the_next_read():
    health = src("pages/settings/HealthPane.svelte")      # moved
    assert '"Reading sources…"' in health and '" · next read " + nextRead(nextAt)' in health
