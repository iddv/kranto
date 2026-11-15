"""The trace page in a real browser: signed in on ``brb ui`` over a research run's
kept stream (the hand-written build session from tests/page/fixtures/trace, kept where the
researcher keeps it), it draws the tree with no error, a span opens in the inspector, the phone gets the Log and
the inspector as a sheet, every text is readable in light and dark (tests/page/contrast.js), a
running stream grows live, and a 50,000-span trace paints its first rows and selects a span
within the design's budget. Builds left with the factory (CUT): the trace page reads sessions,
research runs and the server's runs.

Needs the built UI and Playwright, as tests/page/test_browser_smoke.py does; CI's browser job runs it."""
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from kranto.page import tokens as tokens_mod
from kranto.page.trace.file import transcripts_dir
from kranto.page.ui.server import make_server

from .test_browser_smoke import browser, until  # noqa: F401 - the fixture
from .test_trace_scale import STEM as SCALE_STEM
from .test_trace_scale import make_big

pytestmark = [pytest.mark.browser, pytest.mark.built_ui]
FIX = Path(__file__).parent / "fixtures" / "trace" / "sample-r1" / ".den" / "v5" / "r1" / "transcripts"
CHECK = (Path(__file__).with_name("contrast.js")).read_text()
STEM = "1790000000-loop"
TRACE = f"#/research/{STEM}/trace"


@pytest.fixture
def site(tmp_path):
    """``(base, sign_in(page, hash), the research run's stream, store)``: brb ui over a loop home
    holding one kept research run (the fixture's build session, ended)."""
    # the process's one live hub outlives the servers of earlier test files: their streams and
    # watchers (another app's files) would send changes here too, and a read one sends just before
    # a turn lands holds the turn's read back by the page's 2 s gap
    from kranto.page.ui.live import HUB
    with HUB.cond:
        HUB.streams.clear()
        HUB.watchers.clear()
        HUB.cond.notify_all()
    root = tmp_path / "tasks"
    root.mkdir()
    loop = tmp_path / "loop"
    keep = transcripts_dir(loop)
    keep.mkdir(parents=True)
    f = keep / f"{STEM}.transcript.jsonl"
    shutil.copyfile(FIX / "build.transcript.jsonl", f)
    store = tokens_mod.Store(tmp_path / "tokens")
    srv = make_server(root, port=0, harness="fake", loop_home=loop, tokens=store, require=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def sign_in(page, hash_: str) -> None:
        page.goto(f"{base}/auth/open?code={store.mint_code()}&next=/{hash_.replace('#', '%23')}")
        page.wait_for_load_state("load")

    try:
        yield base, sign_in, f, store
    finally:
        srv.shutdown()
        srv.server_close()


def watch(page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error"
            and not m.text.startswith("Failed to load resource") else None)
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400
            and not r.url.endswith("/api/status") else None)
    return errors


def test_the_trace_draws_and_a_span_opens(browser, site):  # noqa: F811
    _, sign_in, _, _ = site
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = watch(page)
    sign_in(page, TRACE)
    until(page, "document.querySelectorAll('.sr').length > 5", 20)
    assert page.inner_text("h1").startswith("Research")
    page.click(".sr:nth-child(3) .pick")
    until(page, "document.querySelector('.insp .ih')", 10)
    page.keyboard.press("j")
    page.keyboard.press("j")
    until(page, "document.querySelector('.sr.t-sel')", 5)
    page.keyboard.press("3")                           # its Output
    until(page, "(document.querySelector('.itabs [aria-current=page]')||{}).textContent?.startsWith('Output')", 5)
    assert f"#/research/{STEM}/trace?span=" in page.url
    assert not errors, errors


def test_on_the_phone_the_log_and_the_sheet(browser, site):  # noqa: F811
    _, sign_in, _, _ = site
    page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    errors = watch(page)
    sign_in(page, TRACE)
    until(page, "document.querySelectorAll('.sr').length > 5", 20)
    assert page.evaluate("document.querySelectorAll('.sr .t-tw').length") == 0     # the Log form
    page.click(".sr:nth-child(3) .pick")
    until(page, "document.querySelector('.right.t-sheet .insp')", 10)
    page.click(".right.t-sheet .close")
    until(page, "!document.querySelector('.right.t-sheet')", 5)
    assert not errors, errors


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_text_on_the_trace_is_readable(browser, site, scheme):  # noqa: F811
    _, sign_in, _, _ = site
    ctx = browser.new_context(viewport={"width": 1400, "height": 900}, color_scheme=scheme)
    page = ctx.new_page()
    sign_in(page, TRACE)
    until(page, "document.querySelectorAll('.sr').length > 5", 20)
    page.click(".sr:nth-child(3) .pick")
    until(page, "document.querySelector('.insp .ih')", 20)
    page.wait_for_timeout(500)
    low = page.evaluate(CHECK)
    ctx.close()
    assert not low, json.dumps(low, indent=1)


