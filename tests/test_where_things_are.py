"""CONTRIBUTING's "Where things are" stays true: it names every folder at the root and every
package under src/kranto/, and every module it names exists."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECTION = (ROOT / "CONTRIBUTING.md").read_text().split("## Where things are", 1)[1] \
    .split("\n## ", 1)[0]


def test_every_root_folder_is_named():
    try:
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True,
                                 text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout")
    folders = sorted({f.split("/")[0] for f in tracked if "/" in f and not f.startswith(".")})
    assert folders and [f for f in folders if f"`{f}/" not in SECTION] == []


def test_every_package_is_named():
    packages = sorted(p.parent.name for p in (ROOT / "src" / "kranto").glob("*/__init__.py"))
    assert packages and [p for p in packages if f"`{p}/`" not in SECTION] == []


def test_the_tests_map_names_every_fixture():
    text = (ROOT / "tests" / "README.md").read_text().split("## Fixtures", 1)[1]
    fixtures = sorted(p.name for p in (ROOT / "tests" / "fixtures").iterdir()
                      if p.name != "__pycache__")
    assert fixtures and [f for f in fixtures if f"`{f}`" not in text] == []


def test_every_module_it_names_exists():
    flat = SECTION.split("The flat modules", 1)[1]
    named = re.findall(r"`([a-z_]+)`", flat)
    assert named and [m for m in named
                      if not (ROOT / "src" / "kranto" / f"{m}.py").is_file()] == []
