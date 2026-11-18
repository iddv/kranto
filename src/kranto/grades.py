"""Grades: a person's verdict on what the instance surfaced, or failed to.

Kranto improves through a person's occasional verdict on its rare loud
moments. A grade names a target and a verdict; grades are append-only and
the latest one on a target counts, so a changed mind is a new row and the old
verdict stays legible.

- A strike is ``worth_waking`` or ``not_worth_it``; any message can also be
  ``useful``, ``not_useful`` or ``wrong``.
- ``missed`` ("should have told me") on an observation or a cluster is the
  other half of the signal: what the gate kept quiet about, or never saw.
- Ideas keep the three verdicts the Ideas page has always offered.

Cluster numbers only mean something inside one snapshot, so a cluster grade
names the lineage, and records the snapshot and cluster number it was given
on as context.
"""

from __future__ import annotations

from datetime import datetime

from . import feedback
from .store import Store
from .stored.misc import GradeContext

ALLOWED: dict[str, tuple[str, ...]] = {
    "message": ("worth_waking", "not_worth_it", "useful", "not_useful", "wrong"),
    "observation": ("missed", "useful", "not_useful", "wrong"),
    "cluster": ("missed", "useful", "not_useful"),
    "idea": ("useful", "not_useful", "wrong"),
}
# what a card or a piece of evidence may be graded now (▲ ▼; a second press clears): the older
# values above are still read from history
CHOICES = ["useful", "not_useful"]
LABELS = {
    "worth_waking": "worth waking me",
    "not_worth_it": "not worth it",
    "missed": "missed: should have told me",
    "useful": "useful",
    "not_useful": "not useful",
    "wrong": "wrong",
    "skip": "cleared",
}


def _exists(store: Store, target: str, target_id: str) -> dict | None:
    """The context to record with the grade, or None if the target does not exist."""
    if target == "cluster":
        row = store.query_one(
            "SELECT snapshot_id, cluster, name FROM clusters WHERE lineage_id = ? "
            "ORDER BY snapshot_id DESC LIMIT 1", (target_id,))
        return ({"snapshot_id": row["snapshot_id"], "cluster": row["cluster"],
                 "name": row["name"]} if row else None)
    table = {"message": "messages", "observation": "observations", "idea": "ideas"}[target]
    try:
        ident = int(target_id)
    except ValueError:
        return None
    return {} if store.query_one(f"SELECT 1 FROM {table} WHERE id = ?", (ident,)) else None


def add_grade(store: Store, target: str, target_id: int | str, grade: str,
              note: str | None = None, *, now: datetime | None = None) -> int:
    """Record a grade (the Ideas page, ``python -m kranto grade``, the old ``/grade`` form and
    ``/api/grades``): one ``feedback`` row, the one table every grade is written to;
    returns its id. ``grades`` and ``verdicts`` keep their rows as history and are only read."""
    if target not in ALLOWED or target not in feedback.KEPT:
        raise ValueError(feedback.NOT_KEPT)
    if grade not in ALLOWED[target] or grade not in feedback.KEPT_VALUES:
        raise ValueError(f"a {target} grade must be one of {', '.join(ALLOWED[target])}")
    target_id = str(target_id).strip()
    context = _exists(store, target, target_id)
    if context is None:
        raise ValueError(f"no {target} {target_id}")
    return feedback.add(store, {"target": target, "target_id": target_id, "value": grade,
                                "note": note, "context": context}, now=now)


def _from_feedback(r: dict) -> dict:
    """A ``feedback`` grade row in this module's shape (``grade`` for its value)."""
    return {"id": r["id"], "target": r["target"], "target_id": r["target_id"],
            "grade": r["value"], "note": r["note"],
            "context": GradeContext.write(r["context"] or {}),
            "created_at": r["created_at"], "reasons": r["reasons"], "origin": r["origin"],
            "table": "feedback"}


# the tables written before ``feedback`` (migration 19), oldest first: read, never written
OLD = ("verdicts", "grades")


def _old(store: Store, target: str, ids: list[str]) -> list[dict]:
    """The grade rows of the old tables for these ids, oldest table first, each in id order:
    ``verdicts`` (ideas and observations, before migration 10) and ``grades``."""
    out: list[dict] = []
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        marks = ",".join("?" * len(part))
        if target in ("idea", "observation"):
            out += [{**dict(r), "target_id": str(r["target_id"]), "grade": r["verdict"],
                     "context": None, "table": "verdicts"} for r in store.query(
                f"SELECT * FROM verdicts WHERE target = ? AND CAST(target_id AS TEXT) IN "
                f"({marks}) ORDER BY id", (target, *part))]
        out += [{**dict(r), "table": "grades"} for r in store.query(
            f"SELECT * FROM grades WHERE target = ? AND target_id IN ({marks}) ORDER BY id",
            (target, *part))]
    return out


def latest(store: Store, target: str, target_ids) -> dict[str, dict]:
    """The one reader of a grade: the latest grade per target id (as text), for the
    ids that have one, across ``feedback`` and the two tables before it (``verdicts``,
    ``grades``); at the same moment the newer table wins. A grade cleared in the app (a
    ``skip`` row) counts as none. A target whose object left Kranto (``feedback.RETIRED_TARGETS``:
    a build, a project, a theme by lineage) has none: its rows stay and are skipped."""
    ids = [str(i) for i in target_ids]
    if not ids or target in feedback.RETIRED_TARGETS:
        return {}
    out: dict[str, dict] = {}
    for r in _old(store, target, ids):
        if r["target_id"] not in out or r["created_at"] >= out[r["target_id"]]["created_at"]:
            out[r["target_id"]] = r
    for tid, f in feedback.latest(store, target, ids, keep_skip=True).items():
        if tid not in out or f["created_at"] >= out[tid]["created_at"]:
            out[tid] = _from_feedback(f)
    return {k: v for k, v in out.items() if v["grade"] != "skip"}


def history(store: Store, target: str, target_id) -> list[dict]:
    if target in feedback.RETIRED_TARGETS:
        return []
    rows = _old(store, target, [str(target_id)])
    rows += [_from_feedback(f) for f in feedback.history(store, target, target_id)
             if f["kind"] == "grade"]
    order = {t: n for n, t in enumerate((*OLD, "feedback"))}
    return sorted(rows, key=lambda r: (r["created_at"], order[r["table"]], r["id"]))
