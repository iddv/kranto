"""The page in a real browser: every route of lib/nodes.json that draws a page (not a
redirect) opens with the server answered in the page (PageAfk: no model, no network), and none of
them throws, logs a console error, gets a server error or sends a write; the shell's keys, palette
and theme work. The tests that read the page as text can't see any of that: a typo in a
function no test reads, a module that fails to load (S-3b, S-4). The page is the built UI since
so these need a build (``python3 scripts/dev/build_ui.py``; CI's browser job builds first).

The page server (``brb ui``'s ``make_server``) serves the page and its own routes; everything
the server answers (``/api/status``, ``/api/ideas``, ``/api/today``…) is answered in the page.

Needs Playwright and its headless Chromium (``uv sync --group browser``, then
``playwright install chromium-headless-shell``). Where they are missing the test is skipped
with the reason; CI's ``browser`` job sets ``KRANTO_BROWSER_REQUIRED=1``, so there it fails.
"""
import json
import os
import re
import threading
import time

import pytest

from kranto.page import tokens as tokens_mod
from kranto.page.ui.routes import static
from kranto.page.ui.server import make_server

from .webui import nodes

pytestmark = [pytest.mark.browser, pytest.mark.built_ui]
REQUIRED = os.environ.get("KRANTO_BROWSER_REQUIRED") == "1"
# a real build, seen before conftest's stand-in (an empty module) takes its place
BUILT = (static.APP_DIR / ".vite" / "manifest.json").is_file()
# without the server the page asks for its host once and gets a 404: that is how it knows
HOST_PROBE = "/api/status"


def routes() -> list[str]:
    """every route that draws a page of its own: no parameter, no redirect (an old address of a
    page that left lands elsewhere; lib/app/redirects.test.ts walks those)"""
    return [r for r in dict.fromkeys(n["route"] for n in nodes() if not n.get("redirect")) if ":" not in r]


@pytest.fixture(scope="module")
def browser():
    if not BUILT:
        if REQUIRED:
            pytest.fail("the web UI is not built: python3 scripts/dev/build_ui.py")
        pytest.skip("the web UI is not built: python3 scripts/dev/build_ui.py")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        if REQUIRED:
            raise
        pytest.skip(f"Playwright is not installed ({e}): uv sync --group browser")
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                       # noqa: BLE001 - no browser here
            if REQUIRED:
                raise
            pytest.skip(f"no headless Chromium ({str(e).splitlines()[0]}): "
                        "playwright install chromium-headless-shell")
        yield b
        b.close()


@pytest.fixture
def page_base(tmp_path):
    """the page server on loopback, with an empty home: the page's own routes (the console, the
    trace, activity); the server is answered in each test's page"""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "loop").mkdir()
    srv = make_server(tmp_path / "tasks", port=0, harness="fake", loop_home=tmp_path / "loop",
                      tokens=tokens_mod.Store(tmp_path / "tokens"), require=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def until(page, js: str, timeout_s: float = 30.0, must: bool = True) -> bool:
    """Wait until the expression ``js`` is true on the page. Not ``page.wait_for_function``:
    Playwright runs a string predicate through eval in the page, and the page's CSP
    (script-src 'self') refuses that at times (a known flake: "EvalError ... 'unsafe-eval'");
    ``page.evaluate`` of a function is not eval. ``must``: an AssertionError when it never is."""
    end = time.monotonic() + timeout_s
    while not page.evaluate(f"() => Boolean({js})"):
        if time.monotonic() > end:
            if must:
                raise AssertionError(f"not true after {timeout_s:g} s: {js}")
            return False
        page.wait_for_timeout(50)
    return True


def setting_keys() -> list[str]:
    """Every dotted key of the page server's settings (``loop.yaml``), longest first."""
    from kranto.page.settings.store import DEFAULTS

    def walk(d, pre=""):
        for k, v in d.items():
            key = f"{pre}{k}"
            yield key
            if isinstance(v, dict):
                yield from walk(v, key + ".")
    return sorted({k for k in walk(DEFAULTS) if "." in k}, key=len, reverse=True)


# what the owner reads on a page: the text, without the places a key belongs (a code span, the
# "key and its file" line, an Advanced fold, Settings' Advanced group) or a field's value
OWNER_TEXT = """() => {
  const b = document.body.cloneNode(true);
  b.querySelectorAll("code, kbd, pre, input, textarea, select, details.advanced, #set-advanced, script, style").forEach((e) => e.remove());
  return b.innerText;
}"""
# words that are only ever a bug on a page (QA B7, B10: "theme null", a setting key in a row)
NOT_WORDS = re.compile(r"\b(null|undefined|NaN)\b|\[object |Traceback")
# names retired with the doors (QA B11) and with the factory (CUT)
RETIRED = re.compile(r"Go to Today|\(the Library\)|Needs you \(Today\)|Settings › (Publishing|Building)|\bBuild tools\b|"
                     r"\bBuilds?\b|\bProjects\b|\bRepos\b|GitHub App")


def owner_words(text: str, keys: list[str]) -> list[str]:
    """What should not be on a page the owner reads: a setting key, null/undefined, a retired
    name. The guard QA asked for (qa/BUGS.md, "Why so many")."""
    out = [m.group(0) for m in NOT_WORDS.finditer(text)][:3]
    out += [k for k in keys if re.search(rf"(?<![\w.]){re.escape(k)}(?![\w])", text)][:3]
    out += [m.group(0) for m in RETIRED.finditer(text)][:3]
    return out


def test_owner_words_finds_keys_nulls_and_retired_names():
    keys = setting_keys() or ["term.enabled"]
    key = keys[-1]
    assert owner_words(f"every 3 h · theme null · {key} · required · Go to Today", keys) == ["null", key, "Go to Today"]
    assert owner_words("Settings › Building › Rules · Builds", keys) == ["Settings › Building", "Builds"]
    # prose and file names are not keys: kranto.yaml, loop.yaml, a domain
    assert owner_words("in your settings (loop.yaml) · example.com · Write a post", keys) == []


# -- the server, answered in the page ------------------------------------------------------------
AFK_PATHS = re.compile(r"^https?://[^/]+/api/(status|setup(/key|/provider|/finish|/check)?|topics(/\d+(/scout)?)?|"
                       r"sources(/approve|/from-text(/\d+)?)?|catalog|today|observations|ideas(/\d+(/later)?)?|"
                       r"feedback(/vocabulary|/batch)?|review/queue|connections|seen)(\?.*)?$")
SCREENS = """e => {
  let p = e.parentElement;
  while (p && !(p.scrollHeight > p.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(p).overflowY))) p = p.parentElement;
  const b = p ? p.getBoundingClientRect() : { top: 0, bottom: innerHeight };
  const top = Math.max(b.top, 0), bottom = Math.min(b.bottom, innerHeight), r = e.getBoundingClientRect();
  if (r.top >= top - 1 && r.bottom <= bottom + 1) return 0;
  return Math.max(1, Math.ceil((r.bottom - bottom) / Math.max(1, (bottom - top) * 0.9)));
}"""


class Clicks:
    """A story's count: each press, each field focused by hand, each screen scrolled."""

    def __init__(self, page):
        self.page, self.n, self.log = page, 0, []

    def _scroll(self, loc, why):
        k = loc.evaluate(SCREENS)
        if k:
            self.n += k
            self.log.append(f"{k} scroll{'s' if k > 1 else ''} to {why}")
            loc.scroll_into_view_if_needed()

    def click(self, sel, why=None):
        loc = self.page.locator(sel).first
        loc.wait_for()
        self._scroll(loc, why or sel)
        self.n += 1
        self.log.append(why or sel)
        loc.click()

    def type(self, sel, text, why=None):
        loc = self.page.locator(sel).first
        loc.wait_for()
        if not loc.evaluate("e => e === document.activeElement"):
            self._scroll(loc, why or sel)
            self.n += 1
            self.log.append(f"focus {why or sel}")
        loc.fill(text)

    def paste(self, sel, text):
        """a paste (⌘V) into a field: the click that focuses it, if it has not the cursor yet"""
        loc = self.page.locator(sel).first
        loc.wait_for()
        if not loc.evaluate("e => e === document.activeElement"):
            self.n += 1
            self.log.append(f"focus {sel}")
            loc.focus()
        loc.evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('paste', { bubbles: true })); }", text)

    def read(self, sel, why):
        """reading down to the end of sel: the screens it takes"""
        loc = self.page.locator(sel).last
        loc.wait_for()
        self._scroll(loc, why)


