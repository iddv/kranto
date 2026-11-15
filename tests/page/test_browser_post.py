"""Post on a phone and on a desktop. Write a post's dialog fits a 390 × 844 phone in both
themes (it was 358 px wide with 570 px of content, the angle's box past the screen's edge): the
dialog's scroll width is within its width, its question sits above its box, and Cancel and Write
draft are on the screen. Post's rows say what matters, at 1400 × 900 and on the phone: a
scheduled post its day, hour and site, a sent post where and how it went, a failed write its
reason, and Where posts go its whole line, none of them cut.

The server is answered in the page (test_browser_smoke's PageAfk, an idea card, Post's read).
Needs the built UI (CI's browser job)."""
import json
import re

import pytest

from .test_browser_smoke import (  # noqa: F401 - fixtures
    CARDS,
    PageAfk,
    browser,
    page_base,
    pytestmark,
    until,
)

SITES = {"sites": [
    {"id": "bluesky", "name": "Bluesky", "ways": ["open", "direct"], "ticked": True, "direct": False,
     "can_direct": True, "account": None, "account_state": "not set", "connection": "bluesky_post",
     "needs": None, "instance": None, "limit": 300, "unit": "characters", "disclose": False},
    {"id": "x", "name": "X", "ways": ["open"], "ticked": True, "direct": False, "can_direct": False,
     "account": None, "account_state": "not set", "connection": None, "needs": None,
     "instance": None, "limit": 280, "unit": "characters, a link counts 23", "disclose": False}],
    "not_offered": [], "disclosure": "Drafted with this tool.",
    "blog": {"state": "not set", "account": None, "post_url": None}}
ANGLES = {"angles": [
    {"kind": "end", "text": "Within two years most clinics will book from a phone, and paper diaries will "
                            "be the exception rather than the rule.", "words": "where it leads"},
    {"kind": "bet", "text": "The first clinic chain to drop paper will win the waiting-list war.",
     "words": "a bet"},
    {"kind": "scene", "text": "A receptionist at eight in the morning, three phones ringing and one pen.",
     "words": "a scene"}]}

REASON = ("No draft was written: Claude Code is not installed on this machine. Install it, or "
          "choose another provider on Settings › Watching, then choose Write a post again.")


def _json(rt, body):
    rt.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _owner(page):
    page.route(re.compile(r"/api/whoami$"), lambda rt: _json(rt, {"origin": "owner", "require_token": True}))


