"""The broker adapter interface and the dispatcher.

An adapter is one service Kranto performs typed operations on with the owner's credential:
``ops`` (each ``read``, ``draft`` or ``perform``), the ticket ``kinds`` it performs, and its
``call``, ``perform`` and ``readback``. A cub may be granted ``read`` and ``draft`` operations;
``perform`` runs only from ``core.tickets.confirm``, the owner's press.

``run_op`` is the host's ``broker.call``: the op's arguments (-32005), the credential when the
op needs one (-32013), the rate windows (-32004: reads an hour, drafts a day, counted from the
cub's ``cub_calls`` rows), the cub's calls a day (-32002), the call under a 60 s deadline
(-32007), the service's refusal (-32008, with its status and code) and the result's size
(-32011). The credential is looked up at send time through ``Connections`` and added to the
request by the HTTP layer; it is never cached across calls and never passed to the cub. The
host's dispatcher writes the call's ``cub_calls`` row; a perform's row (with ``ticket_id``) is
written here.

Every request a broker sends carries a deadline, which also turns off the HTTP layer's own
retries: a send is never sent twice by Kranto. A send whose answer did not come is ``unknown``
(the owner looks at the service), never retried.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta

from bears_cub.kinds import check_value

from ....scrub import scrub
from ....sources.base import SourceError
from ....store import iso, utcnow

OP_DEADLINE_S = 60.0
RESULT_MAX_BYTES = 262144


class BrokerError(Exception):
    """A refusal in the protocol's words: ``code`` (-32005, -32006, -32008, -32013, ...)."""

    def __init__(self, code: int, message: str, **data) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


@dataclass(frozen=True)
class Op:
    """One operation. ``args``: name -> ``(type, rules, required)``, the shape
    ``bears_cub.kinds.BROKER`` uses (a test holds the two equal)."""

    name: str
    side: str                          # read | draft
    args: dict = field(default_factory=dict)
    needs_credential: bool = False
    per_hour: int | None = None        # the read window
    per_day: int | None = None         # the draft window
    result_max_bytes: int = RESULT_MAX_BYTES


def check_args(op: Op, args: dict) -> dict:
    """``args`` checked against the op's schema (-32005), with nothing added."""
    if not isinstance(args, dict):
        raise BrokerError(-32005, "args is an object")
    unknown = sorted(set(args) - set(op.args))
    if unknown:
        raise BrokerError(-32005, f"{op.name} takes no {', '.join(unknown)}")
    for key, (ftype, rules, required) in op.args.items():
        if key not in args:
            if required:
                raise BrokerError(-32005, f"{op.name} needs {key}")
            continue
        problem = check_value(f"{op.name}.{key}", args[key], ftype, rules)
        if problem:
            raise BrokerError(-32005, problem)
    return dict(args)


# -- the connection -------------------------------------------------------------------------------


def connection_of(store, provider: str | None) -> dict | None:
    """The newest live connection of ``provider`` (``connected`` or ``needs_login``), from the
    library rows only: no secret is read. A newsletter platform and Mastodon posting are one per
    Kranto."""
    if not provider:
        return None
    for row in store.query("SELECT * FROM connections WHERE provider = ? ORDER BY id DESC",
                           (provider,)):
        st = store.query_one(
            "SELECT event, note FROM connection_events WHERE connection_id = ? AND event IN "
            "('connected', 'needs_login', 'disconnected') ORDER BY id DESC LIMIT 1", (row["id"],))
        if st is not None and st["event"] in ("connected", "needs_login"):
            return {**dict(row), "state": st["event"], "note": st["note"]}
    return None


@dataclass
class BrokerContext:
    """What an adapter's call or perform gets: never a credential, only a way to send with one."""

    store: object
    cub: str
    rt: object = None
    connection: dict | None = None
    run_uuid: str | None = None
    ticket_id: int | None = None
    provider: str | None = None
    title: str | None = None           # the service's name in words, when it is chosen per call

    @property
    def connected(self) -> bool:
        """A usable connection: connected (not needing a login) and connections on here."""
        conns = getattr(self.rt, "connections", None)
        return (self.connection is not None and self.connection["state"] == "connected"
                and conns is not None and conns.unavailable() is None)

    @property
    def label(self) -> str | None:
        return self.connection["account"] if self.connection else None

    @property
    def instance(self) -> str | None:
        return self.connection["instance"] if self.connection else None

    def send(self, method: str, url: str, *, json: dict | None = None, data: dict | None = None,
             headers: dict | None = None, params: dict | None = None):
        """One request with the connection's credential added by the HTTP layer at send time.
        A 4xx reply is returned (the adapter reads its code); a 401, a throttle, a 5xx, a
        timeout or a refused address raise ``SourceError``. On the preview only a GET leaves:
        anything else is refused as not sent."""
        from .... import preview
        if method != "GET" and preview.enabled(getattr(getattr(self.rt, "cfg", None), "root",
                                                       None)):
            raise SourceError(f"{preview.NOTHING_SENT} ({method} {self.provider or 'service'})",
                              transient=False, sent=False)
        conns = self.rt.connections
        http = conns.http_for(self.provider, self.instance, self.rt.http)
        if method == "GET":
            return http.get(url, params=params, headers=headers, deadline=OP_DEADLINE_S,
                            errors=False)
        if method == "POST":
            return http.post(url, json=json, data=data, headers=headers,
                             deadline=OP_DEADLINE_S, errors=False)
        if method == "PATCH":
            return http.patch(url, json=json, headers=headers, deadline=OP_DEADLINE_S,
                              errors=False)
        raise ValueError(f"no {method} for a broker")


