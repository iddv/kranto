"""Writing a brief: one grounded call per topic when its brief is due.

Inputs: the topic's observations kept since its last brief (the window is the topic's, not the
clock's: a failed day makes the next brief cover two), two dated live searches, and the
previous brief's items so the model can say what is new. Nothing from model memory: the prompt
forbids it, and an item whose citations name nothing is dropped by ``check``. One reason-tier
call (``news.model``), then the checks, then the row; ``brief.published`` on the bus.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta, tzinfo
from typing import Any

from kranto.core.text import (
    NO_SEARCH,
    combine,
    fenced,
    iso,
    outlet,
    parse_time,
    possessive,
    utcnow,
)

from . import check as checks
from .stored import BriefChecks, BriefItems, BriefSearch

CADENCES = ("daily", "weekdays", "weekly")
MAX_ATTEMPTS_A_DAY = 2
FIRST_WINDOW = {"daily": 1, "weekdays": 3, "weekly": 7}   # days a topic's first brief covers
LOCAL_TZ: tzinfo | None = None            # the machine's zone (tests set one)
_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def lock_for(topic_id: int) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(int(topic_id), threading.Lock())


def running(topic_id: int) -> bool:
    return lock_for(topic_id).locked()


# -- the topic's News setting ---------------------------------------------------------------------


def topic_setting(ctx: Any, topic_id: int) -> dict[str, Any]:
    """The newest ``news_topics`` row for a topic, or News off with the defaults. A row written
    when the topic was made (``origin: new_topic``,) is News on at the owner's own
    ``news.cadence`` and ``news.hour`` as they are now, until the topic's page sets its own."""
    r = ctx.db.query_one("SELECT * FROM news_topics WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
                         (int(topic_id),))
    s = ctx.settings
    if r is None:
        return {"topic_id": int(topic_id), "enabled": False, "cadence": s["news.cadence"],
                "hour": s["news.hour"], "weekday": 0, "since": None}
    if r["origin"] == NEW_TOPIC:
        return {"topic_id": r["topic_id"], "enabled": bool(r["enabled"]),
                "cadence": s["news.cadence"], "hour": s["news.hour"], "weekday": 0,
                "since": r["created_at"]}
    return {"topic_id": r["topic_id"], "enabled": bool(r["enabled"]), "cadence": r["cadence"],
            "hour": r["hour"], "weekday": r["weekday"] if r["weekday"] is not None else 0,
            "since": r["created_at"]}


NEW_TOPIC = "new_topic"     # news_topics.origin of the row a topic gets when it is made
FIRST_READ = "first_read"   # news_briefs.trigger of the brief written when its first read ends
# news_briefs.trigger of the brief written while a topic's first read is still going, as soon as
# it has kept EARLY_KEPT items: the first brief within minutes, not after
# the whole read. The first read's own brief (FIRST_READ) is written over the whole read when it
# ends and takes its place on Today; it reads past this one (``previous`` skips it).
FIRST_EARLY = "first_early"
EARLY_KEPT = 8


def news_topics_row(topic_id: int, now: str) -> dict[str, Any]:
    """The ``news_topics`` row a topic gets when it is made (``library.add_topic_once``): News on
    for it. Its cadence and hour are placeholders: ``topic_setting`` reads the owner's own
    defaults for a row of this origin. Topics made before this change keep what they had."""
    return {"topic_id": int(topic_id), "enabled": 1, "cadence": "daily", "hour": 7,
            "weekday": 0, "origin": NEW_TOPIC, "created_at": now}


def set_topic(ctx: Any, topic_id: int, *, enabled: bool, cadence: str | None = None,
              hour: int | None = None, weekday: int | None = None,
              origin: str = "ui") -> dict[str, Any]:
    topics = {t["id"] for t in ctx.read("topics.list")["topics"]}
    if int(topic_id) not in topics:
        raise ValueError(f"no topic {topic_id}")
    cur = topic_setting(ctx, topic_id)
    cadence = cadence or cur["cadence"]
    if cadence not in CADENCES:
        raise ValueError(f"cadence is one of {', '.join(CADENCES)}")
    hour = cur["hour"] if hour is None else hour
    weekday = cur["weekday"] if weekday is None else weekday
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ValueError("hour is a whole number from 0 to 23")
    if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise ValueError("weekday is 0 (Monday) to 6 (Sunday)")
    ctx.db.insert("news_topics", {"topic_id": int(topic_id), "enabled": int(bool(enabled)),
                                  "cadence": cadence, "hour": hour, "weekday": weekday,
                                  "origin": origin, "created_at": iso(ctx.now())})
    return topic_setting(ctx, topic_id)


