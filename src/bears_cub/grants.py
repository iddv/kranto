"""The capability check of the part that reads only the approved grants.

``allow(granted, method, params)`` is called by the SDK before a call is written to the pipe (so
a careless author gets ``NotGranted`` where the call is) and by Kranto's host before every
dispatch, so the two can never disagree. The host then adds what only it knows: an adapter
operation's side, whether a request kind is registered and grantable to the cub's trust, the
topics a narrowed cub may see, the caps.

``granted`` is ``hello``'s ``granted``: ``{reads, reads_topics, events: {publish, subscribe},
model: {tiers, purposes, monthly_usd}, search, http: {hosts}, broker: {service: [op]},
requests, storage, stages}``. The prose engine (``prose.*``) has no grant of its own: it comes
with ``model``.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .errors import INVALID_PARAMS, NOT_GRANTED

MODEL_KEYS = {"purpose", "tier", "messages", "max_tokens", "temperature", "schema",
              "retry_truncated"}
# What a code stage may call (protocol): the rest is refused during a stage run unless
# the cub declares it for its jobs as well.
STAGE_REQUEST_PREFIXES = ("post.", "send.")
FREE = ("hello", "log", "settings.get", "ticket.list", "ticket.get", "ticket.withdraw")


def _subscribed(granted: dict) -> set[str]:
    return {s.get("kind") for s in (granted.get("events") or {}).get("subscribe", [])}


def host_allowed(host: str, hosts) -> bool:
    """A declared host or a subdomain of one (``api.github.com`` under ``github.com``)."""
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in hosts or [])


def _ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def check_url(url: str, hosts) -> tuple[int, str] | None:
    """``http.fetch``'s URL rules (protocol): https, a declared host or its subdomain,
    no IP literal, no userinfo, no port but 443, at most 2,048 characters."""
    if not isinstance(url, str) or len(url) > 2048:
        return INVALID_PARAMS, "url is text of at most 2048 characters"
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        return INVALID_PARAMS, "url is not a URL"
    if u.scheme != "https":
        return NOT_GRANTED, "http.fetch is https only"
    host = (u.hostname or "").lower()
    if not host:
        return INVALID_PARAMS, "url has no host"
    if _ip_literal(host):
        return INVALID_PARAMS, "url names an IP address; a cub fetches declared names only"
    if u.username is not None or u.password is not None:
        return INVALID_PARAMS, "url carries a user or a password"
    if port not in (None, 443):
        return INVALID_PARAMS, "url names a port; only 443"
    if not host_allowed(host, hosts):
        return NOT_GRANTED, f"{host} is not one of its http.hosts"
    return None


def allow(granted: dict, method: str, params: dict, *, stage: bool = False
          ) -> tuple[int, str] | None:
    """None when the approved grants cover the call; else ``(code, why)``: ``-32001`` (not
    granted) or ``-32602`` (a shape the method never takes)."""
    g = granted or {}
    p = params if isinstance(params, dict) else {}
    if method in FREE:
        return None
    if method == "reads.get":
        name = str(p.get("name") or "")
        if name == "grades.mine":
            return None
        family = name.split(".", 1)[0]
        # a read named apart from its family (Kranto 0.6: ``cards.get`` is the ideas family's)
        family = {"cards": "ideas"}.get(family, family)
        if family not in (g.get("reads") or []):
            return NOT_GRANTED, f"reads {family} is not granted"
        return None
    if method in ("events.read", "events.ack"):
        if p.get("kind") not in _subscribed(g):
            return NOT_GRANTED, f"it does not subscribe to {p.get('kind')}"
        return None
    if method == "events.publish":
        if p.get("kind") not in (g.get("events") or {}).get("publish", []):
            return NOT_GRANTED, f"it does not publish {p.get('kind')}"
        return None
    if method == "model.complete":
        model = g.get("model") or {}
        extra = sorted(set(p) - MODEL_KEYS)
        if extra:
            return NOT_GRANTED, (f"model.complete takes no {', '.join(extra)}: no tools, no "
                                 "provider or model of its own")
        if p.get("purpose") not in (model.get("purposes") or []):
            return NOT_GRANTED, f"the purpose {p.get('purpose')} is not granted"
        if p.get("tier") not in (model.get("tiers") or []):
            return NOT_GRANTED, f"the {p.get('tier')} tier is not granted"
        return None
    if method in ("prose.compose", "prose.check", "prose.revise"):
        # the prose engine comes with the model: a cub that may write may use the person's
        # voice and Kranto's floor; ``revise`` spends under one of its own purposes and tiers
        model = g.get("model") or {}
        if not model.get("purposes"):
            return NOT_GRANTED, "prose is granted with the model, and no purpose is granted"
        if method == "prose.revise":
            if p.get("purpose") not in model.get("purposes"):
                return NOT_GRANTED, f"the purpose {p.get('purpose')} is not granted"
            if p.get("tier") not in (model.get("tiers") or []):
                return NOT_GRANTED, f"the {p.get('tier')} tier is not granted"
        return None
    if method == "search.run":
        kind = p.get("kind") or "web"
        if kind not in (g.get("search") or []):
            return NOT_GRANTED, f"search {kind} is not granted"
        return None
    if method == "http.fetch":
        return check_url(p.get("url"), (g.get("http") or {}).get("hosts"))
    if method == "broker.call":
        ops = (g.get("broker") or {}).get(p.get("service")) or []
        if p.get("op") not in ops:
            return NOT_GRANTED, f"{p.get('service')} {p.get('op')} is not granted"
        return None
    if method == "ticket.file":
        kind = str(p.get("kind") or "")
        if kind not in (g.get("requests") or []):
            return NOT_GRANTED, f"it may not request {kind}"
        if stage and not kind.startswith(STAGE_REQUEST_PREFIXES):
            return NOT_GRANTED, f"a stage may request post.* and send.* only, not {kind}"
        return None
    if method in ("kv.get", "kv.put", "kv.delete", "kv.list"):
        if g.get("storage", "own") != "own":
            return NOT_GRANTED, "it has no storage (storage: none)"
        return None
    return None
