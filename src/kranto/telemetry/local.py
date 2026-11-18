"""The mode, and the lines kept on this machine (sections 3.4, 3.5, 4.2).

The mode is, first match wins: ``DO_NOT_TRACK`` set (anything but empty, 0 or false): off;
``KRANTO_TELEMETRY``; ``telemetry.mode`` in the config file; else ``local``. The file is read
again at most once a minute, so ``kranto telemetry off`` reaches a running server without a
restart.

``record(name, **fields)`` keeps one JSON line in ``<home>/telemetry/local/<day>.jsonl`` when
the mode is not ``off`` and a home is configured (``configure``): the fields the allow-list
lets through (``schema.clean_line``), a count of those it dropped, and the second it was
written (kept here, never sent in the basic tier). It never raises and never blocks on more
than one append. Nothing in this module opens a socket.

``<home>/telemetry/state.json`` is this install's telemetry state: the minute of the day its
report goes, the milestones reached, the detailed tier's install id and when it was made, and
the days built and sent."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from . import schema as schema_mod

MODES = ("off", "local", "basic", "detailed")
SENDING = ("basic", "detailed")
ENV_MODE = "KRANTO_TELEMETRY"
ENV_ENDPOINT = "KRANTO_TELEMETRY_ENDPOINT"
# The usage-report relay (a separate service: CloudFront in front of a function and a bucket
# in eu-west-1). Used only with basic or detailed chosen; the environment and the file override it.
DEFAULT_ENDPOINT = "https://dde6yrzwuxncv.cloudfront.net/v1/logs"
DNT = "DO_NOT_TRACK"
REFRESH_S = 60.0
LOCAL_DAYS = 14

log = logging.getLogger("kranto.telemetry")


class TelemetryError(ValueError):
    """A mode or endpoint that cannot be used; said to the person as it is."""


@dataclass(frozen=True)
class Settings:
    """``telemetry:`` as the config file says (the defaults when it has none or is broken)."""

    mode: str = "local"
    endpoint: str | None = None
    answered_at: str | None = None


@dataclass(frozen=True)
class Effective:
    mode: str
    why: str                 # DO_NOT_TRACK, KRANTO_TELEMETRY, config, default
    endpoint: str | None
    endpoint_from: str          # KRANTO_TELEMETRY_ENDPOINT, config, default
    answered_at: str | None
    answered: bool


def dnt(environ=None) -> bool:
    v = (environ if environ is not None else os.environ).get(DNT)
    return v is not None and v.strip().lower() not in ("", "0", "false", "no")


def check_endpoint(url: str) -> str:
    """An endpoint Kranto may post to: ``https://``, ``http://`` to loopback only, or
    ``file:///dir`` (payloads written to a directory). Raises ``TelemetryError``."""
    from urllib.parse import urlparse

    u = urlparse(str(url).strip())
    if u.scheme == "https" and u.hostname:
        return url.strip()
    if u.scheme == "http" and (u.hostname or "") in ("127.0.0.1", "localhost", "::1"):
        return url.strip()
    if u.scheme == "file" and u.path.startswith("/") and not u.netloc:
        return url.strip()
    raise TelemetryError("an endpoint is https://..., http:// to 127.0.0.1, or file:///a/dir")


def parse(raw) -> Settings:
    """``telemetry:`` from the file. Raises ``TelemetryError`` on a bad value."""
    raw = dict(raw or {})
    if raw.get("mode") is False:              # YAML 1.1 reads a bare off as false
        raw["mode"] = "off"
    unknown = set(raw) - {"mode", "endpoint", "answered_at"}
    if unknown:
        raise TelemetryError(f"unknown keys in telemetry: {', '.join(sorted(map(str, unknown)))}")
    mode = raw.get("mode", "local")
    if mode not in MODES:
        raise TelemetryError(f"telemetry.mode must be one of {', '.join(MODES)}")
    endpoint = raw.get("endpoint")
    if endpoint is not None:
        endpoint = check_endpoint(endpoint)
    answered = raw.get("answered_at")
    return Settings(mode=mode, endpoint=endpoint,
                    answered_at=str(answered) if answered is not None else None)