def bear_card(n: int, title: str, state: str = "waiting", **o) -> dict:
    """an idea card as the server's /api/ideas answers it"""
    return {"id": n, "number": n, "title": title, "status": "shown", "state": state, "score": 0.3, "grade": None,
            "thesis": f"{title}: a thesis.", "one_liner": title, "topics": [], "citations": [], "evidence": [],
            "created_at": "2026-10-01T08:00:00Z", "later_until": None, **o}


class PageAfk:
    """the server's JSON, answered in the page: a first run's setup (the key, Finish), the topics
    with their scout and their pages, the sources, the inbox's read (/api/today), a topic's new rows
    by signal, the idea cards. Every write is kept in ``writes``; nothing reaches a server."""

    PROPOSALS = [{"id": 31 + k, "label": label, "role": role, "pretick": pre, "review": "proposed", "site_name": site,
                  "why": "covers it", "validation": {"median_similarity": sim, "recent": 90}}
                 for k, (label, role, pre, site, sim) in enumerate([
                     ("HN: local-first", "core", True, "news.ycombinator.com", 0.52), ("Ink & Switch", "core", True, "inkandswitch.com", 0.47),
                     ("r/selfhosted", "core", False, "reddit.com", 0.33), ("arXiv cs.DC", "wildcard", False, "arxiv.org", 0.21)])]

    # a pasted list, resolved (the server's /api/sources/from-text batch): two fetched, one not
    DESCRIBED = [{"id": 41 + k, "label": label, "role": "core", "pretick": False, "review": rv, "group": "proposed", "site_name": label,
                  "why": None, "items_per_day": None, "validation": {"items": 20, "recent": 6, "from": line}, "topics": []}
                 for k, (label, rv, line) in enumerate([("this-week-in-rust.org", "proposed", "that Rust weekly thing"),
                                                        ("fly.io", "proposed", "Fly.io's blog"), ("jepsen.io", "invalid", "Jepsen")])]

    def batch(self, topic):
        def line(status, src, why=None, **o):
            row = next((x for x in self.DESCRIBED if src is not None and x["id"] == src), None)
            return {"status": status, "from": row["validation"]["from"] if row else o.pop("frm"), "preset": "web.site", "fields": {},
                    "why": why, "cost": None, "source_id": src, "label": row["label"] if row else None, "row": row, **o}
        lines = [line("valid", 41), line("valid", 42), line("invalid", 43, "no feed found at https://jepsen.io/"),
                 line("not_found", None, "LinkedIn is not offered", frm="my LinkedIn feed", preset=None),
                 line("connect_first", None, "connect X / Twitter first", frm="@karpathy on X", preset="x.profile")]
        return {"id": "fromtext:9", "call_id": 9, "topic": topic, "lines": lines, "stopped_at": None, "read": 80, "total": 80,
                "counts": {"valid": 2, "unverified": 0, "invalid": 1, "not_found": 1, "refused": 0, "connect_first": 1,
                           "already_proposed": 0, "already_watching": 0},
                "message": "Resolved 5 lines: 2 ready to approve, 1 could not be fetched, 1 not found or not offered, 1 need an account connected."}

    def __init__(self, setup=False, topics=(), new_kept=0, cards=()):
        self.needs_setup, self.key = setup, not setup
        self.topics = [{"id": i + 1, "name": n} for i, n in enumerate(topics)]
        self.new_kept, self.sources, self.writes = new_kept, [], []
        self.queue = {"items": []}                   # this week's review queue
        self.cards = [dict(c) for c in cards]         # the server's idea cards

    def install(self, page):
        page.route(AFK_PATHS, self.answer)

    def topic(self, t):
        return {**t, "description": "One sentence.", "kind": "user", "ref": None, "status": "active", "created_at": "2026-10-01T00:00:00Z",
                "sources": 0, "proposed": 0, "items_per_day": 0, "kept_per_day": 0, "observations": 0, "themes": 0, "rising": 0,
                "spend_month_usd": 0, "tokens_month": None, "themes_list": [], "rising_now": [], "snapshot": None, "source_rows": [],
                "prefilter": 0.3, "every_hours": 3, "budget_usd": None, "progress": ""}

    def obs(self, k):
        return {"id": 9000 + k, "kind": "mild_signal", "title": None, "summary": f"A finding of note number {k}, long enough to be a sentence.",
                "signal": round(0.6 - k / 100, 2), "source_id": 1, "source_label": "HN", "created_at": "2026-10-16T05:00:00Z", "grade": None, "new": True}

    def today(self):
        busy = [{"id": t["id"], "name": t["name"], "status": "active", "kind": "user", "ref": None, "new_kept": self.new_kept,
                 "top": [self.obs(k) for k in range(3)] if self.new_kept else [], "proposed": 0, "proposed_ticked": [], "proposed_items_per_day": 0}
                for t in self.topics]
        return {"since": "2026-10-15T06:00:00Z", "seen_at": None, "now": "2026-10-16T06:00:00Z", "default_window_hours": 24,
                "topics": busy, "project_topics": [], "new_kept": self.new_kept * len(self.topics), "proposed": 0, "rising": [],
                "messages": [], "sources_failing": [], "ingest": {"last": None, "judge_calls_24h": 0, "judge_errors_24h": 0,
                                                                  "observations": 9000, "sources": 1, "topics": len(self.topics), "paused": None}}

    def answer(self, rt):
        from urllib.parse import parse_qs, urlsplit
        u = urlsplit(rt.request.url)
        path, q, body = u.path, parse_qs(u.query), json.loads(rt.request.post_data or "{}") if rt.request.method == "POST" else None
        if body is not None:
            self.writes.append((path, body))
        t = re.fullmatch(r"/api/topics/(\d+)(/scout)?", path)
        idea = re.fullmatch(r"/api/ideas/(\d+)(/later)?", path)
        if path == "/api/status":
            out = {"budget_usd": 0, "version": "smoke", "host_api": 2, "paused": None, "topics": self.topics, "observations": 9000, "runs": [], "update": None,
                   "sources": [{"id": s["id"], "label": s["label"], "status": "approved"} for s in self.sources], "tokens_today": None,
                   "next_run": {}, "running": None}
        elif path == "/api/setup":
            out = {"needs_setup": self.needs_setup, "done": not self.needs_setup, "budget_usd": None, "every_hours": 3,
                   "key": {"set": self.key, "env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "provider": "openai_compat",
                           "test": {"ok": True, "detail": "The key works", "at": "2026-10-16T05:00:00Z"} if self.key else None},
                   "logins": {"claude": {"ok": True, "detail": "Signed in"}, "gh": {"ok": True, "detail": "Signed in"}}}
        elif path == "/api/setup/provider" and body is not None:
            self.key = True
            out = {"ok": True, "test": {"ok": True, "detail": "The key works"},
                   "models": {"judge": "anthropic/claude-haiku-5.5", "reason": "anthropic/claude-sonnet-5.5"}}
        elif path == "/api/setup/finish":
            self.needs_setup = False
            out = {"ingest": "started"}
        elif path == "/api/topics" and body is not None:
            self.topics.append({"id": len(self.topics) + 1, "name": body["name"]})
            out = {"id": len(self.topics), "proposals": self.PROPOSALS, "message": f"{len(self.PROPOSALS)} proposed.", "invalid": 0}
        elif path == "/api/topics":
            mine = [] if q.get("kind") == ["project"] else [self.topic(x) for x in self.topics]
            out = {"topics": mine, "archived": [], "broad": [], "progress": "", "every_hours": 3, "theme_min_share": 0.5,
                   "all": {"observations": 9000, "sources": len(self.sources), "themes": 0, "items_per_day": 0, "map": None}}
        elif t and t.group(2):
            out = {"proposals": [], "message": "Nothing new."}
        elif t:
            out = self.topic(next((x for x in self.topics if x["id"] == int(t.group(1))), {"id": int(t.group(1)), "name": "?"}))
        elif path == "/api/sources" and body is not None:
            p = next(x for x in self.PROPOSALS if x["id"] == body["id"])
            self.sources.append({"id": p["id"], "label": p["label"], "topic": body.get("topic")})
            out = {"id": p["id"], "status": "approved"}
        elif path == "/api/sources/approve":
            for i in body["ids"]:
                p = next(x for x in self.PROPOSALS + self.DESCRIBED if x["id"] == i)
                self.sources.append({"id": i, "label": p["label"], "topic": body.get("topic")})
            out = {"approved": body["ids"], "skipped": []}
        elif path == "/api/sources/from-text":
            out = {"job": {"key": "fromtext", "state": "done", "started": 0, "finished": 1, "elapsed_s": 12,
                           "result": self.batch(body.get("topic")), "error": None}}
        elif path == "/api/catalog":
            out = {"providers": [], "connected": {}, "prefilter": 0.3,
                   "topics": [{**t, "description": "", "kind": "user", "ref": None, "sources": 0} for t in self.topics]}
        elif path == "/api/sources":
            out = {"sources": [{"id": s["id"], "label": s["label"], "review": "approved", "status": "ok", "items_per_day": 3,
                                "topics": [{"id": s["topic"]}] if s["topic"] else []} for s in self.sources],
                   "topics": [], "reddit": {"watched": 0, "note": ""}, "connections_need_you": 0, "every_hours": 3,
                   "default_retention_days": 90}
        elif path == "/api/today":
            out = self.today()
        elif path == "/api/observations":
            n = int((q.get("limit") or ["20"])[0])
            out = {"total": self.new_kept, "offset": 0, "cluster_label": None, "seen_at": None, "marker": "", "since": None,
                   "new_total": self.new_kept, "results": [self.obs(k) for k in range(min(n, self.new_kept))]}
        elif idea and idea.group(2):
            n = int(idea.group(1))
            for c in self.cards:
                if c["number"] == n:
                    c.update(state="later", later_until="2026-10-23T06:00:00Z")
            out = {"id": n, "state": "later", "later_until": "2026-10-23T06:00:00Z"}
        elif idea:
            out = next((c for c in self.cards if c["number"] == int(idea.group(1))), {})
        elif path == "/api/ideas":
            # the owner's dispatch cards are their own read (?origin=dispatch): none here
            rows = [] if q.get("origin") == ["dispatch"] else self.cards
            out = {"ideas": rows, "count": len(rows), "first": {"words": "", "at": None, "observations": 0, "needed": 30}}
        elif path == "/api/feedback/vocabulary":
            out = {"chips": {}}
        elif path == "/api/feedback":
            out = {"grades": {}}
        elif path == "/api/review/queue":
            out = self.queue
        elif path == "/api/connections":
            out = {"accounts": [], "providers": []}
        elif path.startswith("/api/errors/"):
            # an error's report is not kept here: the page says it could not read it
            rt.fulfill(status=404, content_type="application/json", body=json.dumps({"error": "no such report"}))
            return
        else:
            out = {}
        rt.fulfill(status=200, content_type="application/json", body=json.dumps(out))


