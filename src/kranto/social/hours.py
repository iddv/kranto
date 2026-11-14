"""Send at an hour: a post the person said yes to goes at the time they chose.

The design (SOCIAL-DESIGN §3.7, X-7) and the owner's brief of 14 November:

- **Nothing goes without the yes.** The confirm dialog's Schedule records the person's yes for
  one waiting ask, for the words they read (the ask's ``fields_hash``) and the time they chose
  (``post_due``, state ``held``). The ask itself stays open (``needs_confirm``): no ask is left
  ``confirmed`` for days with no outcome, so no reader of the tickets has a new shape to handle.
- **It can be moved or cancelled until then.** Move is a newer ``held`` row; Cancel a
  ``cancelled`` row. The draft goes back to Drafts waiting, its ask open as before.
- **At the hour, Kranto presses it** (``tick``, on the scheduler's own lane, every
  ``TICK_SECONDS``): ``core.tickets.press_held``, the same press as the dialog's, which refuses
  when the ask was answered, declined or replaced by an edit (a changed draft is a new ask and
  needs a new yes), or its words changed. Such a hold ends ``void``.
- **A missed hour asks again.** When Kranto was stopped at the hour (the machine was off) and
  starts more than ``LATE`` after it, nothing is sent late: the hold ends ``missed``, and the
  draft waits on Post with "Its hour passed while Kranto was stopped" until the person says yes
  again (now, or at a new hour).
- **A restart keeps the schedule:** the holds are rows, and the lane reads them every tick.
- **The preview never presses** (the lane does nothing there; the confirm is refused before a
  hold is written).

Every row is appended, never edited: the newest row of a ticket says where it stands.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from ..store import Store, iso, utcnow

log = logging.getLogger("kranto.social.hours")

HELD, CANCELLED, MISSED, VOID, PRESSED = "held", "cancelled", "missed", "void", "pressed"
TICK_SECONDS = 30.0
# Pressed later than this after its hour, a post was missed rather than late: the lane ticks
# every 30 seconds, so only a stopped Kranto (or a machine asleep) is this late.
LATE = timedelta(minutes=10)
# The furthest ahead an hour may be chosen, and the nearest.
MOST_AHEAD = timedelta(days=60)
LEAST_AHEAD = timedelta(minutes=2)
MISSED_WORDS = "Its hour passed while Kranto was stopped"


class HoursError(ValueError):
    def __init__(self, words: str, code: int = 400) -> None:
        super().__init__(words)
        self.words, self.code = words, code


def _at(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def local(value: str | datetime) -> datetime:
    """A stored UTC time in the machine's own zone: Kranto runs on the person's machine, so its
    zone is theirs (News' day and the home's clock read it the same way)."""
    from ..core import home
    dt = _at(value) if isinstance(value, str) else value
    return dt.astimezone(home.LOCAL_TZ) if home.LOCAL_TZ is not None else dt.astimezone()


def said_at(value: str | datetime) -> str:
    """"Tuesday 17 Nov, 09:00" in the person's own time."""
    d = local(value)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%b')}, {d.strftime('%H:%M')}"


def kinds() -> tuple[str, ...]:
    """The asks Kranto may hold for an hour: each site's own send (``Kind.meta.holds``)."""
    from ..core import tickets
    tickets.kind_names()
    return tuple(sorted(k for k, s in tickets.KINDS.items() if s.meta.get("holds")))


def newest(store: Store, ticket_id: int) -> dict[str, Any] | None:
    """A ticket's newest ``post_due`` row, or None when it was never held."""
    r = store.query_one("SELECT * FROM post_due WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
                        (int(ticket_id),))
    return dict(r) if r else None


def _write(store: Store, ticket_id: int, state: str, *, due_at: str, fields_hash: str,
           door: str | None = None, note: str | None = None,
           now: datetime | None = None) -> dict[str, Any]:
    row = {"ticket_id": int(ticket_id), "state": state, "due_at": due_at,
           "fields_hash": fields_hash, "door": door, "note": (note or None) and note[:300],
           "created_at": iso(now or utcnow())}
    rid = store.insert("post_due", row)
    return {"id": rid, **row}


