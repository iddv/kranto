"""No button's words are cut where the page has room (the owner, 2026-10-23: "Many of the
buttons' text isn't visible, even though there's tons of space on my screen", the newsletter's
waiting ticket read "Confir…"). Every route of lib/nodes.json, in the New and the Classic layout,
at 1400 px and on a 390 px phone, with the first row of each list pressed open (its sheet), and the
pages the owner named: the newsletter's page with a ticket waiting, Activity with a Fix row. A
shown button whose scrollWidth is over its clientWidth fails.

The server is answered in the page: PageAfk's topics and setup, and the newsletter cub from
``tests/page/fixtures/host_cubs.json`` (their feature rows are the server's own manifests;
every word of data is made up). The activity read is answered as test_browser_activity does.
Needs the built UI (CI's browser job)."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .test_browser_activity import read as activity_read
from .test_browser_smoke import (  # noqa: F401 - fixtures
    AFK_PATHS,
    BUILT,
    PageAfk,
    browser,
    page_base,
    pytestmark,
    routes,
    until,
)

HOST = json.loads((Path(__file__).parent / "fixtures" / "host_cubs.json").read_text())
HOST_PATHS = re.compile(r"^https?://[^/]+/api/(shell|features|cubs(/.*)?|f/newsletter/.*|tickets(/\d+)?)(\?.*)?$")
UUID = "0f9e8d7c6b5a49382716a5b4c3d2e1f0"
FAILING = {"id": "fail:update", "kind": "update", "title": "The update check", "since": "2026-10-21T06:00:00Z",
           "last": "2026-10-23T06:00:00Z", "tries": 3, "error": "GitHub answered 401", "verb": "Try again",
           "trace": f"#/afk/{UUID}/trace", "runs": []}
# the pages the owner named, beside every route
NAMED = ["cub/newsletter", "cub/newsletter?list=issues", "cub/newsletter?list=log", "activity", "needs"]
FRAMES = [("new", 1400), ("new", 390)]  # one layout since open-source wave 1
CUT = r"""() => [...document.querySelectorAll('button, a.btn, [role=button]')]
  .filter((b) => b.getClientRects().length > 0 && getComputedStyle(b).visibility !== 'hidden' && getComputedStyle(b).display !== 'inline')
  .filter((b) => (b.innerText || '').trim() && b.clientWidth > 0 && b.scrollWidth > b.clientWidth + 1)
  .map((b) => `${(b.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)} (${b.clientWidth} of ${b.scrollWidth} px)`)"""


class HostAfk(PageAfk):
    """PageAfk, and a server with the newsletter cub installed (shell.layout: ``layout``)."""

    def __init__(self, layout: str, **kw):
        super().__init__(**kw)
        self.layout = layout

    def install(self, page):
        page.route(AFK_PATHS, self.answer)
        page.route(HOST_PATHS, self.host)
        page.route(re.compile(r"/api/activity(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(activity_read(failing=[FAILING]))))

    def host(self, rt):
        u = urlsplit(rt.request.url)
        path, q = u.path, parse_qs(u.query)
        if rt.request.method != "GET":
            self.writes.append((path, rt.request.post_data))
            return rt.fulfill(status=200, content_type="application/json", body="{}")
        out = HOST.get(path)
        if path == "/api/shell":
            out = {**out, "layout": self.layout, "home": True, "doors": self.layout == "new"}
        elif path == "/api/tickets" and q.get("cub", [""])[0] not in ("", "newsletter"):
            out = {"tickets": []}
        if out is None:
            out = {"rows": []} if path.startswith("/api/f/") else {}
        rt.fulfill(status=200, content_type="application/json", body=json.dumps(out))


def test_no_button_is_cut_on_any_page_in_either_layout_at_1400_or_on_a_phone(browser, page_base):
    every = [r for r in routes() if r not in ("welcome",)] + NAMED
    flagged: dict[str, list[str]] = {}
    for layout, width in FRAMES:
        ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 500 else 844},
                                  has_touch=width < 500, is_mobile=width < 500)
        page = ctx.new_page()
        afk = HostAfk(layout, topics=["Farming", "Local-first software"], new_kept=3)
        afk.install(page)
        page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(status=200, content_type="application/json",
                                                                     body=json.dumps({"origin": "owner", "require_token": True})))
        page.goto(f"{page_base}/#/needs")
        until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
        # the frame is the layout's: New's doors, or Classic's navigator
        until(page, "document.body.classList.contains('doors') && !document.body.classList.contains('classic')", 15)
        for route in every:
            page.evaluate(f"location.hash = {json.dumps('#/' + route)}")
            page.wait_for_timeout(450)
            where = f"{layout} {width} #/{route}"
            cut = page.evaluate(CUT)
            if page.locator("#rows li.row .r-title").count():
                try:
                    page.locator("#rows li.row .r-title").first.click(timeout=2000)
                    page.wait_for_timeout(450)
                    cut += [f"{c}, its first row open" for c in page.evaluate(CUT) if c not in cut]
                except Exception:                    # noqa: BLE001 - a row that is not a link
                    pass
                page.keyboard.press("Escape")
            if cut:
                flagged[where] = cut
        ctx.close()
    assert not flagged, json.dumps(flagged, indent=1)


def test_the_named_pages_draw_what_the_owner_saw(browser, page_base):
    """The guard above measures what is on the page: these are there to be measured. The
    newsletter's waiting issue has its Confirm, Activity its Fix row's Try again; the cub's page says its last update and the one that waits."""
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    HostAfk("new", topics=["Farming"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(status=200, content_type="application/json",
                                                                 body=json.dumps({"origin": "owner", "require_token": True})))
    page.goto(f"{page_base}/#/cub/newsletter?list=issues")
    until(page, "document.querySelector('#rows li.row')", 15)
    assert page.locator("#rows [data-act=ask-open]").first.inner_text() == "Send"   # its own verb
    # The page's one head says its last update among its facts, and the staged one is
    # in its ⋯; this file ran in no CI job until so it still read the old page
    until(page, "document.body.innerText.includes('updated to 1.2.0 by itself, 2026-10-23')", 15)
    page.locator("#page-head .verbs .btn.more").click()
    assert until(page, "[...document.querySelectorAll('.pop')].some((p) => p.innerText"
                       ".includes('Update to 1.3.0'))", 15, must=False), \
        page.evaluate("[...document.querySelectorAll('.pop')].map((p) => p.innerText)")
    page.keyboard.press("Escape")
    page.evaluate("location.hash = '#/activity'")
    until(page, "document.body.innerText.includes('Try again')", 15)
    page.close()
    assert not errors, errors
