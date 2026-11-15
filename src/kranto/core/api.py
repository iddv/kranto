"""The read surface, v1 (MR-RESEARCH): the public contract of reads.

Small on purpose: nine reads, named and frozen, served in-process (``call``) and over HTTP
(``GET /api/read/<name>``). A feature or a mod may call a read only when its manifest grants
the read's family (``reads: [topics, library]``). Text from the library comes back fenced
and labelled with its origin (``[obs 8231]``), as the citation labels are, because it
is strangers' text and must reach a prompt as data.

A feature adds reads of its own (News adds ``briefs.list`` and ``briefs.get``) through its
manifest's ``api``; the core serves them under their family the same way. Everything else a
feature owns stays internal, not on this surface.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from ..rowsafe import readable
from ..store import Store, iso, utcnow

READ_FAMILIES = ("topics", "library", "themes", "ideas", "briefs", "events", "objects", "spend")
V1 = ("topics.list", "library.observations", "library.search", "themes.list", "themes.get",
      "ideas.list", "ideas.get", "briefs.list", "briefs.get", "objects.get", "events.read",
      "spend.mine", "cards.get")
MAX_LIMIT = 100
SUMMARY_CHARS = 700


class ReadError(ValueError):
    def __init__(self, msg: str, code: int = 400) -> None:
        super().__init__(msg)
        self.code = code


def fence(text: str | None) -> str:
    """Strangers' text as it may sit inside a ``<<<`` fence."""
    from ..websearch import fenced
    return fenced(" ".join(str(text or "").split()))


def _int(params: dict, key: str, default: int | None = None, lo: int = 0,
         hi: int | None = None) -> int | None:
    v = params.get(key, default)
    if v is None:
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise ReadError(f"{key} is a whole number") from None
    if v < lo or hi is not None and v > hi:
        raise ReadError(f"{key} is from {lo} to {hi}")
    return v


# -- the core's reads ---------------------------------------------------------------------------


def topics_list(ctx, params: dict) -> dict:
    from ..library import topics_with_status
    from ..progress import first_read_at
    # first_read_at (additive): when the topic's first read ended, null before;
    # what News' first brief waits for
    rows = [{"id": t.id, "name": t.name, "description": t.description, "status": status,
             "first_read_at": first_read_at(ctx.store, t.id)}
            for t, status, _ in topics_with_status(ctx.store) if t.kind == "user"]
    return {"topics": rows}


def _obs_line(r) -> dict:
    date = (r["item_published_at"] or r["created_at"] or "")[:10]
    title = r["title"] or (r["summary"] or "")[:90]
    return {"id": r["id"], "label": f"obs {r['id']}", "date": date, "title": fence(title),
            "source": r["source_label"], "url": r["source_url"],
            "summary": fence((r["summary"] or "")[:SUMMARY_CHARS]),
            "why": fence((r["why_it_matters"] or "")[:300]), "signal": r["signal"],
            "created_at": r["created_at"]}


def library_observations(ctx, params: dict) -> dict:
    from ..library import ObservationFilter, find_observations
    topic = _int(params, "topic_id")
    limit = _int(params, "limit", 40, 1, MAX_LIMIT)
    since = params.get("since")
    rows, total = find_observations(
        ctx.store, ObservationFilter(topic_id=topic, since=str(since) if since else None,
                                     kind="!beat" if params.get("signal_only") else None),
        sort=str(params.get("sort") or "new"), limit=limit)
    # a row that cannot be read is left out of a cub's read (its schema has none; RCA A3)
    return {"observations": readable(rows, _obs_line, "observation"), "total": total}


def library_search(ctx, params: dict) -> dict:
    from ..library import observations_by_id
    from ..search import search
    q = str(params.get("q") or "").strip()
    if not q:
        raise ReadError("q is the query")
    k = _int(params, "limit", 10, 1, MAX_LIMIT) or 10
    since = str(params.get("since") or "")[:10]
    if ctx.index is None or ctx.embedder is None:
        # no embedder here (a command, a job outside the server): the words, by full text
        return _library_words(ctx, q, k, _int(params, "topic_id"), since)
    hits = search(ctx.index, ctx.embedder, q[:300], k=k)
    rows: dict[int, Any] = observations_by_id(ctx.store, [h.observation_id for h in hits])
    topic = _int(params, "topic_id")
    keep = None
    if topic is not None:
        keep = {r["source_id"] for r in ctx.store.query(
            "SELECT source_id FROM topic_links WHERE topic_id = ?", (topic,))}
    pairs = [(rows[h.observation_id], h) for h in hits if h.observation_id in rows
             and (keep is None or rows[h.observation_id]["source_id"] in keep)
             and (not since or (rows[h.observation_id]["item_published_at"]
                                or rows[h.observation_id]["created_at"] or "") >= since)]
    return {"observations": readable(
        pairs, lambda x: {**_obs_line(x[0]), "score": round(float(x[1].score), 4)},
        "observation", ident=lambda x: x[0]["id"]), "match": "meaning"}


