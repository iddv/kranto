"""Installing, updating, stopping and removing cubs, and the security
plan's rows that are about what gets installed (S17 to S22) and who may change it (S27).

Folders are made by the test; git sources are local repositories (``file://``): nothing here
touches the network.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from bears_cub.schema import HOST_RANGE
from kranto import config as config_mod
from kranto.core import events, tickets
from kranto.core.cubs import cli as cubs_cli
from kranto.core.cubs import files, install, registry, views
from kranto.core.cubs import settings as cs
from kranto.core.cubs.runtime import CubUnavailable
from kranto.web.app import create_app

from .conftest import web_client
from .cubhelp import needs_bwrap, runtime
from .test_web import rt  # noqa: F401 - fixture

UI = {"origin": "ui", "via": "cookie"}
BOOK = {"legs": "AMS-LIS", "total": 120.0, "currency": "EUR", "links": "the airline"}
MAIN = '''"""A cub for the install tests."""
from bears_cub import Cub

cub = Cub()


@cub.job("tick")
def tick(ctx):
    return {"line": "ticked"}
'''


def manifest(cid: str = "hello", version: str = "1.0.0", **extra) -> str:
    keys = {"schema": "1", "api": "cub/1", "id": cid, "version": version,
            "title": cid.title(), "says": "Says hello, for the install tests.",
            "reads": "[topics]",
            "jobs": f"[{{kind: {cid}.tick, method: tick, every_hours: 24}}]",
            "storage": "own", **extra}
    if "kranto" in keys:                 # the host range: the manifest's key keeps its name
        keys[HOST_RANGE] = keys.pop("kranto")
    return "".join(f"{k}: {v}\n" for k, v in keys.items())


@pytest.fixture(autouse=True)
def _cub_shop_on(monkeypatch):
    """These tests are of the cub shop: on (cubs.developer;.2 has it off by
    default, tested in test_hide_off.py)."""
    monkeypatch.setattr(cs, "developer", lambda cfg: True)


def make_cub(where: Path, text: str | None = None, main: str = MAIN) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    (where / "cub.yaml").write_text(text or manifest())
    (where / "main.py").write_text(main)
    return where


@pytest.fixture
def home(rt, tmp_path, monkeypatch):  # noqa: F811
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    r = runtime(rt)
    r.load()
    yield rt
    r.stop_all("host")


def added(rt, folder: Path, **kw) -> dict:  # noqa: F811
    j = install.start(rt, str(folder), background=False)
    assert j["state"] == "awaiting_confirm", j
    return install.install(rt, j["id"], door="cli", **kw)


# -- add ------------------------------------------------------------------------------------------


def test_a_folder_installs_in_nine_steps_and_is_pinned(home, tmp_path):
    src = make_cub(tmp_path / "hello")
    j = install.start(home, str(src), background=False)
    assert j["state"] == "awaiting_confirm" and j["needs"] == "house"
    c = j["cub"]
    assert (c["id"], c["version"], c["trust"]) == ("hello", "1.0.0", "owner")
    words = dict(c["words"])
    assert words["Trust"].startswith("Yours") and "It cannot" in words
    assert c["inventory"]["files"] == 2 and c["inventory"]["findings"] == []
    row = install.install(home, j["id"], door="cli")
    steps = [r["step"] for r in home.store.query(
        "SELECT step FROM cub_installs WHERE job_id = ? ORDER BY id", (j["id"],))]
    assert steps == list(install.STEPS)
    assert row["state"] == "installed" and row["source_kind"] == "folder"
    pin = home.store.query_one("SELECT * FROM cub_pins WHERE cub = 'hello'")
    assert pin["tree_hash"] == row["tree_hash"] == files.tree_hash(files.cub_dir(
        home.cfg, "hello") / "src")
    assert oct(os.stat(files.cub_dir(home.cfg, "hello") / "src" / "main.py").st_mode)[-3:] \
        == "400"
    assert not (files.root(home.cfg) / ".staged" / j["id"]).exists()
    assert json.loads((files.cub_dir(home.cfg, "hello") / "cub.json").read_text())[
        "inventory"]["files"] == 2
    assert [e["payload"] for e in events.read(home.store, kinds=["cub.installed"])] == \
        [{"cub": "hello", "version": "1.0.0"}]
    assert "hello" in home.cubs.installed and home.cubs.mode_word("hello") == "practice"
    listed = views.listing(home)["cubs"]
    assert [(x["id"], x["pinned"], x["tree_ok"]) for x in listed] == [("hello", True, True)]


def test_an_installed_id_is_not_added_twice_and_a_cancel_leaves_nothing(home, tmp_path):
    added(home, make_cub(tmp_path / "hello"))
    j = install.start(home, str(tmp_path / "hello"), background=False)
    assert j["state"] == "failed" and "installed already" in j["error"]
    other = make_cub(tmp_path / "other", manifest("other"))
    j = install.start(home, str(other), background=False)
    assert install.cancel(home.store, home.cfg, j["id"])["state"] == "cancelled"
    assert not (files.root(home.cfg) / ".staged" / j["id"]).exists()
    with pytest.raises(install.InstallError, match="cancelled"):
        install.install(home, j["id"], door="cli")
    assert registry.latest(home.store, "other") is None


def test_sources_kranto_does_not_take(home, tmp_path):
    with pytest.raises(install.InstallError, match="index opens at Kranto 0.7"):
        install.parse_source("io.github.someone/cub")
    for url in ("http://example.com/x.git", "git://example.com/x.git"):
        with pytest.raises(install.InstallError, match="never http://"):
            install.parse_source(url)
    with pytest.raises(install.InstallError, match="not a folder here"):
        install.parse_source(str(tmp_path / "missing"))
    with pytest.raises(install.InstallError, match="--ref is for a git URL"):
        install.parse_source(str(tmp_path), "v1")
    for ref in ("-utouch", "--upload-pack=x", "a..b", "x y"):   # never an option to git
        with pytest.raises(install.InstallError, match="--ref is a tag"):
            install.parse_source("https://example.com/x.git", ref)
        with pytest.raises(install.InstallError, match="--ref is a tag"):
            install.checkout("https://example.com/x.git", ref, tmp_path / "never")
    assert not (tmp_path / "never").exists()


def test_a_cub_fetch_reads_none_of_the_owners_git_or_ssh_config(monkeypatch, tmp_path):
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, env=kw["env"])
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(install.subprocess, "run", run)
    install._git(["ls-remote", "https://example.com/x.git"], tmp_path)
    env = seen["env"]
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes -F /dev/null"
    assert "SSH_AUTH_SOCK" not in env


def test_narrowing_to_topics(home, tmp_path):
    topic = home.store.query_one("SELECT id FROM topics")["id"]
    row = added(home, make_cub(tmp_path / "hello", manifest(reads="[topics, library]")),
                topics=[topic])
    assert json.loads(row["grants"])["reads_topics"] == [topic]
    with pytest.raises(install.InstallError, match="no topic 999"):
        added(home, make_cub(tmp_path / "xx", manifest("xx", reads="[library]")), topics=[999])


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_a_git_source_at_a_tag_is_unreviewed_and_its_sha_kept(home, tmp_path):
    repo = make_cub(tmp_path / "repo")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for argv in (["init", "-q"], ["add", "."], ["commit", "-qm", "one"], ["tag", "v1.0.0"]):
        subprocess.run(["git", *argv], cwd=repo, check=True, env=env)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                         text=True, check=True).stdout.strip()
    j = install.start(home, f"file://{repo}", ref="v1.0.0", background=False)
    assert j["state"] == "awaiting_confirm", j
    assert j["cub"]["trust"] == "unreviewed" and j["cub"]["sha"] == sha
    assert dict(j["cub"]["words"])["Trust"].startswith("Nobody at Kranto has read this code")
    row = install.install(home, j["id"], door="cli")
    assert row["trust"] == "unreviewed" and row["sha"] == sha
    assert not (files.cub_dir(home.cfg, "hello") / "src" / ".git").exists()


def test_a_git_url_names_one_folder_of_a_repository_with_subdirectory():
    assert install.parse_source("https://example.com/cubs.git#subdirectory=cubs/hello") == \
        {"kind": "git", "url": "https://example.com/cubs.git", "ref": None,
         "subdirectory": "cubs/hello"}
    assert install.parse_source("https://example.com/cubs.git")["subdirectory"] is None
    for frag in ("subdirectory=../etc", "subdirectory=cubs/../..", "subdirectory=/abs",
                 "subdirectory=", "subdirectory=a//b", "subdirectory=./a", "egg=x", "x"):
        with pytest.raises(install.InstallError, match="subdirectory=path"):
            install.parse_source(f"https://example.com/cubs.git#{frag}")


def git_commit(repo: Path, message: str, tag: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    for argv in (["add", "-A"], ["commit", "-qm", message], *([["tag", tag]] if tag else [])):
        subprocess.run(["git", *argv], cwd=repo, check=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_a_cub_installs_and_updates_from_its_folder_of_a_repository(home, tmp_path):
    repo = tmp_path / "cubs"
    make_cub(repo / "cubs" / "hello")
    make_cub(repo / "cubs" / "other", manifest("other"))
    (repo / "README.md").write_text("Several cubs.\n")
    git_commit(repo, "two cubs")
    j = install.start(home, f"file://{repo}#subdirectory=cubs/hello", background=False)
    assert j["state"] == "awaiting_confirm", j
    assert j["cub"]["id"] == "hello" and j["cub"]["inventory"]["files"] == 2   # that folder only
    row = install.install(home, j["id"], door="cli")
    assert json.loads(row["source"]) == {"kind": "git", "url": f"file://{repo}",
                                         "subdirectory": "cubs/hello"}
    assert not (files.cub_dir(home.cfg, "hello") / "src" / "README.md").exists()
    out = io.StringIO()
    assert cubs_cli.main(home.cfg.root, ["inspect", "hello"], rt=home, out=out) == 0
    assert f"source   git file://{repo}#subdirectory=cubs/hello @ " in out.getvalue()
    (repo / "cubs" / "hello" / "cub.yaml").write_text(manifest(version="1.1.0"))
    git_commit(repo, "hello 1.1.0")
    up = install.start(home, kind="update", cid="hello", background=False)
    assert up["state"] == "awaiting_confirm" and up["cub"]["version"] == "1.1.0", up


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_a_subdirectory_that_is_missing_or_a_link_is_refused(home, tmp_path):
    repo = tmp_path / "cubs"
    make_cub(repo / "cubs" / "hello")
    (repo / "elsewhere").symlink_to(repo / "cubs" / "hello")
    git_commit(repo, "a link")
    for sub in ("cubs/missing", "elsewhere"):
        j = install.start(home, f"file://{repo}#subdirectory={sub}", background=False)
        assert j["state"] == "failed" and "is not a folder of that repository" in j["error"], j


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_sec8_where_only_rlimits_apply_the_install_says_a_strangers_cub_will_not_run(
        home, tmp_path, monkeypatch, capsys):
    """the runtime refuses an unreviewed cub where only rlimits apply; the dialog and
    ``kranto cub add`` say so before the install, not at its first run."""
    from dataclasses import replace

    from kranto.core.cubs import settings as cs
    monkeypatch.setenv("KRANTO_CUBS_RLIMITS", "1")
    repo = make_cub(tmp_path / "repo")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for argv in (["init", "-q"], ["add", "."], ["commit", "-qm", "one"], ["tag", "v1.0.0"]):
        subprocess.run(["git", *argv], cwd=repo, check=True, env=env)
    said = "it will not run until cubs.allow_rlimits: true in kranto.yaml"

    def findings(j: dict) -> list[str]:
        install.cancel(home.store, home.cfg, j["id"])
        return [f["text"] for f in j["cub"]["inventory"]["findings"]]
    stranger = install.start(home, f"file://{repo}", ref="v1.0.0", background=False)
    assert stranger["cub"]["trust"] == "unreviewed"
    assert [t for t in findings(stranger) if said in t] == [
        "This machine cannot cap a cub's processes (no systemd user manager), so only your own "
        "cubs run here; " + said]
    own = install.start(home, str(make_cub(tmp_path / "own", manifest("own"))), background=False)
    assert own["cub"]["trust"] == "owner" and findings(own) == []      # the owner's own runs
    assert cubs_cli.main(tmp_path, ["add", f"file://{repo}", "--ref", "v1.0.0"], ask=lambda q: "n",
                         rt=home) == 2
    assert "! This machine cannot cap a cub's processes" in capsys.readouterr().out
    home.cfg = replace(home.cfg, cubs=cs.parse({"allow_rlimits": True}))
    allowed = install.start(home, f"file://{repo}", ref="v1.0.0", background=False)
    assert not [t for t in findings(allowed) if said in t]


# -- what is refused at the folder: S20, S21, S22 -------------------------------------------------


def _failed(home, folder) -> str:
    j = install.start(home, str(folder), background=False)
    assert j["state"] == "failed", j
    assert not any((files.root(home.cfg) / ".staged").iterdir())
    return j["error"]


def test_s21_a_link_out_or_a_native_file_is_refused(home, tmp_path):
    a = make_cub(tmp_path / "a")
    (a / "data").symlink_to(tmp_path)
    assert "link out of the folder" in _failed(home, a)
    b = make_cub(tmp_path / "b")
    (b / "fast.so").write_bytes(b"\x7fELF....")
    assert "native library" in _failed(home, b)
    c = make_cub(tmp_path / "c")
    (c / "tool").write_bytes(b"\x7fELF\x02\x01")
    assert "a program (ELF" in _failed(home, c)
    d = make_cub(tmp_path / "d")
    (d / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (d / "run.sh").chmod(0o755)
    assert "marked executable" in _failed(home, d)


def test_s20_requirements_must_be_pinned_by_hash(home, tmp_path):
    good = "requests==2.32.3 --hash=sha256:" + "a" * 64
    for line, words in (("requests>=2", "not name==version"),
                        ("https://example.com/x.whl", "not name==version"),
                        ("requests==2.32.3", "not name==version"),
                        ("-e ./local", "not name==version")):
        f = make_cub(tmp_path / f"r{abs(hash(line))}", manifest(requirements="requirements.txt"))
        (f / "requirements.txt").write_text(line + "\n")
        assert words in _failed(home, f)
    f = make_cub(tmp_path / "many", manifest(requirements="requirements.txt"))
    (f / "requirements.txt").write_text("\n".join([good] * 51) + "\n")
    assert "at most" in _failed(home, f)


def test_s22_ids_that_clash(home, tmp_path):
    for cid, words in (("llm", "reserved"), ("news", "reserved")):
        assert words in _failed(home, make_cub(tmp_path / cid, manifest(cid)))
    added(home, make_cub(tmp_path / "hello", manifest(
        events="{publish: [hello.said]}")))
    assert "installed already" in _failed(home, make_cub(tmp_path / "again"))
    thief = manifest("thief", events="{publish: [hello.said]}")
    assert "hello.said" in _failed(home, make_cub(tmp_path / "thief", thief))


# -- update: S19 ----------------------------------------------------------------------------------


def test_an_update_shows_its_delta_and_a_grown_one_goes_dry_again(home, tmp_path):
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    added(home, src)
    cs.write(home.cfg, "cubs.hello.live", ["book.propose"])
    assert cs.live_kinds(home.cfg, "hello") == ["book.propose"]
    j = install.start(home, kind="update", cid="hello", background=False)
    assert j["state"] == "cancelled" and j["error"] == "up to date"
    (src / "main.py").write_text(MAIN + "\n# changed\n")
    j = install.start(home, kind="update", cid="hello", background=False)
    assert j["state"] == "failed" and "raise the version" in j["error"]
    (src / "cub.yaml").write_text(manifest(version="1.1.0", requests="[book.propose, "
                                                                    "post.mastodon]",
                                           broker="{mastodon: [statuses.draft]}"))
    j = install.start(home, kind="update", cid="hello", background=False)
    d = j["cub"]["delta"]
    assert j["state"] == "awaiting_confirm" and j["needs"] == "house"
    assert d["grown"] and d["high_trust"] and d["added"] == {
        "broker": ["mastodon statuses.draft"], "requests": ["post.mastodon"]}
    assert j["cub"]["diff"]["counts"] == {"added": 0, "removed": 0, "changed": 2}
    row = install.apply_update(home, j["id"], "hello", door="ui")
    assert row["version"] == "1.1.0" and cs.live_kinds(home.cfg, "hello") == []
    assert registry.latest(home.store, "hello")["version"] == "1.1.0"
    assert [e["payload"]["version"] for e in events.read(home.store, kinds=["cub.updated"])] \
        == ["1.1.0"]
    assert files.tree_hash(files.cub_dir(home.cfg, "hello") / "src") == row["tree_hash"]


def test_an_update_keeps_the_narrowing(home, tmp_path):
    topic = home.store.query_one("SELECT id FROM topics")["id"]
    src = make_cub(tmp_path / "hello", manifest(reads="[topics, library]"))
    added(home, src, topics=[topic])
    (src / "cub.yaml").write_text(manifest(version="1.0.1", reads="[topics, library]"))
    j = install.start(home, kind="update", cid="hello", background=False)
    assert j["needs"] == "confirm" and not j["cub"]["delta"]["grown"]
    row = install.apply_update(home, j["id"], "hello", door="cli")
    assert json.loads(row["grants"])["reads_topics"] == [topic]


def test_one_staged_update_per_cub_and_it_is_named_where_the_owner_looks(home, tmp_path):
    """live had three update jobs awaiting confirm for one cub, and neither the
    page nor kranto cub inspect said so. Looking again answers the job staged already; newer
    files supersede it; the cub's line and inspect name it with what it may now do."""
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    added(home, src)
    (src / "cub.yaml").write_text(manifest(version="1.1.0", requests="[book.propose, "
                                                                    "post.mastodon]",
                                           broker="{mastodon: [statuses.draft]}"))
    first = install.start(home, kind="update", cid="hello", background=False)
    again = install.start(home, kind="update", cid="hello", background=False)
    assert first["state"] == "awaiting_confirm" and again["id"] == first["id"]
    assert install.awaiting_updates(home.store, home.cfg, "hello") == [first["id"]]
    up = views.row(home, "hello")["update"]
    assert up["job"] == first["id"] and up["version"] == "1.1.0" and up["needs"] == "house"
    assert "requests: post.mastodon" in up["adds"]
    out = io.StringIO()
    cubs_cli.c_inspect(home, argparse.Namespace(id="hello", manifest=False, grants=False,
                                               kv=False, json=False), None, out)
    assert f"update   1.1.0 is staged (job {first['id']}); apply it on the page" in out.getvalue()
    assert "it may now: requests: post.mastodon" in out.getvalue()
    # newer files: a new job, and the old one is superseded, so one waits
    (src / "cub.yaml").write_text(manifest(version="1.2.0", requests="[book.propose, "
                                                                    "post.mastodon]",
                                           broker="{mastodon: [statuses.draft]}"))
    newer = install.start(home, kind="update", cid="hello", background=False)
    assert newer["id"] != first["id"] and newer["state"] == "awaiting_confirm"
    assert install.awaiting_updates(home.store, home.cfg, "hello") == [newer["id"]]
    old = install.job(home.store, home.cfg, first["id"])
    assert old["error"] == f"superseded by job {newer['id']}"


