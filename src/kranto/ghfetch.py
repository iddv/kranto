"""``--fetch-gh``: a pinned GitHub CLI into Kranto's own folder.

For a machine without ``gh``, once the person agrees (``kranto setup`` asks first, unless
``--yes``): the archive for this system from github.com/cli/cli's release ``VERSION``, its
SHA-256 checked twice before anything is unpacked, against the release's own checksums file
and against the hash pinned here (so a changed release cannot pass); then only ``bin/gh`` is
written, as ``~/.local/share/kranto/bin/gh``. Nothing system-wide, no sudo. ``kranto`` puts that
folder on its own PATH and on the unit's, so the server, publishing and the update find it.
The distribution's package stays the first suggestion: it updates with the system, and this
copy does not (``kranto doctor`` says when it is a year old).
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path

VERSION = "2.102.0"
RELEASED = date(2026, 9, 30)
# the release's archives, by system and machine, and their SHA-256 as gh_2.102.0_checksums.txt
# published them (read 2026-10-17; the linux_amd64 archive downloaded and checked by hand)
SHA256 = {
    "linux_amd64.tar.gz": "bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386",
    "linux_arm64.tar.gz": "7862c86c72f43df3a2d93ddde6f473285b4e2af61b494849846827e513ef6484",
    "macOS_amd64.zip": "b245f24eb2bf5f75b426b4c26da3651a107f8d5b6f4fddfbfccc5679041378b3",
    "macOS_arm64.zip": "da922c20d1792e5b2cbf375593d7a658acf034c12c84e007e71c76ef959c337e",
}
BASE = "https://github.com/cli/cli/releases/download"
BASE_ENV = "KRANTO_GH_RELEASES"          # tests: a stand-in for the release, on loopback
MACHINES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
MAX_BYTES = 200 * 1024 * 1024


class FetchError(Exception):
    """The download, a hash or the archive was not what it must be; nothing was installed."""


def bin_dir(user_home: Path) -> Path:
    """Kranto's own command folder: only what ``--fetch-gh`` put there."""
    return Path(user_home) / ".local" / "share" / "kranto" / "bin"


def asset(system: str | None = None, machine: str | None = None) -> str | None:
    """The archive's suffix for this system (``linux_amd64.tar.gz``); None when the release has
    none Kranto pins."""
    system = system or platform.system()
    arch = MACHINES.get((machine or platform.machine()).lower())
    name = {"Linux": f"linux_{arch}.tar.gz", "Darwin": f"macOS_{arch}.zip"}.get(system)
    return name if arch and name in SHA256 else None


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kranto-fetch-gh"})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - https, or a test's loopback
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise FetchError(f"{url} is larger than {MAX_BYTES // 2**20} MB")
    return data


def fetch(user_home: Path, *, get: Callable[[str], bytes] | None = None,
          system: str | None = None, machine: str | None = None) -> Path:
    """Download, check and install ``gh``; returns its path. Raises ``FetchError`` with nothing
    written when anything does not match."""
    suffix = asset(system, machine)
    if suffix is None:
        raise FetchError(f"no pinned gh for {system or platform.system()} "
                         f"{machine or platform.machine()}: install it from https://cli.github.com")
    get = get or _get
    base = (os.environ.get(BASE_ENV) or BASE).rstrip("/")
    name = f"gh_{VERSION}_{suffix}"
    try:
        sums = get(f"{base}/v{VERSION}/gh_{VERSION}_checksums.txt").decode()
        data = get(f"{base}/v{VERSION}/{name}")
    except (OSError, UnicodeDecodeError) as exc:
        raise FetchError(f"could not download gh {VERSION} from github.com: {exc}") from exc
    listed = {}
    for line in sums.splitlines():
        h, _, n = line.strip().partition("  ")
        if h and n:
            listed[n.lstrip("*")] = h.lower()
    got = hashlib.sha256(data).hexdigest()
    if listed.get(name) != got:
        raise FetchError(f"{name}: its SHA-256 does not match the release's checksums file; "
                         "nothing was installed")
    if got != SHA256[suffix]:
        raise FetchError(f"{name}: its SHA-256 does not match the one Kranto pins for gh "
                         f"{VERSION}; nothing was installed")
    binary = _unpack(data, f"gh_{VERSION}_{suffix.split('.')[0]}/bin/gh", suffix.endswith(".zip"))
    folder = bin_dir(user_home)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / "gh"
    tmp = folder / f".gh.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o755)
    with os.fdopen(fd, "wb") as f:
        f.write(binary)
    os.replace(tmp, dest)
    return dest


def _unpack(data: bytes, member: str, is_zip: bool) -> bytes:
    """Only the one member, read into memory: no path from the archive is ever written."""
    try:
        if is_zip:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return z.read(member)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            f = t.extractfile(member)
            if f is None:
                raise KeyError(member)
            return f.read()
    except (KeyError, tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise FetchError(f"the gh archive has no {member}: nothing was installed") from exc


def age_note(version_text: str, today: date | None = None) -> str | None:
    """For ``kranto doctor``: a warning when Kranto's own gh (``gh --version``'s first line, e.g.
    ``gh version 2.102.0 (2026-09-30)``) is more than a year old; None otherwise."""
    import re

    m = re.search(r"\((\d{4})-(\d{2})-(\d{2})\)", version_text or "")
    if not m:
        return None
    built = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    days = ((today or date.today()) - built).days
    return (f"Kranto's own gh is from {built.isoformat()}, over a year old: 'kranto setup machine "
            "--fetch-gh' after a kranto update fetches a newer one, or install your "
            "distribution's gh") if days > 365 else None
