"""The cubs' stored JSON: ``cubs.grants`` and ``.source``, and the
records of the cubs' installs, tickets, broker calls and Invest's orders.

``grants`` is what the owner approved at install: ``bears_cub.schema.grants_of`` of the
validated manifest (every block, defaults filled), plus ``reads_topics`` (the topics a cub
narrowed at install sees; None: all) and ``stages``. It is what the host checks every call
against. :class:`Grants` reads it, and :meth:`Grants.wire` gives the dict the SDK's checks and
``hello.granted`` take, laid out as ``grants_of`` lays it out. A block stored in a shape the
schema does not allow reads as that block's default: the narrower permission, never a wider
one.

``source`` is where the cub came from (a git URL and ref, a path, a release); the install's
``detail``, a ticket's ``fields`` (checked against the kind's schema when filed) and
``because`` and an order's ``order_json`` are kept whole, read totally: a reader gets a
dict, never a raise. A broker call's and an order's ``detail`` are scrubbed text (300 and 500
characters at most), not JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .base import Stored


@dataclass(frozen=True)
class EventGrants(Stored):
    publish: list[str] = field(default_factory=list)
    subscribe: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelGrants(Stored):
    tiers: list[str] = field(default_factory=list)
    purposes: list[str] = field(default_factory=list)
    monthly_usd: float | None = None      # the cap the cub asks for; None: the core's default
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HttpGrants(Stored):
    hosts: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Grants(Stored):
    """What a cub may do (``cubs.grants``), as approved at install."""

    COLUMN = ("cubs", "grants")
    reads: list[str] = field(default_factory=list)
    reads_topics: list[int] | None = None
    events: EventGrants = field(default_factory=EventGrants)
    model: ModelGrants = field(default_factory=ModelGrants)
    search: list[str] = field(default_factory=list)
    http: HttpGrants = field(default_factory=HttpGrants)
    broker: dict[str, list[str]] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    storage: Literal["own", "none"] = "own"
    stages: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        """The grants as ``grants_of`` lays them out (every block, ``reads_topics`` None when
        not narrowed): what ``bears_cub.grants.allow`` checks and ``hello.granted`` sends."""
        return self.to_dict(nulls=True)

    @classmethod
    def named_odd(cls) -> list[Grants]:
        return [cls(requests=["post.toot"], reads=["library"], reads_topics=[1]),
                cls(storage="none", http=HttpGrants(hosts=["odd.example"]),
                    broker={"newsletter": ["newsletter.read"]})]


@dataclass(frozen=True)
class CubSource(Stored):
    """Where a cub came from (``cubs.source``): its fields as the installer kept them."""

    COLUMN = ("cubs", "source")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InstallDetail(Stored):
    """An install step's own record (``cub_installs.detail``)."""

    COLUMN = ("cub_installs", "detail")
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        # a step may record a path or a date: kept as its text, as the writer always did
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class TicketFields(Stored):
    """A ticket's fields, as its kind's schema checked them when it was filed."""

    COLUMN = ("cub_tickets", "fields")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PostReachShape(Stored):
    """A sent post's shape, kept with its first ``post_reach`` row (``kranto.social.reach``):
    ``site``, ``ids`` (the site's own: Bluesky's ``uri``, Mastodon's ``id`` and ``instance``,
    Threads' ``id``, LinkedIn's ``urn``), ``parts``, ``card``, ``length``, ``weekday``, ``hour``
    and ``angle``. A reading's row stores ``{}``."""

    COLUMN = ("post_reach", "shape")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TicketBecause(Stored):
    """Why a ticket was filed: its provenance (the run, the cited objects)."""

    COLUMN = ("cub_tickets", "because")
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderJson(Stored):
    """An Invest instruction's body as sent (``cub_orders.order_json``)."""

    COLUMN = ("cub_orders", "order_json")
    extra: dict[str, Any] = field(default_factory=dict)