# -- the switches ---------------------------------------------------------------------------------


def test_stop_expires_tickets_and_resume_waits_for_the_stop_file(home, tmp_path):
    added(home, make_cub(tmp_path / "hello", manifest(requests="[book.propose]")))
    tid = tickets.file(home.store, cub="hello", trust="owner", granted=("book.propose",),
                       kind="book.propose", fields=BOOK)
    install.stop(home, "hello")
    assert home.cubs.installed["hello"].state == "paused"
    assert home.cubs.installed["hello"].note.startswith("stopped by the owner")
    assert tickets.get(home.store, tid)["state"] == "expired"
    with pytest.raises(CubUnavailable):
        home.cubs.preflight("hello", "job")
    (tmp_path / "cubs.STOP").touch()
    with pytest.raises(install.InstallError, match="remove .*cubs.STOP first"):
        install.resume(home, "hello")
    (tmp_path / "cubs.STOP").unlink()
    install.resume(home, "hello")
    assert home.cubs.installed["hello"].state == "installed"
    assert [e["kind"] for e in events.read(home.store, kinds=["cub.stopped", "cub.resumed"])] \
        == ["cub.stopped", "cub.resumed"]


def test_enable_dry_and_live_write_the_section(home, tmp_path):
    added(home, make_cub(tmp_path / "hello", manifest(requests="[book.propose]")))
    install.set_enabled(home, "hello", False)
    assert home.cubs.off(home.cubs.installed["hello"]) == "hello is off (cubs.hello.enabled: false)"
    install.set_enabled(home, "hello", True)
    install.set_mode(home, "hello", "book.propose", True)
    assert cs.live_kinds(home.cfg, "hello") == ["book.propose"]
    install.set_mode(home, "hello", "book.propose", False)
    assert cs.live_kinds(home.cfg, "hello") == []
    with pytest.raises(install.InstallError, match="does not ask for post.mastodon"):
        install.set_mode(home, "hello", "post.mastodon", True)


