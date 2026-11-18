"""Mastodon: a cub drafts a post; the owner's press publishes it.

The instance and the token are the ``mastodon_post`` connection's (one posting account per
Kranto); ``Authorization: Bearer`` is added by the HTTP layer; form-encoded bodies; 60 s. Mastodon
has no server-side drafts, so every draft is held by Kranto (``draft:<id>``). The instance's
character limit (``configuration.statuses.max_characters`` of ``GET /api/v2/instance``) is kept
24 hours, the account an hour; 500 when not connected.

A post is ``POST /api/v1/statuses`` with ``Idempotency-Key: kranto-ticket-<id>``: Mastodon keeps
the key an hour, so a second request for the same ticket cannot post twice (and Kranto never
sends one by itself).
"""

from __future__ import annotations

import threading
import time

from ....scrub import scrub
from ...api import fence
from .base import (
    BrokerContext,
    BrokerError,
    Op,
    connection_of,
    draft_of,
    drafts_list,
    new_draft,
    outcome_of,
    press_draft,
)

SERVICE = "mastodon"
DEFAULT_LIMIT = 500
LIMIT_S = 24 * 3600
ACCOUNT_S = 3600
LANGUAGE = ("str", {"pattern": r"[a-z]{2}(-[A-Za-z]{2})?", "max_len": 5}, False)
VISIBILITY = ("enum", {"choices": ("public", "unlisted", "private")}, False)


