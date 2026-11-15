"""The names Kranto's hooks accept, for hooks that run alone (``python3 <plugin>/hooks/x.py``,
without the package on the path).

Run from the wheel (``--plugin-dir``, the console), the package's ``product.py`` and ``legacy.py``
sit two folders up and are loaded by path (both are stdlib only), so an install made before the
rename is known by the names it still uses. A plugin copied elsewhere (a marketplace install) has
neither: then a config folder holding a token store (``tokens/index.json``) is one of Kranto's,
and its name a server's name, as that old install keeps its own folder and name. Stdlib only;
nothing here reads a secret.
"""
from __future__ import annotations

import contextlib
import importlib.util
import re
import sys
from pathlib import Path

NEW = "kranto"
_PKG = Path(__file__).resolve().parents[2]
_NAME = re.compile(r"[a-z][a-z0-9]{0,30}")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def legacy():
    """The package's ``legacy`` module when the plugin runs from it, else None."""
    if "legacy" in sys.modules:
        return sys.modules["legacy"]
    if not ((_PKG / "legacy.py").is_file() and (_PKG / "product.py").is_file()):
        return None
    try:
        _load("product", _PKG / "product.py")
        return _load("legacy", _PKG / "legacy.py")
    except Exception:  # noqa: BLE001 - a hook never fails on this; the fallback answers
        sys.modules.pop("legacy", None)
        return None


def store_folders() -> list[Path]:
    """Folders under ``~/.config`` that hold a Kranto token store."""
    base = Path.home() / ".config"
    with contextlib.suppress(OSError):
        return [d for d in sorted(base.iterdir())
                if _NAME.fullmatch(d.name) and (d / "tokens" / "index.json").is_file()]
    return []


def config_dirs() -> list[Path]:
    """Kranto's config folders, new name first, whether they exist or not."""
    lg = legacy()
    found = list(lg.config_dirs(Path.home())) if lg else [Path.home() / ".config" / NEW]
    return found + [d for d in store_folders() if d not in found]


def servers() -> tuple[str, ...]:
    """The MCP server names Kranto answers to: its own, and the old one on an old install."""
    lg = legacy()
    if lg:
        return (lg.product.MCP_SERVER, lg.MCP_SERVER)
    return tuple(dict.fromkeys([NEW] + [d.name for d in store_folders()]))
