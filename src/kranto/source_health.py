"""How each source is doing, and what a source would bring (S1 to S4, P1).

- Every fetch, in an ingest run or by "Fetch now", is a ``source_fetches`` row
  with a state: ``ok``, ``paced`` (a rate limit or another transient refusal),
  ``failing`` (an error that will not clear by itself), ``needs_login`` (the
  connected account is missing or was refused). The error text is scrubbed.
- A source's status is its review status (proposed, retired, ...) or, while it
  is watched, the state of its last fetch.
- Items a day: items consumed in the last seven days (every outcome, so before
  filtering), divided by seven. Kept: observations from the source's items over
  the items the judge read, in the last 30 days.
- A preview is one fetch through the normal adapter, nothing saved: how many
  items, how many in the last 30 days, the median similarity to the topic against
  the prefilter line, and the five newest.
- "Fetch now" is one adapter fetch outside a run: it counts what is new and
  records a fetch row; no item is consumed or judged.
- A mute (UI-v4.md 2.3) is an append-only ``source_mutes`` row, latest wins: muted
  for some days (ingest does not fetch the source until then), or "read less" (ingest
  reads it at half its items per run). A row with neither is back to normal.
- Kept rate: kept over judged in the last 30 days. Yield: observations kept a day over
  the same 30 days.
- Paced is not failing (the owner's ruling, 2026-10-09). A paced fetch records when
  the host may be asked again (``retry_at``, from its Retry-After or the backoff in
  ``sources.pacing``); ingest defers the source until then, and its row says "paced,
  retrying at ...". Only failures that persist count: a source whose fetch failed
  ``fetch.failing_after_runs`` runs in a row (paced runs in between are not counted
  either way) backs off by itself, ``failing_backoff_hours`` doubling with each further
  failure, and is listed under Needs you (``needs_fixing``): fix it or remove it.
- A source feeds every topic it is linked to (``topic_links``; CON's D-3: many to many).
  Its row names them with their kind (user, project) and the topic it was found for
  (``found_for``: the one the scout proposed it for, or the first you added it to); its
  page counts, for each, the topic's watched sources and its kept items this month (SRC).
- Spend: the model calls that judged or screened a source's items this month, the
  same query a topic's facts sum over its sources (``model_spend``). A screening call that
  read items of several sources counts once for each of them, and once for a topic.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from typing import Any, cast

from . import library, rowsafe, sources
from .scrub import scrub
from .sources import catalog
from .sources.reddit import FEEDS_END_NOTE
from .store import Store, iso, month_start, utcnow
from .stored.runs import IngestSummary
from .stored.sources import Validation

RECENT_DAYS = 30
PREVIEW_ITEMS = 5
SIMILARITY_SAMPLE = 30
FETCHES_SHOWN = 7
ERROR_CHARS = 300
REVIEW_STATUSES = ("proposed", "retired", "invalid", "imported")
MUTE_DAYS_MAX = 365


def fetch_state(exc: BaseException | None) -> tuple[str, str | None]:
    """(state, scrubbed error) for a fetch that raised ``exc`` (None: it worked)."""
    if exc is None:
        return "ok", None
    if isinstance(exc, sources.SourceError):
        text = str(exc)
        state = "needs_login" if exc.needs_login else "paced" if exc.transient else "failing"
    else:
        text, state = f"{type(exc).__name__}: {exc}", "failing"
    return state, scrub(text)[:ERROR_CHARS]


def retry_at_of(exc: BaseException | None) -> str | None:
    """When a paced fetch's host may be asked again, as stored (None if not said)."""
    at = getattr(exc, "retry_at", None)
    return iso(at) if isinstance(at, datetime) else None


def record_fetch(store: Store, source_id: int, *, trigger: str, state: str, fetched: int,
                 new: int, error: str | None, run_uuid: str | None = None,
                 now: datetime | None = None, retry_at: str | None = None) -> None:
    store.insert("source_fetches", {
        "source_id": source_id, "run_uuid": run_uuid, "trigger": trigger, "state": state,
        "fetched": fetched, "new": new, "error": error, "created_at": iso(now or utcnow()),
        "retry_at": retry_at if state == "paced" else None})


# -- pacing and persistent failures ------------------------------------------------------

STREAK_FETCHES = 60