class MastodonAdapter:
    service = SERVICE
    provider = "mastodon_post"
    title = "Mastodon (posting)"
    cub_grantable = True
    kinds = ("post.mastodon",)
    ops = {
        "statuses.draft": Op(
            "statuses.draft", "draft",
            {"text": ("str", {"max_len": 5000}, True), "visibility": VISIBILITY,
             "language": LANGUAGE, "spoiler_text": ("str", {"max_len": 200}, False)},
            needs_credential=False, per_day=20),
        "drafts.list": Op("drafts.list", "read", {"limit": ("int", {"lo": 1, "hi": 50}, False)},
                          needs_credential=False, per_hour=60),
        "account.get": Op("account.get", "read", {}, needs_credential=True, per_hour=60),
        "instance.limits": Op("instance.limits", "read", {}, needs_credential=True,
                              per_hour=60),
    }

    def __init__(self) -> None:
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: tuple, ttl: float, fetch):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and now - hit[0] < ttl:
                return hit[1]
        value = fetch()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    # -- the operations a cub may be granted ------------------------------------------------

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:
        return getattr(self, "_" + op.replace(".", "_"))(args, ctx)

    def limit(self, ctx: BrokerContext) -> int:
        """The instance's character limit; 500 when not connected or when it does not say."""
        if not ctx.connected:
            return DEFAULT_LIMIT
        from ....sources.base import SourceError
        try:
            return self._limits(ctx)["max_characters"]
        except (SourceError, BrokerError):
            return DEFAULT_LIMIT

    def _limits(self, ctx: BrokerContext) -> dict:
        def fetch() -> dict:
            r = ctx.send("GET", f"https://{ctx.instance}/api/v2/instance")
            if not 200 <= r.status_code < 300:
                raise BrokerError(-32008, f"the instance answered {r.status_code}",
                                  status=r.status_code)
            body = _json(r)
            n = (((body.get("configuration") or {}).get("statuses") or {})
                 .get("max_characters"))
            ok = isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 100000
            return {"instance": ctx.instance, "max_characters": n if ok else DEFAULT_LIMIT}
        return self._cached(("limits", ctx.connection["id"]), LIMIT_S, fetch)

    def _statuses_draft(self, a: dict, ctx: BrokerContext) -> dict:
        limit = self.limit(ctx)
        if len(a["text"]) > limit:
            raise BrokerError(-32005, f"text: {len(a['text'])} characters, the limit is {limit}",
                              limit=limit, got=len(a["text"]))
        content = {"text": a["text"], "visibility": a.get("visibility", "public"),
                   "language": a.get("language", "en"), "spoiler_text": a.get("spoiler_text")}
        d = new_draft(ctx.store, cub=ctx.cub, service=SERVICE, content=content,
                      run_uuid=ctx.run_uuid)
        return {"draft_ref": d["ref"], "chars": len(a["text"]), "limit": limit, "where": "kranto"}

    def _drafts_list(self, a: dict, ctx: BrokerContext) -> dict:
        return drafts_list(ctx.store, ctx.cub, SERVICE, a.get("limit", 50), "text")

    def _account_get(self, a: dict, ctx: BrokerContext) -> dict:
        def fetch() -> dict:
            r = ctx.send("GET", f"https://{ctx.instance}/api/v1/accounts/verify_credentials")
            if not 200 <= r.status_code < 300:
                raise BrokerError(-32008, f"the instance answered {r.status_code}",
                                  status=r.status_code)
            body = _json(r)
            url = body.get("url")
            return {"acct": ctx.label,
                    "url": url if isinstance(url, str) and url.startswith("https://")
                    and len(url) <= 300 else None,
                    "display_name": fence(str(body.get("display_name") or ""))[:200]}
        return self._cached(("account", ctx.connection["id"]), ACCOUNT_S, fetch)

    def _instance_limits(self, a: dict, ctx: BrokerContext) -> dict:
        return self._limits(ctx)

    # -- the owner's press ----------------------------------------------------------------

    def perform(self, kind: str, ticket: dict, mode: str, ctx: BrokerContext) -> dict:
        from ....sources.base import SourceError

        d = press_draft(ctx.store, ticket, SERVICE, ("text", "visibility", "language"))
        if isinstance(d, str):
            return {"state": "refused", "note": f"refused: {d}"}
        if mode != "live":
            who = ctx.label or "your posting account (not connected yet)"
            return {"state": "dry", "note": f"practice: nothing was posted. For real it would "
                                            f"post as {who}"}
        if not ctx.connected:
            return {"state": "refused", "note": "refused: Mastodon (posting) is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        c = d["content"]
        limit = self.limit(ctx)
        if len(c["text"]) > limit:
            return {"state": "refused", "note": f"refused: {len(c['text'])} characters, the "
                                                f"instance's limit is {limit}"}
        form = {"status": c["text"], "visibility": c["visibility"], "language": c["language"]}
        if c.get("spoiler_text"):
            form["spoiler_text"] = c["spoiler_text"]
        try:
            r = ctx.send("POST", f"https://{ctx.instance}/api/v1/statuses", data=form,
                         headers={"Idempotency-Key": f"kranto-ticket-{ticket['id']}"})
        except SourceError as exc:
            return outcome_of(exc, "the instance", sending="the post went out")
        if 200 <= r.status_code < 300:
            url = _json(r).get("url")
            where = url if isinstance(url, str) and url.startswith("https://") \
                and len(url) <= 300 else f"on {ctx.instance}"
            sid = _json(r).get("id")
            if isinstance(sid, str) and sid.isdigit() and len(sid) <= 30:
                from ....social import reach
                reach.sent(ctx.store, ticket["id"], SERVICE,
                           {"id": sid, "instance": ctx.instance or ""}, c)
            return {"state": "done", "note": f"posted: {where}"}
        if r.status_code == 422:
            error = _json(r).get("error")
            why = scrub(str(error))[:200] if isinstance(error, str) and error else "422"
            return {"state": "refused", "note": f"refused: {why}"}
        return {"state": "refused", "note": f"refused: the instance answered {r.status_code}"}

    def ask(self, kind: str, fields: dict, store, rt=None) -> dict:
        """The plain dialog's parts: the toot's text, whom it goes to (the account and the
        visibility), and the posting account to connect when it is not."""
        conn = connection_of(store, self.provider)
        needs = None
        if conn is None or conn["state"] != "connected":
            needs = {"connect": self.provider, "line": "needs a Mastodon account connected",
                     "words": "No Mastodon account is connected for posting"
                              + (" any more: connect it again." if conn else "."),
                     "button": "Connect Mastodon"}
        d = draft_of(store, fields["draft_ref"])
        warning = (d or {}).get("content", {}).get("spoiler_text")
        seen = {"public": "everyone", "unlisted": "everyone, kept off the public timelines",
                "private": "your followers only"}[fields["visibility"]]
        to = f"{seen}, as {conn['account']}" if conn else seen
        body = (f"Content warning: {warning}\n\n" if warning else "") + fields["text"]
        first = " ".join(fields["text"].split())
        return {"verb": "Post toot", "title": first[:80] + ("…" if len(first) > 80 else ""),
                "to": to, "body": body, "needs": needs}

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        """The confirm's lines. The content warning is the draft's own (Kranto's row, which the
        press posts and its hash binds): the owner reads what the post will carry."""
        conn = connection_of(store, self.provider)
        hit = self._cache.get(("limits", conn["id"])) if conn else None
        limit = hit[1]["max_characters"] if hit else DEFAULT_LIMIT
        d = draft_of(store, fields["draft_ref"])
        warning = (d or {}).get("content", {}).get("spoiler_text") or "none"
        return [("Account", conn["account"] if conn else "Mastodon (posting) is not connected"),
                ("Content warning", warning),
                ("Text", fields["text"]),
                ("Visibility", fields["visibility"]),
                ("Language", fields["language"]),
                ("Characters", f"{len(fields['text'])} of {limit}")]


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
