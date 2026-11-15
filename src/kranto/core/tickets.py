"""Tickets (MR-RESEARCH): a feature or a cub asks, the core performs, the
owner confirms.

The high-trust capabilities (money, sending, posting, booking) belong to the core. A feature
whose manifest lists a kind under ``requests`` may *file* a ticket for it with typed fields and
its provenance (``because``: the events, observations and briefs it rests on). The ticket is a
needs-you row; the owner's press runs ``confirm`` from a door the kind allows (for every kind
today, the page only: a signed-in browser's cookie, never the command line, ``kranto mcp``, an
agent token, a chat or a cub), and only then does the core's performer run.

What the code holds:

- a ticket's fields are checked against the kind's schema (enums, ids, numbers, short text): the
  read-back the confirm shows is built from them, never from a model's prose (MR M10); a
  ``draft_ref`` must name a draft of the filing cub;
- one open ticket per kind and fields at a time (a duplicate is refused with the open one's id),
  and a per-filer daily cap;
- a ticket is confirmable once: the state moves from ``needs_confirm`` to ``confirmed`` inside
  one write transaction, so two presses (two tabs, a retry) perform once;
- it expires (``expires_at``); an expired ticket cannot be confirmed. A draft's ask (a kind
  whose ``expires_hours`` is None: the posting kinds) has no time limit ("a draft
  waits until it is seen"): it stores ``NEVER`` (the column cannot be null) and leaves the
  waiting list only when it is answered, withdrawn, or replaced by the next draft of its
  series (``state`` ``expired`` with the note ``replaced by #<id>``: no new state, since the
  CHECK list cannot grow by an additive migration);
- the press runs in the mode of the moment: a cub's kind is live only while it is listed
  in ``cubs.<id>.live``, the cub's ``kranto`` range includes this host and the ``cubs.STOP``
  file does not exist; otherwise the press resolves ``dry`` and nothing leaves Kranto;
- every state is a new row of ``cub_ticket_states`` (append-only), so the history is the audit.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..store import Store, iso, utcnow
from ..stored.cubs import TicketBecause, TicketFields
from . import events

OPEN = "needs_confirm"
FINAL = ("done", "dry", "declined", "expired", "refused", "unknown")
STATES = (OPEN, "confirmed", *FINAL)
# Trust levels whose tickets the cub rules (live list, range, the STOP file) do not apply to:
# Kranto's own features keep their own modes.
FIRST_PARTY = ("core", "first-party")
# A ticket that waits until it is answered (``Kind.expires_hours`` None): ``expires_at`` is NOT
# NULL, so it holds the last day there is. Every reader compares it as text, so it is never due.
NEVER = "9999-12-31T00:00:00Z"
# The note of a ticket a newer draft of its series replaced (``state`` stays ``expired``), and of
# one swept because its time ran out (the daily ``cubs.gc``; a confirm past the time writes none)
REPLACED = "replaced by #"
PAST_TIME = "past its time"


def waits(expires_at: str | None) -> bool:
    """Whether a ticket's ``expires_at`` says it waits until it is answered."""
    return str(expires_at or "") >= NEVER


def replaced_by(note: str | None) -> int | None:
    """The ticket that replaced this one, from its ``expired`` note, else None."""
    m = re.fullmatch(r"replaced by #([0-9]{1,12})", str(note or ""))
    return int(m.group(1)) if m else None


def time_expired(t: dict[str, Any]) -> bool:
    """Whether a ticket (``get``'s shape) ran out of time rather than being answered, withdrawn
    or replaced: read as expired while open past its time, or its last state ``expired`` by the
    sweep (``past its time``) or by a press past the time (door ``core``, no note)."""
    if t.get("state") != "expired":
        return False
    last = (t.get("history") or [{}])[-1]
    if last.get("state") != "expired":
        return True                      # open past its time, not swept yet
    note = last.get("note")
    return note == PAST_TIME or (note is None and last.get("door") == "core")


class TicketError(ValueError):
    """A ticket the core refuses to file or confirm, with why in words. ``ticket_id``: the
    open ticket a duplicate names."""

    def __init__(self, msg: str, code: int = 400, ticket_id: int | None = None) -> None:
        super().__init__(msg)
        self.code = code
        self.ticket_id = ticket_id


