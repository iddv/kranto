"""The JSON API served by ``python -m kranto serve``, and the host of Kranto UI (``/brb/``).

The UI is Kranto's (the page's pages, mounted at ``/brb/``); the server's old page
addresses redirect there. The server alone is not a supported way to run (D5): those
addresses show how to install Kranto instead. The only pages rendered here are the
connection sign-in pages (``web/sources_api.py``).

The server binds to localhost by default, and reads need no token, so what keeps
another site open in the operator's browser from reading or driving it is
``GuardMiddleware``:

- The ``Host`` header must name this server (an allowlist). Without it, a page
  on a domain that re-resolves to 127.0.0.1 (DNS rebinding) is same-origin
  with the UI and can read and post anything.
- A state-changing request must carry an ``Origin`` (or ``Referer``) equal to
  the allowed host it was sent to; one that carries neither is refused. A write
  with a current token in ``Authorization: Bearer`` is exempt: the check is
  against pages riding the browser's cookie, and a browser never sends that
  header by itself.
- Every response forbids framing (clickjacking) and sets a content policy.
- A state-changing request must carry a kranto token (``web/auth.py``, OI): the page's
  session cookie, or ``Authorization: Bearer``. The token says who acts.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from jinja2 import Environment, PackageLoader, select_autoescape
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__, grades, library, notify, preview, rowsafe, search
from ..config import builds_on
from ..core.cubs.settings import developer as cubs_developer
from ..importers import ARCHIVE, theme_member_ids
from ..intern import override_lifted
from ..links import KRANTO, Links
from ..map import read as map_read
from ..progress import library_progress
from ..runtime import Runtime
from ..scheduler import Scheduler
from ..sources import safe_url
from ..store import utcnow
from ..stored.cards import SynthesisInputIds
from ..stored.observations import Tags
from ..stored.runs import summary_of
from ..stored.sources import Validation as StoredValidation
from ..tick import current_progress
from ..update import check as update_check
from . import brb as brb_mod
from .jobs import Jobs
from .types import HOST_API_VERSION

PAGE_SIZE = 50
# Search results: at most this many (after the cut-off), this many per page.
SEARCH_MAX = 100
SEARCH_PAGE_SIZE = 20
# Rollups shown above the observations on a library search.
ROLLUPS_ON_LIBRARY = 5
# How many nearest observations a search compares to say whether the library covers it at all
NEAREST = 5
STATIC_DIR = Path(__file__).parent / "static"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_JSON_BYTES = 64_000
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        # form-action: github.com too, for the one form the page posts there: the manifest
        # that creates Kranto's own GitHub App (the page's Settings › Publishing › GitHub,
        #); img-src https: for a News article's picture from its source, loaded
        # from the outlet by the reader's browser (the owner's D3 of 2026-10-23; no referrer
        # leaves: Referrer-Policy is same-origin)
        "img-src 'self' data: https:; object-src 'none'; base-uri 'none'; "
        "form-action 'self' https://github.com; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def _hostname(netloc: str) -> str:
    """The host part of a Host header or URL netloc, lowercased, without port."""
    try:
        return (urlparse(f"//{netloc}").hostname or "").lower()
    except ValueError:
        return ""


class GuardMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_hosts: frozenset[str], auth=None) -> None:
        super().__init__(app)
        self.allowed_hosts = allowed_hosts
        self.auth = auth

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host", "")
        if _hostname(host) not in self.allowed_hosts:
            return self._secure(Response("unknown host", status_code=400))
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            if urlparse(origin).netloc.lower() != host.lower() and not self._bearer(request):
                return self._secure(Response("cross-origin request refused", status_code=403))
            if request.headers.get("content-type", "").startswith("multipart/"):
                return self._secure(Response("multipart bodies are not accepted",
                                             status_code=415))
            if self.auth is not None:
                refused = self.auth.check(request)
                if refused is not None:
                    return self._secure(refused)
        elif self.auth is not None and self.auth.owner_read(request.url.path):
            refused = self.auth.check_read(request)           # a trace: the owner's only
            if refused is not None:
                return self._secure(refused)
        return self._secure(await call_next(request))

    def _bearer(self, request: Request) -> bool:
        """Whether a write carries a current kranto token in ``Authorization: Bearer``. The
        Origin check stops another site's page from riding the browser's cookie; a browser
        never adds this header by itself (a page can't set it cross-site without a CORS
        preflight, which this server never grants), so such a write needs no Origin."""
        if self.auth is None:
            return False
        ident, _ = self.auth.identify(request)
        return bool(ident) and ident.get("via") == "bearer"

    @staticmethod
    def _secure(response: Response) -> Response:
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class ErrorAnswerMiddleware:
    """A request that raised answers Kranto's error JSON or page (``App.error_answer``), and the
    exception stops here: it was logged once by its id, so the server does not log it again on
    every request (Starlette's own error middleware raises it on to the server)."""

    def __init__(self, app, answer) -> None:
        self.app = app
        self.answer = answer

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watch(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watch)
        except Exception as exc:  # noqa: BLE001 - every error answers as Kranto, by its id
            if started:              # a stream that broke midway: kept, nothing more to say
                rowsafe.note(exc, "stream", kind="response")
                return
            await self.answer(Request(scope), exc)(scope, receive, send)


# SQLite integers are 64-bit; a larger value raised OverflowError (a 500) when bound.
_INT_LIMIT = 2**62


def _int(value, default=None):
    try:
        n = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
    return n if n is None or abs(n) < _INT_LIMIT else default


def path_id(value: object) -> int:
    """A path's id (``/api/topics/{id}``), or -1 when it is not one (answered as not found):
    ``_int(value, -1)``, typed for the strict modules."""
    try:
        n = int(str(value))
    except ValueError:
        return -1
    return n if abs(n) < _INT_LIMIT else -1


def _count(value, default: int, maximum: int) -> int:
    """A row count from a query parameter, clamped to 1..maximum."""
    return max(1, min(_int(value, default), maximum))


async def _json_body(request: Request, limit: int = MAX_JSON_BYTES):
    """The request's JSON object, or None if it is larger than ``limit`` bytes or not an
    object."""
    declared = _int(request.headers.get("content-length"))
    if declared is not None and declared > limit:
        return None
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _float(value, default=None):
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def cited_by(store, obs_id: int) -> dict:
    """What cites an observation: the cards (``idea_citations``, one indexed
    lookup) and the News briefs whose items name it (a scan of the briefs' JSON: few rows)."""
    from ..ideate.cards import cited_by as cards_citing
    briefs = [int(r["id"]) for r in store.query(
        "SELECT b.id FROM news_briefs b WHERE EXISTS (SELECT 1 FROM json_each(b.items) it, "
        "json_each(it.value, '$.observation_ids') o WHERE it.type = 'object' AND o.value = ?) "
        "ORDER BY b.id DESC", (int(obs_id),))]
    return {"ideas": cards_citing(store, obs_id), "briefs": briefs}


def _row(r) -> dict:
    d = dict(r)
    if "tags" in d and isinstance(d["tags"], str):
        d["tags"] = Tags.load(d["tags"]).items
    return d


def _rollup(r) -> dict:
    d = dict(r)
    d.pop("centroid", None)
    for key in ("source_mix", "platform_mix", "topic_mix", "kind_counts", "keywords", "urls"):
        d[key] = json.loads(d[key])
    d["label"] = d["name"] or ", ".join(d["keywords"][:3]) or f"rollup {d['id']}"
    return d


def _retention_line(cfg) -> str:
    r = cfg.retention
    base = f"{r.default_days:g} days" if r.default_days > 0 else "forever"
    kinds = ", ".join(f"{k} {v:g} days" if v > 0 else f"{k} forever"
                      for k, v in sorted(r.by_kind.items()))
    return base + (f"; {kinds}" if kinds else "")


def _moving_key(c: dict) -> tuple:
    """Rising first, then other bursts, then by q-value, then by the older share excess."""
    m = c["movement"] or {}
    q, excess = m.get("q_value"), m.get("excess")
    return (not c.get("rising"), m.get("burst") != 1, q if q is not None else 2.0,
            -(excess if excess is not None else -1))


class App:
    def __init__(self, rt: Runtime, scheduler: Scheduler | None = None) -> None:
        self.rt = rt
        self.scheduler = scheduler
        self.brb = brb_mod.Brb("off")
        # model-backed work a request starts and the page polls, kept across a restart
        self.jobs = Jobs(rt.cfg.data_dir / "jobs", store=rt.store)
        self._map_cache: tuple[int, JSONResponse] | None = None
        self.env = Environment(
            loader=PackageLoader("kranto.web", "templates"),
            autoescape=select_autoescape(["html"]),
        )
        self.env.globals.update(version=__version__)
        self.env.filters["short_date"] = lambda v: (v or "")[:10]
        # Defence in depth: URLs are checked when stored, and again when rendered.
        self.env.filters["safe_url"] = lambda v: safe_url(v) or ""

    @property
    def threshold(self) -> float:
        return self.rt.cfg.ingest.signal_threshold

    def _public(self, r: dict) -> dict:
        return _public(r, self.threshold)

    @property
    def links(self) -> Links:
        """Where a form sends the browser back to: Kranto UI when it is mounted."""
        return Links(self.brb.mounted)

    def _see(self, url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def render(self, name: str, request: Request, **ctx) -> HTMLResponse:
        store = self.rt.store
        ctx.setdefault("paused", store.pause_reason())
        ctx.setdefault("nav", name.split(".")[0])
        # The page mounted at /brb/: the shared "kranto" header (no builds' figures any more)
        ctx.setdefault("kranto", {} if self.brb.mounted else None)
        return HTMLResponse(self.env.get_template(name).render(request=request, **ctx))

    def install_notice(self, request: Request) -> HTMLResponse:
        """What ``/`` and the server's old page addresses answer when Kranto UI is not
        mounted: Kranto is one app, and how to install it (D5). ``why``: what ``brb.load``
        found, when it says (the page missing, too old, or not on loopback)."""
        return self.render("install.html", request, nav="install", why=self.brb.message)

    # -- library -------------------------------------------------------------------

    def _filter(self, request: Request) -> tuple[library.ObservationFilter, dict]:
        """``source`` is a source id, or ``parallax`` for every source of the imported
        archive; ``theme`` is an archive theme's lineage id (``/api/archive/themes``)."""
        q = request.query_params
        archive = q.get("source") == ARCHIVE
        params = {
            "topic": _int(q.get("topic")),
            "source": None if archive else _int(q.get("source")),
            "kind": q.get("kind") or None,
            "min_signal": _float(q.get("min_signal")),
            "contains": (q.get("contains") or "").strip() or None,
            "cluster": _int(q.get("cluster")),
            "theme": (q.get("theme") or "").strip() or None,
        }
        store = self.rt.store
        ids = None
        if params["cluster"] is not None:
            snap = map_read.latest(store)
            ids = map_read.member_ids(store, snap["id"], params["cluster"]) if snap else ()
        if params["theme"]:
            members = set(theme_member_ids(store, params["theme"]))
            ids = tuple(i for i in ids if i in members) if ids is not None \
                else tuple(sorted(members))
        extra = None
        if params["topic"] is not None and self.rt.cfg.parallax.topic_match > 0:
            extra = library.archive_topic_ids(store, params["topic"],
                                              self.rt.cfg.parallax.topic_match)
        f = library.ObservationFilter(
            topic_id=params["topic"], source_id=params["source"], kind=params["kind"],
            min_signal=params["min_signal"], text=params["contains"], ids=ids,
            source_kind=ARCHIVE if archive else None, topic_extra_ids=extra,
        )
        return f, {**params, "source": ARCHIVE if archive else params["source"]}

    def _semantic(self, query: str, f: library.ObservationFilter, k: int = SEARCH_MAX,
                  cutoff: bool = False):
        hits = search.search(self.rt.index, self.rt.embedder, query, k=k * 3)
        allowed = {
            r["id"]
            for r in library.find_observations(
                self.rt.store, library.ObservationFilter(**{**f.__dict__,
                                                            "ids": tuple(h.observation_id
                                                                         for h in hits)}),
                limit=len(hits) or 1,
            )[0]
        }
        hits = [h for h in hits if h.observation_id in allowed][:k]
        if cutoff:
            hits = search.within_cutoff(hits)
        rows = library.observations_by_id(self.rt.store, [h.observation_id for h in hits])
        return [(_row(rows[h.observation_id]), h) for h in hits if h.observation_id in rows]

    def _rollups(self, query: str, k: int) -> list[tuple[dict, search.RollupHit]]:
        """Matching rollups, leaving out those far below the best, as for observations."""
        hits = search.search_rollups(self.rt.index, self.rt.embedder, query, k=k)
        if hits:
            floor = max(h.score for h in hits) - search.CUTOFF_BELOW_BEST
            hits = [h for h in hits if h.score >= floor]
        if not hits:
            return []
        marks = ",".join("?" * len(hits))
        rows = {r["id"]: r for r in self.rt.store.query(
            f"SELECT * FROM rollups WHERE id IN ({marks})", tuple(h.rollup_id for h in hits))}
        out = []
        for h in hits:
            if h.rollup_id in rows:
                try:
                    out.append((_rollup(rows[h.rollup_id]), h))
                except Exception as exc:  # noqa: BLE001 - listed as unreadable (RCA A3)
                    out.append((rowsafe.unreadable("trend summary", h.rollup_id, exc), h))
        return out

    def _nearest(self, query: str) -> list[search.Hit]:
        # Unfiltered and by cosine alone: whether the library covers the query
        # at all, whatever the page's filters.
        return search.nearest_to_query(self.rt.index, self.rt.embedder, query, k=NEAREST)

    # -- map ----------------------------------------------------------------------

    def api_map(self, request: Request):
        snap = map_read.latest(self.rt.store)
        if snap is None:
            return JSONResponse({"error": "no snapshot yet",
                                 "progress": library_progress(self.rt.store).map_message,
                                 "can_run": self.scheduler is not None}, status_code=404)
        if self._map_cache and self._map_cache[0] == snap["id"]:
            return self._map_cache[1]
        response = JSONResponse(map_read.map_payload(self.rt.store, snap))
        self._map_cache = (snap["id"], response)
        return response

    # -- ideation ---------------------------------------------------------------------

    def _explain(self, kind: str, target: int, offline: bool = False) -> dict:
        """``{"text", "input_ids", "cached"}`` or ``{"error"}``; ``offline``: the cache only
        (``{"missing": True}`` when the model has not explained these inputs yet)."""
        from ..ideate.explain import ExplainError, explain_cluster, explain_neighbourhood
        from ..llm import LLMError

        try:
            if kind == "cluster":
                snap = map_read.latest(self.rt.store)
                if snap is None:
                    return {"error": "no map yet"}
                syn = explain_cluster(self.rt.store, self.rt.llm, snap["id"], target,
                                      offline=offline)
            else:
                syn = explain_neighbourhood(self.rt.store, self.rt.llm, self.rt.index, target,
                                            offline=offline)
        except (ExplainError, LLMError) as exc:
            return {"error": str(exc)}
        if syn is None:
            return {"missing": True}
        return {"text": syn.text, "input_ids": syn.input_ids, "cached": syn.cached}

    def _explain_job(self, kind: str, target: int) -> dict:
        """The model's half of an explanation, in the background (``web/jobs.py``): the
        request that asked answers at once with the job's state."""
        def run() -> dict:
            out = self._explain(kind, target)
            if "error" in out:
                raise RuntimeError(out["error"])
            return out
        return self.jobs.start(f"explain:{kind}:{target}", run)

    async def _explain_now(self, kind: str, target: int | None) -> tuple[dict, int]:
        """What a press gets at once: the cached explanation (200), a refusal (400), or the
        background job that is writing it (202)."""
        if target is None:
            return {"error": "say which observation or cluster"}, 400
        result = await run_in_threadpool(self._explain, kind, target, True)
        if "error" in result:
            return result, 400
        if not result.get("missing"):
            return result, 200
        return {"job": self._explain_job(kind, target)}, 202

    async def explain_observation(self, request: Request):
        obs_id = _int(request.path_params["obs_id"])
        result, code = await self._explain_now("neighbourhood", obs_id)
        if code == 400:
            return self._see(self.links.observation(obs_id, result["error"]))
        if self.links.kranto:
            return self._see(self.links.observation(obs_id))
        return self._see(f"/obs/{obs_id}#explain")

    async def explain_cluster_form(self, request: Request):
        cluster = _int(request.path_params["cluster"])
        result, code = await self._explain_now("cluster", cluster)
        return self._see(self.links.cluster(cluster, result.get("error")))

    async def api_explain(self, request: Request):
        """``POST {cluster} | {observation_id}``: the explanation when it is cached (200),
        else the background job writing it (202, ``{"job"}``); ``GET ?cluster= |
        ?observation_id=``: that job's state, with the explanation as its result once done."""
        if request.method == "GET":
            q = request.query_params
            kind = "cluster" if "cluster" in q else "neighbourhood"
            target = _int(q.get("cluster") if kind == "cluster" else q.get("observation_id"))
            job = self.jobs.get(f"explain:{kind}:{target}") if target is not None else None
            if job is None:
                return JSONResponse({"error": "no explanation is being written for that"},
                                    status_code=404)
            return JSONResponse({"job": job})
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": f"expected a JSON object under {MAX_JSON_BYTES} bytes"},
                                status_code=400)
        if "cluster" in body:
            result, code = await self._explain_now("cluster", _int(body["cluster"]))
        else:
            result, code = await self._explain_now("neighbourhood",
                                                   _int(body.get("observation_id")))
        return JSONResponse(result, status_code=code)

    # -- topics and sources ------------------------------------------------------------

    async def add_topic(self, request: Request):
        form = await request.form()
        name, description = str(form.get("name", "")), str(form.get("description", ""))
        try:
            topic_id = await run_in_threadpool(
                library.add_topic, self.rt.store, self.rt.embedder, name, description
            )
        except ValueError as exc:
            return self._see(self.links.topics(str(exc)))
        msg = f"Added topic '{name}'."
        if form.get("scout"):
            msg += " " + self._scout_started(topic_id, bool(form.get("approve")))
        return self._see(self.links.topics(msg))

    async def scout_topic(self, request: Request):
        topic_id = _int(request.path_params["topic_id"])
        form = await request.form()
        return self._see(self.links.topics(self._scout_started(topic_id,
                                                               bool(form.get("approve")))))

    def _scout_started(self, topic_id: int | None, approve: bool) -> str:
        """Start the scout in the background (it searches the live web, calls the model and
        fetches every proposal) and say so; the proposals show under the topic's sources when
        it finishes."""
        if topic_id not in {t.id for t in library.active_topics(self.rt.store)}:
            return f"No active topic {topic_id}."
        before = self.jobs.get(f"scout:{topic_id}")
        self.scout_job(topic_id, approve)
        running = before is not None and before["state"] == "running"
        return ("The scout is running" if running else "The scout started") + \
            ": its proposals show under the topic's sources when it finishes (about a minute)."

    def scout_job(self, topic_id: int, approve: bool | str = False) -> dict:
        """The scout of one topic as a background job (``web/jobs.py``). Its result:
        ``{message, proposals, invalid, no_feed, search}``, the proposals as rows
        (``TopicsAPI.source_rows``): the sources it found, already watched or not, how many
        failed validation, the sites live search found that have no feed, and the run's live
        search (``scout.search_summary``: its backends and date, or the "no live search"
        sentence).
        ``approve``: True or ``"core"`` approves core proposals at or above the prefilter
        line, ``"all"`` every core proposal with a similarity; wildcards never."""
        def run():
            message, results = self._scout_run(topic_id, approve)
            ids = {r.source_id for r in results
                   if r.source_id is not None and r.status != "invalid"}
            rows = getattr(self, "topics_api", None)
            from ..scout import NO_FEED

            return {"message": message,
                    "proposals": rows.source_rows(ids=ids, first_for=topic_id)
                    if ids and rows else [],
                    "invalid": sum(1 for r in results if r.status == "invalid"),
                    "no_feed": [{"label": r.label, "why": r.validation.error}
                                for r in results if r.status == NO_FEED],
                    "search": results[0].search if results else None}
        return self.jobs.start(f"scout:{topic_id}", run)

    def fromtext_job(self, text: str, topic_id: int | None = None) -> dict:
        """A pasted list of sources resolved in the background (``resolve.py``, 
        4.1): one at a time per install (key ``fromtext``; a second press while one runs
        gets the running one). Its result is the batch (``_batch_json``), also kept under
        ``fromtext:<call id>`` so the page can open it again by its id."""
        def run():
            from .. import websearch
            from ..resolve import resolve_text

            topic = next((t for t in library.active_topics(self.rt.store)
                          if t.id == topic_id), None) if topic_id else None
            batch = resolve_text(self.rt.store, self.rt.llm, self.rt.embedder, self.rt.http,
                                 text, topic=topic, connections=self.rt.connections,
                                 xcfg=self.rt.cfg.x, every_hours=self.rt.cfg.ingest.every_hours,
                                 searcher=websearch.for_runtime(self.rt, "resolve"))
            result = self.batch_json(batch, topic_id if topic is not None else None)
            self.jobs.remember(batch.id, result)
            return result
        return self.jobs.start("fromtext", run)

    def batch_json(self, batch, topic_id: int | None) -> dict:
        """A described batch as the page reads it: each line with its source's row
        (``TopicsAPI.source_rows``) where the line is a source, so it is drawn like a scout
        proposal."""
        ids = {line.source_id for line in batch.lines if line.source_id is not None}
        api = getattr(self, "topics_api", None)
        rows = {r["id"]: r for r in api.source_rows(ids=ids)} if ids and api else {}
        out = batch.to_json()
        out["topic"] = topic_id
        out["lines"] = [{**line.to_json(), "row": rows.get(line.source_id)}
                        for line in batch.lines]
        return out

    def _scout(self, topic_id: int, approve: bool | str) -> str:
        return self._scout_run(topic_id, approve)[0]

    def _scout_run(self, topic_id: int, approve: bool | str) -> tuple[str, list]:
        """Scout a topic: the message the pages show, and the scout's results (empty when
        it failed or proposed nothing usable)."""
        from .. import websearch
        from ..llm import LLMError
        from ..scout import scout_topic

        topic = next((t for t in library.active_topics(self.rt.store) if t.id == topic_id), None)
        if topic is None:
            return f"No active topic {topic_id}.", []
        # cosine similarity is never below -1: "all" approves every core proposal that has one
        threshold = (-1.0 if approve == "all" else
                     self.rt.cfg.ingest.prefilter_min_similarity if approve in (True, "core")
                     else None)
        try:
            results = scout_topic(self.rt.store, self.rt.llm, self.rt.embedder, self.rt.http,
                                  topic, auto_approve_min_similarity=threshold,
                                  connections=self.rt.connections, xcfg=self.rt.cfg.x,
                                  searcher=websearch.for_runtime(self.rt, "scout"))
        except LLMError as exc:
            return f"Scouting failed: {exc}", []
        if not results:
            return "The scout's reply contained no usable proposals; nothing was added.", []
        by_status: dict[str, int] = {}
        for r in results:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        parts = ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in sorted(by_status.items()))
        search = results[0].search or {}
        said = (f" From live search ({', '.join(search.get('backends') or [])}, "
                f"{(search.get('searched_at') or '')[:10]})." if search.get("live")
                else f" {search.get('note') or ''}".rstrip())
        return f"Scout proposed {len(results)} sources: {parts or 'none'}.{said}", results

    async def add_source(self, request: Request):
        from .. import source_health, sources

        form = await request.form()
        topic_id = _int(form.get("topic"))
        if form.get("preset"):
            # From the catalog: the preset's fields arrive as field_<key>.
            preset = str(form.get("preset"))
            fields = {k.removeprefix("field_"): str(v) for k, v in form.items()
                      if k.startswith("field_")}
            try:
                preview = await run_in_threadpool(source_health.preview, self.rt, preset,
                                                  fields, topic_id)
                source_id, label = await run_in_threadpool(
                    source_health.add_from_preset, self.rt, preset, fields, topic_id,
                    items=preview["items"])
            except (ValueError, TypeError, sources.SourceError) as exc:
                msg = f"Could not add it: {exc}"
                if self.links.kranto:
                    return self._see(self.links.topics(msg))
                return self._see(f"/topics?{urlencode({'preset': preset, 'msg': msg})}")
            msg = f"Added {label} ({preview['items']} items). The next ingest run reads it."
            return self._see(self.links.topics(msg))
        kind, value = str(form.get("kind", "")), str(form.get("value", ""))
        try:
            params = sources.params_from_value(kind, value)
            adapter = sources.build(kind, params, self.rt.http)
            items = await run_in_threadpool(adapter.fetch)
        except (ValueError, TypeError, sources.SourceError) as exc:
            return self._see(self.links.topics(f"Could not add {kind} {value!r}: {exc}"))
        source_id = library.add_source(
            self.rt.store, kind, params, label=adapter.label,
            validation=StoredValidation.checked_by("manual", len(items)),
        )
        if topic_id:
            library.link_topic_source(self.rt.store, topic_id, source_id)
        msg = f"Added {adapter.label} ({len(items)} items)."
        return self._see(self.links.topics(msg))

    async def set_source_status(self, request: Request):
        source_id = _int(request.path_params["source_id"])
        form = await request.form()
        status = str(form.get("status", ""))
        if status not in ("approved", "retired", "proposed") or source_id is None:
            return Response("bad request", status_code=400)
        if source_id not in {s.id for s in library.list_sources(self.rt.store)}:
            return Response("no such source", status_code=404)
        self.rt.store.set_status("source", source_id, status, "via web")
        return self._see(self.links.topics())

    # -- grades ----------------------------------------------------------------------

    # -- health ----------------------------------------------------------------------

    def _retention_status(self) -> dict:
        store = self.rt.store
        last = store.query_one("SELECT * FROM runs WHERE kind = 'compact' "
                               "ORDER BY finished_at DESC LIMIT 1")
        last = _row(last) if last else None
        if last:
            last["summary"] = summary_of("compact", last["summary"]).to_dict(nulls=True)
        totals = store.query_one("SELECT COUNT(*) AS n, COALESCE(SUM(replaced_count), 0) AS r "
                                 "FROM rollups")
        return {
            "line": _retention_line(self.rt.cfg), "last": last,
            "rollups": totals["n"], "replaced": totals["r"],
            "removed": store.query("SELECT table_name, SUM(row_count) AS n FROM purges "
                                   "GROUP BY table_name ORDER BY table_name"),
            "last_purge": store.query_one("SELECT MAX(created_at) AS t FROM purges")["t"],
        }

    def feed(self, request: Request):
        xml = notify.atom_feed(self.rt.store, base_url=str(request.base_url),
                               kranto=self.brb.mounted)
        return Response(xml, media_type="application/atom+xml; charset=utf-8")

    async def pause(self, request: Request):
        """Pause Kranto's model spend. The build loop's PAUSE file is left as it is: builds are
        not part of Kranto any more."""
        form = await request.form()
        self.rt.store.pause(str(form.get("reason") or "paused from the web UI"))
        return self._back(request, form, None)

    async def resume(self, request: Request):
        form = await request.form()
        self.rt.store.resume()
        return self._back(request, form, None)

    def _back(self, request: Request, form, msg: str | None):
        """After pause or resume. A caller that asks for JSON (Kranto UI's ``hostForm``)
        gets ``{"ok", "error"}``, with status 502 when only one half changed, so it can
        say so instead of following a redirect to a page that answers 200."""
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"ok": not msg, "error": msg or None},
                                status_code=502 if msg else 200)
        back = str(form.get("next") or "")
        if not back.startswith("/") or back.startswith("//") or "\\" in back:
            back = self.links.health()
        if msg:
            back = self.links.health(msg)
        return RedirectResponse(back, status_code=303)

    async def run_now(self, request: Request):
        """Run one job now. A caller that asks for JSON (the page's run buttons, an assistant
        through the verb door) is answered 202 when it started and 409 with the reason when it
        did not: on 0.6.0.dev4 an assistant asked for four runs, Kranto started one and refused
        three, and the redirect read as "done" for all four (the owner, 2026-10-27)."""
        from ..core import verbs
        kind = request.path_params["kind"]
        if "application/json" in request.headers.get("accept", ""):
            from ..activity import words as W
            title = W.title_of(kind, "scheduled")
            if self.scheduler is None:
                return JSONResponse({"ok": False, "error": f"Not started: {title}: Kranto runs "
                                     "with the scheduler off (kranto serve --no-scheduler)"},
                                    status_code=409)
            why = self.scheduler.why_not(kind)
            if why is None and self.scheduler.trigger(kind, origin="press",
                                                      by=verbs.acting_by() or "ui"):
                return JSONResponse({"ok": True, "started": kind,
                                     "msg": f"Started: {title}. Activity follows it."},
                                    status_code=202)
            why = why or self.scheduler.why_not(kind) or "it could not start"
            return JSONResponse({"ok": False, "started": None,
                                 "error": f"Not started: {title}: {why}. Ask again when it "
                                          "has ended."}, status_code=409)
        if self.scheduler is None:
            msg = "The scheduler is disabled; use 'python -m kranto run'."
        elif self.scheduler.trigger(kind, origin="press", by=verbs.acting_by() or "ui"):
            msg = f"Started {kind}. Refresh to see it in the runs table when it finishes."
            if kind == "snapshot":
                return self._see(self.links.map())
            if kind == "ideas":
                return self._see(self.links.ideas(msg))
        else:
            msg = "A job is already running."
        return self._see(self.links.health(msg))

    # -- JSON API ----------------------------------------------------------------------

    def _new_since(self, rows: list[dict], marker: str) -> list[dict]:
        """Each row with ``new`` (written after the last-visit marker) and its latest grade."""
        latest = grades.latest(self.rt.store, "observation",
                               [r["id"] for r in rows if r.get("id") is not None])
        for r in rows:
            r["new"] = (r.get("created_at") or "") > marker
            g = latest.get(str(r["id"]))
            r["grade"] = {"grade": g["grade"], "created_at": g["created_at"]} if g else None
        return rows

    def api_observations(self, request: Request):
        """The library as JSON. Without ``q``: filtered, sorted and paged, as /library.
        With ``q``: semantic search, the ``k`` best; ``cutoff=1`` searches as /library does
        (up to SEARCH_MAX, leaving out those far below the best) and adds what the page says
        about the query (off topic, the watch threshold it would suggest, matching rollups).
        ``offset`` and ``limit`` page either.

        Every row says whether it is ``new``: written after the last-visit marker
        (``today_api``; the last 24 hours until one is set), and the answer carries the
        marker (``seen_at``, ``marker``) and how many of the filtered rows are new
        (``new_total``). ``since`` (``last`` or an ISO time) keeps only rows after it,
        ``until`` (an ISO time) only rows before it; ``kind=!beat`` every kind but beats."""
        from .today_api import resolve_since

        f, params = self._filter(request)
        q = request.query_params
        query = (q.get("q") or "").strip()
        offset = max(0, _int(q.get("offset"), 0))
        marker, seen = resolve_since(self.rt.store, None)
        if q.get("since"):
            try:
                f = library.ObservationFilter(**{**f.__dict__, "since": resolve_since(
                    self.rt.store, q.get("since"))[0]})
            except ValueError:
                return JSONResponse({"error": 'since must be "last" or an ISO time'},
                                    status_code=400)
        if q.get("until"):
            from .today_api import parse_time
            try:
                f = library.ObservationFilter(**{**f.__dict__, "until": parse_time(q["until"])})
            except ValueError:
                return JSONResponse({"error": "until must be an ISO time"}, status_code=400)
        new_total = library.find_observations(
            self.rt.store, library.ObservationFilter(**{**f.__dict__, "since": max(
                marker, f.since or "")}), limit=1)[1]
        context = {"cluster_label": self._cluster_label(params["cluster"]),
                   "seen_at": seen, "marker": marker, "since": f.since, "new_total": new_total}
        if query:
            as_page = q.get("cutoff") == "1"
            k = SEARCH_MAX if as_page else _count(q.get("k"), 20, 200)
            results = self._semantic(query, f, k=k, cutoff=as_page)
            total = len(results)
            if q.get("limit") or offset:
                results = results[offset:offset + _count(q.get("limit"), SEARCH_PAGE_SIZE, 500)]
            out = {"query": query, "total": total, "offset": offset, **context,
                   "results": self._new_since(rowsafe.each(
                       results, lambda x: {**self._public(x[0]), "score": round(x[1].score, 4),
                                           "weak": x[1].weak},
                       "observation", ident=lambda x: x[0].get("id"),
                       keep=lambda x: {"title": x[0].get("title")}), marker)}
            if as_page:
                nearest = self._nearest(query)
                out.update(
                    cutoff=search.CUTOFF_BELOW_BEST, off_topic_below=search.OFF_TOPIC_BELOW,
                    closest=search.floor2(nearest[0].score) if search.off_topic(nearest) else None,
                    rollups=rowsafe.each(self._rollups(query, ROLLUPS_ON_LIBRARY),
                                         lambda x: {**x[0], "score": round(x[1].score, 4)},
                                         "trend summary", ident=lambda x: x[0].get("id")))
            return JSONResponse(out)
        limit = _count(q.get("limit"), PAGE_SIZE, 500)
        rows, total = library.find_observations(
            self.rt.store, f, sort=q.get("sort", "new"), limit=limit, offset=offset,
        )
        compacted = self.rt.store.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(replaced_count), 0) AS replaced FROM rollups")
        return JSONResponse({"total": total, "offset": offset, **context,
                             "compacted": dict(compacted),
                             "progress": library_progress(self.rt.store).map_message,
                             "results": self._new_since(rowsafe.each(
                                 rows, lambda r: self._public(_row(r)), "observation",
                                 ident=lambda r: r["id"], keep=lambda r: {"title": r["title"]}),
                                 marker)})

    def _cluster_label(self, cluster: int | None) -> str | None:
        """The name /library shows for ``?cluster=``: from the latest map."""
        if cluster is None:
            return None
        snap = map_read.latest(self.rt.store)
        match = [c for c in (map_read.clusters(self.rt.store, snap["id"]) if snap else [])
                 if c["cluster"] == cluster]
        return match[0]["label"] if match else f"cluster {cluster}"

    async def api_remove_observation(self, request: Request):
        """Remove this post: one observation, now, through the recorded purge with no rollup
        (a deletion request, 5.5). Its ``items_seen`` row stays, so it is never
        fetched or judged again."""
        from ..xrecheck import remove_post

        obs_id = _int(request.path_params["obs_id"])
        if not obs_id or library.get_observation(self.rt.store, obs_id) is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        n = await run_in_threadpool(remove_post, self.rt.store, observation_id=obs_id)
        return JSONResponse({"ok": bool(n), "removed": n,
                             "message": "Removed from the library at your request; the purge "
                                        "record says so."})

    def api_observation(self, request: Request):
        obs_id = _int(request.path_params["obs_id"])
        row = library.get_observation(self.rt.store, obs_id) if obs_id else None
        if row is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        hits = search.similar_to(self.rt.index, obs_id,
                                 k=_count(request.query_params.get("k"), 12, 100))
        # Everything /obs/{id} shows, from the same queries.
        from .. import source_health
        from ..ideate.explain import cached as cached_synthesis
        from ..library import children_of, parent_of

        store = self.rt.store
        refs = source_health.topic_refs(store)
        near = library.observations_by_id(store, [h.observation_id for h in hits])
        call = store.query_one(
            "SELECT id, model, prompt_version, cost_usd, prompt_tokens, completion_tokens, "
            "response, created_at FROM llm_calls WHERE id = ?", (row["llm_call_id"],),
        ) if row["llm_call_id"] else None
        synthesis = cached_synthesis(store, f"obs:{obs_id}")
        parent = parent_of(store, obs_id)
        return JSONResponse({
            **self._public(_row(row)),
            "source_url": safe_url(row["source_url"]),
            "source_kind": row["source_kind"], "topic_similarity": row["topic_similarity"],
            "similar": [{"id": h.observation_id, "score": round(h.score, 4), "weak": h.weak}
                        for h in hits],
            "neighbours": [{**self._public(_row(near[h.observation_id])),
                            "score": round(h.score, 4), "weak": h.weak}
                           for h in hits if h.observation_id in near],
            "call": dict(call) if call else None,
            "synthesis": {"text": synthesis["text"],
                          "input_ids": SynthesisInputIds.load(synthesis["input_ids"]).items}
            if synthesis else None,
            "dive_parent": dict(parent) if parent else None,
            "dive_children": [{**dict(c), "source_url": safe_url(c["source_url"])}
                              for c in children_of(store, obs_id)],
            "grade": grades.latest(store, "observation", [obs_id]).get(str(obs_id)),
            # ▲ and ▼; an older "missed" or "wrong" is still read and labelled
            "grade_choices": grades.CHOICES, "grade_labels": grades.LABELS,
            "cited_by": cited_by(store, obs_id),
            # why it is in a topic: the topics its source feeds
            "topics": [source_health.topic_ref(refs, t) for t in
                       source_health.source_links(store).get(row["source_id"], [])],
        })

    def api_rollups(self, request: Request):
        query = (request.query_params.get("q") or "").strip()
        k = _count(request.query_params.get("k"), 20, 200)
        # What /rollups says above the list.
        totals = self.rt.store.query_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(replaced_count), 0) AS r FROM rollups")
        about = {"rollups": totals["n"], "replaced": totals["r"],
                 "retention_line": _retention_line(self.rt.cfg)}
        if query:
            results = self._rollups(query, k)
            return JSONResponse({"query": query, **about, "results": rowsafe.each(
                results, lambda x: {**x[0], "score": round(x[1].score, 4)}, "trend summary",
                ident=lambda x: x[0].get("id"))})
        offset = max(0, _int(request.query_params.get("offset"), 0))
        rows = self.rt.store.query(
            "SELECT * FROM rollups ORDER BY period_start DESC, size DESC, id DESC "
            "LIMIT ? OFFSET ?", (k, offset))
        return JSONResponse({"total": totals["n"], "offset": offset, **about,
                             "results": rowsafe.each(rows, _rollup, "trend summary",
                                                     ident=lambda r: r["id"])})

    def api_status(self, request: Request):
        store = self.rt.store
        return JSONResponse({
            "version": __version__,
            # the JSON's version (web/types.py): Kranto UI says when it expects another
            "host_api": HOST_API_VERSION,
            "observations": store.query_one("SELECT COUNT(*) AS n FROM observations")["n"],
            "rollups": store.query_one("SELECT COUNT(*) AS n FROM rollups")["n"],
            "spend_this_month_usd": round(store.month_spend(), 6),
            "budget_usd": self.rt.cfg.budget.monthly_usd,
            # The watcher's model calls since midnight UTC, in tokens (None: none yet).
            "tokens_today": store.tokens_since(utcnow().replace(hour=0, minute=0, second=0,
                                                                microsecond=0)),
            "paused": store.pause_reason(),
            # the preview: the status bar's sentence and the copy's date; null on
            # every other install
            "preview": preview.status(self.rt.cfg.root),
            # the owner's topics (the navigator's list); project topics: /api/topics?kind=
            "topics": [{"id": t.id, "name": t.name, "description": t.description,
                        "kind": t.kind, "ref": t.ref}
                       for t in library.active_topics(store) if t.kind == "user"],
            "sources": [{"id": s.id, "kind": s.kind, "label": s.label, "status": s.status,
                         "params": s.params} for s in library.list_sources(store)],
            "runs": [{k: r[k] for k in ("run_uuid", "kind", "status", "started_at",
                                        "finished_at", "error")}
                     for r in library.recent_runs(store, 10)],
            "scheduler": self.scheduler is not None,
            # what the header says: the job running now (ingest: reading sources) and when
            # each job is next due, by kind (null: off, or no scheduler)
            "running": self.scheduler.running if self.scheduler else None,
            "ingest_progress": current_progress(),
            "next_run": self.scheduler.next_runs() if self.scheduler else {},
            "lanes": self.scheduler.lane_status() if self.scheduler else {},
            # the header's update pill (section 3): from two small files
            "update": update_check.summary(self.rt.cfg.root),
            "hold": self.scheduler.hold if self.scheduler else None,
            # builds, projects and repos on (builds.enabled,.1): the page draws
            # no Build door, project, repo or "Send to build" while this is false
            "builds": builds_on(self.rt.cfg),
            # the browser extension left Kranto (cut 2): always false, for a page
            # that still reads the key
            "browser": False,
            "cubs_developer": cubs_developer(self.rt.cfg),
        })


    # -- errors ------------------------------------------------------

    def error_answer(self, request: Request, exc: Exception) -> Response:
        """What a request that still failed answers: Kranto's error JSON (the API) or its error
        page (anything else), never a bare 500. Both say the version and a short error id, and
        offer Try again and Send this error; the error is kept once by its id (``rowsafe``)."""
        if isinstance(exc, rowsafe.Unreadable):
            rec = rowsafe.find(exc.error_id) or rowsafe.note(exc, "page")
        else:
            route = getattr(request.scope.get("route"), "path", None) or "other"
            rec = rowsafe.note(exc, f"{request.method} {route}", kind="response")
        eid = rec["id"]
        path = request.url.path
        if path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            out: Response = JSONResponse({
                "error": rowsafe.said(eid), "error_id": eid, "exception": rec["exception"],
                "version": __version__, "report": f"/api/errors/{eid}"}, status_code=500)
        else:
            rep = rowsafe.report(rec)
            out = HTMLResponse(self.env.get_template("error.html").render(
                request=request, kranto=None, nav="error", paused=None, error_id=eid,
                again=str(request.url.path) + (f"?{request.url.query}" if request.url.query
                                               else ""),
                send=f"/#/today?send_error={eid}", github=rowsafe.issue_url(
                    rep["title"], rep["body"]), title=rep["title"], body=rep["body"]),
                status_code=500)
        return GuardMiddleware._secure(out)

    def api_errors(self, request: Request):
        """``GET /api/errors``: the errors kept (``rowsafe``: id, when, where, the exception's
        class, Kranto's frames), newest first; ``GET /api/errors/<id>``: one error's report, as
        Send this error files it (``title``, ``body``, ``url``: GitHub's prefilled page)."""
        eid = request.path_params.get("error_id")
        if eid is None:
            return JSONResponse({"errors": list(reversed(rowsafe.kept()))[:50]})
        rec = rowsafe.find(eid)
        if rec is None:
            return JSONResponse({"error": f"no error {eid} is kept here"}, status_code=404)
        rep = rowsafe.report(rec)
        return JSONResponse({**rep, "record": rec,
                             "url": rowsafe.issue_url(rep["title"], rep["body"])})


