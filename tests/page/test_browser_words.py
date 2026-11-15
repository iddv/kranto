"""the word test, in CI: a fresh home, with builds and the shop off, says nothing
of what left: builds, cubs, and Invest, its broker, the trend radar and the browser
extension, which left the product. found eight pages of the fresh home with a word of builds, a cub
or the broker ("Step 3 asks when Kranto may build", "every feature and cub has its own page",
"Your broker", "builds $0.00 · pitches, checks, Claude Code", the map's "Build the map now"); the
walk was a walk, not a test, so nobody ran it again.

Every route a person meets first: the start page, Welcome's three steps, the four doors and the
map, Post, Settings and its seven pages, at 1400 px and on a 390 px phone. The page's own words
(``#app`` without the console) must hold none of the words nor the nouns. The server is
answered in the page (``PageAfk``: no topic yet). Needs the built UI (CI's browser job)."""
import json
import re

from .test_browser_buttons import HOST
from .test_browser_smoke import (  # noqa: F401 - fixtures
    PageAfk,
    browser,
    page_base,
    pytestmark,
    until,
)

# the word test, and the nouns for a person ("cub", "ticket", "practice run")
WORDS = re.compile(r"\b(build(?:s|ing)?|built|projects?|repos?|repositor(?:y|ies)|publish(?:ing|ed)?|pitch(?:es)?|"
                   r"invest|radar|broker|extension|pairing|shop|cubs?|tickets?|practice run|classic|arrange)\b", re.I)
# what left the product: never on any page, whatever is switched on
GONE = re.compile(r"\b(invest|radar|broker|extension)\b", re.I)
ROUTES = ["hello", "welcome", "welcome/topics", "welcome/finish",
          "news", "ideas", "watch", "watch/map", "post",
          "settings", "settings/watching", "settings/posting", "settings/assistant", "settings/spend",
          "settings/privacy", "settings/system", "settings/appearance"]
FRAMES = [(1400, 900), (390, 844)]
# a control whose box runs past the screen's right edge
OFF = """() => [...document.querySelectorAll('#app button, #app a.btn, #app input, #app select')]
  .filter((e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')
  .filter((e) => e.getBoundingClientRect().right > innerWidth + 1)
  .map((e) => (e.innerText || e.value || e.id || '').trim().slice(0, 50))"""
# The page's own words: #app (the console is docked beside it, outside #app)
TEXT = """() => { const a = document.querySelector('#app'); return a ? a.innerText : ''; }"""


class FreshAfk(PageAfk):
    """PageAfk as a fresh oss home answers ``/api/status`` (builds left with the factory: no
    ``builds`` flag), and the preview's line when ``preview`` is given."""

    def __init__(self, preview: str | None = None, **kw):
        super().__init__(**kw)
        self.preview = preview

    def install(self, page):
        super().install(page)
        shell = {**HOST["/api/shell"], "cubs": [], "layout": "new", "home": True, "doors": True, "pins": []}
        first = {"words": "", "at": None, "observations": 0, "needed": 30}
        page.route(re.compile(r"^https?://[^/]+/api/ideas(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"ideas": [], "count": 0, "first": first})))
        page.route(re.compile(r"^https?://[^/]+/api/(shell|features|cubs|tickets)(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(shell if "/api/shell" in rt.request.url else {"features": [], "api": "", "reads": [],
                                                                           "request_kinds": []}
                            if "/api/features" in rt.request.url else {"cubs": [], "tickets": []})))

    def answer(self, rt):
        if rt.request.url.split("?")[0].endswith("/api/status"):
            out = {"budget_usd": 0, "version": "fresh", "paused": None, "topics": self.topics, "observations": 0,
                   "runs": [], "update": None, "sources": [], "tokens_today": None, "next_run": {}, "running": None}
            if self.preview:
                out["preview"] = {"line": self.preview, "copied_at": "2026-11-11T10:36:11Z", "commits": None}
            return rt.fulfill(status=200, content_type="application/json", body=json.dumps(out))
        return super().answer(rt)


