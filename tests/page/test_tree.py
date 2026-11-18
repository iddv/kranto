"""The factory is gone from the tree (the import test, items 1-4 and 6 for the page;
item 5 is the frontend's vitest): no removed package or module is left under ``the page/``,
nothing imports one (imports inside functions and ``importlib.import_module("...")`` literals
too), every name ``kranto.page.host_api`` offers resolves, the page's server, the terminal and
kranto mcp load none of them, and the host API's version says the factory left."""
import ast
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "kranto" / "page"

# every top-level package and module of the page's that left with the factory
REMOVED = [
    "capabilities", "chat", "costs", "custom_prompts", "den", "errors", "evals", "events",
    "extensions", "github_app", "github_cli", "github_repos", "github_user", "harness", "lab",
    "lessons", "llm", "loop", "maintain", "mcp_servers", "models", "objects", "owner", "plugins",
    "policy", "progress", "projects", "registry", "resources", "rules", "stored", "tasks", "v5",
    "websearch",
]
# the test helpers that went with them
REMOVED_TESTS = ["tests.page.loop_common", "tests.page.functional", "tests.page.lab"]
GONE = [f"kranto.page.{n}" for n in REMOVED] + REMOVED_TESTS
# host_api names that need the mcp extra
MCP_NAMES = {"mcp_available", "mcp_main", "term_mcp_main"}


def _gone(name: str) -> bool:
    return any(name == g or name.startswith(g + ".") for g in GONE)


def test_no_removed_package_or_module_is_left():
    left = [n for n in REMOVED if (PKG / n).exists() or (PKG / f"{n}.py").exists()]
    assert left == []
    assert not (ROOT / "tests" / "functional").exists() and not (ROOT / "tests" / "lab").exists()
    assert not (ROOT / "tests" / "loop_common.py").exists()


def _module_of(path: Path) -> list[str]:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def _imports(path: Path) -> list[tuple[int, str]]:
    """Every module name ``path`` imports, relative ones made absolute, with its line."""
    tree = ast.parse(path.read_text(), str(path))
    here = _module_of(path)
    pkg = here if path.name == "__init__.py" else here[:-1]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[:len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                mod = ".".join([*base, *([node.module] if node.module else [])])
            else:
                mod = node.module or ""
            out.append((node.lineno, mod))
            out += [(node.lineno, f"{mod}.{a.name}") for a in node.names]
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "import_module":
                out.append((node.lineno, node.args[0].value))
    return out


def test_nothing_imports_a_removed_name():
    files = [p for d in ("src/kranto/page", "tests/page", "scripts") for p in sorted((ROOT / d).rglob("*.py"))
             if "__pycache__" not in p.parts and "node_modules" not in p.parts
             and "fixtures" not in p.relative_to(ROOT).parts]
    assert len(files) > 50
    hits = [f"{p.relative_to(ROOT)}:{n}: {m}" for p in files for n, m in _imports(p) if _gone(m)]
    assert hits == [], "imports of what the factory took with it:\n" + "\n".join(hits)


def test_every_host_api_name_resolves():
    from kranto.page import host_api
    have_mcp = importlib.util.find_spec("mcp") is not None
    for name, (module, attr) in host_api._NAMES.items():
        if name in MCP_NAMES and not have_mcp:
            continue
        assert not _gone(module), name
        assert getattr(importlib.import_module(module), attr) is not None, name
        assert getattr(host_api, name) is getattr(importlib.import_module(module), attr), name


def test_the_server_the_terminal_and_kranto_mcp_load_nothing_removed():
    mods = ["kranto.page.ui.api", "kranto.page.term.service"]
    if importlib.util.find_spec("mcp") is not None:
        mods.append("kranto.page.mcp.server")
    code = ("import importlib, json, sys\n"
            f"for m in {mods!r}: importlib.import_module(m)\n"
            "print(json.dumps(sorted(sys.modules)))")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    loaded = json.loads(r.stdout.strip().splitlines()[-1])
    assert [m for m in loaded if _gone(m)] == []


def test_the_host_api_version_says_the_factory_left():
    from kranto.page import host_api
    assert host_api.HOST_API_VERSION == 2


@pytest.mark.parametrize("name", ["x.loop", "kranto.page.loopy", "kranto.page.ui.loop"])
def test_only_the_removed_names_count(name):
    assert not _gone(name)
    assert _gone("kranto.page.loop.daemon") and _gone("kranto.page.v5") and _gone("tests.page.loop_common")
