"""Bluesky: the person's press posts a variant Kranto's writer drafted.

The server and the session are the ``bluesky_post`` connection's (an app password in the vault,
a session made from it at send time; ``Authorization: Bearer`` is added by the HTTP layer for
the person's own server only). Every request has a deadline and none is retried.

A post is ``com.atproto.repo.createRecord`` of an ``app.bsky.feed.post`` (AT Protocol, "Posts":
https://docs.bsky.app/docs/advanced-guides/posts, read 2026-11-13):

- the text as written, with **facets** for each link and tag: byte ranges of the UTF-8 text, so
  a link is a link and a tag is a tag whatever comes before it (an emoji, an accent);
- a **link card** (``app.bsky.embed.external``) Kranto builds from what it already knows: the
  blog post's title and teaser, or the source's (Bluesky draws no card by itself);
- a **thread** part by part, each a reply to the one before with the first as its root. If a
  part fails, the ask ends ``unknown`` "posted 2 of 3 on Bluesky: <address>; the rest was not
  sent" and nothing is retried or deleted.

The draft must be the filer's, unchanged since it was written, and say what the person read
(``press_draft``); the site's limit is checked again at the press, part by part.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from ....scrub import scrub
from ....sources.base import SourceError
from ... import sites
from .base import BrokerContext, connection_of, draft_of, outcome_of, press_draft
from .social import parts_of

SERVICE = "bluesky"
TAG = re.compile(r"(?<![\w#])#(\w{1,64})")


def facets(text: str) -> list[dict]:
    """Links and tags of ``text`` as Bluesky's facets: byte offsets into its UTF-8."""
    out: list[dict] = []

    def span(start: int, end: int) -> dict:
        return {"byteStart": len(text[:start].encode()), "byteEnd": len(text[:end].encode())}
    for m in sites.URL.finditer(text):
        url = m.group(0).rstrip(".,;:!?")
        out.append({"index": span(m.start(), m.start() + len(url)),
                    "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]})
    for m in TAG.finditer(text):
        if any(f["index"]["byteStart"] <= len(text[:m.start()].encode()) < f["index"]["byteEnd"]
               for f in out):
            continue                   # a "#" inside a link's address is the link's
        out.append({"index": span(m.start(), m.end()),
                    "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(1)}]})
    return out


def post_address(handle: str, uri: str) -> str | None:
    """``at://<did>/app.bsky.feed.post/<key>`` as the address a person opens."""
    m = re.fullmatch(r"at://[^/]+/app\.bsky\.feed\.post/([A-Za-z0-9]{1,64})", uri or "")
    if not m or not handle:
        return None
    return f"https://bsky.app/profile/{handle.lstrip('@')}/post/{m.group(1)}"


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class BlueskyAdapter:
    service = SERVICE
    provider = "bluesky_post"
    title = "Bluesky (posting)"
    cub_grantable = False               # no op a cub may call; its kind is Kranto's own
    kinds = ("post.bluesky",)
    ops: dict = {}

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:   # pragma: no cover
        raise ValueError("Bluesky posting has no operation a cub may call")

    def perform(self, kind: str, ticket: dict, mode: str, ctx: BrokerContext) -> dict:
        d = press_draft(ctx.store, ticket, SERVICE, ("text", "language"))
        if isinstance(d, str):
            return {"state": "refused", "note": f"refused: {d}"}
        site = sites.SITES[SERVICE]
        parts = parts_of(d["content"])
        if not parts:
            return {"state": "refused", "note": "refused: the draft has no words"}
        if len(parts) != (ticket["fields"].get("parts") or 1):
            return {"state": "refused", "note": "refused: the draft changed: its posts are not "
                                                "what you were shown"}
        for i, p in enumerate(parts, 1):
            n = sites.count(site, p)
            if n > site.limit:
                return {"state": "refused", "note": f"refused: post {i} is {n} characters, and "
                                                    f"Bluesky takes {site.limit}"}
        if mode != "live":
            return {"state": "dry", "note": "practice: nothing was posted"}
        if not ctx.connected:
            return {"state": "refused", "note": "refused: Bluesky (posting) is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        handle = (ctx.label or "").lstrip("@")
        lang = d["content"].get("language") or "en"
        card = d["content"].get("card")
        root = parent = None
        first_address = None
        for i, text in enumerate(parts):
            record: dict = {"$type": "app.bsky.feed.post", "text": text,
                            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                            "langs": [lang]}
            f = facets(text)
            if f:
                record["facets"] = f
            if i == 0 and isinstance(card, dict) and isinstance(card.get("url"), str):
                record["embed"] = {"$type": "app.bsky.embed.external", "external": {
                    "uri": card["url"], "title": str(card.get("title") or "")[:300],
                    "description": str(card.get("description") or "")[:1000]}}
            if root is not None:
                record["reply"] = {"root": root, "parent": parent}
            try:
                r = ctx.send("POST", f"https://{ctx.instance}/xrpc/com.atproto.repo.createRecord",
                             json={"repo": handle, "collection": "app.bsky.feed.post",
                                   "record": record})
            except SourceError as exc:
                if i == 0:
                    return outcome_of(exc, "Bluesky", sending="the post went out")
                return {"state": "unknown", "note": f"posted {i} of {len(parts)} on Bluesky: "
                                                    f"{first_address}; the rest was not sent"}
            body = _json(r)
            if not 200 <= r.status_code < 300 or not body.get("uri"):
                why = body.get("message") if isinstance(body.get("message"), str) else None
                said = scrub(why)[:160] if why else f"Bluesky answered {r.status_code}"
                if i == 0:
                    return {"state": "refused", "note": f"refused: {said}"}
                return {"state": "unknown", "note": f"posted {i} of {len(parts)} on Bluesky: "
                                                    f"{first_address}; the rest was not sent "
                                                    f"({said})"}
            ref = {"uri": body["uri"], "cid": body.get("cid")}
            if root is None:
                root = ref
                first_address = post_address(handle, body["uri"]) or "on Bluesky"
            parent = ref
        from ....social import reach
        reach.sent(ctx.store, ticket["id"], SERVICE, {"uri": (root or {}).get("uri")},
                   d["content"], parts=len(parts))
        return {"state": "done", "note": f"posted: {first_address}"}

    def ask(self, kind: str, fields: dict, store, rt=None) -> dict:
        conn = connection_of(store, self.provider)
        needs = None
        if conn is None or conn["state"] != "connected":
            needs = {"connect": self.provider, "line": "needs a Bluesky account connected",
                     "words": "No Bluesky account is connected for posting"
                              + (" any more: connect it again." if conn else "."),
                     "button": "Connect Bluesky"}
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        parts = parts_of(d["content"])
        body = "\n\n— — —\n\n".join(parts) if len(parts) > 1 else fields["text"]
        first = " ".join(fields["text"].split())
        to = "everyone on Bluesky" + (f", as {conn['account']}" if conn else "")
        return {"verb": "Post to Bluesky", "title": first[:80] + ("…" if len(first) > 80 else ""),
                "to": to, "body": body, "needs": needs}

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        conn = connection_of(store, self.provider)
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        parts = parts_of(d["content"])
        site = sites.SITES[SERVICE]
        lines = [("Account", conn["account"] if conn else "Bluesky (posting) is not connected")]
        for i, p in enumerate(parts, 1):
            label = "Text" if len(parts) == 1 else f"Post {i} of {len(parts)}"
            lines.append((label, p))
            lines.append(("Characters", f"{sites.count(site, p)} of {site.limit}"))
        card = d["content"].get("card")
        if isinstance(card, dict) and card.get("url"):
            lines.append(("Link card", f"{card.get('title') or card['url']}"))
        lines.append(("Language", fields["language"]))
        return lines