def _library_words(ctx, q: str, k: int, topic: int | None, since: str) -> dict:
    """``library.search`` by full text (any word of ``q``), best first."""
    from ..library import observations_by_id
    from ..search import match_expression
    expr = match_expression(q[:300])
    if expr is None:
        return {"observations": [], "match": "words"}
    ids = [r["rowid"] for r in ctx.store.query(
        "SELECT rowid FROM observations_fts WHERE observations_fts MATCH ? ORDER BY rank "
        "LIMIT ?", (expr, k * 4))]
    rows: dict[int, Any] = observations_by_id(ctx.store, ids)
    keep = None
    if topic is not None:
        keep = {r["source_id"] for r in ctx.store.query(
            "SELECT source_id FROM topic_links WHERE topic_id = ?", (topic,))}
    picked = [rows[i] for i in ids if i in rows
              and (keep is None or rows[i]["source_id"] in keep)
              and (not since or (rows[i]["item_published_at"] or rows[i]["created_at"]
                                 or "") >= since)][:k]
    return {"observations": readable(picked, _obs_line, "observation"), "match": "words"}


def _clusters(ctx) -> tuple[dict | None, list[dict]]:
    from ..map import read as map_read
    snap = map_read.latest(ctx.store)
    if snap is None:
        return None, []
    return dict(snap), map_read.clusters(ctx.store, snap["id"])


def _theme(c: dict) -> dict:
    return {"id": c["lineage_id"], "name": c["label"], "size": c["size"],
            "share": round(float(c["share"]), 5), "keywords": c["keywords"][:8],
            "rising": bool(c["rising"]), "cross_source": c["cross_source"],
            "topics": {str(k): v for k, v in (c.get("topic_mix") or {}).items()}}


def themes_list(ctx, params: dict) -> dict:
    snap, rows = _clusters(ctx)
    topic = _int(params, "topic_id")
    out = readable(rows, _theme, "theme", ident=lambda c: c.get("lineage_id"))
    if topic is not None:
        out = [t for t in out if str(topic) in t["topics"]]
    if params.get("rising"):
        out = [t for t in out if t["rising"]]
    return {"snapshot_at": snap["created_at"] if snap else None, "themes": out}


def themes_get(ctx, params: dict) -> dict:
    from ..map import read as map_read
    lineage = str(params.get("id") or "")
    snap, rows = _clusters(ctx)
    c = next((c for c in rows if c["lineage_id"] == lineage), None)
    if c is None:
        raise ReadError(f"no theme {lineage!r} on the latest map", 404)
    return {**_theme(c), "observation_ids": list(map_read.member_ids(ctx.store, snap["id"],
                                                                     c["cluster"]))[:200]}


EDITOR_CLASSES = ("nominee", "candidate", "note", "reject")


def _editor(r: dict) -> dict | None:
    """The weekly editor's verdict on a card, from its latest ``editor`` outcome: the class
    (``nominee``, ``candidate``, ``note``, ``reject``, or a longer class such as ``repo idea
    for <project>``), the ISO week and the why, fenced (the editor's text is a model's)."""
    e = r.get("editor")
    if not e:
        return None
    detail = e.get("detail") or {}
    return {"class": str(e.get("value") or "").lower(), "week": detail.get("week"),
            "why": fence(detail.get("why")) if detail.get("why") else None}


def _outcome(r: dict) -> dict | None:
    """A card's latest outcome of any kind: ``{kind, value, at}`` (the value fenced: a
    research verdict is a model's word)."""
    o = r.get("outcome")
    return {"kind": o["kind"], "value": fence(o["value"]), "at": o["created_at"]} if o else None


def _built(r: dict) -> dict | None:
    """What the loop made of the card (``outcomes.built``): ``{state, repo, url}`` or None."""
    b = r.get("built")
    return {"state": b["state"], "repo": b.get("repo"), "url": b.get("url")} if b else None


