"""What a cub author reads is complete and current: the protocol is in this repository, and
the SDK pin in the guide is one tag of a Kranto release, and the cub to start from is one Kranto
ships (the project keeps no collection of cubs elsewhere)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "docs" / "cubs.md").read_text()
PIN = re.compile(r"kranto\.git@(v\d+\.\d+\.\d+)#subdirectory=sdk")


def test_the_guide_points_at_the_protocol_here_and_nowhere_private():
    assert "(cub-protocol.md)" in GUIDE and (ROOT / "docs" / "cub-protocol.md").is_file()
    for text in (GUIDE, (ROOT / "docs" / "cub-protocol.md").read_text()):
        assert "plans/" not in text and "-notes" not in text


def test_the_guide_pins_one_sdk_tag_and_says_which():
    """One tag in the guide, of this project's own repository."""
    assert len(set(PIN.findall(GUIDE))) == 1, PIN.findall(GUIDE)
    assert "the tag of Kranto you run" in GUIDE


def test_the_starter_is_a_cub_kranto_ships():
    assert "`kranto paths examples`" in GUIDE and "newsletter" in GUIDE
    assert "github.com/" not in GUIDE.replace("github.com/you/", "").replace(
        "github.com/iddv/kranto.git", "")
    assert not (ROOT / "src" / "bears_cub" / "template").exists()
    assert sorted(p.name for p in (ROOT / "src" / "kranto" / "cubs" / "examples").iterdir()
                  if p.is_dir() and not p.name.startswith("__")) == ["blog", "newsletter", "toot"]
