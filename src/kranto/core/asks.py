"""What a cub asks you, in plain words (SEND; the owner, 2026-10-29: "Not sure what 'ticket #1 is
expired' means, I just wanted to post the newsletter. Seems like nothing is connected.").

A cub's high-trust action is a ticket (``core.tickets``): typed fields, one confirm on the page,
an expiry, an append-only history. The owner never reads that word. They read an *ask*:

- **a row**, one line: the draft's title, where it stands ("ready", "needs a newsletter
  account", "practice: nothing is sent") and the action's own button ("Send", "Post toot");
- **the dialog**, from ``ask`` here: the title, whom it goes to, the body, what stops it (an
  account to connect, practice mode with the cub's own switch), and the action's verb;
- **the history**, from ``said``: "Sent on 28 Oct", "Practiced on 28 Oct: not sent".

Who asks is the core, never the cub's prose: a cub's own rows of Needs you that carry a ticket
are dropped and the core's asks stand in their place (``needs_rows``), and a cub's read that
names a ticket which is no longer open names none (``overlay``), so an expired or used ticket
never opens a dialog anywhere. When the newest ask of a cub's draft is practiced, expired or
refused and that draft is still the cub's newest, the row offers it again: ``again`` files a
fresh ticket with the same fields under the same rules, by the owner's click on the page (no
cub run, no model call).

A draft waits until it is seen: a draft's ask has no time limit, and leaves the
waiting asks only when it is sent, declined, or replaced by the next draft of its series
(``tickets._replace_older``). A draft whose ask ran out of time under an earlier release, and
which is still its cub's newest and was never pressed or declined, waits again: ``wait_again``
files its fresh ask once (the cubs' start and their daily ``cubs.gc``), so nothing the owner has
not seen disappears.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..store import Store, iso, utcnow
from . import tickets

log = logging.getLogger(__name__)

# the states whose draft may be offered again: practiced, ran out of time, refused (the account
# was not connected, the time had passed); never declined (the owner said no), done, or unknown
# (it may have gone out)
AGAIN = ("dry", "expired", "refused")
PRACTICE = "Practice: nothing is sent"


def day(at: str | None) -> str:
    """``2026-10-28T06:39:05Z`` as "28 Oct"."""
    try:
        d = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return str(at or "")[:10]
    return f"{d.day} {d.strftime('%b')}"


def words_of(kind: str) -> dict[str, str]:
    """The kind's own words (``Kind.meta``): its verb, its row button, its noun, what done and
    not done are called. A kind that names none speaks of "it"."""
    spec = tickets.KINDS.get(kind)
    meta = spec.meta if spec else {}
    if "alias_of" in meta:
        meta = {**tickets.KINDS[meta["alias_of"]].meta, **meta}
    title = spec.title if spec else kind
    return {"verb": meta.get("verb") or "Approve", "button": meta.get("button") or "Open",
            "noun": meta.get("noun") or "it", "done": meta.get("done") or "Done",
            "not_done": meta.get("not_done") or "not done", "title": title,
            "question": meta.get("question") or f"{title}?"}


def said(t: dict[str, Any]) -> str | None:
    """A ticket's outcome in the owner's words, for the history and the dialog's last line:
    None while it waits."""
    w = words_of(t["kind"])
    state, note = t["state"], str(t.get("note") or "")
    at = day(t.get("resolved_at") or t.get("created_at"))
    if state == "done":
        if note.startswith("scheduled"):
            return f"Scheduled on {at}"
        return f"{w['done']} on {at}"
    if state == "dry":
        return f"Practiced on {at}: {w['not_done']}"
    if state == "declined":
        return f"Declined on {at}"
    if state == "expired" and tickets.replaced_by(note):
        return f"Replaced by a newer {w['noun'] if w['noun'] != 'it' else 'draft'} ({at})"
    if state == "expired":
        return f"Not approved in time: {w['not_done']} ({at})"
    if state == "refused":
        why = note.split(":", 1)[1].strip() if note.startswith("refused:") else note
        return f"{w['not_done'].capitalize()} on {at}" + (f": {why}" if why else "")
    if state == "unknown":
        return f"Not sure it went out ({at}): {note}" if note else f"Not sure it went out ({at})"
    return None


# -- the draft a ticket names -----------------------------------------------------------------


def _family(service: str) -> tuple[str, ...]:
    """A draft's service and the names it shares a draft list with (the newsletter's aliases)."""
    from .cubs.brokers.newsletter import NewsletterAdapter
    names = NewsletterAdapter.services()
    return tuple(names) if service in names else (service,)


def newest_draft(store: Store, cub: str, ref: str | None) -> bool:
    """Whether ``ref`` is the cub's newest draft of its service."""
    if not ref:
        return False
    row = store.query_one("SELECT service FROM cub_drafts WHERE ref = ? AND cub = ?", (ref, cub))
    if row is None:
        return False
    names = _family(row["service"])
    marks = ",".join("?" * len(names))
    top = store.query_one(f"SELECT ref FROM cub_drafts WHERE cub = ? AND service IN ({marks}) "
                          "ORDER BY id DESC LIMIT 1", (cub, *names))
    return top is not None and top["ref"] == ref


