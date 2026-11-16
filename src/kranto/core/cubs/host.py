"""The host's side of a cub's calls (protocol): one ``CubHost`` a run.

Every call is checked in the protocol's order before it does anything: (1) its shape
(-32602, -32011); (2) the cub's state (-32003: paused, removed, disabled, ``cubs.enabled``
false, the ``cubs.STOP`` file); (3) the grant (-32001): ``bears_cub.grants.allow``, the same
function the SDK runs, then what only the host knows (an adapter operation's side, a request
kind registered and grantable to the cub's trust, a narrowed cub's topics); (4) the rate
windows and the caps (-32004, -32002). Then the call, and a ``cub_calls`` row (service, op,
status, ms, bytes in and out, the run, a scrubbed word or two; never a body). The cub's ``log``
calls go to its log, not to ``cub_calls``.

The host calls the same core functions first-party features use: the v1 reads
(``core.api.call``), the bus (``core.events``), the metered model client, live search, the
tickets, so a grant means the same thing for News and for a cub.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import timedelta

from bears_cub import grants as grant_table

from ...scrub import scrub
from ...store import iso, utcnow
from ...stored.misc import FeedbackReasons
from .. import api, events, tickets
from . import kv
from .process import RpcError

MODEL_PER_HOUR = 60
SEARCH_PER_HOUR = 30
HTTP_PER_HOUR = 60
PUBLISH_PER_HOUR = 200
READS_PER_RUN = 600
KV_PER_RUN = 2000
ANSWER_BYTES = 1_048_576
FETCH_BYTES = 2_097_152
FETCH_S = 20.0
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/rss+xml",
              "application/atom+xml")
RUN_COUNTED = {"reads.get": READS_PER_RUN, "events.read": READS_PER_RUN,
               "events.ack": READS_PER_RUN, "ticket.list": READS_PER_RUN,
               "ticket.get": READS_PER_RUN, "settings.get": READS_PER_RUN,
               "kv.get": KV_PER_RUN, "kv.put": KV_PER_RUN, "kv.delete": KV_PER_RUN,
               "kv.list": KV_PER_RUN}


def _err(code: int, message: str, **data) -> RpcError:
    return RpcError(code, message, data)


def _shape(params: dict, allowed: dict[str, tuple], required: tuple = ()) -> None:
    """``allowed``: key -> the types it takes. A key not listed, or of another type, -32602."""
    extra = sorted(set(params) - set(allowed))
    if extra:
        raise _err(-32602, f"no {', '.join(extra)} in this method's params")
    for k in required:
        if k not in params:
            raise _err(-32602, f"{k} is needed")
    for k, v in params.items():
        types = allowed[k]
        if v is None and type(None) in types:
            continue
        if isinstance(v, bool) and bool not in types:
            raise _err(-32602, f"{k} is not of the expected type")
        if not isinstance(v, tuple(t for t in types if t is not type(None))):
            raise _err(-32602, f"{k} is not of the expected type")


class CubHost:
    """``dispatch(method, params)`` answers one call of one run of one cub."""

    def __init__(self, runtime, cub, *, run_uuid: str, run_log, stage: bool = False) -> None:
        self.rt = runtime.rt
        self.runtime = runtime
        self.cub = cub                       # registry.Installed
        self.run_uuid = run_uuid
        self.log = run_log
        self.stage = stage
        self.counts: dict[str, int] = {}
        from ... import activity
        # the run this call serves (a job's): the owner's Stop is refused at its next call
        self.run = activity.find(run_uuid)

    @property
    def store(self):
        return self.rt.store

    # -- the one entry ----------------------------------------------------------------------------

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "log":
            return self._log(params)
        handler = getattr(self, "_m_" + method.replace(".", "_"), None)
        if handler is None:
            raise _err(-32601, f"no method {method} in cub/1")
        started = time.monotonic()
        service, op = self._service(method, params)
        bytes_in = len(json.dumps(params, default=str))
        status, detail, result = "ok", None, None
        try:
            halted = self.runtime.halted(self.cub)
            if halted:
                raise _err(-32003, f"halted: {halted}")
            if self.run is not None and self.run.stop_requested():
                raise _err(-32003, "halted: stopped by the owner")
            self._count(method)
            result = handler(params)
            out = json.dumps(result, default=str)
            if len(out.encode("utf-8")) >= ANSWER_BYTES:
                raise _err(-32011, "the answer is over 1 MiB", limit=ANSWER_BYTES)
            return result
        except RpcError as exc:
            status = {-32001: "refused", -32003: "refused", -32004: "rate_limited",
                      -32002: "refused", -32005: "refused", -32602: "refused",
                      -32009: "refused", -32006: "refused"}.get(exc.code, "error")
            if exc.code == -32008 and exc.message.startswith("destination not allowed"):
                status = "refused"
            detail = f"{exc.code} {exc.message}"
            raise
        finally:
            self._record(service, op, status, started, bytes_in,
                         len(json.dumps(result, default=str)) if result is not None else None,
                         detail)

    def _service(self, method: str, params: dict) -> tuple[str, str]:
        if method == "broker.call":
            return str(params.get("service") or "broker")[:40], str(params.get("op") or "")[:60]
        if method == "reads.get":
            return "reads", str(params.get("name") or "")[:60]
        if method == "search.run":
            return "search", str(params.get("kind") or "web")[:20]
        head, _, tail = method.partition(".")
        return {"model": "model", "http": "http"}.get(head, head), tail

    def _record(self, service: str, op: str, status: str, started: float, bytes_in: int,
                bytes_out: int | None, detail: str | None, ticket_id: int | None = None) -> None:
        self.store.insert("cub_calls", {
            "cub": self.cub.id, "service": service, "op": op, "status": status,
            "ticket_id": ticket_id, "run_uuid": self.run_uuid,
            "ms": int((time.monotonic() - started) * 1000), "bytes_in": bytes_in,
            "bytes_out": bytes_out, "detail": scrub(detail)[:300] if detail else None,
            "created_at": iso(utcnow())})

    def _count(self, method: str) -> None:
        cap = RUN_COUNTED.get(method)
        if cap is None:
            return
        family = "kv" if method.startswith("kv.") else "reads"
        self.counts[family] = self.counts.get(family, 0) + 1
        if self.counts[family] > cap:
            raise _err(-32004, f"{cap} {family} calls a run", retry_after_s=60)

    def _grant(self, method: str, params: dict) -> None:
        refused = grant_table.allow(self.cub.grants.wire(), method, params, stage=self.stage)
        if refused is not None:
            raise _err(*refused)

    def _window(self, service: str, *, hours: float, op: str | None = None,
                ok_only: bool = True) -> int:
        since = iso(utcnow() - timedelta(hours=hours))
        sql = "SELECT COUNT(*) AS n FROM cub_calls WHERE cub = ? AND service = ? AND " \
              "created_at >= ?"
        args: list = [self.cub.id, service, since]
        if op is not None:
            sql += " AND op = ?"
            args.append(op)
        if ok_only:
            sql += " AND status = 'ok'"
        return int(self.store.query_one(sql, tuple(args))["n"])

    def _per_hour(self, service: str, cap: int, op: str | None = None) -> None:
        if self._window(service, hours=1, op=op) >= cap:
            raise _err(-32004, f"{cap} {service} calls an hour", retry_after_s=600)

    def _calls_today(self) -> None:
        """Calls to your accounts and the web a day: ``cubs.<id>.calls_per_day`` (D6)."""
        from . import brokers
        cap = self.runtime.cub_value(self.cub, "calls_per_day")
        since = iso(utcnow() - timedelta(days=1))
        services = ["http", *brokers.ADAPTERS]
        marks = ",".join("?" * len(services))
        n = self.store.query_one(
            f"SELECT COUNT(*) AS n FROM cub_calls WHERE cub = ? AND created_at >= ? AND "
            f"status = 'ok' AND service IN ({marks})", (self.cub.id, since, *services))["n"]
        if n >= cap:
            raise _err(-32002, f"{self.cub.id} made {n} calls to your accounts and the web "
                               f"today (at most {cap})", limit=cap)

    # -- log, settings --------------------------------------------------------------------------

    def _log(self, p: dict) -> dict:
        _shape(p, {"level": (str,), "message": (str,), "data": (dict, type(None))},
               ("level", "message"))
        if p["level"] not in ("debug", "info", "warning", "error"):
            raise _err(-32602, "level is debug, info, warning or error")
        if len(p["message"]) > 4000 or len(json.dumps(p.get("data") or {})) > 4000:
            raise _err(-32011, "a log line is at most 4,000 characters")
        self.log.call(p["level"], p["message"], p.get("data"))
        return {}

    def _m_settings_get(self, p: dict) -> dict:
        _shape(p, {})
        from .. import settings as feature_settings
        values = feature_settings.section(self.rt.cfg, self.cub.id)
        return {"values": values,
                "core": {"live": self.runtime.live_kinds(self.cub),
                         "monthly_usd": self.runtime.cap_usd(self.cub),
                         "calls_per_day": self.runtime.cub_value(self.cub, "calls_per_day"),
                         "enabled": True, "trust": self.cub.trust}}

    # -- reads ----------------------------------------------------------------------------------

    def _m_reads_get(self, p: dict) -> dict:
        _shape(p, {"name": (str,), "params": (dict,)}, ("name",))
        name, params = p["name"], dict(p.get("params") or {})
        self._grant("reads.get", p)
        if name == "grades.mine":
            return self._grades(params)
        if name == "events.read":
            return self._m_events_read({k: v for k, v in params.items()
                                        if k in ("kind", "limit", "since")})
        if name not in api.reads():
            raise _err(-32601, f"no read {name}")
        from . import narrow
        try:
            return narrow.read(self, name, params)
        except api.ReadError as exc:
            raise _err({404: -32006, 403: -32001}.get(exc.code, -32602), str(exc)) from None

    def feature_context(self):
        from ..context import FeatureContext
        return FeatureContext(self.cub.feature, self.rt, run_uuid=self.run_uuid)

    def _grades(self, params: dict) -> dict:
        _shape(params, {"kind": (str, type(None)), "since": (str, type(None)),
                        "limit": (int, type(None))})
        n = int(params.get("limit") or 50)
        if not 1 <= n <= 200:
            raise _err(-32602, "limit is from 1 to 200")
        targets = list(self.cub.manifest.get("grades") or {})
        if params.get("kind"):
            targets = [t for t in targets if t == params["kind"]]
        if not targets:
            return {"grades": []}
        marks = ",".join("?" * len(targets))
        rows = self.store.query(
            f"SELECT id, target, target_id, value, reasons, note, created_at FROM feedback "
            f"WHERE target IN ({marks}) AND created_at >= ? ORDER BY id DESC LIMIT ?",
            (*targets, str(params.get("since") or ""), n))
        return {"grades": [{"id": r["id"], "target": f"cub:{self.cub.id}:{r['target']}",
                            "target_id": r["target_id"], "verdict": r["value"],
                            "chips": FeedbackReasons.load(r["reasons"]).items,
                            "line": api.fence(r["note"] or ""), "created_at": r["created_at"]}
                           for r in rows]}

    # -- events ---------------------------------------------------------------------------------

    def _sub(self, kind: str) -> dict:
        return next(s for s in self.cub.grants.events.subscribe if s.get("kind") == kind)

    def _m_events_read(self, p: dict) -> dict:
        _shape(p, {"kind": (str,), "limit": (int,), "since": (int,)}, ("kind",))
        self._grant("events.read", p)
        n = p.get("limit", 100)
        if not 1 <= n <= 100:
            raise _err(-32602, "limit is from 1 to 100")
        sub = self._sub(p["kind"])
        cursor = events.cursor(self.store, self.cub.id, p["kind"])
        since = p["since"] if p.get("since") is not None else cursor
        rows = events.read(self.store, since=since, kinds=[p["kind"]],
                           min_trust=sub.get("min_trust", "unreviewed"), limit=n + 1)
        out = [{k: e[k] for k in ("id", "ts", "kind", "feature", "trust", "subject_kind",
                                  "subject_id", "payload")} for e in rows[:n]]
        return {"events": out, "cursor": cursor, "more": len(rows) > n}

    def _m_events_ack(self, p: dict) -> dict:
        _shape(p, {"kind": (str,), "last_id": (int,)}, ("kind", "last_id"))
        self._grant("events.ack", p)
        events.advance(self.store, self.cub.id, p["kind"], p["last_id"])
        return {"cursor": events.cursor(self.store, self.cub.id, p["kind"])}

    def _m_events_publish(self, p: dict) -> dict:
        _shape(p, {"kind": (str,), "payload": (dict,), "subject": (dict, type(None)),
                   "dedupe": (str, type(None))}, ("kind", "payload"))
        self._grant("events.publish", p)
        subject = p.get("subject")
        if subject is not None and (set(subject) != {"kind", "id"} or not isinstance(
                subject["kind"], str) or not isinstance(subject["id"], str | int)):
            raise _err(-32602, "subject is {kind, id}")
        key = p.get("dedupe")
        if key is not None and (not key or len(key) > 80):
            raise _err(-32602, "dedupe is text of 1 to 80 characters")
        try:
            events._check_payload(p["payload"])
        except events.EventError as exc:
            raise _err(-32005, str(exc)) from None
        if key is not None:
            got = self.store.query_one("SELECT event_id FROM cub_dedupe WHERE cub = ? AND "
                                       "key = ?", (self.cub.id, key))
            if got is not None:
                return {"event_id": int(got["event_id"]), "duplicate": True}
        self._per_hour("events", PUBLISH_PER_HOUR, op="publish")
        with self.store.tx():
            eid = events.publish(self.store, feature=self.cub.id, trust=self.cub.trust,
                                 kind=p["kind"], payload=p["payload"],
                                 subject=(subject["kind"], subject["id"]) if subject else None,
                                 run_uuid=self.run_uuid, origin="cub",
                                 declared=tuple(self.cub.grants.events.publish))
            if key is not None:
                self.store.insert("cub_dedupe", {"cub": self.cub.id, "key": key,
                                                 "event_id": eid, "created_at": iso(utcnow())})
        return {"event_id": eid, "duplicate": False}

    # -- the model, search, the web -------------------------------------------------------------

    def _m_model_complete(self, p: dict) -> dict:
        self._grant("model.complete", p)       # an unknown key is "no tools, no model"
        _shape(p, {"purpose": (str,), "tier": (str,), "messages": (list,),
                   "max_tokens": (int,), "temperature": (int, float), "schema": (dict, type(None)),
                   "retry_truncated": (bool,)}, ("purpose", "tier", "messages"))
        msgs = p["messages"]
        if not 1 <= len(msgs) <= 20 or not all(
                isinstance(m, dict) and set(m) == {"role", "content"}
                and m["role"] in ("system", "user", "assistant") and isinstance(m["content"], str)
                for m in msgs):
            raise _err(-32602, "messages: 1 to 20 of {role, content}, content as text")
        if sum(len(m["content"]) for m in msgs) > 400000:
            raise _err(-32011, "messages are over 400,000 characters", limit=400000)
        max_tokens = p.get("max_tokens", 800)
        temperature = p.get("temperature", 0.2)
        if not 1 <= max_tokens <= 4096 or not 0 <= temperature <= 1:
            raise _err(-32602, "max_tokens is 1 to 4096 and temperature 0 to 1")
        self._per_hour("model", MODEL_PER_HOUR)
        cap = self.runtime.cap_usd(self.cub)
        spent = api.spend_of(self.store, self.cub.feature)["month_usd"]
        if cap is not None and spent >= cap:
            self.runtime.capped(self.cub, cap)
            raise _err(-32002, f"{self.cub.id} has spent ${spent:.2f} of its ${cap:.2f} this "
                               "month", spent_usd=round(spent, 6), cap_usd=cap)
        # a posting cub's own model, when the owner set one for this writer:
        # through the same metered client, on a provider the tiers may not use
        own = self._writer_model()
        try:
            got = self.rt.llm.complete(
                tier=p["tier"], purpose=p["purpose"], messages=msgs,
                prompt_version=f"cub:{self.cub.id}@{self.cub.version}", run_uuid=self.run_uuid,
                max_tokens=max_tokens, temperature=temperature, schema=p.get("schema"),
                retry_truncated=bool(p.get("retry_truncated")),
                **({"provider": own["provider"], "model": own["model"]} if own else {}))
        except Exception as exc:  # noqa: BLE001 - the provider's refusal, in words
            # a refused key keeps its cause (the client's message, scrubbed of the key), so the
            # cub's failed run joins the key's incident; other errors say the class
            from ...llm import FatalLLMError
            why = f": {str(exc)[:300]}" if isinstance(exc, FatalLLMError) and str(exc) else ""
            raise _err(-32008, f"the model did not answer: {type(exc).__name__}{why}") from None
        return {"text": got.text, "structured": got.structured, "model": got.model,
                "prompt_tokens": got.prompt_tokens, "completion_tokens": got.completion_tokens,
                "cost_usd": got.cost_usd, "equiv_usd": got.equiv_usd, "call_id": got.call_id,
                "truncated": False}

    # -- the prose engine: the person's voice and Kranto's floor ---------------

    # ``sources`` (SDK 1.4): the material the text was written from, so the checker's
    # ``salt.person`` can flag a person's name or a handle the material does not have
    _PROSE_COMMON = {"site": (str, type(None)), "kind": (str, type(None)),
                     "limits": (dict, type(None)), "take": (str, type(None)),
                     "sources": (str, type(None))}

    def _prose_profile(self):
        from ... import prose
        return prose.load(self.rt.cfg, self.store)

    def _writer_model(self) -> dict[str, str] | None:
        """``{provider, model}`` the owner chose for this writer (Kranto's own blog, toot and
        newsletter cubs), else None: the tier's model. Read from the prose profile's row only
        (no file, no secret); a profile that does not load is the tier's model."""
        from ...prose.profile import WRITER_SITE, clean_writers, load_row
        if self.cub.id not in WRITER_SITE:
            return None
        try:
            return clean_writers(load_row(self.store).writers).get(self.cub.id)
        except Exception:  # noqa: BLE001 - a bad row is the default, never a failed post
            return None

    def _m_prose_compose(self, p: dict) -> dict:
        self._grant("prose.compose", p)
        _shape(p, {"material": (dict,), "site": (str, type(None)), "kind": (str, type(None)),
                   "task": (str, type(None)), "language": (str, type(None)),
                   "limits": (dict, type(None)), "features": (str, type(None))}, ("material",))
        material = p["material"]
        if set(material) - {"angle", "take", "title", "facts", "format", "hint", "form"} or \
                not all(isinstance(v, str | type(None)) for v in material.values()):
            raise _err(-32602, "material holds angle (or take), title, facts, format, hint "
                               "and form, as text")
        if len(json.dumps(p)) > 200_000:
            raise _err(-32011, "the material is over 200,000 characters", limit=200_000)
        from ... import prose
        profile = self._prose_profile()
        msgs = prose.compose(material, p.get("site"), profile, task=p.get("task") or "",
                             kind=p.get("kind"), language=p.get("language"),
                             limits=p.get("limits"), features=p.get("features"),
                             embedder=getattr(self.rt, "embedder", None))
        site = p.get("site") or ""
        from ...prose.composer import angle_of
        return {"messages": msgs, "take": profile.take, "angle": angle_of(material) or None,
                "disclosure": profile.disclosure.get(site) or None}

    def _m_prose_check(self, p: dict) -> dict:
        self._grant("prose.check", p)
        _shape(p, {"text": (str,), **self._PROSE_COMMON}, ("text",))
        if len(p["text"]) > 100_000:
            raise _err(-32011, "the text is over 100,000 characters", limit=100_000)
        self._sources_fit(p)
        from ... import prose
        return prose.check(p["text"], p.get("site"), self._prose_profile(), kind=p.get("kind"),
                           limits=p.get("limits"), take=p.get("take"), sources=p.get("sources"))

    @staticmethod
    def _sources_fit(p: dict) -> None:
        if len(p.get("sources") or "") > 100_000:
            raise _err(-32011, "the sources are over 100,000 characters", limit=100_000)

    def _m_prose_revise(self, p: dict) -> dict:
        self._grant("prose.revise", p)
        _shape(p, {"text": (str,), "flags": (list, type(None)), "purpose": (str,),
                   "tier": (str,), **self._PROSE_COMMON}, ("text", "purpose", "tier"))
        if len(p["text"]) > 100_000:
            raise _err(-32011, "the text is over 100,000 characters", limit=100_000)
        self._sources_fit(p)
        from ... import prose
        profile = self._prose_profile()
        flags = p.get("flags")
        if flags is None or not all(isinstance(f, dict) and isinstance(f.get("start"), int)
                                    and isinstance(f.get("end"), int) for f in flags):
            # the cub's own flags are not trusted for offsets: the host checks again
            flags = prose.check(p["text"], p.get("site"), profile, kind=p.get("kind"),
                                limits=p.get("limits"), take=p.get("take"),
                                sources=p.get("sources"))["flags"]

        def complete(messages: list[dict], schema: dict) -> dict:
            # one model call under the cub's purpose, tier, hourly window and cap, recorded
            # in cub_calls as the cub's model call is
            started = time.monotonic()
            status, detail = "ok", None
            try:
                return self._m_model_complete({
                    "purpose": p["purpose"], "tier": p["tier"], "messages": messages,
                    "max_tokens": 1500, "temperature": 0.2, "schema": schema})
            except RpcError as exc:
                status, detail = "refused" if exc.code in (-32001, -32002, -32004) \
                    else "error", f"{exc.code} {exc.message}"
                raise
            finally:
                self._record("model", "complete", status, started, 0, None, detail)

        return prose.revise(p["text"], flags, profile, complete=complete, site=p.get("site"),
                            kind=p.get("kind"), limits=p.get("limits"), take=p.get("take"))

    def _m_search_run(self, p: dict) -> dict:
        _shape(p, {"q": (str,), "kind": (str,), "recency": (str, type(None)), "n": (int,)},
               ("q",))
        self._grant("search.run", p)
        if len(p["q"]) > 300 or p.get("recency") not in (None, "day", "week", "month", "year") \
                or not 1 <= p.get("n", 10) <= 20:
            raise _err(-32602, "q is at most 300 characters, recency day/week/month/year, "
                               "n 1 to 20")
        self._per_hour("search", SEARCH_PER_HOUR)
        from ... import websearch
        searcher = self.runtime.searcher(self.cub.id) or websearch.for_runtime(
            self.rt, caller=self.cub.id)
        res = searcher.search(p["q"], kind=p.get("kind", "web"), recency=p.get("recency"),
                              n=p.get("n", 10))
        hits = [{"label": label, "url": h.url, "title": api.fence(h.title), "date": h.date,
                 "snippet": api.fence(h.snippet), "backend": h.backend, "rank": h.rank}
                for label, h in res.numbered()]
        return {"query": res.query, "live": res.live, "backend": res.backend,
                "searched_at": res.searched_at, "note": res.note, "hits": hits,
                "block": res.block()}

    def _m_http_fetch(self, p: dict) -> dict:
        _shape(p, {"url": (str,), "headers": (dict,), "max_bytes": (int,)}, ("url",))
        self._grant("http.fetch", p)
        headers = p.get("headers") or {}
        if set(headers) - {"Accept", "Accept-Language"} or not all(
                isinstance(v, str) and len(v) <= 200 for v in headers.values()):
            raise _err(-32602, "headers are Accept and Accept-Language only")
        cap = p.get("max_bytes", FETCH_BYTES)
        if not 1 <= cap <= FETCH_BYTES:
            raise _err(-32602, f"max_bytes is 1 to {FETCH_BYTES}")
        self._per_hour("http", HTTP_PER_HOUR)
        self._calls_today()
        hosts = self.cub.grants.http.hosts
        return fetch(self.runtime, self.cub.id, p["url"], hosts, headers, cap)

    # -- brokers --------------------------------------------------------------------------------

    def _m_broker_call(self, p: dict) -> dict:
        _shape(p, {"service": (str,), "op": (str,), "args": (dict,)}, ("service", "op"))
        self._grant("broker.call", p)
        from . import brokers
        adapter = brokers.ADAPTERS.get(p["service"])
        spec = adapter.ops.get(p["op"]) if adapter is not None else None
        if spec is None or p["op"] not in brokers.grantable().get(p["service"], ()):
            raise _err(-32001, f"{p['service']} {p['op']} is not an operation a cub may be "
                               "granted")
        return brokers.call(self, adapter, spec, dict(p.get("args") or {}))

    # -- tickets --------------------------------------------------------------------------------

    def _m_ticket_file(self, p: dict) -> dict:
        _shape(p, {"kind": (str,), "fields": (dict,), "because": (dict, type(None)),
                   "subject": (dict, type(None))}, ("kind", "fields"))
        self._grant("ticket.file", p)
        kind = p["kind"]
        if not tickets.grantable_to(kind, self.cub.trust):
            raise _err(-32001, f"{kind} is not an action a {self.cub.trust} cub may ask for")
        subject = p.get("subject")
        if subject is not None and set(subject) != {"kind", "id"}:
            raise _err(-32602, "subject is {kind, id}")
        spec = tickets.KINDS[kind]
        own_cap = self.runtime.cub_value(self.cub, "tickets_per_day")
        per_day = spec.per_day if own_cap is None else min(own_cap, spec.per_day)
        self._flood(kind, per_day)
        try:
            tid = tickets.file(self.store, cub=self.cub.id, trust=self.cub.trust,
                               granted=tuple(self.cub.grants.requests), kind=kind,
                               fields=p["fields"], because=p.get("because"),
                               subject=(subject["kind"], subject["id"]) if subject else None,
                               run_uuid=self.run_uuid, per_day=per_day)
        except tickets.TicketError as exc:
            if exc.code == 409 and exc.ticket_id:
                raise _err(-32009, str(exc), ticket_id=exc.ticket_id) from None
            if exc.code == 429:
                raise _err(-32004, str(exc), retry_after_s=3600) from None
            if exc.code == 403:
                raise _err(-32001, str(exc)) from None
            raise _err(-32005, str(exc)) from None
        t = tickets.get(self.store, tid)
        mode, _ = tickets.press_mode(self.store, self.rt.cfg, t)
        return {"ticket_id": tid, "state": t["state"], "expires_at": t["expires_at"],
                "mode": mode}

    def _flood(self, kind: str, per_day: int) -> None:
        """Three times a kind's daily cap in a day pauses the cub."""
        since = iso(utcnow() - timedelta(days=1))
        tried = self.store.query_one(
            "SELECT COUNT(*) AS n FROM cub_calls WHERE cub = ? AND service = 'ticket' AND "
            "op = 'file' AND created_at >= ?", (self.cub.id, since))["n"]
        if tried + 1 >= 3 * per_day:
            self.runtime.pause(self.cub, "it asked for your approval too many times in a "
                                         "day")

    def _ticket_view(self, t: dict) -> dict:
        mode, _ = tickets.press_mode(self.store, self.rt.cfg, t)
        return {"id": t["id"], "kind": t["kind"], "state": t["state"], "fields": t["fields"],
                "because": t["because"], "subject_kind": t["subject_kind"],
                "subject_id": t["subject_id"], "note": t["note"], "expires_at": t["expires_at"],
                "created_at": t["created_at"], "resolved_at": t["resolved_at"], "mode": mode}

    def _m_ticket_list(self, p: dict) -> dict:
        _shape(p, {"subject": (dict, type(None)), "open": (bool,), "limit": (int,)})
        n = p.get("limit", 50)
        if not 1 <= n <= 100:
            raise _err(-32602, "limit is from 1 to 100")
        subject = p.get("subject")
        rows = tickets.listing(self.store, cub=self.cub.id, open_only=bool(p.get("open")),
                               subject=(subject["kind"], subject["id"]) if subject else None,
                               limit=n)
        return {"tickets": [self._ticket_view(t) for t in rows]}

    def _m_ticket_get(self, p: dict) -> dict:
        _shape(p, {"ticket_id": (int,)}, ("ticket_id",))
        t = tickets.get(self.store, p["ticket_id"])
        if t is None or t["cub"] != self.cub.id:
            raise _err(-32006, f"no ticket #{p['ticket_id']} of {self.cub.id}")
        return self._ticket_view(t)

    def _m_ticket_withdraw(self, p: dict) -> dict:
        _shape(p, {"subject": (dict,), "note": (str,)}, ("subject",))
        s = p["subject"]
        if set(s) != {"kind", "id"}:
            raise _err(-32602, "subject is {kind, id}")
        n = tickets.expire_for(self.store, cub=self.cub.id, subject_kind=str(s["kind"]),
                               subject_id=s["id"], note=str(p.get("note") or "withdrawn")[:200])
        return {"expired": n}

    # -- the store ------------------------------------------------------------------------------

    def _kv(self, fn, *args, **kw) -> dict:
        try:
            return fn(self.store, self.cub.id, *args, **kw)
        except kv.KVError as exc:
            raise RpcError(exc.code, exc.message, exc.data) from None

    def _m_kv_get(self, p: dict) -> dict:
        _shape(p, {"key": (str,)}, ("key",))
        self._grant("kv.get", p)
        return self._kv(kv.get, p["key"])

    def _m_kv_put(self, p: dict) -> dict:
        _shape(p, {"key": (str,), "value": (dict, list, str, int, float, bool, type(None))},
               ("key", "value"))
        self._grant("kv.put", p)
        quota = self.runtime.cub_value(self.cub, "kv_mb") * 1024 * 1024
        return self._kv(kv.put, p["key"], p["value"], quota_bytes=quota)

    def _m_kv_delete(self, p: dict) -> dict:
        _shape(p, {"key": (str,)}, ("key",))
        self._grant("kv.delete", p)
        return self._kv(kv.delete, p["key"])

    def _m_kv_list(self, p: dict) -> dict:
        _shape(p, {"prefix": (str,), "after": (str, type(None)), "limit": (int,)})
        self._grant("kv.list", p)
        return self._kv(kv.listing, prefix=p.get("prefix", ""), after=p.get("after"),
                        limit=p.get("limit", 100))


