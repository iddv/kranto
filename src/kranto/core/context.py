"""What the core hands a feature: its permissions, enforced by construction.

A feature's code receives one ``FeatureContext`` and nothing else. Each capability on it is
scoped by the feature's manifest:

- ``ctx.db``: its own tables only (``<id>_*``); a statement naming any other table, or doing
  anything but SELECT and INSERT, is refused (the tables are append-only besides);
- ``ctx.llm``: the metered client, refusing a purpose or tier the manifest did not declare, any
  tool, any provider or model override, and calls past the feature's monthly cap;
- ``ctx.search``: live search under the feature's name and kinds, with no page fetching;
- ``ctx.read``: the v1 read surface, by the families granted;
- ``ctx.publish``, ``ctx.take``, ``ctx.ack``: the bus, for the kinds declared;
- ``ctx.ticket``: a ticket for a high-trust action the manifest lists (never the action);
- ``ctx.settings``: its own section.

The core's own reads use ``ctx.store``; a feature's code never does (a test reads every feature
module for it, beside the import contract).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast

from ..store import Store, iso, utcnow
from ..stored import runs as stored_runs
from . import api, events, settings, tickets

log = logging.getLogger("kranto.core")


class PermissionDenied(PermissionError):
    """A feature asked for something its manifest does not grant."""


class CapReached(RuntimeError):
    """The feature's monthly model cap is reached; its paid calls pause until the month turns
    or the owner raises the cap."""


_TABLES = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_FORBIDDEN = re.compile(r"\b(DELETE|UPDATE|DROP|ALTER|ATTACH|DETACH|PRAGMA|REPLACE|VACUUM|"
                        r"CREATE|TRIGGER)\b", re.I)


class OwnTables:
    """SELECT and INSERT on the feature's own tables."""

    def __init__(self, store: Store, prefix: str) -> None:
        self._store, self.prefix = store, prefix

    def _check(self, sql: str) -> None:
        body = re.sub(r"'(?:[^']|'')*'", "''", sql)
        if ";" in body.strip().rstrip(";"):
            raise PermissionDenied("one statement at a time")
        if _FORBIDDEN.search(body):
            raise PermissionDenied("a feature reads and appends its own tables only")
        if not re.match(r"\s*(SELECT|WITH)\b", body, re.I):
            raise PermissionDenied("ctx.db.query runs SELECT; rows are added with insert")
        for name in _TABLES.findall(body):
            if not name.startswith(self.prefix) and name.lower() not in ("json_each",):
                raise PermissionDenied(f"{name} is not one of this feature's tables "
                                       f"({self.prefix}*)")

    def query(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Any]:
        self._check(sql)
        return self._store.query(sql, params)

    def query_one(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any:
        self._check(sql)
        return self._store.query_one(sql, params)

    def insert(self, table: str, row: dict[str, Any]) -> int:
        if not table.startswith(self.prefix) or not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
            raise PermissionDenied(f"{table} is not one of this feature's tables")
        return self._store.insert(table, row)

    @contextmanager
    def tx(self) -> Iterator[OwnTables]:
        with self._store.tx():
            yield self


class ScopedLLM:
    def __init__(self, llm: Any, feature: Any, cap_usd: float | None, store: Store,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self._llm, self._feature, self._cap, self._store, self._clock = \
            llm, feature, cap_usd, store, clock

    def model_for(self, tier: str) -> str:
        return str(self._llm.model_for(tier))

    def complete(self, *, purpose: str, tier: str, messages: list[dict[str, Any]],
                 prompt_version: str, run_uuid: str | None = None, max_tokens: int = 800,
                 temperature: float = 0.2, schema: dict[str, Any] | None = None,
                 retry_truncated: bool = False, **forbidden: Any) -> Any:
        m = self._feature.permissions.model
        if forbidden:
            raise PermissionDenied(f"{self._feature.id} may not pass "
                                   f"{', '.join(sorted(forbidden))} to the model: no tools, no "
                                   "provider or model of its own")
        if purpose not in m.purposes:
            raise PermissionDenied(f"{self._feature.id} did not declare the purpose {purpose}")
        if tier not in m.tiers:
            raise PermissionDenied(f"{self._feature.id} did not declare the {tier} tier")
        if self._cap is not None:
            spent = api.spend_of(self._store, self._feature, self._clock())["month_usd"]
            if spent >= self._cap:
                events.core_publish(self._store, "spend.capped",
                                    {"feature": self._feature.id, "cap_usd": self._cap})
                raise CapReached(f"{self._feature.id} has spent ${spent:.2f} of its "
                                 f"${self._cap:.2f} this month")
        return self._llm.complete(tier=tier, purpose=purpose, messages=messages,
                                  prompt_version=prompt_version, run_uuid=run_uuid,
                                  max_tokens=max_tokens, temperature=temperature, schema=schema,
                                  retry_truncated=retry_truncated)


class ScopedSearch:
    """Live search as ``feature``: its caller name, its kinds, nothing else (no fetch: a hit's
    page is read through ``ctx.fetch``, when the manifest grants it)."""

    def __init__(self, searcher: Any, kinds: tuple[str, ...],
                 seen: Callable[[str], None] | None = None) -> None:
        self._searcher, self.kinds, self._seen = searcher, kinds, seen

    def off_reason(self) -> str | None:
        return cast("str | None", self._searcher.off_reason()) if self._searcher is not None else \
            "no live search here"

    def search(self, query: str, *, kind: str = "web", recency: str | None = None,
               n: int = 10) -> Any:
        if kind not in self.kinds:
            raise PermissionDenied(f"search kind {kind} is not granted")
        if self._searcher is None:
            from ..websearch import NO_SEARCH, Results
            return Results(query, (), None, iso(utcnow()), note=NO_SEARCH)
        got = self._searcher.search(query, kind=kind, recency=recency, n=n)
        if self._seen is not None:
            for h in getattr(got, "hits", ()):
                self._seen(h.url)
        return got


FETCH_CHARS = 20000          # the most of a page's main text ``ctx.fetch`` hands back
_META = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-z:_-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.I)


class Web:
    """The network a feature's ``ctx.fetch`` goes through: the cub runtime's resolver and client
    when the server has one, else its own (the command line, a job run outside the server)."""

    def __init__(self, transport: Any = None, resolver: Callable[[str], list[str]] | None = None
                 ) -> None:
        from .cubs.runtime import _resolve
        self.resolver = resolver or _resolve
        self._transport: Any = transport
        self._http: Any = None

    def http_client(self) -> Any:
        import httpx
        if self._http is None:
            self._http = httpx.Client(transport=self._transport, follow_redirects=False)
        return self._http


def lead_image(markup: str, base: str) -> dict[str, str] | None:
    """The picture a page offers for sharing (``og:image``, else ``twitter:image``) and its
    site's name: an https address only, never fetched here."""
    from urllib.parse import urljoin, urlsplit
    found: dict[str, str] = {}
    for tag in _META.findall(markup[:200000]):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image",
                   "og:site_name", "og:image:alt") and attrs.get("content"):
            found.setdefault(key, attrs["content"])
    src = found.get("og:image:secure_url") or found.get("og:image") or \
        found.get("og:image:url") or found.get("twitter:image")
    if not src:
        return None
    src = urljoin(base, src)
    u = urlsplit(src)
    if u.scheme != "https" or not u.hostname or len(src) > 1000:
        return None
    site = found.get("og:site_name") or (urlsplit(base).hostname or "").removeprefix("www.")
    return {"url": src, "site": " ".join(site.split())[:80],
            "alt": " ".join(found.get("og:image:alt", "").split())[:200]}


