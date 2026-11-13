"""The front door's install lines are one block, the same in the setup guide and the README,
and it installs a release's wheel (what ``kranto update`` installs), never a git checkout: a
wheel built from git has no built web page."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "setup.md"
DOCS = (GUIDE, ROOT / "README.md")


def install_block(text: str) -> list[str]:
    """The lines from ``tag=$(gh release view`` to the ``uv tool install`` that ends it, spaces
    collapsed."""
    m = re.search(r"^tag=\$\(gh release view[^\n]*\n(?:[^\n]*\n)*?uv tool install[^\n]*\n",
                  text, re.M)
    assert m, "no release install block"
    return [" ".join(line.split()) for line in m.group(0).splitlines()]


def test_the_guide_and_the_readme_install_the_same_way():
    want = install_block(GUIDE.read_text())
    for doc in DOCS[1:]:
        assert install_block(doc.read_text()) == want, doc


def test_the_block_installs_a_releases_verified_wheel():
    tag, download, check, install = install_block(GUIDE.read_text())
    assert tag == "tag=$(gh release view -R iddv/kranto --json tagName --jq .tagName)"
    assert download.startswith('gh release download "$tag" -R iddv/kranto')
    assert "'*.whl'" in download and "SHA256SUMS" in download
    assert check == '(cd "kranto-$tag" && sha256sum -c SHA256SUMS)'
    # the one wheel, by path (a name on an index could be another project's)
    assert install == 'uv tool install --python 3.12 "kranto-$tag"/kranto-*.whl'


def test_no_doc_installs_kranto_from_git():
    for doc in DOCS:
        for line in doc.read_text().splitlines():
            if "uv tool install" in line:
                assert "git+" not in line, (doc, line)
    guide = GUIDE.read_text()
    assert "git+" not in guide and "setup-git" not in guide


def test_the_guide_says_what_changes_once_public():
    guide = " ".join(GUIDE.read_text().split())
    assert "once the repository is public" in guide and "PyPI" in guide


def test_the_readme_sends_a_newcomer_to_the_setup_guide():
    head = (ROOT / "README.md").read_text().split("## ")[0]
    assert "[docs/setup.md](docs/setup.md)" in head


def test_the_wheel_is_the_kranto_distribution_in_this_repo():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert meta["name"] == "kranto" and meta["scripts"]["kranto"]
    readme = (ROOT / "README.md").read_text()
    assert readme.index("kranto up") < readme.index("## Who it is for")
