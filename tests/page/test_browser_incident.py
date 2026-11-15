"""A refused model key, in a real browser: live's OpenRouter key expired on 25 Oct and
for two days the home put a held build above the failure, the console squeezed or covered Needs
you, and the top bar said "Quiet". Here the incident is the first thing on the home and on Needs
you, seen without scrolling and not under the console (docked, open, as live has it), at 1400 px
and on a 390 px phone (one layout since open-source wave 1); the top bar says it in red. One problem,
one card (the owner on 2026-10-29): the band says it, and no row of Needs you says it again. the server and
the activity read are answered in the page (test_browser_buttons' HostAfk); nothing is written.
Needs the built UI (CI's browser job)."""
import json
import re

from .test_browser_activity import read as activity_read
from .test_browser_buttons import HostAfk
from .test_browser_console import STATE as CONSOLE
from .test_browser_smoke import (  # noqa: F401 - fixtures
    BUILT,
    browser,
    page_base,
    pytestmark,
    until,
)

INCIDENT = {"id": "auth:openrouter", "provider": "openrouter", "name": "OpenRouter", "cause": "expired",
            "blocking": True, "title": "Your OpenRouter key is refused (expired)",
            "words": "Your OpenRouter key was refused (expired) at 08:15 on 25 Oct: reading your sources and "
                     "idea cards stop until it is renewed in Settings › Watching.",
            "since": "2026-10-25T08:15:00Z", "last": "2026-10-27T17:00:00Z", "tries": 22,
            "kinds": [{"kind": "ingest", "title": "Reading your sources", "noun": "reading your sources",
                       "since": "2026-10-25T08:15:00Z", "tries": 20},
                      {"kind": "ideas", "title": "Writing idea cards", "noun": "idea cards",
                       "since": "2026-10-25T09:00:00Z", "tries": 2}],
            "error": "HTTP 401 from the provider: API key expired.", "verb": "Renew the key",
            "href": "#/settings/watching?sel=ekey", "trace": "#/afk/i1/trace"}
FRAMES = [("new", 1400), ("new", 390)]  # one layout since open-source wave 1
# the band is in the first screen and the element at its middle is the band's own (no console,
# sheet or bar over it)
SEEN = r"""(sel) => {
  const b = document.querySelector(sel);
  if (!b) return 'not there: ' + sel;
  const r = b.getBoundingClientRect();
  if (r.top < 0 || r.bottom > innerHeight || r.width < 200) return `out of the first screen: ${JSON.stringify(r)}`;
  const at = document.elementFromPoint(r.left + Math.min(r.width / 2, 120), r.top + r.height / 2);
  return at && b.contains(at) ? 'seen' : `covered by ${at ? at.id || at.className : 'nothing'}`;
}"""


def test_a_refused_key_is_seen_first_with_the_console_open_in_every_layout(browser, page_base):
    for layout, width in FRAMES:
        ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 500 else 844},
                                  has_touch=width < 500, is_mobile=width < 500)
        page = ctx.new_page()
        afk = HostAfk(layout, topics=["Farming"], new_kept=3)
        afk.install(page)
        sent = []
        page.on("request", lambda r: sent.append(f"{r.method} {r.url}")
                if r.method not in ("GET", "HEAD") and "/api/term/console/open" not in r.url else None)
        page.route(re.compile(r"/api/activity(\?.*)?$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(activity_read(incidents=[INCIDENT], running=[]))))
        page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps({"origin": "owner", "require_token": True})))
        page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
            status=200, content_type="application/json", body=json.dumps(CONSOLE)))
        page.route(re.compile(r"/api/term/console/open$"), lambda rt: rt.fulfill(
            status=500, content_type="application/json", body=json.dumps({"error": "not in this test"})))
        for route in ("", "needs"):
            where = f"{layout} {width} #/{route}"
            page.goto(f"{page_base}/#/{route}")
            until(page, "document.documentElement.dataset.ui === 'svelte'", 15)
            until(page, "!!document.querySelector('#console')", 15)          # the console is there
            until(page, "!!document.querySelector('#incident-band')", 15)
            page.wait_for_timeout(400)
            titles = page.locator("#home-needs li .r-title, section.grp.needs li .r-title").all_inner_texts()
            # the band, seen in the first screen, never under the console
            assert page.evaluate(SEEN, "#incident-band .inc") == "seen", (where, page.evaluate(SEEN, "#incident-band .inc"))
            assert page.locator("#incident-band a").first.get_attribute("href") == "#/settings/watching?sel=ekey"
            # no ✕: never a control that does nothing
            assert "✕" not in page.inner_text("#incident-band"), where
            # and the incident is no row of Needs you as well (the home's, or the page's Fix group)
            assert INCIDENT["title"] not in titles, (where, titles)
            assert titles.count(INCIDENT["title"]) <= 1, (where, titles)
            # the top bar: red, the key named, whatever was opened
            assert page.locator("#hd-activity[data-state=failed]").count() == 1, where
            assert "OpenRouter key refused" in page.inner_text("#hd-activity"), where
        ctx.close()
        assert not sent, sent
    assert BUILT
