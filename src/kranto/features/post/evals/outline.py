"""How alike the outlines of a set of drafts are (rule 6: posts of one kind must
differ in shape). No model call.

A draft's outline is its blocks in order, one token each: ``H`` a heading, ``L`` a list, ``Q`` a
paragraph that ends on a question, and ``P1``, ``P2``, ``P3`` a paragraph of one sentence, two or
three, or four and more. ``sameness`` is the mean, over every pair of drafts, of how much of
their outlines match (``difflib``'s ratio: 1.0 is the same outline), with the share of drafts
whose outline another draft has exactly. Lower is more varied.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations

from ....prose.checker import sentences


def outline(text: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        b = block.strip()
        if not b:
            continue
        if re.match(r"#{1,6}\s", b) or re.fullmatch(r"\*\*[^*\n]+\*\*:?", b):
            out.append("H")
            continue
        if all(re.match(r"\s*(?:[-*+]\s|\d+[.)]\s)", ln) for ln in b.splitlines() if ln.strip()):
            out.append("L")
            continue
        if b.rstrip("*_ ").endswith("?"):
            out.append("Q")
            continue
        n = len(sentences(b))
        out.append("P1" if n <= 1 else "P2" if n <= 3 else "P3")
    return out


def sameness(texts: list[str]) -> dict[str, float | int]:
    """``{drafts, mean_pair, identical_share, distinct}`` for a set of drafts of one kind."""
    lines = [outline(t) for t in texts if (t or "").strip()]
    pairs = list(combinations(range(len(lines)), 2))
    ratios = [SequenceMatcher(None, lines[a], lines[b]).ratio() for a, b in pairs]
    keys = ["-".join(x) for x in lines]
    shared = sum(1 for k in keys if keys.count(k) > 1)
    return {"drafts": len(lines),
            "mean_pair": round(sum(ratios) / len(ratios), 3) if ratios else 0.0,
            "identical_share": round(shared / len(lines), 2) if lines else 0.0,
            "distinct": len(set(keys))}
