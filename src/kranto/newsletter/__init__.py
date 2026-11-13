"""Newsletter platforms (MAIL, the owner's ruling of 2026-10-21): a newsletter goes out through
whichever platform the owner connects, the same shape as Invest's broker.

A newsletter cub asks for the neutral kind ``send.newsletter`` and the broker service
``newsletter`` (``core.cubs.brokers.newsletter``). Each platform is a module here
(``Platform``: its connection, its words, its calls), the only place that names it.
``PLATFORMS`` lists them in the order the Connect dialog offers them.

Which platform is in use comes from config: ``newsletter.sender`` (kept at Connect: the
platform, and for one that needs them the from address and the audience), else a platform
with a live connection, else none. Until one is named no page, ticket or tile names a
platform: the words say "your newsletter platform".
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from ..stored.settings import NewsletterSender, get_blob
from .platform import Check, Platform

SENDER_KEY = "newsletter.sender"
UNNAMED = "your newsletter platform"
NOT_PLATFORMS = ("platform", "render")

__all__ = ["PLATFORMS", "Check", "Platform", "UNNAMED", "for_ref", "get", "named", "sender"]


def _load() -> dict[str, Platform]:
    found = []
    for m in pkgutil.iter_modules(__path__):
        if m.name in NOT_PLATFORMS or m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{__name__}.{m.name}")
        found.append((getattr(mod, "ORDER", 100), m.name, mod.PLATFORM))
    found.sort(key=lambda x: (x[0], x[1]))
    return {p.id: p for _, _, p in found}


PLATFORMS: dict[str, Platform] = _load()


def get(platform_id: str | None) -> Platform:
    if platform_id in PLATFORMS:
        return PLATFORMS[platform_id]
    raise KeyError(f"no newsletter platform {platform_id!r}: Kranto offers "
                   + ", ".join(PLATFORMS))


def for_ref(ref: str | None) -> Platform | None:
    """The platform a draft is held at, from its ref (``<prefix>:<id>``); None for a draft
    Kranto holds (``draft:<id>``)."""
    prefix = str(ref or "").split(":", 1)[0]
    return next((p for p in PLATFORMS.values() if p.ref_prefix == prefix), None)


def sender(store: Any) -> dict[str, Any]:
    """``newsletter.sender``: ``{platform, from?, audience_id?, audience_name?, last_check?}``
    (``last_check``: what the last Save and test or Check again found missing), or {}."""
    got = get_blob(store, SENDER_KEY, NewsletterSender) if store is not None else None
    return got.to_dict() if got is not None else {}


def keep_sender(store: Any, platform: Platform, values: dict[str, Any]) -> dict[str, Any]:
    """The owner's choice at Connect (and what a check found), kept for the press."""
    value = {"platform": platform.id, **{k: v for k, v in values.items()
                                         if k in ("from", "audience_id", "audience_name",
                                                  "last_check")}}
    store.set_setting(SENDER_KEY, NewsletterSender.write(value))
    return value


def named(store: Any) -> Platform | None:
    """The platform the owner named: the one kept at Connect, else one with a live
    connection; None until then."""
    chosen = sender(store).get("platform")
    if chosen in PLATFORMS:
        return PLATFORMS[chosen]
    from ..core.cubs.brokers.base import connection_of
    return next((p for p in PLATFORMS.values() if connection_of(store, p.id)), None)


def display_name(store: Any) -> str | None:
    p = named(store)
    return p.name if p else None


def listing() -> list[dict[str, Any]]:
    """Every platform as the Connect dialog offers it."""
    return [p.words() for p in PLATFORMS.values()]


def legacy_kinds() -> dict[str, Platform]:
    """An earlier release's kind name -> its platform (an alias of ``send.newsletter``)."""
    return {p.legacy["kind"]: p for p in PLATFORMS.values() if p.legacy.get("kind")}


def legacy_services() -> dict[str, Platform]:
    return {p.legacy["service"]: p for p in PLATFORMS.values() if p.legacy.get("service")}


def status(rt: Any) -> dict[str, Any]:
    """``GET /api/newsletter``: the platform in use, its connection, the sender, and every
    platform offered. Reads Kranto's own rows only: no request leaves the machine."""
    from ..core.cubs.brokers.base import connection_of
    p = named(rt.store)
    snd = sender(rt.store)
    conn = connection_of(rt.store, p.id) if p else None
    out: dict[str, Any] = {"platform": p.words() if p else None,
                           "name": p.name if p else None,
           "audiences": hasattr(p, "create_audience"),
           "unnamed": UNNAMED, "platforms": listing(),
           "connection": None, "from_address": None, "audience": None, "ready": False,
           "missing": []}
    if p is None:
        out["missing"] = ["No newsletter platform is connected: Connect a provider"]
        return out
    out["from_address"] = snd.get("from") if snd.get("platform") == p.id else None
    out["audience"] = p.audience_words(snd if snd.get("platform") == p.id else {})
    if conn is None:
        out["missing"] = [f"{p.name} is not connected."]
        return out
    out["connection"] = {"id": conn["id"], "account": conn["account"], "state": conn["state"]}
    if conn["state"] != "connected":
        out["missing"] = [f"{p.name} needs you to connect it again."]
        return out
    mine = snd if snd.get("platform") == p.id else {}
    why = p.ready(mine)
    last = mine.get("last_check") or {}
    out["missing"] = [why] if why else list(last.get("missing") or [])
    out["ready"] = not out["missing"]
    return out


def check(rt: Any) -> Check:
    """Save and test's second half, and Check again: reads only, at the platform in use."""
    p = named(rt.store)
    if p is None:
        return Check(False, missing=["No newsletter platform is connected: Connect a "
                                     "provider…"])
    conns = rt.connections
    if conns is None or conns.unavailable():
        return Check(False, missing=["Connected accounts are off here."])
    from ..sources.base import SourceError
    snd = sender(rt.store)
    try:
        http = conns.http_for(p.id, None, rt.http)
        found = p.check(http, snd if snd.get("platform") == p.id else {})
    except SourceError as exc:
        if exc.needs_login:
            return Check(False, missing=[f"{p.name} refused the key: connect it again."])
        return Check(False, missing=[f"{p.name} did not answer ({_status(exc)}); try again."])
    keep_sender(rt.store, p, {**snd, **found.sender, "last_check": found.kept()})
    return found


def _status(exc: Any) -> str:
    return f"HTTP {exc.status}" if getattr(exc, "status", None) else "no reply"


def _register_connections() -> None:
    """Each platform's connection provider joins the Connections page and registry."""
    from .. import connections
    for p in PLATFORMS.values():
        if p.connection is not None:
            connections.register(p.info, p.connection)


_register_connections()
