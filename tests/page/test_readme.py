"""The front door: the README installs Kranto from a release's wheels as the server's setup guide
does (a git install has no built page), every relative link in it resolves, and the package
metadata describes the product."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text()
INSTALL = ("tag=$(gh release view -R iddv/kranto --json tagName --jq .tagName)\n"
           "gh release download \"$tag\" -R iddv/kranto -p '*.whl' -p SHA256SUMS -D "
           "\"kranto-$tag\"\n"
           "(cd \"kranto-$tag\" && sha256sum -c SHA256SUMS)\n"
           # the extras install.sh installs (a posting account needs connections)
           "uv tool install --python 3.12 \"kranto[connections,notify,mcp] @ "
           "file://$(ls \"$PWD/kranto-$tag\"/kranto-*.whl)\"\n"
           "kranto up")


def test_no_install_from_git():
    docs = README + (ROOT / "docs" / "mcp.md").read_text()
    assert not [x for x in docs.splitlines() if "uv tool install" in x and "git+" in x]


def test_kranto_is_installed_first():
    assert INSTALL in README
    assert README.index(INSTALL) < README.index("## Usage reports")
    assert "## Research history" not in README and "src/kranto/page/lab/" not in README   # the lab left


def test_every_relative_link_resolves():
    links = re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", README)
    missing = [x for x in links if not x.startswith(("http://", "https://", "mailto:"))
               and not (ROOT / x).exists()]
    assert missing == []


def test_the_package_says_what_it_is():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "Kranto" in meta["description"] and "POC" not in meta["description"]
    assert meta["license"] == "Apache-2.0" and meta["readme"] == "README.md"
    assert all("email" not in a for a in meta["authors"])
