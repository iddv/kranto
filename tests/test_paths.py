"""paths.py: the homes and their layout, the same file in the server and the page.
The resolvers' orders are pinned in tests/test_kranto.py (kranto_home) and in the page's
tests/test_paths.py."""
from pathlib import Path

import pytest

from kranto import launcher, paths


def test_paths_py_is_the_same_in_both_repos():
    bb = pytest.importorskip("kranto.page.paths")
    if not hasattr(bb, "__file__"):
        pytest.skip("the page is a stand-in here")
    assert Path(bb.__file__).read_bytes() == Path(paths.__file__).read_bytes()


def test_the_launcher_finds_homes_through_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("KRANTO_LOOP_HOME", raising=False)
    assert paths.loop_home(str(tmp_path / "l")) == paths.loop_home(tmp_path / "l")
    monkeypatch.setenv("KRANTO_LOOP_HOME", str(tmp_path / "env"))
    assert paths.loop_home() == (tmp_path / "env").resolve()
    assert launcher.pointer_path(tmp_path) == paths.pointer_path(tmp_path, launcher.UNIT)
    assert launcher.unit_env('Environment="KRANTO_HOME=%h/kb"\n', tmp_path) == \
        {"KRANTO_HOME": f"{tmp_path}/kb"}


def test_the_loop_homes_files_are_named_by_the_layout(tmp_path):
    lay = paths.LoopLayout(tmp_path)
    assert [p.name for p in (lay.lock, lay.pid, lay.stop, lay.pause, lay.db, lay.settings)] == \
        ["daemon.lock", "daemon.pid", "STOP", "PAUSE", "loop.db", "loop.yaml"]


def test_no_module_joins_the_loop_homes_names_by_hand():
    """The loop home's entries are named in paths.py only (S-8 step 2)."""
    import re
    names = r"loop\.yaml|loop\.db|daemon\.(?:pid|lock|log)|actions\.jsonl|PAUSE|STOP"
    join = re.compile(rf"/\s*[\"'](?:{names})[\"']")
    root = Path(paths.__file__).resolve().parent
    bad = [f"{f.relative_to(root)}:{n}: {line.strip()}"
           for f in sorted(root.rglob("*.py")) if f.name != "paths.py"
           for n, line in enumerate(f.read_text().splitlines(), 1) if join.search(line)]
    assert not bad, "join through paths.py:\n" + "\n".join(bad)
