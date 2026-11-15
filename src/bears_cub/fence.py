"""Strangers' text as data inside a prompt (MR-RESEARCH): a fence a model is told to read
as material, never as instructions. A run of three or more ``<`` or ``>`` inside the text is
shortened to two, so no line of it can close the fence."""

from __future__ import annotations

import re

_LABEL = re.compile(r"[A-Za-z0-9_ .:-]{1,40}")


def _defang(text: str) -> str:
    return re.sub(r"<{3,}", "<<", re.sub(r">{3,}", ">>", str(text)))


def fence(label: str, text: str) -> str:
    """``<<<label`` + the text, its fence runs shortened + ``>>>``."""
    if not _LABEL.fullmatch(str(label)):
        raise ValueError("a fence's label is a short word (letters, digits, space, _ . : -)")
    return f"<<<{label}\n{_defang(text)}\n>>>"


def fenced_block(label: str, items: list[str]) -> str:
    """Several texts in one fence, numbered ``[1]``, ``[2]``, … so a reply can cite them."""
    body = "\n".join(f"[{i}] {' '.join(_defang(x).split())}" for i, x in enumerate(items, 1))
    return fence(label, body)
