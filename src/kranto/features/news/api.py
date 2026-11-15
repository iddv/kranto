"""News's reads and actions (the API, the surfaces).

Reads (``GET /api/f/news/<name>``): ``briefs.list`` and ``briefs.get`` (also on the v1 read
surface, for Invest and later mods), ``topics`` (every topic with its News setting, last brief
and whether one is being written), ``latest`` (the newest brief of each topic News is on for:
the morning view) and ``count`` (briefs of the last day, for the navigator). A brief from
``brief`` (the page's read of ``briefs.get``) and ``latest`` carries ``articles``: each item's
article as Today shows it (``{n: {id, status, minutes, diagram, timeline, …}}``).
``articles.list`` (newest first, without their bodies), ``articles.get`` (one, as checked) and
``article_for_item`` (an item's newest article, or why it has none) read the articles.

Actions (``POST /api/f/news/act/<verb>``): ``toggle`` (News on or off for a topic, with its
cadence and hour: the one press), ``write_now`` (Brief now: started in the background, never
waited on by the page; refused while one is being written), ``article_now`` (Deep dive now:
the article for one item, in the background; refused while one is being written for it).
"""

from __future__ import annotations

import re
import threading
from datetime import timedelta
from typing import Any

from kranto.core import rows as rowsafe
from kranto.core.text import is_backend_label, iso, outlet

from . import articles, brief
from .stored import BriefChecks, BriefItems, BriefSearch

LIST_MAX = 50


def _int(params: dict[str, Any], key: str, default: Any=None) -> Any:
    v = params.get(key, default)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{key} is a whole number") from None


KRANTO_ON = re.compile(r"^\s*(?:it\s+)?kranto\s+on\s+", re.IGNORECASE)


def plain_why(why: Any) -> Any:
    """A why line as the page says it: one written before the prompt's
    change that opens "Kranto on …" (which reads as the product's name) loses those words."""
    if not isinstance(why, str) or not KRANTO_ON.match(why):
        return why
    rest = KRANTO_ON.sub("", why, count=1).strip()
    return rest[:1].upper() + rest[1:] if rest else why


def _outlets(items: list[Any]) -> list[Any]:
    """A web source stored with the search backend's name as its outlet (briefs written before
     D6: "Exa, free mode (rate-limited, no account)") reads as its own site; a why line
    that opens "Kranto on" says what it Kranto on (``plain_why``)."""
    for it in items:
        if isinstance(it, dict) and "why" in it:
            it["why"] = plain_why(it["why"])
        for s in (it.get("sources") or []) if isinstance(it, dict) else []:
            if isinstance(s, dict) and is_backend_label(s.get("source")):
                s["source"] = outlet(s.get("url"), s["source"])
    return items


def _stories(ctx: Any, b: dict[str, Any]) -> dict[str, Any]:
    """Each story's idea and theme (the core's read ``ideas.for_stories``):
    a page read only. When it cannot answer, the brief still answers, with none."""
    try:
        items = [{"observation_ids": it.get("observation_ids") or []} if isinstance(it, dict)
                 else {} for it in b["items"]]
        out = ctx.read("ideas.for_stories", brief_id=b["id"], items=items).get("stories")
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001 - the brief still answers without its ideas
        ctx.log.exception("the stories' ideas of brief %s could not be read", b["id"])
        return {}


def _brief(r: Any) -> dict[str, Any]:
    items = _outlets(BriefItems.load(r["items"]).items)
    return {"id": r["id"], "topic_id": r["topic_id"], "status": r["status"],
            "period_start": r["period_start"], "period_end": r["period_end"],
            "items": items, "quiet": r["quiet"], "error": r["error"],
            "search": BriefSearch.load(r["search"]).extra,
            "checks": BriefChecks.load(r["checks"]).extra,
            "cost_usd": r["cost_usd"], "equiv_usd": r["equiv_usd"], "model": r["model"],
            "prompt_version": r["prompt_version"], "previous_id": r["previous_id"],
            "trigger": r["trigger"], "created_at": r["created_at"]}


