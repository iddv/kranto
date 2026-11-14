"""Kept X posts that were deleted on X leave the library.

X's Developer Policy asks stored content to track X's: a post its author deleted, or X took
down, goes within 24 hours of a request. Kranto does three things, cheapest first: X posts are
kept 30 days by default (``retention.by_kind.x``); once every ``x.recheck_days`` this job asks
X about at most ``x.recheck_max`` kept posts (the ones idea cards cite first, then the newest)
with ``GET /2/tweets?ids=``, 100 a request, and removes each one X answers "Not Found" or
withheld for, through the recorded purge with no rollup; and any observation can be removed at
once by hand (``remove_post``: Remove this post, ``python -m kranto sources forget``), which is how
a
deletion request is honoured.

Every post X returns is a read ($0.005, counted in ``api_spend``); the job does nothing while
the X cap holds, without an X connection, or when there is nothing to check."""

from __future__ import annotations

import re
from datetime import datetime

from . import activity, spend
from .retention import remove_observations
from .sources.base import SourceError
from .store import Store, iso, utcnow
from .stored import runs as stored_runs
from .stored.cards import InputIds

API = "https://api.x.com/2/tweets"
PAGE = 100
REMOVED_ON_X = "removed on X: the post was deleted or withheld"
REMOVED_BY_YOU = "removed at the person's request"
_ID = re.compile(r"[0-9]{1,19}")


def candidates(store: Store, limit: int) -> list[tuple[int, str]]:
    """(observation id, post id) of kept X posts, cited by an idea card first, then newest."""
    cited: set[int] = set()
    for r in store.query("SELECT input_ids FROM ideas"):
        cited |= set(InputIds.load(r["input_ids"]).items)
    rows = store.query(
        "SELECT o.id, o.item_id FROM observations o JOIN sources s ON s.id = o.source_id "
        "WHERE s.kind = 'x' ORDER BY o.id DESC")
    rows = [(r["id"], str(r["item_id"])) for r in rows if _ID.fullmatch(str(r["item_id"] or ""))]
    rows.sort(key=lambda r: r[0] not in cited)          # stable: cited first, newest within
    return rows[:max(0, limit)]


def gone(body: dict) -> set[str]:
    """Post ids a lookup reply says are no longer there: not found, or withheld."""
    out = set()
    for e in body.get("errors") or []:
        if not isinstance(e, dict):
            continue
        what = f"{e.get('title') or ''} {e.get('type') or ''}".lower()
        rid = str(e.get("resource_id") or e.get("value") or "")
        if _ID.fullmatch(rid) and ("not found" in what or "not-found" in what):
            out.add(rid)
    for p in body.get("data") or []:
        if isinstance(p, dict) and p.get("withheld"):
            out.add(str(p.get("id")))
    return out


def run_recheck(cfg, store: Store, connections, http, *,
                now: datetime | None = None) -> dict:
    """One re-check; records an ``xrecheck`` run (skipped when there is nothing to do)."""
    now = now or utcnow()
    run_uuid = activity.run_uuid("xrecheck")
    summary: dict = {"checked": 0, "removed": 0}
    status, error = "ok", None
    try:
        picks = candidates(store, cfg.x.recheck_max)
        capped = spend.capped(store, cfg.x.monthly_usd, now=now)
        if not picks:
            # nothing to check is a finished run: due again in x.recheck_days, not every hour
            summary["note"] = "no kept X posts"
        elif capped is not None:
            status, error = "skipped", capped[1]
        elif connections is None:
            status, error = "skipped", "connected accounts are not available here"
        else:
            authed = connections.http_for("x", None, http)
            removed: set[str] = set()
            with spend.attributed(None, run_uuid):
                for i in range(0, len(picks), PAGE):
                    ids = [p for _, p in picks[i:i + PAGE]]
                    body = authed.get_json(API, params={"ids": ",".join(ids),
                                                        "post.fields": "withheld"})
                    summary["checked"] += len(ids)
                    removed |= gone(body if isinstance(body, dict) else {})
            obs = [o for o, p in picks if p in removed]
            if obs:
                remove_observations(store, obs, REMOVED_ON_X, clock=lambda: now)
            summary["removed"] = len(obs)
    except SourceError as exc:
        status = "skipped" if exc.needs_login or exc.transient else "failed"
        error = str(exc)[:300]
    store.insert("runs", {"run_uuid": run_uuid, "kind": "xrecheck", "status": status,
                          "started_at": iso(now), "finished_at": iso(utcnow()),
                          "summary": stored_runs.text_for("xrecheck", summary), "error": error})
    return {"status": status, "error": error, **summary}


def remove_post(store: Store, *, observation_id: int | None = None,
                url: str | None = None) -> int:
    """Remove one kept post now, by its observation or its URL (any source, any kind):
    the person's request, honoured at once. Returns how many observations went."""
    ids: list[int] = []
    if observation_id is not None:
        ids = [r["id"] for r in store.query("SELECT id FROM observations WHERE id = ?",
                                            (int(observation_id),))]
    elif url:
        m = re.search(r"(?:x|twitter)\.com/(?:i/web/|i/|[A-Za-z0-9_]{1,15}/)status/([0-9]{1,19})",
                      url)
        if m:
            ids = [r["id"] for r in store.query(
                "SELECT o.id FROM observations o JOIN sources s ON s.id = o.source_id "
                "WHERE s.kind = 'x' AND o.item_id = ?", (m.group(1),))]
        else:
            ids = [r["id"] for r in store.query(
                "SELECT id FROM observations WHERE source_url = ?", (url.strip(),))]
    if not ids:
        return 0
    return remove_observations(store, ids, REMOVED_BY_YOU).removed.get("observations", 0)