def settings(home: Path) -> Settings:
    from .. import config as config_mod

    path = config_mod.config_path(Path(home))
    try:
        raw = yaml.safe_load(path.read_text()) if path else {}
        return parse((raw or {}).get("telemetry"))
    except (OSError, yaml.YAMLError, TelemetryError, AttributeError, TypeError):
        return Settings()


def effective(home: Path | None, environ=None) -> Effective:
    env = environ if environ is not None else os.environ
    s = settings(home) if home is not None else Settings()
    endpoint, endpoint_from = (s.endpoint, "config") if s.endpoint else \
        (DEFAULT_ENDPOINT, "default")
    if env.get(ENV_ENDPOINT):
        try:
            endpoint, endpoint_from = check_endpoint(env[ENV_ENDPOINT]), ENV_ENDPOINT
        except TelemetryError:
            log.warning("%s is not an endpoint Kranto posts to; ignored", ENV_ENDPOINT)
    from .. import preview
    if preview.enabled(home, env):
        # the preview never reports, whatever the copied setting says (line 3). Its
        # unit and 'kranto serve' set DO_NOT_TRACK, so the reason every reader knows is the true one
        return Effective("off", DNT, endpoint, endpoint_from, s.answered_at, True)
    if dnt(env):
        return Effective("off", DNT, endpoint, endpoint_from, s.answered_at, True)
    if env.get(ENV_MODE) in MODES:
        return Effective(env[ENV_MODE], ENV_MODE, endpoint, endpoint_from, s.answered_at, True)
    if s.answered_at is not None or s.mode != "local":
        # a mode written by hand is an answer too
        return Effective(s.mode, "config", endpoint, endpoint_from, s.answered_at, True)
    return Effective("local", "default", endpoint, endpoint_from, None, False)


# -- the process's recorder ------------------------------------------------------------------

_lock = threading.Lock()
_home: Path | None = None
_mode: tuple[float, str] = (0.0, "off")


def configure(home: Path | str | None) -> None:
    """Where this process's lines go (None: nowhere). ``kranto serve`` calls it once."""
    global _home, _mode
    with _lock:
        _home = Path(home) if home is not None else None
        _mode = (0.0, "off")
    schema_mod.reset()


def configured() -> Path | None:
    return _home


def current_mode() -> str:
    """The mode, read again at most once a minute."""
    global _mode
    home = _home
    if home is None:
        return "off"
    now = time.monotonic()
    at, mode = _mode
    if now - at < REFRESH_S and at:
        return mode
    try:
        mode = effective(home).mode
    except Exception:  # noqa: BLE001 - a broken file counts nothing, it never fails a request
        mode = "off"
    _mode = (now, mode)
    return mode


def refresh() -> None:
    """Forget the cached mode (after the mode was set)."""
    global _mode
    _mode = (0.0, "off")


def tdir(home: Path) -> Path:
    return Path(home) / "telemetry"


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


def record(name: str, **fields) -> None:
    """Keep one line, through the allow-list. Never raises."""
    try:
        home = _home
        if home is None or current_mode() == "off":
            return
        kept, dropped = schema_mod.clean_line(name, fields)
        now = time.time()
        line = {"e": name, "ts": int(now), **(kept or {})} if kept is not None else \
            {"e": "dropped"}
        if dropped:
            line["_dropped"] = dropped
        d = tdir(home) / "local"
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(d / f"{day_of(now)}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 - telemetry never breaks what it watches
        log.debug("telemetry line not kept", exc_info=True)


def lines(home: Path, day: str) -> list[dict]:
    """A day's lines, the unreadable ones skipped."""
    out = []
    try:
        text = (tdir(home) / "local" / f"{day}.jsonl").read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


# -- state -----------------------------------------------------------------------------------

def state_path(home: Path) -> Path:
    return tdir(home) / "state.json"


def read_state(home: Path) -> dict:
    try:
        st = json.loads(state_path(home).read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(home: Path, st: dict) -> None:
    p = state_path(home)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = p.with_name(f".state.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, p)
