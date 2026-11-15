"""Buttondown: a newsletter platform, connected with a pasted API key.

The key is made at buttondown.com, Settings, API, and travels as ``Authorization: Token <key>``,
with the API version pinned (``X-API-Version``) on every request so a newer default cannot change
what a call does. One call checks it and labels the connection with the newsletter's name:
``GET /v1/newsletters``. A key does not expire; it is revoked by rotating it at Buttondown.

A draft is ``POST /emails {status: draft}`` (``bd:<id>``). A send is ``PATCH /emails/<id>
{status: about_to_send}`` for a Buttondown draft, or ``POST /emails`` with the body and
``status: about_to_send`` (and the ``X-Buttondown-Live-Dangerously`` header Buttondown asks for
on a direct send) for one Kranto held. A body that starts with ``---`` is refused when drafted:
Buttondown rejects frontmatter. It goes to all subscribers, now: this adapter does not schedule.

Before MAIL a cub asked for ``send.buttondown`` and the broker service ``buttondown``; both stay
as aliases of the neutral names for one release (``legacy``).
"""

from __future__ import annotations

import re

from ..connections.base import Grant, Provider, need, status_of
from ..connections.oauth import OAuthError
from ..connections.pasted import _Header
from ..connections.secret import Secret
from ..sources.base import HTTP, SourceError
from .platform import Check, Platform

ORDER = 20
API = "https://api.buttondown.com/v1"
API_HOST = "api.buttondown.com"
API_VERSION = "2026-04-01"
SCOPES = ("emails:draft", "emails:send")
EXTERNAL_ID = re.compile(r"[A-Za-z0-9-]{1,64}")


def headers_for(key: str) -> dict[str, str]:
    return {"Authorization": f"Token {key}", "X-API-Version": API_VERSION}


class ButtondownProvider(Provider):
    key = "buttondown"
    name = "Buttondown"
    scopes = SCOPES
    default_instance = "buttondown.com"
    writes = True

    def api_host(self, instance: str, entry: dict) -> str:
        return API_HOST

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return headers_for(entry["key"])

    def paste(self, fields: dict) -> Grant:
        key = Secret(need(fields, "key", "The API key"))
        http = self.http.with_auth(_Header(API_HOST, headers_for(key.reveal())))
        try:
            account = self.identify(http, self.default_instance, {})
        except SourceError as exc:
            if exc.needs_login:
                raise OAuthError("Buttondown refused this key (HTTP 401): copy the API key "
                                 "again from Settings, API") from None
            raise OAuthError(f"Buttondown did not accept the key ({status_of(exc)})") from None
        if self.conns is not None:
            from . import keep_sender
            keep_sender(self.conns.store, PLATFORM, {})
        return Grant(account, SCOPES, {"key": key.reveal()},
                     note="Ready: issues go to all your Buttondown subscribers.")

    def identify(self, http: HTTP, instance: str, entry: dict) -> str:
        data = http.get_json(f"{API}/newsletters")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            raise OAuthError("Buttondown did not say which newsletter this key is for")
        first = results[0]
        name = first.get("name") or first.get("username")
        if not isinstance(name, str) or not name.strip():
            raise OAuthError("Buttondown did not say which newsletter this key is for")
        return name.strip()[:80]


INFO = {
    "key": "buttondown", "name": "Buttondown", "state": "available", "flow": "paste",
    "writes": True, "group": "newsletter",
    "blurb": "Your Buttondown newsletter's API key, used to send: Kranto drafts an "
             "issue, and sends it with this key only when you approve that issue "
             "(Send now).",
    "scopes": list(SCOPES),
    "reads": "Your newsletter's name and subscriber count; the drafts a cub made.",
    "never": "Never sends without your approval, and never while the cub is in practice (the "
             "default: nothing is sent) or cubs.STOP exists. Never edits subscribers.",
    "revoke_at": "buttondown.com, Settings, API: rotate the key.",
    "expiry": "no expiry",
    "steps": ["Sign in at buttondown.com and open Settings, then API "
              "(https://buttondown.com/settings/api).",
              "Copy the API key.",
              "Paste it below and click Save and test. Kranto checks it with one call and "
              "names the connection after your newsletter.",
              "A cub's issues are practice (nothing is sent) until you turn on Send for real."],
    "fields": [{"key": "key", "label": "API key", "secret": True}],
    "sources": [],
}


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _url(body: dict) -> str | None:
    url = body.get("absolute_url")
    return url if isinstance(url, str) and url.startswith("https://") and len(url) <= 300 \
        else None


