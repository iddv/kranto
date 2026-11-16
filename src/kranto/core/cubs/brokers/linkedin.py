"""LinkedIn: the person's press posts a variant to their profile, with their own app's token
(the ``linkedin_post`` connection). LinkedIn has no link that fills in a post, so this is the only
way Kranto offers it.

``POST https://api.linkedin.com/rest/posts`` with ``Linkedin-Version: 202610`` and
``X-Restli-Protocol-Version: 2.0.0`` (Posts API, learn.microsoft.com, version 2026-10, read
2026-11-13): the author ``urn:li:person:<sub>``, the commentary in LinkedIn's "little text"
format (every reserved character escaped with a backslash, so a "#" or a "(" reads as written),
visibility from Settings (public by default), and an **article** card Kranto builds (the link,
the post's title and teaser: LinkedIn does not read the page). A ``201`` carries the post's id in
``x-restli-id``; its address is ``https://www.linkedin.com/feed/update/<id>/``.

A 401 is a token that ran out (60 days) or was revoked: refused in words, never retried.
"""

from __future__ import annotations

import re

from ....scrub import scrub
from ....sources.base import SourceError
from ... import sites
from .base import BrokerContext, connection_of, draft_of, outcome_of, press_draft
from .social import parts_of

SERVICE = "linkedin"
VERSION = "202610"
RESERVED = re.compile(r"([|{}@\[\]()<>#\\*_~])")
URN = re.compile(r"urn:li:(share|ugcPost):[0-9]{1,30}")


ESCAPED_TAG = re.compile(r"(?<![\w\\])\\#(\w{1,60})")


def little(text: str) -> str:
    """``text`` in LinkedIn's little text format: every reserved character escaped, and a tag
    (``#Word``) written as the format's hashtag, ``{hashtag|\\#|Word}``."""
    out = RESERVED.sub(r"\\\1", text)
    return ESCAPED_TAG.sub(lambda m: "{hashtag|\\#|" + m.group(1) + "}", out)


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class LinkedInAdapter:
    service = SERVICE
    provider = "linkedin_post"
    title = "LinkedIn (posting)"
    cub_grantable = False
    kinds = ("post.linkedin",)
    ops: dict = {}

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:   # pragma: no cover
        raise ValueError("LinkedIn posting has no operation a cub may call")

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
                                                f"and LinkedIn takes {site.limit}"}
        if mode != "live":
            return {"state": "dry", "note": "practice: nothing was posted"}
        if not ctx.connected:
            return {"state": "refused", "note": "refused: LinkedIn (posting) is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        # the author: the member's id, read at the press (the adapter never sees the vault)
        try:
            who = ctx.send("GET", "https://api.linkedin.com/v2/userinfo")
        except SourceError as exc:
            return outcome_of(exc, "LinkedIn", sending="nothing went out")
        sub = _json(who).get("sub") if who.status_code == 200 else None
        if not isinstance(sub, str) or not sub:
            return {"state": "refused", "note": f"refused: LinkedIn did not say whose token this "
                                                f"is ({who.status_code})"}
        body: dict = {
            "author": f"urn:li:person:{sub}", "commentary": little(text),
            "visibility": d["content"].get("visibility") or "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
        card = d["content"].get("card")
        if isinstance(card, dict) and isinstance(card.get("url"), str) and card.get("title"):
            body["content"] = {"article": {"source": card["url"],
                                           "title": str(card["title"])[:399],
                                           "description": str(card.get("description") or "")
                                           [:4000]}}
        try:
            r = ctx.send("POST", "https://api.linkedin.com/rest/posts", json=body,
                         headers={"Linkedin-Version": VERSION,
                                  "X-Restli-Protocol-Version": "2.0.0"})
        except SourceError as exc:
            return outcome_of(exc, "LinkedIn", sending="the post went out")
        if r.status_code == 201:
            urn = str(r.headers.get("x-restli-id") or "")
            where = f"https://www.linkedin.com/feed/update/{urn}/" if URN.fullmatch(urn) \
                else "on your LinkedIn profile"
            from ....social import reach
            reach.sent(ctx.store, ticket["id"], SERVICE,
                       {"urn": urn} if URN.fullmatch(urn) else {}, d["content"])
            return {"state": "done", "note": f"posted: {where}"}
        msg = _json(r).get("message")
        said = scrub(msg)[:160] if isinstance(msg, str) and msg else \
            f"LinkedIn answered {r.status_code}"
        return {"state": "refused", "note": f"refused: {said}"}

    def ask(self, kind: str, fields: dict, store, rt=None) -> dict:
        conn = connection_of(store, self.provider)
        needs = None
        if conn is None or conn["state"] != "connected":
            needs = {"connect": self.provider, "line": "needs your LinkedIn app's token",
                     "words": "No LinkedIn token is connected for posting"
                              + (" any more: make a new one." if conn else "."),
                     "button": "Connect LinkedIn"}
        first = " ".join(fields["text"].split())
        to = "your LinkedIn profile, everyone" + (f", as {conn['account']}" if conn else "")
        return {"verb": "Post to LinkedIn", "title": first[:80] + ("…" if len(first) > 80 else ""),
                "to": to, "body": fields["text"], "needs": needs}

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        conn = connection_of(store, self.provider)
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        site = sites.SITES[SERVICE]
        lines = [("Account", conn["account"] if conn else "LinkedIn (posting) is not connected"),
                 ("Text", fields["text"]),
                 ("Characters", f"{sites.count(site, fields['text'])} of {site.limit}")]
        card = d["content"].get("card")
        if isinstance(card, dict) and card.get("url"):
            # the address the article card attaches, beside its title
            lines.append(("Link card", str(card.get("title") or card["url"])))
            lines.append(("Link", str(card["url"])))
        return lines
