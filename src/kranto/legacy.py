"""Names from before the product was called Kranto, still honoured on an install made then.

This is the only module that holds them; a test refuses them anywhere else. Nothing here moves
or renames a file: an old install keeps its folders, unit and settings file, and Kranto reads
them where they are. A new install gets the names in ``product``.

Standard library only, imports nothing of Kranto but ``product``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from . import product
except ImportError:      # the update helper's copy under <home>/update/, beside product.py
    import product  # type: ignore[no-redef]

_OLD = "be" + "ars"   # written in two parts so a search for the old name finds it here only

COMMAND = _OLD                                         # the alias command, kept until 1.0
COMMANDS = (_OLD, "afk", "brb")                        # executables an old tool put on PATH
TOOL = _OLD                                            # the uv tool an old install lives in
# A release in the old shape (K0: the one release that crosses an old install over): three
# wheels, the real code under its old distribution name, an empty one the old helper still
# asks for, and the meta-package that carries the commands.
COMPAT_META = _OLD
COMPAT_SERVER = f"{_OLD}afk"
COMPAT_PAGE = f"{_OLD}brb"
COMPAT_DISTS = (COMPAT_META, COMPAT_SERVER, COMPAT_PAGE)
OLD_PACKAGE = f"{_OLD}afk"   # the server's import package before the rename (its loggers' names)

ENV_PREFIXES = (_OLD.upper() + "_", _OLD.upper() + "BRB_", _OLD.upper() + "AFK_")
# variables that were named after one half of the old pair, and the name each has now
ENV_RENAMED = {
    "AFK_HOME": "KRANTO_HOME",
    "AFK_NOTIFY_URLS": "KRANTO_NOTIFY_URLS",
    "AFK_TEST_NOTIFY_URLS": "KRANTO_TEST_NOTIFY_URLS",
    "BRB_LOOP_HOME": "KRANTO_LOOP_HOME",
    "BRB_" + _OLD.upper() + "AFK_URL": "KRANTO_SERVER_URL",
}

HOME_FILES = (f"{_OLD}.yaml", f"{_OLD}afk.yaml")       # a home's settings file, newest first
DB_FILE = f"{_OLD}afk.db"                              # a home's library
CONFIG_DIR = _OLD                                      # ~/.config/<this>
UNIT = f"{_OLD}.service"                               # the unit an old install runs as
ADOPT_UNIT = f"{_OLD}afk.service"                      # the server-only unit `adopt` replaces
DEFAULT_HOME = f"~/.{_OLD}"
WORKSPACE = f"~/{_OLD}afk-kb"                          # the server-only install's home
LOOP_HOME = "~/brb-loop"
COOKIE = f"{_OLD}_session"
MCP_SERVER = _OLD
DISTS = (f"{_OLD}afk", _OLD, f"{_OLD}brb")             # distributions an old install has
# the page's settings file (loop.yaml): its section for the server, on an old install
LOOP_SECTION = f"{_OLD}afk"
# stored outside Kranto: the draft's field in a Sanity document, the keys of exported traces
SANITY_META = f"{_OLD}Meta"
TRACE_PREFIX = _OLD
# the browser's stored keys, read once when the new one is missing (legacy.ts holds the page's)
BROWSER_KEYS = tuple(f"{_OLD}.{k}" for k in ("theme", "look", "look.custom", "layout"))


def new_env_name(name: str) -> str | None:
    """The variable's name now, or None when ``name`` is not an old one."""
    if name in ENV_RENAMED:
        return ENV_RENAMED[name]
    for prefix in ENV_PREFIXES:
        if name.startswith(prefix):
            return product.ENV_PREFIX + name[len(prefix):]
    return None


def adopt_env(environ: os._Environ[str] | dict[str, str] | None = None) -> list[str]:
    """Copy each old variable to its new name when the new one is unset (so a unit file, a
    drop-in or a shell written before the rename keeps working). Returns the old names seen."""
    env = os.environ if environ is None else environ
    seen = []
    for name, value in list(env.items()):
        new = new_env_name(name)
        if new:
            seen.append(name)
            env.setdefault(new, value)
    return seen


def old_env_names(environ: os._Environ[str] | dict[str, str] | None = None) -> list[str]:
    """The variables set under an old name (the doctor's notice, a test's isolation)."""
    env = os.environ if environ is None else environ
    return [n for n in env if new_env_name(n)]


def forget_env(environ: os._Environ[str] | dict[str, str] | None = None) -> None:
    """Drop every old variable, and its adopted copy where the copy came from it (a test's
    isolation from the developer's shell)."""
    env = os.environ if environ is None else environ
    for name in old_env_names(env):
        new = new_env_name(name)
        if new and env.get(new) == env.get(name):
            env.pop(new, None)
        env.pop(name, None)


