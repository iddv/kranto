"""The reads a cub narrowed to some topics may see: the owner narrowed
``library`` at install, so ``grants.reads_topics`` names the topics; every read that can show
something of another topic is filtered to these, and an object outside them is not found
(-32006). A cub that was not narrowed reads as a first-party feature does."""

from __future__ import annotations

from .. import api


def _missing(what: str) -> api.ReadError:
    return api.ReadError(f"no such {what}", 404)


def _topic_sources(store, topics: set[int]) -> set[int]:
    if not topics:
        return set()
    marks = ",".join("?" * len(topics))
    return {r["source_id"] for r in store.query(
        f"SELECT source_id FROM topic_links WHERE topic_id IN ({marks})", tuple(topics))}


def _obs_ok(store, obs_id, sources: set[int]) -> bool:
    r = store.query_one("SELECT source_id FROM observations WHERE id = ?", (int(obs_id),))
    return r is not None and r["source_id"] in sources


def _idea_topics(store, idea_id: int) -> set[int]:
    from ...web.ideas_api import read_ideas
    card = next((r for r in read_ideas(store) if r["id"] == idea_id), None)
    return {t["id"] for t in (card or {}).get("topics") or [] if t.get("id") is not None}


def _per_topic(ctx, name: str, params: dict, topics: set[int], key: str, sort, limit: int
               ) -> dict:
    rows: dict = {}
    for t in sorted(topics):
        for row in api.call(ctx, name, {**params, "topic_id": t})[key]:
            rows[row["id"]] = row
    out = sorted(rows.values(), key=sort)[:limit]
    return {key: out}


def read(host, name: str, params: dict) -> dict:
    ctx = host.feature_context()
    narrowed = host.cub.grants.reads_topics
    if narrowed is None:
        return api.call(ctx, name, params)
    allowed = {int(t) for t in narrowed}
    store = host.store
    if params.get("topic_id") is not None:
        try:
            asked = int(params["topic_id"])
        except (TypeError, ValueError):
            raise api.ReadError("topic_id is a whole number") from None
        if asked not in allowed:
            raise _missing("topic")
    if name == "topics.list":
        out = api.call(ctx, name, params)
        return {"topics": [t for t in out["topics"] if t["id"] in allowed]}
    if name in ("library.observations", "library.search", "briefs.list") \
            and params.get("topic_id") is None:
        key = "briefs" if name == "briefs.list" else "observations"
        default = {"library.observations": 40, "library.search": 10, "briefs.list": 20}[name]
        limit = int(params.get("limit") or default)
        sort = (lambda r: -r.get("score", 0)) if name == "library.search" else \
            (lambda r: -int(r["id"]))
        out = _per_topic(ctx, name, params, allowed, key, sort, limit)
        if name == "library.observations":
            out["total"] = len(out["observations"])
        return out
    if name in ("library.observations", "library.search", "briefs.list"):
        return api.call(ctx, name, params)
    if name == "briefs.get":
        out = api.call(ctx, name, params)
        if out.get("topic_id") not in allowed:
            raise _missing("brief")
        return out
    if name == "themes.list":
        out = api.call(ctx, name, params)
        out["themes"] = [t for t in out["themes"] if {int(k) for k in t["topics"]
                                                      if str(k).isdigit()} & allowed]
        return out
    if name == "themes.get":
        out = api.call(ctx, name, params)
        if not {int(k) for k in out["topics"] if str(k).isdigit()} & allowed:
            raise _missing("theme")
        sources = _topic_sources(store, allowed)
        out["observation_ids"] = [i for i in out["observation_ids"]
                                  if _obs_ok(store, i, sources)]
        return out
    if name == "ideas.list":
        out = api.call(ctx, name, params)
        out["ideas"] = [i for i in out["ideas"] if _idea_topics(store, i["id"]) & allowed]
        return out
    if name in ("ideas.get", "cards.get"):
        out = api.call(ctx, name, params)
        if not _idea_topics(store, out["id"]) & allowed:
            raise _missing("idea")
        return out
    if name == "objects.get":
        kind = params.get("kind")
        if kind == "observation":
            if not _obs_ok(store, params.get("id"), _topic_sources(store, allowed)):
                raise _missing("observation")
            return api.call(ctx, name, params)
        inner = {"idea": "ideas.get", "theme": "themes.get", "brief": "briefs.get"}.get(kind)
        if kind in ("trend", *api.LOOP_KINDS):
            raise _missing(str(kind))       # not narrowed by topic yet: a narrowed cub sees none
        if inner is None:
            return api.call(ctx, name, params)
        return {"kind": kind, "object": read(host, inner, {"id": params.get("id")})}
    return api.call(ctx, name, params)