def fetch(runtime, cid: str, url: str, hosts, headers: dict, cap: int, *,
          agent: str = "kranto-cub/1") -> dict:
    """A GET Kranto performs for a cub (protocol): public addresses only (a declared name
    that resolves to a private address is refused), at most 3 redirects each to a declared
    host over https, 20 s, ``cap`` bytes, no credential, the cub's name in the User-Agent.

    ``hosts`` None: any host on the public web (a feature's ``ctx.fetch``, whose URL is one its
    own reads handed it); every other rule holds, each redirect's included."""
    import httpx

    from ...sources.base import SourceError, check_public_url
    started = time.monotonic()
    sent = {"User-Agent": f"{agent} ({cid})", **headers}
    for _ in range(4):
        refused = grant_table.check_url(url, hosts if hosts is not None else [_host(url)])
        if refused is not None:
            raise _err(*refused)
        try:
            check_public_url(url, resolver=runtime.resolver)
        except SourceError:
            raise _err(-32008, "destination not allowed: the name resolves to a private "
                               "address") from None
        left = FETCH_S - (time.monotonic() - started)
        if left <= 0:
            raise _err(-32007, "no answer in 20 s")
        try:
            with runtime.http_client().stream("GET", url, headers=sent,
                                              timeout=left) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = str(resp.url.join(resp.headers["location"]))
                    continue
                body, truncated = b"", False
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > cap:
                        body, truncated = body[:cap], True
                        break
                    if time.monotonic() - started > FETCH_S:
                        raise _err(-32007, "no answer in 20 s")
                status, ctype = resp.status_code, resp.headers.get("content-type")
                final = str(resp.url)
        except httpx.TimeoutException:
            raise _err(-32007, "no answer in 20 s") from None
        except httpx.HTTPError as exc:
            raise _err(-32008, f"the fetch failed: {type(exc).__name__}") from None
        is_text = bool(ctype) and ctype.split(";")[0].strip().lower().startswith(TEXT_TYPES)
        text = body.decode("utf-8", "replace") if is_text else None
        if text is not None:
            from bears_cub.fence import _defang
            text = _defang(text)
        out = {"status": status, "url": final, "content_type": ctype, "bytes": len(body),
               "truncated": truncated, "text": text,
               "body_b64": None if is_text else base64.b64encode(body).decode()}
        if not 200 <= status < 300:
            raise _err(-32008, f"the service answered {status}", status=status,
                       text=(text or "")[:4000])
        return out
    raise _err(-32008, "too many redirects")


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
