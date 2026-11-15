"""CI's own limits (the operator's fix 15): the server's ``test`` job ran 18 to 22
minutes on ``oss`` in wave 2 and was cancelled at its 25-minute limit three times with nothing
failing. Its limit is 35."""

from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_the_test_job_has_room_for_a_busy_day():
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert jobs["test"]["timeout-minutes"] == 45