DIALOG = r"""() => {
  const d = document.querySelector('dialog[open]');
  const r = d.getBoundingClientRect();
  const box = document.querySelector('#write-post-angle').getBoundingClientRect();
  const lab = document.querySelector('label[for=write-post-angle]').getBoundingClientRect();
  const ok = document.querySelector('#dlg-ok').getBoundingClientRect();
  const cancel = [...d.querySelectorAll('.dlg-f .btn')].find((b) => b.textContent.trim() === 'Cancel').getBoundingClientRect();
  const body = d.querySelector('.dlg-b');
  return { w: d.clientWidth, sw: d.scrollWidth, bw: body.clientWidth, bsw: body.scrollWidth, vw: innerWidth,
           left: r.left, right: r.right, box: [box.left, box.right], labBottom: lab.bottom, boxTop: box.top,
           ok: [ok.left, ok.right, ok.top, ok.bottom], cancel: [cancel.left, cancel.right], vh: innerHeight };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_write_a_post_fits_a_phone(browser, page_base, scheme):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, color_scheme=scheme,
                              has_touch=True, is_mobile=True)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    PageAfk(topics=["Clinics"], cards=CARDS).install(page)
    _owner(page)
    page.route(re.compile(r"/api/prose$"), lambda rt: _json(rt, {"voice": "Plain.", "samples": []}))
    page.route(re.compile(r"/api/post/sites$"), lambda rt: _json(rt, SITES))
    page.route(re.compile(r"/api/post/angles$"), lambda rt: _json(rt, ANGLES))
    page.goto(f"{page_base}/#/ideas/7")
    until(page, "!!document.querySelector('#idea-write')", 15)
    page.locator("#idea-write").first.click()
    until(page, "!!document.querySelector('dialog[open] #write-post-angle')", 10)
    until(page, "document.querySelectorAll('#write-post-angles [data-angle]').length === 3", 10)
    page.check('input[name="write-as"][value="short"]')
    page.wait_for_timeout(300)
    m = page.evaluate(DIALOG)
    assert m["sw"] <= m["w"] + 1, m                    # nothing scrolls sideways in the dialog
    assert m["bsw"] <= m["bw"] + 1, m
    assert m["right"] <= m["vw"] + 0.5 and m["left"] >= -0.5, m
    assert m["box"][1] <= m["right"] + 0.5, m           # the angle's box inside the dialog
    assert m["labBottom"] <= m["boxTop"] + 0.5, m       # its question above it
    assert m["ok"][0] >= 0 and m["ok"][1] <= m["vw"] + 0.5, m
    assert m["cancel"][0] >= 0 and m["cancel"][1] <= m["vw"] + 0.5, m
    # the second As choice keeps its circle beside its words
    pair = page.evaluate("""() => { const l = document.querySelector('input[value=short]').closest('label');
      const i = l.querySelector('input').getBoundingClientRect(); return { inputTop: i.top, labelTop: l.getBoundingClientRect().top }; }""")
    assert abs(pair["inputTop"] - pair["labelTop"]) < 12, pair
    ctx.close()
    assert not errors, errors


def _post_read():
    def draft(n, **o):
        return {"id": n, "ref": f"draft:{n}", "cub": "social", "kind": "short", "word": "short posts",
                "title": "Pre-purchase solar-and-battery payback check for UK homes before VAT returns "
                         "in April 2027", "fact": "from #2", "at": "2026-11-15T08:00:00Z", "ticket": None,
                "again": None, "verb": None, "line": None, "said": None, "note": None, "link": None,
                "account": True, **o}
    return {
        "line": "Drafts wait here until you have seen them.",
        "drafts": [], "earlier": [],
        "scheduled": [draft(2, site="bluesky", site_word="Bluesky", due="2026-11-17T09:00:00Z",
                            due_words="Tuesday 17 Nov, 09:00", ticket=12)],
        "sent": [draft(5, site="x", site_word="X", said="posted by you")],
        "failed": [{"about": "card:1", "as": "blog", "at": "2026-11-15T10:00:00Z",
                    "title": "Replay your own home-battery logs against rival tariffs before you switch",
                    "error": REASON, "fix": "settings/watching"}],
        "accounts": [{"key": "newsletter", "word": "Newsletter", "state": "not set", "account": None, "platform": None},
                     {"key": "blog", "word": "Blog", "state": "not set", "account": None, "platform": None}],
        "sites": {"line": "Bluesky and X open in the site, with the draft filled in. Bluesky is "
                          "posted after your yes once you connect it.", "ticked": 2},
        "reach_foot": None,
    }


ROWS = r"""() => {
  const one = (id, sel) => { const e = document.querySelector(sel.startsWith('li.')
      ? `section[aria-labelledby=${id}] ${sel}` : `section[aria-labelledby=${id}] li.row ${sel}`);
    if (!e) return null; const s = getComputedStyle(e);
    return { text: e.innerText.trim(), shown: e.getClientRects().length > 0 && s.display !== 'none' && s.visibility !== 'hidden',
             cut: e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 2 }; };
  return { due: one('post-scheduled', '.r-title'), sent: one('post-sent', '.r-title'),
           why: one('post-failed', 'li.row-why'), where: one('post-accounts', '.c-meta') };
}"""


@pytest.mark.parametrize("width,height", [(1400, 900), (390, 844)])
def test_post_rows_say_when_where_and_why(browser, page_base, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height}, timezone_id="Europe/London",
                              has_touch=width < 500, is_mobile=width < 500)
    page = ctx.new_page()
    PageAfk(topics=["Clinics"]).install(page)
    _owner(page)
    page.route(re.compile(r"/api/post$"), lambda rt: _json(rt, _post_read()))
    page.goto(f"{page_base}/#/post")
    until(page, "!!document.querySelector('section[aria-labelledby=post-scheduled] li.row')", 15)
    page.wait_for_timeout(300)
    got = page.evaluate(ROWS)
    assert got["due"] == {"text": "Tue 17 Nov, 09:00 · Bluesky", "shown": True, "cut": False}, got
    assert got["sent"] == {"text": "X · posted by you", "shown": True, "cut": False}, got
    assert got["why"]["text"] == REASON and got["why"]["shown"] and not got["why"]["cut"], got
    assert got["where"]["shown"] and not got["where"]["cut"], got
    assert got["where"]["text"].endswith("Newsletter: not set."), got
    ctx.close()
