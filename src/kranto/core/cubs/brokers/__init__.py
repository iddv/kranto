"""Brokers: typed operations Kranto performs for a cub with the owner's
credential, which the cub never sees. Each service is an adapter (``base``); a cub may be
granted an adapter's ``read`` and ``draft`` operations, never a ``perform`` one, which only a
ticket's confirm runs. ``ADAPTERS`` lists the services this Kranto offers; importing this
package gives ``send.newsletter`` (and its earlier names, aliases for one release) and
``post.mastodon`` their performers and read-backs, and ``draft.sanity`` (a post filed in Sanity as
a draft, never published: ``sanity``), and the short posts' kinds (``social``: ``post.open``,
Kranto's own, whose confirm is I posted it; ``post.bluesky``, the ``bluesky`` adapter's). The
newsletter service names no platform: the one connected does the work (``newsletter``)."""

from __future__ import annotations

from ... import tickets
from .base import Op, performer
from .bluesky import BlueskyAdapter
from .linkedin import LinkedInAdapter
from .mastodon import MastodonAdapter
from .newsletter import adapters as _newsletter_adapters
from .newsletter import register_kinds as _newsletter_kinds
from .sanity import SanityAdapter
from .sanity import register_kind as _sanity_kind
from .social import register_kinds as _social_kinds
from .threads import ThreadsAdapter

_newsletter_kinds()
_sanity_kind()
_social_kinds()
ADAPTERS: dict = {**_newsletter_adapters(), "mastodon": MastodonAdapter(),
                  "sanity": SanityAdapter(), "bluesky": BlueskyAdapter(),
                  "linkedin": LinkedInAdapter(), "threads": ThreadsAdapter()}

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
        # a cub's adapter, or one that performs only Kranto's own kinds (Bluesky's send)
        if not adapter.cub_grantable and not all(
                tickets.KINDS[name].first_party_only for name in adapter.kinds):
            continue
        for kind in adapter.kinds:
            spec = tickets.KINDS[kind]
            spec.perform = performer(adapter)
            spec.readback = (lambda a, k: lambda fields, store: a.readback(k, fields, store))(
                adapter, kind)
            if hasattr(adapter, "ask"):      # the plain dialog's parts (core.asks)
                spec.ask = (lambda a, k: lambda fields, store, rt: a.ask(k, fields, store, rt))(
                    adapter, kind)
            if spec.ask is not None and spec.meta.get("holds"):
                # a send Kranto may hold for an hour: the dialog offers Schedule, in the
                # person's own time (the page turns it into UTC)
                spec.ask = (lambda f: lambda fields, store, rt: {
                    **(f(fields, store, rt) or {}), "schedule": True, "zone": "local"})(spec.ask)


_register()