def test_another_process_writing_the_section_reaches_this_one(home, tmp_path):
    """``kranto cub dry`` from a terminal: the server's next press is dry."""
    added(home, make_cub(tmp_path / "hello", manifest(requests="[book.propose]")))
    install.set_mode(home, "hello", "book.propose", True)
    other = replace(home.cfg)                       # the command line's own config
    assert cs.live_kinds(other, "hello") == ["book.propose"]
    raw = yaml.safe_load((tmp_path / "kranto.yaml").read_text())
    raw["cubs"]["hello"]["live"] = []               # what another process writes
    (tmp_path / "kranto.yaml").write_text(yaml.safe_dump(raw))
    assert cs.live_kinds(home.cfg, "hello") == []
    (tmp_path / "kranto.yaml").write_text("cubs: {hello: {live: 3}}\n")    # broken by hand
    assert cs.live_kinds(home.cfg, "hello") == []   # dry, never the last live list


def test_remove_keeps_the_history_and_frees_the_id(home, tmp_path):
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    added(home, src)
    tid = tickets.file(home.store, cub="hello", trust="owner", granted=("book.propose",),
                       kind="book.propose", fields=BOOK)
    home.store.insert("cub_kv", {"cub": "hello", "key": "k", "value": "1", "bytes": 1,
                                 "updated_at": "2026-10-19T00:00:00Z"})
    out = install.remove(home, "hello")
    assert out["removed"] and Path(out["kept"]).is_dir()
    assert registry.latest(home.store, "hello")["state"] == "removed"
    assert tickets.get(home.store, tid)["state"] == "expired"
    assert home.store.query_one("SELECT COUNT(*) AS n FROM cub_kv")["n"] == 1
    assert "hello" not in home.cubs.installed
    added(home, src)                                         # the id is free again
    out = install.remove(home, "hello", purge=True)
    assert out["purged"] and home.store.query_one("SELECT COUNT(*) AS n FROM cub_kv")["n"] == 0
    assert home.store.query_one("SELECT COUNT(*) AS n FROM cub_pins WHERE cub = 'hello'")["n"] \
        == 2                                                 # pins are kept for ever


