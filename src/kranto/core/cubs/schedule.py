"""When a cub's job is due (the schema's ``jobs[].at`` and ``days``).

A job with ``at: "08:00"`` (and ``days: [mon]``) is due once at or after that local time on
each listed day (every day when ``days`` is empty): its slot is the newest such time not after
now, and it is due while no run since that slot ended ``ok``, ``degraded`` or ``skipped`` (a
scheduled run with nothing to do is no row: the store's note of it counts, until a restart). A
failed run leaves it due, under the scheduler's back-off (read from the stored runs, so a
restart keeps it); a slot missed while Kranto was down is
run once when Kranto is back (a Monday issue on Tuesday, not a lost week). A job without ``at``
is due by its interval, as every job is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ...store import Store

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DONE = ("ok", "degraded", "skipped")
RETRY_FIRST = timedelta(minutes=5)      # the scheduler's FIRST_BACKOFF
RETRY_CAP = timedelta(days=1)


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
    """When a run of ``kind`` last ended done: its newest such row, or the scheduled run that
    had nothing to do, which the store keeps in memory instead of a row (``Store.skipped_at``).
    Reading the rows alone left a job that found nothing to do due at every tick: the short
    posts' daily job ran once a minute."""
    marks = ",".join("?" * len(DONE))
    r = store.query_one(f"SELECT MAX(finished_at) AS t FROM runs WHERE kind = ? AND status IN "
                        f"({marks})", (kind, *DONE))
    row = datetime.fromisoformat(r["t"].replace("Z", "+00:00")) if r and r["t"] else None
    noted = store.skipped_at(kind) if hasattr(store, "skipped_at") else None
    return max((t for t in (row, noted) if t is not None), default=None)


def _retry_at(store: Store, kind: str, slot: datetime) -> datetime | None:
    """When a job whose runs since ``slot`` failed may be tried again: the scheduler's back-off
    (5 minutes, doubled after each failure, at most a day) read from the stored runs, so a
    restart does not try it again at once (it did: one model call per start). A run cut short
    by Kranto stopping does not count: an update must not cost the week's issue."""
    rows = store.query(
        "SELECT finished_at, error FROM runs WHERE kind = ? AND status = 'failed' "
        "AND finished_at >= ?", (kind, slot.astimezone(ZoneInfo("UTC")).strftime(
            "%Y-%m-%dT%H:%M:%SZ")))
    failed = [datetime.fromisoformat(r["finished_at"].replace("Z", "+00:00")) for r in rows
              if not str(r["error"] or "").startswith("failed: interrupted")]
    if not failed:
        return None
    return max(failed) + min(RETRY_FIRST * 2 ** (len(failed) - 1), RETRY_CAP)


def at_due(store: Store, kind: str, at: str, days, now: datetime, tz: str | None = None
           ) -> bool:
    slot = last_slot(at, days, now, tz)
    done = _last_done(store, kind)
    if done is not None and done >= slot:
        return False
    retry = _retry_at(store, kind, slot)
    return retry is None or now >= retry


def at_next(store: Store, kind: str, at: str, days, now: datetime, tz: str | None = None
            ) -> datetime:
    if at_due(store, kind, at, days, now, tz):
        return now
    slot = last_slot(at, days, now, tz)
    done = _last_done(store, kind)
    retry = _retry_at(store, kind, slot) if done is None or done < slot else None
    return retry if retry is not None else next_slot(at, days, now, tz)
