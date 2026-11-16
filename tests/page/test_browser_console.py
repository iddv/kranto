"""The docked console in a real browser: a start that fails is not started again by itself.
The console's read is answered in the page (a server with terminals, Claude Code chosen) and its
start answers an error: the panel says it once and waits for your press, not a request a frame
(seen on live read-only, where every write was refused: 32,369 starts in one walk). Needs the
built UI (CI's browser job)."""
import json
import re

from .test_browser_smoke import (  # noqa: F401 - fixtures
    browser,
    page_base,
    pytestmark,
    until,
)

STATE = {"settings": {"open": True, "harness": "claude", "model": {}, "permission": "auto",
                      "config": "own", "daily_usd": None},
         "harness": "claude",
         "harnesses": [{"id": "claude", "name": "Claude Code", "installed": True, "models": [],
                        "extras": True}],
         "conversations": {"claude": None}, "plugin": True, "head": None, "why": None,
         "socket": True}


def test_end_this_session_starts_fresh_and_previous_sessions_resume(browser, page_base):
    """ (the owner: "the window does close and the conversation just stays there"): ⋯ › End
    this session asks once, ends it and starts a fresh conversation in the same panel with a
    clean screen; ⋯ › Previous sessions resumes the one that ended; a reload resumes what runs.
    The console's routes are answered here and its terminal is a faked socket that says which
    conversation it is."""
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    conv = {"session": "conv-one", "previous": []}
    calls = []

    def state(rt):
        c = {"tid": "c1", "subject": {"kind": "console", "id": "claude"}, "title": "Claude Code",
             "state": "running", "reason": None, "words": "Running", "usd": 0.0,
             "tokens": None, "sandboxed": False, "cwd": "/h", "branch": None,
             "session": conv["session"], "net": {"allowed": [], "asked": []}, "proposals": [],
             "previous": conv["previous"]}
        rt.fulfill(status=200, content_type="application/json",
                   body=json.dumps({**STATE, "conversations": {"claude": c}}))

    def post(rt):
        what = rt.request.url.rsplit("/", 1)[-1]
        body = json.loads(rt.request.post_data or "{}")
        calls.append((what, body))
        if what == "end" and body.get("fresh"):
            conv["previous"] = [{"session": conv["session"], "ended": 1793170000,
                                 "started": 1793160000, "usd": 0.4}, *conv["previous"]]
            conv["session"] = "conv-two"
        elif what == "resume":
            was = conv["session"]
            conv["previous"] = [{"session": was, "ended": 1793171000, "started": 1793170000,
                                 "usd": 0.1}, *[p for p in conv["previous"]
                                                if p["session"] != body["session"]]]
            conv["session"] = body["session"]
        rt.fulfill(status=200, content_type="application/json",
                   body=json.dumps({"tid": "c1", "ticket": "t", "harness": "claude",
                                    "session": conv["session"]}))

    def socket(ws):
        ws.send(f"conversation {conv['session']}\r\n> ".encode())
    page.route(re.compile(r"/api/term/console$"), state)
    page.route(re.compile(r"/api/term/console/(open|end|resume|here)$"), post)
    page.route_web_socket(re.compile(r"/term/ws/"), socket)
    page.goto(f"{page_base}/#/home")
    screen = "document.querySelector('#console .xterm-rows')?.innerText || ''"
    until(page, f"({screen}).includes('conversation conv-one')")
    # minimize hides it and ends nothing
    page.click("#console [aria-label='Minimize']")
    assert page.is_visible("#console-min") and not [c for c in calls if c[0] == "end"]
    page.click("#console-min")
    page.click("#console [title='More']")
    assert page.inner_text("#console-previous") == "Previous sessions"
    page.click("#console-end")
    dialog = page.get_by_role("dialog")
    assert "This conversation is kept" in dialog.inner_text()
    page.get_by_role("button", name="End and start fresh").click()
    until(page, f"({screen}).includes('conversation conv-two')")
    assert "conv-one" not in page.evaluate(screen), "a clean prompt, not the old screen"
    assert ("end", {"harness": "claude", "fresh": True}) in calls
    # Previous sessions › the one that ended: it comes back
    page.click("#console [title='More']")
    until(page, "!document.querySelector('#console-previous').disabled")
    page.click("#console-previous")
    page.click("#console .con-prev button")
    until(page, f"({screen}).includes('conversation conv-one')")
    assert ("resume", {"harness": "claude", "session": "conv-one"}) in calls
    # a reload resumes what runs (the default), never a new one
    page.reload()
    until(page, f"({screen}).includes('conversation conv-one')")
    assert [c for c in calls if c[0] == "end"] == [("end", {"harness": "claude", "fresh": True})]
    page.close()