CARDS = [bear_card(7, "Clinic schedules on paper"), bear_card(8, "Plumbers lose invoices")]


def _story(browser, afk=None, width=1360, height=900):
    """a page signed in as the owner, the server answered in it; ``sent``: a write that reaches the
    page server (none should)"""
    page = browser.new_page(viewport={"width": width, "height": height})
    errors, sent = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("request", lambda r: sent.append(f"{r.method} {r.url}") if r.method not in ("GET", "HEAD") and not AFK_PATHS.match(r.url) else None)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(status=200, content_type="application/json",
                                                                 body=json.dumps({"origin": "owner", "require_token": True})))
    if afk:
        afk.install(page)
    return page, errors, sent, Clicks(page)


def test_every_route_draws_without_an_error(browser, page_base):
    """... with the server answered in the page, and says nothing the owner should not read: no
    setting key outside its code span or Advanced, no null or undefined, no retired name (QA B7,
    B10, B11; CUT: no Build, Projects, Repos). A read this fake the server does not answer is a 404
    and the page says it could not read it: only a server error counts here."""
    keys = setting_keys()
    afk = PageAfk(topics=["Clinics"], new_kept=3, cards=CARDS)
    page, errors, sent, _ = _story(browser, afk)
    bad = []
    # a failed request is judged by its response (which names it), not by the console's line
    page.on("console", lambda m: errors.append(m.text) if m.type == "error"
            and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 500 else None)
    seen, flagged = [], {}
    for route in routes():
        errors.clear()
        bad.clear()
        sent.clear()
        page.goto(f"{page_base}/#/{route}")
        page.wait_for_load_state("load")
        until(page, "document.body.innerText.trim().length >= 40", 10, must=False)
        page.wait_for_timeout(700)                   # the route's reads come back
        text = page.inner_text("body")
        problems = errors[:3] + bad[:3] + sent[:3]
        if re.search(r"Something went wrong|Traceback", text):
            problems.append("an error on the page")
        if len(text.strip()) < 40:
            problems.append("nearly empty")
        problems += [f"says {w!r}" for w in owner_words(page.evaluate(OWNER_TEXT), keys)]
        if problems:
            flagged[route] = problems
        seen.append(route)
    page.close()
    assert len(seen) >= 30, seen
    assert not flagged, json.dumps(flagged, indent=1)


