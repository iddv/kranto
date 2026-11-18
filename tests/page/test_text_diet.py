"""The text diet: a sentence that says what the data already says is gone; help
is a ? (TIPS) or the docs page, not a paragraph; empty states are one line; keys live in the
status bar and the ? sheet. The browser budget per page is tests/page/ui/text_budget.py (run on a
scratch copy by the shipping track, not in CI); this is its static half."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import everything, src

UI = Path(api.__file__).parent
JS = everything()

# sentences VERDICTS.md deletes or moves: never drawn as page text again (a TIPS entry or
# help.md may carry the words; the page does not)
GONE = [
    "What needs you, then the top of what is new in each topic, by signal.",
    "one press each",
    "Each row's twelve cells are its pipeline, scope to publish.",
    "One thread per conversation, kept in the loop's home under chat/.",
    "Build sends an idea to the pitch; its pane has Pass, Later and the card.",
    "open: waiting for you, or sent to the pitch",
    "the pitch took it; its build is under Builds",
    "passed, skipped, failed or closed",
    "ready to publish, held or failed",
    "public, private, closed, and fixes",
    "j k open one in the pane; 1 2 grade it; x ticks it for the bulk bar.",
    "Each observation placed by meaning, coloured by cluster.",
    "the eight largest have their own colour",
    "What the kranto watch, in your words.",
    "Cards written from this topic's themes, newest first.",
    "What was built from this topic's ideas.",
    "builds when you press Build",
    "Where this topic reads.",
    "Active watches read every topic's observations.",
    "Keys only: 1 2 3 grade, 0 skip, a–f a why chip.",
    "Where the kranto read, for every topic.",
    "Pick what to read. Each kind asks for one or two things",
    "Accounts Kranto may read with: read-only scopes only",
    "The model key Kranto watches with, and the two logins it builds with.",
    "Which model each part of Kranto calls.",
    "What each step is told.",
    "What your grades change, policy by policy.",
    "What Kranto did and what went wrong",
    "Where the money went, then every cap Kranto has.",
    "What is pulled from monitoring into the build pipeline",
    "Kranto keeps the published repos through GitHub",
    "What a build session can use beyond Claude Code's own tools.",
    "How Kranto looks in this browser.",
    "as the world will see it: rendered from the delivered branch",
    "choices the build left to whoever runs the product",
    "tokens and time; each row opens its log",
    "the loop's own notes, newest first",
    "From the last poll; each opens in this pane. GitHub is the record.",
    "held: every failed check is a reason",
    "in the task folder and the delivered branch: ",
    "A line opens the observation in this pane; original is the source.",
    "Its body and checks are on GitHub; kranto reads them at the next poll.",
    "What should exist, and for whom. Nothing is saved until you press Add.",
    "Select a row to see it here.",
    "Enter sends · Shift-Enter for a new line",
    "Each reply shows the tokens it used; the thread's total is on the right.",
    "Failures are recorded as data here instead of being lost in a log.",
    "Grades are kept and counted; each policy says what it still needs",
    "Builds have no cap unless you set one. Monitoring keeps a monthly budget.",
    "each with its own token",
    "The scout proposes sources for each topic; nothing is watched until you approve it.",
    "Pick a kind on the left. Each asks for one or two things",
    "the 12 most recent",
    "Read-only: to change a line, retire the watch",
]


def body():
    """the app's code without the tips (ui/tips.json): the words a page draws"""
    js = JS.replace(src("ui/tips.json"), "\n")
    return re.sub(r"/\*.*?\*/", "", js, flags=re.S)                      # not the comments


def test_the_deleted_sentences_are_gone():
    js = body()
    left = [s for s in GONE if s in js]
    assert not left, left


def test_no_hint_paragraph_outside_the_welcome_steps():
    # a field's hint is a ? beside its label (flabel); the Building step that kept its words left
    # with the factory
    assert 'h("p", { class: "hint"' not in JS
    assert 'class: "hint", text' not in JS


def test_the_review_legend_is_gone_and_its_keys_are_the_status_bar():
    assert 'h("div", { class: "keys" }' not in JS
    assert "0 skip · a–f why" in src("shell/StatusBar.svelte")


def test_a_list_has_no_sub_line_but_add_topic():
    calls = re.findall(r'listHead\((.*?)\)(?:,|;)', JS)
    subs = [c for c in calls if re.match(r'(?:\[[^\]]*\]|"[^"]*"|[^,"\[]+), (?:"[^"]*"|`[^`]*`|[^,]+), "', c)]
    assert len(subs) <= 1 and all("Add topic" in c for c in subs), subs


def test_empty_states_are_one_line():
    for t in re.findall(r'<p class="(?:empty|more)">([^<{]+)</p>', body()):
        long = [x for x in re.split(r"(?<=[.!?])\s+", t) if len(x.split()) > 3 and not x.startswith(("Click ", "Add "))]   # "Click Build on an idea." is an action
        assert len(long) <= 1 or "No topics yet" in t, t
