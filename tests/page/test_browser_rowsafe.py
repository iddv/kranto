"""One bad row never takes a page down, in a real browser: every route
opens on the page server with the server answered in the page (PageAfk) while the server lists one
card it could not read. No route throws, logs a console error, gets a 5xx or says "Something
went wrong"; the other rows draw as always; Ideas lists the card as "Couldn't read this idea"
with its error id; Send this error opens Feedback with the error's report (its report is not
answered here, so it says so) and sends nothing."""
import json
import re

import pytest

from .test_browser_smoke import (  # noqa: F401
    CARDS,
    PageAfk,
    _story,
    browser,
    page_base,
    routes,
    until,
)

pytestmark = [pytest.mark.browser, pytest.mark.built_ui]

BAD_CARD = {"id": 99, "title": "Broken card", "status": "shown", "score": None,
            "created_at": "2026-10-23T10:00:00Z",
            "unreadable": {"what": "idea", "words": "Couldn't read this idea",
                           "error_id": "c0ffee01", "exception": "TypeError"}}


def test_every_route_draws_with_a_row_it_cannot_read(browser, page_base):  # noqa: F811
    afk = PageAfk(topics=["Clinics"], new_kept=3, cards=[*CARDS, BAD_CARD])
    page, errors, sent, _ = _story(browser, afk)
    bad = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error"
            and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status >= 500 else None)
    flagged, said = {}, {}
    for route in routes():
        errors.clear()
        bad.clear()
        page.goto(f"{page_base}/#/{route}")
        page.wait_for_load_state("load")
        until(page, "document.body.innerText.trim().length >= 40", 10, must=False)
        page.wait_for_timeout(500)
        text = page.inner_text("body")
        problems = errors[:3] + bad[:3]
        if re.search(r"Something went wrong|Traceback", text):
            problems.append("an error on the page")
        if problems:
            flagged[route] = problems
        said[route] = page.evaluate(
            "() => [...document.querySelectorAll('#unreadable .unread')].map(e => e.innerText)")
    assert not flagged, json.dumps(flagged, indent=1)
    assert not sent, sent
    assert "Couldn't read this idea · Broken card · error c0ffee01" in " ".join(said["ideas"]), said["ideas"]
    # pages that list no card say nothing of it
    assert not [r for r in ("settings", "activity") if said.get(r)]
    # the other rows draw as always
    page.goto(f"{page_base}/#/ideas")
    until(page, "document.querySelector('#rows').innerText.includes('Clinic schedules')", 10)
    # Send this error: Feedback, with what would be sent shown first; nothing is sent
    until(page, "document.querySelector('#unreadable .unread button')", 10)
    page.click("#unreadable .unread button")
    until(page, "document.querySelector('#fb-report') && !document.querySelector('#fb-report').innerText.startsWith('Reading')", 10)
    report = page.inner_text("#fb-report")
    assert "c0ffee01" in report and "could not be read here" in report
    assert "Couldn't read this idea (error c0ffee01)" in page.input_value("#fb-text")
    assert not sent, sent
    assert not [p for p, _ in afk.writes if p == "/api/feedback"], afk.writes
    page.close()