def _turn(n: int) -> str:
    """One more turn of a running session: a Bash call and its result."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    return "".join(json.dumps(o) + "\n" for o in (
        {"type": "assistant", "timestamp": ts, "message": {
            "id": f"live-{n}", "usage": {"input_tokens": 5, "output_tokens": 9},
            "content": [{"type": "tool_use", "id": f"live-tool-{n}", "name": "Bash",
                         "input": {"command": f"pytest -q -k live_{n}"}}]}},
        {"type": "user", "timestamp": ts, "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"live-tool-{n}", "content": "1 passed"}]}}))


def test_a_running_trace_grows_live_and_survives_a_reconnect(browser, site):  # noqa: F811
    """the acceptance: a running run's new spans show within 2 s of their lines (a stream
    without its result that grew lately is running); the feed dropped and back (the page offline
    a moment) loses none."""
    _, sign_in, f, _ = site
    rows = f.read_text().splitlines(keepends=True)
    f.write_text("".join(r for r in rows if json.loads(r)["type"] != "result"))
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    errors = watch(page)
    sign_in(page, TRACE)
    height = "() => parseInt(document.querySelector('.spacer').style.height)"
    until(page, "document.querySelectorAll('.sr').length > 5", 20)
    page.wait_for_timeout(1500)                                 # the follow is registered
    for n in range(1, 3):
        before = page.evaluate(height)
        with open(f, "a") as fh:
            fh.write(_turn(n))
        t0 = time.monotonic()
        until(page, f"parseInt(document.querySelector('.spacer').style.height) > {before}", 10)
        took = time.monotonic() - t0
        assert took < 2.0 + 1.0, f"turn {n} showed after {took:.1f} s"    # 2 s, a tick's slack
    # the feed drops: the server ends every stream and the page cannot reconnect for a while
    # (with no stream open the server stops watching, so what lands meanwhile sends no event)
    from kranto.page.ui.live import HUB
    page.route("**/api/stream*", lambda route: route.abort())
    with HUB.cond:
        HUB.streams.clear()
        HUB.cond.notify_all()
    page.wait_for_timeout(4000)                                 # past PING_S: the streams end
    before = page.evaluate(height)
    with open(f, "a") as fh:
        fh.write(_turn(3) + _turn(4))                           # written while it was down
    page.wait_for_timeout(1500)
    page.unroute("**/api/stream*")                              # the feed is back
    t0 = time.monotonic()
    # 7: the page reads on from its cursor as the feed reconnects (the EventSource retries
    # every 3 s), not at the next change or the 60 s read: within 10 s (measured 30 s)
    until(page, f"parseInt(document.querySelector('.spacer').style.height) >= {before} + 60", 10)
    print(f"caught up {time.monotonic() - t0:.1f} s after the feed came back")
    ctx.close()
    assert not [e for e in errors if "api/stream" not in e and "ERR_INTERNET" not in e], errors


def test_a_50000_span_trace_paints_and_selects_in_budget(browser, site, tmp_path):  # noqa: F811
    """the acceptance, on a trace the server has open (its first read of 50,000
    spans is bounded by tests/page/test_trace_scale.py): the first rows within 1.5 s of the page's
    load, a span selected (its inspector drawn) within 200 ms. The big session is kept as a
    research run's stream."""
    base, sign_in, f, store = site
    big = make_big(tmp_path / "scratch") / f"{SCALE_STEM}.transcript.jsonl"
    stem = "1790000001-big"
    shutil.move(big, f.with_name(f"{stem}.transcript.jsonl"))
    import urllib.request
    req = urllib.request.Request(f"{base}/api/trace?trace=research:{stem}",
                                 headers={"Authorization": "Bearer " + (store.value("ui") or "")})
    with urllib.request.urlopen(req, timeout=120) as r:  # the server reads it once
        assert json.loads(r.read())["spans"] >= 49_990     # no stage span: a research run has none
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = watch(page)
    sign_in(page, f"#/research/{stem}/trace")
    t0 = time.monotonic()
    until(page, "document.querySelectorAll('.sr').length > 10", 30)
    first = time.monotonic() - t0
    assert page.evaluate("document.querySelectorAll('.sr').length") < 200       # windowed
    took = page.evaluate("""async () => {
      const row = document.querySelectorAll('.sr .pick')[6];
      const t = performance.now();
      row.click();
      while (!document.querySelector('.insp .ih')) await new Promise((r) => requestAnimationFrame(r));
      return performance.now() - t;
    }""")
    assert first < 1.5, f"the first rows after {first:.2f} s"
    assert took < 200, f"a span selected in {took:.0f} ms"
    assert not errors, errors