# -- due-ness -------------------------------------------------------------------------------------


def local(now: datetime) -> datetime:
    return now.astimezone(LOCAL_TZ) if LOCAL_TZ is not None else now.astimezone()


def briefs_on_local_day(ctx: Any, topic_id: int, day: date) -> list[Any]:
    rows = ctx.db.query("SELECT id, status, created_at FROM news_briefs WHERE topic_id = ? AND "
                        "created_at >= ? ORDER BY id", (int(topic_id),
                                                        iso(utcnow() - timedelta(days=8))))
    return [r for r in rows if local(parse_time(r["created_at"]) or utcnow()).date() == day]


def due(setting: dict[str, Any], todays: list[Any], now: datetime) -> bool:
    """Whether a topic's brief is due now: its local hour has passed on a day its
    cadence runs, and no brief (ok or quiet) covers the day; a failed one is tried again,
    at most twice a day."""
    if not setting["enabled"]:
        return False
    here = local(now)
    if here.hour < setting["hour"]:
        return False
    if setting["cadence"] == "weekdays" and here.weekday() >= 5:
        return False
    if setting["cadence"] == "weekly" and here.weekday() != setting["weekday"]:
        return False
    if any(r["status"] in ("ok", "quiet") for r in todays):
        return False
    return len(todays) < MAX_ATTEMPTS_A_DAY


def first_due(ctx: Any, topic: dict[str, Any]) -> bool:
    """Whether a topic's first brief is due now, whatever the hour: News is on for
    it, its first read has ended (``topics.list``'s ``first_read_at``), and it has no brief yet
    (ok or quiet). Written once a topic: a failed first try is tried again at most
    ``MAX_ATTEMPTS_A_DAY`` times in all, then the topic waits for its ordinary hour."""
    if not topic.get("first_read_at"):
        return False
    # every column: ctx.db refuses a statement that names the column "trigger" (a keyword)
    rows = ctx.db.query("SELECT * FROM news_briefs WHERE topic_id = ?", (int(topic["id"]),))
    # the early brief (FIRST_EARLY) does not count: the first read's own still follows it
    if any(r["status"] in ("ok", "quiet") and r["trigger"] != FIRST_EARLY for r in rows):
        return False
    return sum(1 for r in rows if r["trigger"] == FIRST_READ) < MAX_ATTEMPTS_A_DAY


def early_due(ctx: Any, topic: dict[str, Any], kept: int) -> bool:
    """Whether a topic's early first brief is due: News is on for it, its
    first read is still going (no ``first_read_at``), that read has kept at least ``EARLY_KEPT``
    of its items, and the topic has no brief of any kind yet. Tried once a topic: a failed early
    brief leaves the first read's own brief to come at the read's end, as before."""
    if topic.get("status") not in (None, "active") or topic.get("first_read_at"):
        return False
    if kept < EARLY_KEPT or not topic_setting(ctx, topic["id"])["enabled"]:
        return False
    return ctx.db.query_one("SELECT id FROM news_briefs WHERE topic_id = ? LIMIT 1",
                            (int(topic["id"]),)) is None


def run_early(ctx: Any, kept: dict[int, int]) -> dict[str, Any]:
    """While a read runs: the early first brief of each topic in its first read that has kept
    ``EARLY_KEPT`` items (``kept``: the read's kept items so far, by topic id). Called from the
    read itself, between two items (``cli.server_jobs``), so it never runs beside it."""
    made: list[dict[str, Any]] = []
    for t in ctx.read("topics.list")["topics"]:
        if not early_due(ctx, t, int(kept.get(int(t["id"]), 0))):
            continue
        ctx.progress(f"Writing {possessive(t['name'])} first brief from the first items",
                     detail={"topic": t["id"]})
        out = write(ctx, t, trigger=FIRST_EARLY)
        if out is not None:
            made.append({"topic_id": t["id"], "brief_id": out["id"], "status": out["status"]})
    if not made:
        return {"status": "skipped", "briefs": 0}
    failed = sum(1 for m in made if m["status"] == "failed")
    return {"status": "degraded" if failed else "ok", "briefs": len(made), "failed": failed}


