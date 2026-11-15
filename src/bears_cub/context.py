"""``ctx``: what a cub's handler is given. Every method is one ``cub/1`` call to
the host (protocol), checked first against the grants the host sent at ``hello``: a call
outside them raises ``NotGranted`` here, before anything is written to the pipe."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import grants
from .errors import DUPLICATE, NOT_GRANTED, HostError, NotGranted


@dataclass(frozen=True)
class Ticket:
    """What ``ctx.ticket`` returns: the ticket's id, its state, when it expires, the mode of
    its kind when filed, and whether an open ticket with the same fields was there already
    (then ``ticket_id`` is that one's)."""

    ticket_id: int
    state: str = "needs_confirm"
    expires_at: str | None = None
    mode: str | None = None
    duplicate: bool = False


def _parse_now(text) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _subject(subject) -> dict | None:
    if subject is None:
        return None
    if isinstance(subject, dict):
        return {"kind": subject["kind"], "id": subject["id"]}
    kind, ident = subject
    return {"kind": kind, "id": ident}


class Context:
    """One request's context. ``call(method, params)`` is the transport (the pipe, or
    ``FakeHost``); ``hello`` is the host's answer to the cub's ``hello``."""

    def __init__(self, call: Callable[[str, dict], dict], *, cub_id: str, version: str,
                 hello: dict, run_uuid: str | None = None, mode: dict | None = None,
                 stage: bool = False, cancelled: Callable[[], bool] = lambda: False,
                 clock_at: float | None = None) -> None:
        self._transport = call
        self.cub_id, self.version = cub_id, version
        self.trust = hello.get("trust")
        self.granted = hello.get("granted") or {}
        self.limits = hello.get("limits") or {}
        self.run_uuid = run_uuid or (hello.get("run") or {}).get("uuid")
        self.mode: dict = dict(mode if mode is not None else hello.get("mode") or {})
        self._tz = hello.get("tz") or os.environ.get("TZ") or "UTC"
        # the host's clock (hello.now), run on by this process's monotonic time: Kranto is the
        # clock a cub's day and week are counted by (FakeHost's advance() moves it too)
        self._host_now = _parse_now(hello.get("now"))
        self._t0 = time.monotonic() if clock_at is None else clock_at
        self._stage = stage
        self._cancelled = cancelled
        self._settings: dict | None = None
        self.read = Read(self)
        self.events = Events(self)
        self.model = Model(self)
        self.prose = Prose(self)
        self.http = Http(self)
        self.tickets = Tickets(self)
        self.kv = KV(self)
        self.log = Log(self)

    def _call(self, method: str, params: dict) -> dict:
        refused = grants.allow(self.granted, method, params, stage=self._stage)
        if refused is not None:
            code, why = refused
            raise NotGranted(why) if code == NOT_GRANTED else HostError(code, why)
        return self._transport(method, params)

    # -- the run --------------------------------------------------------------------------------

    @property
    def cancelled(self) -> bool:
        """True once the host sent ``cancel`` for this request: a long loop checks it."""
        return bool(self._cancelled())

    def live(self, kind: str) -> bool:
        return self.mode.get(kind) == "live"

    def now(self) -> datetime:
        """The host's time now, in the host's zone."""
        utc = self._host_now + timedelta(seconds=time.monotonic() - self._t0) \
            if self._host_now is not None else datetime.now(UTC)
        try:
            from zoneinfo import ZoneInfo
            return utc.astimezone(ZoneInfo(self._tz))
        except Exception:  # noqa: BLE001 - no zone data: the host's clock in UTC
            return utc

    def today(self) -> str:
        return self.now().date().isoformat()

    def now_minus(self, **delta) -> datetime:
        return self.now() - timedelta(**delta)

    @property
    def settings(self) -> Mapping:
        """The cub's own keys, by full key (``newsletter.topics``), as in force now."""
        if self._settings is None:
            self._settings = dict(self._call("settings.get", {}).get("values") or {})
        return self._settings

    # -- the host's capabilities ----------------------------------------------------------------

    def search(self, q: str, kind: str = "web", recency: str | None = None, n: int = 10) -> dict:
        return self._call("search.run", {"q": q, "kind": kind, "recency": recency, "n": n})

    def broker(self, service: str) -> Broker:
        return Broker(self, service)

    def ticket(self, kind: str, fields: dict, because: dict | None = None, subject=None
               ) -> Ticket:
        """File a ticket for a high-trust action the owner confirms; a duplicate of an open
        ticket returns that ticket with ``duplicate=True`` instead of raising."""
        params: dict = {"kind": kind, "fields": fields}
        if because:
            params["because"] = because
        if subject is not None:
            params["subject"] = _subject(subject)
        try:
            out = self._call("ticket.file", params)
        except HostError as exc:
            if exc.code == DUPLICATE:
                return Ticket(int(exc.data.get("ticket_id", 0)), duplicate=True)
            raise
        return Ticket(int(out["ticket_id"]), out.get("state", "needs_confirm"),
                      out.get("expires_at"), out.get("mode"))

    def withdraw(self, subject, note: str) -> int:
        """Expire this cub's open tickets about one subject (a redraft); how many."""
        return int(self._call("ticket.withdraw", {"subject": _subject(subject),
                                                  "note": str(note)[:200]}).get("expired", 0))

    def once(self, key: str) -> bool:
        """True the first time it is asked for ``key``, False ever after: a run delivered or
        retried twice does its work once (the key is kept in the cub's store)."""
        k = f"once:{key}"
        if self.kv.get(k) is not None:
            return False
        self.kv.put(k, True)
        return True

    def spend(self) -> dict:
        return self._call("reads.get", {"name": "spend.mine", "params": {}})

    def grades(self, kind: str | None = None, since: str | None = None) -> list:
        params = {k: v for k, v in (("kind", kind), ("since", since)) if v is not None}
        return self._call("reads.get", {"name": "grades.mine", "params": params})["grades"]


class Read:
    """The read surface (protocol): text comes back fenced and labelled."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def get(self, name: str, **params) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        return self._ctx._call("reads.get", {"name": name, "params": params})

    def topics(self) -> dict:
        return self.get("topics.list")

    def observations(self, topic_id=None, since=None, limit=None, sort=None, signal_only=None):
        return self.get("library.observations", topic_id=topic_id, since=since, limit=limit,
                        sort=sort, signal_only=signal_only)

    def search(self, q: str, topic_id=None, limit=None) -> dict:
        return self.get("library.search", q=q, topic_id=topic_id, limit=limit)

    def themes(self, topic_id=None, rising=None) -> dict:
        return self.get("themes.list", topic_id=topic_id, rising=rising)

    def theme(self, ident: str) -> dict:
        return self.get("themes.get", id=ident)

    def ideas(self, since=None, limit=None, editor_class=None) -> dict:
        return self.get("ideas.list", since=since, limit=limit, editor_class=editor_class)

    def idea(self, ident: int) -> dict:
        return self.get("ideas.get", id=ident)

    def card(self, ident: int) -> dict:
        """One idea card with its sources and their links (``cards.get``, Kranto 0.6)."""
        return self.get("cards.get", id=ident)

    def briefs(self, topic_id=None, since=None, limit=None) -> dict:
        return self.get("briefs.list", topic_id=topic_id, since=since, limit=limit)

    def brief(self, ident: int) -> dict:
        return self.get("briefs.get", id=ident)

    def object(self, kind: str, ident) -> dict:
        return self.get("objects.get", kind=kind, id=ident)


class Events:
    """The bus (protocol): at least once; a cub makes its effects idempotent with
    ``ctx.once`` or a dedupe key."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def read(self, kind: str, limit: int = 100) -> list[dict]:
        return self._ctx._call("events.read", {"kind": kind, "limit": limit})["events"]

    def ack(self, kind: str, last_id: int) -> int:
        return int(self._ctx._call("events.ack", {"kind": kind, "last_id": int(last_id)})
                   ["cursor"])

    def publish(self, kind: str, payload: dict, subject=None, dedupe: str | None = None) -> int:
        params: dict = {"kind": kind, "payload": payload}
        if subject is not None:
            params["subject"] = _subject(subject)
        if dedupe is not None:
            params["dedupe"] = dedupe
        return int(self._ctx._call("events.publish", params)["event_id"])


class Model:
    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def complete(self, *, purpose: str, tier: str, messages: list[dict], max_tokens: int = 800,
                 temperature: float = 0.2, schema: dict | None = None,
                 retry_truncated: bool = False) -> dict:
        """The metered model, under the cub's purpose and cap: no tools, no provider or model
        of its own. Strangers' text goes in through ``fence``."""
        for m in messages:
            if not isinstance(m, dict) or not isinstance(m.get("content"), str):
                raise ValueError("a message is {role, content} with content as text")
        params = {"purpose": purpose, "tier": tier, "messages": messages,
                  "max_tokens": max_tokens, "temperature": temperature,
                  "retry_truncated": retry_truncated}
        if schema is not None:
            params["schema"] = schema
        return self._ctx._call("model.complete", params)


class Prose:
    """Kranto's prose engine, for a cub that writes posts: the person's voice,
    their rules and Kranto's floor go into the prompt, and a draft is checked and fixed before it
    is filed. Granted with the model: a cub with no model purpose has no prose either.

    - ``compose(material, site=, kind=, task=, language=, limits=, features=)`` → ``{messages,
      take, angle, disclosure}``: the messages to send ``ctx.model.complete`` (``task`` is the
      writer's own instruction; ``material`` holds ``angle`` (the person's sentence or a picked
      proposal: it drives the post; ``take`` is its old name), ``title``, ``facts``,
      ``format``, ``hint`` and ``form``; ``limits`` and ``features`` are the site's, when the
      cub knows them; ``angle`` in the answer is the one used, None for a plain summary);
    - ``check(text, site=, kind=, limits=, take=)`` → ``{score, verdict, flags[]}``, local, no
      model call;
    - ``revise(text, flags=None, site=, purpose=, tier=, ...)`` → ``{text, flags, rounds}``:
      at most two model calls under the cub's own purpose and cap, rewriting only the flagged
      spans."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    @staticmethod
    def _params(**kw) -> dict:
        return {k: v for k, v in kw.items() if v is not None}

    def compose(self, material: dict, *, site: str | None = None, kind: str | None = None,
                task: str | None = None, language: str | None = None,
                limits: dict | None = None, features: str | None = None) -> dict:
        return self._ctx._call("prose.compose", self._params(
            material=dict(material), site=site, kind=kind, task=task, language=language,
            limits=limits, features=features))

    def check(self, text: str, *, site: str | None = None, kind: str | None = None,
              limits: dict | None = None, take: str | None = None,
              sources: str | None = None) -> dict:
        """``sources``: the material the text was written from (the card's or the item's words);
        with it, a person's name or a handle the material does not have is flagged
        (``salt.person``). SDK 1.4; a host before it refuses the key."""
        return self._ctx._call("prose.check", self._params(
            text=str(text), site=site, kind=kind, limits=limits, take=take,
            sources=None if sources is None else str(sources)))

    def revise(self, text: str, flags: list | None = None, *, purpose: str, tier: str,
               site: str | None = None, kind: str | None = None, limits: dict | None = None,
               take: str | None = None, sources: str | None = None) -> dict:
        return self._ctx._call("prose.revise", self._params(
            text=str(text), flags=flags, purpose=purpose, tier=tier, site=site, kind=kind,
            limits=limits, take=take, sources=None if sources is None else str(sources)))


class Http:
    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def get(self, url: str, headers: dict | None = None, max_bytes: int | None = None) -> dict:
        """A GET Kranto performs for the cub: https, a declared host, no credential."""
        params: dict = {"url": url}
        if headers:
            params["headers"] = headers
        if max_bytes is not None:
            params["max_bytes"] = max_bytes
        return self._ctx._call("http.fetch", params)


class Broker:
    def __init__(self, ctx: Context, service: str) -> None:
        self._ctx, self.service = ctx, service

    def call(self, op: str, **args) -> dict:
        """A typed operation Kranto performs with the owner's credential, which the cub never
        sees."""
        return self._ctx._call("broker.call", {"service": self.service, "op": op, "args": args})


class Tickets:
    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def list(self, subject=None, open: bool = False, limit: int = 50) -> list[dict]:  # noqa: A002
        params: dict = {"open": bool(open), "limit": limit}
        if subject is not None:
            params["subject"] = _subject(subject)
        return self._ctx._call("ticket.list", params)["tickets"]

    def get(self, ticket_id: int) -> dict:
        return self._ctx._call("ticket.get", {"ticket_id": int(ticket_id)})


class KV:
    """The cub's own store, held by Kranto (protocol): JSON values of at most 64 KiB, keys
    of ``[A-Za-z0-9_.:/-]``, under the cub's quota."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def get(self, key: str, default=None):
        from .errors import NOT_FOUND
        try:
            return self._ctx._call("kv.get", {"key": key})["value"]
        except HostError as exc:
            if exc.code == NOT_FOUND:
                return default
            raise

    def put(self, key: str, value) -> dict:
        return self._ctx._call("kv.put", {"key": key, "value": value})

    def delete(self, key: str) -> bool:
        return bool(self._ctx._call("kv.delete", {"key": key})["deleted"])

    def list(self, prefix: str = "", limit: int = 100, after: str | None = None) -> dict:
        params: dict = {"prefix": prefix, "limit": limit}
        if after is not None:
            params["after"] = after
        return self._ctx._call("kv.list", params)

    def items(self, prefix: str = "") -> Iterator[tuple[str, object]]:
        """Every ``(key, value)`` under ``prefix``, page by page."""
        after = None
        while True:
            page = self.list(prefix=prefix, limit=500, after=after)
            for k in page["keys"]:
                yield k["key"], self.get(k["key"])
            if not page.get("more") or not page["keys"]:
                return
            after = page["keys"][-1]["key"]


class Log:
    """Lines in the cub's log (at most 600 a run; scrubbed by Kranto before they are written)."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def _line(self, level: str, msg: str, data: dict) -> None:
        params: dict = {"level": level, "message": str(msg)[:4000]}
        if data:
            params["data"] = data
        self._ctx._call("log", params)

    def debug(self, msg: str, **data) -> None:
        self._line("debug", msg, data)

    def info(self, msg: str, **data) -> None:
        self._line("info", msg, data)

    def warning(self, msg: str, **data) -> None:
        self._line("warning", msg, data)

    def error(self, msg: str, **data) -> None:
        self._line("error", msg, data)
