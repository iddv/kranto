"""CI for strangers: the workflow runs on `pull_request` and pushes to main and release/X.Y
only (never `pull_request_target`), its token reads and nothing more, and no job names a
runner label in the tree: each runs where the repository's RUNNER variable says, or on
GitHub's own runner (ci.yml's `sandbox` always there)."""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def docs():
    for f in sorted(WORKFLOWS.glob("*.yml")):
        yield f.name, yaml.safe_load(f.read_text())


def test_the_triggers_and_the_token():
    for name, doc in docs():
        triggers = doc.get(True) or doc.get("on") or {}       # YAML reads `on:` as True
        assert set(triggers) <= {"pull_request", "push", "workflow_dispatch", "schedule"}, name
        assert doc.get("permissions") == {"contents": "read"}, name


def test_a_stable_lines_merge_is_checked():
    """cut_local.sh --line stable cuts only from a release/X.Y commit whose own checks are
    green, so a merge into release/X.Y must start the same run a merge into main does."""
    doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
    push = (doc.get(True) or doc.get("on"))["push"]
    assert push["branches"] == ["main", "release/**"]


def test_no_job_names_a_runner_label():
    for name, doc in docs():
        for job, body in (doc.get("jobs") or {}).items():
            runs = str(body.get("runs-on"))
            if (name, job) == ("ci.yml", "sandbox"):      # always GitHub's own runner
                assert runs == "ubuntu-latest", (name, job)
                continue
            assert "vars.RUNNER" in runs and "self-hosted" not in runs, (name, job)