def run_due(ctx: Any) -> dict[str, Any]:
    """The hourly job, and the job that follows each read (``scheduler.FOLLOWS``): a brief for
    every enabled topic that is due; a topic's first brief as soon as its first read ends."""
    now = ctx.now()
    made: list[dict[str, Any]] = []
    skipped = 0
    for t in ctx.read("topics.list")["topics"]:
        if t["status"] != "active":
            continue
        s = topic_setting(ctx, t["id"])
        if not s["enabled"]:
            continue
        trigger = FIRST_READ if first_due(ctx, t) else "schedule"
        if trigger != FIRST_READ and \
                not due(s, briefs_on_local_day(ctx, t["id"], local(now).date()), now):
            skipped += 1
            continue
        if ctx.stop_requested():
            return {"status": "skipped", "briefs": len(made), "stopped_by": "owner",
                    "why": f"stopped by you after {len(made)} brief"
                           f"{'' if len(made) == 1 else 's'}; the rest at the next hour"}
        ctx.progress(f"Writing {possessive(t['name'])} {'first ' if trigger == FIRST_READ else ''}"
                     "brief", detail={"topic": t["id"]})
        out = write(ctx, t, trigger=trigger)
        if out is not None:
            made.append({"topic_id": t["id"], "brief_id": out["id"], "status": out["status"]})
    # the job's second half: the article of each of today's briefs still
    # missing its picks, a failed one tried again at most twice a day
    from . import articles
    arts = articles.run_due(ctx)
    if not made and not arts["articles"] and not arts["failed"]:
        return {"status": "skipped", "briefs": 0, "not_due": skipped}
    failed = sum(1 for m in made if m["status"] == "failed")
    return {"status": "degraded" if failed or arts["failed"] else "ok", "briefs": len(made),
            "failed": failed, "articles": arts["articles"], "articles_failed": arts["failed"]}


# -- inputs ---------------------------------------------------------------------------------------


def previous(ctx: Any, topic_id: int) -> dict[str, Any] | None:
    """The topic's newest ok or quiet brief, skipping an early first brief (``FIRST_EARLY``):
    the first read's own brief covers the whole read, the early one's stories with it."""
    rows = ctx.db.query("SELECT * FROM news_briefs WHERE topic_id = ? AND status IN "
                        "('ok', 'quiet') ORDER BY id DESC LIMIT 5", (int(topic_id),))
    r = next((x for x in rows if x["trigger"] != FIRST_EARLY), None)
    return dict(r) if r else None


def window(ctx: Any, topic_id: int, cadence: str, now: datetime) -> tuple[str, dict[str,
           Any] | None]:
    prev = previous(ctx, topic_id)
    if prev is not None:
        return prev["period_end"], prev
    return iso(now - timedelta(days=FIRST_WINDOW.get(cadence, 1))), None


def proper_nouns(titles: list[str], skip: set[str], n: int = 3) -> list[str]:
    """The most frequent capitalised words of the window's titles, not at a title's start,
    not the topic's own words: what else is said about what the watchers saw."""
    c: Counter[Any] = Counter()
    for t in titles:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9.+-]*", t or "")
        for tok in tokens[1:]:
            if tok[0].isupper() and len(tok) > 2 and tok.lower() not in skip:
                c[tok] += 1
    return [w for w, _ in c.most_common(n)]


def observation_lines(obs: list[dict[str, Any]]) -> tuple[str, dict[str, checks.Line]]:
    lines, block = {}, []
    for o in sorted(obs, key=lambda o: (o["date"] or "", o["id"])):
        label = f"obs {o['id']}"
        lines[label] = checks.Line(label, "obs", o["date"] or None, o["title"], o["url"],
                                   f"{o['summary']} {o['why']}", float(o["signal"] or 0.0),
                                   o["id"], o["source"])
        block.append(f"[{label}] {o['date'] or 'undated'} | {o['title']} | {o['source']} | "
                     f"{o['url'] or ''}\n{o['summary']}")
    return "\n".join(block) or "(none)", lines


