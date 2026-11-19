"""The front door's install lines: one curl line for install.sh, then one block, the same in
the setup guide and the README, that installs a release's wheel (what ``kranto update``
installs), never a git checkout: a wheel built from git has no built web page."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "setup.md"
DOCS = (GUIDE, ROOT / "README.md")


BASE = "https://github.com/iddv/kranto/releases"
ONE_LINE = f"curl -fsSL {BASE}/latest/download/install.sh | sh"


def install_block(text: str) -> list[str]:
    """The lines from ``base=…/releases/latest/download`` to the ``uv tool install`` that ends
    it, spaces collapsed."""
    m = re.search(r"^base=https://github\.com/iddv/kranto/releases/latest/download\n"
                  r"(?:[^\n]*\n)*?uv tool install[^\n]*\n", text, re.M)
    assert m, "no release install block"
    return [" ".join(line.split()) for line in m.group(0).splitlines()]


def test_the_guide_and_the_readme_install_the_same_way():
    want = install_block(GUIDE.read_text())
    for doc in DOCS[1:]:
        assert install_block(doc.read_text()) == want, doc


def test_the_block_installs_a_releases_verified_wheel_with_no_login():
    base, sums, wheel, download, check, install = install_block(GUIDE.read_text())
    assert base == f"base={BASE}/latest/download"
    assert sums == 'curl -fsSLO "$base/SHA256SUMS"'
    assert wheel == "wheel=$(grep -o 'kranto-[^ ]*\\.whl' SHA256SUMS)"
    assert download == 'curl -fsSLO "$base/$wheel"'
    assert check == "sha256sum -c --ignore-missing SHA256SUMS"
    # the one wheel, by path (a name on an index could be another project's), with the extras
    # install.sh installs (connections: a posting account; notify; mcp), so both installs are one
    assert install == ('uv tool install --python 3.12 "kranto[connections,notify,mcp] @ '
                       'file://$PWD/$wheel"')
    assert "kranto[connections,notify,mcp] @ file://$WHEEL" in (ROOT / "install.sh").read_text()


def test_the_one_line_install_is_first_in_both():
    for doc in DOCS:
        text = doc.read_text()
        assert ONE_LINE in text, doc
        assert text.index(ONE_LINE) < text.index("base=https://github.com"), doc


def test_no_doc_needs_a_github_login_to_install():
    """A public repository: the README and the guide install with curl, never gh, and speak of
    no invitation and of no time before the repository was public."""
    readme = (ROOT / "README.md").read_text()
    guide = GUIDE.read_text()
    for name, text in (("README.md", readme), ("docs/setup.md", guide)):
        flat = " ".join(text.split())
        for words in ("gh release", "invitation", "gh auth status",
                      "before the repository is public", "No stable release is out yet"):
            assert words not in flat, (name, words)


def test_no_doc_installs_kranto_from_git():
    for doc in DOCS:
        for line in doc.read_text().splitlines():
            if "uv tool install" in line:
                assert "git+" not in line, (doc, line)
    guide = GUIDE.read_text()
    assert "git+" not in guide and "setup-git" not in guide


def test_the_guide_says_kranto_is_not_on_pypi():
    guide = " ".join(GUIDE.read_text().split())
    assert "Kranto is not on PyPI" in guide


def test_the_readme_sends_a_newcomer_to_the_setup_guide():
    head = (ROOT / "README.md").read_text().split("## ")[0]
    assert "[docs/setup.md](docs/setup.md)" in head


def test_the_wheel_is_the_kranto_distribution_in_this_repo():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert meta["name"] == "kranto" and meta["scripts"]["kranto"]
    readme = (ROOT / "README.md").read_text()
    assert readme.index(ONE_LINE) < readme.index("## Who it is for")