@dataclass(frozen=True)
class Field:
    type: str                         # int | float | str | enum | iso
    choices: tuple[Any, ...] = ()
    pattern: str | None = None
    max_len: int = 120
    lo: float | None = None
    hi: float | None = None
    label: str = ""                   # the read-back's word for it (the confirm dialog)


@dataclass
class Kind:
    """A high-trust action: its fields, the doors that may confirm it, whether the door must be
    the page's cookie (``page_only``), how long a ticket lives (None: until it is answered, the
    posting kinds), its daily cap per filer, and the performer, which the owning core module
    registers.
    ``perform(store, ticket, context, mode=...)`` returns ``{state, note}``; ``mode`` is
    ``dry`` or ``live``, the mode of the press. ``meta.series`` True: every ticket of the kind
    from one filer is one series (a weekly issue), so a newer one replaces the open older one;
    otherwise only a newer one about the same subject does."""

    kind: str
    title: str
    fields: dict[str, Field]
    doors: tuple[str, ...] = ("ui",)
    page_only: bool = True
    expires_hours: float | None = 48
    per_day: int = 10
    perform: Callable[..., Any] | None = None
    readback: Callable[..., Any] | None = None   # fields -> list[(label, text)] the confirm shows
    first_party_only: bool = False     # Kranto's own: never grantable to a cub
    # meta: ``alias_of``; the owner's words (``core.asks``): ``verb``, ``button``, ``noun``,
    # ``done``, ``not_done``; ``schedules``: the confirm may choose a time (``when``)
    meta: dict[str, Any] = field(default_factory=dict)
    ask: Callable[..., Any] | None = None   # (fields, store, rt) -> the plain dialog's parts


KINDS: dict[str, Kind] = {}


def register(kind: Kind) -> Kind:
    KINDS[kind.kind] = kind
    return kind


def kind_names() -> tuple[str, ...]:
    """Every kind a manifest may ask for: each high-trust module registers its own when the
    core package is imported, and the kinds below are
    declared here with their typed fields, so the confirm dialog has one shape for every kind;
    one without a performer is refused at the press until its module lands. The broker
    adapters (``core.cubs.brokers``) give ``send.newsletter`` and ``post.mastodon`` theirs."""
    import kranto.core  # noqa: F401 - the package's import registers the kinds
    import kranto.core.cubs.brokers  # noqa: F401 - and the adapters' performers
    return tuple(sorted(KINDS))


def canonical(kind: str) -> str:
    """A kind's own name: an earlier release's name for it is an alias (``meta.alias_of``)."""
    spec = KINDS.get(kind)
    return spec.meta.get("alias_of", kind) if spec else kind


def same_kind(a: str, b: str) -> bool:
    kind_names()
    return canonical(a) == canonical(b)


def grantable_to(kind: str, trust: str) -> bool:
    """Whether a manifest of ``trust`` may list ``kind`` under ``requests``."""
    spec = KINDS.get(kind)
    return spec is not None and (not spec.first_party_only or trust in FIRST_PARTY)


def readback_of(spec: Kind, fields: dict[str, Any], store: Store | None = None) -> list[list[str]]:
    """The confirm's read-back, built from the ticket's typed fields and the core's own rows
    (a broker's draft and connection label, when the kind's words take ``store``): the kind's
    own words, else each field's label and value in the kind's order (never a feature's
    prose)."""
    if spec.readback:
        try:
            if len(inspect.signature(spec.readback).parameters) >= 2:
                if store is not None:
                    return [list(x) for x in spec.readback(fields, store)]
            else:
                return [list(x) for x in spec.readback(fields)]
        except (KeyError, TypeError, ValueError):
            pass                         # a row the kind's words cannot read: its labels
    return [[f.label or name, str(fields.get(name, ""))] for name, f in spec.fields.items()]


