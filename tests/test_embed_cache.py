"""The embedding model is kept under the user's own cache folder, never fastembed's default in
/tmp (emptied at a reboot, and a path any local user can make first). A model an earlier Kranto
left in /tmp is copied over once, only when it is this user's, and the old place is used for one
run when the copy fails: it is never downloaded again for the move. Nothing here touches the
network or the real model."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from kranto import embed


def env_for(tmp_path: Path, **more) -> dict:
    return {"HOME": str(tmp_path / "user"), **more}


def old_model(tmp_path: Path) -> Path:
    """An old cache as the hub lays it out: a blob, and a snapshot that links to it."""
    old = tmp_path / "tmp" / "fastembed_cache"
    blobs = old / "models--org--m" / "blobs"
    snap = old / "models--org--m" / "snapshots" / "abc"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (blobs / "f1").write_bytes(b"weights")
    os.symlink("../../blobs/f1", snap / "model.onnx")
    return old


def test_the_folder_is_under_the_users_cache():
    assert embed.default_cache_dir({"HOME": "/srv/u"}) == Path("/srv/u/.cache/kranto/fastembed")
    assert embed.default_cache_dir({"HOME": "/srv/u", "XDG_CACHE_HOME": "/var/c"}) == \
        Path("/var/c/kranto/fastembed")
    # a relative XDG_CACHE_HOME is not a cache folder (the XDG rule): the default stands
    assert embed.default_cache_dir({"HOME": "/srv/u", "XDG_CACHE_HOME": "c"}) == \
        Path("/srv/u/.cache/kranto/fastembed")
    assert embed.default_cache_dir({"HOME": "/srv/u", "FASTEMBED_CACHE_PATH": "/m"}) == \
        Path("/m")
    assert embed.OLD_CACHE.name == "fastembed_cache"


def test_a_new_install_gets_its_own_empty_folder(tmp_path):
    got = embed.cache_dir(env_for(tmp_path), old=tmp_path / "nothing")
    assert got == tmp_path / "user/.cache/kranto/fastembed" and got.is_dir()
    assert not str(got).startswith("/tmp/fastembed_cache")
    assert oct(got.stat().st_mode & 0o777) == "0o700"


def test_an_old_cache_is_copied_once_and_left_in_place(tmp_path):
    old = old_model(tmp_path)
    got = embed.cache_dir(env_for(tmp_path), old=old)
    link = got / "models--org--m/snapshots/abc/model.onnx"
    assert got == tmp_path / "user/.cache/kranto/fastembed"
    assert link.is_symlink() and link.read_bytes() == b"weights"       # the links kept
    assert (old / "models--org--m/blobs/f1").read_bytes() == b"weights"  # the old one stays
    assert not [p for p in got.parent.iterdir() if p.name.startswith(".fastembed-copy-")]
    (old / "models--org--m/blobs/f2").write_bytes(b"new")
    assert embed.cache_dir(env_for(tmp_path), old=old) == got           # not copied again
    assert not (got / "models--org--m/blobs/f2").exists()


def test_an_old_cache_that_is_not_this_users_is_not_taken(tmp_path, monkeypatch):
    old = old_model(tmp_path)
    real = os.getuid()
    monkeypatch.setattr(embed.os, "getuid", lambda: real + 1)
    got = embed.cache_dir(env_for(tmp_path), old=old)
    assert got.is_dir() and list(got.iterdir()) == []


def test_an_old_cache_that_is_a_link_is_not_taken(tmp_path):
    real = old_model(tmp_path)
    link = tmp_path / "linked_cache"
    os.symlink(real, link)
    got = embed.cache_dir(env_for(tmp_path), old=link)
    assert list(got.iterdir()) == []


def test_a_failed_copy_uses_the_old_place_for_this_run(tmp_path, monkeypatch):
    old = old_model(tmp_path)

    def full_disk(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(embed.shutil, "copytree", full_disk)
    assert embed.cache_dir(env_for(tmp_path), old=old) == old
    new = tmp_path / "user/.cache/kranto/fastembed"
    assert not new.exists() or list(new.iterdir()) == []
    assert not [p for p in new.parent.iterdir() if p.name.startswith(".fastembed-copy-")]


def test_the_users_own_choice_is_used_as_it_is(tmp_path):
    old = old_model(tmp_path)
    mine = tmp_path / "models"
    got = embed.cache_dir(env_for(tmp_path, FASTEMBED_CACHE_PATH=str(mine)), old=old)
    assert got == mine and not mine.exists()          # fastembed makes it; nothing copied


def test_the_real_model_is_loaded_from_the_users_cache(tmp_path, monkeypatch):
    made = {}

    class TextEmbedding:
        def __init__(self, name, **kwargs):
            made.update(name=name, **kwargs)

    monkeypatch.setitem(sys.modules, "fastembed", types.SimpleNamespace(
        TextEmbedding=TextEmbedding))
    monkeypatch.setattr(embed, "OLD_CACHE", tmp_path / "no-old")
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    embed.NomicEmbedder()._load()
    assert made["name"] == embed.NOMIC_MODEL
    assert made["cache_dir"] == str(tmp_path / "user/.cache/kranto/fastembed")
    made.clear()
    embed.NomicEmbedder(cache_dir=str(tmp_path / "mine"))._load()
    assert made["cache_dir"] == str(tmp_path / "mine")


def test_a_stand_in_model_is_never_handed_a_folder(tmp_path):
    made = {}

    def factory(name, **kwargs):
        made.update(kwargs)
        return types.SimpleNamespace()
    embed.NomicEmbedder(factory=factory)._load()
    assert "cache_dir" not in made
