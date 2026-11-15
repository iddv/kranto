"""The one distribution: its commands' entry point is ``kranto.launcher:main`` (``kranto``, and
the command's old name as an alias), its wheel holds the server, the page and the cub SDK, and
``kranto --version`` finds the distribution by the ``kranto`` package it provides, not by its
name."""
import tomllib
from pathlib import Path

from kranto import launcher

ROOT = Path(__file__).resolve().parents[1]


def test_both_commands_are_the_launcher():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())
    scripts = meta["project"]["scripts"]
    assert scripts["kranto"] == "kranto.launcher:main"
    assert set(scripts.values()) == {"kranto.launcher:main"} and len(scripts) == 2
    wheel = meta["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["src/kranto", "src/bears_cub"]
    assert wheel["artifacts"] == ["src/kranto/page/ui/static/app/**"]


def test_versions_find_the_distribution_by_its_package_not_its_name(monkeypatch):
    import importlib.metadata as md

    asked = []

    def version(name):
        asked.append(name)
        return "9.9.9"
    monkeypatch.setattr(md, "packages_distributions", lambda: {"kranto": ["octo-owner.kranto"]})
    monkeypatch.setattr(md, "version", version)
    v = launcher.versions()
    assert v["kranto"] == "9.9.9" and asked[0] == "octo-owner.kranto"
    assert launcher.version_line(v) == "kranto 9.9.9"