class Buttondown(Platform):
    id = "buttondown"
    name = "Buttondown"
    ref_prefix = "bd"
    about = "A newsletter service: you paste an API key; issues go to all your subscribers."
    docs = "docs/newsletter.md#buttondown"
    legacy = {"kind": "send.buttondown", "service": "buttondown"}
    connection = ButtondownProvider
    info = INFO

    def check_body(self, body: str) -> str | None:
        if body.lstrip().startswith("---"):
            return "body: Buttondown refuses frontmatter (a body that starts with ---)"
        return None

    def create_draft(self, ctx, content: dict, sender: dict) -> dict:
        from ..core.cubs.brokers.base import BrokerError, reply_code
        r = ctx.send("POST", f"{API}/emails", json={
            "subject": content["subject"], "body": content["body"],
            "email_type": content.get("email_type", "public"), "status": "draft"})
        if not 200 <= r.status_code < 300:
            raise BrokerError(-32008, f"Buttondown answered {r.status_code}",
                              status=r.status_code, code=reply_code(r))
        body = _json(r)
        eid = str(body.get("id") or "")
        if not EXTERNAL_ID.fullmatch(eid):
            raise BrokerError(-32008, "Buttondown's answer had no draft id")
        return {"external_id": eid, "url": _url(body)}

    def status(self, ctx, draft: dict) -> dict:
        from ..core.cubs.brokers.base import BrokerError, reply_code
        r = ctx.send("GET", f"{API}/emails/{draft['external_id']}")
        if not 200 <= r.status_code < 300:
            raise BrokerError(-32008, f"Buttondown answered {r.status_code}",
                              status=r.status_code, code=reply_code(r))
        body = _json(r)
        st = body.get("status")
        return {"status": st if isinstance(st, str) and len(st) <= 40 else "unknown",
                "url": _url(body)}

    def newsletter(self, ctx, sender: dict) -> dict:
        from ..core.cubs.brokers.base import BrokerError, reply_code
        r = ctx.send("GET", f"{API}/newsletters")
        if not 200 <= r.status_code < 300:
            raise BrokerError(-32008, f"Buttondown answered {r.status_code}",
                              status=r.status_code, code=reply_code(r))
        results = _json(r).get("results")
        first = results[0] if isinstance(results, list) and results and \
            isinstance(results[0], dict) else {}
        name = first.get("name") or first.get("username") or ctx.label
        return {"name": str(name)[:80] if name else None,
                "subscriber_count": self.subscribers(ctx, sender)}

    def subscribers(self, ctx, sender: dict) -> int | None:
        """The count of regular subscribers, or None when Buttondown does not say."""
        try:
            r = ctx.send("GET", f"{API}/subscribers", params={"type": "regular"})
        except SourceError:
            return None
        if not 200 <= r.status_code < 300:
            return None
        count = _json(r).get("count")
        return count if isinstance(count, int) and not isinstance(count, bool) else None

    def send(self, ctx, draft: dict, when: str, sender: dict) -> dict:
        from ..core.cubs.brokers.base import outcome_of, reply_code
        if when != "now":
            return {"state": "refused", "note": "refused: Kranto sends a Buttondown issue now "
                                                "only; it does not schedule one"}
        try:
            if draft["ref"].startswith("bd:"):
                r = ctx.send("PATCH", f"{API}/emails/{draft['external_id']}",
                             json={"status": "about_to_send"})
            else:
                c = draft["content"]
                r = ctx.send("POST", f"{API}/emails",
                             json={"subject": c["subject"], "body": c["body"],
                                   "email_type": c.get("email_type", "public"),
                                   "status": "about_to_send"},
                             headers={"X-Buttondown-Live-Dangerously": "true"})
        except SourceError as exc:
            return outcome_of(exc, "Buttondown", sending="the issue was sent")
        if 200 <= r.status_code < 300:
            body = _json(r)
            eid = str(body.get("id") or draft.get("external_id") or "")
            sent = eid if EXTERNAL_ID.fullmatch(eid) else "the issue"
            url = _url(body)
            return {"state": "done", "note": f"sent: {sent}" + (f" ({url})" if url else "")
                    + "; undo within minutes at Buttondown by setting it back to draft",
                    "external_id": eid if EXTERNAL_ID.fullmatch(eid) else None}
        code = reply_code(r)
        return {"state": "refused", "note": f"refused: Buttondown answered {r.status_code}"
                + (f" ({code})" if code else "")}

    def check(self, http, sender: dict) -> Check:
        data = http.get_json(f"{API}/newsletters")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return Check(False, missing=["Buttondown did not say which newsletter this key "
                                         "is for."])
        return Check(True, said=["The key works; issues go to all your Buttondown "
                                 "subscribers."], sender={})


PLATFORM = Buttondown()
