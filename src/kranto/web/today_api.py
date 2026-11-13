"""Today, Kranto UI's inbox (UI-v4.md 2.2), the "last visit" marker, and spend by topic.

| Method and path         | Does                                                          |
|-------------------------|---------------------------------------------------------------|
| GET  /api/today         | ``since``: per topic, kept since then (count, top 3 by signal); |
|                         | rising themes; proposed sources; messages; the ingest line    |
|                         | (``topics``: the user's; ``project_topics``: the page's, apart) |
| GET  /api/seen          | the marker, ``seen_at``, and ``since``: where "new" starts     |
| POST /api/seen          | ``{at}``: move the marker (default: now); answers the previous |
| POST /api/home/visit    | the home was seen: moves ``home.visit`` (``core.home``)       |
| GET  /api/spend/topics  | this month's spend by topic, the broad lane, other purposes   |
|                         | and compacted calls; the parts add up to the month's spend    |

The marker is one row in ``settings`` (``seen_at``). Reading a page never moves it: only
Mark all seen does, so a glance at the phone does not hide anything from the laptop. Until
it is first set, "new" means the last 24 hours. ``since`` on these endpoints and on
``/api/observations`` is ``last`` (the marker; the default) or an ISO time.

Every number is a query over the library; no model call is made.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import grades, health, library, notify, rowsafe, source_health, source_rule
from ..llm import watch_pause
from ..store import Store, iso, month_start, utcnow
from ..stored.runs import IngestSummary

SEEN_KEY = "seen_at"
DEFAULT_WINDOW = timedelta(hours=24)
TOP_SHOWN = 3
RISING_SHOWN = 3
MESSAGES_SHOWN = 20
# the model calls of the features that left Kranto, said as one line of Spend's "other"
RETIRED_PURPOSES = ("invest_", "radar_", "deep_dive")
RETIRED_SPEND = "features that left Kranto"


def evaluation_spend(other: dict) -> tuple[dict, dict]:
    """Spend's own line for evaluation: every ``eval_*`` purpose (``kranto eval``
    asking the models again) as one ``{"usd", "calls"}``, and the other purposes without them.
    Eval calls count toward the month like every call; they are capped by the run's budget."""
    ev = {p: v for p, v in other.items() if p.startswith("eval_")}
    return ({"usd": round(sum(v[0] for v in ev.values()), 6),
             "calls": sum(v[1] for v in ev.values())},
            {p: v for p, v in other.items() if p not in ev})


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def parse_time(value: str) -> str:
    """An ISO time as the library writes it (UTC, seconds, ``Z``); ValueError if it is not one."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=UTC))


def seen_at(store: Store) -> str | None:
    return store.get_setting(SEEN_KEY)


def resolve_since(store: Store, value: str | None, now: datetime | None = None
                  ) -> tuple[str, str | None]:
    """``(since, seen_at)``: the time "new" counts from for ``value`` (``last``, empty or an
    ISO time), and the marker. Raises ValueError for anything else."""
    seen = seen_at(store)
    if not value or value == "last":
        return seen or iso((now or utcnow()) - DEFAULT_WINDOW), seen
    return parse_time(value), seen


def mark_seen(store: Store, at: str | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    previous = seen_at(store)
    stamp = parse_time(at) if at else iso(now)
    if stamp > iso(now):
        raise ValueError("the marker cannot be in the future")
    store.set_setting(SEEN_KEY, stamp, now=now)
    return {"seen_at": stamp, "previous": previous}


class TodayAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def _obs(self, rows) -> list[dict]:
        from .app import _row

        out = rowsafe.each(rows, lambda r: self.app._public(_row(r)), "observation",
                           ident=lambda r: r["id"], keep=lambda r: {"title": r["title"]})
        latest = grades.latest(self.rt.store, "observation", [o["id"] for o in out])
        for o in out:
            g = latest.get(str(o["id"]))
            o["grade"] = {"grade": g["grade"], "created_at": g["created_at"]} if g else None
        return out

    def _rising(self, topics: list) -> list[dict]:
        """Up to three rising themes across the active topics, each with the topic most of
        its stories come from."""
        from .app import _moving_key
        from .topics_api import THEME_MIN_SHARE, theme_share

        _, clusters = self.app.topics_api._clusters()
        out = []
        for c in sorted((c for c in clusters if c["rising"]), key=_moving_key):
            with rowsafe.row(out, "theme", c.get("cluster"), label=c.get("label"),
                             lineage_id=c.get("lineage_id")):
                best = max(((theme_share(c, self.app.topics_api.names(t)), t) for t in topics),
                           default=(0.0, None), key=lambda x: x[0])
                if best[1] is None or best[0] < THEME_MIN_SHARE:
                    continue
                out.append({k: c[k] for k in ("cluster", "lineage_id", "label", "name", "size",
                                              "stories", "keywords", "cross_source", "rising",
                                              "movement", "trajectory", "source_mix")
                            if k in c}
                           | {"topic": {"id": best[1].id, "name": best[1].name},
                              "topic_share": round(best[0], 4)})
            if len(out) == RISING_SHOWN:
                break
        return out

    def _ingest_line(self, now: datetime) -> dict:
        store = self.rt.store
        last = store.query_one("SELECT * FROM runs WHERE kind = 'ingest' AND status != "
                               "'skipped' ORDER BY finished_at DESC LIMIT 1")
        summary = IngestSummary.load(last["summary"] if last else None)
        day = iso(now - timedelta(hours=24))
        judge = store.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(status = 'error'), 0) AS errors FROM llm_calls "
            "WHERE purpose = 'judge' AND created_at >= ?", (day,))
        return {
            "last": {"status": last["status"], "finished_at": last["finished_at"],
                     "contributed": summary.contributed, "error": last["error"]}
            if last else None,
            "judge_calls_24h": int(judge["n"]), "judge_errors_24h": int(judge["errors"]),
            "observations": store.query_one(
                "SELECT COUNT(*) AS n FROM observations o WHERE NOT EXISTS "
                "(SELECT 1 FROM observations n WHERE n.supersedes = o.id)")["n"],
            "sources": len(library.list_sources(store, status="approved")),
            "topics": len(library.active_topics(store)),
            "paused": store.pause_reason(),
            "watch_paused": watch_pause(store, now),
            # the status bar's word and why, worked out here once
            "health": health.served(self.app, now),
        }

    def today(self, request: Request):
        store = self.rt.store
        now = utcnow()
        try:
            since, seen = resolve_since(store, request.query_params.get("since"), now)
        except ValueError:
            return _error('since must be "last" or an ISO time')
        # a source that cannot be read is counted nowhere here; its list says so (RCA A3)
        rows = [r for r in self.app.topics_api.source_rows() if not rowsafe.is_unreadable(r)]
        topics_out: list[dict] = []
        project_out: list[dict] = []
        everything = library.topics_with_status(store)
        for topic, status, _ in everything:
            # project topics (migration 23) are listed apart, so the user's groups and
            # totals stay the user's topics
            out = topics_out if topic.kind == "user" else project_out
            with rowsafe.row(out, "topic", topic.id, name=topic.name, status=status,
                             kind=topic.kind, new_kept=0, proposed=0):
                f = library.ObservationFilter(topic_id=topic.id, since=since)
                top, total = library.find_observations(store, f, sort="signal",
                                                       limit=TOP_SHOWN)
                # a project's topic held while builds are off waits on no one
                proposed = [] if library.held(topic) else [
                    r for r in rows if r["review"] == "proposed" and (
                        topic.id in {t["id"] for t in r["topics"]}
                        or r.get("proposed_topic") == topic.id)]
                out.append({
                    "id": topic.id, "name": topic.name, "status": status,
                    "kind": topic.kind, "ref": topic.ref,
                    "new_kept": total, "top": self._obs(top),
                    "proposed": len(proposed),
                    "proposed_ticked": [r["id"] for r in proposed if r.get("pretick")],
                    "proposed_items_per_day": round(sum(
                        (r.get("validation") or {}).get("recent") or 0
                        for r in proposed) / 30, 1),
                })
        active = [t for t, status, _ in everything if status == "active"]
        messages = [m for m in notify.recent_messages(store, MESSAGES_SHOWN)
                    if m["created_at"] > since]
        return JSONResponse({
            "since": since, "seen_at": seen, "now": iso(now),
            "default_window_hours": int(DEFAULT_WINDOW.total_seconds() // 3600),
            "topics": topics_out,
            "project_topics": project_out,
            "new_kept": sum(t["new_kept"] for t in topics_out),
            "proposed": sum(t["proposed"] for t in topics_out),
            "rising": self._rising(active),
            "messages": messages,
            # Watched sources failing run after run (source_health.needs_fixing): they back
            # off by themselves, and Needs you asks to fix or remove them. Paced ones are
            # not listed: a throttled source is not a failure.
            "sources_failing": source_health.needs_fixing(store, self.rt.cfg, now=now),
            # sources the owner's downvotes recommend removing (source_rule,): a
            # Needs you row with Remove and Keep; nothing is removed without the press
            "sources_to_remove": source_rule.to_remove(
                store, getattr(self.rt.cfg, "grading", None), now=now),
            "ingest": self._ingest_line(now),
        })

    def seen(self, request: Request):
        since, seen = resolve_since(self.rt.store, None)
        return JSONResponse({"seen_at": seen, "since": since})

    async def set_seen(self, request: Request):
        from .app import _json_body

        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object")
        at = body.get("at")
        if at is not None and not isinstance(at, str):
            return _error("at must be an ISO time, or left out for now")
        try:
            return JSONResponse(mark_seen(self.rt.store, at))
        except ValueError as exc:
            return _error(str(exc) if "future" in str(exc) else "at must be an ISO time")

    def home_visit(self, request: Request):
        """The home was seen (``core.home.visit``): the ordinary home says so each time it is
        drawn, While you were away only when one of its rows is opened or Show today chosen.
        No body; answers the marker as stored."""
        from ..core import home
        return JSONResponse(home.visit(self.rt.store))

    def spend_topics(self, request: Request):
        """This month's model spend by topic. A call that judged or screened an item counts
        for its source's topics, split evenly between them; a call on a source with no topic is
        the broad lane's; any other call is listed by purpose (map names, cards, the scout...);
        calls already removed by compaction are one line. The parts sum to the month's spend
        (``Store.month_spend``), so the page can say so."""
        store = self.rt.store
        now = utcnow()
        start = iso(month_start(now))
        links: dict[int, list[int]] = {}
        for r in store.query("SELECT topic_id, source_id FROM topic_links"):
            links.setdefault(r["source_id"], []).append(r["topic_id"])
        source_of: dict[int, int] = {}
        for r in store.query(
                "SELECT i.source_id, i.llm_call_id AS call FROM items_seen i "
                "WHERE i.llm_call_id IN (SELECT id FROM llm_calls WHERE created_at >= ?) "
                "UNION ALL SELECT i.source_id, i.screen_call_id FROM items_seen i "
                "WHERE i.screen_call_id IN (SELECT id FROM llm_calls WHERE created_at >= ?)",
                (start, start)):
            source_of.setdefault(r["call"], r["source_id"])
        by_topic: dict[int, list[float]] = {}
        broad, other = [0.0, 0], {}
        for c in store.query("SELECT id, purpose, COALESCE(cost_usd, 0) AS usd FROM llm_calls "
                             "WHERE created_at >= ?", (start,)):
            usd = float(c["usd"])
            src = source_of.get(c["id"])
            if src is None:
                # a call of a feature that left Kranto (cut 2) is one line in words,
                # never its raw purpose (radar_propose, invest_card)
                purpose = RETIRED_SPEND if str(c["purpose"] or "").startswith(
                    RETIRED_PURPOSES) else c["purpose"]
                o = other.setdefault(purpose, [0.0, 0])
                o[0] += usd
                o[1] += 1
            elif links.get(src):
                share = usd / len(links[src])
                for t in links[src]:
                    row = by_topic.setdefault(t, [0.0, 0])
                    row[0] += share
                    row[1] += 1
            else:
                broad[0] += usd
                broad[1] += 1
        total = store.month_spend(now)
        counted = sum(v[0] for v in by_topic.values()) + broad[0] + sum(v[0] for v in
                                                                        other.values())
        names = {t.id: t.name for t, _, _ in library.topics_with_status(store)}
        evaluation, other = evaluation_spend(other)
        return JSONResponse({
            "month": start[:7], "total_usd": round(total, 6),
            "topics": sorted(({"id": t, "name": names.get(t, f"topic {t}"),
                               "usd": round(v[0], 6), "calls": v[1]}
                              for t, v in by_topic.items()), key=lambda x: -x["usd"]),
            "broad": {"usd": round(broad[0], 6), "calls": broad[1]},
            "other": sorted(({"purpose": p, "usd": round(v[0], 6), "calls": v[1]}
                             for p, v in other.items()), key=lambda x: -x["usd"]),
            "evaluation": evaluation,
            "compacted_usd": round(max(0.0, total - counted), 6),
            "budget_usd": self.rt.cfg.budget.monthly_usd,
        })

    def routes(self) -> list[Route]:
        return [
            Route("/api/today", self.today),
            Route("/api/seen", self.seen),
            Route("/api/seen", self.set_seen, methods=["POST"]),
            Route("/api/home/visit", self.home_visit, methods=["POST"]),
            Route("/api/spend/topics", self.spend_topics),
        ]
