"""A cub's update the owner presses, and the ones it applies by itself.

Live had three identical update jobs of the newsletter staged before each press
applied one and the page offered the next, "Update to 1.2.0…" again, so the button looked
dead. A job that offers nothing (its version installed, its staged folder gone) is cancelled
and never offered. The daily ``cubs.updates`` applies by itself an update that adds no
permission and no send and runs on this Kranto (``cubs.auto_update``, on by default); any other
waits for one press, in Needs you. Folders only: nothing here touches the network.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import replace

import pytest

from kranto import activity
from kranto.activity import read as activity_read
from kranto.core.cubs import files, install, registry, updates, views
from kranto.core.cubs import settings as cs

from .test_cub_install import added, home, make_cub, manifest  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


def _staged_twice_more(home, monkeypatch) -> list[str]:  # noqa: F811
    """Three jobs staging the same files, as live had them before."""
    with monkeypatch.context() as m:
        m.setattr(install, "awaiting_updates", lambda *a: [])
        ids = [install.start(home, kind="update", cid="hello", background=False)["id"]
               for _ in range(3)]
    assert len(set(ids)) == 3
    return ids


def test_pressing_update_once_leaves_nothing_to_press_however_many_jobs_staged_it(
        home, tmp_path, monkeypatch):  # noqa: F811
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.2.0"))
    first, second, third = _staged_twice_more(home, monkeypatch)
    # the page offers one of them, newest first, as before
    assert views.row(home, "hello")["update"]["job"] == third
    install.apply_update(home, third, "hello", door="ui")
    assert registry.latest(home.store, "hello")["version"] == "1.2.0"
    # the press is the last: the others are cancelled, saying why, and their folders go
    assert views.row(home, "hello")["update"] is None
    for j in (first, second):
        got = install.job(home.store, home.cfg, j)
        assert got["state"] == "cancelled" and got["error"] == "1.2.0 is installed"
        assert not (files.root(home.cfg) / ".staged" / j).exists()
    assert install.awaiting_updates(home.store, home.cfg, "hello") == []
    assert views.row(home, "hello")["updated"]["version"] == "1.2.0"
    assert views.row(home, "hello")["updated"]["by"] == "you"


def test_an_update_an_older_kranto_applied_still_says_its_version(
        home, tmp_path, monkeypatch):  # noqa: F811
    """Live's newsletter was updated by 0.5.15, whose installed step kept no version: its page
    said nothing. The registry row its pin wrote says it."""
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.2.0"))
    j = install.start(home, kind="update", cid="hello", background=False)
    step = install._step
    with monkeypatch.context() as m:                 # as 0.5.15 wrote it: no detail
        m.setattr(install, "_step", lambda store, job_id, kind, cid, s, detail=None: step(
            store, job_id, kind, cid, s, None if s == "installed" else detail))
        install.apply_update(home, j["id"], "hello", door="ui")
    assert home.store.query_one("SELECT detail FROM cub_installs WHERE job_id = ? AND step = "
                                "'installed'", (j["id"],))["detail"] is None
    got = views.row(home, "hello")["updated"]
    assert (got["version"], got["by"]) == ("1.2.0", "you")


def test_jobs_a_crash_or_an_older_kranto_left_are_cancelled_at_the_start(
        home, tmp_path, monkeypatch):  # noqa: F811
    """What live has now: the version installed by an earlier job, one more job still awaiting
    the confirm with the same files; and one whose staged folder went (cubs.gc)."""
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.2.0"))
    a, b, c = _staged_twice_more(home, monkeypatch)
    # an older Kranto applied ``a`` and left ``b`` and ``c`` waiting
    with monkeypatch.context() as m:
        m.setattr(install, "cancel_stale", lambda *a, **k: [])
        install.apply_update(home, a, "hello", door="ui")
    assert [j for j, _ in install.awaiting_ids(home.store, "hello")] == [c, b]
    assert views.row(home, "hello")["update"] is None       # never offered meanwhile
    said = install.recover(home)
    assert f"{c}: offers nothing now" in said and f"{b}: offers nothing now" in said
    assert install.awaiting_ids(home.store, "hello") == []
    # a newer update whose staged folder is gone is not offered either
    (src / "cub.yaml").write_text(manifest(version="1.3.0"))
    j = install.start(home, kind="update", cid="hello", background=False)
    staged = files.root(home.cfg) / ".staged" / j["id"]
    files.make_writable(staged)
    shutil.rmtree(staged)
    assert views.row(home, "hello")["update"] is None
    install.recover(home)
    assert install.job(home.store, home.cfg, j["id"])["error"] == \
        "its staged folder is gone: look for the update again"


def test_the_daily_sweep_keeps_an_update_that_waits_for_the_press(home, tmp_path):  # noqa: F811
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.1.0", requests="[book.propose]"))
    j = install.start(home, kind="update", cid="hello", background=False)
    staged = files.root(home.cfg) / ".staged" / j["id"]
    old = time.time() - 3 * 86400
    os.utime(staged, (old, old))
    home.cubs.gc()
    assert staged.exists() and views.row(home, "hello")["update"]["job"] == j["id"]


def test_an_update_that_adds_nothing_applies_by_itself_and_says_so(home, tmp_path):  # noqa: F811
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    added(home, src)
    cs.write(home.cfg, "cubs.hello.live", ["book.propose"])
    assert cs.values(home.cfg)["cubs.auto_update"] is True            # the default now
    (src / "cub.yaml").write_text(manifest(version="1.2.1", requests="[book.propose]"))
    with activity.run(home.store, updates.KIND):
        out = updates.run(home)
    assert out["line"] == "Hello updated to 1.2.1 by itself"
    assert registry.latest(home.store, "hello")["version"] == "1.2.1"
    # trust and its live kinds are as they were: nothing grew
    assert registry.latest(home.store, "hello")["trust"] == "owner"
    assert cs.live_kinds(home.cfg, "hello") == ["book.propose"]
    assert views.row(home, "hello")["updated"] == {
        "version": "1.2.1", "at": views.row(home, "hello")["updated"]["at"], "by": "itself"}
    activity.flush(5)
    read = activity_read.Reader(home.store).read()
    titles = [r["title"] for r in read["recent"]]
    assert "Hello updated to 1.2.1 by itself" in titles
    assert read["waiting"] == []
    # the next day: up to date, nothing applied twice
    assert updates.run(home)["line"] == "every cub is up to date"


def test_an_update_that_adds_a_send_or_a_permission_waits_in_needs_you(
        home, tmp_path):  # noqa: F811
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.2.0", requests="[book.propose]"))
    out = updates.run(home)
    assert out["line"] == "Hello 1.2.0 asks to send something new"
    assert registry.latest(home.store, "hello")["version"] == "1.0.0"
    up = views.row(home, "hello")["update"]
    assert up["version"] == "1.2.0" and up["why"] == "asks to send something new"
    activity.flush(5)
    [w] = activity_read.Reader(home.store).read()["waiting"]
    assert w["words"] == "Hello 1.2.0 asks to send something new"
    assert w["needs"] == {"verb": "Review", "href": "cub/hello?sel=settings"}
    assert w["subject"] == {"kind": "cub", "id": "hello", "name": "Hello"}
    # a second day says it once; the owner's press ends the wait
    updates.run(home)
    activity.flush(5)
    assert len(activity_read.Reader(home.store).read()["waiting"]) == 1
    install.apply_update(home, up["job"], "hello", door="ui")
    assert activity_read.Reader(home.store).read()["waiting"] == []
    # one more permission, not a send
    (src / "cub.yaml").write_text(manifest(version="1.3.0", requests="[book.propose]",
                                           reads="[topics, briefs]"))
    assert updates.run(home)["line"] == "Hello 1.3.0 asks for one more permission"


def test_an_update_for_a_newer_kranto_or_with_auto_update_off_waits(home, tmp_path):  # noqa: F811
    src = make_cub(tmp_path / "hello")
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.1.0", kranto='">=99.0"'))
    assert updates.run(home)["line"] == "Hello 1.1.0 needs a newer Kranto (>=99.0)"
    (src / "cub.yaml").write_text(manifest(version="1.2.0"))
    home.cfg = replace(home.cfg, cubs=cs.parse({"auto_update": False}))
    assert updates.run(home)["line"] == \
        "Hello 1.2.0 waits for your approval: cubs.auto_update is off"
    assert registry.latest(home.store, "hello")["version"] == "1.0.0"
    home.cfg = replace(home.cfg, cubs=cs.parse({"auto_update": False, "check_updates": False}))
    assert updates.run(home) == {"why": "looking for the cubs' updates is off"}


def test_a_failed_look_is_said_and_the_others_go_on(home, tmp_path):  # noqa: F811
    added(home, make_cub(tmp_path / "hello"))
    other = make_cub(tmp_path / "other", manifest("other"))
    added(home, other)
    (tmp_path / "hello" / "main.py").write_text("# changed, the version not raised\n")
    (other / "cub.yaml").write_text(manifest("other", version="1.0.1"))
    out = updates.run(home)
    states = {o["cub"]: o["state"] for o in out["cubs"]}
    assert states == {"hello": "failed", "other": "updated"}
    assert "raise the version" in json.dumps(out["cubs"][0]["why"])


def test_a_cub_whose_folder_is_gone_stays_as_installed_and_fails_nothing(home, tmp_path):  # noqa: F811
    """A reference cub a release no longer ships (examplecom left Kranto's package for bearcubs),
    or a
    folder the owner deleted: the cub keeps running as installed; the daily look says nothing
    and is not degraded."""
    added(home, make_cub(tmp_path / "hello"))
    shutil.rmtree(tmp_path / "hello")
    with activity.run(home.store, updates.KIND):
        out = updates.run(home)
    assert out["line"] == "every cub is up to date"
    [o] = out["cubs"]
    assert o["state"] == "kept" and "is gone" in o["why"]
    run = home.store.query_one("SELECT status FROM runs WHERE kind = ? ORDER BY rowid DESC "
                               "LIMIT 1", (updates.KIND,))
    assert run["status"] == "ok"
    assert registry.latest(home.store, "hello")["state"] == "installed"


def cli_args(*argv: str):
    import argparse

    from kranto.core.cubs import cli
    p = argparse.ArgumentParser(prog="kranto")
    cli.add_parser(p.add_subparsers(dest="cmd", required=True))
    return p.parse_args(["cub", *argv])


def test_a_gone_source_is_said_once_with_the_command_that_points_it_elsewhere(home, tmp_path):  # noqa: F811
    """live's examplecom recorded a folder that no longer exists; its daily look said
    ok and it would never update, and nothing said so. Now its page, ``kranto cub inspect`` and
    Needs you (once) say it, with ``kranto cub source`` to point it elsewhere."""
    from io import StringIO

    from kranto.core.cubs import cli
    added(home, make_cub(tmp_path / "hello"))
    shutil.rmtree(tmp_path / "hello")
    gone = views.row(home, "hello")["source_gone"]
    assert gone["path"] == str((tmp_path / "hello").resolve())
    assert gone["fix"] == "kranto cub source hello <its folder or git URL>"
    assert gone["words"].startswith("Its source folder is gone (")
    assert "it gets no updates" in gone["words"]
    out = StringIO()
    assert cli.run(cli_args("inspect", "hello"), home.cfg.root, out=out, rt=home) == 0
    assert "source gone: Its source folder is gone" in out.getvalue()
    # Needs you, once: a waiting run of its own, not one a day
    for _ in range(3):
        with activity.run(home.store, updates.KIND):
            updates.run(home)
    activity.flush()
    waits = [w for w in activity_read.Reader(home.store).read()["waiting"]
             if w["kind"] == updates.GONE]
    assert len(waits) == 1 and waits[0]["words"].endswith("source is gone: it gets no updates")
    # Kranto's own example cubs (examplecom, 0.6.0.dev2 and before): the reinstall line names
    # bearcubs
    ours = updates.gone_words("examplecom", "/x/site-packages/kranto/cubs/examples/examplecom")
    assert ours["fix"] == ("kranto cub source examplecom https://github.com/octo-owner/bearcubs"
                           "#subdirectory=cubs/examplecom")


def test_kranto_cub_source_rewrites_the_source_only(home, tmp_path):  # noqa: F811
    """``kranto cub source`` changes ``cubs.source`` and ``source_kind`` (a new row) and nothing
    else: the version, the pin, the grants, the state and the installed files stay. Readers of
    ``cubs.source`` (``stored.cubs.CubSource``): updates' folder_gone reads ``path`` (a git
    source has none: not gone), install's update reads ``url``/``subdirectory`` for git and
    ``path`` for a folder, views and the CLI print them."""
    from io import StringIO

    from kranto.core.cubs import cli
    added(home, make_cub(tmp_path / "hello"))
    before = registry.latest(home.store, "hello")
    shutil.rmtree(tmp_path / "hello")
    moved = make_cub(tmp_path / "moved" / "hello")
    out = StringIO()
    assert cli.run(cli_args("source", "hello", str(moved)), home.cfg.root, out=out,
                   rt=home) == 0
    after = registry.latest(home.store, "hello")
    assert after["id"] != before["id"]                                 # a new row, appended
    same = ("version", "sha", "tree_hash", "manifest_hash", "grants", "state", "trust")
    assert {k: after[k] for k in same} == {k: before[k] for k in same}
    assert json.loads(after["source"]) == {"path": str(moved.resolve())}
    assert views.row(home, "hello")["source_gone"] is None
    # a git URL with a subdirectory, as bearcubs holds them
    install.set_source(home, "hello", "https://example.invalid/cubs.git#subdirectory=cubs/hello")
    row = registry.latest(home.store, "hello")
    assert row["source_kind"] == "git"
    assert json.loads(row["source"]) == {"url": "https://example.invalid/cubs.git",
                                         "subdirectory": "cubs/hello"}
    assert views.row(home, "hello")["source_gone"] is None
    with pytest.raises(install.InstallError):
        install.set_source(home, "hello", str(tmp_path / "nowhere"))
    with pytest.raises(install.InstallError):
        install.set_source(home, "nobody", str(moved))
