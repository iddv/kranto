"""Outcomes: what happened to an idea card after it was written (PLAN 4.7), one append-only row
each, written by the page through ``POST /api/ideas/{id}/outcome`` (migration 24).

``kind`` says which step decided (``KINDS``); ``value`` is that step's word, ``detail`` its
reasons as JSON, ``source`` who wrote it. The kind the weekly editor writes is ``editor``: its
``value`` is the class it gave the card that week (``nominee``, ``candidate``, ``repo idea for
<project>``, ``feature of <tool>``, ``note`` or ``reject``) and ``detail`` holds ``week`` (an ISO
week, ``2026-W41``) and ``why`` (the gate that decided, in one sentence).
``research`` is the page's Research this card: ``value`` the desk's verdict
(``proceed``, ``revise``, ``drop``), ``detail`` when it searched, the risk, what exists with URLs
and dates, what shipped since the card's newest observation.

The loop (the page ``loop/outcomes.py``) wrote one row at each step a card taken in went
through (CON L1): ``intake`` (taken in, sent to build, skipped), ``pitch`` (accepted, rejected,
error), ``build`` (building, queued, paused, held), ``gate`` (ready, held), ``publish``
(published, public, kept) and ``verdict`` (closed, rejected); each ``detail`` names the loop's
idea (``idea``), and a publish row its ``repo`` and ``url``. ``built`` reads them. Since builds
left Kranto (CUT) these kinds, with ``editor``, ``signals`` and ``research`` (``LOOP_ONLY``),
take no new row; the old rows are read as they are.

``decision`` is the owner's word on a card in the server: ``later`` with
``detail.until`` (an ISO time) puts it off until then, ``open`` brings it back now (``later``).

The latest row of a kind counts; a card's page shows it ("The editor: repo idea for Receipts,
week of 5 Oct"). Nothing here calls a model, and nothing is ever updated or deleted: a changed
mind is a new row.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from .store import Store, iso, utcnow
from .stored.misc import OutcomeDetail

KINDS = ("editor", "signals", "decision", "pitch", "intake", "build", "gate", "publish",
         "verdict", "signal_external", "research")
# the kinds only the build loop wrote (CUT, ``outcomes``): no new row of these after
# builds left; their old rows are still read (a card's history may say "built → Repo X")
LOOP_ONLY = ("intake", "pitch", "build", "gate", "publish", "verdict", "research", "editor",
             "signals")
WRITABLE = tuple(k for k in KINDS if k not in LOOP_ONLY)
# who wrote an outcome: the page, the command line, or an assistant (kranto mcp, the console,
# an agent: its Later was recorded as the page's before)
SOURCES = ("kranto.page", "ui", "cli", "assistant")
WEEK = re.compile(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])")
MAX_VALUE = 120
MAX_DETAIL = 4000
# the loop's steps that say a card was built (``built``), and the owner's word that ends one
BUILT_KINDS = ("build", "gate", "publish", "verdict")
# the classes the editor gives a card (the class may name its tool or project after "of"/"for")
EDITOR_CLASS = re.compile(r"(nominee|candidate|note|reject|build|feature of .+|repo idea for .+)",
                          re.I)


def validate(idea_id: int, body: dict) -> dict:
    """The row to insert, or ValueError naming what is wrong."""
    if not isinstance(body, dict):
        raise ValueError("expected a JSON object")
    kind = body.get("kind")
    if kind in LOOP_ONLY:
        raise ValueError(f"a {kind} outcome was the build loop's, which is not part of Kranto "
                         f"any more: kind is one of {', '.join(WRITABLE)}")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(WRITABLE)}")
    value = " ".join(str(body.get("value") or "").split())
    if not value or len(value) > MAX_VALUE:
        raise ValueError(f"value is a word or a short phrase (1 to {MAX_VALUE} characters)")
    detail = body.get("detail") or {}
    if not isinstance(detail, dict):
        raise ValueError("detail is an object")
    if kind == "decision" and value == "later":
        until = detail.get("until")
        try:
            datetime.fromisoformat(str(until).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("a later decision's detail.until is an ISO time") from None
    if kind == "editor":
        if not EDITOR_CLASS.fullmatch(value):
            raise ValueError("an editor outcome's value is its class: nominee, candidate, "
                             "repo idea for <project>, feature of <tool>, note or reject")
        if not WEEK.fullmatch(str(detail.get("week") or "")):
            raise ValueError("an editor outcome's detail.week is an ISO week such as 2026-W41")
        if detail.get("why") is not None and not isinstance(detail["why"], str):
            raise ValueError("detail.why is text")
    text = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    if len(text) > MAX_DETAIL:
        raise ValueError(f"detail is at most {MAX_DETAIL} characters of JSON")
    source = body.get("source") or "kranto.page"
    if source not in SOURCES:
        raise ValueError(f"source is one of {', '.join(SOURCES)}")
    return {"idea_id": int(idea_id), "kind": kind, "value": value, "detail": text,
            "source": source}


def add(store: Store, idea_id: int, body: dict, *, now: datetime | None = None) -> int:
    """Record one outcome on card ``idea_id``; LookupError when there is no such card."""
    row = validate(idea_id, body)
    if store.query_one("SELECT id FROM ideas WHERE id = ?", (row["idea_id"],)) is None:
        raise LookupError(f"no idea card #{idea_id}")
    return store.insert("outcomes", {**row, "created_at": iso(now or utcnow())})


def public(r) -> dict:
    d = dict(r)
    try:
        d["detail"] = OutcomeDetail.load(d.get("detail")).extra
    except ValueError:
        d["detail"] = {}
    return {k: d.get(k) for k in ("id", "kind", "value", "detail", "source", "created_at")}


def latest(store: Store, idea_ids, kind: str | None = None) -> dict[int, dict]:
    """The latest outcome per card (of ``kind``, or of any kind), for the cards that have one."""
    ids = sorted({int(i) for i in idea_ids})
    out: dict[int, dict] = {}
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        rows = store.query(
            f"SELECT * FROM outcomes WHERE idea_id IN ({','.join('?' * len(part))})"
            + (" AND kind = ?" if kind else "") + " ORDER BY id",
            (*part, *((kind,) if kind else ())))
        for r in rows:
            out[int(r["idea_id"])] = public(r)
    return out


def by_kind(store: Store, idea_ids) -> dict[int, dict[str, dict]]:
    """The latest outcome of each kind per card, for the cards that have one: one indexed read
    (``outcomes_idea``), never a scan of the loop's snapshot."""
    ids = sorted({int(i) for i in idea_ids})
    out: dict[int, dict[str, dict]] = {}
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        rows = store.query(
            "SELECT * FROM outcomes WHERE id IN (SELECT MAX(id) FROM outcomes WHERE idea_id IN "
            f"({','.join('?' * len(part))}) GROUP BY idea_id, kind) ORDER BY id", tuple(part))
        for r in rows:
            out.setdefault(int(r["idea_id"]), {})[r["kind"]] = public(r)
    return out


