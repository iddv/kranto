"""A fresh clone has every file the tests need: no test fixture is hidden by .gitignore (a
bare ``lib/`` pattern once dropped a fixture's ``lib/count.js`` from every clone; the page's
``src/lib/`` is one more such folder)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not (ROOT / ".git").exists() or not shutil.which("git"),
                                reason="needs a git checkout")


def test_no_fixture_file_is_git_ignored():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-o", "-i", "--exclude-standard",
                        "--", "tests/page/fixtures"], capture_output=True, text=True, check=True)
    ignored = [f for f in r.stdout.splitlines()
               if "__pycache__" not in f and not f.endswith((".pyc", ".pyo"))]
    assert ignored == [], f"git ignores these fixture files, so a clone lacks them: {ignored}"


@pytest.mark.parametrize("path", ["src/kranto/page/ui/web/src/lib/nodes.json"])
def test_files_under_lib_and_build_folders_are_tracked(path):
    assert (ROOT / path).is_file(), f"{path} is gone: name a file that exists"
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", path])
    assert r.returncode == 1, f"{path} is git-ignored"


def test_the_readme_names_every_package():
    """docs/ui.md's "What is in the page's package" table names every package under
    ``src/kranto/page/``."""
    readme = (ROOT / "docs" / "ui.md").read_text()
    table = readme.split("## What is in the page's package", 1)[1].split("\n## ", 1)[0]
    packages = sorted(p.parent.name for p in (ROOT / "src" / "kranto" / "page").glob("*/__init__.py"))
    missing = [p for p in packages if f"{p}/`" not in table]
    assert packages and missing == [], f"the README's table misses {missing}"


def test_the_maps_name_every_script_and_fixture():
    """``scripts/README.md`` names every script; ``tests/page/README.md`` every fixture."""
    scripts = (ROOT / "scripts" / "README.md").read_text()
    names = sorted(str(p.relative_to(ROOT / "scripts")) for p in (ROOT / "scripts").rglob("*")
                   if p.is_file() and p.name != "README.md" and "__pycache__" not in p.parts)
    assert names and [n for n in names if f"`{n}`" not in scripts] == []
    tests = (ROOT / "tests" / "page" / "README.md").read_text().split("## Fixtures", 1)[1]
    fixtures = sorted(p.name for p in (ROOT / "tests" / "page" / "fixtures").iterdir()
                      if p.name not in ("conftest.py", "__pycache__"))
    assert fixtures and [f for f in fixtures if f"`{f}`" not in tests] == []
