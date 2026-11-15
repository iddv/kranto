"""The source rule: a source with many downvotes is recommended for removal.

For each watched source (``approved``, not paused by its topics), over the trailing
``grading.window_days`` (90), from the owner's latest grade on each of its observations:

    down = observations graded not useful or wrong
    up   = observations graded useful
    recommend removal when  down >= grading.remove_after (3)
                       and  up <= down * grading.remove_ratio (0.25)

So 3 down and 0 up, 4 and 1, 8 and 2; never 3 and 1. A cleared grade and a purged observation's
grade count for nothing. No model, nothing automatic: the recommendation is one Needs you row
whose **Remove** is ``source.retire`` (the owner's press, through the house confirm) and whose
**Keep** is ``source.keep``: one ``feedback`` action row (target ``source``, value ``keep``,
context ``{down, up, window_days}``). **Keep restarts the count** (D-9): only grades given after
the latest Keep count toward the next recommendation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from . import feedback, library
from .config import GradingConfig
from .store import Store, iso, utcnow
from .stored.misc import FeedbackContext

DOWN = ("not_useful", "wrong")


def keeps(store: Store) -> dict[int, dict[str, Any]]:
    """Each source's latest Keep: ``{at, row, down, up, window_days}`` (``row``: its feedback
    row's id; a grade counts after a Keep when its row is newer, even in the same second)."""
    out: dict[int, dict[str, Any]] = {}
    for r in store.query("SELECT id, target_id, context, created_at FROM feedback WHERE target = "
                         "'source' AND kind = 'action' AND value = 'keep' ORDER BY id"):
        try:
            sid = int(r["target_id"])
        except ValueError:
            continue
        ctx = FeedbackContext.load(r["context"]).extra
        out[sid] = {"at": r["created_at"], "row": int(r["id"]), "down": _count(ctx.get("down")),
                    "up": _count(ctx.get("up")), "window_days": _count(ctx.get("window_days"))}
    return out


