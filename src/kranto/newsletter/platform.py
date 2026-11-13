"""What every newsletter platform has in common (MAIL, the owner's ruling of 2026-10-21).

A platform is the service a newsletter cub's issue goes out through. Kranto speaks to every one
through this shape, and each lives in its own module (``newsletter/<id>.py``), the only place that
names it: its connection (the key the owner pastes), its words, and the calls that draft, read,
check and send. The cub asks for the neutral kind ``send.newsletter`` and the neutral broker
service ``newsletter``; which platform does the work comes from config (``newsletter.sender``,
written at Connect).

A platform's calls get a ``BrokerContext`` (``core.cubs.brokers.base``) bound to its connection:
they send with the owner's credential through ``ctx.send`` and never see it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Check:
    """What a read-only check found: ``ok`` when an issue can go out as things are, the lines
    it read (``said``) and, in plain words, what is missing (``missing``)."""

    ok: bool
    said: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sender: dict = field(default_factory=dict)      # what to keep in newsletter.sender

    def words(self) -> str:
        if self.ok:
            return " ".join(self.said) or "Ready to send."
        return "Not ready yet: " + " ".join(self.missing)

    def kept(self) -> dict:
        """What is kept of it with the sender, for the page until the next check."""
        return {"ok": self.ok, "missing": list(self.missing)}


class Platform(ABC):
    """Defaults, and the calls each platform must make its own."""

    id = ""                       # also the key of its connection provider
    name = ""
    ref_prefix = ""               # a draft held at the platform is "<prefix>:<its id>"
    about = ""
    docs = "docs/newsletter.md"
    can_schedule = False
    # What a release before this one called this platform's kind and broker service: kept as
    # aliases for one release so installed cubs and their tickets go on working.
    legacy: dict = {}
    # The connection provider class and the Connections page's entry (``connections``).
    connection = None
    info: dict = {}

    def words(self) -> dict:
        """What a page may show of it (never a secret)."""
        return {"id": self.id, "name": self.name, "about": self.about, "docs": self.docs,
                "can_schedule": self.can_schedule}

    # -- the sender: who it is from and to whom ------------------------------------------------

    def ready(self, sender: dict) -> str | None:
        """Why an issue cannot go out with this sender config, or None."""
        return None

    def audience_words(self, sender: dict) -> str:
        return "all subscribers"

    def footer(self) -> str | None:
        """What the platform adds below every issue, in words for the read-back."""
        return None

    # -- the calls (each with a bound ``ctx``) ---------------------------------------------------

    @abstractmethod
    def create_draft(self, ctx, content: dict, sender: dict) -> dict:
        """A draft at the platform: ``{external_id, url}``."""

    @abstractmethod
    def status(self, ctx, draft: dict) -> dict:
        """``{status, url}`` of a draft held at the platform."""

    @abstractmethod
    def newsletter(self, ctx, sender: dict) -> dict:
        """``{name, subscriber_count}``."""

    def subscribers(self, ctx, sender: dict) -> int | None:
        return None

    @abstractmethod
    def send(self, ctx, draft: dict, when: str, sender: dict) -> dict:
        """The owner's press, live: ``{state, note}``. Called once per ticket."""

    @abstractmethod
    def check(self, http, sender: dict) -> Check:
        """Reads only: is the key's permission enough, the domain verified, the audience
        there. ``http`` is authed with the connection."""