def describe_kinds() -> dict[str, dict[str, Any]]:
    """Every kind's read-back schema, for ``GET /api/features`` and the one dialog."""
    kind_names()
    return {k: {"title": s.title, "doors": list(s.doors), "page_only": s.page_only,
                "performs": s.perform is not None, "expires_hours": s.expires_hours,
                "per_day": s.per_day, "first_party_only": s.first_party_only,
                "alias_of": s.meta.get("alias_of"),
                # the owner's word for its button (SEND: "Send", "Post toot"), an alias's own
                "button": (s.meta.get("button") or KINDS.get(s.meta.get("alias_of", ""),
                                                            s).meta.get("button") or "Approve"),
                "fields": [{"key": n, "label": f.label or n, "type": f.type,
                            "choices": list(f.choices)} for n, f in s.fields.items()]}
            for k, s in sorted(KINDS.items())}


# The kinds a cub may ask for (cld/tickets.json): declared here with their
# read-back fields; ``post.mastodon`` gets its performer from the broker adapters (a ticket of
# one is filed, listed and declined like any other and refused at Confirm until its adapter is
# registered); ``send.newsletter`` is declared with its adapter (``core.cubs.brokers.newsletter``),
# which names no platform; ``book.propose`` has none in 0.5 (filed, shown, declined; never
# confirmed). A cub never names the owner's account: the core fills it from the connection.
_F = Field
register(Kind("post.mastodon", "Publish this post", {
    "draft_ref": _F("str", pattern=r"draft:[0-9]{1,12}", max_len=20, label="Draft"),
    "text": _F("str", max_len=500, label="Text"),
    "visibility": _F("enum", ("public", "unlisted", "private"), label="Visibility"),
    "language": _F("str", pattern=r"[a-z]{2}(-[A-Za-z]{2})?", max_len=5, label="Language")},
    expires_hours=None, per_day=5,
    meta={"verb": "Post toot", "button": "Post toot", "noun": "toot", "done": "Posted",
          "not_done": "not posted", "question": "Post this toot?"}))
register(Kind("book.propose", "Propose this trip", {
    "legs": _F("str", max_len=400, label="Legs"),
    "total": _F("float", lo=0, hi=1000000, label="Total"),
    "currency": _F("enum", ("EUR", "USD", "GBP"), label="Currency"),
    "links": _F("str", max_len=400, label="Where you pay")}, expires_hours=24, per_day=3))


def _check(spec: Kind, fields: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fields, dict):
        raise TicketError("the fields are an object")
    unknown = set(fields) - set(spec.fields)
    missing = set(spec.fields) - set(fields)
    if unknown or missing:
        raise TicketError(f"{spec.kind}: fields must be exactly {', '.join(sorted(spec.fields))}"
                          + (f" (unknown: {', '.join(sorted(unknown))})" if unknown else "")
                          + (f" (missing: {', '.join(sorted(missing))})" if missing else ""))
    out = {}
    for name, f in spec.fields.items():
        v = fields[name]
        where = f"{spec.kind}.{name}"
        if f.type == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise TicketError(f"{where} must be a whole number")
        elif f.type == "float":
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise TicketError(f"{where} must be a number")
            v = float(v)
        elif f.type in ("str", "iso"):
            if not isinstance(v, str) or not v or len(v) > f.max_len:
                raise TicketError(f"{where} must be text of 1 to {f.max_len} characters")
            if f.type == "iso":
                try:
                    datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    raise TicketError(f"{where} must be an ISO time") from None
        elif f.type == "enum":
            if v not in f.choices:
                raise TicketError(f"{where} must be one of {', '.join(map(str, f.choices))}")
        else:
            raise TicketError(f"{where}: unknown field type {f.type}")
        if f.pattern and not re.fullmatch(f.pattern, str(v)):
            raise TicketError(f"{where}: {v!r} is not of the expected shape")
        if f.lo is not None and float(v) < f.lo or f.hi is not None and float(v) > f.hi:
            raise TicketError(f"{where} must be between {f.lo} and {f.hi}")
        out[name] = v
    return out


# a trend's key, as the radar made it (a cub of before the cut 2 may still name one)
TREND_KEY = re.compile(r"[a-z][a-z0-9_-]{1,40}")