def hold(store: Store, t: dict[str, Any], *, when: str, door: str | None,
         now: datetime | None = None) -> dict[str, Any]:
    """Record the person's yes to send ask ``t`` at ``when`` (a UTC time like
    ``2026-11-17T09:00Z``). ``core.tickets.confirm`` calls it after the door (the page only),
    the answer and the preview were checked. A second hold of the same ask moves it. Returns the
    row and ``said`` ("Goes Tuesday 17 Nov, 09:00 …")."""
    now = now or utcnow()
    if door != "ui":
        raise HoursError("a time is chosen on the page only", 403)
    try:
        due = _at(when if len(when) > 17 else when.replace("Z", ":00Z"))
    except ValueError as exc:
        raise HoursError("when is a UTC time like 2026-11-17T09:00Z") from exc
    if due - now < LEAST_AHEAD:
        raise HoursError("choose a time at least two minutes ahead, or post it now")
    if due - now > MOST_AHEAD:
        raise HoursError("choose a time within the next 60 days")
    r = store.query_one("SELECT fields_hash FROM cub_tickets WHERE id = ?", (int(t["id"]),))
    if r is None:
        raise HoursError("not found", 404)
    before = newest(store, t["id"])
    row = _write(store, t["id"], HELD, due_at=iso(due), fields_hash=r["fields_hash"], door=door,
                 note=f"moved from {before['due_at']}" if before and before["state"] == HELD
                 else None, now=now)
    _event(store, t, "post.scheduled", due_at=row["due_at"])
    return {**row, "said": f"Goes {said_at(due)}. Until then you can move or cancel it on Post."}


def cancel(store: Store, ticket_id: int, *, door: str | None,
           now: datetime | None = None) -> dict[str, Any]:
    """The person's Cancel: the hold ends, nothing is sent, and the draft waits as before."""
    if door not in ("ui", "ui-token"):
        raise HoursError("a scheduled post is cancelled on the page", 403)
    cur = newest(store, ticket_id)
    if cur is None or cur["state"] != HELD:
        raise HoursError("nothing is scheduled for this post", 409)
    row = _write(store, ticket_id, CANCELLED, due_at=cur["due_at"],
                 fields_hash=cur["fields_hash"], door=door, note="cancelled by you", now=now)
    from ..core import tickets
    t = tickets.get(store, ticket_id)
    if t:
        _event(store, t, "post.unscheduled", due_at=cur["due_at"])
    return row


def _event(store: Store, t: dict[str, Any], name: str, **extra: Any) -> None:
    from ..core import events
    try:
        events.core_publish(store, name, {"ticket_id": int(t["id"]), "kind": t["kind"],
                                          "cub": t["cub"], **extra},
                            subject=("ticket", t["id"]))
    except Exception:  # noqa: BLE001 - an event nobody may read must not stop the hold
        log.exception("could not publish %s", name)


def held(store: Store) -> list[dict[str, Any]]:
    """Every ask held for an hour now: the newest row of each ticket whose state is ``held``,
    soonest first."""
    rows = store.query(
        "SELECT d.* FROM post_due d WHERE d.id = (SELECT MAX(id) FROM post_due x "
        "WHERE x.ticket_id = d.ticket_id) AND d.state = ? ORDER BY d.due_at, d.id", (HELD,))
    return [dict(r) for r in rows]


def held_of(store: Store, ticket_id: int | None) -> dict[str, Any] | None:
    """The hold of one ask, when its newest row is ``held`` and the ask is still open."""
    if ticket_id is None:
        return None
    cur = newest(store, ticket_id)
    return cur if cur and cur["state"] == HELD else None


def missed_of(store: Store, ticket_id: int | None) -> dict[str, Any] | None:
    """The hold of one ask that ended ``missed`` (its newest row): the draft says so."""
    if ticket_id is None:
        return None
    cur = newest(store, ticket_id)
    return cur if cur and cur["state"] == MISSED else None