def test_an_old_address_lands_where_its_page_went(browser, page_base):
    """CUT: a bookmark to a build, a project or Today lands on the home, Ideas
    or Needs you, and a toast says once why ("Builds are not part of Kranto any more.")."""
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Clinics"], cards=CARDS))
    for old, new in (("builds/sidedoor", "#/home"), ("projects/p1/changes", "#/home"), ("today", "#/needs"),
                     ("ideas/new", "#/ideas"), ("settings/building", "#/settings")):
        page.goto(f"{page_base}/#/{old}")
        until(page, f"location.hash.split('?')[0] === {json.dumps(new)}", 10)
    page.goto(f"{page_base}/#/build")
    page.wait_for_selector("#toast >> text=Builds are not part of Kranto any more.")
    page.close()
    assert not errors and not sent, errors + sent


def test_the_built_ui_loads_under_the_csp(browser, page_base):
    """The Vite build is the page: its module loads from this version's address,
    marks the document, draws the frame, and nothing is refused by the page's CSP."""
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error"
            and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400
            and not r.url.endswith(HOST_PROBE) else None)
    page.goto(f"{page_base}/#/needs")
    until(page, "document.documentElement.dataset.ui === 'svelte'", 10)
    assert page.locator("#nav").count() == 1 and page.locator("#rows").count() == 1
    page.close()
    assert not errors, errors


def test_the_shell_answers_the_keys_the_palette_and_the_theme(browser, page_base):
    """the shell, pressed for real: j focuses a card's row and the pane follows; g then n goes to
    News; ⌘K opens the palette with its commands and finds the console; esc closes it; ? opens
    the sheet; ◐ switches the theme. No write is sent."""
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Clinics"], cards=CARDS))
    page.goto(f"{page_base}/#/ideas")
    page.wait_for_selector("#rows li.row a.r-title[href^='#/ideas/']")
    page.keyboard.press("j")
    page.wait_for_selector("#rows .focus")
    until(page, "location.hash.includes('ideas/') || location.hash.includes('sel=')")
    page.keyboard.press("Escape")
    page.keyboard.press("g")
    assert "g then:" in page.inner_text("#key-hint")
    page.keyboard.press("n")
    until(page, "location.hash.startsWith('#/news')")
    page.keyboard.press("Control+k")
    page.wait_for_selector("#pal[open] #pal-q")
    assert page.locator("#pal-list [role=option]").count() > 5
    page.keyboard.type("console")
    page.wait_for_selector("#pal-list [role=option] >> text=Console")
    page.keyboard.press("Escape")
    until(page, "!document.getElementById('pal').open")
    page.keyboard.press("?")
    page.wait_for_selector("#dlg[open] >> text=Keyboard shortcuts")
    page.keyboard.press("Escape")
    dark = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.click("#theme")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") != dark
    page.close()
    assert not errors and not sent, errors + sent


