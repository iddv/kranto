"""The attention budget on every page (the owner,
2026-10-29: "We're giving the user WAAAY too much shit"). Every route of lib/nodes.json and the
pages the owner named, in New and in Classic, at 1400 × 900 and on a 390 × 844 phone, counted by
tests/page/budget.js (rows of one line, one primary, seven decisions before scrolling, nothing
internal, every fact once, a number only where it is acted on, a short first screen, no template
chrome, plain words), and Needs you and the home on a full day (a refused key's band, a prepared
item, idea cards waiting, the week's review queue, a cub's ask).

A finding fails unless tests/page/budget_allow.json allows it: an entry names the check, where (routes
starting "#/", or selectors), optionally a pattern the finding's text must match, and always why.
An entry without a why fails. Each used entry is printed with its why. A page brought into budget
by a later PR takes its entries out.

Needs the built UI and Playwright (CI's browser job)."""
import json
import re

import pytest

from . import budget as B
from .test_browser_activity import read as activity_read
from .test_browser_buttons import NAMED, HostAfk
from .test_browser_smoke import CARDS, browser, page_base, routes, until  # noqa: F401 - fixtures
from .test_nyu_words import WORD as NYU_WORD

pytestmark = [pytest.mark.browser, pytest.mark.built_ui]
ALLOW = B.ALLOW
FRAMES = [("new", 1400), ("new", 390)]  # one layout since open-source wave 1
NOW = 1793300000


def _count(page, route: str, phone: bool, used=None) -> list[str]:
    return B.count(page, route, phone)


def _report(used=None) -> None:
    for line in B.report():
        print(line)


def test_the_banned_words_are_nyus_and_sends_and_the_designs():
    """one list of words the owner never reads: the "press", SEND's "ticket" and "dry", and the
    design's R10 (tests/page/budget.js's BANNED; the own test reads the code's strings)"""
    banned = re.search(r"const BANNED = /(.*)/gi;", B.JS).group(1)
    rx = re.compile(banned, re.I)
    for w in ("press", "pressed", "ticket", "tickets", "dry", "readback", "typed fields", "ladder", "verb", "kind",
              "manifest", "schema", "uuid", "daemon", "pid", "cub ·"):
        assert rx.search(w), w
    assert NYU_WORD.search("press") and rx.search("press")
    assert not rx.search("kindly") and not rx.search("dryer") and not rx.search("impressive")


def test_every_entry_of_the_allowlist_says_why():
    assert ALLOW, "the allowlist is a list"
    for i, a in enumerate(ALLOW):
        assert a.get("check") and isinstance(a.get("why"), str) and len(a["why"].split()) >= 4, (i, a)
        if a.get("pattern"):
            re.compile(a["pattern"])


def _open(browser, layout: str, width: int, afk=None):  # noqa: F811 - the fixture
    ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 500 else 844},
                              has_touch=width < 500, is_mobile=width < 500)
    page = ctx.new_page()
    (afk or HostAfk(layout, topics=["Farming", "Local-first software"], new_kept=3)).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(status=200, content_type="application/json",
                                                                 body=json.dumps({"origin": "owner", "require_token": True})))
    return ctx, page


def _frame(page, page_base, layout):  # noqa: F811 - the fixture
    page.goto(f"{page_base}/#/needs")
    until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
    until(page, "document.body.classList.contains('doors') && !document.body.classList.contains('classic')", 15)


def test_every_page_keeps_the_budget_in_both_layouts_and_on_a_phone(browser, page_base):  # noqa: F811
    every = [r for r in routes() if r not in ("welcome",)] + NAMED
    flagged: dict[str, list[str]] = {}
    used: dict[int, int] = {}
    for layout, width in FRAMES:
        ctx, page = _open(browser, layout, width)
        _frame(page, page_base, layout)
        for route in every:
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            page.wait_for_timeout(450)
            bad = _count(page, route, width < 500, used)
            if bad:
                flagged[f"{layout} {width} #/{route}"] = bad
        ctx.close()
    _report(used)
    assert not flagged, json.dumps(flagged, indent=1, ensure_ascii=False)


# a full day on Needs you and the home: Kranto's own trouble (the band), a prepared item, idea cards
# waiting, a week's review queue, a cub's ask: a real install on 29 Oct had 35 primaries on Needs you (most of
# them builds, which left with the factory)
QUEUE = {"week": "2026-W44", "items": [{"target": "idea", "id": 40 + i, "slot": "card", "title": f"Card {i}"} for i in range(4)]}
PREPARED = {"uuid": "f1", "verb": "b.factory_issue", "title": "File a Kranto issue", "by_words": "by Claude Code", "page": "#/needs", "words": None,
            "fields": {"issue": "The Send dialog asks about an expired draft", "text": "## What happened\nIt asked.", "labels": ["feature"], "area": "ui"},
            "state": "open", "button": "File issue", "created_at": "2026-10-29T18:54:00Z", "says": "A new issue on iddv/kranto."}