def test_a_failed_start_waits_for_your_press(browser, page_base):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    opens = []
    page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(STATE)))

    def refuse(rt):
        opens.append(rt.request.method)
        rt.fulfill(status=500, content_type="application/json",
                   body=json.dumps({"error": "Claude Code did not start"}))
    page.route(re.compile(r"/api/term/console/open$"), refuse)
    page.goto(f"{page_base}/#/home")
    until(page, "document.querySelector('#console .con-error')")
    page.wait_for_timeout(3000)
    assert len(opens) == 1, f"{len(opens)} starts after one failure"
    assert "did not start" in page.inner_text("#console .con-error")
    page.click("#console .con-empty > .btn")        # Start (plain beside the starters,)
    page.wait_for_timeout(1500)
    assert len(opens) == 2, "your press starts it again, once"
    page.close()


def test_an_empty_console_offers_three_starters_and_sends_the_one_you_click(browser, page_base):
    """an empty console (no conversation yet) offers three questions with a
    line each; a click types the sentence into the session and sends it, and the starters give
    way to the conversation."""
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    typed = []
    page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(STATE)))
    page.route(re.compile(r"/api/term/console/(open|here)$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"tid": "c1", "ticket": "t", "harness": "claude", "session": "s"})))

    def socket(ws):
        ws.on_message(lambda m: typed.append(m if isinstance(m, str) else m.decode("utf-8", "replace")))
        ws.send(b"Claude Code\r\n> ")
    page.route_web_socket(re.compile(r"/term/ws/"), socket)
    page.goto(f"{page_base}/#/home")
    until(page, "document.querySelectorAll('#console-starters .con-starter').length === 3")
    labels = page.locator("#console-starters .cs-q").all_inner_texts()
    assert labels[1:] == ["Which idea should I look at?", "Write a post about this week's news"], labels
    assert labels[0].startswith("What is new in"), labels
    assert page.locator("#console-starters .cs-says").all_inner_texts()[2] == "a draft on Post; nothing is sent"
    page.locator("#console-starters .con-starter").nth(1).click()
    until(page, "!document.querySelector('#console-starters')")
    page.wait_for_timeout(500)
    assert any("Which idea should I look at?" in t for t in typed), typed
    page.close()


def test_on_a_phone_the_console_is_read_and_approve_not_a_terminal(browser, page_base):
    """on a phone the console opens as a sheet when you ask (✦ in the bar of doors): what waits
    for your yes and what it last said, with one link to the terminal; no session starts by
    itself, and a place kept as open does not cover the page by itself."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.add_init_script("localStorage.setItem('kranto.console', 'open')")
    opened = []
    said = {"harness": "claude", "said": "Robotics has a new brief with five items.",
            "more": False, "at": "2026-11-11T19:01:00Z", "page": "#/news/b/26"}
    page.route(re.compile(r"/api/term/console$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(STATE)))
    page.route(re.compile(r"/api/term/console/last$"), lambda rt: rt.fulfill(
        status=200, content_type="application/json", body=json.dumps(said)))

    def refuse(rt):
        opened.append(1)
        rt.fulfill(status=500, content_type="application/json", body="{}")
    page.route(re.compile(r"/api/term/console/open$"), refuse)
    page.goto(f"{page_base}/#/needs")
    # ✦: the bar of doors' Console (New), else the top bar's chip of the minimized console
    ask = "#tab-console:visible, #console-min:visible"
    until(page, "!!document.querySelector('#tab-console, #console-min')")
    page.wait_for_timeout(1500)                       # the console has read its state and placed
    assert not page.is_visible("#console-phone"), "the sheet waits for ✦"
    page.locator(ask).first.click()
    until(page, "!!document.querySelector('#console-phone')")
    text = page.inner_text("#console-phone")
    assert "Waiting for your yes" in text and "What it last said" in text
    assert "Robotics has a new brief with five items." in text
    assert page.get_attribute("#console-phone a[href='#/news/b/26']", "href") == "#/news/b/26"
    assert "Start a conversation on a wider screen" in text
    assert not page.is_visible("#console .screen") and not opened, "no terminal on a phone by itself"
    page.click("#console-phone-full")
    until(page, "!document.querySelector('#console-phone')")
    ctx.close()