def _idea(r: dict) -> dict:
    return {"id": r["id"], "title": fence(r["title"]), "one_liner": fence(r.get("one_liner")),
            "status": r["status"], "created_at": r["created_at"],
            "evidence_ids": [e.get("id") for e in r.get("evidence") or [] if e.get("id")],
            "editor": _editor(r), "outcome": _outcome(r), "built": _built(r)}


def ideas_for_stories(ctx, params: dict) -> dict:
    """Each news story's idea and theme (``news_ideas.story_ideas``): params
    ``brief_id`` and ``items`` (each ``{observation_ids}``, in the brief's order). Chosen by rule
    from stored rows, never by a model: ``{stories: {n: {idea, theme, no_theme, story}}}``."""
    from ..news_ideas import story_ideas
    bid = int(_int(params, "brief_id", 0, 0, 10**9) or 0)
    items = params.get("items")
    if not isinstance(items, list) or len(items) > 50:  # stored-shape: a read's params, checked
        raise ReadError("items is a list of at most 50 stories")
    clean = [{"observation_ids": [i for i in (it.get("observation_ids") or [])
                                  if isinstance(i, int) and not isinstance(i, bool)][:200]}
             if isinstance(it, dict) else {} for it in items]
    return {"stories": story_ideas(ctx.store, bid, clean)}


def ideas_list(ctx, params: dict) -> dict:
    """The cards, newest first. ``editor_class`` (0.5, additive): only the cards whose latest
    weekly-editor verdict is that class (the toot cub reads the nominees)."""
    from ..web.ideas_api import read_ideas
    since = params.get("since")
    limit = _int(params, "limit", 50, 1, MAX_LIMIT)
    want = params.get("editor_class")
    if want is not None and want not in EDITOR_CLASSES:
        raise ReadError(f"editor_class is one of {', '.join(EDITOR_CLASSES)}")
    # a card that cannot be read is not handed to a cub (its schema has no such row; RCA A3)
    rows = [r for r in read_ideas(ctx.store) if not r.get("unreadable")
            and (not since or r["created_at"] > str(since))]
    rows.sort(key=lambda r: r["id"], reverse=True)
    out = readable(rows, _idea, "idea")
    if want is not None:
        out = [i for i in out if i["editor"] and i["editor"]["class"] == want]
    return {"ideas": out[:limit]}


def ideas_get(ctx, params: dict) -> dict:
    from ..web.ideas_api import read_ideas
    ident = _int(params, "id")
    r = next((r for r in read_ideas(ctx.store) if r["id"] == ident
              and not r.get("unreadable")), None)
    if r is None:
        raise ReadError(f"no idea {ident}", 404)
    return _idea(r)


def cards_get(ctx, params: dict) -> dict:
    """One idea card with what a post about it needs (additive to v1): its title,
    one line, thesis, insight and why it was chosen, its topic, and its sources with their
    links (the card's citations, numbered as the card numbers them). Every text is fenced:
    a card's words are a model's."""
    from ..web.ideas_api import read_ideas
    ident = _int(params, "id")
    r = next((r for r in read_ideas(ctx.store) if r["id"] == ident
              and not r.get("unreadable")), None)
    if r is None:
        raise ReadError(f"no card {ident}", 404)
    sources: list[dict] = []
    seen: set[str] = set()
    for c in r.get("citations") or []:
        url = c.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"n": len(sources) + 1, "url": url, "claim": fence(c.get("claim")),
                        "source": fence(c.get("source")), "date": c.get("date")})
    topic = r.get("topic") or {}
    return {"id": r["id"], "title": fence(r["title"]), "one_liner": fence(r.get("one_liner")),
            "thesis": fence(r.get("thesis")), "insight": fence(r.get("insight")),
            "why": fence(r.get("why_selected")),
            "topic": {"id": topic.get("id"), "name": fence(topic.get("name"))} if topic
            else None, "created_at": r["created_at"], "sources": sources}


OBJECT_KINDS = ("observation", "idea", "theme", "brief", "trend", "build", "product", "project")
LOOP_KINDS = ("build", "product", "project")


