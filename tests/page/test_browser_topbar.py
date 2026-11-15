"""No two of the top bar's controls overlap, with the console open, on its rail or minimized
(the owner, 07:35 on 28 Oct). On live 0.6.0.dev14 at 1400 px the minimized
"✦ Claude Code" chip was fixed at the bar's right edge, over Feedback, the gear and the theme
toggle, in both layouts and both themes: measured here as every visible control's box in
``#top`` against every other's, at 1400 × 900 and 390 × 844, New and Classic, light and dark.
The server is answered in the page (test_browser_buttons' HostAfk). Needs the built UI (CI's
browser job)."""
import json
import re

import pytest

from .test_browser_buttons import HostAfk
from .test_browser_console import STATE as CONSOLE
from .test_browser_smoke import (  # noqa: F401 - fixtures
    browser,
    page_base,
    pytestmark,
    until,
)

# the top bar's controls that draw, with their boxes; a control inside another is one control
BOXES = r"""() => {
  const els = [...document.querySelectorAll('#top a, #top button, #top [role=status] > .lanes')]
    .filter((e) => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const top = els.filter((e) => !els.some((o) => o !== e && o.contains(e)));
  return top.map((e) => { const r = e.getBoundingClientRect();
    return { id: e.id || e.className || e.tagName, x: r.x, y: r.y, w: r.width, h: r.height }; })
    .filter((b) => b.w > 0 && b.h > 0);
}"""
# the minimized chip wherever it is drawn, against the bar's controls
CHIP = "(() => { const r = document.querySelector('#console-min')?.getBoundingClientRect(); " \
       "return r ? {x: r.x, y: r.y, w: r.width, h: r.height} : null; })()"


def overlaps(boxes):
    out = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a["x"] < b["x"] + b["w"] - 0.5 and b["x"] < a["x"] + a["w"] - 0.5 and \
                    a["y"] < b["y"] + b["h"] - 0.5 and b["y"] < a["y"] + a["h"] - 0.5:
                out.append((a["id"], b["id"]))
    return out


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(1400, 900), (390, 844)])
def test_no_two_top_bar_controls_overlap_with_the_console_in_any_place(browser, page_base,
                                                                       scheme, width, height,
                                                                       layout="new"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    page = ctx.new_page()
    HostAfk(layout, topics=["Farming"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"origin": "owner", "require_token": True})))
    page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(CONSOLE)))
    page.route(re.compile(r"/api/term/console/(open|here)$"), lambda rt: rt.fulfill(
        status=500, content_type="application/json", body=json.dumps({"error": "not here"})))
    seen = []
    for place in ("open", "rail", "min"):
        page.goto(f"{page_base}/#/home")
        page.evaluate(f"localStorage.setItem('kranto.console', '{place}')")
        page.reload()
        until(page, "!!document.querySelector('#top #theme')", 15)
        if place == "min":
            until(page, "!!document.querySelector('#console-min')", 15)
        page.wait_for_timeout(300)
        boxes = page.evaluate(BOXES)
        assert overlaps(boxes) == [], (layout, scheme, width, place, boxes)
        if place == "min" and width < 760:
            # a phone: the minimized console is ✦ in the bar of doors at the
            # foot, not a chip in the top bar (it is not drawn twice)
            assert "console-min" not in [b["id"] for b in boxes]
            assert page.is_visible("#tab-console")
            page.click("#tab-console")
            until(page, "!document.querySelector('#console').hidden", 10)
        elif place == "min":
            chip = page.evaluate(CHIP)
            assert chip is not None
            # inside the bar, not fixed over anything below it either
            bar = page.evaluate("document.querySelector('#top').getBoundingClientRect().bottom")
            assert chip["y"] + chip["h"] <= bar + 0.5, (chip, bar)
            assert "console-min" in [b["id"] for b in boxes]
            page.click("#console-min")
            until(page, "!document.querySelector('#console').hidden", 10)
        seen.append(place)
    assert seen == ["open", "rail", "min"]
    ctx.close()
