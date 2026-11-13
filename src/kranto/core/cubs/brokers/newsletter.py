"""The newsletter broker (MAIL; made neutral): a cub drafts an issue; the
owner's press sends it through whichever newsletter platform is connected.

A cub is granted the service ``newsletter`` and asks for the kind ``send.newsletter``; it never
names a platform, and neither does this module: the platform comes from config
(``kranto.newsletter``: the one kept at Connect), and each platform's own calls live in its
module there.

- **Draft.** Not connected (or the platform not ready: one that needs an audience without it),
  the draft is held by Kranto (``draft:<id>``). Connected and ready, it is also a draft at the
  platform (``<prefix>:<its id>``), with the audience and its subscriber count as they were.
- **The press.** Dry (the default) sends nothing. Live: the draft the ticket names (this cub's,
  unchanged, its subject the ticket's), the platform that holds it (else the one connected),
  its sender ready, the audience the one the draft was made for; then the platform's one send,
  ``now`` or at the ticket's time. Every request has a deadline and none is retried, so a send
  whose answer did not come is ``unknown``: the owner looks at the platform. A ticket is
  confirmed once (``core.tickets``), so a press never sends twice.

Before MAIL the kind and the service carried a platform's name; a platform's ``legacy`` names
are aliases of these for one release (the same adapter, under the old service name, and the
old kind with its old fields), so cubs installed then, their drafts and their open tickets go
on working.
"""

from __future__ import annotations

from dataclasses import replace

from ....store import iso, utcnow
from ... import tickets
from .base import (
    BrokerContext,
    BrokerError,
    Op,
    connection_of,
    draft_of,
    drafts_list,
    new_draft,
    own_draft,
    press_draft,
)

SERVICE = "newsletter"
KIND = "send.newsletter"
_LIMIT = ("int", {"lo": 1, "hi": 50}, False)
WHEN = r"now|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?Z"
# the owner's words for it (``core.asks``); an issue may be scheduled in the dialog
WORDS = {"verb": "Send now", "button": "Send", "noun": "issue", "done": "Sent",
         "not_done": "not sent", "schedules": True,
         # one series: next Monday's issue replaces this Monday's ask (``tickets``,)
         "series": True}
REF = r"[a-z]{2,8}:[A-Za-z0-9-]{1,64}"


def _platforms():
    from .... import newsletter
    return newsletter


