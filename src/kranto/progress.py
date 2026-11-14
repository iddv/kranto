"""What a new library is still missing before each page has something to show.

A new workspace has empty pages for days: the map needs ``MIN_OBSERVATIONS``
observations and idea cards need a map with a cluster worth writing about.
These messages say how far along the library is instead of leaving a person
to guess whether anything is working.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ideate.cards import BRIDGE_MIN_TOPIC_SHARE
from .map import read as map_read
from .map.compute import CROSS_SOURCE_MIN_SIZE, MIN_OBSERVATIONS
from .store import Store


@dataclass(frozen=True)
class Progress:
    observations: int
    has_map: bool
    candidate_clusters: int | None  # clusters in the latest map that idea cards can use

    @property
    def map_message(self) -> str:
        if self.has_map:
            return ""
        if self.observations < MIN_OBSERVATIONS:
            return (f"{self.observations} of {MIN_OBSERVATIONS} observations until the "
                    "first map.")
        return (f"{self.observations} observations: enough for a first map. It is drawn at "
                "the next scheduled map, or now with Map now.")

    @property
    def ideas_message(self) -> str:
        need = (f"Ideas need a map and a cross-source cluster of at least "
                f"{CROSS_SOURCE_MIN_SIZE} observations (or one of that size that bridges "
                "topics).")
        if not self.has_map:
            return f"{need} {self.map_message}"
        if not self.candidate_clusters:
            return (f"{need} The latest map has none yet; more observations from more "
                    "sources make one likelier.")
        n = self.candidate_clusters
        return (f"The latest map has {n} cluster{'s' if n != 1 else ''} ideas can be written "
                "from. Cards are generated on the ideas schedule, or now with "
                "'python -m kranto ideas'.")


def observation_count(store: Store) -> int:
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM observations o "
        "WHERE NOT EXISTS (SELECT 1 FROM observations x WHERE x.supersedes = o.id)")
    return int(row["n"]) if row else 0


# -- the first hour of a topic ---------------------------------------------------------


def first_read(store: Store, topic_id: int, *, counts: bool = True) -> dict[str, Any] | None:
    """The topic's first read, once it has ended: the first ingest run (not a skip) that fetched
    one of its sources after the source was linked to it. ``{run_uuid, started_at, finished_at,
    status, kept, judged}``: ``kept`` is what that run kept from the topic's sources, ``judged``
    what it took in from them. None while no such run has ended."""
    # the earliest ingest run that fetched one of its sources once linked (source_fetches_source
    # per linked source); its runs row exists once it has ended. A run in progress has no row
    # yet, and a later run cannot end before it (one ingest at a time), so the first is the one.
    first = store.query_one(
        "SELECT f.run_uuid FROM topic_links l JOIN source_fetches f ON f.source_id = l.source_id "
        "WHERE l.topic_id = ? AND f.created_at >= l.created_at AND f.trigger = 'run' "
        "AND f.run_uuid IS NOT NULL ORDER BY f.id LIMIT 1", (int(topic_id),))
    if first is None:
        return None
    row = store.query_one(
        "SELECT run_uuid, started_at, finished_at, status FROM runs WHERE run_uuid = ? "
        "AND kind = 'ingest' ORDER BY rowid LIMIT 1", (first["run_uuid"],))
    if row is None:
        return None
    if not counts:
        return {**dict(row), "kept": None, "judged": None}
    got = store.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(i.outcome = 'contributed'), 0) AS k "
        "FROM items_seen i WHERE i.run_uuid = ? AND i.source_id IN "
        "(SELECT source_id FROM topic_links WHERE topic_id = ?)", (row["run_uuid"], int(topic_id)))
    return {"run_uuid": row["run_uuid"], "started_at": row["started_at"],
            "finished_at": row["finished_at"], "status": row["status"],
            "kept": int(got["k"] or 0) if got else 0,
            "judged": int(got["n"] or 0) if got else 0}


def read_counts(store: Store, run_uuid: str) -> dict[int, dict[str, int]]:
    """A read's counts so far, by topic: ``{topic_id: {kept, judged}}`` from its ``items_seen``
    rows (written as each item is consumed, so a running read answers too)."""
    rows = store.query(
        "SELECT l.topic_id AS t, COUNT(*) AS n, COALESCE(SUM(i.outcome = 'contributed'), 0) AS k "
        "FROM items_seen i JOIN topic_links l ON l.source_id = i.source_id "
        "WHERE i.run_uuid = ? GROUP BY l.topic_id", (run_uuid,))
    return {int(r["t"]): {"kept": int(r["k"] or 0), "judged": int(r["n"] or 0)} for r in rows}


def first_read_at(store: Store, topic_id: int) -> str | None:
    """When the topic's first read ended (ISO), or None: what News' first brief waits for."""
    got = first_read(store, topic_id, counts=False)
    return got["finished_at"] if got else None


QUIET_KEPT = 1          # kept in the first read at most, for the topic's page to call it quiet
NUMBER_WORDS = ("No item", "One item", "Two items", "Three items")


def _items(n: int) -> str:
    return NUMBER_WORDS[n] if 0 <= n < len(NUMBER_WORDS) else f"{n} items"


def quiet_line(kept: int) -> str:
    """Under the four rows, when the first read kept little."""
    return (f"A quiet topic takes longer. {_items(kept)} in the first read "
            f"{'is' if kept == 1 else 'are'} few. Scout more sources or widen the sentence, and "
            "ideas come sooner.")


STUCK_SCHEDULER = ("Not while Kranto runs with the scheduler off: nothing is read "
                   "(kranto serve --no-scheduler)")
STUCK_KEY = "Not until a model key is set (Settings › Watching)"


def topic_start(store: Store, topic_id: int, *, next_runs: dict[str, str | None] | None,
                news_on: bool, reading: dict[str, Any] | None = None,
                brief_running: bool = False, no_key: bool = False) -> dict[str, Any]:
    """The four rows of a new topic's page, in order: Sources, First read, First
    brief, First ideas, each ``{key, title, state, words, at}`` read from stored rows and the
    scheduler's own next runs (``next_runs``: ``Scheduler.next_runs()``, None without a
    scheduler), never promised by hand. ``done`` once the topic has its first idea card: the
    page then draws none of it. ``quiet``: the line under the rows when the first read kept
    little. ``news_on``: News is on for the topic (and as a whole); ``reading``: the running
    ingest's progress (``tick.current_progress``); ``brief_running``: its brief is being written.
    With no scheduler (``next_runs`` None) or no model key (``no_key``) a row that waits says why
    nothing comes, never a time (8: "Written as soon as the first read ends" on a copy that
    could not read). No model call."""
    from .ideate.cards import ideas_of_topic
    from .map.compute import MIN_OBSERVATIONS

    tid = int(topic_id)
    nxt = next_runs or {}
    stuck = STUCK_SCHEDULER if next_runs is None else STUCK_KEY if no_key else None
    sources = store.query(
        "SELECT l.source_id, l.created_at FROM topic_links l WHERE l.topic_id = ? AND "
        "(SELECT e.status FROM status_events e WHERE e.entity = 'source' AND "
        "e.entity_id = l.source_id ORDER BY e.id DESC LIMIT 1) = 'approved' "
        "ORDER BY l.created_at", (tid,))
    rows: list[dict[str, Any]] = []
    n = len(sources)
    rows.append({"key": "sources", "title": "Sources",
                 "state": "done" if n else "waiting",
                 "words": f"{n} source{'s' if n != 1 else ''} watched" if n
                 else "None watched yet: tick the proposals that fit and choose Watch these.",
                 "at": sources[0]["created_at"] if n else None})

    read = first_read(store, tid)
    if read is not None:
        rows.append({"key": "read", "title": "First read", "state": "done",
                     "words": f"Kept {read['kept']} of {read['judged']} items read",
                     "at": read["finished_at"]})
    elif not n:
        rows.append({"key": "read", "title": "First read", "state": "waiting",
                     "words": "Starts once a source is watched.", "at": None})
    elif reading is not None:
        so_far = read_counts(store, str(reading.get("run_uuid") or "")).get(tid) \
            if reading.get("run_uuid") else None
        rows.append({"key": "read", "title": "First read", "state": "running",
                     "words": "Reading now" + (f": source {reading.get('source_index') or 1} of "
                                               f"{reading.get('sources')}"
                                               if reading.get("sources") else "")
                     + (f" · {so_far['kept']} kept of {so_far['judged']} read"
                        if so_far and so_far["judged"] else ""),
                     "at": reading.get("started_at")})
    else:
        rows.append({"key": "read", "title": "First read", "state": "waiting",
                     "words": stuck or "At the next read",
                     "at": None if stuck else nxt.get("ingest")})

    brief = store.query_one(
        "SELECT id, status, items, created_at, trigger FROM news_briefs WHERE topic_id = ? "
        "AND status IN ('ok', 'quiet') ORDER BY id LIMIT 1", (tid,))
    if brief is not None:
        import json
        try:
            items = len(json.loads(brief["items"] or "[]"))  # stored-shape: news' own list
        except ValueError:
            items = 0
        rows.append({"key": "brief", "title": "First brief",
                     "state": "done" if brief["status"] == "ok" else "quiet",
                     "words": f"{items} item{'s' if items != 1 else ''}" if brief["status"] == "ok"
                     else "Nothing new worth your time in the first read",
                     "at": brief["created_at"], "brief_id": brief["id"]})
    elif not news_on:
        rows.append({"key": "brief", "title": "First brief", "state": "off",
                     "words": "News is off for this topic", "at": None})
    elif brief_running:
        rows.append({"key": "brief", "title": "First brief", "state": "running",
                     "words": "Being written now", "at": None})
    else:
        from .features.news.brief import EARLY_KEPT
        got = store.query_one(
            "SELECT COUNT(*) AS n FROM news_briefs WHERE topic_id = ? AND status = 'failed'",
            (tid,))
        failed = int(got["n"]) if got else 0
        rows.append({"key": "brief", "title": "First brief",
                     "state": "failed" if failed and read is not None else "waiting",
                     "words": stuck or ("The first try failed; it is tried again at the next hour"
                               if failed and read is not None else
                               # a topic whose first read ended before News was turned on (one
                               # made before the change: Padel on the copy) waits for News' hour
                               "Written at News' next hour" if read is not None else
                               # written once the read has kept EARLY_KEPT
                               f"As soon as {EARLY_KEPT} items are kept"),
                     # the scheduler's own time after a failed try, News' next
                     # hour; before the first read ends no time of another job's (
                     # fix 10: "tonight at 23:47" was the hourly briefs' next run)
                     "at": None if stuck or read is None else nxt.get("news.brief")})

    cards = ideas_of_topic(store, tid)
    total = observation_count(store)
    if cards:
        first = store.query_one(
            f"SELECT MIN(created_at) AS t FROM ideas WHERE id IN ({','.join('?' * len(cards))})",
            tuple(sorted(cards)))
        rows.append({"key": "ideas", "title": "First ideas", "state": "done",
                     "words": f"{len(cards)} card{'s' if len(cards) != 1 else ''}",
                     "at": first["t"] if first else None})
    else:
        rows.append({"key": "ideas", "title": "First ideas", "state": "waiting",
                     **ideas_wait(store, nxt, total, MIN_OBSERVATIONS)})
    quiet = quiet_line(read["kept"]) if read is not None and read["kept"] <= QUIET_KEPT \
        and not cards else None
    return {"topic_id": tid, "done": bool(cards), "rows": rows, "quiet": quiet,
            "observations": total, "needed": MIN_OBSERVATIONS}


def ideas_wait(store: Store, next_runs: dict[str, str | None], total: int,
               needed: int) -> dict[str, Any]:
    """When the first ideas come, as the topic's row and Ideas' empty page say it: after the
    map, once ``needed`` items are kept (``So far: 12.``), else after the next map at its time."""
    at = next_runs.get("snapshot")
    if total < needed:
        # the hour and the threshold both: "after tonight's map at 22:00, once 30
        # items are kept"; ``at`` is the map's own next run, None without a scheduler
        return {"words": f"After the map, once {needed} items are kept. So far: {total}.",
                "at": at}
    return {"words": "After the next map", "at": at}


def library_progress(store: Store) -> Progress:
    n = observation_count(store)
    snap = map_read.latest(store)
    candidates = None
    if snap is not None:
        candidates = 0
        for c in map_read.clusters(store, snap["id"]):
            total = sum(c["topic_mix"].values())
            bridging = c["size"] >= CROSS_SOURCE_MIN_SIZE and sum(
                1 for v in c["topic_mix"].values()
                if total and v / total >= BRIDGE_MIN_TOPIC_SHARE) >= 2
            candidates += int(c["cross_source"] or bridging)
    return Progress(observations=n, has_map=snap is not None, candidate_clusters=candidates)