def _newer_ask(store: Store, t: dict[str, Any]) -> bool:
    """Whether a later ticket of the same cub names the same draft (it was offered again)."""
    ref = (t.get("fields") or {}).get("draft_ref")
    return bool(ref) and store.query_one(
        "SELECT 1 FROM cub_tickets WHERE cub = ? AND id > ? AND "
        "json_extract(fields, '$.draft_ref') = ?", (t["cub"], int(t["id"]), ref)) is not None


def again_why_not(store: Store, t: dict[str, Any]) -> str | None:
    """Why this ticket's draft cannot be offered again, or None."""
    if t["state"] not in AGAIN:
        return f"it is {t['state']}" if t["state"] != tickets.OPEN else "it waits for you already"
    ref = (t.get("fields") or {}).get("draft_ref")
    if not ref:
        return "it names no draft"
    if not newest_draft(store, t["cub"], ref):
        return "a newer draft has come since"
    if _newer_ask(store, t):
        return "it was offered again already"
    return None


# -- the dialog ---------------------------------------------------------------------------------


def _live_kind(rt: Any, t: dict[str, Any]) -> str | None:
    """The kind of the cub's manifest this ticket's kind is (an alias's canonical kind)."""
    cubs = getattr(rt, "cubs", None)
    cub = cubs.installed.get(t["cub"]) if cubs is not None else None
    asks = list(cub.grants.requests) if cub is not None else []
    return next((k for k in asks if tickets.same_kind(k, t["kind"])), None)


def ask(rt: Any, t: dict[str, Any]) -> dict[str, Any]:
    """The dialog of one ticket, from its typed fields and Kranto's own rows (never the cub's
    prose): ``verb``, ``title``, ``to``, ``body``, ``needs`` (what stops it, with the account to
    connect), ``schedule`` (whether a time may be chosen), ``practice`` (``on`` while an approval
    sends nothing, and the cub's own Send for real switch when the owner may turn it), ``open``,
    ``said``, ``again`` and ``question`` (the dialog's title)."""
    spec = tickets.KINDS.get(t["kind"])
    w = words_of(t["kind"])
    store = rt.store
    own: dict[str, Any] = {}
    if spec is not None and spec.ask is not None:
        try:
            own = dict(spec.ask(t["fields"], store, rt) or {})
        except (KeyError, TypeError, ValueError):
            own = {}
    out: dict[str, Any] = {
        "question": w["question"], "verb": own.get("verb") or w["verb"],
        "button": w["button"], "noun": w["noun"],
        "title": own.get("title") or w["title"], "to": own.get("to"),
        "body": own.get("body") or "", "needs": own.get("needs"),
        "schedule": bool(own.get("schedule")), "when": own.get("when"),
        # the time the dialog's Schedule is typed in: ``utc`` (a platform's own schedule, the
        # newsletter's) or ``local`` (Kranto holds the post: the person's own clock)
        "zone": own.get("zone") or "utc",
        "open": t["state"] == tickets.OPEN, "said": said(t),
        "again": t["state"] != tickets.OPEN and again_why_not(store, t) is None,
        "practice": None,
        # a kind with no plain words of its own (Invest's order) shows its read-back as the
        # dialog's facts: nothing it approves is hidden behind Details
        "facts": [] if own else [list(x) for x in t.get("readback") or []
                                 if len(str(x[1])) <= 300]}
    from .. import preview
    if preview.enabled(getattr(getattr(rt, "cfg", None), "root", None)):
        # the preview: no account is copied, and none is needed: the press is the
        # owner's to try, and the confirm answers that nothing is sent
        out["needs"] = None
        out["practice"] = {"on": True, "words": preview.NOTHING_SENT, "switch": None}
        return out
    if t["trust"] in tickets.FIRST_PARTY:
        return out                       # Kranto's own features keep their own modes
    mode, why = tickets.press_mode(store, getattr(rt, "cfg", None), t)
    kind = _live_kind(rt, t)
    # the switch is the cub's own setting (cubs.<id>.live): offered while nothing else holds
    # the ask in practice (cubs.STOP, a Kranto outside the cub's range)
    can = kind is not None and (mode == "live"
                                or (why or "").endswith(f"is not live for {t['cub']}"))
    if mode == "dry" or can:
        out["practice"] = {
            "on": mode == "dry",
            "words": PRACTICE if mode == "dry" and can
            else f"{PRACTICE} ({_why_practice(why)})" if mode == "dry" else "",
            "switch": {"cub": t["cub"], "kind": kind,
                       "words": f"This {w['noun']} and the ones after it go out when you "
                                "approve them"} if can else None}
    return out


