"""The event bus (MR-RESEARCH): the one way features speak.

An event is a fact, never an instruction: ``kind`` is ``<noun>.<verb-past>``, the payload carries
ids and small facts (a reader fetches the object through a read API), and the row records who
published it and how far they are trusted. One append-only table (``events``, migration 30);
each subscriber has a cursor per kind (``event_cursors``, the newest row counting), advanced
only after its handler succeeds, so delivery is at least once and handlers key on the event id.

Rules the code holds:

1. a feature publishes only kinds its manifest declares, and a kind is declared by exactly one
   publisher (the registry checks); the core's own kinds are ``CORE_KINDS``;
2. a payload is small: a JSON object of at most ``MAX_PAYLOAD`` bytes whose strings are at most
   ``MAX_STRING`` characters (an id, a status, a word), so no document rides the bus;
3. a subscription has a trust floor (``min_trust``): Invest reads ``brief.published`` from
   first-party News only (MR D8).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..store import Store, iso, utcnow
from ..stored.events import Payload
from .manifest import KIND, TRUST, trust_rank

log = logging.getLogger("kranto.core.events")

MAX_PAYLOAD = 2000
MAX_STRING = 200
READ_LIMIT = 500
# The core's own kinds (rule 5,): no feature may declare them.
CORE_KINDS = ("job.finished", "settings.changed", "grade.given", "spend.capped",
              "ticket.filed", "ticket.resolved", "instruction.sent", "instruction.refused",
              "instruction.updated", "money.halted", "money.resumed", "money.tools_approved",
              "money.disconnected",
              # a cub's state changes, the core's word, never a cub's
              "cub.installed", "cub.updated", "cub.removed", "cub.enabled", "cub.disabled",
              "cub.stopped", "cub.resumed", "cub.mode_changed", "cub.paused")


class EventError(ValueError):
    """An event the bus refuses."""


def _check_payload(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise EventError("a payload is a JSON object of ids and small facts")

    def walk(v: object, depth: int = 0) -> None:
        if depth > 3:
            raise EventError("a payload is at most three levels deep")
        if isinstance(v, str) and len(v) > MAX_STRING:
            raise EventError(f"a payload string is at most {MAX_STRING} characters: the reader "
                             "fetches documents through a read API")
        if isinstance(v, dict):
            for x in v.values():
                walk(x, depth + 1)
        elif isinstance(v, list):
            for x in v:
                walk(x, depth + 1)

    walk(payload)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(text) > MAX_PAYLOAD:
        raise EventError(f"a payload is at most {MAX_PAYLOAD} bytes")
    return text


def publish(store: Store, *, feature: str, trust: str, kind: str,
            payload: dict[str, Any] | None = None,
            subject: tuple[str, str | int] | None = None, run_uuid: str | None = None,
            origin: str | None = None, declared: tuple[str, ...] | None = None,
            now: datetime | None = None) -> int:
    """Append one event; its id. ``declared``: the kinds this publisher may publish (a feature's
    manifest); the core passes None and may publish only ``CORE_KINDS``."""
    if not KIND.fullmatch(kind):
        raise EventError(f"{kind!r} is not <noun>.<verb>")
    if trust not in TRUST:
        raise EventError(f"trust must be one of {', '.join(TRUST)}")
    if declared is None:
        if kind not in CORE_KINDS:
            raise EventError(f"{kind} is not one of the core's kinds")
    elif kind not in declared:
        raise EventError(f"{feature} does not declare {kind} in its manifest")
    text = _check_payload(payload or {})
    return store.insert("events", {
        "ts": iso(now or utcnow()), "kind": kind, "feature": feature, "trust": trust,
        "subject_kind": subject[0] if subject else None,
        "subject_id": str(subject[1]) if subject else None,
        "payload": text, "run_uuid": run_uuid, "origin": origin})


def core_publish(store: Store, kind: str, payload: dict[str, Any] | None = None,
                 **kw: Any) -> int | None:
    """The core's own events. Never raises into the caller: a bus that cannot be written must
    not stop a grade or a job (the row is a record, not the action)."""
    try:
        return publish(store, feature="core", trust="core", kind=kind, payload=payload, **kw)
    except Exception:  # noqa: BLE001 - logged; the action it records already happened
        log.exception("could not record %s", kind)
        return None


def _row(r: Any) -> dict[str, Any]:
    return {"id": r["id"], "ts": r["ts"], "kind": r["kind"], "feature": r["feature"],
            "trust": r["trust"], "subject_kind": r["subject_kind"],
            "subject_id": r["subject_id"], "payload": Payload.load(r["payload"]).extra,
            "run_uuid": r["run_uuid"], "origin": r["origin"]}


def read(store: Store, *, since: int = 0, kinds: tuple[str, ...] | list[str] | None = None,
         min_trust: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Events after ``since`` (an id), oldest first, of ``kinds`` (all if None), published at
    or above ``min_trust``."""
    limit = max(1, min(int(limit), READ_LIMIT))
    sql = "SELECT * FROM events WHERE id > ?"
    params: list[Any] = [int(since)]
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        params += list(kinds)
    if min_trust:
        allowed = [t for t in TRUST if trust_rank(t) >= trust_rank(min_trust)]
        sql += f" AND trust IN ({','.join('?' * len(allowed))})"
        params += allowed
    rows = store.query(sql + " ORDER BY id LIMIT ?", (*params, limit))
    return [_row(r) for r in rows]


def get(store: Store, event_id: int) -> dict[str, Any] | None:
    r = store.query_one("SELECT * FROM events WHERE id = ?", (int(event_id),))
    return _row(r) if r else None


def cursor(store: Store, feature: str, kind: str) -> int:
    row = store.query_one("SELECT last_id FROM event_cursors WHERE feature = ? AND kind = ? "
                          "ORDER BY id DESC LIMIT 1", (feature, kind))
    return int(row["last_id"]) if row else 0


def advance(store: Store, feature: str, kind: str, last_id: int,
            now: datetime | None = None) -> None:
    if last_id > cursor(store, feature, kind):
        store.insert("event_cursors", {"feature": feature, "kind": kind, "last_id": int(last_id),
                                       "created_at": iso(now or utcnow())})


def take(store: Store, feature: str, kind: str, *, min_trust: str, limit: int = 100
         ) -> list[dict[str, Any]]:
    """The events of ``kind`` after ``feature``'s cursor at or above its floor (not advanced:
    the reader calls ``advance`` with the last id it handled)."""
    return read(store, since=cursor(store, feature, kind), kinds=[kind], min_trust=min_trust,
                limit=limit)


def deliver(store: Store, subscriptions: list[tuple[str, str, str, Any]],
            context_for: Callable[[str], Any]) -> dict[str, int]:
    """Hand new events to every subscriber with a handler: ``(feature, kind, min_trust,
    handler)``; ``context_for(feature)`` builds the handler's context. A handler that raises
    keeps its cursor where it was (the next tick tries again). Returns events handled per
    subscriber."""
    done: dict[str, int] = {}
    for feature, kind, min_trust, handler in subscriptions:
        if handler is None:
            continue
        rows = take(store, feature, kind, min_trust=min_trust)
        if not rows:
            continue
        ctx = context_for(feature)
        last = None
        try:
            for ev in rows:
                handler(ctx, ev)
                last = ev["id"]
        except Exception:  # noqa: BLE001 - the cursor stays; the next tick retries
            log.exception("%s's handler for %s raised", feature, kind)
        if last is not None:
            advance(store, feature, kind, last)
            done[f"{feature}:{kind}"] = done.get(f"{feature}:{kind}", 0) + 1
    return done