INCIDENT = {"id": "auth:openrouter", "provider": "openrouter", "name": "OpenRouter", "cause": "expired", "band": True, "tries": 1, "dismiss": False,
            "title": "Your OpenRouter key is refused", "words": "Reading and idea cards stopped at 19:02.", "verb": "Renew the key",
            "href": "#/settings/watching?sel=ekey", "since": "2026-10-29T19:02:00Z", "kinds": [{"kind": "ingest", "since": "2026-10-29T19:02:00Z"}]}


def _iso(at: int) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


# the home's one read on a full day (the server core.home.today): today's brief and five new cards
HOME = {"date": _iso(NOW)[:10], "now": _iso(NOW), "sentence": "Today's brief is ready, and one prepared item waits for you.",
        "waiting": {"drafts": 0, "prepared": 1},
        "briefs": {"topics": [{"topic": {"id": 1, "name": "Farming"}, "brief": 4, "at": _iso(NOW - 3600 * 5), "more": 3,
                               "items": [{"n": n, "title": t, "source": s} for n, (t, s) in enumerate([
                                   ("Seed prices fall for the first time in four years", "agweb.com"),
                                   ("A co-op shares its harvest robots across six farms", "farmprogress.com"),
                                   ("Drought insurance claims double in the plains", "reuters.com")])]}], "more": 0},
        "ideas": {"rows": [{"id": 40 + i, "title": t, "at": _iso(NOW - 3600 * (10 + 20 * i)), "grade": None} for i, t in enumerate([
            "A shared calendar for harvest robots across a co-op", "Seed price alerts for small farms",
            "Drought claims checker for plains farmers", "A field log that fills itself from photos",
            "Weekly co-op digest from the members' own notes"])], "new": 2, "since": _iso(NOW - 86400 * 2), "total": 44},
        "quiet": {"topics": 1, "sources": 12, "read_at": _iso(NOW - 7200), "next": None},
        "visit": {"at": _iso(NOW - 86400), "previous": None}, "away_days": 3, "away": None,
        "slots": {}, "budget_s": 2}


class FullDay(HostAfk):
    """HostAfk, with the prepared item, the refused key's band and the home (the server's reads)"""

    def install(self, page):
        super().install(page)
        page.route(re.compile(r"/api/home(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(HOME)))
        page.route(re.compile(r"/api/home/visit$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(HOME["visit"])))
        page.route(re.compile(r"/api/prepared(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"prepared": [PREPARED]})))
        page.route(re.compile(r"/api/activity(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(activity_read(incidents=[INCIDENT]))))


def test_needs_you_and_the_home_keep_the_budget_on_a_full_day(browser, page_base):  # noqa: F811
    """The design's acceptance for PR 1: one primary on Needs you's first screen (the one thing's;
    the band's verb is Kranto's own), every row one line, at most seven decisions before scrolling."""
    flagged: dict[str, list[str]] = {}
    used: dict[int, int] = {}
    for layout, width in FRAMES:
        afk = FullDay(layout, topics=["Farming"], new_kept=3, cards=CARDS)
        afk.queue = QUEUE
        ctx, page = _open(browser, layout, width, afk)
        _frame(page, page_base, layout)
        for route in ("needs", "home"):
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            until(page, "document.querySelectorAll('li.row').length >= 2", 15)
            page.wait_for_timeout(500)
            where = f"{layout} {width} #/{route}"
            # the one thing is drawn, the band above it, and the rows are the day's
            assert page.locator("#next").count() == 1, where
            assert page.locator("#incident-band").count() == 1, where
            # one primary besides the band's (Kranto's own trouble has its own verb,)
            prim = page.evaluate("[...document.querySelectorAll('.btn.primary')].filter((b) => b.getClientRects().length"
                                 " && b.getBoundingClientRect().top < innerHeight && !b.closest('#incident-band')).length")
            assert prim == 1, (where, prim)
            heights = page.evaluate("[...document.querySelectorAll('li.row')].filter((r) => r.getClientRects().length).map((r) => r.getBoundingClientRect().height)")
            assert heights and max(heights) <= (60 if width < 500 else 36), (where, heights)
            bad = _count(page, route, width < 500, used)
            if bad:
                flagged[where] = bad
            if route == "needs" and layout == "new":
                # the prepared item's dialog is a decision dialog (R2: at most 60 words above its
                # action, 3 facts, one verb beside Cancel), and its Details opens the record
                page.locator("#next [data-prepared-act]").first.click()
                until(page, "!!document.querySelector('#dlg #dlg-details')", 10)
                bad = _count(page, route, width < 500, used)
                if bad:
                    flagged[where + " (the prepared dialog)"] = bad
                page.click("#dlg-details")
                until(page, "!!document.querySelector('#details')", 10)
                assert page.locator("#details .tools code").count() + page.locator("#details .muted").count() >= 1, where
                page.keyboard.press("Escape")
                until(page, "!document.querySelector('#details')", 5)
                page.keyboard.press("Escape")
        ctx.close()
    _report(used)
    assert not flagged, json.dumps(flagged, indent=1, ensure_ascii=False)