def _preview_words() -> str:
    from .. import preview
    return preview.NOTHING_SENT


def _why_practice(why: str | None) -> str:
    if why and why.startswith("cubs.STOP"):
        return "every cub is stopped by the cubs.STOP file"
    return why or "this Kranto holds it"


# -- the rows -----------------------------------------------------------------------------------


def row(rt: Any, t: dict[str, Any]) -> dict[str, Any]:
    """One ask as a cub's row of Needs you (the shape a cub's ``rows`` read answers)."""
    a = ask(rt, t)
    if a["needs"]:
        line = a["needs"]["line"]
    elif a["practice"] and a["practice"]["on"]:
        line = "practice: nothing is sent" if a["practice"]["words"] != _preview_words() \
            else "the preview: nothing is sent"
    else:
        line = "ready"
    ref = (t.get("fields") or {}).get("draft_ref")
    return {"id": ref or f"ask{t['id']}", "title": a["title"], "meta": line,
            "at": t["created_at"], "ticket": t["id"] if a["open"] else None,
            "again": t["id"] if a["again"] else None, "verb": a["button"],
            "ask": {"line": line, "said": a["said"], "open": a["open"]}}


def latest(store: Store, cub: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
    """The asks that wait: every open ticket, and the newest resolved ticket of a draft that
    may be offered again; newest first."""
    out, seen = [], set()
    for t in tickets.listing(store, cub=cub, limit=limit):
        ref = (t.get("fields") or {}).get("draft_ref")
        key = (t["cub"], ref or f"#{t['id']}")
        if key in seen:
            continue
        seen.add(key)
        if t["state"] == tickets.OPEN or again_why_not(store, t) is None:
            out.append(t)
    return out


def count(store: Store, cub: str) -> int:
    return len(latest(store, cub))


def rows(rt: Any, cub: str) -> list[dict[str, Any]]:
    return [row(rt, t) for t in latest(rt.store, cub)]


def needs_rows(rt: Any, cub: str, got: Any) -> Any:
    """A cub's Needs you read with the core's asks: its own rows that carry a ticket (any
    state, any shape) are dropped, the core's stand first."""
    if not isinstance(got, dict) or not isinstance(got.get("rows"), list):
        return got
    kept = [r for r in got["rows"] if not (isinstance(r, dict) and "ticket" in r)]
    return {**got, "rows": [*rows(rt, cub), *kept]}


def overlay(store: Store, cub: str, got: Any) -> Any:
    """A cub's read with every ticket it names checked: a ticket that is not open (or not this
    cub's) is named as none, so no list offers a dialog on it."""
    open_ids = {int(r["ticket_id"]) for r in store.query(
        "SELECT s.ticket_id FROM cub_ticket_states s JOIN cub_tickets t ON t.id = s.ticket_id "
        "WHERE t.cub = ? AND s.id = (SELECT MAX(id) FROM cub_ticket_states x "
        "WHERE x.ticket_id = s.ticket_id) AND s.state = ? AND t.expires_at > ?",
        (cub, tickets.OPEN, iso(utcnow())))}

    def walk(x: Any) -> Any:
        if isinstance(x, list):
            return [walk(v) for v in x]
        if not isinstance(x, dict):
            return x
        out = {k: walk(v) for k, v in x.items()}
        if "ticket" in out:
            t = out["ticket"]
            tid = t.get("id") if isinstance(t, dict) else t
            if not (isinstance(tid, int) and not isinstance(tid, bool) and tid in open_ids):
                out["ticket"] = None
        return out

    return walk(got)


# -- offered again ------------------------------------------------------------------------------


def again(rt: Any, ticket_id: int, *, identity: dict[str, Any] | None) -> dict[str, Any]:
    """The owner's click on a row that offers a draft again: a fresh ticket with the same
    fields, under the same rules (the cub's grant, its daily cap, the duplicate check), filed
    in the cub's name with its history's first line saying so. The page only."""
    store = rt.store
    if tickets.door_of(identity) != "ui":
        raise tickets.TicketError("a draft is offered again on the page only, by your click", 403)
    t = tickets.get(store, ticket_id)
    if t is None:
        raise tickets.TicketError("not found", 404)
    why = again_why_not(store, t)
    if why:
        raise tickets.TicketError(f"this one cannot be offered again: {why}", 409)
    cubs = getattr(rt, "cubs", None)
    cub = cubs.installed.get(t["cub"]) if cubs is not None else None
    if cubs is None or cub is None or cub.state != "installed":
        raise tickets.TicketError(f"{t['cub']} is not installed and running", 409)
    kind = _live_kind(rt, t)
    if kind is None:
        raise tickets.TicketError(f"{t['cub']} no longer asks for this", 409)
    spec = tickets.KINDS[kind]
    fields = {k: v for k, v in t["fields"].items() if k in spec.fields}
    if "when" in spec.fields and "when" not in fields:
        fields["when"] = "now"
    own_cap = cubs.cub_value(cub, "tickets_per_day")
    per_day = spec.per_day if own_cap is None else min(own_cap, spec.per_day)
    subject = (t["subject_kind"], t["subject_id"]) if t.get("subject_kind") else None
    tid = tickets.file(store, cub=t["cub"], trust=t["trust"], granted=tuple(cub.grants.requests),
                       kind=kind, fields=fields, because=t["because"], subject=subject,
                       run_uuid=None, per_day=per_day,
                       note=f"offered again by your click (it was #{t['id']}, {t['state']})")
    return tickets.get(store, tid) or {"id": tid}


def history(store: Store, cub: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """A cub's asks as its history reads them: the title and what happened, in words."""
    out = []
    for t in tickets.listing(store, cub=cub, limit=limit):
        fields = t.get("fields") or {}
        out.append({"id": t["id"], "title": fields.get("subject") or fields.get("title")
                    or (fields.get("text") or "")[:80] or words_of(t["kind"])["title"],
                    "said": said(t) or "Waits for you", "at": t["created_at"],
                    "state": t["state"]})
    return out


# -- a draft waits until it is seen ------------------------------------------------------------


def _answered(store: Store, cub: str, ref: str) -> bool:
    """Whether the owner ever pressed or declined an ask of this draft (its tickets' history)."""
    return store.query_one(
        "SELECT 1 FROM cub_ticket_states s JOIN cub_tickets t ON t.id = s.ticket_id "
        "WHERE t.cub = ? AND json_extract(t.fields, '$.draft_ref') = ? "
        "AND s.state IN ('confirmed', 'declined') LIMIT 1", (cub, ref)) is not None


def wait_again(store: Store, installed: dict[str, Any], *,
               now: datetime | None = None) -> list[int]:
    """The asks filed again because their draft's time ran out before drafts waited (the old rows
    are not rewritten). For each draft, its newest ask is looked at: it ran out of
    time (``tickets.time_expired``: not answered, withdrawn or replaced), the draft is still
    its cub's newest of its service, nobody ever pressed or declined an ask of it, the cub is
    installed and still asks for the kind, and the kind now waits until it is answered. Then a
    fresh ask with the same fields is filed under the same rules (the grant, the cap, the
    duplicate check), its history's first line saying why. An ask open past its time that the
    daily sweep has not reached yet gets its ``expired`` row first. Idempotent: the fresh ask is
    the draft's newest. The new tickets' ids."""
    now = now or utcnow()
    out: list[int] = []
    seen: set[tuple[str, str]] = set()
    for t in tickets.listing(store, limit=500, now=now):          # newest first
        ref = (t.get("fields") or {}).get("draft_ref")
        if not ref or (t["cub"], ref) in seen:
            continue
        seen.add((t["cub"], ref))
        if not tickets.time_expired(t) or not newest_draft(store, t["cub"], ref) \
                or _answered(store, t["cub"], ref):
            continue
        cub = installed.get(t["cub"])
        if cub is None or getattr(cub, "state", None) != "installed":
            continue
        kind = next((k for k in cub.grants.requests if tickets.same_kind(k, t["kind"])), None)
        spec = tickets.KINDS.get(kind or "")
        if kind is None or spec is None or spec.expires_hours is not None:
            continue
        if (t.get("history") or [{}])[-1].get("state") != "expired":
            tickets.append_state(store, t["id"], "expired", door="core",
                                 note=tickets.PAST_TIME, now=now)
            tickets.resolved(store, t, "expired")
        fields = {k: v for k, v in t["fields"].items() if k in spec.fields}
        if "when" in spec.fields and "when" not in fields:
            fields["when"] = "now"
        subject = (t["subject_kind"], t["subject_id"]) if t.get("subject_kind") else None
        try:
            tid = tickets.file(store, cub=t["cub"], trust=t["trust"],
                               granted=tuple(cub.grants.requests), kind=kind, fields=fields,
                               because=t["because"], subject=subject, run_uuid=t["run_uuid"],
                               now=now,
                               note=f"waits for you again: it had run out of time (#{t['id']})")
        except tickets.TicketError as exc:
            log.warning("draft %s of %s could not wait again: %s", ref, t["cub"], exc)
            continue
        out.append(tid)
    return out