# -- S17, S18: the files changed after the confirm ------------------------------------------------


def test_s17_a_changed_byte_pauses_the_cub_and_an_update_shows_the_change(home, tmp_path):
    src = make_cub(tmp_path / "hello")
    added(home, src)
    placed = files.cub_dir(home.cfg, "hello") / "src" / "main.py"
    placed.chmod(0o600)
    placed.write_text(MAIN + "\n# patched in place\n")
    with pytest.raises(CubUnavailable, match="changed since you approved"):
        home.cubs.preflight("hello", "job")
    assert home.cubs.installed["hello"].state == "paused"
    (src / "cub.yaml").write_text(manifest(version="1.0.1"))
    j = install.start(home, kind="update", cid="hello", background=False)
    assert j["state"] == "awaiting_confirm" and j["cub"]["diff"]["changed"] == ["cub.yaml",
                                                                                "main.py"]


@needs_bwrap
def test_s18_a_registry_row_whose_hash_is_not_the_files_is_refused_at_hello(home, tmp_path):
    added(home, make_cub(tmp_path / "hello"))
    row = registry.latest(home.store, "hello")
    registry.append(home.store, row, manifest_hash="0" * 64)    # the attacker's row
    home.store.insert("cub_pins", {"cub": "hello", "version": "1.0.0", "trust": "owner",
                                   "manifest_hash": "0" * 64, "tree_hash": row["tree_hash"],
                                   "created_at": "2026-10-19T00:00:00Z"})
    home.cubs.load()
    with pytest.raises(RuntimeError, match="not the one approved"):
        home.cubs.run_job("hello", "hello.tick", "tick")
    assert home.cubs.installed["hello"].state == "paused"