def _trend(ctx, key: str) -> dict:
    """A followed trend of the radar, as its list says it, its title fenced."""
    from . import registry
    try:
        from ..features.radar import api as radar_api
        from ..features.radar import data as radar_data
        rctx = registry.context(ctx.rt, registry.by_id("radar"))
    except (ImportError, LookupError, StopIteration):
        raise ReadError("no trend radar here", 404) from None
    t = radar_data.trend(rctx, key)
    if t is None or t.get("state") == "dismissed":
        raise ReadError(f"no trend {key!r}", 404)
    s = radar_api.summary_of(rctx, t)
    return {"key": s["key"], "title": fence(s["title"]), "kind": s["kind"],
            "topic_id": s["topic_id"], "topic": s["topic"], "stage": s["stage"],
            "since": s["since"], "gap": s["gap"], "line": fence(s["line"])}


def objects_trends(ctx, params: dict) -> dict:
    """The radar's followed trends as their list says them (stage, since, the attention gap),
    and with ``key`` that trend's last chain: its links and candidate companies, every text
    fenced (a model wrote them)."""
    from . import registry
    try:
        from ..features.radar import api as radar_api
        from ..features.radar import data as radar_data
        rctx = registry.context(ctx.rt, registry.by_id("radar"))
    except (ImportError, LookupError, StopIteration):
        return {"trends": [], "note": "no trend radar here"}
    key = str(params.get("key") or "")
    out = []
    for t in radar_data.trends(rctx):
        if key and t.get("key") != key:
            continue
        s = radar_api.summary_of(rctx, t)
        st: dict[str, Any] = radar_data.last_stage(rctx, s["key"]) or {}
        raw = st.get("scores")
        sc: dict[str, Any] = raw if isinstance(raw, dict) else {}
        nums: dict[str, float] = {k: float(v) for k in ("L", "A", "A_pct")
                                  if isinstance(v := sc.get(k), int | float)
                                  and not isinstance(v, bool)}
        row = {"key": s["key"], "title": fence(s["title"]), "kind": s["kind"],
               "topic": s["topic"], "topic_id": s.get("topic_id"), "stage": s["stage"],
               "since": s["since"], "gap": s["gap"], "line": fence(s["line"]),
               "month": st.get("month"),
               # the measured axes: leading L, attention A, its percentile; crowded
               # as the radar's own rule says it (A's percentile high and the counts big)
               "scores": {**nums, "crowded": bool(nums.get("A_pct", 0.0) >= 0.8
                                                  and sc.get("big") is True)}}
        if key:
            ch: dict[str, Any] = radar_data.last_chain(rctx, key) or {}
            got = ch.get("chain")
            chain: dict[str, Any] = got if isinstance(got, dict) else {}
            row["chain"] = {
                "made": str(ch.get("created_at") or "")[:10],
                "links": [fence(f"{x.get('from')} → {x.get('to')}")
                          for x in chain.get("links") or [] if isinstance(x, dict)][:8],
                "candidates": [{"name": fence(str(x.get("name") or "")),
                                "role": fence(str(x.get("role") or ""))}
                               for x in chain.get("candidates") or []
                               if isinstance(x, dict)][:10]}
        out.append(row)
    return {"trends": out}


def _loop_object(ctx, kind: str, key: str) -> dict:
    """A build, a product or a project: not available since builds left Kranto (CUT,). The kinds
    stay in ``OBJECT_KINDS`` so a cub written to v1 still asks; it is answered
    "not found" (its SDK's none), and the page is never asked (its ``object_record`` left)."""
    raise ReadError(f"no {kind} {key!r}: a {kind} is not available (builds are not part of "
                    "Kranto any more)", 404)


def objects_get(ctx, params: dict) -> dict:
    """One object by kind and id (``OBJECT_KINDS``): an observation, an idea card, a theme, a
    brief; a trend (``id``: its key). A build, a product or a project is not available any
    more (``_loop_object``)."""
    kind = str(params.get("kind") or "")
    if kind == "trend":
        return {"kind": kind, "object": _trend(ctx, str(params.get("id") or ""))}
    if kind in LOOP_KINDS:
        key = str(params.get("id") or "")
        if not key or len(key) > 60:
            raise ReadError(f"a {kind}'s id is the loop's (i… or p…)")
        return {"kind": kind, "object": _loop_object(ctx, kind, key)}
    if kind == "observation":
        from ..library import get_observation
        r = get_observation(ctx.store, _int(params, "id"))
        if r is None:
            raise ReadError("no such observation", 404)
        return {"kind": kind, "object": _obs_line(r)}
    if kind == "idea":
        return {"kind": kind, "object": ideas_get(ctx, params)}
    if kind == "theme":
        return {"kind": kind, "object": themes_get(ctx, params)}
    if kind == "brief":
        return {"kind": kind, "object": call(ctx, "briefs.get", params)}
    raise ReadError(f"kind is one of {', '.join(OBJECT_KINDS)}")


