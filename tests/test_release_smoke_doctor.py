"""smoke.sh's judge of `kranto doctor` on a bare machine (scripts/release/smoke_doctor.py).

A cut's setup smoke runs doctor on a new HOME with no model chosen; doctor may lack only Claude
Code, gh's login and the model, and must say the model is missing."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "release_smoke_doctor", ROOT / "scripts" / "release" / "smoke_doctor.py")
smoke_doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke_doctor)

# today's doctor on a bare machine, before Welcome's model step (exit 0)
FRESH = """\
ok    migrations     current
ok    library        schema v44, 0 observations
warn  model          none chosen yet: Welcome's first step chooses one
warn  sources        none approved; add a topic or a pack
ok    kranto.page    API version 7 (needs 1)
warn  claude         Claude Code is not installed; Kranto works without it.
warn  gh             gh is not logged in: 'File a Kranto issue' needs it (gh auth login)
"""

# an older doctor, or a model chosen whose key is unset (exit 1)
KEY_FAILS = """\
ok    migrations     current
FAIL  api key        $OPENROUTER_API_KEY is not set
FAIL  claude         Claude Code is not installed
warn  gh             gh is not logged in
"""


def test_a_fresh_install_that_warns_no_model_is_chosen_passes_with_exit_0():
    ok, line = smoke_doctor.judge(FRESH, 0)
    assert ok and "no model is chosen" in line


def test_a_doctor_that_fails_only_on_the_key_and_claude_passes():
    ok, line = smoke_doctor.judge(KEY_FAILS, 1)
    assert ok and "api key" in line


def test_a_fail_outside_what_a_bare_machine_lacks_stops_the_cut():
    ok, line = smoke_doctor.judge(FRESH + "FAIL  routes         3 of 92 reads failed\n", 1)
    assert not ok and "routes" in line


def test_a_doctor_that_passes_without_saying_the_model_is_missing_stops_the_cut():
    text = FRESH.replace("warn  model          none chosen yet",
                         "ok    model          claude-sonnet-5-5")
    ok, line = smoke_doctor.judge(text, 0)
    assert not ok and "model is missing" in line


def test_a_fail_printed_with_exit_0_stops_the_cut():
    ok, _ = smoke_doctor.judge(KEY_FAILS, 0)
    assert not ok


def test_main_reads_the_log_and_the_exit_code(tmp_path, capsys):
    log = tmp_path / "doctor.log"
    log.write_text(FRESH)
    assert smoke_doctor.main([str(log), "0"]) == 0
    assert "ok: kranto doctor exits 0" in capsys.readouterr().out
    log.write_text("FAIL  library        unreadable\n")
    assert smoke_doctor.main([str(log), "1"]) == 1


def test_smoke_sh_hands_doctor_to_the_judge():
    smoke = (ROOT / "scripts" / "release" / "smoke.sh").read_text()
    assert 'smoke_doctor.py" "$S/doctor.log" "$code"' in smoke
