"""``--fetch-gh``: a pinned gh, its hash checked against the release's
checksums file and Kranto's own pin before anything is unpacked, only ``bin/gh`` written, into
Kranto's own folder. A stand-in release in memory: no network."""

from __future__ import annotations

import hashlib
import io
import stat
import tarfile
import zipfile
from datetime import date

import pytest

from kranto import ghfetch

V = ghfetch.VERSION


def tar_gz(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def release(monkeypatch, archive: bytes, suffix="linux_amd64.tar.gz", *, listed=None, pin=None):
    """A release whose checksums file lists ``listed`` (default: the archive's hash) and a pin
    of ``pin`` (default: the same); returns the fake ``get`` and the URLs it was asked for."""
    h = hashlib.sha256(archive).hexdigest()
    monkeypatch.setitem(ghfetch.SHA256, suffix, pin or h)
    sums = f"{'0' * 64}  gh_{V}_other.tar.gz\n{listed or h}  gh_{V}_{suffix}\n".encode()
    asked = []

    def get(url):
        asked.append(url)
        return sums if url.endswith("_checksums.txt") else archive
    return get, asked


GOOD = {f"gh_{V}_linux_amd64/bin/gh": b"#!/bin/sh\necho gh version\n",
        f"gh_{V}_linux_amd64/LICENSE": b"MIT",
        "../../escape": b"never written"}


def test_a_matching_release_installs_only_gh_into_kranto_own_folder(tmp_path, monkeypatch):
    get, asked = release(monkeypatch, tar_gz(GOOD))
    path = ghfetch.fetch(tmp_path, get=get, system="Linux", machine="x86_64")
    assert path == tmp_path / ".local" / "share" / "kranto" / "bin" / "gh"
    assert path.read_bytes() == GOOD[f"gh_{V}_linux_amd64/bin/gh"]
    assert stat.S_IMODE(path.stat().st_mode) & 0o111
    assert sorted(p.name for p in path.parent.iterdir()) == ["gh"]
    assert not (tmp_path / "escape").exists() and not (tmp_path.parent / "escape").exists()
    assert asked == [f"{ghfetch.BASE}/v{V}/gh_{V}_checksums.txt",
                     f"{ghfetch.BASE}/v{V}/gh_{V}_linux_amd64.tar.gz"]


def test_a_hash_the_checksums_file_does_not_list_installs_nothing(tmp_path, monkeypatch):
    get, _ = release(monkeypatch, tar_gz(GOOD), listed="f" * 64)
    with pytest.raises(ghfetch.FetchError, match="checksums file"):
        ghfetch.fetch(tmp_path, get=get, system="Linux", machine="x86_64")
    assert not (tmp_path / ".local").exists()


def test_a_release_changed_under_the_pin_installs_nothing(tmp_path, monkeypatch):
    """The checksums file agrees with the archive (both replaced), but Kranto's pin does not."""
    get, _ = release(monkeypatch, tar_gz(GOOD), pin="e" * 64)
    with pytest.raises(ghfetch.FetchError, match="Kranto pins"):
        ghfetch.fetch(tmp_path, get=get, system="Linux", machine="x86_64")
    assert not (tmp_path / ".local").exists()


def test_an_archive_without_gh_installs_nothing(tmp_path, monkeypatch):
    get, _ = release(monkeypatch, tar_gz({"gh/bin/other": b"x"}))
    with pytest.raises(ghfetch.FetchError, match="no gh_"):
        ghfetch.fetch(tmp_path, get=get, system="Linux", machine="x86_64")
    assert not (tmp_path / ".local").exists()


def test_macos_takes_the_zip(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"gh_{V}_macOS_arm64/bin/gh", b"mac gh")
    get, asked = release(monkeypatch, buf.getvalue(), "macOS_arm64.zip")
    assert ghfetch.fetch(tmp_path, get=get, system="Darwin", machine="arm64").read_bytes() == \
        b"mac gh"
    assert asked[-1].endswith(f"gh_{V}_macOS_arm64.zip")


def test_the_download_failing_says_so_and_installs_nothing(tmp_path):
    def get(url):
        raise OSError("no route to host")
    with pytest.raises(ghfetch.FetchError, match="could not download"):
        ghfetch.fetch(tmp_path, get=get, system="Linux", machine="x86_64")
    assert not (tmp_path / ".local").exists()


def test_the_pins_cover_the_systems_kranto_runs_on():
    assert ghfetch.asset("Linux", "x86_64") == "linux_amd64.tar.gz"
    assert ghfetch.asset("Linux", "aarch64") == "linux_arm64.tar.gz"
    assert ghfetch.asset("Darwin", "x86_64") == "macOS_amd64.zip"
    assert ghfetch.asset("Windows", "AMD64") is None and ghfetch.asset("Linux", "riscv64") is None
    assert set(ghfetch.SHA256) == {"linux_amd64.tar.gz", "linux_arm64.tar.gz",
                                   "macOS_amd64.zip", "macOS_arm64.zip"}
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in ghfetch.SHA256.values())


def test_the_doctor_warns_when_kranto_own_gh_is_a_year_old():
    line = f"gh version {V} (2026-09-30)\nhttps://github.com/cli/cli/releases/tag/v{V}\n"
    assert ghfetch.age_note(line, today=date(2027, 9, 1)) is None
    assert "over a year old" in ghfetch.age_note(line, today=date(2027, 10, 2))
    assert ghfetch.age_note("gh version 2.0.0", today=date(2030, 1, 1)) is None