def test_ideas_rows_answer_j_and_k(browser, page_base):
    """Ideas' card rows keep the row contract: j walks onto a card, whose sheet follows with Write a
    post, Pass and Later; k comes back to the first. Nothing is written."""
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Clinics"], cards=CARDS))
    page.goto(f"{page_base}/#/ideas")
    page.wait_for_selector("#rows li.row a.r-title[href^='#/ideas/']")
    page.keyboard.press("j")
    until(page, "location.hash.includes('ideas/') || location.hash.includes('sel=i')")
    title = page.inner_text("#rows li.row.focus a.r-title")
    page.wait_for_selector(f"#dscroll .dh .dt >> text={title}")
    for act in ("write", "pass", "later"):
        assert page.is_visible(f"#dscroll .dh .acts button[data-act={act}]"), act
    page.keyboard.press("j")
    page.wait_for_selector("#rows li.row.focus")
    second = page.inner_text("#rows li.row.focus a.r-title")
    assert second != title
    page.keyboard.press("k")
    page.wait_for_selector(f"#rows li.row.focus a.r-title >> text={title}")
    page.close()
    assert not errors and not sent, errors + sent


def test_the_review_queue_answers_its_keys(browser, page_base):
    """Review moved into components keeps its keys (QUEUE_KEYS): with the server's queue
    answered in the page (its status, the queue, the why chips, the grades' posts), 1 grades the
    current card and selects the next row, a puts a why chip on the card just graded, 0 skips the
    next card (back next week), the pane says Done., k comes back to it. A build an older the server
    still sends is dropped (no grade on builds). The posts are the server's /api/feedback,
    answered here; nothing reaches a server."""
    page = browser.new_page(viewport={"width": 1360, "height": 900})
    errors, posts = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    queue = {"week": "2026-W42", "items": [
        {"target": "idea", "id": 1, "slot": "card", "title": "Clinic schedules on paper", "facts": ["3 cited"]},
        {"target": "idea", "id": 2, "slot": "card", "title": "A clinic's paper calendar", "facts": ["1 cited"]},
        {"target": "build", "id": "plotkeeper", "slot": "build"}]}
    vocab = {"chips": {"idea": [{"key": "novel", "label": "novel", "letter": "a"}], "build": []}}

    def answer(body):
        return lambda rt: rt.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    def feedback(rt):
        posts.append(json.loads(rt.request.post_data or "{}"))
        rt.fulfill(status=200, content_type="application/json", body="{}")
    page.route(re.compile(r"/api/status$"), answer({"budget_usd": 0, "version": "smoke", "paused": False, "topics": []}))
    page.route(re.compile(r"/api/review/queue$"), answer(queue))
    page.route(re.compile(r"/api/feedback/vocabulary$"), answer(vocab))
    page.route(re.compile(r"/api/feedback\?"), answer({"grades": {}}))
    page.route(re.compile(r"/api/feedback$"), feedback)
    page.goto(f"{page_base}/#/review")
    page.wait_for_selector("#rows li.row.sel[data-cur] >> text=Clinic schedules on paper")
    page.wait_for_selector("#dscroll section.qcard .q-what >> text=card · 1 of 2")
    page.keyboard.press("1")
    page.wait_for_selector("#rows li.row.sel[data-cur] >> text=A clinic's paper calendar")
    assert posts[-1]["target"] == "idea" and posts[-1]["value"] == "useful" and posts[-1]["origin"] == "review"
    assert page.inner_text("#rows li.row >> nth=0").strip().endswith("useful")
    page.wait_for_selector("#dscroll .qlast >> text=Just graded card")
    page.keyboard.press("a")
    until(page, "document.querySelector('#dscroll .qlast button.chip[aria-pressed=true]') !== null")
    assert posts[-1]["reasons"] == ["novel"]
    page.keyboard.press("0")
    page.wait_for_selector("#dscroll section.qcard h2 >> text=Done.")
    assert posts[-1]["target"] == "idea" and posts[-1]["value"] == "skip"
    assert not [x for x in posts if x["target"] == "build"]
    assert "2 of 2" in page.inner_text("#rows .progress")
    page.keyboard.press("k")
    page.wait_for_selector("#dscroll section.qcard .q-what >> text=card · 2 of 2")
    page.close()
    assert not errors, errors