class FeatureContext:
    def __init__(self, feature: Any, rt: Any, *, run_uuid: str | None = None,
                 clock: Callable[[], datetime] = utcnow, searcher: Any = None,
                 web: Web | None = None) -> None:
        self.feature, self.rt = feature, rt
        self.clock: Callable[[], datetime] = clock
        self.store: Store = rt.store
        self.index = getattr(rt, "index", None)
        self.embedder = getattr(rt, "embedder", None)
        self.run_uuid = run_uuid or uuid.uuid4().hex
        self.db = OwnTables(rt.store, feature.id + "_")
        self.settings = settings.section(rt.cfg, feature.id)
        # the owner's setting, else the feature's declared cap (a null is the owner's own value)
        cap = self.settings.get(f"{feature.id}.monthly_usd",  # stored-shape: config, not JSON
                                feature.permissions.model.monthly_usd)
        self.llm = ScopedLLM(rt.llm, feature, cap, rt.store, clock)
        p = feature.permissions
        # the URLs this context's reads and searches handed it: what ``fetch`` may read
        self.cited: set[str] = set()
        self._web = web
        if p.search:
            if searcher is None:
                from .. import websearch
                searcher = websearch.for_runtime(rt, caller=feature.id)
            self.search: ScopedSearch | None = ScopedSearch(searcher, p.search, self._cite)
        else:
            self.search = None
        self.log = logging.getLogger(f"kranto.features.{feature.id}")

    def _cite(self, url: Any) -> None:
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            self.cited.add(url)

    def _cite_all(self, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "url":
                    self._cite(v)
                else:
                    self._cite_all(v)
        elif isinstance(value, list):
            for v in value:
                self._cite_all(v)

    @property
    def cfg(self) -> Any:
        return self.rt.cfg

    def now(self) -> datetime:
        return self.clock()

    def read(self, name: str, **params: Any) -> dict[str, Any]:
        out = api.call(self, name, params)
        if self.feature.permissions.fetch and name.split(".")[0] in ("library", "objects"):
            self._cite_all(out)
        return out

    def fetch(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        """The page behind a URL this context was handed (``fetch: [cited]``,): an observation's
        source of a library or objects read, or a hit of a search it
        ran; refused for any other. The cub host's fetch with no host list (public addresses
        only, https, 3 redirects, 20 s, 2 MiB, no credential), then Kranto's main-text
        extraction, scrubbed, fenced, cut to ``max_chars``. ``{url, final_url, fetched_at,
        chars, text, image}``, or ``{url, fetched_at, error}`` when the page cannot be read."""
        if "cited" not in self.feature.permissions.fetch:
            raise PermissionDenied(f"{self.feature.id} may not fetch pages: its manifest does "
                                   "not grant fetch")
        if url not in self.cited:
            raise PermissionDenied("ctx.fetch reads only a URL this run's reads or searches "
                                   "returned")
        if not 1 <= int(max_chars) <= FETCH_CHARS:
            raise ValueError(f"max_chars is 1 to {FETCH_CHARS}")
        from urllib.parse import urlsplit

        from ..sources.fulltext import extract_main_text
        from ..websearch import fenced
        from .cubs import host
        from .cubs.process import RpcError
        when = iso(self.clock())
        target = "https://" + url[len("http://"):] if url.startswith("http://") else url
        self.progress(f"Reading the page at {urlsplit(target).hostname or 'its address'}")
        if self._web is None:
            cubs = getattr(self.rt, "cubs", None)
            self._web = cubs if cubs is not None and hasattr(cubs, "http_client") else Web()
        try:
            got = host.fetch(self._web, self.feature.id, target, None,
                             {"Accept": "text/html,application/xhtml+xml"}, host.FETCH_BYTES,
                             agent="kranto/1")
        except RpcError as exc:
            return {"url": url, "fetched_at": when, "error": exc.message[:200]}
        markup = got.get("text")
        if not markup:
            return {"url": url, "fetched_at": when,
                    "error": f"not a text page ({got.get('content_type') or 'no type'})"}
        final = str(got.get("url") or target)
        text = extract_main_text(markup, url=final) if "html" in str(
            got.get("content_type") or "").lower() else markup
        text = fenced(self.scrub(" ".join((text or "").split())))[:int(max_chars)]
        if not text:
            return {"url": url, "fetched_at": when, "error": "no readable text on the page"}
        return {"url": url, "final_url": final, "fetched_at": when, "chars": len(text),
                "text": text, "truncated": bool(got.get("truncated")),
                "image": lead_image(markup, final)}

    def publish(self, kind: str, payload: dict[str, Any] | None = None,
                subject: tuple[str, str | int] | None = None) -> int:
        return events.publish(self.store, feature=self.feature.id, trust=self.feature.trust,
                              kind=kind, payload=payload, subject=subject,
                              run_uuid=self.run_uuid, origin="job",
                              declared=self.feature.events.publishes)

    def _sub(self, kind: str) -> Any:
        sub = next((s for s in self.feature.events.subscribes if s.kind == kind), None)
        if sub is None:
            raise PermissionDenied(f"{self.feature.id} does not subscribe to {kind}")
        return sub

    def take(self, kind: str, limit: int = 100) -> list[dict[str, Any]]:
        sub = self._sub(kind)
        return events.take(self.store, self.feature.id, kind, min_trust=sub.min_trust,
                           limit=limit)

    def ack(self, kind: str, last_id: int) -> None:
        self._sub(kind)
        events.advance(self.store, self.feature.id, kind, last_id)

    def ticket(self, kind: str, fields: dict[str, Any], *, because: dict[str, Any] | None = None,
               subject: tuple[str, str | int] | None = None) -> int:
        """File a ticket for a high-trust action the manifest lists; its id."""
        return tickets.file(self.store, cub=self.feature.id, trust=self.feature.trust,
                            granted=self.feature.permissions.requests, kind=kind,
                            fields=fields, because=because, subject=subject,
                            run_uuid=self.run_uuid)

    def request(self, kind: str, fields: dict[str, Any], *, because: dict[str, Any] | None = None,
                subject: tuple[str, str | int] | None = None) -> int:
        """``ticket``'s old name (MR's word), kept for first-party code through 0.5.x."""
        return self.ticket(kind, fields, because=because, subject=subject)

    def withdraw(self, subject: tuple[str, str | int], note: str) -> int:
        """Close this feature's open tickets about one of its objects (dismissed, refreshed)."""
        return tickets.expire_for(self.store, cub=self.feature.id, subject_kind=subject[0],
                                  subject_id=subject[1], note=note)

    def tickets(self, subject: tuple[str, str | int] | None = None) -> list[dict[str, Any]]:
        return tickets.listing(self.store, cub=self.feature.id, subject=subject, limit=500)

    def prompt(self, name: str) -> Any:
        if name not in {p.id for p in self.feature.prompts}:
            raise PermissionDenied(f"{self.feature.id} did not declare the prompt {name}")
        from .. import prompts
        return prompts.load(name)

    def prompt_schema(self, name: str) -> dict[str, Any] | None:
        from .. import prompts
        return prompts.schema(name)

    def scrub(self, text: str) -> str:
        from ..scrub import scrub
        return scrub(text)

    # -- the run it is part of ----------------------------------------------------

    @contextmanager
    def run(self, kind: str, *, title: str | None = None,
            subject: tuple[Any, ...] | None = None, record: bool = True) -> Iterator[Any]:
        """A press that does work is a run: ``started`` now, its ``runs`` row and ``ended``
        when the block ends (``record``: the block's own code writes no row; the block may
        set ``run.result`` to the job's summary, its ``status`` the row's). The run takes
        this context's ``run_uuid``, so its model calls are its trace. Inside a run of the
        same kind already (the scheduler's), that run is used."""
        from .. import activity
        cur = activity.current()
        if cur is not None and cur.kind == kind:
            yield cur
            return
        from . import verbs
        origin = "press" if getattr(self, "door", None) in (None, "ui", "ui-token") else "owner"
        started = utcnow()
        # an assistant's verb (``core.verbs.acting``) says who in the run, else the door
        by = verbs.acting_by() or getattr(self, "door", None)
        with activity.run(self.store, kind, origin=origin, by=by,
                          title=title, subject=subject, uuid=self.run_uuid) as r:
            status, error, summary = "ok", None, {}
            try:
                yield r
            except Exception as exc:
                status, error = "failed", f"{type(exc).__name__}: {exc}"[:300]
                raise
            finally:
                if isinstance(r.result, dict) and status == "ok":
                    summary = dict(r.result)
                    got = summary.pop("status", "ok")
                    status = got if got in ("ok", "degraded", "failed", "skipped") else "ok"
                    # a failed or degraded result may say why (``error``): the run's reason
                    why = summary.get("error")
                    if status in ("failed", "degraded") and isinstance(why, str) and why:
                        error = str(summary.pop("error"))[:300]
                if r.stop_requested():
                    status = "skipped"
                    summary = {**summary, "stopped_by": r.stopped_by or "owner"}
                if record and self.store.query_one(
                        "SELECT 1 FROM runs WHERE run_uuid = ?", (self.run_uuid,)) is None:
                    record_run(self.store, kind, status, started, summary, error,
                               run_uuid=self.run_uuid)

    def progress(self, words: str | None = None, *, step: int | None = None,
                 steps: int | None = None, detail: dict[str, Any] | None = None) -> None:
        """How far the run is, in words ("source 2 of 5, arXiv"): a mark, never a wait."""
        from .. import activity
        activity.progress(words, step=step, steps=steps, detail=detail)

    def waiting(self, words: str, needs: dict[str, Any] | None = None, *,
                subject: tuple[Any, ...] | None = None) -> None:
        """The run stopped for the owner (proposals to follow): ``needs`` names the verb and
        where it is pressed (``{"verb": "Review", "href": "#/cub/radar?list=proposals"}``)."""
        from .. import activity
        activity.waiting(words, needs, subject=subject)

    def stop_requested(self) -> bool:
        """Whether the owner pressed Stop on this run: checked between its steps."""
        from .. import activity
        return activity.stop_requested()


def record_run(store: Store, kind: str, status: str, started: datetime, summary: dict[str, Any],
               error: str | None = None, run_uuid: str | None = None) -> str:
    """A ``runs`` row for a feature's job (due-ness reads them) and a ``job.finished`` event."""
    rid = run_uuid or uuid.uuid4().hex
    store.insert("runs", {"run_uuid": rid, "kind": kind, "status": status,
                          "started_at": iso(started), "finished_at": iso(utcnow()),
                          "summary": stored_runs.text_for(kind, summary), "error": error})
    events.core_publish(store, "job.finished", {"kind": kind, "status": status},
                        run_uuid=rid)
    return rid