def op_error(exc: SourceError, service: str) -> BrokerError:
    """A failed request of a read or draft op in the protocol's words."""
    if exc.needs_login:
        return BrokerError(-32013, f"{service} refused the connection's credential (HTTP 401): "
                                   "reconnect it on Settings › Connections")
    if exc.status is not None:
        return BrokerError(-32008, f"{service} answered {exc.status}", status=exc.status)
    text = str(exc)
    if "Timeout" in text or "no complete response" in text:
        return BrokerError(-32007, f"{service} did not answer in {OP_DEADLINE_S:.0f} s")
    if not exc.sent:
        why = scrub(text.split(": ", 1)[-1])[:120]
        return BrokerError(-32008, f"{service} was not asked: {why}")
    return BrokerError(-32008, f"the request to {service} failed")


def reply_code(response) -> str | None:
    """A service's error code from a JSON reply (``{"code": "body_contains_frontmatter"}``),
    only when it is a short slug: never free text the service may have quoted from the body."""
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    if isinstance(code, str) and 0 < len(code) <= 60 and all(
            c.isalnum() or c in "_-." for c in code):
        return code
    return None


# -- drafts ---------------------------------------------------------------------------------------


def content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def new_draft(store, *, cub: str, service: str, content: dict, run_uuid: str | None,
              ref: str | None = None, external_id: str | None = None) -> dict:
    """A ``cub_drafts`` row: ``ref`` is the service's (``bd:<id>``) or, for a draft only Kranto
    holds, ``draft:<row id>`` (the id chosen inside the write so the ref names its own row)."""
    now = iso(utcnow())
    with store.tx():
        seq = store.query_one("SELECT seq FROM sqlite_sequence WHERE name = 'cub_drafts'")
        top = store.query_one("SELECT MAX(id) AS n FROM cub_drafts")
        rid = max(int(seq["seq"]) if seq else 0, int(top["n"] or 0)) + 1
        row = {"id": rid, "cub": cub, "service": service, "ref": ref or f"draft:{rid}",
               "content": json.dumps(content, sort_keys=True),
               "content_hash": content_hash(content),
               "external_id": external_id, "run_uuid": run_uuid, "created_at": now}
        store.insert("cub_drafts", row)
    return {**row, "content": dict(content)}


def draft_of(store, ref: str) -> dict | None:
    r = store.query_one("SELECT * FROM cub_drafts WHERE ref = ?", (ref,))
    if r is None:
        return None
    return {**dict(r), "content": json.loads(r["content"])}


def _services(service: str | tuple[str, ...]) -> tuple[str, ...]:
    """A service's names: one, or the neutral one with its aliases (the newsletter's)."""
    return (service,) if isinstance(service, str) else tuple(service)


def own_draft(store, cub: str, service: str | tuple[str, ...], ref) -> dict:
    """The cub's own draft of this service, or -32005 (the ref is not one of its drafts)."""
    d = draft_of(store, ref) if isinstance(ref, str) else None
    if d is None or d["cub"] != cub or d["service"] not in _services(service):
        raise BrokerError(-32005, f"draft_ref: {ref} is not one of {cub}'s drafts")
    return d


def drafts_list(store, cub: str, service: str | tuple[str, ...], limit: int,
                title: str) -> dict:
    names = _services(service)
    marks = ",".join("?" * len(names))
    rows = store.query(f"SELECT * FROM cub_drafts WHERE cub = ? AND service IN ({marks}) "
                       "ORDER BY id DESC LIMIT ?", (cub, *names, int(limit)))
    return {"drafts": [{"draft_ref": r["ref"], title: json.loads(r["content"]).get(title),
                        "created_at": r["created_at"]} for r in reversed(rows)]}


def press_draft(store, ticket: dict, service: str | tuple[str, ...],
                matches: tuple[str, ...]) -> dict | str:
    """The draft a ticket names, or why the press is refused: it must be the filing cub's, of
    this service, unchanged since it was written, and say what the ticket says (``matches``:
    the fields the owner read in the dialog)."""
    d = draft_of(store, ticket["fields"].get("draft_ref") or "")
    if d is None or d["cub"] != ticket["cub"] or d["service"] not in _services(service):
        return "the draft is not this cub's"
    if content_hash(d["content"]) != d["content_hash"]:
        return "the draft changed"
    for name in matches:
        if d["content"].get(name) != ticket["fields"].get(name):
            return "the draft changed: its " + name + " is not what you were shown"
    return d