def _count(v: Any) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def counts(store: Store, cfg: GradingConfig | None = None, *,
           now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Per source: ``{down, up, since, kept}`` over the window, counting from its latest Keep
    when that is later (``since`` the ISO time counted from, ``kept`` the Keep or None)."""
    cfg = cfg or GradingConfig()
    start = iso((now or utcnow()) - timedelta(days=cfg.window_days))
    kept = keeps(store)
    latest: dict[str, tuple[int, str, int]] = {}
    for r in store.query(
            "SELECT f.id, f.target_id, f.value, o.source_id FROM feedback f "
            "JOIN observations o ON o.id = CAST(f.target_id AS INTEGER) "
            "WHERE f.target = 'observation' AND f.kind = 'grade' AND f.created_at >= ? "
            "AND o.source_id IS NOT NULL ORDER BY f.id", (start,)):
        latest[r["target_id"]] = (int(r["source_id"]), r["value"], int(r["id"]))
    out: dict[int, dict[str, Any]] = {}
    for sid, value, row in latest.values():
        k = kept.get(sid)
        since = max(start, k["at"]) if k else start
        c = out.setdefault(sid, {"down": 0, "up": 0, "since": since, "kept": k})
        if k and row < k["row"]:      # given before the Keep: the count restarted
            continue
        if value in DOWN:
            c["down"] += 1
        elif value == "useful":
            c["up"] += 1
    for sid, k in kept.items():
        out.setdefault(sid, {"down": 0, "up": 0, "since": max(start, k["at"]), "kept": k})
    return out


def recommends(c: dict[str, Any] | None, cfg: GradingConfig) -> bool:
    return (c is not None and c["down"] >= cfg.remove_after
            and c["up"] <= c["down"] * cfg.remove_ratio)


def watched(store: Store) -> list[Any]:
    """The sources the rule reads: approved, and not paused by every topic they feed."""
    paused = library.paused_topic_sources(store)
    return [s for s in library.list_sources(store, status="approved") if s.id not in paused]


def state(store: Store, cfg: GradingConfig | None = None, *,
          now: datetime | None = None) -> dict[int, dict[str, Any]]:
    """Per source with grades or a Keep, what its sheet says: ``{recommend, down, up,
    window_days, kept}`` (``kept``: the latest Keep, ``{at, down, up, window_days}``, or None).
    ``recommend`` is only ever true for a watched source."""
    cfg = cfg or GradingConfig()
    live = {s.id for s in watched(store)}
    return {sid: {"recommend": sid in live and recommends(c, cfg), "down": c["down"],
                  "up": c["up"], "window_days": cfg.window_days, "kept": c["kept"]}
            for sid, c in counts(store, cfg, now=now).items()}


def to_remove(store: Store, cfg: GradingConfig | None = None, *,
              now: datetime | None = None) -> list[dict[str, Any]]:
    """The sources Kranto recommends removing, for Needs you: ``{id, label, kind, down, up,
    window_days, topics: [{id, name}], items_per_day}``, most downvoted first."""
    cfg = cfg or GradingConfig()
    now = now or utcnow()
    c = counts(store, cfg, now=now)
    picked = [s for s in watched(store) if recommends(c.get(s.id), cfg)]
    if not picked:
        return []
    names = {t.id: t.name for t, _, _ in library.topics_with_status(store, archived=True)}
    links: dict[int, list[int]] = {}
    for r in store.query("SELECT topic_id, source_id FROM topic_links ORDER BY topic_id"):
        links.setdefault(int(r["source_id"]), []).append(int(r["topic_id"]))
    week = iso(now - timedelta(days=7))
    seen = {int(r["source_id"]): int(r["n"]) for r in store.query(
        "SELECT source_id, COUNT(*) AS n FROM items_seen WHERE created_at >= ? "
        "GROUP BY source_id", (week,))}
    out = [{"id": s.id, "label": s.label, "kind": s.kind, "down": c[s.id]["down"],
            "up": c[s.id]["up"], "window_days": cfg.window_days,
            "topics": [{"id": t, "name": names.get(t, f"topic {t}")}
                       for t in links.get(s.id, [])],
            "items_per_day": round(seen.get(s.id, 0) / 7, 1)} for s in picked]
    return sorted(out, key=lambda r: (-r["down"], r["up"], r["id"]))


def keep(store: Store, source_id: int, cfg: GradingConfig | None = None, *,
         now: datetime | None = None) -> dict[str, Any]:
    """The owner keeps a source Kranto recommended removing: one ``feedback`` action row; the
    count restarts from now. Raises ValueError for a source that does not exist."""
    cfg = cfg or GradingConfig()
    if store.query_one("SELECT 1 FROM sources WHERE id = ?", (source_id,)) is None:
        raise ValueError(f"no source {source_id}")
    c = counts(store, cfg, now=now).get(source_id) or {"down": 0, "up": 0}
    ctx = {"down": c["down"], "up": c["up"], "window_days": cfg.window_days}
    feedback.add(store, {"target": "source", "target_id": str(source_id), "kind": "action",
                         "value": "keep", "context": ctx}, now=now)
    return {"id": source_id, "kept": True, **ctx}


def summary(store: Store, cfg: GradingConfig | None = None, *,
            now: datetime | None = None) -> dict[str, Any]:
    """Your grades' Sources section: the ones recommended for removal, the closest watched one
    otherwise (most downvotes, then fewest upvotes), and the kept ones with their dates."""
    cfg = cfg or GradingConfig()
    c = counts(store, cfg, now=now)
    labels = {s.id: s.label for s in library.list_sources(store)}
    live = [s for s in watched(store) if s.id in c and c[s.id]["down"] + c[s.id]["up"]]
    ranked = sorted(live, key=lambda s: (-c[s.id]["down"], c[s.id]["up"], s.id))
    closest = next((s for s in ranked if not recommends(c[s.id], cfg)), None)
    return {"window_days": cfg.window_days, "remove_after": cfg.remove_after,
            "recommended": to_remove(store, cfg, now=now),
            "closest": ({"id": closest.id, "label": closest.label,
                         "down": c[closest.id]["down"], "up": c[closest.id]["up"]}
                        if closest else None),
            "kept": [{"id": sid, "label": labels.get(sid, f"source {sid}"),
                      "at": v["kept"]["at"], "down": v["kept"]["down"], "up": v["kept"]["up"]}
                     for sid, v in sorted(c.items()) if v["kept"]]}
