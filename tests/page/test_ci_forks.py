"""CI for strangers: no job names a self-hosted runner in the tree (each reads the repository's
RUNNER variable, falling back to GitHub's own runner), no workflow hands a secret to a pull
request's code, and the required jobs are the eight."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RUNNER = '${{ inputs.hosted && \'ubuntu-latest\' || fromJSON(vars.RUNNER || \'"ubuntu-latest"\') }}'


def jobs():
    for f in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(f.read_text())
        for name, job in (doc.get("jobs") or {}).items():
            yield f.name, name, job


def test_every_job_runs_where_the_runner_variable_says():
    """All but ci.yml's ``sandbox``, which always runs on GitHub's own runner (it needs a fresh
    /proc inside bubblewrap)."""
    bad = [f"{wf}:{name}: {job.get('runs-on')}" for wf, name, job in jobs()
           if job.get("runs-on") != ("ubuntu-latest" if (wf, name) == ("ci.yml", "sandbox")
                                     else RUNNER)]
    assert bad == []


def test_no_workflow_hands_a_secret_to_a_pull_request():
    for f in sorted(WORKFLOWS.glob("*.yml")):
        text = f.read_text()
        assert "pull_request_target" not in text and "workflow_run" not in text, f.name
        assert not re.search(r"[$][{][{]\s*secrets[.]", text), f.name


def test_the_required_jobs_are_the_eight():
    names = {name for wf, name, _ in jobs() if wf == "ci.yml"}
    assert names == {"test", "fast", "slow", "browser", "frontend", "lint", "gitleaks", "sandbox"}
