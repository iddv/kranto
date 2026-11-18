"""Every text on the page is readable in both themes: the WCAG contrast of each visible text
against what is drawn under it, 4.5:1 (3:1 for large text), on every route of the fake app
(tests/page/test_browser_smoke.py's), in light and in dark, with the theme from the OS and from
Settings › Appearance against the OS (static/theme.js's html[data-theme]). The palette's pairs are
checked in tests/page/test_palette.py and the themes' in tests/page/test_looks.py; this checks what the page
actually puts together. The checker is tests/page/contrast.js. A disabled control is exempt.

Needs a built UI and Playwright, as the smoke does; CI's browser job runs it."""
import json
from pathlib import Path

import pytest

from .test_browser_smoke import browser, page_base, routes, until  # noqa: F401 - fixtures

pytestmark = [pytest.mark.browser, pytest.mark.built_ui]
CHECK = (Path(__file__).with_name("contrast.js")).read_text()
# (the OS's scheme, Settings › Appearance's base: None is auto)
THEMES = {"light": ("light", None), "dark": ("dark", None),
          "set-dark": ("light", "dark"), "set-light": ("dark", "light")}


@pytest.mark.parametrize("theme", list(THEMES))
def test_every_text_is_readable(browser, page_base, theme):  # noqa: F811 - the fixtures
    scheme, base = THEMES[theme]
    ctx = browser.new_context(viewport={"width": 1360, "height": 900}, color_scheme=scheme)
    if base:
        ctx.add_init_script(f"try {{ localStorage.setItem('kranto.theme', {json.dumps(base)}) }} "
                            "catch (e) {}")
    page = ctx.new_page()
    low = {}
    for route in routes():
        page.goto(f"{page_base}/#/{route}")
        page.wait_for_load_state("load")
        until(page, "document.body.innerText.trim().length >= 40", 10)
        page.wait_for_timeout(500)                   # the route's reads come back
        found = page.evaluate(CHECK)
        if found:
            low[route] = found
    ctx.close()
    assert not low, json.dumps(low, indent=1)