class NewsletterAdapter:
    """``service``: ``newsletter``, or an earlier release's name for it (an alias whose ops
    keep their old arguments)."""

    provider = None                  # chosen per call, from config (``bind``)
    cub_grantable = True

    def __init__(self, service: str = SERVICE, kinds: tuple[str, ...] = (KIND,),
                 legacy: bool = False) -> None:
        self.service, self.kinds, self.legacy = service, kinds, legacy
        draft_args = {"subject": ("str", {"max_len": 200}, True),
                      "body": ("str", {"max_len": 200000}, True)}
        if legacy:
            draft_args["email_type"] = ("enum", {"choices": ("public", "private")}, False)
        self.ops = {
            "emails.create_draft": Op("emails.create_draft", "draft", draft_args,
                                      needs_credential=False, per_day=20),
            "emails.get": Op("emails.get", "read",
                             {"draft_ref": ("str", {"max_len": 80 if not legacy else 70}, True)},
                             needs_credential=False, per_hour=60),
            "drafts.list": Op("drafts.list", "read", {"limit": _LIMIT}, needs_credential=False,
                              per_hour=60),
            "newsletter.get": Op("newsletter.get", "read", {}, needs_credential=True,
                                 per_hour=60),
        }

    @property
    def title(self) -> str:
        return _platforms().UNNAMED[0].upper() + _platforms().UNNAMED[1:]

    @staticmethod
    def services() -> tuple[str, ...]:
        """Every name a newsletter draft's row may carry."""
        return (SERVICE, *_platforms().legacy_services())

    # -- which platform ----------------------------------------------------------------------

    def bind(self, ctx: BrokerContext, *, ticket: dict | None = None,
             platform=None) -> BrokerContext:
        """``ctx`` with the platform's connection: the one given, else (at a press) the one
        holding the ticket's draft, else the one in use."""
        nl = _platforms()
        if platform is None and ticket is not None:
            platform = nl.for_ref(ticket["fields"].get("draft_ref"))
        platform = platform or nl.named(ctx.store)
        if platform is None:
            return replace(ctx, provider=None, connection=None, title=self.title)
        return replace(ctx, provider=platform.id, title=platform.name,
                       connection=connection_of(ctx.store, platform.id))

    def _platform(self, ctx: BrokerContext):
        return _platforms().PLATFORMS.get(ctx.provider) if ctx.provider else None

    def _sender(self, ctx: BrokerContext, platform) -> dict:
        snd = _platforms().sender(ctx.store)
        return snd if platform is not None and snd.get("platform") == platform.id else {}

    # -- the operations a cub may be granted -------------------------------------------------

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:
        return getattr(self, "_" + op.replace(".", "_"))(args, ctx)

    def _emails_create_draft(self, a: dict, ctx: BrokerContext) -> dict:
        platform = self._platform(ctx)
        content = {"subject": a["subject"], "body": a["body"]}
        if "email_type" in a or self.legacy:
            content["email_type"] = a.get("email_type", "public")
        for p in [platform] if platform else _platforms().PLATFORMS.values():
            problem = getattr(p, "check_body", lambda _b: None)(a["body"])
            if problem:
                raise BrokerError(-32005, problem)
        snd = self._sender(ctx, platform)
        if platform is None or not ctx.connected or platform.ready(snd):
            d = new_draft(ctx.store, cub=ctx.cub, service=self.service, content=content,
                          run_uuid=ctx.run_uuid)
            return {"draft_ref": d["ref"], "where": "kranto", "subject": a["subject"],
                    "url": None, "created_at": d["created_at"]}
        n = platform.subscribers(ctx, snd)
        if snd.get("audience_id"):
            content["audience"] = {"id": snd["audience_id"], "name": snd.get("audience_name"),
                                   "subscribers": n}
        made = platform.create_draft(ctx, content, snd)
        eid = made["external_id"]
        d = new_draft(ctx.store, cub=ctx.cub, service=self.service, content=content,
                      run_uuid=ctx.run_uuid, ref=f"{platform.ref_prefix}:{eid}", external_id=eid)
        return {"draft_ref": d["ref"], "where": platform.id, "subject": a["subject"],
                "url": made.get("url"), "created_at": d["created_at"]}

    def _emails_get(self, a: dict, ctx: BrokerContext) -> dict:
        d = own_draft(ctx.store, ctx.cub, self.services(), a["draft_ref"])
        out = {"draft_ref": d["ref"], "subject": d["content"]["subject"], "url": None}
        holder = _platforms().for_ref(d["ref"])
        if holder is None:
            return {**out, "status": "sent" if _sent(ctx.store, d["ref"]) else "kranto",
                    "where": "kranto"}
        ctx = self.bind(ctx, platform=holder)
        if not ctx.connected:
            return {**out, "status": "draft", "where": holder.id}
        got = holder.status(ctx, d)
        return {**out, "status": got["status"], "where": holder.id, "url": got.get("url")}

    def _drafts_list(self, a: dict, ctx: BrokerContext) -> dict:
        return drafts_list(ctx.store, ctx.cub, self.services(), a.get("limit", 50), "subject")

    def _newsletter_get(self, a: dict, ctx: BrokerContext) -> dict:
        platform = self._platform(ctx)
        got = platform.newsletter(ctx, self._sender(ctx, platform))
        return {"name": got.get("name"), "subscriber_count": got.get("subscriber_count")}

    # -- the owner's press ----------------------------------------------------------------

    def perform(self, kind: str, ticket: dict, mode: str, ctx: BrokerContext) -> dict:
        d = press_draft(ctx.store, ticket, self.services(), ("subject",))
        if isinstance(d, str):
            return {"state": "refused", "note": f"refused: {d}"}
        platform = self._platform(ctx)
        holder = _platforms().for_ref(d["ref"])
        where = f"at {holder.name}" if holder else "in Kranto"
        when = ticket.get("press_when") or ticket["fields"].get("when") or "now"
        snd = self._sender(ctx, platform)
        if mode != "live":
            to = _audience(d, platform, snd)
            return {"state": "dry", "note": f"practice: nothing was sent; the draft stays "
                                            f"{where}. For real it would go to {to}"
                                            + ("" if when == "now" else f" at {when}")}
        if platform is None:
            return {"state": "refused", "note": "refused: your newsletter platform is not "
                                                "connected (Settings › Accounts › Newsletter)"}
        if not ctx.connected:
            return {"state": "refused", "note": f"refused: {platform.name} is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        if when != "now" and not platform.can_schedule:
            return {"state": "refused", "note": f"refused: Kranto sends a {platform.name} issue "
                                                "now only; it does not schedule one"}
        if when != "now" and when.replace("Z", "") <= iso(utcnow()).replace("Z", "")[:19]:
            return {"state": "refused", "note": f"refused: the time to send it ({when}) has "
                                                "passed; redraft the issue"}
        why = platform.ready(snd)
        if why:
            return {"state": "refused", "note": f"refused: {why}"}
        drafted_for = (d["content"].get("audience") or {}).get("id")
        if drafted_for and drafted_for != snd.get("audience_id"):
            return {"state": "refused", "note": "refused: the audience changed since the draft; "
                                                "redraft the issue"}
        return platform.send(ctx, d, when, snd)

    def ask(self, kind: str, fields: dict, store, rt) -> dict:
        """The plain dialog's parts (SEND): the subject, whom it goes to by name and count, the
        body, and what stops a send now (no account, or one that needs its setup finished),
        with the account to connect. Built from the ticket's fields and Kranto's own rows; the
        count is the platform's, read when the dialog opens (kept 5 minutes)."""
        nl = _platforms()
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        platform = nl.for_ref(fields["draft_ref"]) or nl.named(store)
        snd = nl.sender(store)
        snd = snd if platform is not None and snd.get("platform") == platform.id else {}
        conn = connection_of(store, platform.id) if platform else None
        needs = None
        if platform is None:
            needs = {"connect": "newsletter", "line": "needs a newsletter account",
                     "words": "No newsletter account is connected, so nothing can be sent yet.",
                     "button": "Connect a newsletter account"}
        elif conn is None or conn["state"] != "connected":
            needs = {"connect": platform.id, "line": f"needs {platform.name} connected",
                     "words": f"{platform.name} is not connected"
                              + (" any more: connect it again." if conn else "."),
                     "button": f"Connect {platform.name}"}
        elif platform.ready(snd):
            needs = {"connect": platform.id, "line": f"needs {platform.name}'s setup finished",
                     "words": platform.ready(snd).split(":")[0] + ".",
                     "button": f"Finish {platform.name}'s setup"}
        when = fields.get("when") or "now"
        return {"verb": "Send now", "title": fields["subject"],
                "to": None if needs and platform is None else self._to(d, platform, snd, rt),
                "body": d["content"].get("body", ""), "needs": needs,
                "schedule": bool(platform is not None and platform.can_schedule),
                "when": None if when == "now" else when}

    def _to(self, d: dict, platform, snd: dict, rt) -> str:
        """"312 subscribers on <platform>": the count the platform gives now, else the audience
        in words."""
        drafted = d["content"].get("audience") or {}
        n = drafted.get("subscribers") if isinstance(drafted.get("subscribers"), int) else None
        if n is None and rt is not None:
            n = _count(rt, platform, snd)
        if n is None:
            return f"{_audience(d, platform, snd)} on {platform.name}"
        who = f"the audience {drafted['name']}, " if drafted.get("name") else \
            f"the audience {snd['audience_name']}, " if snd.get("audience_name") else ""
        return f"{who}{n:,} subscriber{'' if n == 1 else 's'} on {platform.name}"

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        """The confirm's lines, from the ticket's fields and Kranto's own rows: the
        draft's whole body, so the owner reads what goes to every subscriber, its audience
        with the count when it was drafted, and the platform by name once one is named."""
        nl = _platforms()
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        holder = nl.for_ref(fields["draft_ref"])
        platform = holder or nl.named(store)
        snd = nl.sender(store)
        snd = snd if platform is not None and snd.get("platform") == platform.id else {}
        conn = connection_of(store, platform.id) if platform else None
        body = d["content"].get("body", "")
        when = fields.get("when", "now")
        lines = [("Draft", f"{fields['draft_ref']}, "
                           + (f"at {holder.name}" if holder else "in Kranto")),
                 ("Subject", fields["subject"]),
                 ("To", _audience(d, platform, snd))]
        if snd.get("from"):
            lines.append(("From", snd["from"]))
        lines.append(("Newsletter", conn["account"] if conn
                      else f"{platform.name} is not connected" if platform
                      else "no newsletter platform is connected"))
        if platform is not None:
            lines.append(("Platform", platform.name))
        if when != "now":
            lines.append(("When", f"scheduled for {when} (UTC); you can cancel it at "
                                  f"{platform.name if platform else nl.UNNAMED} before then"))
        lines.append(("Length", f"{len(body.split())} words, {len(body):,} characters"))
        lines.append(("Body", body))
        footer = platform.footer() if platform else None
        if footer:
            lines.append(("Footer", footer))
        return lines


def _audience(d: dict, platform, snd: dict) -> str:
    """Whom the issue goes to, in words: the audience it was drafted for with its count then,
    else the platform's audience now."""
    drafted = d["content"].get("audience") or {}
    if drafted.get("name"):
        n = drafted.get("subscribers")
        count = f", {n:,} subscriber{'' if n == 1 else 's'} when drafted" if isinstance(n, int) \
            else ""
        return f"the audience {drafted['name']}{count}"
    return platform.audience_words(snd) if platform else "all subscribers"


_COUNTS: dict[tuple, tuple[float, int | None]] = {}
COUNT_S = 300.0


def _count(rt, platform, snd: dict) -> int | None:
    """The platform's subscriber count with the owner's connection (a read), or None: not
    connected, or it did not answer. Kept ``COUNT_S`` so a dialog opened twice asks once."""
    import time

    from ....sources.base import SourceError
    from .base import BrokerContext
    conn = connection_of(rt.store, platform.id)
    if conn is None or conn["state"] != "connected":
        return None
    key = (platform.id, conn["id"], snd.get("audience_id"))
    hit = _COUNTS.get(key)
    if hit and time.monotonic() - hit[0] < COUNT_S:
        return hit[1]
    ctx = BrokerContext(store=rt.store, cub="", rt=rt, connection=conn, provider=platform.id,
                        title=platform.name)
    if not ctx.connected:
        return None
    try:
        n = platform.subscribers(ctx, snd)
    except (SourceError, BrokerError, KeyError, TypeError, ValueError):
        n = None
    n = n if isinstance(n, int) and not isinstance(n, bool) else None
    _COUNTS[key] = (time.monotonic(), n)
    return n


def _sent(store, ref: str) -> bool:
    """Whether a press sent this kranto-held draft (a ``done`` ticket that names it)."""
    kinds = [KIND, *_platforms().legacy_kinds()]
    marks = ",".join("?" * len(kinds))
    for r in store.query(f"SELECT id FROM cub_tickets WHERE kind IN ({marks}) AND "
                         "json_extract(fields, '$.draft_ref') = ?", (*kinds, ref)):
        st = tickets.state_of(store, r["id"])
        if st and st["state"] == "done":
            return True
    return False


def adapters() -> dict[str, NewsletterAdapter]:
    """The neutral service, and each earlier name as its alias."""
    out = {SERVICE: NewsletterAdapter()}
    for service, p in _platforms().legacy_services().items():
        out[service] = NewsletterAdapter(service=service, kinds=(p.legacy["kind"],),
                                         legacy=True)
    return out


def register_kinds() -> None:
    """``send.newsletter``, and each earlier kind as its alias: the old fields, the same
    title, performer and read-back (``meta.alias_of``)."""
    _F = tickets.Field
    tickets.register(tickets.Kind(KIND, "Send this issue", {
        "draft_ref": _F("str", pattern=REF, max_len=80, label="Draft"),
        "subject": _F("str", max_len=200, label="Subject"),
        "audience": _F("enum", ("all",), label="To"),
        "when": _F("str", pattern=WHEN, max_len=20, label="When")},
        expires_hours=None, per_day=3, meta=WORDS))
    for kind in _platforms().legacy_kinds():
        tickets.register(tickets.Kind(kind, "Send this issue", {
            "draft_ref": _F("str", pattern=REF, max_len=80, label="Draft"),
            "subject": _F("str", max_len=200, label="Subject"),
            "audience": _F("enum", ("all",), label="To")},
            expires_hours=None, per_day=3, meta={"alias_of": KIND}))
