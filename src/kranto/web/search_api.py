"""One search for Kranto UI's command palette (UI-v4.md 2.4).

| Method and path   | Does                                                             |
|-------------------|------------------------------------------------------------------|
| GET /api/search   | ``q``: topics, sources and observations that match, in one list |

- **Topics** match on their name or description, as typed (case-insensitive), active or
  paused.
- **Sources** match on their label or kind, whatever their review state; ``status`` says
  which (``approved``, ``proposed``, ``retired``...).
- **Observations** come from the library's own search (words and meaning, fused; the
  same cutoff below the best that /library applies). A hit the embedder rates off topic
  is kept only when its title or summary holds the query's words, so a short word does
  not fill the palette with near misses.

Each result is ``{kind, id, title, detail, score}``; topics first, then sources, then
observations best first. ``k`` caps the observations (default 8, at most 50). No model
call: the query is embedded by the library's local embedder. A GET, under the same guard
as every route (an allowed Host).
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import library

TOPICS_SHOWN = 5
SOURCES_SHOWN = 8
MAX_QUERY = 200


def _words_in(query: str, *texts: str | None) -> bool:
    hay = " ".join(t or "" for t in texts).lower()
    return all(w in hay for w in query.lower().split())


class SearchAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def search(self, request: Request):
        from .app import _count

        query = (request.query_params.get("q") or "").strip()[:MAX_QUERY]
        k = _count(request.query_params.get("k"), 8, 50)
        if not query:
            return JSONResponse({"query": "", "results": []})
        store = self.rt.store
        out: list[dict] = []
        for topic, status, _ in library.topics_with_status(store):
            if _words_in(query, topic.name, topic.description):
                out.append({"kind": "topic", "id": topic.id, "title": topic.name,
                            "detail": status, "score": None})
        out = out[:TOPICS_SHOWN]
        sources = [s for s in library.list_sources(store) if _words_in(query, s.label, s.kind)]
        out += [{"kind": "source", "id": s.id, "title": s.label,
                 "detail": f"{s.kind} · {s.status}", "score": None}
                for s in sources[:SOURCES_SHOWN]]
        for row, hit in self.app._semantic(query, library.ObservationFilter(), k=k,
                                           cutoff=True):
            if hit.weak and not _words_in(query, row.get("title"), row.get("summary")):
                continue
            out.append({"kind": "observation", "id": row["id"],
                        "title": row.get("title") or (row.get("summary") or "")[:120],
                        "detail": " · ".join(x for x in (row.get("source_label"), row.get("kind"),
                                                         (row.get("created_at") or "")[:10]) if x),
                        "score": round(hit.score, 4)})
        return JSONResponse({"query": query, "results": out})

    def routes(self) -> list[Route]:
        return [Route("/api/search", self.search)]
