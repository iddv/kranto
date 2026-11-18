"""Where Kranto keeps its files: the homes, how each is found, and what is inside them.
The one module that knows these names.

A **kranto home** (``kranto_home()``: ``--home``, else ``$KRANTO_HOME``, else the home ``kranto
up`` or ``kranto adopt`` recorded, else ``~/.kranto``) is a workspace with the ``brb``
section on (``Layout``). The record is ``~/.config/kranto/home`` (``pointer_path()``), or the
installed unit's ``Environment=KRANTO_HOME``; another unit (``$KRANTO_UNIT``, the update's
scratch instance) keeps its own pointer, ``home.<unit>``, so it never moves the real one.

The **loop home** (``loop_home()``: the configured one, else ``$KRANTO_LOOP_HOME``, else
``~/kranto-loop``; the page also looks at the kranto install's ``brb.loop_home`` first) holds the
build loop's ledger, settings and control files (``LoopLayout``).

Standard library only. Kept byte-identical in the server (``src/kranto/paths.py``) and the page
(``src/kranto/page/paths.py``); a test compares them, as for ``tokens.py``.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from kranto import legacy, product

KRANTO_HOME_ENV = "KRANTO_HOME"
LOOP_HOME_ENV = "KRANTO_LOOP_HOME"
UNIT_ENV = "KRANTO_UNIT"
DEFAULT_UNIT = product.UNIT
DEFAULT_KRANTO_HOME = product.DEFAULT_HOME
DEFAULT_LOOP_HOME = product.DEFAULT_LOOP_HOME


# -- finding the homes --------------------------------------------------------------------------
def unit_name() -> str:
    """The systemd user unit Kranto runs as: ``$KRANTO_UNIT``, else ``kranto.service``."""
    return os.environ.get(UNIT_ENV) or DEFAULT_UNIT


def pointer_path(user_home: Path, unit: str | None = None) -> Path:
    """Where ``kranto up`` and ``kranto adopt`` record the home they set up, so every command
    finds it without ``--home``: ``~/.config/kranto/home``, or ``home.<name>`` for another
    unit."""
    unit = unit or unit_name()
    name = (
        "home" if unit in (DEFAULT_UNIT, legacy.UNIT) else f"home.{unit.removesuffix('.service')}"
    )
    return legacy.config_dir(Path(user_home)) / name


def read_pointer(user_home: Path, unit: str | None = None) -> Path | None:
    """The home the pointer names, or None (no pointer, or an empty one)."""
    try:
        text = pointer_path(user_home, unit).read_text().strip()
    except OSError:
        return None
    return Path(text).expanduser() if text else None


def unit_dir(user_home: Path) -> Path:
    return Path(user_home) / ".config" / "systemd" / "user"


def unit_env(text: str, user_home: Path) -> dict[str, str]:
    """``Environment=`` values of a unit file's text (``KEY=value``, quoted or not), ``%h``
    expanded."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'\s*Environment="?([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').replace("%h", str(user_home))
    return out


def unit_home(user_home: Path, units: Path | None = None, unit: str | None = None) -> Path | None:
    """The installed unit's ``KRANTO_HOME`` (or its old name, ``legacy.adopt_env``), or None."""
    try:
        text = ((units or unit_dir(user_home)) / (unit or unit_name())).read_text()
    except OSError:
        return None
    env = unit_env(text, Path(user_home))
    legacy.adopt_env(env)
    found = env.get(KRANTO_HOME_ENV)
    return Path(found).expanduser() if found else None


def recorded_home(
    user_home: Path, units: Path | None = None, unit: str | None = None
) -> Path | None:
    """The home ``kranto up`` or ``kranto adopt`` recorded, else the installed unit's
    ``KRANTO_HOME``; None when there is neither."""
    return read_pointer(user_home, unit) or unit_home(user_home, units, unit)


def kranto_home(
    explicit: str | Path | None = None,
    user_home: Path | None = None,
    units: Path | None = None,
    unit: str | None = None,
    default: str | None = DEFAULT_KRANTO_HOME,
) -> Path | None:
    """``explicit`` (``--home``), else ``$KRANTO_HOME``, else the recorded home, else
    ``default`` (``~/.kranto``; None: return None), resolved."""
    found = explicit or os.environ.get(KRANTO_HOME_ENV)
    if not found and user_home is not None:
        found = recorded_home(user_home, units, unit)
    found = found or default
    return Path(found).expanduser().resolve() if found else None


def loop_home(configured: str | Path | None = None) -> Path:
    """``configured`` (``brb.loop_home``, ``--home``), else ``$KRANTO_LOOP_HOME``, else
    ``~/kranto-loop``, resolved."""
    return (
        Path(configured or os.environ.get(LOOP_HOME_ENV) or DEFAULT_LOOP_HOME)
        .expanduser()
        .resolve()
    )


# -- inside them --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Layout:
    """A kranto home's top level. ``config`` is ``kranto.yaml``, or the settings file of a home
    made before the rename (``legacy.home_file``)."""

    root: Path

    @property
    def config(self) -> Path:
        return legacy.home_file(self.root)

    data = property(lambda self: self.root / "data")  # kranto.db, secrets/, locks
    db = property(lambda self: legacy.db_file(self.root / "data"))
    secrets = property(lambda self: self.root / "data" / "secrets")
    env_file = property(lambda self: self.root / ".env")  # the model key; never read here
    loop = property(lambda self: self.root / "loop")  # the default loop home
    tasks = property(lambda self: self.root / "tasks")  # the default task folder
    prompts = property(lambda self: self.root / "prompts")  # the owner's prompt versions
    corpus = property(lambda self: self.root / "corpus")  # the regression corpus
    plugins = property(lambda self: self.root / "plugins")
    mcp_servers = property(lambda self: self.root / "mcp-servers")
    capabilities = property(lambda self: self.root / "capabilities")
    targets = property(lambda self: self.root / "targets")
    update = property(lambda self: self.root / "update")  # state, staged releases, logs
    backups = property(lambda self: self.root / "backups")


@dataclass(frozen=True)
class LoopLayout:
    """A loop home's entries."""

    root: Path

    settings = property(lambda self: self.root / "loop.yaml")  # the loop's settings store
    db = property(lambda self: self.root / "loop.db")  # the ledger
    lock = property(lambda self: self.root / "daemon.lock")  # held while the loop ticks
    pid = property(lambda self: self.root / "daemon.pid")
    log = property(lambda self: self.root / "daemon.log")
    stop = property(lambda self: self.root / "STOP")  # ask the loop to stop
    pause = property(lambda self: self.root / "PAUSE")  # no new work while present
    inbox = property(lambda self: self.root / "inbox")
    # chat/ (threads from before 0.3.70, when the chat was removed) stays on disk, unread
    term = property(lambda self: self.root / "term")  # Open in Claude Code's sessions
    actions = property(lambda self: self.root / "actions.jsonl")  # every registry action run
    maintain = property(lambda self: self.root / "maintain")
    projects = property(lambda self: self.root / "projects")
    publish = property(lambda self: self.root / "publish")
