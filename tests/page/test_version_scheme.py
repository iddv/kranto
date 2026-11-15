"""A checkout past a nightly's tag still has a version (setuptools-scm refuses to count past
vX.Y.0-devN: after v0.6.0-dev1, no clone with the tags could uv sync)."""

from __future__ import annotations

import shlex
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_version_describes_from_the_last_tag_that_is_not_a_nightly(tmp_path):
    raw = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["version"][
        "raw-options"]
    describe = shlex.split(raw["scm"]["git"]["describe_command"])

    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t",
                        "-c", "user.email=t@example.invalid", *a],
                       capture_output=True, text=True, check=True)

    git("init", "-q")
    for tag in ("v0.5.29", "v0.6.0-dev1", None):
        git("commit", "-q", "--allow-empty", "-m", tag or "after")
        if tag:
            git("tag", tag)
    assert subprocess.run(describe, cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.startswith("v0.5.29-2-g")
