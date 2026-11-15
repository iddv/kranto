"""Feedback: the owner's grades, pairs and confirmed actions (LEARNING.md 2.4, track L1).

One append-only table (migration 19) for every grade Kranto UI, the review queue and
chat record, on any target: an observation, an idea card, a source, a topic, a message, or a
pair of cards. Rows on a build, a project or a theme (``cluster``), written before those left
Kranto, stay and are skipped by every reader (``RETIRED_TARGETS``).

- **The latest grade row on a target counts.** A second press on the same glyph clears it:
  a new row with ``value = skip``, so the history stays legible. ``latest`` leaves a cleared
  target out, as if never graded.
- **The vocabulary lives here**, not in the schema: ``TARGETS``, ``KINDS``, the values per
  kind, ``ORIGINS`` and the "why" chips per target (LEARNING.md 3.3). A new target is a line
  here, not a migration.
- **The review queue** (``build_queue``, LEARNING.md 3.4) is computed, never stored, and
  holds only what a grade is read for today: this week's ungraded cards in the order
  of what they stand on. Pairs, themes, random controls and
  what was opened are no longer asked (their old rows stay, and the API still takes a pair).
  A queue skip hides an item for the rest of the week; a second queue skip, in a later week,
  hides it for good.
- **The learning summary** (``learning``, LEARNING.md 5.2) is a stub until tracks L2-L5:
  this month's signal counts, every policy as *Waiting for signal* (or *Blocked*) with what
  it needs, and the one honest number once controls have been graded.

Nothing here calls a model. ``grades.latest`` and ``grades.history`` read this table next to
``grades``, so every page that showed a grade before keeps working.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from .store import Store, iso, utcnow
from .stored.misc import FeedbackContext, FeedbackPair, FeedbackReasons

TARGETS = ("observation", "idea", "source", "topic", "message", "pair")
# Targets whose object left Kranto (CUT, ``feedback.target``): a build and a project
# (the page's ledger, gone with builds) and a theme graded by lineage (``cluster``). Their rows
# stay in the table, never rewritten; every reader here skips them (no history, no latest, no
# count), and no new row names one.
RETIRED_TARGETS = ("build", "cluster", "project")
KINDS = ("grade", "pair", "action", "implicit")
# worth_waking and not_worth_it: a message's (a strike's), through grades.add_grade
GRADE_VALUES = ("useful", "not_useful", "wrong", "missed", "skip", "worth_waking",
                "not_worth_it")
PAIR_VALUES = ("a", "b", "tie")
IMPLICIT_VALUES = ("opened",)
ORIGINS = ("ui", "review", "chat", "chat_suggested", "learn")
LABELS = {"useful": "useful", "not_useful": "not useful", "wrong": "wrong",
          "missed": "missed: should have told me", "skip": "skipped",
          "worth_waking": "worth waking me", "not_worth_it": "not worth it",
          "a": "the first", "b": "the second", "tie": "a tie"}

# The "why" chips (LEARNING.md 3.3): a closed vocabulary per target, in key order a, b, c...
CHIPS: dict[str, list[tuple[str, str]]] = {
    "idea": [("not_my_topic", "not my topic"), ("already_exists", "already exists"),
             # the keys stay (stored grades); the words a person reads say no build
             ("thin_evidence", "thin evidence"), ("not_buildable", "not doable"),
             ("wrong_user", "wrong user"), ("build_it", "want this")],
    "observation": [("off_topic", "off topic"), ("ad", "ad or sponsor"), ("stale", "stale"),
                    ("duplicate", "duplicate"), ("thin", "thin"),
                    ("missed", "missed: should have told me")],
    "source": [("noisy", "noisy"), ("off_topic", "off topic"), ("dead", "dead"),
               ("duplicates", "duplicates another"), ("more_like_this", "more like this")],
    "topic": [("too_quiet", "too quiet"), ("too_noisy", "too noisy"),
              ("wrong_description", "wrong description")],
    "message": [],
}

# Grades are kept on ideas and evidence only: ▲ useful, ▼ not useful, a second
# press clears (skip). Rows on other targets written before stay history (``grades.history``).
KEPT = ("idea", "observation")
KEPT_VALUES = ("useful", "not_useful", "skip")
NOT_KEPT = "grades are kept on ideas and evidence only"

# The queue's settings (binary rules become settings: each is a query parameter of
# GET /api/review/queue, with these defaults).
QUEUE_SIZE = 20
QUEUE_WINDOW_DAYS = 7
BATCH_MAX = 50
NOTE_MAX = 2000
CONTEXT_MAX = 2000
TARGET_ID_MAX = 200
_ACTION = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _feature_grades() -> dict[str, tuple]:
    """The targets features add (a brief's item, a proposal), with their chips."""
    from .core.registry import features
    return {t: c for f in features() for t, c in f.grades.items()}


def targets() -> tuple[str, ...]:
    return TARGETS + tuple(_feature_grades())


def chips() -> dict[str, list[tuple[str, str]]]:
    return {**CHIPS, **{t: list(c) for t, c in _feature_grades().items()}}


def vocabulary() -> dict:
    """What the UI draws its controls and chips from."""
    return {"targets": list(targets()), "kinds": list(KINDS), "grades": list(GRADE_VALUES),
            "pairs": list(PAIR_VALUES), "origins": list(ORIGINS), "labels": LABELS,
            "chips": {t: [{"key": k, "label": w, "letter": "abcdef"[i]}
                          for i, (k, w) in enumerate(cs)] for t, cs in chips().items()}}


def _exists(store: Store, target: str, target_id: str) -> bool:
    if target in _feature_grades():        # a feature's object, by the feature's ids
        return True
    table = {"observation": "observations", "idea": "ideas", "source": "sources",
             "topic": "topics", "message": "messages"}[target]
    try:
        ident = int(target_id)
    except ValueError:
        return False
    return store.query_one(f"SELECT 1 FROM {table} WHERE id = ?", (ident,)) is not None


def _ref(x) -> tuple[str, str]:
    if not isinstance(x, dict):
        raise ValueError("a pair names two targets: {a: {target, id}, b: {target, id}}")
    target, ident = str(x.get("target") or ""), str(x.get("id") or "").strip()
    if target not in targets() or target == "pair" or not ident:
        raise ValueError("each side of a pair needs a target and an id")
    return target, ident


def validate(row: dict) -> dict:
    """One feedback row, checked against the vocabulary and normalised; raises ValueError.
    Does not check that the target exists (``add`` does)."""
    kind = str(row.get("kind") or "grade")
    origin = str(row.get("origin") or "ui")
    value = str(row.get("value") or "")
    target = str(row.get("target") or "")
    target_id = str(row.get("target_id") if row.get("target_id") is not None else "").strip()
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {', '.join(ORIGINS)}")
    pair = None
    if kind == "pair":
        if value not in PAIR_VALUES:
            raise ValueError(f"a pair's value must be one of {', '.join(PAIR_VALUES)}")
        p = row.get("pair") or {}
        a, b = _ref(p.get("a") if isinstance(p, dict) else None), _ref(
            p.get("b") if isinstance(p, dict) else None)
        if a == b:
            raise ValueError("a pair needs two different targets")
        target, target_id = "pair", f"{a[0]}:{a[1]}|{b[0]}:{b[1]}"
        pair = {"a": {"target": a[0], "id": a[1]}, "b": {"target": b[0], "id": b[1]}}
    else:
        if target not in targets() or target == "pair":
            named = ", ".join(t for t in targets() if t != "pair")
            raise ValueError(f"target must be one of {named}")
        if not target_id or len(target_id) > TARGET_ID_MAX:
            raise ValueError("target_id is required (at most 200 characters)")
        if kind == "grade" and target in KEPT and value not in KEPT_VALUES:
            raise ValueError(f"a grade must be one of {', '.join(KEPT_VALUES)}")
        if kind == "grade" and target not in KEPT and target not in _feature_grades():
            raise ValueError(NOT_KEPT)
        if kind == "grade" and value not in GRADE_VALUES:
            raise ValueError(f"a grade must be one of {', '.join(GRADE_VALUES)}")
        if kind == "implicit" and value not in IMPLICIT_VALUES:
            raise ValueError(f"an implicit signal must be one of {', '.join(IMPLICIT_VALUES)}")
        if kind == "action" and not _ACTION.match(value):
            raise ValueError("an action is a lower-case name")
    reasons = row.get("reasons") or []
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        raise ValueError("reasons is a list of chip names")
    allowed = {k for k, _ in chips().get(target, [])}
    bad = [r for r in reasons if r not in allowed]
    if bad:
        raise ValueError(f"not a chip for a {target}: {', '.join(bad)}")
    note = row.get("note")
    note = str(note).strip()[:NOTE_MAX] if note else None
    context = row.get("context") or {}
    if not isinstance(context, dict):
        raise ValueError("context is an object")
    # a build's grade names its card and the loop's idea (CON L3; ``build_grades``)
    card = context.get("card")
    if card is not None and (not isinstance(card, int) or isinstance(card, bool) or card < 1):
        raise ValueError("context.card is a card's id, a whole number")
    if context.get("idea") is not None and not (isinstance(context["idea"], str)
                                                 and 0 < len(context["idea"]) <= 40):
        raise ValueError("context.idea is the loop's idea id")
    ctx = json.dumps(context, sort_keys=True)
    if len(ctx) > CONTEXT_MAX:
        raise ValueError(f"context is at most {CONTEXT_MAX} characters as JSON")
    return {"target": target, "target_id": target_id, "kind": kind, "value": value,
            "reasons": FeedbackReasons.write(list(dict.fromkeys(reasons))),
            "pair": json.dumps(pair) if pair else None, "note": note or None,
            "origin": origin, "context": ctx}


def _check_targets(store: Store, row: dict) -> None:
    refs = ([(s["target"], s["id"]) for s in FeedbackPair.load(row["pair"]).extra.values()]
            if row["pair"] else [(row["target"], row["target_id"])])
    for target, ident in refs:
        if not _exists(store, target, ident):
            raise ValueError(f"no {target} {ident}")


def add(store: Store, row: dict, *, now: datetime | None = None) -> int:
    """Record one feedback row (see ``validate``); returns its id."""
    clean = validate(row)
    _check_targets(store, clean)
    row_id = store.insert("feedback", {**clean, "created_at": iso(now or utcnow())})
    if clean["kind"] == "grade":
        from .core import events
        events.core_publish(store, "grade.given", {"target": clean["target"],
                                                   "target_id": clean["target_id"][:120],
                                                   "value": clean["value"]},
                            subject=(clean["target"], clean["target_id"][:120]))
    return row_id


def _public(r) -> dict:
    d = dict(r)
    d["reasons"] = FeedbackReasons.load(d.get("reasons")).items
    d["context"] = FeedbackContext.load(d.get("context")).extra
    pair = FeedbackPair.parse(d.get("pair"))
    d["pair"] = pair.extra if pair is not None else None
    return d


def latest(store: Store, target: str, target_ids, *, keep_skip: bool = False) -> dict[str, dict]:
    """The latest grade row per target id (as text), for the ids that have one. A target
    whose latest row is a ``skip`` (a cleared grade) is left out unless ``keep_skip``. A
    retired target's rows (``RETIRED_TARGETS``) are skipped: none."""
    if target in RETIRED_TARGETS:
        return {}
    ids = sorted({str(i) for i in target_ids})
    out: dict[str, dict] = {}
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        rows = store.query(
            f"SELECT * FROM feedback WHERE kind = 'grade' AND target = ? "
            f"AND target_id IN ({','.join('?' * len(part))}) ORDER BY id", (target, *part))
        for r in rows:
            out[r["target_id"]] = _public(r)
    return out if keep_skip else {k: v for k, v in out.items() if v["value"] != "skip"}


def history_row(store: Store, row_id: int) -> dict:
    return _public(store.query_one("SELECT * FROM feedback WHERE id = ?", (row_id,)))


def history(store: Store, target: str, target_id) -> list[dict]:
    """Every row on one target, oldest first; none for a retired target (``RETIRED_TARGETS``)."""
    if target in RETIRED_TARGETS:
        return []
    return [_public(r) for r in store.query(
        "SELECT * FROM feedback WHERE target = ? AND target_id = ? ORDER BY id",
        (target, str(target_id)))]


# -- the review queue (LEARNING.md 3.4) ----------------------------------------------------


def _week(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _hidden(store: Store, since: str) -> set[tuple[str, str]]:
    """Targets the queue leaves out after a queue skip: this week's, and any skipped twice."""
    rows = store.query("SELECT target, target_id, created_at FROM feedback WHERE kind = 'grade' "
                       "AND value = 'skip' AND origin = 'review'")
    count: dict[tuple[str, str], int] = {}
    out = set()
    for r in rows:
        key = (r["target"], r["target_id"])
        count[key] = count.get(key, 0) + 1
        if r["created_at"] >= since:
            out.add(key)
    return out | {k for k, n in count.items() if n >= 2}


def _graded(store: Store, target: str, ids) -> set[str]:
    from . import grades  # grades imports this module for its union

    return set(grades.latest(store, target, ids))


def build_queue(store: Store, cards: list[dict], *, builds=(), now: datetime | None = None,
                size: int = QUEUE_SIZE, window_days: int = QUEUE_WINDOW_DAYS) -> dict:
    """This week's queue: only what a grade is read for today: this week's ungraded
    cards, in ``cards.fact_order`` (the weekly editor reads the owner's card grades and chips).
    ``builds`` is accepted and ignored (builds left Kranto, CUT); a skip row on a retired target
    hides nothing that is asked. ``cards`` are the idea cards as /api/ideas returns them (id, title,
    one_liner, status, created_at, topic, theme, citations, facts). Each item is ``{slot,
    target, id, ...}``; ``slot`` (build, card) goes into the grade's context."""
    from .ideate.cards import fact_order

    now = now or utcnow()
    since = iso(now - timedelta(days=window_days))
    hidden = _hidden(store, since)

    items: list[dict] = []

    shown = [c for c in cards if c.get("status") == "shown"]
    card_grades = _graded(store, "idea", [c["id"] for c in shown])
    week_cards = sorted((c for c in shown if (c.get("created_at") or "") >= since
                         and str(c["id"]) not in card_grades
                         and ("idea", str(c["id"])) not in hidden), key=fact_order)
    items += [_card_item(c, "card") for c in week_cards]
    return {"week": _week(now), "size": size, "items": items[:size],
            "chips": vocabulary()["chips"]}


def _card_item(c: dict, slot: str) -> dict:
    from .ideate.cards import fact_words, facts

    out = fact_words(c.get("facts") or facts(c.get("card") or {"evidence": c.get("evidence"),
                                                             "demand": c.get("demand"),
                                                             "citations": c.get("citations")}))
    if c.get("theme"):
        out.append(f"theme: {c['theme']['name']}")
    return {"slot": slot, "target": "idea", "id": c["id"], "title": c["title"],
            "line": c.get("one_liner") or "", "topic": (c.get("topic") or {}).get("name"),
            "facts": out}
