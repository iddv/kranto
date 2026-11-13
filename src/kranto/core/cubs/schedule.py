"""When a cub's job is due (the schema's ``jobs[].at`` and ``days``).

A job with ``at: "08:00"`` (and ``days: [mon]``) is due once at or after that local time on
each listed day (every day when ``days`` is empty): its slot is the newest such time not after
now, and it is due while no run since that slot ended ``ok``, ``degraded`` or ``skipped``. A
failed run leaves it due, under the scheduler's back-off; a slot missed while Kranto was down is
run once when Kranto is back (a Monday issue on Tuesday, not a lost week). A job without ``at``
is due by its interval, as every job is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ...store import Store

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DONE = ("ok", "degraded", "skipped")


def _zone(tz: str | None):
    try:
        return ZoneInfo(tz or "UTC")
    except Exception:  # noqa: BLE001 - an unknown zone is UTC
        return ZoneInfo("UTC")


def local_zone() -> str:
    import os
    from pathlib import Path
    tz = os.environ.get("TZ")
    if tz:
        return tz
    try:
        return Path("/etc/timezone").read_text().strip() or "UTC"
    except OSError:
        return "UTC"


def last_slot(at: str, days: tuple[str, ...] | list[str], now: datetime,
              tz: str | None = None) -> datetime:
    """The newest ``at`` on an allowed day not after ``now`` (an aware datetime)."""
    zone = _zone(tz or local_zone())
    local = now.astimezone(zone)
    hh, mm = (int(x) for x in at.split(":"))
    allowed = set(days) or set(DAYS)
    for back in range(8):
        day = local.date() - timedelta(days=back)
        slot = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)
        if slot <= local and DAYS[day.weekday()] in allowed:
            return slot
    raise ValueError("no slot in a week")             # unreachable: some day is allowed


def next_slot(at: str, days, after: datetime, tz: str | None = None) -> datetime:
    zone = _zone(tz or local_zone())
    local = after.astimezone(zone)
    hh, mm = (int(x) for x in at.split(":"))
    allowed = set(days) or set(DAYS)
    for ahead in range(9):
        day = local.date() + timedelta(days=ahead)
        slot = datetime(day.year, day.month, day.day, hh, mm, tzinfo=zone)
        if slot > local and DAYS[day.weekday()] in allowed:
            return slot
    raise ValueError("no slot in a week")


def _last_done(store: Store, kind: str) -> datetime | None:
    marks = ",".join("?" * len(DONE))
    r = store.query_one(f"SELECT MAX(finished_at) AS t FROM runs WHERE kind = ? AND status IN "
                        f"({marks})", (kind, *DONE))
    if not r or not r["t"]:
        return None
    return datetime.fromisoformat(r["t"].replace("Z", "+00:00"))


def at_due(store: Store, kind: str, at: str, days, now: datetime, tz: str | None = None
           ) -> bool:
    slot = last_slot(at, days, now, tz)
    done = _last_done(store, kind)
    return done is None or done < slot


def at_next(store: Store, kind: str, at: str, days, now: datetime, tz: str | None = None
            ) -> datetime:
    if at_due(store, kind, at, days, now, tz):
        return now
    return next_slot(at, days, now, tz)
