"""An imported archive as JSON: its themes, and what it holds (``python -m kranto import
parallax``).

| Method and path                      | Does                                              |
|--------------------------------------|---------------------------------------------------|
| GET /api/archive                     | the archive in numbers: observations, sources,   |
|                                      | themes, dispatch cards by kind and status         |
| GET /api/archive/themes              | every theme, alive first then by size             |
| GET /api/archive/themes/{lineage_id} | one theme                                         |

A theme is a lineage of the archive's own clustering (``archive_themes``): its name (the
most recent Parallax gave it, else its keywords), the other names it had, keywords, when it
was first and last seen, whether it is alive in the latest bundle, its size, its history
(``trajectory``: share and size per epoch, at most ``TRAJECTORY_POINTS`` evenly spaced, the
last always kept), its members still in the library (``members``; list them with
``/api/observations?theme=<lineage_id>``), and the dispatches whose clusters it was, with
the cards made from each. Every number is a query; no model call is made.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..ideate.dispatches import ORIGIN, dispatch_cards
from ..importers import ARCHIVE, latest_themes
from ..store import Store
from ..stored.cards import Card

TRAJECTORY_POINTS = 60
NAMES_SHOWN = 5


def _trajectory(history: list[dict]) -> list[dict]:
    if len(history) <= TRAJECTORY_POINTS:
        picked = history
    else:
        step = (len(history) - 1) / (TRAJECTORY_POINTS - 1)
        picked = [history[round(i * step)] for i in range(TRAJECTORY_POINTS)]
    return [{"at": h["at"], "share": h.get("share"), "size": h["n"]} for h in picked]


def _dispatches_by_lineage(store: Store) -> dict[str, list[dict]]:
    out: dict[str, dict[str, dict]] = {}
    for r in store.query("SELECT id, status, title, card FROM ideas WHERE origin = ? "
                         "ORDER BY id", (ORIGIN,)):
        card = Card.load(r["card"])
        d = card.dispatch or {}
        for lin in card.lineages:
            if not lin.get("lineage_id"):
                continue
            entry = out.setdefault(lin["lineage_id"], {}).setdefault(d.get("dispatch_id"), {
                "dispatch_id": d.get("dispatch_id"), "title": d.get("title"),
                "date": d.get("date"), "url": d.get("url"), "cards": []})
            entry["cards"].append({"id": r["id"], "kind": card.pitch_kind,
                                   "title": r["title"], "status": r["status"]})
    return {k: sorted(v.values(), key=lambda d: d["date"] or "", reverse=True)
            for k, v in out.items()}


def theme_records(store: Store) -> list[dict]:
    members = {r["lineage_id"]: r["n"] for r in store.query(
        "SELECT t.lineage_id, COUNT(o.id) AS n FROM archive_themes t "
        "JOIN archive_theme_members m ON m.theme_id = t.id "
        "JOIN observations o ON o.id = m.observation_id "
        "WHERE t.archive = ? AND t.id = (SELECT MAX(l.id) FROM archive_themes l "
        "WHERE l.archive = t.archive AND l.lineage_id = t.lineage_id) GROUP BY t.id",
        (ARCHIVE,))}
    by_lineage = _dispatches_by_lineage(store)
    from .. import rowsafe

    def record(t: dict) -> dict:
        names = t["names"]
        return {
            "lineage_id": t["lineage_id"], "name": t["name"],
            "named": bool(names), "names": [n["name"] for n in names[:NAMES_SHOWN]],
            "name_count": len(names), "keywords": t["keywords"], "alive": bool(t["alive"]),
            "size": t["size"], "first_at": t["first_at"], "last_at": t["last_at"],
            "epochs": t["epochs"], "members": members.get(t["lineage_id"], 0),
            "trajectory": _trajectory(t["history"]),
            "dispatches": by_lineage.get(t["lineage_id"], []), "bundle": t["bundle"],
        }
    # one theme that cannot be read is listed as such, never the whole list
    return rowsafe.each(latest_themes(store, ARCHIVE), record, "theme",
                        ident=lambda t: t.get("lineage_id"),
                        keep=lambda t: {"lineage_id": t.get("lineage_id"),
                                        "name": t.get("name")})


class ArchiveAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def store(self) -> Store:
        return self.app.rt.store

    def summary(self, request: Request):
        store = self.store
        obs = store.query_one(
            "SELECT COUNT(*) AS n, MIN(o.created_at) AS first, MAX(o.created_at) AS last "
            "FROM observations o JOIN sources s ON s.id = o.source_id WHERE s.kind = ?",
            (ARCHIVE,))
        sources = store.query_one("SELECT COUNT(*) AS n FROM sources WHERE kind = ?",
                                  (ARCHIVE,))["n"]
        themes = latest_themes(store, ARCHIVE)
        cards = dispatch_cards(store)
        by_kind: dict[str, int] = {}
        for c in cards:
            by_kind[c["kind"] or "other"] = by_kind.get(c["kind"] or "other", 0) + 1
        return JSONResponse({
            "archive": ARCHIVE, "observations": obs["n"], "first_at": obs["first"],
            "last_at": obs["last"], "sources": sources, "themes": len(themes),
            "alive_themes": sum(1 for t in themes if t["alive"]),
            "retention_days": self.app.rt.cfg.retention.days_for_kind(ARCHIVE),
            "topic_match": self.app.rt.cfg.parallax.topic_match,
            "dispatch_cards": {"total": len(cards), "by_kind": by_kind,
                               "shown": sum(1 for c in cards if c["status"] == "shown"),
                               "dispatches": len({c["dispatch"].get("dispatch_id")
                                                  for c in cards})},
        })

    def themes(self, request: Request):
        records = theme_records(self.store)
        return JSONResponse({"archive": ARCHIVE, "themes": records, "count": len(records)})

    def theme(self, request: Request):
        lineage = request.path_params["lineage_id"]
        record = next((t for t in theme_records(self.store) if t["lineage_id"] == lineage), None)
        if record is None:
            return JSONResponse({"error": "no such theme"}, status_code=404)
        return JSONResponse(record)

    def routes(self) -> list[Route]:
        return [
            Route("/api/archive", self.summary),
            Route("/api/archive/themes", self.themes),
            Route("/api/archive/themes/{lineage_id}", self.theme),
        ]