def _because(because: dict[str, Any] | None) -> dict[str, Any]:
    """What a ticket rests on: the events, observations, briefs and idea cards (ids), the
    radar's trends (keys), labels, a proposal and a card id (L4; the trend, the
    proposal and the card are Invest's and the radar's, which left Kranto: an older cub's ticket
    that names them still files)."""
    because = dict(because or {})
    allowed = {"events", "observations", "briefs", "ideas", "trends", "labels", "proposal",
               "card"}
    if set(because) - allowed:
        raise TicketError(f"because names some of {', '.join(sorted(allowed))}")
    card = because.get("card")
    if card is not None and (isinstance(card, bool) or not isinstance(card, int)):
        raise TicketError("because.card is a card's id")
    trends = because.get("trends", [])
    if not isinstance(trends, list) or len(trends) > 50 or not all(
            isinstance(k, str) and TREND_KEY.fullmatch(k) for k in trends):
        raise TicketError("because.trends is a list of at most 50 trend keys")
    for key in ("events", "observations", "briefs", "ideas"):
        ids = because.get(key, [])
        if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool)
                                                for i in ids) or len(ids) > 50:
            raise TicketError(f"because.{key} is a list of at most 50 ids")
    labels = because.get("labels", [])
    if not isinstance(labels, list) or len(labels) > 50 or not all(
            isinstance(x, str) and len(x) <= 40 for x in labels):
        raise TicketError("because.labels is a list of at most 50 short labels")
    return because


