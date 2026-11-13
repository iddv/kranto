"""What paid APIs other than a model cost: the ``api_spend`` ledger.

X bills each resource a reply returns (``pricing.X_PRICES``). Every reply from a connected X
account passes the provider's ``observe`` hook (``connections/x.py``), which records one row
per request here: the price line, how many resources, their list price, and which source and
run asked (``attributed``, set by ingest around a source's fetch; null for a preview, a Test or
a catalog lookup). A request X refused returns nothing and costs nothing, so it is not counted.

Kranto cannot see X's same-day deduplication, so the sum is an estimate from above; the
Developer Console is the bill. ``x.monthly_usd`` (null: no cap, the owner's rule) defers X
sources until the first of next month once this month's estimate reaches it: paced, never
failing. The watcher's own budget is about model calls and does not count these."""

from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from datetime import datetime, timedelta

from . import pricing
from .store import Store, iso, month_start, utcnow

_WHO: contextvars.ContextVar[tuple[int | None, str | None]] = contextvars.ContextVar(
    "api_spend_who", default=(None, None))


@contextlib.contextmanager
def attributed(source_id: int | None, run_uuid: str | None) -> Iterator[None]:
    """Requests made inside are recorded against this source and run."""
    token = _WHO.set((source_id, run_uuid))
    try:
        yield
    finally:
        _WHO.reset(token)


def record(store: Store, provider: str, kind: str, count: int, *,
           now: datetime | None = None, usd: float | None = None,
           caller: str | None = None) -> float:
    """One request's resources, at list price; returns the USD recorded (0 for none).
    ``usd``: what the request cost when the caller knows it (a search backend's own figure or
    list price); ``caller``: which part of Kranto asked (live search's callers)."""
    count = max(0, int(count))
    if not count:
        return 0.0
    if usd is None:
        usd = pricing.x_cost(kind, count) if provider == "x" else 0.0
    source_id, run_uuid = _WHO.get()
    row = {"provider": provider, "source_id": source_id, "run_uuid": run_uuid, "kind": kind,
           "count": count, "usd": round(float(usd), 6), "created_at": iso(now or utcnow())}
    if caller is not None:
        row["caller"] = caller
    store.insert("api_spend", row)
    return usd


def month(store: Store, provider: str, *, now: datetime | None = None) -> dict:
    """This UTC month's ``{usd, reads, requests}`` for one provider."""
    row = store.query_one(
        "SELECT COALESCE(SUM(usd), 0) AS usd, COALESCE(SUM(count), 0) AS reads, COUNT(*) AS n "
        "FROM api_spend WHERE provider = ? AND created_at >= ?",
        (provider, iso(month_start(now or utcnow()))))
    return {"usd": round(float(row["usd"]), 6), "reads": int(row["reads"]),
            "requests": int(row["n"])}


def by_source(store: Store, provider: str, *, now: datetime | None = None) -> dict[int, dict]:
    """This UTC month's ``{usd, reads}`` per source."""
    rows = store.query(
        "SELECT source_id, SUM(usd) AS usd, SUM(count) AS reads FROM api_spend "
        "WHERE provider = ? AND created_at >= ? AND source_id IS NOT NULL GROUP BY source_id",
        (provider, iso(month_start(now or utcnow()))))
    return {r["source_id"]: {"usd": round(float(r["usd"]), 6), "reads": int(r["reads"])}
            for r in rows}


def next_month(now: datetime) -> datetime:
    start = month_start(now)
    return month_start(start + timedelta(days=32))


def capped(store: Store, cap: float | None, provider: str = "x", *,
           now: datetime | None = None) -> tuple[datetime, str] | None:
    """(when to ask again, why) once this month's estimate has reached ``cap``; None while
    under it or with no cap."""
    if cap is None:
        return None
    now = now or utcnow()
    spent = month(store, provider, now=now)["usd"]
    if spent < cap:
        return None
    return next_month(now), (f"X cap reached: ${spent:.2f} of ${cap:.2f} this month; X sources "
                             "wait until the first of next month (Settings › Spend)")
