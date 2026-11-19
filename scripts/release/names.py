#!/usr/bin/env python3
"""The names the release scripts compute from, read from the tree they run in: the published
project (``public.toml``), the product's names (``src/kranto/product.py``) and the names an old
install still uses (``src/kranto/legacy.py``, the one place that holds them). The two modules
are loaded by path, so a script needs no install of Kranto and no ``sys.path`` change.

    names.py repo            the repository releases are published to (public.toml's repo)
    names.py dist            the release's one distribution (product.DIST)
    names.py command         the product's command
    names.py alias           the command's old name (legacy.COMMAND): only an old install has it
    names.py compat          the old shape's three distributions, meta first (one a line)
    names.py old-env VAR     the old names of the variable VAR (KRANTO_UNIT: each name an
                             install made before the rename reads instead), one a line
    names.py units           the units a real install runs as, the product's and the old one
    names.py config-dirs     ~/.config's folder names, the product's and the old one
    names.py home-files      a home's settings file names, the product's first
    names.py db-files        a home's library names (under data/), the product's first

Standard library only.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def product(root: Path = ROOT) -> ModuleType:
    return _load("release_product", root / "src" / "kranto" / "product.py")


def legacy(root: Path = ROOT) -> ModuleType:
    """legacy.py imports ``product`` (``from . import product``, else ``import product``): the
    second form finds the copy loaded here, for the time of the load only."""
    saved = sys.modules.get("product")
    sys.modules["product"] = product(root)
    try:
        return _load("release_legacy", root / "src" / "kranto" / "legacy.py")
    finally:
        if saved is None:
            sys.modules.pop("product", None)
        else:
            sys.modules["product"] = saved


def public(root: Path = ROOT) -> dict:
    return tomllib.loads((root / "public.toml").read_text())


def repo(root: Path = ROOT) -> str:
    """OWNER/NAME of the one repository releases are published to."""
    return public(root).get("repo") or product(root).REPO


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    what = argv[0] if argv else ""
    if what == "repo":
        print(repo())
    elif what == "dist":
        print(product().DIST)
    elif what == "command":
        print(product().COMMAND)
    elif what == "alias":
        print(legacy().COMMAND)
    elif what == "compat":
        print("\n".join(legacy().COMPAT_DISTS))
    elif what == "old-env" and len(argv) == 2:
        print("\n".join(old_env(argv[1])))
    elif what == "units":
        print("\n".join((product().UNIT, legacy().UNIT)))
    elif what == "config-dirs":
        print("\n".join((product().CONFIG_DIR, legacy().CONFIG_DIR)))
    elif what == "home-files":
        print("\n".join((product().HOME_FILE, *legacy().HOME_FILES)))
    elif what == "db-files":
        print("\n".join((product().DB_FILE, legacy().DB_FILE)))
    else:
        print("usage: names.py repo|dist|command|alias|compat|old-env VAR|units|config-dirs|"
              "home-files|db-files", file=sys.stderr)
        return 2
    return 0


def old_env(var: str, root: Path = ROOT) -> list[str]:
    """The names an install made before the rename reads for the variable ``var`` (legacy's
    renames and prefixes, inverted)."""
    lg, prefix = legacy(root), product(root).ENV_PREFIX
    out = [old for old, new in lg.ENV_RENAMED.items() if new == var]
    if var.startswith(prefix):
        out += [p + var[len(prefix):] for p in lg.ENV_PREFIXES]
    return [n for n in dict.fromkeys(out) if lg.new_env_name(n) == var]


if __name__ == "__main__":
    sys.exit(main())