def failing_streak(fetches: list[dict[str, Any]]) -> tuple[int, str | None]:
    """(runs in a row whose fetch failed, when the latest of them was) from a source's
    fetches, newest first. A paced fetch says nothing either way and is passed over;
    a manual fetch that failed is not a run; anything else ends the streak."""
    streak, last = 0, None
    for f in fetches:
        if f["state"] == "paced" or (f["state"] == "failing" and f["trigger"] != "run"):
            continue
        if f["state"] != "failing":
            break
        streak += 1
        last = last or f["created_at"]
    return streak, last


def backoff_until(streak: int, last_failed: str | None, cfg: Any) -> str | None:
    """Until when a source failing ``streak`` runs in a row is left alone (``cfg`` is a
    ``config.FetchConfig``); None while it is retried every run."""
    if streak < cfg.failing_after_runs or not last_failed:
        return None
    hours = min(cfg.failing_backoff_max_hours,
                cfg.failing_backoff_hours * 2 ** (streak - cfg.failing_after_runs))
    return iso(datetime.fromisoformat(last_failed.replace("Z", "+00:00"))
               + timedelta(hours=hours))


def fetch_plan(store: Store, cfg: Any, *, now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Per source with a fetch on record: ``failing_runs``, ``backoff_until`` (set while it
    backs off), ``retry_at`` (set while its last fetch was paced) and ``wait_until``, the
    later of the two when it is still ahead (ingest skips the source until then).
    ``cfg`` is a ``config.Config``; without one the defaults apply."""
    from .config import FetchConfig

    fetch_cfg = cfg.fetch if cfg is not None else FetchConfig()
    stamp = iso(now or utcnow())
    out: dict[int, dict[str, Any]] = {}
    for source_id, fetches in _last_fetches(store, STREAK_FETCHES).items():
        streak, last_failed = failing_streak(fetches)
        until = backoff_until(streak, last_failed, fetch_cfg)
        latest = fetches[0]
        retry = latest.get("retry_at") if latest["state"] == "paced" else None
        ahead = [t for t in (until, retry) if t and t > stamp]
        error = next((f["error"] for f in fetches if f["state"] == "failing"), None) \
            if streak else None
        out[source_id] = {"failing_runs": streak, "backoff_until": until, "retry_at": retry,
                          "wait_until": max(ahead) if ahead else None, "failing_error": error,
                          "needs_fixing": streak >= fetch_cfg.failing_after_runs}
    return out


def needs_fixing(store: Store, cfg: Any, *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Watched sources that fail persistently, for Needs you: fix it or remove it."""
    plan = fetch_plan(store, cfg, now=now)
    paused = library.paused_topic_sources(store)
    out = []
    for s in library.list_sources(store, status="approved"):
        p = plan.get(s.id)
        if p and p["needs_fixing"] and s.id not in paused:
            out.append({"id": s.id, "label": s.label, "kind": s.kind,
                        "failing_runs": p["failing_runs"], "backoff_until": p["backoff_until"],
                        "error": p["failing_error"]})
    return out


# -- muting ---------------------------------------------------------------------------


def set_mute(store: Store, source_id: int, *, days: float | None = None,
             read_less: bool = False, note: str | None = None,
             now: datetime | None = None) -> dict[str, Any]:
    """Mute a source for ``days``, or have it read less, or (neither) undo either.
    Returns the source's mute as ``mutes`` gives it."""
    if store.query_one("SELECT 1 FROM sources WHERE id = ?", (source_id,)) is None:
        raise ValueError(f"no source {source_id}")
    if days is not None and not 0 < days <= MUTE_DAYS_MAX:
        raise ValueError(f"mute for 1 to {MUTE_DAYS_MAX} days")
    now = now or utcnow()
    until = iso(now + timedelta(days=days)) if days is not None else None
    store.insert("source_mutes", {"source_id": source_id, "muted_until": until,
                                  "read_less": int(bool(read_less)), "note": note,
                                  "created_at": iso(now)})
    return mutes(store, now=now).get(source_id) or {"muted_until": None, "read_less": False}


def mutes(store: Store, *, now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """The sources muted or reading less now: ``{source_id: {muted_until, read_less}}``.
    An expired mute is not listed."""
    stamp = iso(now or utcnow())
    rows = store.query(
        "SELECT m.source_id, m.muted_until, m.read_less, m.created_at FROM source_mutes m "
        "WHERE m.id = (SELECT MAX(id) FROM source_mutes l WHERE l.source_id = m.source_id)")
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        muted = r["muted_until"] if r["muted_until"] and r["muted_until"] > stamp else None
        if muted or r["read_less"]:
            out[r["source_id"]] = {"muted_until": muted, "read_less": bool(r["read_less"]),
                                   "since": r["created_at"]}
    return out


# -- reading --------------------------------------------------------------------------


def _group(s: library.SourceRow, linked: list[int]) -> str:
    role = s.validation.role if s.validation else None
    if role == "wildcard" and s.status in ("proposed", "approved"):
        return "wildcard"
    if s.status == "approved" and not linked:
        return "broad"
    return s.status or "unknown"


def _status(s: library.SourceRow, last: dict[str, Any] | None,
            plan: dict[str, Any] | None = None) -> tuple[str, str]:
    """(status word key, one line of detail) for a source row."""
    v = s.validation or Validation.empty()
    if s.status == "proposed":
        if v.status == "valid":
            # A source tested without a topic has no similarity (None), not 0.
            sim = v.median_similarity
            detail = (f"sim {sim:.2f} · " if sim is not None else "") \
                + f"{v.items} items, {v.recent or 0} in 30 days"
        elif v.checked and not v.status and not v.error:
            # Added by hand or from the catalog (``checked``, no test status), then set back
            # to proposed: it was never test-fetched, so nothing "did not finish".
            how = "added from the catalog" if v.checked == "preview" else "added by hand"
            detail = f"{how}; not test-fetched"
        else:
            detail = v.error or "test fetch did not finish"
        return "proposed", ("wildcard · " if v.role == "wildcard" else "") + detail
    if s.status in ("retired", "invalid", "imported"):
        return s.status, (v.error or "") if s.status == "invalid" else ""
    if last is None:
        return "new", "not fetched yet: the next ingest run reads it"
    if last["state"] == "ok":
        return "ok", f"{last['fetched']} fetched, {last['new']} new"
    plan = plan or {}
    if last["state"] == "paced":
        # Not a failure: the host asked for a pause, and the source is read again then.
        at = plan.get("retry_at")
        return "paced", "retrying at " + (f"{at[:16].replace('T', ' ')} UTC" if at
                                          else "the next run")
    runs = plan.get("failing_runs") or 0
    if last["state"] == "failing" and runs > 1:
        until = plan.get("backoff_until")
        lead = f"failing {runs} runs in a row" + (
            f"; left alone until {until[:16].replace('T', ' ')} UTC" if until else "")
        return "failing", f"{lead}: {last.get('error') or ''}"
    return last["state"], last.get("error") or ""


def _last_fetches(store: Store, limit: int) -> dict[int, list[dict[str, Any]]]:
    rows = store.query(
        "SELECT * FROM (SELECT f.*, ROW_NUMBER() OVER (PARTITION BY source_id "
        "ORDER BY id DESC) AS n FROM source_fetches f) WHERE n <= ? ORDER BY source_id, id DESC",
        (limit,))
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        d = dict(r)
        d.pop("n", None)
        out.setdefault(r["source_id"], []).append(d)
    return out


def _from_runs(store: Store) -> dict[int, dict[str, Any]]:
    """The latest fetch per source from runs' summaries, for sources with no
    ``source_fetches`` row yet (fetched before migration 17)."""
    out: dict[int, dict[str, Any]] = {}
    for run in store.query("SELECT run_uuid, finished_at, summary FROM runs WHERE kind = "
                           "'ingest' AND status != 'skipped' ORDER BY finished_at DESC LIMIT 7"):
        for rep in IngestSummary.load(run["summary"]).sources:
            sid = rep.source_id
            if sid is None or sid in out or rep.not_reached or rep.muted:
                continue
            error = rep.fetch_error
            out[sid] = {"source_id": sid, "run_uuid": run["run_uuid"], "trigger": "run",
                        "state": "failing" if error else "ok", "fetched": rep.fetched,
                        "new": rep.new, "error": scrub(error)[:ERROR_CHARS]
                        if error else None, "created_at": run["finished_at"]}
    return out


GRADE_DAYS = 90
def source_grades(store: Store, *, now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Per source, the owner's latest grade of each of its observations over the trailing
    ``GRADE_DAYS``: ``{useful, not_useful, wrong, missed, reasons: {chip: n}}`` (a cleared grade
    counts for nothing; a purged observation's grade no longer counts), L7. Grows
    with the grades, not with the library."""
    since = iso((now or utcnow()) - timedelta(days=GRADE_DAYS))
    latest: dict[str, tuple[int, str, str]] = {}
    for r in store.query(
            "SELECT f.target_id, f.value, f.reasons, o.source_id FROM feedback f "
            "JOIN observations o ON o.id = CAST(f.target_id AS INTEGER) "
            "WHERE f.target = 'observation' AND f.kind = 'grade' AND f.created_at >= ? "
            "ORDER BY f.id", (since,)):
        latest[r["target_id"]] = (int(r["source_id"]), r["value"], r["reasons"])
    out: dict[int, dict[str, Any]] = {}
    for source_id, value, reasons in latest.values():
        if value == "skip":
            continue
        g = out.setdefault(source_id, {"useful": 0, "not_useful": 0, "wrong": 0, "missed": 0,
                                       "reasons": {}})
        if value in g:
            g[value] += 1
        for chip in json.loads(reasons or "[]"):
            g["reasons"][chip] = g["reasons"].get(chip, 0) + 1
    return out


def topic_refs(store: Store) -> dict[int, dict[str, Any]]:
    """Every topic a source can feed, paused and archived ones too: ``{id: {id, name, kind}}``
    (the current name, ``topics_now``)."""
    return {t.id: {"id": t.id, "name": t.name, "kind": t.kind}
            for t, _, _ in library.topics_with_status(store, archived=True)}


def topic_ref(refs: dict[int, dict[str, Any]], topic_id: int) -> dict[str, Any]:
    """A copy of one topic's ref (callers may rename it), or a stand-in for one gone."""
    return dict(refs.get(topic_id) or {"id": topic_id, "name": f"topic {topic_id}",
                                       "kind": "user"})


def source_links(store: Store) -> dict[int, list[int]]:
    """Each source's topics, in the order it was linked to them (``topic_links``)."""
    order = {(r["source_id"], r["topic_id"]): n for n, r in enumerate(store.query(
        "SELECT topic_id, source_id FROM topic_sources ORDER BY rowid"))}
    links: dict[int, list[int]] = {}
    for r in store.query("SELECT topic_id, source_id FROM topic_links"):
        links.setdefault(r["source_id"], []).append(r["topic_id"])
    for sid, ts in links.items():
        def rank(t: int, s: int = sid) -> tuple[int, int]:
            return (order.get((s, t), len(order)), t)
        ts.sort(key=rank)
    return links


def model_spend(store: Store, source_ids: list[int], *,
                now: datetime | None = None) -> tuple[float, dict[str, Any] | None]:
    """This month's model calls that judged or screened the items of ``source_ids``: (USD,
    ``{"in", "out"}`` tokens, or None when no call has counts). A topic's facts ask it for
    the topic's sources, a source's page for the one."""
    if not source_ids:
        return 0.0, None
    marks = ",".join("?" * len(source_ids))
    row = store.query_one(
        f"""SELECT COALESCE(SUM(c.cost_usd), 0) AS usd, COUNT(c.prompt_tokens) AS n,
                   COALESCE(SUM(c.prompt_tokens), 0) AS i,
                   COALESCE(SUM(c.completion_tokens), 0) AS o FROM llm_calls c
            WHERE c.created_at >= ? AND c.id IN (
                SELECT llm_call_id FROM items_seen WHERE source_id IN ({marks})
                UNION SELECT screen_call_id FROM items_seen WHERE source_id IN ({marks}))""",
        (iso(month_start(now or utcnow())), *source_ids, *source_ids))
    assert row is not None                     # an aggregate always answers one row
    tokens ={"in": int(row["i"]), "out": int(row["o"])} if row["n"] else None
    return round(float(row["usd"]), 6), tokens


def kept_this_month(store: Store, *, now: datetime | None = None) -> dict[int, int]:
    """Items kept (they became observations) this month, by source."""
    return {r["source_id"]: int(r["k"] or 0) for r in store.query(
        "SELECT source_id, SUM(outcome = 'contributed') AS k FROM items_seen "
        "WHERE created_at >= ? GROUP BY source_id", (iso(month_start(now or utcnow())),))}


def list_sources(store: Store, cfg: Any = None, *,
                 now: datetime | None = None) -> list[dict[str, Any]]:
    """Every source with its status, group, topics, health and site label, and what the owner
    graded of its observations (``grades``, ``suggest``)."""
    from .retention import retention_days

    now = now or utcnow()
    srcs = library.list_sources(store)
    links = source_links(store)
    refs = topic_refs(store)
    topics = {i: r["name"] for i, r in refs.items()}
    week = iso(now - timedelta(days=7))
    month = iso(now - timedelta(days=RECENT_DAYS))
    seen = {r["source_id"]: r["n"] for r in store.query(
        "SELECT source_id, COUNT(*) AS n FROM items_seen WHERE created_at >= ? "
        "GROUP BY source_id", (week,))}
    kept = {r["source_id"]: (r["kept"], r["judged"]) for r in store.query(
        "SELECT source_id, SUM(outcome = 'contributed') AS kept, "
        f"SUM(outcome IN ({','.join('?' * len(library.JUDGED_OUTCOMES))})) AS judged "
        "FROM items_seen WHERE created_at >= ? GROUP BY source_id",
        (*library.JUDGED_OUTCOMES, month))}
    fetches = _last_fetches(store, 1)
    # Items a day counts what ingest runs consumed; before a source's first run it is unknown.
    ran = {r["source_id"] for r in store.query(
        "SELECT DISTINCT source_id FROM source_fetches WHERE trigger = 'run'")}
    ran |= set(seen)
    fallback = _from_runs(store) if len(fetches) < len(srcs) else {}
    days = retention_days(store, cfg.retention) if cfg is not None else {}
    muted = mutes(store, now=now)
    graded = source_grades(store, now=now)
    from . import source_rule

    removal = source_rule.state(store, getattr(cfg, "grading", None), now=now)
    plans = fetch_plan(store, cfg, now=now)
    from . import spend
    from .config import XConfig
    from .sources.x import run_cost

    xcfg = cfg.x if cfg is not None else XConfig()
    paid = spend.by_source(store, "x", now=now) if any(s.kind == "x" for s in srcs) else {}
    out: list[dict[str, Any]] = []
    for s in srcs:
        # one source that cannot be read is listed as such, never the whole list (RCA A3)
        with rowsafe.row(out, "source", s.id, label=s.label, kind=s.kind, review=s.status):
            got = fetches.get(s.id)
            last = got[0] if got else fallback.get(s.id)
            plan = plans.get(s.id) or {}
            status, detail = _status(s, last, plan)
            v = s.validation or Validation.empty()
            provider = catalog.provider_of(s.kind, s.params)
            preset = v.preset
            k, j = kept.get(s.id, (0, 0))
            out.append({
                "id": s.id, "kind": s.kind, "label": s.label, "origin": s.origin,
                "review": s.status, "group": _group(s, links.get(s.id, [])),
                "status": status, "detail": detail,
                "site": provider, "site_name": catalog.PROVIDERS.get(provider, provider),
                "preset": preset if preset in catalog.PRESETS else None,
                "fields": v.fields if preset in catalog.PRESETS else None,
                "topics": [topic_ref(refs, t) for t in links.get(s.id, [])],
                "proposed_for": topics.get(v.topic_id) if v.role == "wildcard"
                and v.topic_id is not None else None,
                # the topic the scout proposed it for, else the first you added it to (SRC)
                "found_for": topic_ref(refs, v.topic_id) if v.topic_id in refs
                else topic_ref(refs, links[s.id][0]) if links.get(s.id) else None,
                "why": v.why, "replaces": v.replaces,
                # the keys that are set (a Parallax import's: none)
                "validation": v.api() if s.validation is not None else {},
                "items_7d": seen.get(s.id, 0),
                "items_per_day": round(seen.get(s.id, 0) / 7, 1)
                if s.id in ran or s.id in fallback else None,
                "kept_30d": int(k or 0), "judged_30d": int(j or 0),
                "kept_rate": round(int(k or 0) / int(j), 3) if j else None,
                "yield_per_day": round(int(k or 0) / RECENT_DAYS, 2),
                "mute": muted.get(s.id),
                # what the owner graded of it (90 days) and the verb that follows (CON L7)
                "grades": graded.get(s.id),
                # the source rule: recommended for removal, kept, or None
                "removal": removal.get(s.id),
                "last_fetch": last["created_at"] if last else None,
                "last_error": last.get("error") if last and last["state"] != "ok" else None,
                # Pacing (sources.pacing): when a paced source is read again, how many runs in
                # a row it failed, until when it backs off, and whether it needs you.
                "retry_at": plan.get("retry_at") if status == "paced" else None,
                "failing_runs": plan.get("failing_runs") or 0,
                "backoff_until": plan.get("backoff_until"),
                "needs_fixing": bool(plan.get("needs_fixing")) and s.status == "approved",
                "connection": sources.needs(s.kind, s.params) or sources.uses(s.kind),
                "retention_days": days.get(s.id),
                "note": FEEDS_END_NOTE if s.kind == "reddit" else None,
                # a paid API's reads (X): this month's, and one fetch's at most, at list price
                "spend": ({**paid.get(s.id, {"usd": 0.0, "reads": 0}),
                           "run_usd": round(run_cost(s.params, xcfg), 4)}
                          if s.kind == "x" else None),
            })
    return out


def describe(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """How a source is read: the request, its pacing, its connection, its terms."""
    from .sources import arxiv, bluesky, hackernews

    if kind == "rss":
        return {"request": params.get("url"), "pacing": "one request per run",
                "terms": "the site's own terms"}
    if kind == "hackernews":
        what = f"search {params['query']!r}" if params.get("query") else \
            f"the {params.get('feed')} feed"
        return {"request": f"{hackernews.API}/search_by_date ({what})",
                "pacing": "one request per run; Algolia allows 10,000 an hour",
                "terms": "Hacker News API (Algolia)"}
    if kind == "reddit":
        return {"request": f"https://www.reddit.com/r/{params.get('subreddit')}/new/.rss",
                "pacing": "one request a minute across every Reddit source, process-wide",
                "terms": f"Reddit Responsible Builder Policy; {FEEDS_END_NOTE} "
                         "See RESPONSIBLE_USE.md"}
    if kind == "arxiv":
        q = arxiv.search_query(params.get("query") or "")
        return {"request": f"{arxiv.API}?search_query={q}",
                "pacing": "one request every three seconds, process-wide",
                "terms": "arXiv API terms of use; thank you to arXiv for use of its open "
                         "access interoperability"}
    if kind == "bluesky" and params.get("what"):
        what = "getTimeline" if params["what"] == "home" else \
            f"searchPosts (q={params.get('query')!r})"
        return {"request": f"your PDS: /xrpc/app.bsky.feed.{what}, proxied to the AppView",
                "pacing": "one request per run; Bluesky allows 3,000 in five minutes",
                "terms": "Bluesky's terms; read-only rpc: scopes (or an app password)"}
    if kind == "bluesky":
        what = "getFeed" if params.get("feed_uri") else "getListFeed"
        return {"request": f"{bluesky.API}/app.bsky.feed.{what}",
                "pacing": "one request per run", "terms": "Bluesky's public API"}
    if kind == "github":
        return {"request": "https://api.github.com/users/<you>/starred, then "
                           "/repos/<repo>/releases for the 30 most recently pushed",
                "pacing": "up to 32 requests per run; a token allows 5,000 an hour",
                "terms": "GitHub's terms; a read-only token"}
    if kind == "youtube":
        return {"request": "https://www.googleapis.com/youtube/v3/subscriptions, then "
                           "playlistItems for up to 100 channels",
                "pacing": "about 100 quota units per run, of 10,000 a day",
                "terms": "YouTube API Services terms; API data kept at most 30 days"}
    if kind == "producthunt":
        topic = params.get("topic")
        return {"request": "https://api.producthunt.com/v2/api/graphql (posts"
                           + (f", topic {topic}" if topic else "") + ")",
                "pacing": "one request per run",
                "terms": "Product Hunt API terms: non-commercial use"}
    if kind == "stackexchange":
        return {"request": f"https://api.stackexchange.com/2.3/search/advanced "
                           f"(site {params.get('site')}, q={params.get('query')!r})",
                "pacing": "one request per run; 300 a day per address, 10,000 with your key; "
                          "the API's backoff is honoured",
                "terms": "CC BY-SA: observations link to the question"}
    if kind == "x":
        from .config import XConfig
        from .sources.x import XSource, cadence_hours, limit_for, run_cost

        x_what = params.get("what")
        try:
            # the request alone: built without an HTTP, nothing is sent
            url, query = XSource(cast(Any, None), **params).request(
                None, limit_for(params, XConfig()))
        except (ValueError, TypeError, sources.SourceError):
            # TypeError: stored params with a key this XSource no longer takes.
            path = {"home": "timelines/reverse_chronological", "bookmarks": "bookmarks",
                    "likes": "liked_tweets"}.get(str(x_what), "")
            url = f"https://api.x.com/2/users/<you>/{path}"
            query = {"max_results": limit_for(params, XConfig()),
                     **({"exclude": "replies"} if x_what == "home" else {})}
        every = cadence_hours(params, XConfig())
        return {"request": url + " ("
                + ", ".join(f"{k}={v}" for k, v in query.items()
                            if k in ("max_results", "query", "exclude")) + ")",
                "pacing": (f"one request {'a day' if every >= 24 else 'per run'}, "
                           f"{limit_for(params, XConfig())} posts at most and only the new "
                           "ones where X allows since_id; X allows 900 a window"),
                "terms": "X's Developer Agreement and Policy; read-only scopes; posts kept 30 "
                         "days by default, authors never kept; your reads are billed by X to "
                         f"your developer account: about ${run_cost(params, XConfig()):.2f} a "
                         "fetch at X's list price"}
    if kind == "xai_search":
        who = f", only {params['handles']}" if params.get("handles") else ""
        return {"request": f"https://api.x.ai/v1/responses (grok-4.7 with x_search: "
                           f"{params.get('query')!r}{who})",
                "pacing": "one call a day (x.search_every_hours)",
                "terms": "xAI's terms; Grok's digest in its own words, never the posts' text; "
                         "$5 per 1,000 posts the tool reads plus tokens, in the watcher's "
                         "budget"}
    if kind == "websearch":
        return {"request": f"one live search a run, restricted to {params.get('site')} "
                           "(the search.provider backend)",
                "pacing": "one search per run, results from the last four weeks",
                "terms": "the search backend's terms; titles, links, dates and snippets only; "
                         "free in Exa's free mode, $0.005 to $0.008 a run with a key, counted "
                         "on Spend"}
    if kind == "mastodon":
        path = "timelines/home" if params.get("what") == "home" else \
            f"timelines/list/{params.get('list_id')}"
        return {"request": f"https://{params.get('instance')}/api/v1/{path}",
                "pacing": "one request per run; the instance allows 300 in five minutes",
                "terms": "the instance's terms; read-only scopes"}
    return {"request": json.dumps(params),  # stored-shape: the params, shown
            "pacing": "one request per run", "terms": ""}


def source_detail(store: Store, cfg: Any, source_id: int) -> dict[str, Any] | None:
    row = next((s for s in list_sources(store, cfg) if s["id"] == source_id), None)
    if row is None:
        return None
    if rowsafe.is_unreadable(row):        # its own page cannot be drawn: the error page, by its id
        raise rowsafe.Unreadable(row)
    src = next(s for s in library.list_sources(store) if s.id == source_id)
    fetches = _last_fetches(store, FETCHES_SHOWN).get(source_id, [])
    created = store.query_one("SELECT created_at FROM sources WHERE id = ?", (source_id,))
    from .retention import source_overrides

    override = source_overrides(store).get(source_id)
    # each topic it feeds: the topic's watched sources and kept items this month, beside
    # this source's own ("19 of its 34 kept items this month")
    kept = kept_this_month(store)
    links = source_links(store)
    status = {s.id: s.status for s in library.list_sources(store)}
    topic_status = {t.id: st for t, st, _ in library.topics_with_status(store, archived=True)}
    facts = []
    for t in row["topics"]:
        watched = [sid for sid, ts in links.items() if t["id"] in ts
                   and status.get(sid) == "approved"]
        facts.append({**t, "status": topic_status.get(t["id"], "active"),
                      "sources": len(watched),
                      "kept_month": sum(kept.get(sid, 0) for sid in watched)})
    usd, tokens = model_spend(store, [source_id])
    return {**row, "params": src.params, "fetches": fetches,
            "how": describe(src.kind, src.params),
            "added_at": created["created_at"] if created else None,
            "retention_override": override is not None,
            "retention_kind_days": cfg.retention.days_for_kind(src.kind) if cfg else None,
            "topic_facts": facts, "kept_month": kept.get(source_id, 0),
            "spend_month": {"usd": usd, "tokens": tokens}}


# -- preview and fetch now ------------------------------------------------------------


def _counts(items: list[sources.Item], topic: library.Topic | None, embedder: Any,
            now: datetime) -> dict[str, Any]:
    dated = [it.published_at for it in items if it.published_at]
    recent = sum(1 for d in dated if d >= now - timedelta(days=RECENT_DAYS))
    similarity = None
    if topic is not None and items:
        sample = items[:SIMILARITY_SAMPLE]
        sims = embedder.embed_documents([it.text_for_prefilter() for it in sample]) \
            @ topic.embedding
        similarity = round(float(statistics.median(sims.tolist())), 4)
    newest = sorted(items, key=lambda it: it.published_at.timestamp() if it.published_at
                    else 0.0, reverse=True)[:PREVIEW_ITEMS]
    return {"items": len(items), "recent": recent, "median_similarity": similarity,
            # Some feeds (a Mastodon hashtag's) give items no title: show the text's start.
            "newest": [{"title": it.title or it.excerpt()[:140] or "(no text)",
                        "url": sources.safe_url(it.url), "link": sources.safe_url(it.link),
                        "published_at": iso(it.published_at) if it.published_at else None}
                       for it in newest]}


def preview(rt: Any, preset_key: str, fields: dict[str, Any], topic_id: int | None,
            *, now: datetime | None = None) -> dict[str, Any]:
    """One fetch for a preset, nothing saved. Raises ValueError or SourceError."""
    preset = catalog.get(preset_key)
    http = _http_for_preset(rt, preset, fields)
    resolved = catalog.resolve(preset_key, fields, http)
    adapter = sources.build(resolved.kind, resolved.params, rt.http,
                            connections=rt.connections, llm=getattr(rt, "llm", None))
    items = adapter.fetch()
    topic = next((t for t in library.active_topics(rt.store) if t.id == topic_id), None) \
        if topic_id else None
    existing = rt.store.query_one(
        "SELECT id FROM sources WHERE kind = ? AND params = ?",
        (resolved.kind, sources.canonical_params(resolved.kind, resolved.params)))
    return {"preset": preset.key, "kind": resolved.kind, "params": resolved.params,
            "label": resolved.label, "existing_id": existing["id"] if existing else None,
            "prefilter": rt.cfg.ingest.prefilter_min_similarity,
            "retention_days": preset.retention_days,
            **_counts(items, topic, rt.embedder, now or utcnow())}


def _http_for_preset(rt: Any, preset: catalog.Preset, fields: dict[str, Any]) -> Any:
    """The HTTP a preset's fields are resolved with: the account's, for a login preset
    (a Mastodon list's name is read with it). X through Grok reads with a key, not an
    account: nothing to resolve."""
    if not preset.needs or preset.needs == "xai":
        return rt.http
    instance = None
    if "instance" in {f.key for f in preset.fields}:
        from .sources.mastodon import clean_instance

        instance = clean_instance(str(fields.get("instance") or ""))
    if rt.connections is None:
        raise sources.SourceError("needs login: connections are not available here",
                                  needs_login=True)
    return rt.connections.http_for(preset.needs, instance, rt.http)


def add_from_preset(rt: Any, preset_key: str, fields: dict[str, Any], topic_id: int | None, *,
                    items: int | None = None) -> tuple[int, str]:
    """Create an approved source from a preset: (source id, label). No fetch beyond
    what resolving the fields needs; the first real fetch is the next ingest run."""
    from .retention import set_source_retention

    preset = catalog.get(preset_key)
    http = _http_for_preset(rt, preset, fields)
    resolved = catalog.resolve(preset_key, fields, http)
    sources.build(resolved.kind, resolved.params, rt.http, connections=rt.connections)
    # what the preview read (``items``), the preset and its fields: no test fetch here
    record = Validation(items=items or 0, preset=preset.key,
                        fields={k: str(v) for k, v in fields.items()}, checked="preview")
    existing = rt.store.query_one(
        "SELECT id FROM sources WHERE kind = ? AND params = ?",
        (resolved.kind, sources.canonical_params(resolved.kind, resolved.params)))
    source_id = library.add_source(rt.store, resolved.kind, resolved.params,
                                   label=resolved.label, validation=record)
    if topic_id and topic_id in {t.id for t in library.active_topics(rt.store)}:
        library.link_topic_source(rt.store, topic_id, source_id)
    if preset.retention_days is not None and existing is None:
        set_source_retention(rt.store, source_id, preset.retention_days,
                             f"{catalog.PROVIDERS[preset.provider]}: kept "
                             f"{preset.retention_days:g} days")
    return source_id, resolved.label


def fetch_now(rt: Any, source_id: int) -> dict[str, Any]:
    """One fetch of a source outside a run; nothing is consumed or judged."""
    src = next((s for s in library.list_sources(rt.store) if s.id == source_id), None)
    if src is None:
        raise ValueError(f"no source {source_id}")
    if src.status == "imported":
        raise ValueError("an imported source is a label, never fetched")
    try:
        adapter = sources.build(src.kind, src.params, rt.http, connections=rt.connections,
                                llm=getattr(rt, "llm", None))
        items = adapter.fetch()
    except Exception as exc:  # recorded like a run's fetch error
        state, error = fetch_state(exc)
        retry_at = retry_at_of(exc)
        record_fetch(rt.store, source_id, trigger="manual", state=state, fetched=0, new=0,
                     error=error, retry_at=retry_at)
        return {"state": state, "fetched": 0, "new": 0, "error": error,
                "retry_at": retry_at if state == "paced" else None}
    seen = library.seen_item_ids(rt.store, source_id)
    new = len({it.id for it in items} - seen)
    record_fetch(rt.store, source_id, trigger="manual", state="ok", fetched=len(items), new=new,
                 error=None)
    return {"state": "ok", "fetched": len(items), "new": new, "error": None}