def tick(store: Store, context: Any = None, now: datetime | None = None) -> list[dict[str, Any]]:
    """Press every hold whose hour has come, once: ``pressed`` and the ask's outcome; ``void``
    when the ask was answered or changed; ``missed`` when the hour is more than ``LATE`` past.
    Nothing on the preview. Returns what happened, one entry a hold."""
    from .. import preview
    from ..core import tickets
    if preview.enabled(getattr(getattr(context, "cfg", None), "root", None)):
        return []
    now = now or utcnow()
    out = []
    for h in held(store):
        due = _at(h["due_at"])
        if due > now:
            break                              # soonest first: the rest are later
        tid = int(h["ticket_id"])
        t = tickets.get(store, tid, now=now)
        if t is None or t["state"] != tickets.OPEN:
            why = f"the post was answered before its hour ({t['state'] if t else 'gone'})"
            out.append(_write(store, tid, VOID, due_at=h["due_at"], fields_hash=h["fields_hash"],
                              note=why, now=now))
            continue
        if now - due > LATE:
            out.append(_write(store, tid, MISSED, due_at=h["due_at"],
                              fields_hash=h["fields_hash"],
                              note=f"{MISSED_WORDS}: say yes again to post it", now=now))
            _event(store, t, "post.missed", due_at=h["due_at"])
            _missed_message(store, t, h, now)
            continue
        # the hold is spent before the press, so a press that dies half-way is never pressed
        # again by the next tick (Kranto never retries a send by itself)
        _write(store, tid, PRESSED, due_at=h["due_at"], fields_hash=h["fields_hash"],
               door="core", now=now)
        try:
            got = tickets.press_held(store, tid, context=context, now=now, yes=h)
            out.append({"ticket_id": tid, "state": got.get("state"),
                        "note": (got.get("outcome") or {}).get("note")})
        except tickets.TicketError as exc:
            _write(store, tid, VOID, due_at=h["due_at"], fields_hash=h["fields_hash"],
                   note=str(exc), now=now)
            out.append({"ticket_id": tid, "state": VOID, "note": str(exc)})
    return out


def _missed_message(store: Store, t: dict[str, Any], h: dict[str, Any], now: datetime) -> None:
    """Needs you: a held post whose hour passed while Kranto was stopped waits for a new yes."""
    from .. import notify
    from ..core.asks import words_of
    title = words_of(t["kind"])["verb"]
    try:
        notify.emit(store, "alarm", f"Not posted at {said_at(h['due_at'])}: Kranto was stopped",
                    f"{title}: its hour passed while Kranto was stopped, so nothing was sent "
                    "late. It waits on Post: post it now or choose a new time.",
                    dedup_key=f"post-missed:{t['id']}:{h['due_at']}", origin="post.hours",
                    links=["#/post"], now=now)
    except Exception:  # noqa: BLE001 - the draft still says so on Post
        log.exception("could not say a post's hour was missed")


class HoursLane:
    """The scheduler's lane for held posts: its own thread and pace (``TICK_SECONDS``), so a
    long job (a read, the map) never makes a post late. Held while Kranto updates (``hold``)."""

    name = "post-hours"

    def __init__(self, rt: Any, *, tick_seconds: float = TICK_SECONDS) -> None:
        self.rt = rt
        self.tick_seconds = tick_seconds
        self.hold: str | None = None
        self.last: str | None = None
        self.last_error: str | None = None
        self._stopping = threading.Event()

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set() and not self._stopping.is_set():
            if self.hold is None:
                self.once()
            stop.wait(self.tick_seconds)

    def once(self) -> list[dict[str, Any]]:
        try:
            got = tick(self.rt.store, self.rt)
            self.last, self.last_error = iso(utcnow()), None
            return got
        except Exception as exc:  # noqa: BLE001 - a failing tick must not stop the lane
            log.exception("the post hours tick raised")
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return []

    def request_stop(self) -> None:
        self._stopping.set()

    def status(self) -> dict[str, Any]:
        try:
            n = len(held(self.rt.store))
        except Exception:  # noqa: BLE001 - a status for a page
            n = None
        return {"state": "held" if self.hold else "running", "scheduled": n,
                "last_tick": self.last, "error": self.last_error}
