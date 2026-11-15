#!/usr/bin/env python3
"""The old shape's three wheels, built from the same tree as the one-wheel release.

An install made before the rename updates with its own, older helper: it installs exactly three
distributions by their old names (``legacy.COMPAT_DISTS``) and refuses any other wheel. The one
release that crosses such an install over carries them:

- the server's name (``legacy.COMPAT_SERVER``): the real wheel (``src/kranto``,
  ``src/bears_cub``, the page's built files, the same dependencies and extras) under that name,
  with no commands;
- the page's name (``legacy.COMPAT_PAGE``): an empty distribution the old helper still asks for;
- the meta-package (``legacy.COMPAT_META``): no code; it depends on the other two at this
  version (``mcp`` passed on as the server's ``mcp`` extra) and carries both commands, the
  product's and its old name, each the real pyproject.toml's entry point for the product's.

Each is built by ``uv build`` from its own temporary tree; the checkout is never edited. The
page must already be built (``build.sh`` runs ``scripts/dev/build_ui.py`` first).

    compat_wheels.py --src CHECKOUT --dist FOLDER --version V

Standard library plus ``uv``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import names  # noqa: E402

BUILD_SYSTEM = ('[build-system]\nrequires = ["hatchling>=1.24"]\n'
                'build-backend = "hatchling.build"\n')
# the sections a renamed copy of the real pyproject.toml leaves out: the commands (the
# meta-package carries them) and the version from git (the copy has a fixed one)
DROPPED = ("project.scripts", "tool.hatch.version", "tool.hatch.version.raw-options")


class CompatError(Exception):
    pass


def _sections(text: str) -> list[tuple[str, str]]:
    """(table name, its text) in order; the text before the first table has the name ""."""
    out: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines(keepends=True):
        m = re.match(r"^\[\[?([^\]]+)\]\]?\s*(#.*)?$", line.strip())
        if m:
            out.append((m[1].strip(), [line]))
        else:
            out[-1][1].append(line)
    return [(name, "".join(lines)) for name, lines in out]


def server_pyproject(text: str, name: str, version: str) -> str:
    """The real pyproject.toml under ``name`` at ``version``, without its commands."""
    out = []
    for table, body in _sections(text):
        if table in DROPPED:
            continue
        if table == "project":
            body, n = re.subn(r'(?m)^name\s*=\s*"[^"]*"', f'name = "{name}"', body, count=1)
            body, v = re.subn(r'(?m)^dynamic\s*=\s*\["version"\]', f'version = "{version}"',
                              body, count=1)
            if n != 1 or v != 1:
                raise CompatError("pyproject.toml's [project] has no name or no dynamic "
                                  "version to replace")
        out.append(body)
    result = "".join(out)
    data = tomllib.loads(result)
    proj = data["project"]
    if proj.get("name") != name or proj.get("version") != version or "scripts" in proj:
        raise CompatError(f"the renamed pyproject.toml is wrong: {proj.get('name')} "
                          f"{proj.get('version')}, scripts {proj.get('scripts')}")
    want = tomllib.loads(text)["project"]
    if proj.get("dependencies") != want.get("dependencies") or \
            proj.get("optional-dependencies") != want.get("optional-dependencies"):
        raise CompatError("the renamed pyproject.toml lost a dependency or an extra")
    return result


def page_pyproject(name: str, version: str, product_name: str) -> str:
    return (BUILD_SYSTEM + "\n[project]\n" f'name = "{name}"\nversion = "{version}"\n'
            f'description = "Empty: what {product_name} was split into before, kept for '
            'the update that crosses an old install over."\nrequires-python = ">=3.12"\n'
            "\n[tool.hatch.build.targets.wheel]\nbypass-selection = true\n")


def meta_pyproject(name: str, server: str, page: str, version: str, commands: list[str],
                   entry: str, product_name: str) -> str:
    scripts = "".join(f'{c} = "{entry}"\n' for c in commands)
    return (BUILD_SYSTEM + "\n[project]\n" f'name = "{name}"\nversion = "{version}"\n'
            f'description = "{product_name}, installed under the name an install made before '
            'the rename updates."\nrequires-python = ">=3.12"\n'
            f'dependencies = ["{server}[connections,notify]=={version}", '
            f'"{page}=={version}"]\n'
            f'\n[project.optional-dependencies]\nmcp = ["{server}[mcp]=={version}"]\n'
            f"\n[project.scripts]\n{scripts}"
            "\n[tool.hatch.build.targets.wheel]\nbypass-selection = true\n")


def _ignore(directory: str, entries: list[str]) -> set[str]:
    skip = {e for e in entries if e in ("__pycache__", "node_modules") or e.endswith(".pyc")}
    if Path(directory).as_posix().endswith("kranto/page/ui") and "web" in entries:
        skip.add("web")          # the page's sources; its build is under static/app
    return skip


def server_tree(src: Path, into: Path, name: str, version: str) -> Path:
    into.mkdir(parents=True)
    (into / "pyproject.toml").write_text(
        server_pyproject((src / "pyproject.toml").read_text(), name, version))
    for f in ("README.md", "LICENSE", "NOTICE", ".gitignore"):
        if (src / f).is_file():
            shutil.copy2(src / f, into / f)
    for pkg in ("kranto", "bears_cub"):
        shutil.copytree(src / "src" / pkg, into / "src" / pkg, ignore=_ignore, symlinks=True)
    return into


def build(tree: Path, dist: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "SETUPTOOLS_SCM_PRETEND_VERSION"}
    r = subprocess.run(["uv", "build", "--wheel", "--out-dir", str(dist), str(tree)],
                       capture_output=True, text=True, env=env, check=False)
    if r.returncode != 0:
        raise CompatError(f"uv build {tree.name}: {(r.stderr or r.stdout).strip()[-800:]}")


def wheel_name(dist: str, version: str) -> str:
    return f"{dist}-{version}-py3-none-any.whl"


def entry_points(whl: Path) -> str:
    with zipfile.ZipFile(whl) as z:
        ep = [n for n in z.namelist() if n.endswith(".dist-info/entry_points.txt")]
        return z.read(ep[0]).decode() if ep else ""


def entry_of(src: Path, product) -> str:
    """The product's command's entry point in the real pyproject.toml (``pkg.module:func``)."""
    return tomllib.loads((src / "pyproject.toml").read_text())["project"]["scripts"][
        product.COMMAND]


def check(dist: Path, version: str, legacy, product, entry: str) -> list[Path]:
    """The three wheels, each what it must be; raises CompatError otherwise."""
    meta, server, page = (dist / wheel_name(n, version) for n in legacy.COMPAT_DISTS)
    for w in (meta, server, page):
        if not w.is_file():
            raise CompatError(f"{w.name} was not built")
    with zipfile.ZipFile(server) as z:
        files = z.namelist()
    module = entry.split(":", 1)[0].replace(".", "/") + ".py"
    if module not in files or "bears_cub/__init__.py" not in files:
        raise CompatError(f"{server.name} lacks the code")
    if "console_scripts" in entry_points(server):
        raise CompatError(f"{server.name} has commands; only the meta-package may")
    for w in (meta, page):
        with zipfile.ZipFile(w) as z:
            code = [n for n in z.namelist() if ".dist-info/" not in n]
        if code:
            raise CompatError(f"{w.name} carries files: {code[:3]}")
    eps = entry_points(meta)
    for c in (product.COMMAND, legacy.COMMAND):
        if not re.search(rf"(?m)^{re.escape(c)}\s*=\s*{re.escape(entry)}$", eps):
            raise CompatError(f"{meta.name} has no {c} command")
    return [meta, server, page]


def make(src: Path, dist: Path, version: str) -> list[Path]:
    legacy, product = names.legacy(src), names.product(src)
    meta, server, page = legacy.COMPAT_DISTS
    entry = entry_of(src, product)
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compat-wheels-") as tmp:
        t = Path(tmp)
        build(server_tree(src, t / server, server, version), dist)
        for dname, text in ((page, page_pyproject(page, version, product.NAME)),
                            (meta, meta_pyproject(meta, server, page, version,
                                                  [product.COMMAND, legacy.COMMAND],
                                                  entry, product.NAME))):
            (t / dname).mkdir()
            (t / dname / "pyproject.toml").write_text(text)
            build(t / dname, dist)
    return check(dist, version, legacy, product, entry)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", required=True, type=Path)
    p.add_argument("--dist", required=True, type=Path)
    p.add_argument("--version", required=True)
    a = p.parse_args(argv)
    try:
        for w in make(a.src.resolve(), a.dist.resolve(), a.version):
            print(w)
    except CompatError as exc:
        print(f"compat_wheels: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