def test_a_tip_opens_on_focus_and_click_and_a_missing_page_says_so(browser, page_base):
    """a ? beside a word is the one popover: the focus shows it as a tooltip, its own ?
    key makes it a dialog with its link to the docs, esc closes it. A route the app does not have
    says so, with the way back home."""
    page = browser.new_page(viewport={"width": 1360, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{page_base}/#/review")                # Review's head has the grading tip
    tip = page.locator("button.tip").first
    tip.wait_for()
    tip.focus()
    page.wait_for_selector(".pop.tipbox[role=tooltip]")
    assert tip.get_attribute("aria-expanded") == "true"
    page.keyboard.press("?")
    page.wait_for_selector(".pop.tipbox[role=dialog] a[target=_blank]")
    page.keyboard.press("Escape")
    page.wait_for_selector(".pop.tipbox", state="detached")
    assert tip.get_attribute("aria-expanded") == "false"
    page.goto(f"{page_base}/#/no/such/page")
    page.wait_for_selector("#rows >> text=There is no page at #/no/such/page")
    assert page.title() == "Not found · Kranto"
    page.click("#rows a.btn >> text=Go home")       # never the retired "Go to Today" (QA B11)
    page.wait_for_url(re.compile(r"\#/(home)?$"))
    page.close()
    assert not errors, errors


def test_while_term_is_off_c_says_how_to_turn_it_on(browser, page_base, monkeypatch):
    """c opens Open in Claude Code on a card's sheet; while it is off (term.enabled false,
    or automatic without bubblewrap or a Claude token) c says in one line how to turn it on, the
    panel stays shut and nothing is asked to start."""
    from kranto.page.term import launch
    why = "Open in Claude Code is off: set term.enabled: true in loop.yaml and restart Kranto."
    monkeypatch.setattr(launch, "offered", lambda cfg, environ=None, sandboxed=None: (False, why))
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Clinics"], cards=CARDS))
    page.goto(f"{page_base}/#/ideas/7")
    page.wait_for_selector("#dscroll #idea-write")
    page.wait_for_timeout(500)
    page.keyboard.press("c")
    page.wait_for_selector("text=set term.enabled: true in loop.yaml")
    assert page.is_hidden("#term")
    page.close()
    assert not errors and not sent, errors + sent


# -- the click stories (CLICKS-v4.md), played on the hosted page ------------------------------
# Each story counts what CLICKS-v4.md counts: a click, a key that replaces one, the click that
# focuses a field (none when the page already put the cursor there) and a scroll (a screen of
# the pane the target sits in, or of what the story reads).

def test_s01_first_install_to_first_topic(browser, page_base):
    """S01 (Welcome in three steps): the splash's Set up Kranto, the key pasted (tested on
    paste), Continue, a suggested topic, Scout, the proposals read, Watch these and continue, Start
    reading: on the topic's page, the close matches watched."""
    afk = PageAfk(setup=True)
    page, errors, sent, c = _story(browser, afk)
    page.goto(f"{page_base}/#/")
    page.wait_for_url(re.compile(r"\#/hello$"))
    c.click("#set-up", "Set up Kranto")
    c.click("#way-key-open", "Paste a key")       # step 1's ways in
    c.paste("#model-key", "pasted-" + "x" * 24)
    page.wait_for_selector("#continue:not([aria-disabled])")
    c.click("#continue", "Continue")
    c.click(".chips button.chip >> text=Local-first software", "a suggested topic")
    c.click("#scout", "Find places to read")
    page.wait_for_selector("section.grp.props li.row")
    c.read("section.grp.props li.row", "read the proposals")
    c.click("#watch-continue", "Watch these and continue")
    page.wait_for_url(re.compile(r"\#/welcome/finish$"))
    c.click("#finish", "Start reading")
    # How you write while kranto reads (F-13); skipped, the home's first hour
    page.wait_for_url(re.compile(r"\#/welcome/voice$"))
    c.click("#voice-skip", "Skip for now")
    page.wait_for_url(re.compile(r"\#/home$"))
    assert ("/api/setup/provider", {"provider": "openrouter", "key": "pasted-" + "x" * 24, "replace": False}) in afk.writes
    assert [s["id"] for s in afk.sources] == [31, 32], "the close matches, ticked for you"
    assert not afk.needs_setup
    page.close()
    assert not errors and not sent, errors + sent
    assert c.n <= 12, (c.n, c.log)          # Paste a key and Skip for now are the two added


def test_s02_add_a_topic_and_approve_its_sources(browser, page_base):
    """S02 (8 measured, 6 designed; 6 here): the navigator's + add, the name (the field has the cursor),
    the sentence, Scout, the proposals read, one ticked and one unticked, Watch these and open the
    topic: on its Sources, what was ticked watched."""
    afk = PageAfk(topics=["Lab tools"])
    page, errors, sent, c = _story(browser, afk)
    page.goto(f"{page_base}/#/needs")
    page.wait_for_selector("#nav a.add")
    c.click("#nav a.add", "+ add")
    page.wait_for_selector("#topic-name:focus")
    c.type("#topic-name", "Local-first software", "the name")
    c.type("#topic-desc", "Software that keeps working offline and keeps the user's data on their own devices.", "the sentence")
    c.click("#scout", "Find places to read")
    page.wait_for_selector("section.grp.props li.row")
    c.read("section.grp.props li.row", "read the proposals")
    c.click("section.grp.props li.row:has-text('r/selfhosted') input.ptick", "tick r/selfhosted")
    c.click("section.grp.props li.row:has-text('Ink & Switch') input.ptick", "untick Ink & Switch")
    c.click("button:has-text('Watch these and open the topic')", "Watch these and open the topic")
    page.wait_for_url(re.compile(r"\#/topics/2/sources$"))
    assert sorted(s["id"] for s in afk.sources) == [31, 33]
    page.close()
    assert not errors and not sent, errors + sent
    assert c.n <= 6, (c.n, c.log)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_s07_add_sources_by_describing_them(browser, page_base, theme):
    """ 4.4 (the server #213): Add source from a topic, the list pasted into Describe what
    to add, Resolve, the batch read as one group (ready ones ticked, the failed, not found and
    account ones apart), one unticked, Approve the ticked: on the topic's Sources, what was ticked
    watched, in one request. Four presses and a paste; in both themes, nothing scrolls sideways."""
    afk = PageAfk(topics=["Rust"])
    page, errors, sent, c = _story(browser, afk)
    page.add_init_script(f"localStorage.setItem('kranto.theme', '{theme}')")
    page.goto(f"{page_base}/#/settings/sources/new?topic=1")
    page.wait_for_selector("#d-text")
    assert page.input_value("#d-topic") == "1"
    c.paste("#d-text", "that Rust weekly thing\nFly.io's blog\nJepsen\nmy LinkedIn feed\n@karpathy on X")
    page.locator("#d-text").dispatch_event("input")
    c.click("#resolve", "Resolve")
    page.wait_for_selector("#s-ready li.row")
    assert page.locator(".sec h3").all_inner_texts() == ["Ready to approve2", "Could not be fetched1", "Not found or not offered1",
                                                          "Needs an account1"]
    assert [x.is_checked() for x in page.locator("#s-ready input.ptick").all()] == [True, True]
    c.read("#s-account li.row", "read the batch")
    assert not page.evaluate(LAYOUT)
    c.click("#s-ready li.row:has-text('fly.io') input.ptick", "untick fly.io")
    c.click("#approve-ticked", "Approve the ticked")
    page.wait_for_url(re.compile(r"\#/topics/1/sources$"))
    assert [(p, b) for p, b in afk.writes if p.startswith("/api/sources")] == [
        ("/api/sources/from-text", {"text": "that Rust weekly thing\nFly.io's blog\nJepsen\nmy LinkedIn feed\n@karpathy on X", "topic": 1}),
        ("/api/sources/approve", {"ids": [41], "topic": 1})]
    assert [s["id"] for s in afk.sources] == [41]
    page.close()
    assert not errors and not sent, errors + sent
    assert c.n <= 5, (c.n, c.log)


def test_s04_review_an_idea_and_decide(browser, page_base):
    """S04 (3 here): Needs you's one row for the idea cards waiting opens Ideas;
    a card's title opens it in the pane; Later in its head puts it off (the server's idea.later,
    answered in the page). Nothing reaches the page server."""
    afk = PageAfk(topics=["Clinics"], cards=CARDS)
    page, errors, sent, c = _story(browser, afk)
    page.goto(f"{page_base}/#/needs")
    cards = "li.row[data-sel=cards]"
    page.wait_for_selector(cards)
    c.click(f"{cards} .r-act a", "Open the cards waiting")
    row = "#rows li.row:has(a.r-title[href^='#/ideas/'])"
    page.wait_for_selector(row)
    title = page.inner_text(f"{row} a.r-title")
    c.click(f"{row} a.r-title", "the card's title")
    page.wait_for_selector(f"#dscroll .dh .dt >> text={title}")
    c.click("#dscroll .dh .acts button[data-act=later]", "Later")
    page.wait_for_timeout(300)
    page.close()
    assert not errors and not sent, errors + sent
    assert [p for p, _ in afk.writes if p.endswith("/later")], afk.writes
    assert c.n <= 3, (c.n, c.log)


def test_the_grade_keys_on_evidence_and_no_ticks(browser, page_base):
    """ (the owner's D-3): no tick, no Select, no bulk bar; 1 grades the focused row with one
    post (the server's, answered in the page), ▲ pressed in place; x does nothing."""
    afk = PageAfk(topics=["AI developer tooling"], new_kept=25)
    page, errors, sent, _ = _story(browser, afk)
    page.goto(f"{page_base}/#/topics/1/evidence")
    row = "#rows li.row:has(.grade)"
    page.wait_for_selector(row)
    assert page.query_selector("input.tick") is None and page.query_selector("#bulk") is None
    assert page.query_selector("#select-rows") is None
    page.click(f"{row} >> nth=1")                                   # selects the row (the pane follows)
    page.wait_for_selector("#rows li.row.sel.focus")
    page.keyboard.press("x")
    assert page.query_selector("input.tick") is None
    page.keyboard.press("1")
    page.wait_for_selector("#toast >> text=Graded")
    one = [b for p, b in afk.writes if p == "/api/feedback"]
    assert one and one[0]["value"] == "useful" and one[0]["target"] == "observation"
    assert not [b for p, b in afk.writes if p == "/api/feedback/batch"]
    assert page.get_attribute("#rows li.row.sel .grade", "data-value") == "useful"
    page.close()
    assert not errors and not sent, errors + sent


# -- the layout: every list fills its column (UF) ----------------------------------------------
# Review's queue was drawn as a 760 px block on a blue wash, its week's header a cell beside the
# rows: the group's kind ("queue") also named two old rules. A list group's kind is a bare class,
# so any page-wide rule of the same name lands on it; this is the check that sees it.
LAYOUT = r"""() => {
  const bad = [];
  const shown = e => !!e && e.getClientRects().length > 0;
  const nm = g => g.querySelector('h2')?.id || g.className;
  const rows = document.getElementById('rows');
  if (shown(rows)) {
    // a stage page (the home, a cub's page, Cubs) is one centred column by design: its groups
    // fill that column, not the window
    const col = document.body.classList.contains('stage') && rows.firstElementChild ? rows.firstElementChild : rows;
    const right = col.getBoundingClientRect().left + col.clientLeft + col.clientWidth;
    const pad = parseFloat(getComputedStyle(col).paddingRight) || 0;
    for (const g of rows.querySelectorAll('section.grp')) {
      if (!shown(g)) continue;
      const r = g.getBoundingClientRect(), cs = getComputedStyle(g);
      if (right - r.right > pad + 2) bad.push(`${nm(g)}: ends ${Math.round(right - r.right)} px short of the list's right edge`);
      if (cs.display !== 'block') bad.push(`${nm(g)}: display ${cs.display}`);
      if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)') bad.push(`${nm(g)}: a background of its own (${cs.backgroundColor})`);
      const hd = g.querySelector(':scope > .ghd'), ul = g.querySelector(':scope > ul.lst');
      // a header stuck to the top while its rows scroll under it (a page of several lists opened
      // on a row far down) is not where its group starts: only an unstuck header is measured
      const stuck = hd && hd.getBoundingClientRect().top > r.top + 1;
      // a folded group draws no rows: only a group's shown rows are measured
      if (hd && ul && ul.children.length && !ul.hidden && !stuck && hd.getBoundingClientRect().bottom > ul.getBoundingClientRect().top + 1)
        bad.push(`${nm(g)}: its header is beside its rows, not above them`);
    }
    for (const m of rows.querySelectorAll('li.row.lr .c-main'))
      if (shown(m) && m.getBoundingClientRect().width < 40) { bad.push(`a row's title cell is ${Math.round(m.getBoundingClientRect().width)} px`); break; }
    if (rows.scrollWidth > rows.clientWidth + 1) bad.push(`the list scrolls sideways (${rows.scrollWidth - rows.clientWidth} px)`);
  }
  const d = document.getElementById('dscroll');
  if (shown(d) && d.scrollWidth > d.clientWidth + 1) bad.push(`the pane scrolls sideways (${d.scrollWidth - d.clientWidth} px)`);
  return bad;
}"""


def _week(n=20):
    """a review queue of a busy week: n cards, and a build an older the server still sends, which
    the page drops (no grade on builds)"""
    return {"week": "2026-W42", "items": [
        {"target": "idea", "id": 100 + i, "slot": "card", "topic": "AI developer tooling",
         "title": f"Item {i + 1}: a title long enough to be cut where the row ends, as on live"} for i in range(n)]
        + [{"target": "build", "id": "sidedoor", "slot": "build"}]}


def test_every_list_fills_its_column(browser, page_base):
    """UF (the owner's report, 2026-10-16): on every route, at 1280 and 1920 px, light and dark,
    the navigator open and as icons, each list group is as wide as the list column, its header
    above its rows, with no background of its own; no list or pane scrolls sideways; no row's
    title is squeezed under 40 px. Review is drawn from a week of 20 items, at 1280, 1530 and 1920
    in both themes, and its keys still answer: j and k move the current row, ▲ grades it and moves
    on, enter opens the current item's page."""
    afk = PageAfk(topics=["AI developer tooling", "Local-first software"], new_kept=25, cards=CARDS)
    afk.queue = _week()
    every = routes() + ["topics/1", "topics/1/evidence", "ideas/7"]
    flagged = {}

    def visit(width, theme, nav, which):
        ctx = browser.new_context(viewport={"width": width, "height": 890})
        layout = json.dumps({"icons": True} if nav == "icons" else {})
        ctx.add_init_script(f"localStorage.setItem('kranto.theme', '{theme}'); localStorage.setItem('kranto.layout', {json.dumps(layout)})")
        page = ctx.new_page()
        afk.install(page)
        page.goto(f"{page_base}/#/needs")
        until(page, "document.documentElement.dataset.ui === 'svelte'", 10)
        for route in which:
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            page.wait_for_timeout(450)
            if route == "review":
                page.wait_for_selector("#rows section.grp.queue li.row >> nth=19")
            bad = page.evaluate(LAYOUT)
            if bad:
                flagged[f"{width} {theme} {nav} #/{route}"] = bad
        return ctx, page

    for width, theme, nav in [(1280, "dark", "open"), (1920, "light", "icons")]:
        visit(width, theme, nav, every)[0].close()
    for width in (1280, 1530, 1920):
        for theme in ("dark", "light"):
            ctx, page = visit(width, theme, "open", ["review"])
            if width == 1530 and theme == "dark":
                cur = "#rows li.row[data-cur] .r-title"
                assert page.inner_text(cur).startswith("Item 1:")
                page.keyboard.press("j")
                page.keyboard.press("j")
                page.wait_for_selector(f"{cur} >> text=Item 3:")
                page.keyboard.press("k")
                page.wait_for_selector(f"{cur} >> text=Item 2:")
                page.click("#rows li.row[data-cur] .grade button >> nth=0")
                page.wait_for_selector(f"{cur} >> text=Item 3:")
                assert [b["value"] for p, b in afk.writes if p == "/api/feedback"] == ["useful"]
                assert page.inner_text("#rows li.row >> nth=1").strip().endswith("useful")
                page.click("#rows li.row >> nth=19")                          # the last card: its page
                page.wait_for_selector("#rows li.row[data-cur] >> nth=0")
                page.wait_for_selector("#dscroll section.qcard .q-what >> text=card · 20 of 20")
                assert "sidedoor" not in page.inner_text("#rows")              # the build is dropped
            ctx.close()
    assert not flagged, json.dumps(flagged, indent=1)


def test_a_lists_scroll_survives_a_reload(browser, page_base):
    """QA B19: the list scrolls inside #rows, not the document, so a reload put it back at the
    top (the sheet, the filter and the selection stayed). Its place comes back with the rows."""
    page = browser.new_page(viewport={"width": 1360, "height": 320})
    page.goto(f"{page_base}/#/settings")
    until(page, "document.querySelectorAll('#rows li.row').length > 8", 15)
    top = page.evaluate("() => { const r = document.getElementById('rows'); r.scrollTop = r.scrollHeight; return r.scrollTop; }")
    assert top > 100, top
    page.wait_for_timeout(500)                       # the scroll settles
    page.reload()
    until(page, "document.querySelectorAll('#rows li.row').length > 8", 15)
    until(page, f"Math.abs(document.getElementById('rows').scrollTop - {top}) <= 2", 5)
    page.close()


PHONE_TARGETS = """() => {
  const small = [...document.querySelectorAll("#rows .row .btn, #rows .r-act .btn, .acts .btn, #top .btn, #top .menu, .wl .lh .btn, .wl .tb .btn, .area-top .btn, .ghb .btn")]
    .filter((b) => b.offsetParent !== null).map((b) => [b.textContent.trim(), Math.round(b.getBoundingClientRect().height)])
    .filter(([, h]) => h < 44);
  const cut = [...document.querySelectorAll(".wl .lh .ph .small")].filter((e) => getComputedStyle(e).whiteSpace === "nowrap").length;
  return { small: small.slice(0, 5), cut, verbs: document.querySelectorAll("#rows .row .btn, #rows .r-act .btn").length };
}"""


def test_on_the_phone_every_verb_is_a_thumb_target_and_no_lede_is_cut(browser, page_base):
    """QA B24: at 390 px a row's verb was 22 px tall and a page's lede was cut with an
    ellipsis. Every visible row verb and sheet action is at least 44 px tall, and the lede wraps."""
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Clinics"], cards=CARDS), 390, 844)
    seen, flagged = 0, {}
    # the top bar's Pause and ◐ and a page head's verbs too (they were 34 px); Needs
    # you has Mark all seen in its head, and the cards' row its Open
    for route in ("needs", "ideas", "settings"):
        page.goto(f"{page_base}/#/{route}")
        until(page, "document.documentElement.dataset.ui === 'svelte'", 10)
        page.wait_for_timeout(700)
        got = page.evaluate(PHONE_TARGETS)
        seen += got["verbs"]
        if got["small"] or got["cut"]:
            flagged[route] = got
    page.close()
    assert seen, "no row verb on any page: the test measured nothing"
    assert not flagged, json.dumps(flagged, indent=1)


def test_the_topic_edit_sheet_says_no_key_null_or_retired_name(browser, page_base):
    """QA's words guard (B7, B10, B11) over a sheet no route walk opens: a topic's Edit sheet
    (from its page). It says what it must, and nothing the owner should not read."""
    keys = setting_keys()
    page, errors, sent, _ = _story(browser, PageAfk(topics=["Lab tools"]))
    page.goto(f"{page_base}/#/topics/1")
    page.wait_for_selector("#topic-edit")
    page.click("#topic-edit")
    page.wait_for_selector("#dlg[open] #te-desc")
    text = page.evaluate("document.getElementById('dlg').innerText")
    assert "Every item is compared with them before any model call" in text
    assert "Add a source from your library" in text and "Archive" in text
    assert owner_words(text, keys) == [], text
    page.close()
    assert not errors, errors