def _hits(text: str) -> list[str]:
    return [line.strip()[:160] for line in text.split("\n") if WORDS.search(line)]


def test_a_fresh_home_says_nothing_of_builds_cubs_or_the_broker(browser, page_base):
    found: dict[str, list[str]] = {}
    for width, height in FRAMES:
        ctx = browser.new_context(viewport={"width": width, "height": height},
                                  has_touch=width < 500, is_mobile=width < 500)
        page = ctx.new_page()
        FreshAfk(setup=True, topics=()).install(page)
        page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
        page.goto(f"{page_base}/#/hello")
        until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
        for route in ROUTES:
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            page.wait_for_timeout(600)
            hits = _hits(page.evaluate(TEXT))
            if hits:
                found[f"{width} #/{route}"] = hits
            # on a phone no control of Settings runs off the screen ("Check for updates")
            if route.startswith("settings") and width < 500:
                off = page.evaluate(OFF)
                if off:
                    found[f"{width} #/{route} off the screen"] = off
        ctx.close()
    assert not found, json.dumps(found, indent=1, ensure_ascii=False)


def test_the_previews_strip_is_never_cut_on_a_phone(browser, page_base):
    """on a 390 px phone the strip read "Preview: a copy of your data from 11
    November. Nothi…" (441 px of text in 390): it wraps instead."""
    line = "Preview: a copy of your data from 11 November. Nothing is sent."
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    FreshAfk(preview=line, topics=["Padel"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
    page.goto(f"{page_base}/#/home")
    until(page, "document.querySelector('#preview-strip')", 15)
    got = page.evaluate("""() => { const s = document.querySelector('#preview-strip');
      return { text: s.innerText, shown: s.getClientRects().length > 0, sw: s.scrollWidth, cw: s.clientWidth }; }""")
    ctx.close()
    assert got["shown"] and got["text"] == line, got
    assert got["sw"] <= got["cw"], got


START = {"topic_id": 1, "done": False, "quiet": None, "observations": 4, "needed": 30, "rows": [
    {"key": "sources", "title": "Sources", "state": "done", "words": "11 sources watched", "at": "2026-10-29T09:00:00Z"},
    {"key": "read", "title": "First read", "state": "done", "words": "Kept 1 of 40 items read", "at": "2026-10-29T10:00:00Z"},
    {"key": "brief", "title": "First brief", "state": "waiting", "words": "Written as soon as the first read ends", "at": "2026-11-12T15:00:00Z"},
    {"key": "ideas", "title": "First ideas", "state": "waiting", "words": "After the map, once 30 items are kept. So far: 4.", "at": "2026-11-12T22:00:00Z"}]}


def test_the_first_hours_rows_keep_their_words_and_dates_on_a_phone(browser, page_base):
    """on a phone the four rows lost their words ("First brief", "First ideas" alone)
    and the dates were cut ("29 Oc"); at 1400 too, the rows' 40 px age column cut "29 Oct 06:47"."""
    for width, height in FRAMES:
        ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=width < 500,
                                  is_mobile=width < 500)
        page = ctx.new_page()
        FreshAfk(topics=["Padel"]).install(page)
        page.route(re.compile(r"/api/topics/1/start(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(START)))
        page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
        page.goto(f"{page_base}/#/topics/1")
        until(page, "document.querySelectorAll('section[aria-labelledby=topic-start] li.row').length === 4", 15)
        rows = page.evaluate("""() => [...document.querySelectorAll('section[aria-labelledby=topic-start] li.row')].map((r) => {
          const m = r.querySelector('.c-meta'), a = r.querySelector('.c-age');
          return { words: m ? m.innerText : '', shown: !!m && m.getClientRects().length > 0 && m.getBoundingClientRect().width > 0,
                   age: a ? a.innerText : '', cut: !!a && a.scrollWidth > a.clientWidth + 1 }; })""")
        ctx.close()
        assert [r["words"] for r in rows] == [x["words"] for x in START["rows"]], (width, rows)
        assert all(r["shown"] and not r["cut"] and r["age"] for r in rows), (width, rows)


CARD = {"id": 143, "title": "Padel court finder", "state": "waiting", "created_at": "2026-11-10T08:00:00Z", "topics": [],
        "thesis": "Clubs book by phone.", "status": "shown", "score": 0.5, "grade": None,
        "evidence": [{"observation_id": 1, "claim": "a", "url": "https://padelfip.com/a"},
                     {"observation_id": 2, "claim": "b", "url": "https://reuters.com/b"}]}


def test_the_write_a_post_journey_from_a_card_to_the_draft_on_post(browser, page_base):
    """the journey in a browser, with builds off: the card's Write a post, the
    question, Write draft (POST /api/post/write), then the page follows the job and says "The
    draft is on Post."; a job that fails says why in a red line."""
    for end, said in (({"state": "done"}, "The draft is on Post."),
                      ({"state": "failed", "error": "No draft was written: the model did not answer."},
                       "No draft was written: the model did not answer.")):
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        FreshAfk(topics=["Padel"]).install(page)
        writes = []

        def ideas(rt):
            path = rt.request.url.split("?")[0]
            body = CARD if path.endswith("/api/ideas/143") else {"ideas": [CARD], "count": 1}
            rt.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        def writer(job):
            def write(rt):
                if rt.request.method == "POST":
                    writes.append(rt.request.post_data)
                    return rt.fulfill(status=202, content_type="application/json", body=json.dumps({"state": "running"}))
                rt.fulfill(status=200, content_type="application/json", body=json.dumps(job))
            return write
        page.route(re.compile(r"/api/ideas(/143)?(\?.*)?$"), ideas)
        page.route(re.compile(r"/api/post/write(\?.*)?$"), writer(end))
        page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
        page.goto(f"{page_base}/#/ideas/143")
        until(page, "document.querySelector('#idea-write')", 15)
        page.click("#idea-write")
        until(page, "document.querySelector('#dlg-ok')", 10)
        assert page.inner_text("#dlg-t") == "Write a post about this idea?"
        page.click("#dlg-ok")
        assert until(page, f"document.body.innerText.includes({json.dumps(said)})", 20, must=False), \
            page.evaluate("document.body.innerText.slice(-800)")
        ctx.close()
        assert writes and json.loads(writes[0]) == {"about": "card:143", "as": "blog"}


def test_keys_and_the_palette_say_nothing_of_builds_with_builds_off(browser, page_base):
    """ B (Codex 9, 21; Gemini 7): ? keys listed g b Builds, g p Projects, b Build and a
    Trace section; ⌘K had a Builds filter; "console" found no console and "post" + enter opened
    Settings › Posting. With builds off: none of it, the console offered, Post first."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    FreshAfk(topics=["Padel"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
    page.goto(f"{page_base}/#/home")
    until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
    page.wait_for_timeout(800)
    page.keyboard.press("?")
    until(page, "document.querySelector('#dlg') && document.querySelector('#dlg').innerText.includes('Keyboard')", 10)
    keys = page.inner_text("#dlg")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.keyboard.press("Control+k")
    until(page, "document.querySelector('#pal') && document.querySelector('#pal').open", 10)
    pal = page.inner_text("#pal")
    page.fill("#pal-q", "console")
    page.wait_for_timeout(400)
    console = page.inner_text("#pal-list")
    page.fill("#pal-q", "post")
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    landed = page.evaluate("location.hash")
    ctx.close()
    assert not _hits(keys), _hits(keys)
    assert "Keyboard shortcuts" in keys and "Later" in keys
    assert not _hits(pal), _hits(pal)
    assert "Console" in console, console
    assert landed.split("?")[0] == "#/post", landed


def test_prompts_keys_and_the_palette_say_nothing_of_what_left(browser, page_base):
    """ A2: Settings › Prompts, the ? keys sheet and ⌘K (searched for each word) name no
    broker, no Invest, no radar and no browser extension."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    FreshAfk(topics=["Padel"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
    page.goto(f"{page_base}/#/settings/prompts")
    until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
    until(page, "!!document.querySelector('#rows li.row, #rows .state-empty')", 15, must=False)
    page.wait_for_timeout(600)
    said = {"settings/prompts": page.evaluate(TEXT)}
    page.keyboard.press("?")
    until(page, "document.querySelector('#dlg') && document.querySelector('#dlg').innerText.includes('Keyboard')", 10)
    said["?"] = page.inner_text("#dlg")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.keyboard.press("Control+k")
    until(page, "document.querySelector('#pal') && document.querySelector('#pal').open", 10)
    said["⌘K"] = page.inner_text("#pal")
    for q in ("invest", "radar", "broker", "browser", "extension", "trend"):
        page.fill("#pal-q", q)
        page.wait_for_timeout(400)
        said[f"⌘K {q}"] = page.inner_text("#pal-list")
    ctx.close()
    # the palette's own echo of the query ("Nothing matches "invest".") is not a page's word
    hits = {k: [ln.strip()[:160] for ln in v.split("\n")
                if GONE.search(ln) and not ln.strip().startswith("Nothing matches")]
            for k, v in said.items()}
    assert not any(hits.values()), json.dumps(hits, indent=1, ensure_ascii=False)


def test_the_word_list_catches_what_orev2_found():
    """the list itself: each sentence found on the fresh home is caught"""
    for said in ("Step 3 asks when Kranto may build", "every feature and cub has its own page", "Your broker",
                 "builds $0.00 · pitches, checks, Claude Code", "Build the map now", "after the pitch: Receipts"):
        assert WORDS.search(said), said
    assert not WORDS.search("The first brief is written right after the first read")
    for said in ("Invest's cards", "the trend radar", "Connect a broker", "the browser extension"):
        assert GONE.search(said) and WORDS.search(said), said
    assert not GONE.search("investigate the radars of brokers' extensions")   # whole words only


# the plain-words list, the left column, for the pages F2 draws (News, a story, a
# draft's page, Settings › Posting › How you write, Needs you): none of it on a fresh home either
PLAIN_F2 = re.compile(r"Kranto on\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:obs|exa) \d+|observation \d+ ›|Deep dive now|Article · \d|"
                      r"this brief ›|About this brief|thing wait on|needs_confirm|readback|"
                      r"draft\.sanity|9999-12-31|HN search:|Exa, free mode", re.I)
# (the fake the server answers News's and Post's reads with 404, which the page says as "Could not
# read the server: not found"; a missing source's sheet is 's, in acceptance.py)
F2_ROUTES = ["news", "news/earlier", "post", "settings/posting", "settings/posting/voice", "needs"]


def test_f2s_pages_hold_none_of_front_56s_words(browser, page_base):
    found: dict[str, list[str]] = {}
    for width, height in FRAMES:
        ctx = browser.new_context(viewport={"width": width, "height": height}, has_touch=width < 500,
                                  is_mobile=width < 500)
        page = ctx.new_page()
        FreshAfk(setup=True, topics=()).install(page)
        page.goto(f"{page_base}/#/hello")
        until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
        for route in F2_ROUTES:
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            page.wait_for_timeout(600)
            hits = [line.strip()[:160] for line in page.evaluate(TEXT).split("\n") if PLAIN_F2.search(line)]
            if hits:
                found[f"{width} #/{route}"] = hits
        ctx.close()
    assert not found, json.dumps(found, indent=1, ensure_ascii=False)


def test_front_56s_list_catches_what_the_testers_found():
    for said in ("Why: Kranto on robot costs", "obs 12825 · exa 3", "observation 13183 ›", "Deep dive now",
                 "1 thing wait on you", "HN search: coding agent, 2026-11-11"):
        assert PLAIN_F2.search(said), said
    assert not PLAIN_F2.search("Why it matters · cheap arms learn faster · Hacker News · 11 Nov")
