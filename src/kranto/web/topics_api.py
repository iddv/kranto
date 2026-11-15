"""Topics as JSON, for Kranto UI's Topics tab (PLAN.md sections 2.2 and 2.3).

| Method and path                | Does                                                      |
|--------------------------------|-----------------------------------------------------------|
| GET  /api/topics?kind=         | every topic (active or paused) with its facts; the broad lane |
|                                | kind: user (default), project or all (migration 23);       |
|                                | ``archived``: the owner's archived topics, facts and all   |
| GET  /api/topics/{id}          | one topic (archived too): facts, themes, its sources by group, |
|                                | ``history``: its edits, sources added or removed, statuses |
| GET  /api/topics/{id}/start    | its first hour: Sources, First read, First brief, |
|                                | First ideas, each with its state and time; ``done`` once  |
|                                | it has an idea card; ``quiet`` when the first read kept little |
| POST /api/topics/{id}          | {name, description, origin, note}: the owner's edit   |
| POST /api/topics/{id}/sources  | {add: [ids], remove: [ids], origin}: one topic's sources;   |
|                                | ``remaining``: the topics each removed source still feeds  |
| POST /api/topics/{id}/status   | {status}: active, paused or archived                       |

``POST /api/topics`` (add) and ``POST /api/topics/{id}/scout`` are in ``sources_api``; both
return the scout's proposals in the shape ``source_rows`` gives here.

Facts are counted the way Settings › Sources counts them: items a day are what ingest
runs consumed from the topic's watched sources over the last seven days, before any
filtering; kept a day are those that became observations. A theme is a cluster of the
latest map whose stories come from this topic's sources for at least ``THEME_MIN_SHARE``
of the cluster. Spend is the model calls that judged or screened the topic's items this
month. No model call is made by any of these.

An edit (migration 38) keeps the topic's id: its name and description are a new
``topic_revisions`` row, read everywhere through ``topics_now``, so every page, card, cub and
brief that names the topic says the new name at once; its embedding is made again from the new
words by the local embedder (no model call). A theme counts the stories of every name the topic
has had (a map made before a rename filed them under the old one). Removing a source from a
topic is an ``unlink`` row (``topic_links``); a source left with no topic is retired too (as
Retire on its row: not read, its evidence kept), so it never falls into the broad lane, where
every item is judged. Adding one back undoes both. Each write records who (``origin``: ui, chat,
mcp or cli) and answers with what it changed, which is what the page's Undo sends back.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import grades, library, rowsafe, source_health
from ..map import read as map_read
from ..progress import library_progress
from ..store import iso, utcnow
from ..stored.sources import Validation

THEME_MIN_SHARE = 0.2
RISING_SHOWN = 3


FIRST_TICKS = 5     # places ticked for a topic that watches none yet


def first_ticks(rows: list[dict[str, Any]], topic_id: int) -> None:
    """A topic that watches no place yet has at most ``FIRST_TICKS`` of its close matches ticked,
    the best by fit; the rest stay proposed, unticked (its first read is the ticked places times
    their items: five places put the first brief inside minutes). A topic that already watches
    one keeps the rule as it was."""
    if any(r.get("review") == "approved" and any(t.get("id") == topic_id
                                                  for t in r.get("topics") or [])
           for r in rows):
        return
    ticked = sorted((r for r in rows if r.get("pretick")), key=lambda r: -float(r["_sim"]))
    for r in ticked[FIRST_TICKS:]:
        r["pretick"] = False


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


EDIT_ORIGINS = ("ui", "chat", "mcp", "cli")
MAX_SOURCES_A_CHANGE = 50


def theme_share(cluster: dict[str, Any], topic_name: str | set[str]) -> float:
    """The share of a cluster's stories that came from a topic's sources: under its name, or
    under any of ``topic_name`` when it is the set of names the topic has had."""
    names = {topic_name} if isinstance(topic_name, str) else topic_name
    total = cluster.get("stories") or cluster["size"] or 0
    mix = cluster["topic_mix"]
    return (sum(mix.get(n) or 0 for n in names) / total) if total else 0.0


class TopicsAPI:
    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def rt(self) -> Any:
        return self.app.rt

    def names(self, topic: library.Topic) -> set[str]:
        """Every name the topic has had (``library.topic_names_ever``), its current one too."""
        return library.topic_names_ever(self.rt.store, topic.id) | {topic.name}

    # -- reading ---------------------------------------------------------------------------

    def source_rows(self, topic_id: int | None = None, ids: set[int] | None = None,
                    first_for: int | None = None) -> list[dict[str, Any]]:
        """Sources as Settings › Sources lists them, with the topic each was proposed for
        and ``pretick``: what onboarding's proposal list ticks (a core proposal at or above
        the prefilter line, the scout's ``--approve`` rule; never a wildcard). For a topic
        (``topic_id``, or ``first_for``: the scout's rows for it) that watches nothing yet, at
        most ``FIRST_TICKS`` are ticked (``first_ticks``)."""
        store, cfg = self.rt.store, self.rt.cfg
        names = {t.id: t.name for t, _, _ in library.topics_with_status(store)}
        meta = {s.id: s.validation for s in library.list_sources(store)}
        line = cfg.ingest.prefilter_min_similarity
        links = source_health.source_links(store)
        out: list[dict[str, Any]] = []
        for row in source_health.list_sources(store, cfg):
            if ids is not None and row["id"] not in ids:
                continue
            v = meta.get(row["id"]) or Validation.empty()
            if rowsafe.is_unreadable(row):
                # listed where it belongs, as "Couldn't read this source" (RCA A3)
                if topic_id is None or topic_id in links.get(row["id"], []) or \
                        v.topic_id == topic_id:
                    out.append(row)
                continue
            with rowsafe.row(out, "source", row["id"], label=row.get("label"),
                             kind=row.get("kind"), review=row.get("review")):
                linked = {t["id"] for t in row["topics"]}
                for t in row["topics"]:
                    t["name"] = names.get(t["id"], t["name"])
                row["proposed_topic"] = v.topic_id
                row["role"] = v.role or "core"
                if row["role"] == "wildcard" and v.topic_id is not None and v.topic_id in names:
                    row["proposed_for"] = names[v.topic_id]
                if topic_id is not None and topic_id not in linked and v.topic_id != topic_id:
                    continue
                sim = v.median_similarity
                row["pretick"] = bool(row["review"] == "proposed" and row["role"] == "core"
                                      and sim is not None and sim >= line)
                row["_sim"] = sim if sim is not None else -1.0
                out.append(row)
        first = first_for if first_for is not None else topic_id
        if first is not None:
            first_ticks(out, first)
        for row in out:
            row.pop("_sim", None)
        return out

    def _counts(self) -> tuple[dict[int, int], dict[int, int]]:
        week = iso(utcnow() - timedelta(days=7))
        seen: dict[int, int] = {}
        kept: dict[int, int] = {}
        for r in self.rt.store.query(
                "SELECT source_id, COUNT(*) AS n, SUM(outcome = 'contributed') AS k "
                "FROM items_seen WHERE created_at >= ? GROUP BY source_id", (week,)):
            seen[r["source_id"]], kept[r["source_id"]] = r["n"], int(r["k"] or 0)
        return seen, kept

    def _spend(self, source_ids: list[int]) -> tuple[float, dict[str, Any] | None]:
        """This month's model calls on the topic's sources: (USD, {"in", "out"} tokens or
        None when no call has counts); a source's page asks the same."""
        return source_health.model_spend(self.rt.store, source_ids)

    def _clusters(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        snap = map_read.latest(self.rt.store)
        return (snap, map_read.clusters(self.rt.store, snap["id"])) if snap else (None, [])

    def _facts(self, topic: library.Topic, status: str, created_at: str,
               links: dict[int, set[int]], review: dict[int, str | None], seen: dict[int, int],
               kept: dict[int, int], clusters: list[dict[str, Any]]) -> dict[str, Any]:
        mine = [s for s, ts in links.items() if topic.id in ts]
        watched = [s for s in mine if review.get(s) == "approved"]
        observations = self.rt.store.query_one(
            "SELECT COUNT(*) AS n FROM observations o WHERE o.source_id IN "
            "(SELECT source_id FROM topic_links WHERE topic_id = ?) AND NOT EXISTS "
            "(SELECT 1 FROM observations n WHERE n.supersedes = o.id)", (topic.id,))["n"]
        names = self.names(topic)
        themes = [c for c in clusters if theme_share(c, names) >= THEME_MIN_SHARE]
        usd, tokens = self._spend(mine)
        return {
            "id": topic.id, "name": topic.name, "description": topic.description,
            "kind": topic.kind, "ref": topic.ref,
            "status": status, "created_at": created_at,
            "sources": len(watched),
            "proposed": sum(1 for s in mine if review.get(s) == "proposed"),
            "items_per_day": round(sum(seen.get(s, 0) for s in watched) / 7, 1),
            "kept_per_day": round(sum(kept.get(s, 0) for s in watched) / 7, 1),
            "observations": observations,
            "themes": len(themes),
            "rising": sum(1 for c in themes if c["rising"]),
            "spend_month_usd": usd,
            "tokens_month": tokens,
        }

    def _links(self) -> dict[int, set[int]]:
        links: dict[int, set[int]] = {}
        for r in self.rt.store.query("SELECT topic_id, source_id FROM topic_links"):
            links.setdefault(r["source_id"], set()).add(r["topic_id"])
        return links

    def list_topics(self, request: Request) -> Response:
        kind = request.query_params.get("kind") or "user"
        if kind not in (*library.TOPIC_KINDS, "all"):
            return _error("kind is user, project or all")
        store = self.rt.store
        links = self._links()
        srcs = library.list_sources(store)
        review = {s.id: s.status for s in srcs}
        seen, kept = self._counts()
        snap, clusters = self._clusters()
        rows = [(t, status, created) for t, status, created
                in library.topics_with_status(store, archived=True) if kind in ("all", t.kind)]

        def facts(r: tuple[library.Topic, str, str]) -> dict[str, Any]:
            return self._facts(r[0], r[1], r[2], links, review, seen, kept, clusters)

        def keep(r: tuple[library.Topic, str, str]) -> dict[str, Any]:
            return {"name": r[0].name, "kind": r[0].kind, "status": r[1]}

        # one topic or source that cannot be read is listed as such (RCA A3)
        topics = rowsafe.each([r for r in rows if r[1] != library.ARCHIVED], facts, "topic",
                              ident=lambda r: r[0].id, keep=keep)
        archived = rowsafe.each([r for r in rows if r[1] == library.ARCHIVED], facts, "topic",
                                ident=lambda r: r[0].id, keep=keep)
        broad = rowsafe.each(
            [s for s in srcs if s.status == "approved" and not links.get(s.id)],
            lambda s: {"id": s.id, "label": s.label, "kind": s.kind,
                       "items_per_day": round(seen.get(s.id, 0) / 7, 1),
                       "kept_per_day": round(kept.get(s.id, 0) / 7, 1),
                       "wildcard": s.validation is not None
                       and s.validation.role == "wildcard"},
            "source", keep=lambda s: {"label": s.label, "kind": s.kind})
        approved = [s.id for s in srcs if s.status == "approved"]
        return JSONResponse({
            "topics": topics, "archived": archived, "broad": broad,
            "all": {"observations": store.query_one(
                        "SELECT COUNT(*) AS n FROM observations o WHERE NOT EXISTS "
                        "(SELECT 1 FROM observations n WHERE n.supersedes = o.id)")["n"],
                    "sources": len(approved), "themes": len(clusters),
                    "items_per_day": round(sum(seen.get(s, 0) for s in approved) / 7, 1),
                    "map": snap["created_at"] if snap else None},
            "progress": library_progress(store).map_message,
            "every_hours": self.rt.cfg.ingest.every_hours,
            "theme_min_share": THEME_MIN_SHARE,
        })

    def one_topic(self, request: Request) -> Response:
        from ..ideate.explain import cached as cached_synthesis
        from .app import _moving_key, path_id
        from .kranto_api import _synthesis

        store = self.rt.store
        topic_id = path_id(request.path_params["topic_id"])
        found = next(((t, s, c) for t, s, c in library.topics_with_status(store, archived=True)
                      if t.id == topic_id), None)
        if found is None:
            return _error("no such topic", 404)
        topic, status, created = found
        links = self._links()
        review = {s.id: s.status for s in library.list_sources(store)}
        seen, kept = self._counts()
        snap, clusters = self._clusters()
        facts = self._facts(topic, status, created, links, review, seen, kept, clusters)
        names = self.names(topic)
        themes = [c for c in clusters if theme_share(c, names) >= THEME_MIN_SHARE]
        themes.sort(key=_moving_key)
        cluster_grades = grades.latest(store, "cluster", [c["lineage_id"] for c in themes])
        listed: list[dict[str, Any]] = []
        for c in themes:
            with rowsafe.row(listed, "theme", c.get("cluster"), label=c.get("label"),
                             lineage_id=c.get("lineage_id")):
                c["topic_share"] = round(theme_share(c, names), 4)
                c["grade"] = cluster_grades.get(str(c["lineage_id"]))
                c["synthesis"] = _synthesis(cached_synthesis(store,
                                                             f"cluster:{c['lineage_id']}"))
                c.pop("centroid_2d", None)
                listed.append(c)
        themes = listed
        sources = self.source_rows(topic.id)
        for s in sources:
            s["items_per_day_7d"] = round(seen.get(s["id"], 0) / 7, 1)
        return JSONResponse({
            **facts, "themes_list": themes,
            "rising_now": [c for c in themes if not rowsafe.is_unreadable(c) and (
                c["rising"] or (c["movement"] or {}).get("burst") == 1)][:RISING_SHOWN],
            "snapshot": {"id": snap["id"], "created_at": snap["created_at"]} if snap else None,
            "source_rows": sources,
            "prefilter": self.rt.cfg.ingest.prefilter_min_similarity,
            "every_hours": self.rt.cfg.ingest.every_hours,
            "budget_usd": self.rt.cfg.budget.monthly_usd,
            "progress": library_progress(store).map_message,
            "grade_labels": grades.LABELS, "grade_choices": [],   # a theme has no grade
            "history": library.topic_history(store, topic.id),
        })

    def start(self, request: Request) -> Response:
        """``GET /api/topics/{id}/start``: a new topic's first hour, the four rows
        Sources, First read, First brief, First ideas with their states and times (the
        scheduler's own next runs), the quiet line, and ``done`` once it has an idea card."""
        from ..core import registry
        from ..core import settings as feature_settings
        from ..features.news import brief
        from ..progress import topic_start
        from ..tick import current_progress
        from .app import path_id

        store = self.rt.store
        topic_id = path_id(request.path_params["topic_id"])
        if not any(t.id == topic_id for t, _, _ in library.topics_with_status(store,
                                                                              archived=True)):
            return _error("no such topic", 404)
        scheduler = getattr(self.app, "scheduler", None)
        try:
            news = registry.by_id("news")
            on = registry.enabled(self.rt.cfg, news) and bool(
                feature_settings.section(self.rt.cfg, "news").get("news.enabled", True))
        except KeyError:
            on = False
        if on:
            row = store.query_one("SELECT enabled FROM news_topics WHERE topic_id = ? "
                                  "ORDER BY id DESC LIMIT 1", (topic_id,))
            on = bool(row and row["enabled"])
        reading = current_progress()
        if reading is not None and scheduler is not None and scheduler.running != "ingest":
            reading = None
        return JSONResponse(topic_start(
            store, topic_id, next_runs=scheduler.next_runs() if scheduler is not None else None,
            news_on=on, reading=reading, brief_running=brief.running(topic_id),
            no_key=not getattr(getattr(self.rt, "llm", None), "has_key", True)))

    # -- writing ---------------------------------------------------------------------------

    @staticmethod
    def _origin(body: dict[str, Any]) -> str | None:
        origin = body.get("origin") or "ui"
        return origin if origin in EDIT_ORIGINS else None

    @staticmethod
    def _via(origin: str) -> str:
        return "via Kranto UI" if origin == "ui" else f"via {origin}"

    async def set_status(self, request: Request) -> Response:
        """Pause, resume, archive or restore. Answers with the status it had (``was``), which
        is what Undo sends back."""
        from .app import _json_body, path_id

        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object")
        origin = self._origin(body)
        if origin is None:
            return _error(f"origin is one of {', '.join(EDIT_ORIGINS)}")
        topic_id = path_id(request.path_params["topic_id"])
        status = str(body.get("status") or "")
        was = next((s for t, s, _ in library.topics_with_status(self.rt.store, archived=True)
                    if t.id == topic_id), None)
        try:
            changed = library.set_topic_status(self.rt.store, topic_id, status,
                                               self._via(origin))
        except ValueError as exc:
            return _error(str(exc), 404 if "no topic" in str(exc) else 400)
        return JSONResponse({"id": topic_id, "status": status, "was": was, "changed": changed})

    async def edit(self, request: Request) -> Response:
        """The owner's edit: ``{name, description}`` (either), ``origin``, ``note``. Answers
        with the change (``before`` and ``after``: Undo sends ``before`` back), or ``changed``
        None when the words were the same."""
        from .app import _json_body, path_id

        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object")
        origin = self._origin(body)
        if origin is None:
            return _error(f"origin is one of {', '.join(EDIT_ORIGINS)}")
        name, desc = body.get("name"), body.get("description")
        if name is None and desc is None:
            return _error("send a name, a description or both")
        if any(v is not None and not isinstance(v, str) for v in (name, desc)):
            return _error("name and description are text")
        note = body.get("note")
        note = " ".join(str(note).split())[:200] if note else None
        topic_id = path_id(request.path_params["topic_id"])
        try:
            change = await run_in_threadpool(lambda: library.edit_topic(
                self.rt.store, self.rt.embedder, topic_id, name=name, description=desc,
                by=origin, note=note))
        except ValueError as exc:
            return _error(str(exc), 404 if "no topic" in str(exc) else 400)
        return JSONResponse({"id": topic_id, "changed": change["changed"] if change else None,
                             "revision": change})

    async def sources(self, request: Request) -> Response:
        """One topic's sources: ``add`` and ``remove`` (lists of source ids), ``origin``. A
        source added is linked (and approved when it was retired or is still proposed); one
        removed is unlinked, and retired when no topic is left to it. Answers with what
        changed, ``retired`` and ``approved`` among it, so Undo can send it back, and the topics
        each removed source still feeds (``remaining``)."""
        from .app import _json_body, path_id

        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object")
        origin = self._origin(body)
        if origin is None:
            return _error(f"origin is one of {', '.join(EDIT_ORIGINS)}")
        add, remove = body.get("add") or [], body.get("remove") or []
        for v in (add, remove):
            if not isinstance(v, list) or len(v) > MAX_SOURCES_A_CHANGE or any(
                    isinstance(x, bool) or not isinstance(x, int) for x in v):
                return _error(f"add and remove are lists of at most {MAX_SOURCES_A_CHANGE} "
                              "source ids")
        if not add and not remove:
            return _error("send add or remove")
        if set(add) & set(remove):
            return _error("a source is either added or removed")
        store = self.rt.store
        topic_id = path_id(request.path_params["topic_id"])
        topic = next((t for t, _, _ in library.topics_with_status(store, archived=True)
                      if t.id == topic_id), None)
        if topic is None:
            return _error("no such topic", 404)
        known = {s.id: s for s in library.list_sources(store)}
        missing = [x for x in (*add, *remove) if x not in known]
        if missing:
            return _error(f"no source {missing[0]}", 404)
        note = f"{topic.name}, {self._via(origin)}"
        out: dict[str, Any] = {"id": topic_id, "added": [], "removed": [], "retired": [],
                               "approved": []}
        with store.tx():
            for sid in add:
                if library.link_topic_source(store, topic_id, sid, by=origin, note=note):
                    out["added"].append(sid)
                if known[sid].status in ("retired", "proposed"):
                    store.set_status("source", sid, "approved", f"added to {note}")
                    out["approved"].append(sid)
            for sid in remove:
                if not library.unlink_topic_source(store, topic_id, sid, by=origin, note=note):
                    continue
                out["removed"].append(sid)
                left = store.query_one("SELECT 1 FROM topic_links WHERE source_id = ?", (sid,))
                if left is None and known[sid].status == "approved":
                    store.set_status("source", sid, "retired",
                                     f"removed from its last topic, {note}")
                    out["retired"].append(sid)
        # what each removed source still feeds, for the toast's "It still feeds ..."
        links, refs = source_health.source_links(store), source_health.topic_refs(store)
        out["remaining"] = {str(sid): [source_health.topic_ref(refs, t)
                                       for t in links.get(sid, [])] for sid in out["removed"]}
        return JSONResponse(out)

    def routes(self) -> list[Route]:
        return [
            Route("/api/topics", self.list_topics),
            Route("/api/topics/{topic_id:int}", self.one_topic),
            Route("/api/topics/{topic_id:int}/start", self.start),
            Route("/api/topics/{topic_id:int}", self.edit, methods=["POST"]),
            Route("/api/topics/{topic_id:int}/sources", self.sources, methods=["POST"]),
            Route("/api/topics/{topic_id:int}/status", self.set_status, methods=["POST"]),
        ]