# -- recovery -------------------------------------------------------------------------------------


def test_a_crash_mid_install_is_recovered(home, tmp_path):
    src = make_cub(tmp_path / "hello")
    j = install.start(home, str(src), background=False)
    install._step(home.store, j["id"], "add", "hello", "placing")
    staged = files.root(home.cfg) / ".staged" / j["id"]
    staged.rename(files.cub_dir(home.cfg, "hello"))            # placed, then the crash
    k = install.start(home, str(make_cub(tmp_path / "b", manifest("bee"))), background=False)
    install._step(home.store, k["id"], "add", "bee", "fetching")    # a fetch cut short
    said = install.recover(home)
    assert sorted(said) == sorted([f"{j['id']}: interrupted before the pin",
                                   f"{k['id']}: interrupted"])
    assert not files.cub_dir(home.cfg, "hello").exists()
    assert any(p.name.startswith("bad-hello") for p in (files.root(home.cfg) / ".work").iterdir())
    assert registry.latest(home.store, "hello") is None


# -- the HTTP API and its doors: S27 --------------------------------------------------------------


def test_s27_the_doors_of_the_api(home, tmp_path):
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    app = create_app(home)
    with web_client(app, "http://127.0.0.1:8765") as web:
        cli = {"authorization": f"Bearer {app.state.app.auth.store.value('cli')}"}
        ui_bearer = {"authorization": f"Bearer {app.state.app.auth.store.value('ui')}"}
        r = web.post("/api/cubs/fetch", json={"source": str(src)}, headers=cli)
        assert r.status_code == 202
        job = r.json()["job"]["id"]
        for _ in range(100):
            state = web.get(f"/api/cubs/jobs/{job}").json()["state"]
            if state not in ("queued", "fetching", "fetched", "inspected"):
                break
            import time
            time.sleep(0.05)
        assert state == "awaiting_confirm"
        body = {"job": job, "confirm": True}
        assert web.post("/api/cubs/hello/install", json=body, headers=cli).status_code == 403
        assert web.post("/api/cubs/hello/install", json=body,
                        headers=ui_bearer).status_code == 403
        assert web.post("/api/cubs/hello/install", json={"job": job}).status_code == 400
        r = web.post("/api/cubs/hello/install", json=body)
        assert r.status_code == 200 and r.json()["cub"]["state"] == "installed"
        listing = web.get("/api/cubs").json()
        assert [c["id"] for c in listing["cubs"]] == ["hello"] and listing["stop_file"] is False
        assert "words" in web.get("/api/cubs/hello").json()
        assert web.get("/api/cubs/hello/log").status_code == 200
        assert web.get("/api/cubs/..%2F..%2Fx/log").status_code == 404
        assert web.get("/api/cubs/Bad.Id/log").status_code == 404
        live = {"kind": "book.propose", "confirm": True}
        assert web.post("/api/cubs/hello/live", json={"kind": "book.propose"}).status_code == 400
        assert web.post("/api/cubs/hello/live", json=live, headers=cli).status_code == 403
        assert web.post("/api/cubs/hello/live", json=live).status_code == 200
        assert web.post("/api/cubs/hello/dry", json={"kind": "book.propose"},
                        headers=cli).status_code == 200
        assert web.post("/api/cubs/settings", json={"key": "cubs.hello.live",
                                                    "value": ["book.propose"]}).status_code == 400
        assert web.post("/api/cubs/settings", json={"key": "cubs.enabled", "value": False},
                        headers=cli).status_code == 403
        assert web.post("/api/cubs/settings", json={"key": "cubs.hello.kv_mb", "value": 4},
                        headers=cli).status_code == 200
        tid = tickets.file(home.store, cub="hello", trust="owner", granted=("book.propose",),
                           kind="book.propose", fields=BOOK)
        for headers in (cli, ui_bearer):
            assert web.post(f"/api/tickets/{tid}/confirm", json={"confirm": True},
                            headers=headers).status_code == 403
        assert web.post("/api/cubs/hello/stop", json={}, headers=cli).status_code == 200
        assert web.post("/api/cubs/hello/remove", json={"confirm": True},
                        headers=cli).status_code == 403
        r = web.post("/api/cubs/hello/remove", json={"confirm": True})
        assert r.status_code == 200 and r.json()["removed"]
        assert web.get("/api/cubs/hello").json()["state"] == "removed"


