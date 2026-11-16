"""What Kranto is doing, in a real browser (test 10): the top bar's one item spins
only while a run runs and says Quiet otherwise; it opens Activity, whose groups draw from the read
and grow without a reload when the live feed says so; Watch › opens the run's trace following it;
at 1400 px and on a 390 px phone (the ring and the count only there), with no console error, no
write and no setting key or null on the page. The activity read is answered in the page (the smoke
app has no server); everything else is the fake app's. Needs the built UI (CI's browser job)."""
import json
import re

from .test_browser_smoke import (  # noqa: F401 - fixtures
    BUILT,
    HOST_PROBE,
    OWNER_TEXT,
    browser,
    owner_words,
    page_base,
    pytestmark,
    setting_keys,
    until,
)

UUID = "0f9e8d7c6b5a49382716a5b4c3d2e1f0"


def run(**o) -> dict:
    return {"id": f"afk:{UUID}", "uuid": UUID, "kind": "news.brief", "title": "Writing the News brief",
            "words": "Collecting Robotics' history · arXiv", "state": "running",
            "trigger": {"origin": "press", "by": "ui", "at": "2026-10-23T01:00:00Z"},
            "subject": {"kind": "topic", "id": "12", "name": "Robotics"}, "feature": "news",
            "started": "2026-10-23T01:00:00Z", "finished": None, "elapsed_s": 72.0, "usd": 0.03,
            "calls": 1, "tokens": None, "progress": None, "trace": f"#/afk/{UUID}/trace",
            "stoppable": True, "stopping": False, "needs": None, "error": None, "why": None,
            "verb": None, **o}


def read(**o) -> dict:
    out = {"seq": 1, "running": [], "waiting": [], "recent": [], "folded": [], "failing": [],
           "next": [{"kind": "ingest", "title": "Reading your sources", "at": "2026-10-23T20:23:00Z",
                     "every_words": "every 2 hours", "last": {"state": "ok", "at": "2026-10-23T18:23:00Z", "why": None},
                     "failing_since": None, "failures_in_a_row": 0}],
           "counts": {}, "quiet": "Nothing is running. Next: reading your sources at 20:23.",
           "scheduler": True, "paused": False, "afk_error": None, "now": "2026-10-23T02:00:00Z"}
    out.update(o)
    out["counts"] = {"running": len(out["running"]), "waiting": len(out["waiting"]), "failed_recent": 0,
                     "failing": len(out["failing"]), "building": 0}
    return out


def open_page(browser, width: int, answer: dict):
    page = browser.new_page(viewport={"width": width, "height": 900 if width > 500 else 844})
    errors, sent = [], []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # an HTTP error, but the host probe's 404 (the smoke app has no server: that is how it knows)
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}")
            if r.status >= 400 and not r.url.endswith(HOST_PROBE) else None)
    page.on("request", lambda r: sent.append(f"{r.method} {r.url}") if r.method not in ("GET", "HEAD") else None)
    page.route(re.compile(r"/api/whoami$"), lambda rt: rt.fulfill(status=200, content_type="application/json",
                                                                 body=json.dumps({"origin": "owner", "require_token": True})))
    page.route(re.compile(r"/api/activity(\?.*)?$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(answer["now"])))
    return page, errors, sent


def test_the_indicator_spins_only_while_a_run_runs_and_opens_activity(browser, page_base):
    answer = {"now": read()}
    for width in (1400, 390):
        page, errors, sent = open_page(browser, width, answer)
        answer["now"] = read()
        page.goto(f"{page_base}/#/needs")
        until(page, "!!document.querySelector('#hd-activity[data-state=quiet]')", 15)
        assert page.locator("#hd-activity .i.spin").count() == 0           # nothing spins
        # the word alone in the bar at every width; what is next is its tooltip
        assert page.inner_text("#hd-activity").strip() == "Quiet"
        assert "next: reading your sources at" in (page.get_attribute("#hd-activity", "aria-label") or "")
        answer["now"] = read(running=[run()])
        # a run starts: the page that is opened now reads it (the smoke app's feed says nothing,
        # so a fresh load stands in for the change it would send)
        page.goto(f"{page_base}/#/activity")
        page.reload()
        until(page, "!!document.querySelector('#hd-activity[data-state=running]')", 15)
        assert page.locator("#hd-activity .i.spin").count() == 1
        until(page, "!!document.querySelector('#act-running')", 15)
        text = page.inner_text(".act")
        assert "Writing the News brief" in text and "Watch ›" in text and "Stop" in text
        assert owner_words(page.evaluate(OWNER_TEXT), setting_keys()) == []
        page.close()
        assert not errors and not sent, errors + sent


def test_activity_draws_its_groups_and_watch_opens_the_running_trace(browser, page_base):
    failing = {"id": "fail:update", "kind": "update", "title": "The update check", "since": "2026-10-19T08:00:00Z",
               "last": "2026-10-22T08:00:00Z", "tries": 3, "error": "GitHub answered 401", "verb": "Try again",
               "trace": "#/afk/u3/trace", "runs": []}
    waiting = run(id="afk:w1", uuid="w1", state="waiting", words="The brief for Robotics waits for you",
                  needs={"verb": "Review", "href": "news/topics"}, stoppable=False)
    done = run(id="afk:d1", uuid="d1", kind="ingest", title="Read your sources", state="ok", words="8 sources · 12 kept",
               finished="2026-10-23T01:30:00Z", stoppable=False)
    answer = {"now": read(running=[run()], waiting=[waiting], failing=[failing], recent=[done],
                          folded=[{"kind": "ideas", "state": "skipped", "n": 22, "first": None, "last": "2026-10-23T01:00:00Z",
                                   "why": "the map has not changed", "title": "Writing idea cards",
                                   "line": "Writing idea cards · skipped 22 times today: the map has not changed"}])}
    page, errors, sent = open_page(browser, 1400, answer)
    page.goto(f"{page_base}/#/activity")
    until(page, "!!document.querySelector('#act-recent')", 15)
    body = page.inner_text(".act")
    for words in ("Running now", "Waiting on you", "Review", "Failing", "The update check is failing", "Try again",
                  "Next", "Reading your sources", "Recent", "Read your sources",
                  "Writing idea cards · skipped 22 times today: the map has not changed"):
        assert words in body, words
    # a failing row's one verb is Try again; Dismiss is its ⋯'s
    assert page.locator("section[aria-labelledby=act-failing] li.row .row-more").count() == 1
    # Stop says which run in its toast and offers Undo; undone, nothing is asked
    page.locator(".act button:has-text('Stop')").first.click()
    until(page, "document.body.innerText.includes('Writing the News brief: stopping at its next step')", 5)
    page.locator("button:has-text('Undo')").first.click()
    # a run that starts later shows without a reload (the page reads again on a change)
    answer["now"] = read(running=[run(), run(id="afk:x2", uuid="x2", title="Reading your sources", kind="ingest")],
                         waiting=[waiting], failing=[failing], recent=[done])
    page.evaluate("() => { document.dispatchEvent(new Event('visibilitychange')); }")
    until(page, "document.querySelector('.act').innerText.split('Waiting on you')[0].includes('Reading your sources')", 20)
    page.locator(".act a:has-text('Watch ›')").first.click()
    page.wait_for_url(re.compile(rf"#/afk/{UUID}/trace\?follow=1$"))
    page.close()
    assert not sent, sent
    # the trace of a run the fake app does not have answers 404, as a run that ended long ago would
    assert not [e for e in errors if "/api/trace" not in e], errors
    assert BUILT
