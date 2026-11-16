"""The docked console's width (the owner, 07:38 on 28 Oct: resize, remembered,
double-click, keyboard): a handle on its left edge drags it between 320 px and 60% of the
window, this browser keeps it across a reload, a double-click resets it to 380, the arrow keys
step it (one layout since open-source wave 1). The server is answered in the page. Needs the
built UI (CI's browser job)."""
import json
import re

from .test_browser_buttons import HostAfk
from .test_browser_console import STATE as CONSOLE
from .test_browser_smoke import (  # noqa: F401 - fixtures
    browser,
    page_base,
    pytestmark,
    until,
)

WIDTH = "document.querySelector('#console').getBoundingClientRect().width"


def opened(browser, layout: str, width: int = 1400):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    HostAfk(layout, topics=["Farming"]).install(page)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"origin": "owner", "require_token": True})))
    page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(CONSOLE)))
    page.route(re.compile(r"/api/term/console/(open|here)$"), lambda rt: rt.fulfill(
        status=500, content_type="application/json", body=json.dumps({"error": "not here"})))
    return ctx, page


def drag_to(page, x: float) -> None:
    box = page.locator("#console-grip").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(x, box["y"] + 200, steps=8)
    page.mouse.up()


def test_the_console_is_dragged_kept_reset_and_stepped(browser, page_base, layout="new"):
    ctx, page = opened(browser, layout)
    page.goto(f"{page_base}/#/home")
    page.evaluate("localStorage.setItem('kranto.console', 'open')")
    page.reload()
    until(page, "!!document.querySelector('#console-grip')", 15)
    page.wait_for_timeout(300)
    assert abs(page.evaluate(WIDTH) - 380) <= 1
    # dragged wider: the panel follows, the page's margin with it
    drag_to(page, 1400 - 520)
    wide = page.evaluate(WIDTH)
    assert 500 <= wide <= 540, wide
    assert abs(page.evaluate("parseFloat(getComputedStyle(document.querySelector('#app'))"
                             ".marginRight)") - wide) <= 1
    # kept across a reload, in this browser
    page.reload()
    until(page, "!!document.querySelector('#console-grip')", 15)
    page.wait_for_timeout(300)
    assert abs(page.evaluate(WIDTH) - wide) <= 1
    # never narrower than 320 nor wider than 60% of the window
    drag_to(page, 1400 - 100)
    assert abs(page.evaluate(WIDTH) - 320) <= 1
    drag_to(page, 50)
    most = page.evaluate(WIDTH)
    assert most <= 1400 * 0.6 + 1
    # double-click resets to 380 and forgets the kept width
    page.dblclick("#console-grip")
    page.wait_for_timeout(100)
    assert abs(page.evaluate(WIDTH) - 380) <= 1
    assert page.evaluate("localStorage.getItem('kranto.console.width')") is None
    # the keyboard: ← widens by 16 (shift: 64), → narrows, Enter resets
    page.focus("#console-grip")
    page.keyboard.press("ArrowLeft")
    assert abs(page.evaluate(WIDTH) - 396) <= 1
    page.keyboard.press("Shift+ArrowRight")
    assert abs(page.evaluate(WIDTH) - 332) <= 1
    assert page.get_attribute("#console-grip", "aria-valuenow") == "332"
    page.keyboard.press("Enter")
    assert abs(page.evaluate(WIDTH) - 380) <= 1
    ctx.close()


def test_a_phone_has_no_handle(browser, page_base):
    ctx, page = opened(browser, "new", width=390)
    page.goto(f"{page_base}/#/home")
    page.evaluate("localStorage.setItem('kranto.console', 'open')")
    page.reload()
    until(page, "!!document.querySelector('#top #theme')", 15)
    page.wait_for_timeout(300)
    assert not page.is_visible("#console-grip")
    ctx.close()
