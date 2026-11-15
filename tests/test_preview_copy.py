"""scripts/preview/copy_live.py: the preview's copy of live, read-only on live. On a
fake live home and loop home in a temp folder: what is left out, what is rewritten, and that the
sources are byte-for-byte what they were."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")


def copy_mod():
    spec = importlib.util.spec_from_file_location("preview_copy",
                                                  ROOT / "scripts" / "preview" / "copy_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree_hash(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def live(tmp_path, monkeypatch):
    user = tmp_path / "u"
    home, loop, tasks = user / "kranto-kb", user / "kranto-loop", user / "tasks"
    for d in (home / "data" / "secrets", home / "backups", home / "update", home / "telemetry",
              home / "cubs" / "newsletter", loop / "term" / "x", loop / "chat", loop / "projects",
              tasks / "t1"):
        d.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user))
    (home / ".env").write_text("A_KEY=" + "x" * 8 + "\n")
    (home / "data" / "secrets" / "conn.json").write_text("{}")
    (home / "backups" / "old.tar").write_text("b")
    (home / "telemetry" / "install.json").write_text("{}")
    (home / "cubs" / "newsletter" / "cub.yaml").write_text("id: newsletter\n")
    (home / "data" / "errors.jsonl").write_text("{}\n")
    db = sqlite3.connect(home / "data" / "kranto.db")
    db.execute("create table topics (name text)")
    db.execute("insert into topics values ('Padel')")
    db.commit()
    db.close()
    sqlite3.connect(loop / "loop.db").close()
    (loop / "trace.db").write_text("t")
    (loop / "term" / "x" / "session.json").write_text("{}")
    (loop / "loop.yaml").write_text(yaml.safe_dump({
        "tasks_dir": "~/tasks", "kranto": {"url": "http://127.0.0.1:8765"},
        "feed": {"ui_url": "http://127.0.0.1:8765/brb/"}}))
    (home / "kranto.yaml").write_text(yaml.safe_dump({
        "llm": {"base_url": "https://example.invalid/v1"},
        "brb": {"loop_home": "~/kranto-loop", "root": "~/tasks"},
        "notify": {"urls": ["ntfy://example.invalid/topic"], "heartbeat_every_hours": 24,
                   "base_url": "http://127.0.0.1:8765"},
        "telemetry": {"mode": "detailed"}, "update": {"auto": "idle", "channel": "nightly"},
        "import": {"path": str(home / "corpus")}}))
    return user, home, loop, tasks


def test_the_copy_leaves_secrets_out_points_at_itself_and_never_writes_live(live, tmp_path,
                                                                             capsys):
    user, home, loop, tasks = live
    before = {d: tree_hash(d) for d in (home, loop, tasks)}
    root = user / "kranto-preview"
    rc = copy_mod().main(["--src-home", str(home), "--src-loop", str(loop), "--root", str(root),
                          "--port", "8766", "--commits", json.dumps({"kranto": "a1"})])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 0 and out["databases"] == {"home/data/kranto.db": "ok", "loop/loop.db": "ok"}
    assert {d: tree_hash(d) for d in (home, loop, tasks)} == before      # live untouched
    c = root / "home"
    for gone in (".env", "data/secrets", "backups", "update", "telemetry", "data/errors.jsonl"):
        assert not (c / gone).exists(), gone
    for gone in ("trace.db", "term", "chat"):
        assert not (root / "loop" / gone).exists(), gone
    assert (c / "cubs" / "newsletter" / "cub.yaml").exists()
    assert sqlite3.connect(c / "data" / "kranto.db").execute(
        "select name from topics").fetchall() == [("Padel",)]
    assert list((root / "tasks").iterdir()) == []                         # ~/tasks is not copied
    cfg = yaml.safe_load((c / "kranto.yaml").read_text())
    assert cfg["preview"]["enabled"] is True and cfg["preview"]["commits"] == {"kranto": "a1"}
    assert cfg["brb"] == {"loop_home": str(root / "loop"), "root": str(root / "tasks")}
    assert cfg["notify"]["urls"] == [] and cfg["notify"]["heartbeat_every_hours"] == 0
    assert cfg["notify"]["base_url"] == "http://127.0.0.1:8766"
    assert cfg["telemetry"] == {"mode": "off"}
    assert cfg["update"]["auto"] == "off" and cfg["update"]["check_every_hours"] == 0
    assert cfg["import"]["path"] == str(c / "corpus")                    # absolute names too
    lp = yaml.safe_load((root / "loop" / "loop.yaml").read_text())
    assert lp["tasks_dir"] == str(root / "tasks")
    assert lp["kranto"]["url"] == "http://127.0.0.1:8766"
    assert lp["feed"]["ui_url"] == "http://127.0.0.1:8766/brb/"
    text = (c / "kranto.yaml").read_text() + (root / "loop" / "loop.yaml").read_text()
    assert str(home) not in text and "~/kranto-kb" not in text and "~/kranto-loop" not in text


def test_a_copy_inside_live_is_refused(live):
    user, home, loop, _ = live
    with pytest.raises(SystemExit):
        copy_mod().main(["--src-home", str(home), "--src-loop", str(loop),
                         "--root", str(home / "preview")])


def test_a_live_folder_left_in_the_settings_stops_the_copy(live, capsys, monkeypatch):
    user, home, loop, _ = live
    mod = copy_mod()
    monkeypatch.setattr(mod, "rewrite", lambda value, swaps: value)       # a rewrite that misses
    rc = mod.main(["--src-home", str(home), "--src-loop", str(loop),
                   "--root", str(user / "kranto-preview")])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 3 and out["error"] == "live folders still named"


def test_no_preview_script_shadows_the_standard_library():
    """Run as a script, a file's folder comes first on sys.path: scripts/preview/copy.py once
    hid the standard library's copy from acceptance.py (yaml would not import)."""
    import sys
    names = {p.stem for p in (ROOT / "scripts" / "preview").glob("*.py")}
    assert not names & set(sys.stdlib_module_names), names & set(sys.stdlib_module_names)
