"""Every pytest lane in CI prints its skips with their reasons (``-rs``), so a job that skipped
what it was meant to run says so in its log (9; the fix 5 did the server's lanes)."""
from __future__ import annotations

import re
from pathlib import Path

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def test_the_fast_and_slow_lanes_print_their_skips():
    runs = [ln for ln in WF.read_text().splitlines() if re.search(r"\bpytest -q\b", ln)]
    lanes = [ln for ln in runs if "-m \"not slow\"" in ln or "-m slow" in ln]
    assert len(lanes) >= 2, runs
    for ln in lanes:
        assert " -rs" in ln, ln