def search_lines(results: Any) -> dict[str, checks.Line]:
    out = {}
    for label, h in results.numbered():
        # the item names the site it was published on, not the search that found it
        out[label] = checks.Line(label, "web", h.date, fenced(h.title), h.url,
                                 fenced(h.snippet), 0.0, None, outlet(h.url, results.labels[0]
                                 if results.labels else h.backend))
    return out


def searches(ctx: Any, topic: dict[str, Any], titles: list[str]) -> Any:
    """Two dated searches: the topic's name with "news this week" (web and the
    discussion backend), and the name with the window's three most frequent proper nouns."""
    if ctx.search is None:
        return None
    skip = {w.lower() for w in re.findall(r"[A-Za-z]+", topic["name"])} | {"the", "and", "new"}
    nouns = proper_nouns(titles, skip)
    first = ctx.search.search(f"{topic['name']} news this week", kind="discussion",
                              recency="1w", n=10)
    if not nouns:
        return first
    second = ctx.search.search(f"{topic['name']} {' '.join(nouns)}", kind="web", recency="1w",
                               n=10)
    return combine(first, second)


def _previous_json(prev: dict[str, Any] | None) -> str:
    if prev is None:
        return "(none: this is the first brief)"
    items = BriefItems.load(prev["items"]).items
    return json.dumps([{"headline": i["headline"], "date": i.get("date"),
                        "sources": [s.get("url") or s.get("label") for s in i.get("sources", [])]}
                       for i in items], ensure_ascii=False) if items else \
        f"(quiet: {prev.get('quiet') or 'nothing new'})"


def parse_reply(text: str) -> dict[str, Any]:
    """The model's JSON object, from a reply that may wrap it in a fence or prose."""
    text = (text or "").strip()
    try:
        out = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("the reply has no JSON object") from None
        out = json.loads(text[start:end + 1])
    if not isinstance(out, dict) \
            or not isinstance(out.get("items", []), list):  # stored-shape: the model's reply
        raise ValueError("the reply is not {items, quiet}")
    return out


# -- one brief ------------------------------------------------------------------------------------


def write(ctx: Any, topic: dict[str, Any], *, trigger: str) -> dict[str, Any] | None:
    """Write one brief for ``topic`` (a ``topics.list`` row). None when one is being written
    for it already (the hourly job and Brief now never overlap)."""
    lock = lock_for(topic["id"])
    if not lock.acquire(blocking=False):
        return None
    try:
        return _write(ctx, topic, trigger)
    finally:
        lock.release()


def _write(ctx: Any, topic: dict[str, Any], trigger: str) -> dict[str, Any]:
    s = ctx.settings
    now = ctx.now()
    setting = topic_setting(ctx, topic["id"])
    since, prev = window(ctx, topic["id"], setting["cadence"], now)
    obs = ctx.read("library.observations", topic_id=topic["id"], since=since,
                   limit=s["news.max_observations"], sort="signal")["observations"]
    block, lines = observation_lines(obs)
    results = None
    try:
        results = searches(ctx, topic, [o["title"] for o in obs])
    except Exception as exc:  # noqa: BLE001 - a brief without search says so
        ctx.log.warning("news search for topic %s failed: %s", topic["id"], exc)
    search_block = results.block() if results is not None else \
        f"Live search results: none. {NO_SEARCH}"
    if results is not None:
        lines.update(search_lines(results))
    base = {"topic_id": topic["id"], "run_uuid": ctx.run_uuid, "period_start": since,
            "period_end": iso(now), "previous_id": prev["id"] if prev else None,
            "trigger": trigger, "search": BriefSearch.write(_search_meta(results)),
            "created_at": iso(now)}
    if not obs and (results is None or not results.hits):
        return _store(ctx, {**base, "status": "quiet", "items": "[]",
                            "quiet": f"nothing new worth your time since {since[:10]}",
                            "checks": BriefChecks.write({"no_material": True})})
    prompt = ctx.prompt("news")
    today = local(now).date()
    text = prompt.render_keeping(
        "search_block", today=today.isoformat(), topic_name=fenced(topic["name"]),
        topic_description=fenced(topic.get("description") or ""), max_items=s["news.max_items"],
        period_start=since[:10], previous_date=prev["created_at"][:10] if prev else "none",
        previous=_previous_json(prev), since=since[:10], observations=block,
        search_block=search_block)
    tier = s["news.model"]
    try:
        reply = ctx.llm.complete(purpose="news_brief", tier=tier,
                                 messages=[{"role": "user", "content": text}],
                                 prompt_version=prompt.version, run_uuid=ctx.run_uuid,
                                 max_tokens=4000, temperature=0.2,
                                 schema=ctx.prompt_schema("news"), retry_truncated=True)
        parsed = parse_reply(reply.text)
    except Exception as exc:  # noqa: BLE001 - a failed brief is a row with its reason
        return _store(ctx, {**base, "status": "failed", "items": "[]",
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                            "prompt_version": prompt.version, "checks": "{}"})
    cost = float(reply.cost_usd or 0)
    equiv = float(reply.equiv_usd or 0)
    items = parsed.get("items") or []
    shortened = 0
    long_ones = [i for i, it in enumerate(items)
                 if isinstance(it, dict) and checks.too_long(it, s["news.max_words"])]
    if long_ones:
        items, shortened, extra = _shorter(ctx, items, long_ones, prompt.version, tier,
                                           s["news.max_words"])
        cost += extra[0]
        equiv += extra[1]
    prev_items = BriefItems.load(prev["items"]).items if prev else []
    kept, rep = checks.check(items, lines, prev_items, today=today,
                             max_items=s["news.max_items"], max_words=s["news.max_words"],
                             max_age_days=s["news.max_age_days"])
    rep.shortened = shortened
    status = "ok" if kept else "quiet"
    quiet = None if kept else (parsed.get("quiet") or
                               f"nothing new worth your time since {since[:10]}")
    report = {**rep.as_dict(), "model_items": len(items), "kept": len(kept),
              "observations": len(obs), "search_hits": len(results.hits) if results else 0}
    return _store(ctx, {**base, "status": status, "items": BriefItems.write(kept),
                        "quiet": quiet and str(quiet)[:300], "llm_call_id": reply.call_id,
                        "prompt_version": prompt.version, "model": reply.model,
                        "cost_usd": round(cost, 6),
                        "equiv_usd": round(equiv, 6) if equiv else None,
                        "checks": BriefChecks.write(report)})