# -- the dispatcher -------------------------------------------------------------------------------


def _window(host, adapter, op: Op) -> None:
    same = [o.name for o in adapter.ops.values() if o.side == op.side]
    if op.side == "draft":
        cap, hours, word, retry = op.per_day or 20, 24, "drafts a day", 3600
    else:
        cap, hours, word, retry = op.per_hour or 60, 1, "reads an hour", 600
    since = iso(utcnow() - timedelta(hours=hours))
    marks = ",".join("?" * len(same))
    n = host.store.query_one(
        f"SELECT COUNT(*) AS n FROM cub_calls WHERE cub = ? AND service = ? AND status = 'ok' "
        f"AND created_at >= ? AND op IN ({marks})",
        (host.cub.id, adapter.service, since, *same))["n"]
    if n >= cap:
        raise BrokerError(-32004, f"{adapter.service}: {cap} {word}", retry_after_s=retry)


def run_op(host, adapter, op: Op, args: dict) -> dict:
    """One granted read or draft operation for a cub's run (``broker.call``)."""
    from ..process import RpcError

    try:
        args = check_args(op, args)
        ctx = BrokerContext(store=host.store, cub=host.cub.id, rt=host.rt,
                            connection=connection_of(host.store, adapter.provider),
                            run_uuid=host.run_uuid, provider=adapter.provider)
        if hasattr(adapter, "bind"):
            ctx = adapter.bind(ctx)          # a service whose platform comes from config
        if op.needs_credential and not ctx.connected:
            raise BrokerError(-32013, not_connected(adapter, ctx))
        _window(host, adapter, op)
        host._calls_today()
        try:
            result = adapter.call(op.name, args, ctx)
        except SourceError as exc:
            raise op_error(exc, ctx.title or adapter.title) from None
        size = len(json.dumps(result, default=str).encode())
        if size > op.result_max_bytes:
            raise BrokerError(-32011, f"{adapter.service} {op.name}: the result is over "
                                      f"{op.result_max_bytes} bytes", limit=op.result_max_bytes)
        return result
    except BrokerError as exc:
        raise RpcError(exc.code, exc.message, exc.data) from None


def not_connected(adapter, ctx: BrokerContext) -> str:
    title = ctx.title or adapter.title
    if ctx.connection is not None and ctx.connection["state"] == "needs_login":
        return f"{title} needs you to reconnect it (Settings › Accounts)"
    return f"{title} is not connected"


# -- the performer --------------------------------------------------------------------------------


def performer(adapter):
    """``core.tickets``' performer for the adapter's kinds: the press's mode, the connection,
    the adapter's ``perform``, and a ``cub_calls`` row with the ticket's id."""

    def press(store, ticket: dict, context, mode: str = "dry") -> dict:
        started = time.monotonic()
        ctx = BrokerContext(store=store, cub=ticket["cub"], rt=context,
                            connection=connection_of(store, adapter.provider),
                            run_uuid=ticket.get("run_uuid"), ticket_id=int(ticket["id"]),
                            provider=adapter.provider)
        if hasattr(adapter, "bind"):
            ctx = adapter.bind(ctx, ticket=ticket)
        outcome = {"state": "unknown", "note": "the performer did not finish"}
        try:
            outcome = adapter.perform(ticket["kind"], ticket, mode, ctx)
            return outcome
        finally:
            store.insert("cub_calls", {
                "cub": ticket["cub"], "service": adapter.service, "op": ticket["kind"],
                "status": outcome.get("state", "unknown"), "ticket_id": int(ticket["id"]),
                "run_uuid": ticket.get("run_uuid"),
                "ms": int((time.monotonic() - started) * 1000), "bytes_in": None,
                "bytes_out": None, "detail": scrub(str(outcome.get("note") or ""))[:300] or None,
                "created_at": iso(utcnow())})

    return press


def outcome_of(exc: SourceError, service: str, *, sending: str) -> dict:
    """A failed send in the ticket's words: refused when the service said no or the request
    never left; ``unknown`` when it may have been sent (a timeout, a 5xx, a dropped line)."""
    if exc.needs_login:
        return {"state": "refused", "note": f"refused: {service} refused the credential (HTTP "
                                            "401); reconnect it on Settings › Connections"}
    if exc.status == 429:
        return {"state": "refused", "note": f"refused: rate limited by {service}"}
    if exc.status is not None and 400 <= exc.status < 500:
        return {"state": "refused", "note": f"refused: {service} answered {exc.status}"}
    if not exc.sent:
        return {"state": "refused", "note": f"refused: the request was not sent ("
                                            f"{scrub(str(exc).split(': ', 1)[-1])[:120]})"}
    why = f"{service} answered {exc.status}" if exc.status else f"no answer from {service}"
    return {"state": "unknown", "note": f"unknown: {why}; look at {service} to see whether "
                                        f"{sending} before doing anything else"}
