"""What a stranger sees of the repository before reading any code: NOTICE's holder line and
public.toml agree, the package says where the project lives, and the CHANGELOG never dates a
release that is not out."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = tomllib.loads((ROOT / "public.toml").read_text())
PLACEHOLDER = ("Copyright 2026 [HOLDER: the copyright holder's line, to be written before the "
               "repository is public]")


def test_notice_holder_is_public_toml_s_or_the_one_placeholder():
    """The holder is written in two places: public.toml's ``holder`` and NOTICE's second line.
    Empty in public.toml, NOTICE keeps the one placeholder (nothing half-filled); set, NOTICE
    carries exactly it and no placeholder is left."""
    lines = (ROOT / "NOTICE").read_text().splitlines()
    assert lines[0] == PUBLIC["name"]
    holder = PUBLIC["holder"].strip()
    if holder:
        assert lines[1] == f"Copyright 2026 {holder}"
        assert "[HOLDER" not in (ROOT / "NOTICE").read_text()
    else:
        assert lines[1] == PLACEHOLDER


def test_the_package_says_where_the_project_lives():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    home = f"https://github.com/{PUBLIC['repo']}"
    urls = meta["urls"]
    assert urls["Homepage"] == (PUBLIC["site"] or home) and urls["Source"] == home
    assert urls["Issues"] == f"{home}/issues"
    for key in ("Documentation", "Changelog"):
        assert urls[key].startswith(f"{home}/blob/main/"), key
        assert (ROOT / urls[key].split("/blob/main/", 1)[1]).is_file(), key
    assert "Operating System :: POSIX :: Linux" in meta["classifiers"]
    pythons = [c for c in meta["classifiers"]
               if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)]
    low = meta["requires-python"].removeprefix(">=")
    assert pythons and pythons[0].endswith(low), (pythons, low)


def test_the_changelog_dates_only_what_is_released():
    """Above the releases there may be one ``## Unreleased``; the newest release heading is
    ``## X.Y.Z — unreleased`` until it is cut, then ``## X.Y.Z — YYYY-MM-DD``; every older one
    is dated."""
    heads = re.findall(r"^## (.+)$", (ROOT / "CHANGELOG.md").read_text(), re.M)
    if heads and heads[0] == "Unreleased":
        heads = heads[1:]
    assert heads
    assert re.fullmatch(r"\d+\.\d+\.\d+ — (unreleased|\d{4}-\d{2}-\d{2})", heads[0]), heads[0]
    for h in heads[1:]:
        assert re.fullmatch(r"\d+\.\d+\.\d+ — \d{4}-\d{2}-\d{2}", h), h
