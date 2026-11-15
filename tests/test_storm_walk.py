"""rc_check's request-storm step (scripts/release/storm_walk.py). v0.6.0-dev3 passed
rc_check while its console posted console/open without end; the step counts each address's
asks in the walk's window. The browser part runs in rc_check (Playwright); here, the counting
and that rc_check runs it."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("storm_walk", ROOT / "scripts/release/storm_walk.py")
storm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(storm)


def test_an_address_asked_without_end_is_a_storm():
    loop = [(i * 0.01, "POST /brb/api/term/console/open") for i in range(300)]
    reads = [(i * 5.0, "GET /api/activity") for i in range(6)]
    assert storm.storms(loop + reads) == {"POST /brb/api/term/console/open": 300}


def test_a_page_polling_as_it_should_is_not():
    # every 5 s for a minute: 13 asks, never more than 7 in 30 s
    polls = [(i * 5.0, "GET /brb/api/activity") for i in range(13)]
    assert storm.storms(polls) == {}
    # 21 asks spread over 40 s: never 21 within 30 s
    spread = [(i * 2.0, "GET /api/today") for i in range(21)]
    assert storm.storms(spread) == {}
    assert storm.storms(spread, window=40.0) == {"GET /api/today": 21}


def test_an_address_is_its_method_and_path():
    assert storm.key("POST", "http://127.0.0.1:9820/brb/api/term/console/open?x=1") == \
        "POST /brb/api/term/console/open"


def test_rc_check_runs_it_and_says_so():
    sh = (ROOT / "scripts/release/rc_check.sh").read_text()
    assert 'step "7. no request storm' in sh and "storm_walk.py" in sh
    assert "all eight pass" in sh
    # the sign-in link is kept out of every log
    uses = [ln.strip() for ln in sh.splitlines() if "$link" in ln]
    assert uses and all(u.startswith(("[ -n \"$link\" ]", "STORM_LINK=\"$link\"")) for u in uses)
