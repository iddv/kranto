"""The cub security plan runs on every change: ci.yml's sandbox job has no path list (the old
gate ran only for the paths it listed, and two changes to what every cub reads merged without
it). The runtime's own imports are still found, for whoever reads what the cubs depend on."""
from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "kranto"
RUNTIME = [SRC / "core" / "cubs" / "runtime.py", SRC / "core" / "cubs" / "host.py"]
# what serves the cubs to the page and the page's presses to them
SERVED = ["src/kranto/web/cubs_api.py", "src/kranto/web/features_api.py",
          "src/kranto/core/home.py", "tests/test_home.py",
          "tests/test_action_when.py"]


def imported(module: Path) -> set[str]:
    """The repo paths of the modules ``module`` imports from kranto.core and kranto.web."""
    pkg = module.parent.relative_to(SRC.parent).parts       # ("kranto", "core", "cubs")
    out = set()
    for node in ast.walk(ast.parse(module.read_text())):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = list(pkg[:len(pkg) - node.level + 1]) if node.level else []
        parts = base + (node.module.split(".") if node.module else [])
        names = [parts + [a.name] for a in node.names] if not node.module else [parts]
        for p in names:
            if p[:2] not in (["kranto", "core"], ["kranto", "web"]):
                continue
            f = SRC.parent.joinpath(*p)
            path = f.with_suffix(".py") if f.with_suffix(".py").is_file() else f / "__init__.py"
            if path.is_file():
                out.add("src/" + str(path.relative_to(SRC.parent)))
    return out


def test_the_runtime_imports_are_found():
    found = imported(RUNTIME[0]) | imported(RUNTIME[1])
    for must in ("src/kranto/core/api.py", "src/kranto/core/manifest.py",
                 "src/kranto/core/tickets.py", "src/kranto/core/cubs/sandbox.py"):
        assert must in found


def test_the_sandbox_job_runs_on_every_change():
    """One workflow: its sandbox job has no path list, so every pull request and every push to
    main runs the cub security plan, whatever the change touches."""
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    triggers = ci.get(True) or ci.get("on")
    assert "paths" not in (triggers.get("pull_request") or {})
    assert "paths" not in (triggers.get("push") or {})
    plan = " ".join(s.get("run", "") for s in ci["jobs"]["sandbox"]["steps"])
    for f in ("tests/test_cub_security.py", "tests/test_cub_runtime.py"):
        assert f in plan