def test_s19_an_update_that_asks_for_more_is_applied_from_the_page_only(home, tmp_path):
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))
    added(home, src)
    install.set_mode(home, "hello", "book.propose", True)
    (src / "cub.yaml").write_text(manifest(version="1.1.0", requests="[book.propose, "
                                                                    "post.mastodon]"))
    app = create_app(home)
    with web_client(app, "http://127.0.0.1:8765") as web:
        cli = {"authorization": f"Bearer {app.state.app.auth.store.value('cli')}"}
        j = install.start(home, kind="update", cid="hello", background=False)
        assert j["state"] == "awaiting_confirm" and j["needs"] == "house"
        assert j["cub"]["delta"]["grown"] is True
        body = {"job": j["id"], "confirm": True}
        assert web.post("/api/cubs/hello/apply_update", json={"job": j["id"]}).status_code == 400
        assert web.post("/api/cubs/hello/apply_update", json=body, headers=cli).status_code == 403
        assert registry.latest(home.store, "hello")["version"] == "1.0.0"
        r = web.post("/api/cubs/hello/apply_update", json=body)
        assert r.status_code == 200 and r.json()["cub"]["version"] == "1.1.0"
        assert r.json()["cub"]["live"] == [] and cs.live_kinds(home.cfg, "hello") == []


