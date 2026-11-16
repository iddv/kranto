"""Grading in Kranto UI (once LEARNING.md section 3): one control,
▲ ▼ and a why chip, on idea cards and evidence only; no grade on builds, themes, messages, sources
or News; no bulk grading; the review queue of this week's cards and its keys; Settings › System ›
Your grades. The key maps (lib/keys.json) are read as the JSON they are and the components whole;
what they do is pressed in Vitest beside them (ui/grades.svelte.test.ts, ui/ticks.svelte.test.ts,
pages/review/review.svelte.test.ts, lib/app/grading.test.ts)."""
import json
import re

from .webui import SRC, css, everything, src

OBS_GRADE = '<Grade target="observation" id={o.id}'

JS = everything()
CSS = css()
QUEUE = json.loads(src("lib/keys.json"))["QUEUE_KEYS"]
KEYMAP = json.loads(src("lib/keys.json"))["KEYMAP"]


def test_one_control_on_cards_and_evidence_only():
    """a card's row (Ideas, a topic's cards) and an observation's row carry ▲ ▼; the idea
    sheet and the observation sheet carry the bar under the title. Nothing else draws a grade."""
    assert '<Grade target="idea" id={card}' in src("pages/ideas/IdeaLine.svelte")
    assert '<Grade target="idea" id={x.number}' in src("pages/ideas/CardLine.svelte")
    assert '<GradeHead target="idea" id={c.number}' in src("pages/ideas/Idea.svelte")
    assert OBS_GRADE in src("pages/library/ObsLine.svelte") and "grade={gradeOf(o, k)}" in src("pages/library/ObsList.svelte")
    assert '<GradeHead target="observation" id={o.id}' in src("pages/library/ObsPane.svelte")
    # the owner's words (2026-10-28): "it does not make sense for builds"; themes, messages, sources
    # and News go too
    for f in ("pages/library/ThemeLine.svelte", "pages/library/ThemePane.svelte",
              "pages/settings/HealthList.svelte", "pages/settings/SrcLine.svelte", "pages/settings/SourcePane.svelte",
              "features/news/NewsToday.svelte", "features/news/NewsPane.svelte", "features/news/BriefPage.svelte",
              "features/news/StoryPage.svelte"):
        text = src(f)
        assert "<Grade " not in text and "<GradeHead " not in text and "postGrade(" not in text and "BuildGrade" not in text, f
    assert not (SRC / "pages/builds/BuildGrade.svelte").exists()
    # the bar is one line; its why chips are a popover after a grade and on why ▾
    comp = src("ui/GradeHead.svelte")
    # (the compact card sheet draws no why ▾: the chips open after a grade beside the bar,)
    assert ">why ▾</button>" in comp and "whyPop(at, target, id, { what }, true)" in comp and "compact" in comp and 'class="gh line" data-why-target={target}' in comp
    pop = src("ui/WhyPop.svelte")
    assert "<kbd>{c.letter}</kbd>" in pop and "toggleChip(" in pop and "+ note" in pop
    for gone in ("function gradeMini(", "function gradeButtons(", "/verdict`", '"/api/grades"', "buildRefs", "buildGradeLine"):
        assert gone not in JS, gone


def test_the_control_is_two_glyphs_pressed_in_place_without_a_redraw():
    """▲ ▼, no ✕ (D-4: a wrong reading is a ▼ with its why chip; a stored wrong shows as ▼);
    aria-pressed, never colour alone; a second press clears (a skip row); data-verb names the verb.
    No render(), so the list does not move."""
    comp = src("ui/Grade.svelte")
    assert "aria-pressed={" in comp and '"skip" : v' in comp and "e.stopPropagation()" in comp and "render()" not in comp
    assert 'data-verb="feedback.add"' in comp and 'x === "wrong" ? "not_useful"' in comp
    assert re.search(r'\["useful", "▲".*\["not_useful", "▼", "Not useful", "dn", "2"\]\];', JS)
    assert '"✕", "Wrong' not in JS and "button.x" not in CSS.replace(".toast button.x", "")
    app, t = src("App.svelte"), src("ui/Toast.svelte")
    assert app.index('<div id="app">') < app.index("<!-- the drawer's backdrop") < app.index("<Toast />")
    assert ">Undo</button>" in t and 'role="status"' in t
    assert re.search(r"\.toast \{[^}]*position: fixed", CSS)


