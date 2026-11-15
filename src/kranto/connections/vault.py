"""Where connected accounts' secrets are kept (section 3.4).

``<workspace>/data/secrets/connections.json``: one file, encrypted as a whole
with AES-256-GCM, written atomically, mode 0600 in a 0700 directory. Never in
kranto.yaml, never in the library database (which ``python -m kranto export`` and bundles
read), never in git (``data/`` is outside the config, and ``.gitignore`` names
``data/secrets/``).

The key is HKDF-SHA256 over two things: ``/etc/machine-id`` (something on the
box) and a random 32-byte salt file ``data/secrets/salt`` (0600). A copy of
``data/`` restored on another machine cannot decrypt the file, and neither can a
copy of the salt alone. This defends against backups, exports and accidental
copies, not against root on the box.

Needs the ``cryptography`` package (``pip install 'kranto[connections]'``).
Reads and writes take a file lock, so ``python -m kranto serve`` and a cron ``python -m kranto
run`` that
both refresh a token do not lose each other's writes; ``locked`` holds it across a
whole refresh for a provider whose old refresh token dies when a new one is issued.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import json
import os
import secrets
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

FILENAME = "connections.json"
SALT_FILENAME = "salt"
LOCK_FILENAME = ".lock"
MACHINE_ID = Path("/etc/machine-id")
_INFO = b"the server connections v1"
_AAD = b"kranto-connections"


class VaultError(Exception):
    """The secrets cannot be read or written; the message says why and what to do."""


def _crypto():
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError as exc:
        raise VaultError("connected accounts need the cryptography package: "
                         "pip install 'kranto[connections]'") from exc
    return AESGCM, HKDF, hashes, InvalidTag


def crypto_available() -> bool:
    try:
        _crypto()
    except VaultError:
        return False
    return True


class Vault:
    def __init__(self, directory: Path, *, machine_id: Path = MACHINE_ID) -> None:
        self.directory = Path(directory)
        self.path = self.directory / FILENAME
        self.salt_path = self.directory / SALT_FILENAME
        self.machine_id = Path(machine_id)
        self._lock = threading.RLock()
        # How deep this thread is inside ``locked``: the file lock is taken on the way in only
        # (a second flock on a new descriptor in the same process would wait for itself).
        self._depth = 0

    # -- key -----------------------------------------------------------------------

    def _machine_id(self) -> bytes:
        try:
            value = self.machine_id.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise VaultError(f"cannot read {self.machine_id}: the key is derived from it") \
                from exc
        if len(value) < 16:
            raise VaultError(f"{self.machine_id} is empty or too short to derive a key from")
        return value.encode()

    def _salt(self, create: bool) -> bytes | None:
        if not self.salt_path.exists():
            if not create:
                return None
            self._ensure_dir()
            _write_private(self.salt_path, secrets.token_bytes(32))
        data = self.salt_path.read_bytes()
        if len(data) != 32:
            raise VaultError(f"{self.salt_path} is not a 32-byte salt; it was altered")
        return data

    def _key(self, create: bool) -> bytes | None:
        AESGCM, HKDF, hashes, _ = _crypto()  # noqa: N806 - class names
        salt = self._salt(create)
        if salt is None:
            return None
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                    info=_INFO).derive(self._machine_id())

    def _ensure_dir(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)

    # -- read and write --------------------------------------------------------------

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the vault, across processes, for several reads and writes: a refresh whose old
        token dies once the provider answers (X) reads, asks and writes inside one. Re-entrant
        in the thread that holds it."""
        with self._lock:
            if self._depth:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self._ensure_dir()
            with open(self.directory / LOCK_FILENAME, "a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                self._depth = 1
                try:
                    yield
                finally:
                    self._depth = 0
                    fcntl.flock(fh, fcntl.LOCK_UN)

    _locked = locked

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        AESGCM, _, _, InvalidTag = _crypto()  # noqa: N806
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            nonce = base64.b64decode(envelope["nonce"])
            data = base64.b64decode(envelope["data"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise VaultError(f"{self.path} is not a secrets file") from exc
        key = self._key(create=False)
        if key is None:
            raise VaultError(f"{self.salt_path} is missing, so {self.path} cannot be decrypted; "
                             "disconnect and connect the accounts again")
        try:
            plain = AESGCM(key).decrypt(nonce, data, _AAD)
        except InvalidTag as exc:
            raise VaultError(f"{self.path} cannot be decrypted here: it was written on another "
                             "machine or with another salt. Connect the accounts again.") from exc
        return json.loads(plain)

    def _write(self, entries: dict) -> None:
        AESGCM, _, _, _ = _crypto()  # noqa: N806
        key = self._key(create=True)
        nonce = secrets.token_bytes(12)
        data = AESGCM(key).encrypt(nonce, json.dumps(entries).encode(), _AAD)
        envelope = json.dumps({"version": 1, "cipher": "AES-256-GCM",
                               "nonce": base64.b64encode(nonce).decode(),
                               "data": base64.b64encode(data).decode()})
        _write_private(self.path, envelope.encode())

    def get(self, key: str) -> dict | None:
        with self._locked():
            value = self._read().get(key)
        return dict(value) if isinstance(value, dict) else None

    def keys(self) -> list[str]:
        with self._locked():
            return sorted(self._read())

    def put(self, key: str, value: dict) -> None:
        with self._locked():
            entries = self._read()
            entries[key] = value
            self._write(entries)

    def update(self, key: str, **changes) -> dict | None:
        """Merge ``changes`` into an entry; None (and no write) if it does not exist."""
        with self._locked():
            entries = self._read()
            if not isinstance(entries.get(key), dict):
                return None
            entries[key] = {**entries[key], **changes}
            self._write(entries)
            return dict(entries[key])

    def delete(self, *keys: str) -> None:
        with self._locked():
            entries = self._read()
            if not any(k in entries for k in keys):
                return
            for k in keys:
                entries.pop(k, None)
            self._write(entries)

    # -- checks (afk doctor) -----------------------------------------------------------

    def problems(self) -> list[str]:
        """What is wrong with the directory, its files' modes, or decryption."""
        out = []
        if not self.directory.exists():
            return out
        mode = stat.S_IMODE(self.directory.stat().st_mode)
        if mode & 0o077:
            out.append(f"{self.directory} is mode {mode:o}; it should be 700")
        for path in (self.path, self.salt_path):
            if path.exists():
                mode = stat.S_IMODE(path.stat().st_mode)
                if mode & 0o077:
                    out.append(f"{path} is mode {mode:o}; it should be 600")
        if self.path.exists():
            try:
                with self._locked():
                    self._read()
            except VaultError as exc:
                out.append(str(exc))
        return out


def _write_private(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically, readable by the owner only."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
