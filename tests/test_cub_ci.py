"""The cub security plan gates every merge: ci.yml's `sandbox` job, required on every pull
request, fails where bubblewrap cannot start a sandbox (never a quiet skip), then runs the
plan with KRANTO_CUBS_SANDBOX_REQUIRED (a sandbox that cannot start is a failure) and the
console's box with KRANTO_BWRAP_REQUIRED."""
from __future__ import annotations

from pathlib import Path

import yaml

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def sandbox_steps() -> list[dict]:
    return yaml.safe_load(CI.read_text())["jobs"]["sandbox"]["steps"]


def test_the_sandbox_job_fails_where_bubblewrap_cannot_start():
    steps = sandbox_steps()
    probe = next(s for s in steps if "--proc /proc" in s.get("run", ""))
    assert "continue-on-error" not in probe and "if" not in probe
    assert "|| true" not in probe["run"]


def test_the_plan_runs_with_the_sandbox_required():
    runs = [s.get("run", "") for s in steps_after_probe()]
    plan = next(r for r in runs if "tests/test_cub_security.py" in r)
    assert "KRANTO_CUBS_SANDBOX_REQUIRED=1" in plan and "-rs" in plan
    assert "tests/test_cub_runtime.py" in plan
    box = next(r for r in runs if "tests/page/test_term_sandbox.py" in r)
    assert "KRANTO_BWRAP_REQUIRED=1" in box


def test_no_step_of_the_job_skips_quietly():
    """Only the step that installs bubblewrap on GitHub's own runner has a condition."""
    conditional = [s for s in sandbox_steps() if "if" in s]
    assert [s["if"] for s in conditional] == ["runner.environment == 'github-hosted'"]


def steps_after_probe() -> list[dict]:
    steps = sandbox_steps()
    i = next(n for n, s in enumerate(steps) if "--proc /proc" in s.get("run", ""))
    return steps[i + 1:]


def test_the_plan_runs_again_on_a_uv_managed_python_under_the_home():
    """A machine without a system Python 3.12 gets one from uv, under the home folder: the
    plan runs there too (a cub must not see the home, or a path naming it), and the step fails
    if the interpreter is not the managed one."""
    steps = steps_after_probe()
    leg = next(s for s in steps if "tests/test_cub_security.py" in s.get("run", "")
               and s.get("env", {}).get("UV_PYTHON_PREFERENCE") == "only-managed")
    assert "if" not in leg and "continue-on-error" not in leg
    run = leg["run"]
    assert "uv python install 3.12" in run and "KRANTO_CUBS_SANDBOX_REQUIRED=1" in run
    assert 'sys.base_prefix.startswith("/home/")' in run
    assert "-k" not in run or "test_s1_" in run         # S1 always among the rows it runs
    assert "|| true" not in run


def test_the_console_box_is_checked_under_the_images_own_apparmor_before_the_lift():
    step = next(s for s in sandbox_steps() if "apt-get install" in s.get("run", ""))
    run = step["run"]
    first = run.index("tests/page/test_term_apparmor.py")
    assert first < run.index("sysctl -w") < run.index("apparmor_parser -R")