def _public(r: dict, threshold: float) -> dict:
    """An observation as the JSON API shows it. ``override`` is true only where it lifted
    the item over the gate; otherwise it and its reason are left out."""
    keys = ("id", "kind", "title", "summary", "why_it_matters", "content_quality", "durability",
            "opportunity", "signal", "override", "override_reason", "tags", "source_url",
            "source_excerpt", "item_published_at", "source_id", "source_label", "admitted_by",
            "created_at", "llm_call_id", "prompt_version")
    out = {k: r.get(k) for k in keys}
    out["override"] = override_lifted(r, threshold)
    if not out["override"]:
        out["override_reason"] = None
    return out


def create_app(rt: Runtime, scheduler: Scheduler | None = None, *,
               allowed_hosts: frozenset[str] | set[str] = LOOPBACK_HOSTS,
               bind_host: str | None = None, port: int | None = None,
               tokens=None, stop=None) -> Starlette:
    """``allowed_hosts`` are the names the server may be reached by (Host
    header, without port). Loopback names by default; ``python -m kranto serve`` adds the
    bound address and any ``--allow-host``. ``bind_host`` is the address the
    server is bound to: the page (``brb.enabled``) is mounted only on loopback.
    ``port`` is the one it listens on: the mounted the page reads idea cards
    from this server's ``/api/ideas`` there. ``tokens``: the token store
    (``tokens.Store``; default ``~/.config/kranto/tokens``, made if missing).
    ``stop``: the server's ``stopping.Stop`` (``cmd_serve``'s, begun at SIGTERM); by
    default one without a watchdog, begun when the app shuts down."""
    from .. import tokens as tokens_mod
    from ..telemetry.timing import TimingMiddleware
    from .activity_api import ActivityAPI
    from .archive_api import ArchiveAPI
    from .auth import Auth
    from .cubs_api import CubsAPI
    from .evals_api import EvalsAPI
    from .features_api import FeaturesAPI
    from .feedback_api import FeedbackAPI
    from .ideas_api import IdeasAPI
    from .kranto_api import KrantoAPI
    from .newsletter_api import NewsletterAPI
    from .post_api import PostAPI
    from .prompts_api import PromptsAPI
    from .prose_api import ProseAPI
    from .runs_api import RunsAPI
    from .search_api import SearchAPI
    from .selfcheck_api import SelfCheckAPI
    from .service_api import ServiceAPI
    from .settings_api import SettingsAPI
    from .setup_api import SetupAPI
    from .sources_api import SourcesAPI
    from .telemetry_api import TelemetryAPI
    from .today_api import TodayAPI
    from .topics_api import TopicsAPI
    from .update_api import UpdateAPI
    from .verbs_api import VerbsAPI
    from .websearch_api import WebSearchAPI

    app = App(rt, scheduler)
    app.port = port
    rowsafe.configure(rt.cfg.data_dir)      # where each error is kept once by its id
    if rt.cubs is None:
        from ..core.cubs.runtime import CubRuntime
        rt.cubs = CubRuntime(rt, scheduler)
    store = tokens if tokens is not None else tokens_mod.Store()
    try:
        store.ensure_doors()          # kranto up and kranto update make them too; this is the net
    except OSError as exc:
        import logging
        logging.getLogger(__name__).warning("the door tokens could not be made in %s: %s",
                                            store.root, exc)
    try:
        from ..core import shell as shell_mod
        shell_mod.migrate(rt.cfg.root)  # shell.home/shell.doors, once, as shell.layout
    except (OSError, ValueError) as exc:  # the old keys go on being read
        import logging
        logging.getLogger(__name__).warning("kranto.yaml's shell: was not migrated: %s", exc)
    app.auth = Auth(store, require=rt.cfg.api.require_token, port=port)
    try:
        # the console's plugin: the wheel's, or a copy in Kranto's home without the skill of a
        # feature that is off; written at each start
        from .. import assistant
        assistant.console_plugin(rt.cfg.root)
    except OSError as exc:      # the console loads the wheel's plugin, every skill in it
        import logging
        logging.getLogger(__name__).warning("the console's plugin was not written: %s", exc)
    app.brb = brb_mod.load(rt.cfg.brb, bind_host, port, data_dir=rt.cfg.data_dir)
    sources_api = SourcesAPI(app)
    kranto_api = KrantoAPI(app)
    app.topics_api = TopicsAPI(app)
    setup_api = SetupAPI(app)
    settings_api = SettingsAPI(app)
    ideas_api = IdeasAPI(app)
    search_api = SearchAPI(app)
    websearch_api = WebSearchAPI(app)
    feedback_api = FeedbackAPI(app)
    evals_api = EvalsAPI(app)
    today_api = TodayAPI(app)
    archive_api = ArchiveAPI(app)
    prompts_api = PromptsAPI(app)
    update_api = UpdateAPI(app)
    telemetry_api = TelemetryAPI(app)
    features_api = FeaturesAPI(app)
    cubs_api = CubsAPI(app)
    newsletter_api = NewsletterAPI(app)
    post_api = PostAPI(app)
    prose_api = ProseAPI(app)         # the prose profile and its checker
    runs_api = RunsAPI(app)           # an analyst's or a cub's run, for the page's trace
    activity_api = ActivityAPI(app)   # what Kranto is doing, as it goes (ACT)
    service_api = ServiceAPI(app)     # the service's memory, as a setting
    verbs_api = VerbsAPI(app)         # every write, once, for every caller (ASK, core.verbs)
    # what the post-update self-check reads (RCA D1): the routes, once they are made
    selfcheck_api = SelfCheckAPI(app, lambda: routes)

    @contextlib.asynccontextmanager
    async def lifespan(_):
        try:
            from .. import activity
            activity.recover(rt.store)  # runs the last process left without an end
        except Exception:  # noqa: BLE001 - Kranto starts; those runs say so at the next start
            import logging
            logging.getLogger(__name__).exception("the activity marks could not be recovered")
        try:
            cubs: Any = rt.cubs                 # a CubRuntime (runtime.Runtime.cubs)
            cubs.start()
        except Exception:  # noqa: BLE001 - Kranto starts without its cubs, not not at all
            import logging
            logging.getLogger(__name__).exception("the cub runtime did not start")
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            # the cubs, the scheduler, then the server's children, inside one budget
            from .. import stopping
            stopping.stop_server(stop or stopping.Stop(hard_exit_s=None, own_children=False),
                                 rt.cubs, scheduler)

    def kranto_page(route):
        """An old the server page address Kranto UI has as a hash route (UI-v4.md 2.3):
        while the page is mounted it answers 302 to it, with its query kept; without it,
        the install notice (D5). ``route`` is the hash route, or a function of the request
        that returns it."""
        def endpoint(request: Request):
            if not app.brb.mounted:
                return app.install_notice(request)
            to = route(request) if callable(route) else route
            query = request.url.query
            return RedirectResponse(f"{KRANTO}{to}" + (f"?{query}" if query else ""),
                                    status_code=302)
        return endpoint

    def obs_route(request: Request) -> str:
        obs_id = _int(request.path_params["obs_id"])
        return f"library/o/{obs_id}" if obs_id is not None else "library"

    def grade_link(request: Request):
        """``/grade/<target>/<id>``, the link a strike delivered without Kranto UI: the
        thing graded, in Kranto UI, while the page is mounted; else the install notice."""
        if not app.brb.mounted:
            return app.install_notice(request)
        # the thing the old link graded, in Kranto UI (grades themselves are kept on ideas
        # and evidence only since the link still opens what it names)
        target, target_id = request.path_params["target"], request.path_params["target_id"]
        n = _int(target_id)
        to = (app.links.message(n) if target == "message" and n is not None
              else app.links.observation(n) if target == "observation" and n is not None
              else app.links.idea(n) if target == "idea" and n is not None
              else f"{KRANTO}library/clusters" if target == "cluster" else app.links.health())
        return RedirectResponse(to, status_code=302)

    async def front_door(request: Request):
        """The page, when it is mounted; else the install notice."""
        if app.brb.mounted:
            return await brb_mod.document(app.brb, request)
        return app.install_notice(request)

    routes = [
        Route("/", front_door),
        Route("/library", kranto_page("library")),
        Route("/obs/{obs_id}", kranto_page(obs_route)),
        Route("/rollups", kranto_page("library/rollups")),
        Route("/map", kranto_page("library/map")),
        Route("/clusters", kranto_page("library/clusters")),
        Route("/api/map", app.api_map),
        Route("/api/explain", app.api_explain, methods=["GET", "POST"]),
        Route("/obs/{obs_id}/explain", app.explain_observation, methods=["POST"]),
        Route("/clusters/{cluster}/explain", app.explain_cluster_form, methods=["POST"]),
        Route("/ideas", kranto_page("ideas")),
        Route("/topics", kranto_page("settings")),
        Route("/topics", app.add_topic, methods=["POST"]),
        Route("/topics/{topic_id}/scout", app.scout_topic, methods=["POST"]),
        Route("/sources", app.add_source, methods=["POST"]),
        Route("/sources/{source_id}/status", app.set_source_status, methods=["POST"]),
        # watches were retired: the old page's address opens Watch, where your topics are
        Route("/watches", kranto_page("watch")),
        Route("/health", kranto_page("settings/health")),
        Route("/grade/{target}/{target_id}", grade_link),
        Route("/feed.xml", app.feed),
        Route("/pause", app.pause, methods=["POST"]),
        Route("/resume", app.resume, methods=["POST"]),
        Route("/run/{kind}", app.run_now, methods=["POST"]),
        Route("/api/observations", app.api_observations),
        Route("/api/observations/{obs_id}", app.api_observation),
        Route("/api/observations/{obs_id}/remove", app.api_remove_observation,
              methods=["POST"]),
        Route("/api/rollups", app.api_rollups),
        Route("/api/status", app.api_status),
        Route("/api/errors", app.api_errors),
        Route("/api/errors/{error_id}", app.api_errors),
        *sources_api.routes(),
        *kranto_api.routes(),
        *app.topics_api.routes(),
        *setup_api.routes(),
        *settings_api.routes(),
        *ideas_api.routes(),
        *search_api.routes(),
        *websearch_api.routes(),
        *feedback_api.routes(),
        *evals_api.routes(),
        *today_api.routes(),
        *archive_api.routes(),
        *prompts_api.routes(),
        *update_api.routes(),
        *telemetry_api.routes(),
        *features_api.routes(),
        *cubs_api.routes(),
        *newsletter_api.routes(),
        *post_api.routes(),
        *prose_api.routes(),
        *runs_api.routes(),
        *activity_api.routes(),
        *service_api.routes(),
        *verbs_api.routes(),
        *selfcheck_api.routes(),
        *app.auth.routes(),
        *brb_mod.term_routes(app.brb, app.auth, allowed_hosts),
        *brb_mod.routes(app.brb),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
    starlette = Starlette(
        routes=routes, lifespan=lifespan,
        # a request that still fails answers Kranto's error JSON or page (RCA A3, B3)
        exception_handlers={rowsafe.Unreadable: app.error_answer},
        # timing outside the guard, so a refused request is counted too; the
        # error answer outside timing, so timing still records what escaped a route
        middleware=[Middleware(ErrorAnswerMiddleware, answer=app.error_answer),
                    Middleware(TimingMiddleware),
                    Middleware(GuardMiddleware,
                               allowed_hosts=frozenset(h.lower() for h in allowed_hosts),
                               auth=app.auth)]
    )
    starlette.state.app = app
    verbs_api.starlette = starlette       # a verb calls its route in this process
    return starlette
