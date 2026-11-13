"""Brokers: typed operations Kranto performs for a cub with the owner's
credential, which the cub never sees. Each service is an adapter (``base``); a cub may be
granted an adapter's ``read`` and ``draft`` operations, never a ``perform`` one, which only a
ticket's confirm runs. ``ADAPTERS`` lists the services this Kranto offers; importing this
package gives ``send.newsletter`` (and its earlier names, aliases for one release) and
``post.mastodon`` their performers and read-backs, and ``draft.sanity`` (a post filed in Sanity as
a draft, never published: ``sanity``). The newsletter service names no platform: the one
connected does the work (``newsletter``)."""

from __future__ import annotations

from ... import tickets
from .base import Op, performer
from .mastodon import MastodonAdapter
from .newsletter import adapters as _newsletter_adapters
from .newsletter import register_kinds as _newsletter_kinds
from .sanity import SanityAdapter
from .sanity import register_kind as _sanity_kind

_newsletter_kinds()
_sanity_kind()
ADAPTERS: dict = {**_newsletter_adapters(), "mastodon": MastodonAdapter(),
                  "sanity": SanityAdapter()}

__all__ = ["ADAPTERS", "Op", "call", "grantable"]


def grantable() -> dict[str, set[str]]:
    """Each service's operations a cub may be granted (what the validator accepts)."""
    return {s: {name for name, op in a.ops.items() if op.side in ("read", "draft")}
            for s, a in ADAPTERS.items() if a.cub_grantable}


def call(host, adapter, spec, args: dict) -> dict:
    """One granted operation for a cub's run (the adapters' dispatcher)."""
    from .base import run_op
    return run_op(host, adapter, spec, args)


def _register() -> None:
    for adapter in ADAPTERS.values():
        if not adapter.cub_grantable:
            continue
        for kind in adapter.kinds:
            spec = tickets.KINDS[kind]
            spec.perform = performer(adapter)
            spec.readback = (lambda a, k: lambda fields, store: a.readback(k, fields, store))(
                adapter, kind)
            if hasattr(adapter, "ask"):      # the plain dialog's parts (core.asks)
                spec.ask = (lambda a, k: lambda fields, store, rt: a.ask(k, fields, store, rt))(
                    adapter, kind)


_register()
