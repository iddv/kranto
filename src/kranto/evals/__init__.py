"""Evaluating Kranto: a frozen set cut
from a library's own history (``sets``), the free cassette replay CI runs (``replay``), and
dated scorecards (``scorecard``). ``kranto eval`` is the command.

Two layers at two prices. **Free, on CI:** recorded replies replayed through the current
code, and ``prompts.lock.json`` (a shipped prompt cannot change without the scorecard that
justifies it). **Cents to dollars, by hand:** a stage asked again on the frozen set through
the product's own provider seam, under ``--budget``. (The build benchmark left with builds.)
A model is never asked under CI."""

from __future__ import annotations

import os
from pathlib import Path

CI_VARS = ("CI", "GITHUB_ACTIONS")


class Refused(RuntimeError):
    """An eval that will not run: under CI, over the budget, or with nothing to run on."""


def refuse_under_ci(what: str = "an eval that asks a model") -> None:
    hit = [v for v in CI_VARS if os.environ.get(v)]
    if hit:
        raise Refused(f"{what} never runs under CI ({hit[0]} is set); the free check is "
                      "kranto eval replay")


def home_dir(home: Path) -> Path:
    """``<home>/evals``: sets, the reply cache and scorecards."""
    return Path(home) / "evals"