# -- the command line -----------------------------------------------------------------------------


def test_the_command_line(home, tmp_path, capsys):
    src = make_cub(tmp_path / "hello", manifest(requests="[book.propose]"))

    def cub(*argv, ask=lambda q: "n"):
        return cubs_cli.main(tmp_path, list(argv), ask=ask, rt=home)

    assert cub("add", str(src)) == 2                     # answered no
    assert registry.latest(home.store, "hello") is None
    assert cub("add", str(src), "--yes") == 0
    out = capsys.readouterr().out
    assert "installed hello 1.0.0 (owner) in practice" in out and "It cannot" in out
    assert cub("list") == 0 and "hello" in capsys.readouterr().out
    assert cub("live", "hello", "book.propose") == 2
    assert "/#/cub/hello?sel=settings" in capsys.readouterr().out
    assert cub("dry", "hello", "book.propose") == 0
    assert cub("inspect", "hello") == 0 and "pinned   yes" in capsys.readouterr().out
    assert cub("check", str(src)) == 0 and "the manifest is valid" in capsys.readouterr().out
    assert cub("stopfile", "--set") == 0 and (tmp_path / "cubs.STOP").exists()
    assert cub("stopfile", "--clear") == 0 and not (tmp_path / "cubs.STOP").exists()
    assert cub("stop", "hello") == 0
    assert registry.latest(home.store, "hello")["state"] == "paused"
    assert cub("resume", "hello") == 0
    assert cub("remove", "hello", "--yes", "--purge") == 0
    assert cub("inspect", "nope") == 2
    assert cub("new", "post my pick") == 2 and "template" in capsys.readouterr().out
