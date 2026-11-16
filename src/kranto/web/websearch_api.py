"""Live web search over the loopback API, for the page (the research desk,
the editor, the pitch, evolve) and the ``kranto_search``/``kranto_fetch`` tools of ``kranto mcp``:
they ask Kranto, and never hold a search key.

| Method and path          | Does                                                             |
|--------------------------|------------------------------------------------------------------|
| GET /api/websearch       | ``q``, ``recency``, ``kind``, ``n``, ``backend``, ``caller``     |
| GET /api/websearch/fetch | ``url``, ``max_chars``: a page's text, through ``sources.HTTP``  |
| GET /api/setup/search    | the backend, its label, keys set (names), callers, this month   |
| POST /api/setup/search   | {provider, key?, replace?, keep_failed?}: test, then make it    |
|                          | live search's (``websearch.setup.choose``); used at once        |
| POST /api/setup/search/callers | {callers?, recent_weeks?}: each caller on or off         |

``recency``: 1w 2w 4w 12w 3mo 6mo 12mo; ``kind``: web, discussion (adds Hacker News), code
(GitHub), papers (arXiv); ``n``: 1 to 20; ``backend``: comma-separated names instead of the
configured ones; ``caller``: who asks (``scout``, ``cards``, ``editor``, ``research``,
``resolve``, ``pitch``, ``evolve``, or ``owner``), for the ledger and its switch.

The answer is ``websearch.Results.to_dict()``: ``backend`` null and ``note`` "no live search:
results are from model memory and may be stale" when nothing answered, never an error for a
backend that failed. A search costs what the backend charges (Exa's free mode nothing); it is
counted in ``api_spend`` with the ``caller`` named. Under the same token guard as every route.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import websearch
from ..config import SEARCH_CALLERS

MAX_FETCH_CHARS = 20_000


class WebSearchAPI:
    def __init__(self, app) -> None:
        self.app = app

    def searcher(self, caller: str | None) -> websearch.Searcher:
        return websearch.for_runtime(self.app.rt, caller=caller)

    def search(self, request: Request):
        q = request.query_params
        caller = q.get("caller") or None
        if caller is not None and caller not in SEARCH_CALLERS and caller != "owner":
            return JSONResponse({"error": f"caller must be one of {', '.join(SEARCH_CALLERS)} "
                                          "or owner"}, status_code=400)
        backends = tuple(b for b in (q.get("backend") or "").split(",") if b) or None
        try:
            n = int(q.get("n") or 10)
            results = self.searcher(None if caller == "owner" else caller).search(
                q.get("q") or "", recency=q.get("recency") or None,
                kind=q.get("kind") or "web", n=n, backends=backends)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(results.to_dict())

    def fetch(self, request: Request):
        q = request.query_params
        try:
            max_chars = max(200, min(int(q.get("max_chars") or 3000), MAX_FETCH_CHARS))
        except ValueError:
            return JSONResponse({"error": "max_chars must be a whole number"}, status_code=400)
        url = (q.get("url") or "").strip()
        if not url:
            return JSONResponse({"error": "url is required"}, status_code=400)
        return JSONResponse({"url": url, "text": self.searcher(None).fetch(url,
                                                                       max_chars=max_chars)})

    # -- the backend and the callers (Settings, Watching, Live search;) ----------------

    def state(self, request: Request):
        from ..websearch import setup as wsetup
        return JSONResponse(wsetup.detect(self.app.rt.cfg, self.app.rt.store))

    async def _body(self, request: Request):
        from .app import MAX_JSON_BYTES, _json_body
        body = await _json_body(request)
        if body is None:
            return None, JSONResponse({"error": f"expected a JSON object under "
                                                f"{MAX_JSON_BYTES} bytes"}, status_code=400)
        return body, None

    def _reload(self) -> None:
        """The running server takes the new search settings at once."""
        from dataclasses import replace

        from .. import config as config_mod
        from .. import websearch
        rt = self.app.rt
        rt.cfg = replace(rt.cfg, search=config_mod.load(rt.cfg.root, dotenv=False).search)
        websearch.configure(websearch.for_runtime(rt, caller="sources"))

    async def choose(self, request: Request):
        from starlette.concurrency import run_in_threadpool

        from .. import config as config_mod
        from .. import setup
        from ..websearch import setup as wsetup
        body, err = await self._body(request)
        if err:
            return err
        raw = body.get("key")
        key = str(raw) if raw not in (None, "") else None
        provider = str(body.get("provider") or "")
        from .. import preview
        if key is not None and preview.enabled(self.app.rt.cfg.root):
            return JSONResponse({"error": preview.NO_KEY_TEST}, status_code=409)
        try:
            result = await run_in_threadpool(
                wsetup.choose, self.app.rt.cfg.root, provider, key=key,
                keep_failed=body.get("keep_failed") is True)
        except (setup.SetupError, config_mod.ConfigError) as exc:
            return JSONResponse({"error": setup.scrub_key(str(exc), key or "")},
                                status_code=400)
        except OSError as exc:
            return JSONResponse({"error": setup.scrub_key(f"could not save: {exc}", key or "")},
                                status_code=500)
        if not result["ok"]:
            return JSONResponse({"error": setup.scrub_key(result["test"]["detail"], key or ""),
                                 "test": result["test"]}, status_code=400)
        self._reload()
        return JSONResponse({**result, "state": wsetup.detect(self.app.rt.cfg,
                                                              self.app.rt.store)})

    async def callers(self, request: Request):
        from .. import setup
        from ..websearch import setup as wsetup
        body, err = await self._body(request)
        if err:
            return err
        callers = body.get("callers") or {}
        weeks = body.get("recent_weeks")
        if not isinstance(callers, dict) or (weeks is not None and (
                isinstance(weeks, bool) or not isinstance(weeks, int))):
            return JSONResponse({"error": "callers maps a caller to on or off; recent_weeks "
                                          "is a whole number of weeks"}, status_code=400)
        try:
            wsetup.set_callers(self.app.rt.cfg.root, callers, weeks)
        except setup.SetupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except OSError as exc:
            return JSONResponse({"error": f"could not save: {exc}"}, status_code=500)
        self._reload()
        return JSONResponse(wsetup.detect(self.app.rt.cfg, self.app.rt.store))

    def routes(self) -> list[Route]:
        return [Route("/api/websearch", self.search),
                Route("/api/websearch/fetch", self.fetch),
                Route("/api/setup/search", self.state),
                Route("/api/setup/search", self.choose, methods=["POST"]),
                Route("/api/setup/search/callers", self.callers, methods=["POST"])]