def built(kinds: dict[str, dict] | None) -> dict | None:
    """What was made of a card, from its latest outcome per kind (CON L1): the newest of the
    loop's ``build``, ``gate`` and ``publish`` steps, ``{state, kind, idea, repo, url, at}``;
    None when nothing was built, or when the owner's ``verdict`` (closed, rejected) is newer.
    ``repo`` and ``url`` come from the latest ``publish`` row, once there is one. Rows only
    the loop wrote, so after the cut this reads old rows only; no stored value's
    shape is assumed (a detail that is not an object, a repo that is not text, a null id)."""
    def text(v) -> str | None:
        return v if isinstance(v, str) and v else None

    rows = [r for k, r in (kinds if isinstance(kinds, dict) else {}).items()
            if k in BUILT_KINDS and isinstance(r, dict)]
    if not rows:
        return None
    def order(r: dict) -> int:
        n = r.get("id")
        return n if isinstance(n, int) else -1

    last = max(rows, key=order)
    if last.get("kind") == "verdict":
        return None
    publish = kinds.get("publish") if isinstance(kinds, dict) else None
    got = publish.get("detail") if isinstance(publish, dict) else None
    pub: dict = got if isinstance(got, dict) else {}
    seen = last.get("detail")
    det: dict = seen if isinstance(seen, dict) else {}
    return {"state": text(last.get("value")) or "", "kind": last.get("kind"),
            "idea": text(det.get("idea")) or text(pub.get("idea")),
            "repo": text(pub.get("repo")), "url": text(pub.get("url")),
            "at": last.get("created_at")}


LATER_DAYS = 7          # Later's default: back in a week
MAX_LATER_DAYS = 365


def later(store: Store, idea_id: int, days: int = LATER_DAYS, *, source: str = "ui",
          now: datetime | None = None) -> dict:
    """Later on a card (``idea.later``): a ``decision`` row, ``later`` with
    ``detail.until`` (``days`` from now), or ``open`` when ``days`` is 0 (it is back now). Written
    in the server alone: nothing reaches the build loop's ledger. The outcome as ``public`` reads
    it; LookupError for no such card, ValueError for days out of range."""
    if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= MAX_LATER_DAYS:
        raise ValueError(f"days is a whole number from 0 (back now) to {MAX_LATER_DAYS}")
    at = now or utcnow()
    from datetime import timedelta
    body = {"kind": "decision", "value": "later", "source": source,
            "detail": {"until": iso(at + timedelta(days=days)), "days": days}} if days else \
        {"kind": "decision", "value": "open", "source": source, "detail": {}}
    row_id = add(store, idea_id, body, now=at)
    return public(store.query_one("SELECT * FROM outcomes WHERE id = ?", (row_id,)))


def later_until(kinds: dict[str, dict] | None, now: datetime | None = None) -> str | None:
    """When a card put off with Later comes back (ISO), while that is still ahead; else None.
    Read from its latest ``decision`` row: ``later`` with ``detail.until``; ``open`` (or any
    other decision) ends it. A ``detail`` stored without ``until``, or with one that is not a
    time, is not a Later."""
    d = (kinds or {}).get("decision") or {}
    if d.get("value") != "later":
        return None
    until = (d.get("detail") or {}).get("until")
    if not isinstance(until, str):
        return None
    try:
        at = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return None
    return until if at > (now or utcnow()) else None


def history(store: Store, idea_id: int) -> list[dict]:
    return [public(r) for r in store.query(
        "SELECT * FROM outcomes WHERE idea_id = ? ORDER BY id", (int(idea_id),))]
