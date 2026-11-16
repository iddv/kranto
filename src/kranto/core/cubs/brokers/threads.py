"""Threads: the person's press posts a variant, with their own Meta app's token (the
``threads_post`` connection), when they switched Threads to Post directly. Open (Threads' own
box, filled in) still comes first.

Two steps (developers.facebook.com/docs/threads/posts, read 2026-11-13): a container
(``POST https://graph.threads.com/v1.0/me/threads`` with ``media_type=TEXT``, ``text``,
``link_attachment``, and one ``topic_tag`` when the draft has one), then ``threads_publish`` with
its ``creation_id``. Meta asks for time between the two ("Wait about 30 seconds before
publishing"): Kranto reads the container's ``status`` every few seconds, up to half a minute, and
publishes once it says ``FINISHED``. The address is the post's ``permalink``. A thread is not
written for Threads: a reply needs one more permission (``threads_manage_replies``).

A container that never finishes is refused (nothing was published); a publish with no answer is
``unknown`` (look at your profile), never retried.
"""

from __future__ import annotations

import time

from ....scrub import scrub
from ....sources.base import SourceError
from ... import sites
from .base import BrokerContext, connection_of, draft_of, outcome_of, press_draft
from .social import parts_of

SERVICE = "threads"
API = "https://graph.threads.com/v1.0"
WAIT_S = 30.0
POLL_S = 3.0


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _why(r) -> str:
    err = _json(r).get("error")
    msg = err.get("message") if isinstance(err, dict) else None
    return scrub(msg)[:160] if isinstance(msg, str) and msg else f"Threads answered {r.status_code}"


class ThreadsAdapter:
    service = SERVICE
    provider = "threads_post"
    title = "Threads (posting)"
    cub_grantable = False
    kinds = ("post.threads",)
    ops: dict = {}
    sleep = staticmethod(time.sleep)        # a test's clock replaces it

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:   # pragma: no cover
        raise ValueError("Threads posting has no operation a cub may call")

    def perform(self, kind: str, ticket: dict, mode: str, ctx: BrokerContext) -> dict:
        d = press_draft(ctx.store, ticket, SERVICE, ("text",))
        if isinstance(d, str):
            return {"state": "refused", "note": f"refused: {d}"}
        site = sites.SITES[SERVICE]
        text = (parts_of(d["content"]) or [""])[0]
        if not text:
            return {"state": "refused", "note": "refused: the draft has no words"}
        if sites.count(site, text) > site.limit:
            return {"state": "refused", "note": f"refused: {sites.count(site, text)} characters, "
                                                f"and Threads takes {site.limit}"}
        if mode != "live":
            return {"state": "dry", "note": "practice: nothing was posted"}
        if not ctx.connected:
            return {"state": "refused", "note": "refused: Threads (posting) is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        form = {"media_type": "TEXT", "text": text}
        link = d["content"].get("link")
        if isinstance(link, str) and link.startswith("https://"):
            form["link_attachment"] = link
        tag = d["content"].get("topic_tag")
        if isinstance(tag, str) and 1 <= len(tag) <= 50 and not set(tag) & {".", "&"}:
            form["topic_tag"] = tag
        try:
            r = ctx.send("POST", f"{API}/me/threads", data=form)
        except SourceError as exc:
            return outcome_of(exc, "Threads", sending="nothing was published")
        cid = _json(r).get("id")
        if not 200 <= r.status_code < 300 or not cid:
            return {"state": "refused", "note": f"refused: {_why(r)}"}
        waited, status = 0.0, None
        while waited <= WAIT_S:
            try:
                st = ctx.send("GET", f"{API}/{cid}", params={"fields": "status,error_message"})
                status = _json(st).get("status")
            except SourceError:
                status = None
            if status in ("FINISHED", "ERROR", "EXPIRED"):
                break
            self.sleep(POLL_S)
            waited += POLL_S
        if status != "FINISHED":
            return {"state": "refused", "note": f"refused: Threads did not get the post ready "
                                                f"({status or 'no answer'}); nothing was "
                                                "published"}
        try:
            r = ctx.send("POST", f"{API}/me/threads_publish", data={"creation_id": str(cid)})
        except SourceError as exc:
            return outcome_of(exc, "Threads", sending="the post went out")
        mid = _json(r).get("id")
        if not 200 <= r.status_code < 300 or not mid:
            return {"state": "refused", "note": f"refused: {_why(r)}"}
        where = "on Threads"
        try:
            p = ctx.send("GET", f"{API}/{mid}", params={"fields": "permalink"})
            link_back = _json(p).get("permalink")
            if isinstance(link_back, str) and link_back.startswith("https://www.threads."):
                where = link_back[:300]
        except SourceError:
            pass
        from ....social import reach
        reach.sent(ctx.store, ticket["id"], SERVICE, {"id": str(mid)}, d["content"])
        return {"state": "done", "note": f"posted: {where}"}

    def ask(self, kind: str, fields: dict, store, rt=None) -> dict:
        conn = connection_of(store, self.provider)
        needs = None
        if conn is None or conn["state"] != "connected":
            needs = {"connect": self.provider, "line": "needs your Threads app's token",
                     "words": "No Threads token is connected for posting"
                              + (" any more: connect it again." if conn else "."),
                     "button": "Connect Threads"}
        first = " ".join(fields["text"].split())
        to = "everyone on Threads" + (f", as {conn['account']}" if conn else "")
        return {"verb": "Post to Threads", "title": first[:80] + ("…" if len(first) > 80 else ""),
                "to": to, "body": fields["text"], "needs": needs}

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        conn = connection_of(store, self.provider)
        site = sites.SITES[SERVICE]
        lines = [("Account", conn["account"] if conn else "Threads (posting) is not connected"),
                 ("Text", fields["text"]),
                 ("Characters", f"{sites.count(site, fields['text'])} of {site.limit}")]
        # the link the send attaches (``link_attachment``, as ``perform`` reads it)
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        link = d["content"].get("link")
        if isinstance(link, str) and link.startswith("https://"):
            lines.append(("Link", link))
        return lines