SHORTER = ("These items of a news brief are too long. Rewrite each one shorter, keeping its "
           "facts and its cites exactly: body one sentence, two at most, under 40 words; why "
           "one sentence under 20 words; headline under 90 characters. Reply with exactly one "
           'JSON object {{"items": [...], "quiet": null}} with the items in the same order.\n\n'
           "{items}")


def _shorter(ctx: Any, items: list[Any], idx: list[int], version: str, tier: str,
             max_words: int) -> tuple[list[Any], int, tuple[float, float]]:
    """the length rule: the over-long items are asked once more, shorter (the retry is in
    the ledger); an answer that changes an item's cites, or is still long, is not taken."""
    ask = [items[i] for i in idx]
    try:
        reply = ctx.llm.complete(purpose="news_brief", tier=tier, messages=[
            {"role": "user", "content": SHORTER.format(items=json.dumps(ask,
                                                                        ensure_ascii=False))}],
            prompt_version=version, run_uuid=ctx.run_uuid, max_tokens=2000, temperature=0.2)
        got = parse_reply(reply.text).get("items") or []
    except Exception:  # noqa: BLE001 - the check cuts them instead
        return items, 0, (0.0, 0.0)
    out, n = list(items), 0
    for i, new in zip(idx, got, strict=False):
        if isinstance(new, dict) and new.get("cites") == items[i].get("cites") and \
                not checks.too_long(new, max_words):
            out[i] = {**items[i], **{k: new.get(k, items[i].get(k))
                                     for k in ("headline", "body", "why")}}
            n += 1
    return out, n, (float(reply.cost_usd or 0), float(reply.equiv_usd or 0))


def _search_meta(results: Any) -> dict[str, Any]:
    if results is None:
        return {"live": False, "note": NO_SEARCH}
    return {"live": results.live, "labels": list(results.labels), "searched_at":
            results.searched_at, "note": results.note, "query": results.query[:300],
            "hits": len(results.hits)}


def _store(ctx: Any, row: dict[str, Any]) -> dict[str, Any]:
    bid = ctx.db.insert("news_briefs", row)
    items = BriefItems.load(row.get("items")).items
    ctx.publish("brief.published", {"brief_id": bid, "topic_id": row["topic_id"],
                                    "status": row["status"], "items": len(items)},
                subject=("brief", bid))
    return {**row, "id": bid}
