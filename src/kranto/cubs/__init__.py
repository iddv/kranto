"""The reference cubs Kranto ships: folders under ``examples/``, installed like
any cub (``kranto cub add $(kranto paths examples)/newsletter``), never imported by Kranto."""

from __future__ import annotations

from pathlib import Path


def examples_dir() -> Path:
    return Path(__file__).resolve().parent / "examples"
