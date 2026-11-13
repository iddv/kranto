"""CI's two lanes, `-m "not slow"` and `-m slow`, run every test exactly once between them. (The
research code's weekly `lab` lane left with the lab, CUT.)"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def collected(*args: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/page", "--collect-only", "-q",
                        "-p", "no:cacheprovider", *args], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    m = re.search(r"(\d+)(?:/\d+)? tests? collected", r.stdout)
    assert m, r.stdout[-500:]
    return int(m[1])


def test_the_fast_and_slow_lanes_partition_the_suite():
    everything = collected()
    slow, fast = collected("-m", "slow"), collected("-m", "not slow")
    assert slow > 0 and fast > 0
    assert slow + fast == everything


def test_there_is_no_lab_lane_any_more():
    assert not (ROOT / "tests" / "page" / "lab").exists()
    assert "--lab" not in (ROOT / "tests" / "page" / "conftest.py").read_text()