def fields_hash(kind: str, fields: dict[str, Any]) -> str:
    text = json.dumps({"kind": kind, "fields": fields}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def state_of(store: Store, ticket_id: int) -> dict[str, Any] | None:
    r = store.query_one("SELECT * FROM cub_ticket_states WHERE ticket_id = ? ORDER BY id DESC "
                        "LIMIT 1", (int(ticket_id),))
    return dict(r) if r else None


def _append_state(store: Store, ticket_id: int, state: str, *, door: str | None = None,
                  note: str | None = None, now: datetime | None = None) -> None:
    store.insert("cub_ticket_states", {"ticket_id": int(ticket_id), "state": state,
                                       "door": door, "note": (note or None) and note[:500],
                                       "created_at": iso(now or utcnow())})


def _resolved(store: Store, t: dict[str, Any], state: str) -> None:
    events.core_publish(store, "ticket.resolved", {"ticket_id": int(t["id"]), "kind": t["kind"],
                                                   "cub": t["cub"], "state": state},
                        subject=("ticket", t["id"]))


# for ``core.asks.wait_again``: a state row and its event, as this module writes them
append_state = _append_state
resolved = _resolved


def _draft_owner(store: Store, ref: str) -> str | None:
    r = store.query_one("SELECT cub FROM cub_drafts WHERE ref = ?", (ref,))
    return r["cub"] if r else None


def open_ticket(store: Store, kind: str, digest: str, now: datetime) -> int | None:
    """The open ticket of ``kind`` with these fields, if any."""
    for r in store.query("SELECT id FROM cub_tickets WHERE kind = ? AND fields_hash = ? "
                         "ORDER BY id DESC", (kind, digest)):
        st = state_of(store, r["id"])
        if st and st["state"] in (OPEN, "confirmed") and not _expired(store, r["id"], now):
            return int(r["id"])
    return None


def filed_today(store: Store, cub: str, kind: str, now: datetime) -> int:
    day = iso(now - timedelta(days=1))
    counted = store.query_one("SELECT COUNT(*) AS n FROM cub_tickets WHERE cub = ? AND "
                              "kind = ? AND created_at >= ?", (cub, kind, day))
    assert counted is not None                 # COUNT(*) always answers one row
    return int(counted["n"])


def file(store: Store, *, cub: str, trust: str, granted: tuple[str, ...], kind: str,
         fields: dict[str, Any], because: dict[str, Any] | None = None,
         subject: tuple[str, str | int] | None = None,
         run_uuid: str | None = None, per_day: int | None = None,
         now: datetime | None = None, note: str | None = None, capped: bool = True) -> int:
    """File a ticket; its id. Refused when the filer was not granted the kind, the fields do
    not fit, a ``draft_ref`` is not the filer's draft, an open ticket with the same fields
    exists (409 with its id), or the day's cap is reached (429). ``per_day`` lowers, never
    raises, the kind's cap (``cubs.<id>.tickets_per_day``). ``note``: its first state's
    words (a draft offered again by the owner's click, ``core.asks.again``). ``capped``
    False: the owner's own edit of a waiting draft (``post.edit``), which replaces an ask the
    cub filed and is not one more ask of the cub's, so the cub's daily cap does not count it."""
    kind_names()
    if canonical(kind) not in {canonical(k) for k in granted}:
        raise TicketError(f"{cub} may not request {kind}: its manifest does not list it", 403)
    spec = KINDS.get(kind)
    if spec is None:
        raise TicketError(f"no high-trust action {kind}", 404)
    if not grantable_to(kind, trust):
        raise TicketError(f"{kind} is Kranto's own: a {trust} cub may not ask for it", 403)
    now = now or utcnow()
    clean = _check(spec, fields)
    prov = _because(because)
    if "draft_ref" in clean and _draft_owner(store, clean["draft_ref"]) != cub:
        raise TicketError(f"{kind}.draft_ref: {clean['draft_ref']} is not one of {cub}'s drafts")
    digest = fields_hash(kind, clean)
    cap = spec.per_day if per_day is None else max(0, min(int(per_day), spec.per_day))
    with store.tx():
        dup = open_ticket(store, kind, digest, now)
        if dup is not None:
            raise TicketError(f"the same one waits for you already (#{dup})", 409, dup)
        n = filed_today(store, cub, kind, now)
        if capped and n >= cap:
            raise TicketError(f"{cub} has asked {n} times for {kind} in a day (at most {cap})",
                              429)
        tid = store.insert("cub_tickets", {
            "cub": cub, "kind": kind, "trust": trust,
            "subject_kind": subject[0] if subject else None,
            "subject_id": str(subject[1]) if subject else None,
            "fields": TicketFields.write(clean), "fields_hash": digest,
            "because": TicketBecause.write(prov), "run_uuid": run_uuid,
            "expires_at": NEVER if spec.expires_hours is None
            else iso(now + timedelta(hours=spec.expires_hours)),
            "created_at": iso(now)})
        _append_state(store, tid, OPEN, now=now, note=note)
        older = _replace_older(store, tid, cub=cub, kind=kind, subject=subject, now=now)
    events.core_publish(store, "ticket.filed", {"ticket_id": tid, "kind": kind, "cub": cub},
                        subject=("ticket", tid))
    for old in older:
        t = get(store, old, now=now)
        if t:
            _resolved(store, t, "expired")
    return tid


def _replace_older(store: Store, tid: int, *, cub: str, kind: str,
                   subject: tuple[str, str | int] | None, now: datetime) -> list[int]:
    """The open tickets a new one replaces, closed as ``expired`` with ``replaced by #<tid>``:
    when the new one's kind waits until answered, the same filer's open ones of the same kind
    (an alias counts as its kind; one filed with a time limit before this release too) and of
    the same series (every one of a ``meta.series`` kind: next Monday's issue replaces
    this Monday's; else the same subject). So Needs you holds one row a series, and the older
    draft is still there to open, copy and download."""
    spec = KINDS.get(kind)
    if spec is None or spec.expires_hours is not None:
        return []
    series = bool(KINDS.get(canonical(kind), spec).meta.get("series"))
    if not series and subject is None:
        return []
    names = [k for k in KINDS if canonical(k) == canonical(kind)]
    marks = ",".join("?" * len(names))
    sql = f"SELECT id FROM cub_tickets WHERE cub = ? AND kind IN ({marks}) AND id < ?"
    params: list[Any] = [cub, *names, int(tid)]
    if not series and subject is not None:
        sql += " AND subject_kind = ? AND subject_id = ?"
        params += [subject[0], str(subject[1])]
    out = []
    for r in store.query(sql, tuple(params)):
        st = state_of(store, r["id"])
        if st and st["state"] == OPEN:
            _append_state(store, r["id"], "expired", door="core", note=f"{REPLACED}{tid}",
                          now=now)
            out.append(int(r["id"]))
    return out


def _expired(store: Store, ticket_id: int, now: datetime) -> bool:
    r = store.query_one("SELECT expires_at FROM cub_tickets WHERE id = ?", (int(ticket_id),))
    return r is not None and r["expires_at"] <= iso(now)


def resting_on(store: Store, key: str, ref: int | str, *, limit: int = 20) -> list[dict[str, Any]]:
    """The tickets whose ``because.<key>`` names ``ref`` (an idea card's id, a trend's key),
    newest first: ``{id, cub, kind, title, state, created_at}``. A scan of the
    tickets' JSON: they are few by construction (per-day caps per kind)."""
    if key not in ("ideas", "trends"):
        raise ValueError("key is ideas or trends")
    rows = store.query(
        "SELECT t.id FROM cub_tickets t WHERE EXISTS (SELECT 1 FROM json_each(t.because, ?) b "
        "WHERE b.value = ?) ORDER BY t.id DESC LIMIT ?", (f"$.{key}", ref, int(limit)))
    out = []
    for r in rows:
        t = get(store, r["id"])
        if t:
            out.append({k: t[k] for k in ("id", "cub", "kind", "title", "state", "created_at")})
    return out


def get(store: Store, ticket_id: int, *, now: datetime | None = None) -> dict[str, Any] | None:
    """One ticket with its read-back, provenance and history. ``feature`` repeats ``cub``
    for the page's readers of ``/api/requests`` through 0.5.x."""
    kind_names()
    r = store.query_one("SELECT * FROM cub_tickets WHERE id = ?", (int(ticket_id),))
    if r is None:
        return None
    st = state_of(store, ticket_id) or {"state": OPEN}
    state = st["state"]
    if state == OPEN and _expired(store, ticket_id, now or utcnow()):
        state = "expired"
    spec = KINDS.get(r["kind"])
    fields = TicketFields.load(r["fields"]).extra
    history = [dict(x) for x in store.query(
        "SELECT state, door, note, created_at FROM cub_ticket_states WHERE ticket_id = ? "
        "ORDER BY id", (int(ticket_id),))]
    resolved = next((h["created_at"] for h in reversed(history) if h["state"] in FINAL), None)
    from .asks import said
    out = {"id": r["id"], "cub": r["cub"], "feature": r["cub"], "kind": r["kind"],
            "trust": r["trust"], "title": spec.title if spec else r["kind"],
            "subject_kind": r["subject_kind"], "subject_id": r["subject_id"], "fields": fields,
            "because": TicketBecause.load(r["because"]).extra, "state": state,
            "note": st.get("note"),
            "run_uuid": r["run_uuid"], "expires_at": r["expires_at"],
            "created_at": r["created_at"], "resolved_at": resolved,
            "performs": bool(spec and spec.perform is not None),
            "readback": readback_of(spec, fields, store) if spec
            else [[k, str(v)] for k, v in fields.items()],
            "history": history}
    out["said"] = said(out)            # what happened, in the owner's words (None: it waits)
    return out


def listing(store: Store, *, cub: str | None = None, open_only: bool = False,
            subject: tuple[str, str | int] | None = None, limit: int = 50,
            now: datetime | None = None, unreadable: bool = False) -> list[dict[str, Any]]:
    """The tickets, newest first. One that cannot be read is kept once by its error's id and
    left out (a cub, a feature and the counts read tickets' fields); ``unreadable`` lists it as
    "Couldn't read this ticket" instead (the page's list: ``GET /api/tickets``, RCA A3)."""
    sql = "SELECT id FROM cub_tickets WHERE 1 = 1"
    params: list[Any] = []
    if cub:
        sql, params = sql + " AND cub = ?", [*params, cub]
    if subject is not None:
        sql, params = sql + " AND subject_kind = ? AND subject_id = ?", \
            [*params, subject[0], str(subject[1])]
    rows = store.query(sql + " ORDER BY id DESC LIMIT ?", (*params, max(1, min(limit, 500))))
    from ..rowsafe import each
    out = each(rows, lambda r: get(store, r["id"], now=now), "ticket", ident=lambda r: r["id"])
    return [t for t in out if t and (unreadable if t.get("unreadable") else
                                     not open_only or t["state"] == OPEN)]


def door_of(identity: dict[str, Any] | None) -> str | None:
    """The door a caller came through: ``ui`` only for the page's session cookie."""
    if not identity:
        return None
    origin = identity.get("origin")
    if origin == "ui" and identity.get("via") != "cookie":
        return "ui-token"
    return origin


# -- the mode of a press -------------------------------------------------------------------


def stop_file() -> Path:
    """``~/.config/kranto/cubs.STOP``: while it exists no cub runs and every press of a cub's
    ticket resolves ``dry`` (a phone shell's ``touch``)."""
    return Path(os.environ.get("KRANTO_CUBS_STOP") or
                Path.home() / ".config" / "kranto" / "cubs.STOP")


def press_mode(store: Store, cfg: Any, t: dict[str, Any]) -> tuple[str, str | None]:
    """``(mode, why)`` for a press on ticket ``t`` now: ``live`` or ``dry`` and, when dry,
    why in words. Kranto's own features keep their own modes (``live`` here)."""
    if t["trust"] in FIRST_PARTY:
        return "live", None
    if stop_file().exists():
        return "dry", f"cubs.STOP exists ({stop_file()})"
    from .cubs import settings as cub_settings
    if not any(same_kind(t["kind"], k) for k in cub_settings.live_kinds(cfg, t["cub"])):
        return "dry", f"{t['kind']} is not live for {t['cub']}"
    outside = cub_settings.outside_range(store, t["cub"])
    if outside:
        return "dry", outside
    return "live", None


def _perform(spec: Kind, store: Store, t: dict[str, Any], context: Any, mode: str) -> dict[str,
             Any]:
    """Call the performer with the press's mode when it takes one."""
    performer = spec.perform
    assert performer is not None               # only a kind with a performer is pressed
    params = inspect.signature(performer).parameters
    if "mode" in params:
        return performer(store, t, context, mode=mode) or {}
    return performer(store, t, context) or {}


WHEN = re.compile(r"now|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z")


def _when(spec: Kind, when: str | None, now: datetime) -> str | None:
    """The time the owner chose in the dialog (Send now, or Schedule's time): only for a kind
    that schedules, ``now`` or a UTC time still ahead."""
    if when is None:
        return None
    if not spec.meta.get("schedules"):
        raise TicketError(f"{spec.title} goes now: it takes no time")
    if not isinstance(when, str) or not WHEN.fullmatch(when):
        raise TicketError("when is now or a UTC time like 2026-11-02T09:30Z")
    if when != "now" and when.replace("Z", "")[:16] <= iso(now).replace("Z", "")[:16]:
        raise TicketError("that time has passed: choose a later one")
    return when


def confirm(store: Store, ticket_id: int, *, identity: dict[str, Any] | None, confirm: bool,
            context: object = None, now: datetime | None = None,
            when: str | None = None) -> dict[str, Any]:
    """The owner's press. Checks the door, the state and the expiry, moves the ticket to
    ``confirmed`` atomically, then runs the kind's performer in the mode of the press and
    records its outcome. A dry press of a cub's ticket while ``cubs.STOP`` exists never reaches
    the performer. ``when``: the time the owner chose in the dialog, for a kind that schedules
    (``press_when``; the ticket's own ``when`` otherwise)."""
    kind_names()
    now = now or utcnow()
    t = get(store, ticket_id, now=now)
    if t is None:
        raise TicketError("not found", 404)
    spec = KINDS.get(t["kind"])
    door = door_of(identity)
    # who may press comes first: a wrong door learns nothing more about the ticket
    doors, page_only = (spec.doors, spec.page_only) if spec else (("ui",), True)
    if door not in doors or (page_only and door != "ui"):
        raise TicketError(f"{spec.title if spec else t['kind']} is confirmed on the page only, "
                          "by your click and the confirm dialog (never from the command line, "
                          "kranto mcp, an agent token, a chat or a cub)", 403)
    if spec is None or spec.perform is None:
        raise TicketError(f"{t['kind']} has no performer in this Kranto: decline it, or wait "
                          "for Kranto that performs it", 409)
    if confirm is not True:
        raise TicketError("the confirm dialog's answer is missing: this needs confirm: true")
    chosen = _when(spec, when, now)
    cfg = getattr(context, "cfg", None)
    from .. import preview
    if preview.enabled(getattr(cfg, "root", None)):
        # the preview never performs: refused before any state is written, so the ask stays
        raise TicketError(preview.NOTHING_SENT + ".", 409)
    mode, why = press_mode(store, cfg, t)
    with store.tx():
        st = state_of(store, ticket_id)
        if not st or st["state"] != OPEN:
            done = st["state"] if st else "unknown"
            raise TicketError(f"this was answered already ({done}): an approval happens once",
                              409)
        expired = _expired(store, ticket_id, now)
        if expired:
            # recorded, then refused outside the transaction (a raise inside rolls it back)
            _append_state(store, ticket_id, "expired", door="core", now=now)
        else:
            _append_state(store, ticket_id, "confirmed", door=door,
                          note=f"mode: {mode}" + (f"; when: {chosen}" if chosen else ""),
                          now=now)
    if expired:
        _resolved(store, t, "expired")
        raise TicketError(f"this waited past its time ({t['expires_at'][:16].replace('T', ' ')}"
                          " UTC): offer it again from its row", 409)
    if mode == "dry" and why and why.startswith("cubs.STOP"):
        outcome = {"state": "dry", "note": f"practice: nothing was done ({why})"}
    else:
        try:
            outcome = _perform(spec, store, {**t, "press_mode": mode, "press_why": why,
                                             **({"press_when": chosen} if chosen else {})},
                               context, mode)
        except Exception as exc:  # noqa: BLE001 - recorded as unknown; never retried by itself
            outcome = {"state": "unknown", "note": f"{type(exc).__name__}: {exc}"[:300]}
    state = outcome.get("state", "done")
    if state not in FINAL or state in ("declined", "expired"):
        state = "unknown"
    if mode == "dry" and state == "done":
        # a performer that ignored the mode must not report a send that the mode forbade
        state, outcome = "unknown", {**outcome, "note": "the performer reported done in "
                                                        "practice: " + str(outcome.get("note"))}
    _append_state(store, ticket_id, state, door=door, note=outcome.get("note"), now=now)
    _resolved(store, t, state)
    return {**(get(store, ticket_id, now=now) or {}), "outcome": outcome, "mode": mode}


def decline(store: Store, ticket_id: int, *, identity: dict[str, Any] | None,
            note: str | None = None
            ) -> dict[str, Any]:
    """The owner's Decline, from the page or the command line."""
    t = get(store, ticket_id)
    if t is None:
        raise TicketError("not found", 404)
    door = door_of(identity)
    if door not in ("ui", "ui-token", "cli"):
        raise TicketError("this is declined on the page or from the command line", 403)
    if t["state"] != OPEN:
        raise TicketError(f"this was answered already ({t['state']})", 409)
    _append_state(store, ticket_id, "declined", door=door, note=note)
    _resolved(store, t, "declined")
    return get(store, ticket_id) or {}


def expire_for(store: Store, *, cub: str, subject_kind: str, subject_id: str | int,
               note: str) -> int:
    """Close a filer's open tickets about one subject (a proposal dismissed or refreshed, an
    issue redrafted)."""
    n = 0
    for r in store.query("SELECT id FROM cub_tickets WHERE cub = ? AND subject_kind = ? "
                         "AND subject_id = ?", (cub, subject_kind, str(subject_id))):
        st = state_of(store, r["id"])
        if st and st["state"] == OPEN:
            _append_state(store, r["id"], "expired", door="core", note=note)
            t = get(store, r["id"])
            if t:
                _resolved(store, t, "expired")
            n += 1
    return n


def expire_all(store: Store, *, cub: str, note: str) -> int:
    """Close every open ticket of a cub (it was stopped or removed:)."""
    n = 0
    for r in store.query("SELECT id FROM cub_tickets WHERE cub = ?", (cub,)):
        st = state_of(store, r["id"])
        if st and st["state"] == OPEN:
            _append_state(store, r["id"], "expired", door="core", note=note)
            t = get(store, r["id"])
            if t:
                _resolved(store, t, "expired")
            n += 1
    return n


def expire_due(store: Store, now: datetime | None = None) -> int:
    """Append ``expired`` for open tickets past their time, so lists and counts are right
    without a press (the daily ``cubs.gc``)."""
    now = now or utcnow()
    n = 0
    for r in store.query("SELECT id FROM cub_tickets WHERE expires_at <= ?", (iso(now),)):
        st = state_of(store, r["id"])
        if st and st["state"] == OPEN:
            _append_state(store, r["id"], "expired", door="core", note="past its time", now=now)
            t = get(store, r["id"], now=now)
            if t:
                _resolved(store, t, "expired")
            n += 1
    return n