def events_read(ctx, params: dict) -> dict:
    from . import events
    kinds = [k for k in str(params.get("kinds") or params.get("kind") or "").split(",") if k]
    return {"events": events.read(ctx.store, since=_int(params, "since", 0) or 0,
                                  kinds=kinds or None, min_trust=params.get("min_trust"),
                                  limit=_int(params, "limit", 100, 1, events.READ_LIMIT))}


def spend_mine(ctx, params: dict) -> dict:
    if getattr(ctx, "feature", None) is None:   # the core's own reader (GET /api/read/...)
        raise ReadError("spend.mine is a feature's own spend: ask it as a feature")
    return {"feature": ctx.feature.id, **spend_of(ctx.store, ctx.feature)}


def spend_of(store: Store, feature, now: datetime | None = None) -> dict:
    """The feature's model spend this month and today, by its declared purposes."""
    from ..store import month_start
    now = now or utcnow()
    purposes = list(feature.permissions.model.purposes)
    if not purposes:
        return {"month_usd": 0.0, "today_usd": 0.0, "calls": 0, "equiv_usd": 0.0}
    marks = ",".join("?" * len(purposes))
    m = store.query_one(
        f"SELECT COALESCE(SUM(cost_usd), 0) AS usd, COALESCE(SUM(equiv_usd), 0) AS eq, "
        f"COUNT(*) AS n FROM llm_calls WHERE purpose IN ({marks}) AND created_at >= ?",
        (*purposes, iso(month_start(now))))
    d = store.query_one(
        f"SELECT COALESCE(SUM(cost_usd), 0) AS usd FROM llm_calls WHERE purpose IN ({marks}) "
        "AND created_at >= ?", (*purposes, iso(now - timedelta(days=1))))
    return {"month_usd": round(float(m["usd"]), 6), "today_usd": round(float(d["usd"]), 6),
            "calls": int(m["n"]), "equiv_usd": round(float(m["eq"]), 6)}


CORE: dict[str, tuple[str, Callable]] = {
    "topics.list": ("topics", topics_list),
    "library.observations": ("library", library_observations),
    "library.search": ("library", library_search),
    "themes.list": ("themes", themes_list),
    "themes.get": ("themes", themes_get),
    "ideas.list": ("ideas", ideas_list),
    "ideas.get": ("ideas", ideas_get),
    "ideas.for_stories": ("ideas", ideas_for_stories),
    "cards.get": ("ideas", cards_get),
    "objects.get": ("objects", objects_get),
    "objects.trends": ("objects", objects_trends),
    "events.read": ("events", events_read),
    "spend.mine": ("spend", spend_mine),
}


def reads() -> dict[str, tuple[str, str, Callable]]:
    """Every read: name -> (family, provider, fn). A feature's ``api`` entry named
    ``<family>.<verb>`` with a v1 family is on the surface; the rest is the feature's own
    page reads (served at ``/api/<feature>/<name>``, not to other features)."""
    from ..features import FEATURES
    out = {name: (fam, "core", fn) for name, (fam, fn) in CORE.items()}
    for f in FEATURES:
        for name, fn in f.api.items():
            fam = name.split(".", 1)[0]
            if fam in READ_FAMILIES and name in V1:
                out[name] = (fam, f.id, fn)
    return out


def call(ctx, name: str, params: dict | None = None) -> dict:
    """Run a read as ``ctx``'s feature: refused unless its manifest grants the family."""
    entry = reads().get(name)
    if entry is None:
        raise ReadError(f"no read {name!r} (v1: {', '.join(V1)})", 404)
    family, provider, fn = entry
    if ctx.feature is not None and family not in ctx.feature.permissions.reads \
            and provider != ctx.feature.id:
        raise ReadError(f"{ctx.feature.id} may not read {family}: its manifest does not "
                        "list it", 403)
    if provider != "core" and (ctx.feature is None or ctx.feature.id != provider):
        # a feature's read runs as that feature
        from . import registry
        ctx = registry.context(ctx.rt, registry.by_id(provider))
    out = fn(ctx, dict(params or {}))
    json.dumps(out)                     # a read answers JSON, or it is a bug here
    return out
