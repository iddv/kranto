"""prompts.lock.json: a change to a prompt the server ships, or
to TENETS, fails here until the lock names the scorecard that evaluated the new version (or
says why it was skipped). The only place CI touches evaluation; it costs nothing."""

import json
from pathlib import Path

import pytest

from kranto.evals import lock

ROOT = Path(__file__).resolve().parents[1]


def test_every_shipped_prompt_is_locked_at_its_version():
    probs = lock.problems(lock.read(ROOT / lock.LOCK))
    assert probs == [], "prompts.lock.json:\n" + "\n".join(probs)


def test_a_changed_prompt_names_its_eval():
    now = lock.shipped()
    stale = {**json.loads((ROOT / lock.LOCK).read_text()),
             "screen": {"version": "screen-00000000", "evaluated": "2026-10-01",
                        "scorecard": "x.md"}}
    (msg,) = lock.problems(stale, now)
    assert msg.startswith("`screen` changed (screen-00000000 -> ") and "kranto eval watching" in msg
    stale["screen"] = {"version": now["screen"], "evaluated": "2026-10-01"}
    assert lock.problems(stale, now) == ["`screen`: evaluated 2026-10-01 but names no scorecard"]
    del stale["screen"]
    stale["gone"] = {"version": "gone-1", "evaluated": "skipped: x"}
    assert [p.split(" ")[0] for p in lock.problems(stale, now)] == ["`screen`", "`gone`"]


def test_set_entry(tmp_path):
    p = tmp_path / lock.LOCK
    e = lock.set_entry(p, "card", skipped="a reason")
    assert e == {"version": lock.shipped()["card"], "evaluated": "skipped: a reason"}
    e = lock.set_entry(p, "judge", scorecard="scorecards/a.md")
    assert e["scorecard"] == "scorecards/a.md" and e["evaluated"][:2] == "20"
    with pytest.raises(ValueError):
        lock.set_entry(p, "nope", skipped="x")
    with pytest.raises(ValueError):
        lock.set_entry(p, "card")
