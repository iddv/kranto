"""CI for strangers: no job names a self-hosted runner in the tree (each reads the repository's
RUNNER variable, falling back to GitHub's own runner; ci.yml's sandbox always runs on GitHub's),
a pull request from a fork runs every job on GitHub's own runner whatever RUNNER says, no
workflow hands a secret to a pull request's code, and the required jobs are the eight.

The fork rule is belt and braces: a fork's pull request runs the fork's copy of the workflow, so
what keeps a stranger's code off a runner of the project's own is that no such runner is
registered on the public repository and outside contributors need approval. The rule here keeps
the tree's own workflow from ever sending a fork there."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RUNNER = ("${{ (inputs.hosted || (github.event_name == 'pull_request' && "
          "github.event.pull_request.head.repo.full_name != github.repository)) && "
          "'ubuntu-latest' || fromJSON(vars.RUNNER || '\"ubuntu-latest\"') }}")


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


# The contexts RUNNER reads, as Python names; anything else left in it fails the evaluation.
_CONTEXT = {
    "inputs.hosted": "hosted",
    "github.event_name": "event",
    "github.event.pull_request.head.repo.full_name": "head_repo",
    "github.repository": "repo",
    "vars.RUNNER": "runner_var",
}
OWN = '["self-hosted","kranto"]'


def runs_on(expr: str, *, event: str, head_repo: str | None = None, hosted: bool | None = None,
            runner_var: str | None = OWN) -> object:
    """Evaluate a ``runs-on`` expression as GitHub does for the operators it uses: ``&&`` and
    ``||`` give back an operand (as Python's ``and``/``or``), a missing context is null, and
    null is falsy. Only the contexts above may appear."""
    body = expr.removeprefix("${{").removesuffix("}}").strip()
    for path in sorted(_CONTEXT, key=len, reverse=True):
        body = body.replace(path, _CONTEXT[path])
    body = body.replace("&&", " and ").replace("||", " or ").replace("fromJSON", "loads")
    assert not re.search(r"\b(github|inputs|vars|secrets|env|steps|needs)\.", body), body
    names = {"hosted": hosted, "event": event, "head_repo": head_repo, "repo": "owner/kranto",
             "runner_var": runner_var, "loads": json.loads}
    return eval(body, {"__builtins__": {}}, names)  # our own pinned string, no input


def test_a_fork_never_reaches_the_projects_runner():
    """Whatever RUNNER says: a fork's pull request (or one whose fork is gone: head repo null)
    runs on GitHub's runner; a push to main and a pull request from a branch of the repository
    itself run where RUNNER says; a run by hand with ``hosted`` runs on GitHub's."""
    own = json.loads(OWN)
    assert runs_on(RUNNER, event="pull_request", head_repo="stranger/kranto") == "ubuntu-latest"
    assert runs_on(RUNNER, event="pull_request", head_repo=None) == "ubuntu-latest"
    assert runs_on(RUNNER, event="pull_request", head_repo="owner/kranto") == own
    assert runs_on(RUNNER, event="push") == own
    assert runs_on(RUNNER, event="workflow_dispatch", hosted=False) == own
    assert runs_on(RUNNER, event="workflow_dispatch", hosted=True) == "ubuntu-latest"
    # no RUNNER set: GitHub's runner for everything
    assert runs_on(RUNNER, event="push", runner_var=None) == "ubuntu-latest"
    assert runs_on(RUNNER, event="pull_request", head_repo="owner/kranto",
                   runner_var=None) == "ubuntu-latest"


def test_every_runner_expression_in_the_tree_keeps_forks_off():
    """Every job not plainly on ``ubuntu-latest`` is evaluated too, so a job written another way
    than RUNNER cannot send a fork's pull request to the variable's runner."""
    bad = []
    for wf, name, job in jobs():
        expr = str(job.get("runs-on"))
        if expr == "ubuntu-latest":
            continue
        if runs_on(expr, event="pull_request", head_repo="stranger/kranto") != "ubuntu-latest":
            bad.append(f"{wf}:{name}")
    assert bad == []


def test_no_workflow_hands_a_secret_to_a_pull_request():
    for f in sorted(WORKFLOWS.glob("*.yml")):
        text = f.read_text()
        assert "pull_request_target" not in text and "workflow_run" not in text, f.name
        assert not re.search(r"[$][{][{]\s*secrets[.]", text), f.name


REQUIRED = {"test", "fast", "slow", "browser", "frontend", "lint", "gitleaks", "sandbox"}


def test_the_required_jobs_are_the_eight():
    """ci.yml's jobs: the eight a merge requires (guards.py's REQUIRED), and ``install`` (the
    release installed as a stranger installs it), not required yet."""
    import importlib.util
    names = {name for wf, name, _ in jobs() if wf == "ci.yml"}
    assert names == REQUIRED | {"install"}
    path = WORKFLOWS.parents[1] / "scripts" / "release" / "guards.py"
    spec = importlib.util.spec_from_file_location("ci_forks_guards", path)
    guards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guards)
    assert set(guards.REQUIRED) == REQUIRED