def briefs_list(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    topic = _int(params, "topic_id")
    limit = max(1, min(_int(params, "limit", 20), LIST_MAX))
    sql, args = "SELECT * FROM news_briefs", []
    where = []
    if topic is not None:
        where.append("topic_id = ?")
        args.append(topic)
    if params.get("since"):
        where.append("created_at > ?")
        args.append(str(params["since"]))
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = ctx.db.query(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
    # one brief that cannot be read is listed as such, never the whole list (RCA A3)
    return {"briefs": rowsafe.each(rows, _brief, "brief", ident=lambda r: r["id"],
                                   keep=lambda r: {"topic_id": r["topic_id"],
                                                   "created_at": r["created_at"]})}


def briefs_get(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    r = ctx.db.query_one("SELECT * FROM news_briefs WHERE id = ?", (_int(params, "id"),))
    if r is None:
        raise ValueError("no such brief")
    return _brief(r)


def brief_page(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """The brief as its page and an item's page read it: ``briefs.get`` with each item's
    article. A page read only, never on the v1 surface (a cub reads ``briefs.get``: an article's
    source picture never reaches anything that publishes)."""
    b = briefs_get(ctx, params)
    return {**b, "articles": _articles_of(ctx, b["id"]), "stories": _stories(ctx, b)}


def _articles_of(ctx: Any, brief_id: int) -> dict[str, Any]:
    """Each item's article as Today and the brief's page show it (the newest ok one, else the
    newest try with its reason), keyed by the item's number as text."""
    out = {}
    lead = ctx.settings["news.lead_image"]
    for n, r in articles.for_items(ctx, brief_id).items():
        v = articles.row_view(r, full=False, lead_image=lead)
        out[str(n)] = {**{k: v[k] for k in ("id", "status", "kind", "headline", "minutes",
                                             "words", "diagram", "timeline", "quiet", "error",
                                             "created_at", "image")},
                       "running": articles.running(brief_id, n)}
    return out


def _next_due(setting: dict[str, Any], now: Any) -> str | None:
    if not setting["enabled"]:
        return None
    here = brief.local(now)
    for d in range(0, 8):
        day = (here + timedelta(days=d)).replace(hour=setting["hour"], minute=0, second=0,
                                                 microsecond=0)
        if day < here.replace(minute=0, second=0, microsecond=0):
            continue
        if setting["cadence"] == "weekdays" and day.weekday() >= 5:
            continue
        if setting["cadence"] == "weekly" and day.weekday() != setting["weekday"]:
            continue
        return iso(day)
    return None


def topics(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    now = ctx.now()
    out: list[dict[str, Any]] = []
    for t in ctx.read("topics.list")["topics"]:
        with rowsafe.row(out, "topic", t["id"], name=t["name"], status=t["status"]):
            s = brief.topic_setting(ctx, t["id"])
            last = ctx.db.query_one("SELECT id, status, created_at, items FROM news_briefs "
                                    "WHERE topic_id = ? ORDER BY id DESC LIMIT 1", (t["id"],))
            out.append({"id": t["id"], "name": t["name"], "status": t["status"], "news": s,
                        "running": brief.running(t["id"]), "next_due": _next_due(s, now),
                        "last": {"id": last["id"], "status": last["status"],
                                 "created_at": last["created_at"],
                                 "items": len(BriefItems.load(last["items"]).items)}
                        if last else None})
    search = ctx.search.off_reason() if ctx.search is not None else "no live search"
    return {"topics": out, "enabled": ctx.settings["news.enabled"], "search_off": search,
            "spend": ctx.read("spend.mine") if "spend" in ctx.feature.permissions.reads else None}


def latest(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for t in ctx.read("topics.list")["topics"]:
        with rowsafe.row(out, "brief", t["id"], topic={"id": t["id"], "name": t["name"]}):
            if not brief.topic_setting(ctx, t["id"])["enabled"]:
                continue
            newest = ctx.db.query_one("SELECT * FROM news_briefs WHERE topic_id = ? ORDER BY "
                                      "id DESC LIMIT 1", (t["id"],))
            # a failed try never takes the topic's good brief off Today: the newest ok or
            # quiet brief stays, and the failure is one line under it (``failed``)
            good = newest if newest is None or newest["status"] != "failed" else \
                ctx.db.query_one("SELECT * FROM news_briefs WHERE topic_id = ? AND status IN "
                                 "('ok', 'quiet') ORDER BY id DESC LIMIT 1", (t["id"],))
            r = good or newest
            b = _brief(r) if r else None
            failed = failed_line(ctx, newest) if newest is not None and \
                newest["status"] == "failed" else None
            out.append({"topic": {"id": t["id"], "name": t["name"]},
                        "brief": {**b, "articles": _articles_of(ctx, b["id"]),
                                  "stories": _stories(ctx, b)} if b else None,
                        "failed": failed})
    return {"topics": out}


def failed_line(ctx: Any, r: Any) -> dict[str, Any]:
    """A failed brief as Today's one line under the good one: when, why in the owner's words
    (the context's ``model_trouble``: the provider's own trouble, said with where it is fixed),
    and the page's route that fixes it."""
    error = r["error"] or ""
    say = getattr(ctx, "model_trouble", None)
    t = say(error) if callable(say) else None
    why = t["words"] if t else (error.split(": ", 1)[-1][:200] or "no reason was given")
    return {"id": r["id"], "created_at": r["created_at"], "why": why,
            "fix": t["fix"] if t else None}


def today(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """The home's New rows (row 2): each topic's brief of the last day, one row each."""
    since = iso(ctx.now() - timedelta(days=1))
    rows: list[dict[str, Any]] = []
    names = {t["id"]: t["name"] for t in ctx.read("topics.list")["topics"]}
    for r in ctx.db.query("SELECT * FROM news_briefs WHERE status = 'ok' AND created_at > ? "
                          "ORDER BY id DESC LIMIT 20", (since,)):
        if r["topic_id"] not in names or any(x.get("topic_id") == r["topic_id"]
                                             for x in rows):
            continue
        with rowsafe.row(rows, "brief", r["id"], topic_id=r["topic_id"],
                         title=f"{names[r['topic_id']]} · the brief", at=r["created_at"]):
            n = len(BriefItems.load(r["items"]).items)
            rows.append({"id": r["id"], "topic_id": r["topic_id"],
                         "title": f"{names[r['topic_id']]} · the brief",
                         "meta": f"{n} item{'' if n == 1 else 's'}", "at": r["created_at"],
                         "open": f"news/b/{r['id']}"})
    return {"rows": rows}


def widget_brief(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """The home's widget The brief, a rows widget: the newest brief's
    headlines across the topics News is on for, each opening the brief on News."""
    names = {t["id"]: t["name"] for t in ctx.read("topics.list")["topics"]
             if brief.topic_setting(ctx, t["id"])["enabled"]}
    for r in ctx.db.query("SELECT * FROM news_briefs WHERE status = 'ok' ORDER BY id DESC "
                          "LIMIT 20"):
        if r["topic_id"] not in names:
            continue
        items = BriefItems.load(r["items"]).items
        made = {n: a for n, a in articles.for_items(ctx, r["id"]).items()
                if a["status"] == "ok"}
        name = names[r["topic_id"]]
        return {"as_of": r["created_at"],
                "rows": [{"id": f"{r['id']}-{i}", "title": it.get("headline") or "",
                          "meta": f"{name} · article, {articles.minutes(made[i]['words'])} min"
                          if i in made else f"{name} · the brief", "at": r["created_at"],
                          "tone": "quiet" if it.get("background") else "new",
                          "open": f"news/a/{made[i]['id']}" if i in made
                          else f"news/b/{r['id']}"}
                         for i, it in enumerate(items) if it.get("headline")]}
    return {"rows": []}


def count(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    since = iso(ctx.now() - timedelta(days=1))
    r = ctx.db.query_one("SELECT COUNT(*) AS n FROM news_briefs WHERE status = 'ok' AND "
                         "created_at > ?", (since,))
    return {"count": int(r["n"])}


def articles_list(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Articles, newest first, without their bodies (Earlier's Articles group): ``topic_id``,
    ``limit``, ``status`` (ok by default; ``all`` for every try)."""
    topic = _int(params, "topic_id")
    limit = max(1, min(_int(params, "limit", 20), LIST_MAX))
    sql, args, where = "SELECT * FROM news_articles", [], []
    if topic is not None:
        where.append("topic_id = ?")
        args.append(topic)
    status = str(params.get("status") or "ok")
    if status != "all":
        where.append("status = ?")
        args.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = ctx.db.query(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
    lead = ctx.settings["news.lead_image"]
    return {"articles": rowsafe.each(rows, lambda r: articles.row_view(r, full=False,
                                                                       lead_image=lead),
                                     "article", ident=lambda r: r["id"],
                                     keep=lambda r: {"topic_id": r["topic_id"],
                                                     "created_at": r["created_at"]})}


def articles_get(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """One article as checked, with its topic's name and the newest article of its item."""
    r = ctx.db.query_one("SELECT * FROM news_articles WHERE id = ?", (_int(params, "id"),))
    if r is None:
        raise ValueError("no such article")
    out = articles.row_view(r, full=True, lead_image=ctx.settings["news.lead_image"])
    names = {t["id"]: t["name"] for t in ctx.read("topics.list")["topics"]}
    b = ctx.db.query_one("SELECT created_at FROM news_briefs WHERE id = ?", (r["brief_id"],))
    newest = ctx.db.query_one("SELECT MAX(id) AS id FROM news_articles WHERE brief_id = ? AND "
                              "item_n = ? AND status = 'ok'", (r["brief_id"], r["item_n"]))
    return {**out, "topic": names.get(r["topic_id"]),
            "brief_at": b["created_at"] if b else None,
            "newest_id": newest["id"] if newest is not None and newest["id"] else r["id"]}


def article_for_item(ctx: Any, params: dict[str, Any]) -> dict[str, Any]:
    """An item's newest article (ok first), or why it has none: ``{article, running, score,
    eligible}``; ``article`` null when none was written."""
    bid, n = _int(params, "brief_id"), _int(params, "n")
    r = ctx.db.query_one("SELECT * FROM news_briefs WHERE id = ?", (bid,))
    if r is None:
        raise ValueError("no such brief")
    got = articles.for_items(ctx, bid).get(n)
    scored = next((s for s in articles.scores(ctx, dict(r)) if s["n"] == n), None)
    return {"article": articles.row_view(got, full=False,
                                         lead_image=ctx.settings["news.lead_image"])
            if got is not None else None,
            "running": articles.running(bid, n),
            "score": scored["score"] if scored else None,
            "eligible": bool(scored and scored["eligible"])}


# -- actions --------------------------------------------------------------------------------------


def toggle(ctx: Any, fields: dict[str, Any]) -> dict[str, Any]:
    on = fields.get("on")
    if not isinstance(on, bool):
        raise ValueError("on is true or false")
    s = brief.set_topic(ctx, _int(fields, "topic_id"), enabled=on,
                        cadence=fields.get("cadence"), hour=fields.get("hour"),
                        weekday=fields.get("weekday"), origin=getattr(ctx, "door", None) or "ui")
    return {"topic_id": s["topic_id"], "news": s, "next_due": _next_due(s, ctx.now())}


def write_now(ctx: Any, fields: dict[str, Any]) -> dict[str, Any]:
    topic_id = _int(fields, "topic_id")
    topic = next((t for t in ctx.read("topics.list")["topics"] if t["id"] == topic_id), None)
    if topic is None:
        raise ValueError(f"no topic {topic_id}")
    if brief.running(topic_id):
        raise ValueError("a brief for this topic is being written; it shows here when done")

    def work() -> None:
        try:
            with ctx.run("news.write", subject=("topic", topic_id, topic.get("name"))) as run:
                out = brief.write(ctx, topic, trigger="now")
                if out is not None and out["status"] == "ok":
                    articles.run_due(ctx, [topic])
                elif out is not None and out["status"] == "failed":
                    # the run failed with the brief, its reason in words (Activity listed a
                    # failed try as "Wrote a brief")
                    run.result = {"status": "failed", "brief_id": out["id"],
                                  "error": failed_line(ctx, out)["why"]}
        except Exception:  # noqa: BLE001 - written as a failed brief or logged
            ctx.log.exception("Brief now failed for topic %s", topic_id)

    if getattr(ctx, "sync", False):
        work()
        return {"started": True, "topic_id": topic_id, "running": False}
    threading.Thread(target=work, name=f"news-brief-{topic_id}", daemon=True).start()
    return {"started": True, "topic_id": topic_id, "running": True}


def article_now(ctx: Any, fields: dict[str, Any]) -> dict[str, Any]:
    """Deep dive now: the article for item ``n`` of brief ``brief_id``, in the background (it
    reads the pages behind the item and calls the model once)."""
    bid, n = _int(fields, "brief_id"), _int(fields, "n")
    r = ctx.db.query_one("SELECT * FROM news_briefs WHERE id = ?", (bid,))
    if r is None:
        raise ValueError(f"no brief {bid}")
    items = BriefItems.load(r["items"]).items
    if n is None or not 0 <= n < len(items):
        raise ValueError(f"brief {bid} has no item {n}")
    if not items[n].get("observation_ids"):
        raise ValueError("this item rests on search results alone: there is no page behind it "
                         "Kranto may read")
    topic = next((t for t in ctx.read("topics.list")["topics"] if t["id"] == r["topic_id"]),
                 None)
    if topic is None:
        raise ValueError(f"no topic {r['topic_id']}")
    if articles.running(bid, n):
        raise ValueError("an article for this item is being written; it shows here when done")
    why = articles.capped(ctx)
    if why:
        raise ValueError(why)
    head = str(items[n].get("headline") or "")[:60]

    def work() -> None:
        try:
            with ctx.run("news.article", title=f"Deep dive: {head}",
                         subject=("topic", topic["id"], topic.get("name"))):
                articles.write(ctx, topic, dict(r), n, trigger="now")
        except Exception:  # noqa: BLE001 - written as a failed article or logged
            ctx.log.exception("Deep dive now failed for brief %s item %s", bid, n)

    if getattr(ctx, "sync", False):
        work()
        return {"started": True, "brief_id": bid, "n": n, "running": False}
    threading.Thread(target=work, name=f"news-article-{bid}-{n}", daemon=True).start()
    return {"started": True, "brief_id": bid, "n": n, "running": True}