def test_chips_wait_for_a_grade_and_come_from_kranto():
    row = src("pages/review/Chips.svelte")
    assert "chipsOf(target)" in row and "disabled={!g}" in row and ">+ note</button>" in row
    assert "<kbd>{c.letter}</kbd>" in row and "function chipRow(" not in JS


def test_no_bulk_grading():
    """D-3: Select, the tick column, the bulk bar and x ⇧x ⌘a went (no batch row was ever written
    on live)."""
    assert not (SRC / "ui/BulkBar.svelte").exists() and not (SRC / "ui/Tick.svelte").exists()
    for gone in ("<BulkBar", "<Tick ", "/api/feedback/batch", "bulkGrade", "TICKED", "select-rows"):
        assert gone not in JS, gone
    assert ".bulk" not in CSS
    assert not [m for m in KEYMAP if m["keys"] in ("x", "⇧x", "⌘a", "3")]


def test_the_queue_key_map_covers_the_legend():
    keys = [m["keys"] for m in QUEUE]
    assert len(keys) == len(set(keys))
    assert set(keys) == {"j", "k", "1", "2", "0", "s", "a", "b", "c", "d", "e", "f", "enter", "n"}
    assert all(m["does"] and m["do"] in ("next", "prev", "grade", "skip", "chip", "open", "note") for m in QUEUE)
    review = src("pages/review/ReviewList.svelte")
    assert "for (const m of QUEUE_KEYS) L.pageKey(m.keys, () => reviewKey(m.keys));" in review


def test_the_queue_is_a_nav_entry_with_its_count_and_a_row_on_needs_you():
    assert '"review"' in re.search(r"const VIEWS = new Set\(\[(.*?)\]\)", JS).group(1)
    assert 'register("review", {' in src("pages/index.ts")
    # this week's cards only (D-2): the page names no builds, and drops one an older server sends
    assert 'REVIEW_API = "/api/review/queue";' in src("pages/review/review.ts")
    assert 'x.target !== "build"' in src("pages/review/review.ts") and 'x.target !== "build"' in src("pages/front/needs.ts")


def test_review_is_a_list_with_the_current_item_in_the_pane():
    review = src("pages/review/ReviewList.svelte")
    pane = src("pages/review/ReviewPane.svelte")
    assert "for (const m of QUEUE_KEYS) L.pageKey(m.keys" in review
    assert "cur={i === Q.at}" in review and '<Group id="queue" title="The queue"' in review and "Q.given[i]" in review
    assert '<div class="progress">' in review and "tools={progress}" in review, "the progress bar is the toolbar"
    assert 'register("review", {' in src("pages/index.ts") and "paneReview" not in src("pages/PaneEmpty.svelte")
    assert "<ReviewCard {x} i={Q.at} />" in pane and "So far this week" in pane
    assert "Back home" in pane and "Read the queue again" in pane
    assert "void Q.at;" in pane and "box.scrollTop = 0" in pane, "a new item starts at the pane's top"
    assert "<Grade target={x.target} id={x.id}" in review
    assert "walks the queue by its keys" in src("pages/review/review.svelte.test.ts")


def test_the_queue_asks_no_pairs():
    assert "qpair" not in src("pages/review/ReviewCard.svelte")
    assert "nothing acts on them yet" not in src("pages/review/review.svelte.ts")
    assert not [m for m in QUEUE if m["do"] == "pick"]


def test_settings_system_has_no_build_evaluation():
    """CUT: Settings › System lost the build benchmark (Evaluation); its parts are the service,
    updates, activity, health and Your grades (the server's /api/grades/summary: ratings steer
    gathering)."""
    sys_ = src("pages/settings/SystemList.svelte")
    assert "[[ServiceList], [UpdatesList], [ActivitySetList], [HealthList], [GradesList]]" in sys_
    assert '"/api/grades/summary"' in src("pages/settings/grades.ts")
    assert "EvaluationList" not in sys_ and not (SRC / "pages/settings/EvaluationList.svelte").exists()


def test_no_sample_data_in_the_grading_pages():
    review = src("pages/review/ReviewList.svelte")
    assert '<div class="mark-empty">' in review and "rebuilt each week" in review
    for sample in ("Plotkeeper", "Lesson Ledger", "AI developer tooling", "#245"):
        assert sample not in review, sample
