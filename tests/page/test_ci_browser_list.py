"""The tests that run in no CI job. ``tests/page/test_browser_trace.py`` and
``tests/page/test_browser_buttons.py`` ran nowhere: ``fast`` skips a browser test ("the web UI is
not built") and ``scripts/ci/browser.sh`` did not name them. ``tests/page/test_mcp_server.py``
skipped "could not import 'mcp'" on every run: ``fast`` synced without the mcp extra. Here:
every browser test file is in browser.sh, CI's jobs sync the extra, and a skip for a missing
import is a failure there (``KRANTO_NO_IMPORT_SKIPS``, tests/page/conftest.py)."""
import re
from pathlib import Path

from .conftest import import_skip

ROOT = Path(__file__).resolve().parents[2]


def test_every_browser_test_file_runs_in_the_browser_job():
    named = set(re.findall(r"tests/page/(test_browser\w*\.py)", (ROOT / "scripts/ci/browser.sh").read_text()))
    files = {p.name for p in (ROOT / "tests" / "page").glob("test_browser*.py")}
    assert files - named == set(), "add these to scripts/ci/browser.sh, or they run in no CI job"
    assert named - files == set(), "scripts/ci/browser.sh names a file that is gone"


def test_ci_syncs_the_mcp_extra_and_fails_a_skip_for_a_missing_import():
    wf = (ROOT / ".github/workflows/ci.yml").read_text()
    for job in ("fast", "slow"):
        body = wf.split(f"\n  {job}:\n", 1)[1].split("\n  # ", 1)[0].split("\n  sandbox:", 1)[0]
        assert "uv sync --locked --extra dev --extra mcp" in body, job
        assert "KRANTO_NO_IMPORT_SKIPS=1" in body, job


def test_a_skip_for_a_missing_import_is_told_apart():
    # pytest's skip report: (path, line, "Skipped: could not import 'mcp': No module named 'mcp'")
    assert import_skip(("t.py", 6, "Skipped: could not import 'mcp': No module named 'mcp'"))
    assert import_skip(("t.py", 6, "Skipped: the web UI is not built")) is None
    assert import_skip("Skipped: could not import 'x'")
    # the server, the other repository, is the one exception, by name and with its reason
    assert import_skip(("t.py", 1, "Skipped: could not import 'kranto.paths': no")) is None