def loop_settings(user: dict[str, Any]) -> dict[str, Any]:
    """loop.yaml as written: its section for the server under its old name counts as
    ``kranto`` when there is no ``kranto`` section (the file is never rewritten for it)."""
    if isinstance(user, dict) and LOOP_SECTION in user and "kranto" not in user:
        user = {**user, "kranto": user[LOOP_SECTION]}
        del user[LOOP_SECTION]
    return user


def home_file(root: Path) -> Path:
    """A home's settings file: ``kranto.yaml``, else an old name that exists, else the new."""
    new = Path(root) / product.HOME_FILE
    if new.is_file():
        return new
    for name in HOME_FILES:
        old = Path(root) / name
        if old.is_file():
            return old
    return new


def home_files(root: Path) -> list[Path]:
    """Every name a home's settings file may have, the new first."""
    return [Path(root) / n for n in (product.HOME_FILE, *HOME_FILES)]


def db_file(data_dir: Path) -> Path:
    """A home's library: ``kranto.db``, else the old name when only it exists."""
    new = Path(data_dir) / product.DB_FILE
    old = Path(data_dir) / DB_FILE
    return old if old.is_file() and not new.exists() else new


def config_dir(user_home: Path) -> Path:
    """``~/.config/kranto``, or the old folder when only it exists (it is never moved)."""
    base = Path(user_home) / ".config"
    new, old = base / product.CONFIG_DIR, base / CONFIG_DIR
    return old if old.is_dir() and not new.exists() else new


def config_dirs(user_home: Path | str = "~") -> tuple[Path, Path]:
    """Both folders, for the checks that must guard either (secrets, the sandbox's hides)."""
    base = Path(user_home) / ".config"
    return base / product.CONFIG_DIR, base / CONFIG_DIR


def unit_dir(environ: os._Environ[str] | dict[str, str] | None = None,
             user_home: Path | str | None = None) -> Path:
    """The user's systemd unit folder (``$XDG_CONFIG_HOME/systemd/user``)."""
    env = os.environ if environ is None else environ
    home = Path(user_home or env.get("HOME") or Path.home())
    xdg = env.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else home / ".config") / "systemd" / "user"


def unit_name(environ: os._Environ[str] | dict[str, str] | None = None,
              user_home: Path | str | None = None) -> str:
    """The unit this install runs as: ``$KRANTO_UNIT`` (or its old name), else the old unit
    when only it is installed (an install made before the rename, whose unit names nothing),
    else ``kranto.service``. What an update restarts, and whose stores the doors read."""
    env = os.environ if environ is None else environ
    named = env.get(product.ENV_PREFIX + "UNIT") or env.get(ENV_PREFIXES[0] + "UNIT")
    if named:
        return named
    d = unit_dir(env, user_home)
    if (d / UNIT).exists() and not (d / product.UNIT).exists():
        return UNIT
    return product.UNIT


def is_default_unit(unit: str) -> bool:
    """The install's own unit, new name or old: its stores have no suffix."""
    return unit in (product.UNIT, UNIT)


def unit_store(kind: str, environ: os._Environ[str] | dict[str, str] | None = None,
               user_home: Path | str | None = None) -> Path:
    """A per-unit folder under the config folder (``tokens``, ``claude``, ``home``): the plain
    name for the install's own unit, ``<kind>.<unit>`` for another (a scratch instance). The
    config folder is the old one when only it exists (``config_dir``)."""
    env = os.environ if environ is None else environ
    home = Path(user_home or env.get("HOME") or Path.home())
    unit = unit_name(env, home)
    name = kind if is_default_unit(unit) else f"{kind}.{unit.removesuffix('.service')}"
    return config_dir(home) / name


def mcp_server_for(invoked: str | None) -> str:
    """The MCP server's name for the command it was started as: the old command serves the old
    names (``<old>_status``), so a client added long ago and its allow-lists keep matching."""
    return MCP_SERVER if invoked and Path(invoked).name == COMMAND else product.MCP_SERVER


# Claude Code's names for the tools, by server: the plugin's hooks accept both
MCP_ALLOW_PREFIXES = tuple(f"mcp__{s}__{s}_" for s in (product.MCP_SERVER, MCP_SERVER))


def alias_notice() -> str:
    """What the old command says on a terminal, once a day."""
    return f"{_OLD} is now {product.COMMAND}; both commands work."


def live_homes() -> tuple[str, ...]:
    """The folders an install made before the rename keeps its data in (the preview never
    serves them)."""
    return (WORKSPACE, LOOP_HOME, "~/tasks")
