"""Helpers for the cub runtime's tests: a fixture cub installed by writing its folder, its pin
and its registry row directly (what the install path does after the owner's confirm), and the
runtime that runs it."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from kranto.core import registry as core_registry
from kranto.core.cubs import files, sandbox
from kranto.core.cubs.runtime import CubRuntime
from kranto.core.manifest import grants_of, manifest_hash
from kranto.store import iso, utcnow

FIXTURES = Path(__file__).parent / "fixtures" / "cubs"
# The cubs-sandbox workflow sets this: there a sandbox that cannot start fails the tests
# instead of skipping them (the server runner's hardening forbids a fresh /proc, so the plain
# test job skips them; see .github/workflows/cubs-sandbox.yml).
REQUIRED = os.environ.get("KRANTO_CUBS_SANDBOX_REQUIRED") == "1"

needs_bwrap = pytest.mark.skipif(
    not REQUIRED and not sandbox.sandboxed(),
    reason="bubblewrap cannot start a sandbox here (no fresh /proc): the cubs-sandbox workflow "
           "runs these")


def install(rt, name: str, *, trust: str = "owner", topics: list[int] | None = None,
            folder: Path | None = None, grants: dict | None = None) -> str:
    """Install the fixture cub ``name`` (or ``folder``) as the install path would leave it."""
    src_from = folder or FIXTURES / name
    data = yaml.safe_load((src_from / "cub.yaml").read_text())
    m = core_registry.validate_cub(copy.deepcopy(data))
    cid = m["id"]
    dest = files.cub_dir(rt.cfg, cid)
    files.ensure_root(rt.cfg)
    if dest.exists():
        files.make_writable(dest)
        shutil.rmtree(dest)
    shutil.copytree(src_from, dest / "src", ignore=shutil.ignore_patterns("__pycache__"))
    tree = files.tree_hash(dest / "src")
    files.make_read_only(dest / "src")
    g = grants or grants_of(m)
    if topics is not None:
        g["reads_topics"] = topics
    now = iso(utcnow())
    rt.store.insert("cub_pins", {"cub": cid, "version": m["version"], "trust": trust,
                                 "manifest_hash": manifest_hash(data), "tree_hash": tree,
                                 "created_at": now})
    rt.store.insert("cubs", {"cub": cid, "state": "installed", "version": m["version"],
                             "trust": trust, "source_kind": "folder",
                             "source": json.dumps({"path": str(src_from)}), "sha": None,
                             "tree_hash": tree, "manifest_hash": manifest_hash(data),
                             "grants": json.dumps(g), "bears_range": m.get("kranto"),
                             "note": None, "created_at": now})
    (dest / "cub.json").write_text(json.dumps({"manifest": m}))
    if rt.cubs is not None:
        rt.cubs.load()
    return cid


def runtime(rt, **kw) -> CubRuntime:
    rt.cubs = CubRuntime(rt, **kw)
    return rt.cubs
