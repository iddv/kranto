"""Sanity: a cub drafts a post; the owner's press files it in Sanity as a draft.

The project, the dataset and the token are the ``sanity`` connection's (one per Kranto);
``Authorization: Bearer`` is added by the HTTP layer for ``<project>.api.sanity.io`` only; every
request has a deadline and none is retried.

What the press does, live, with one draft the ticket names (this cub's, unchanged since it was
written, its title, slug and category the ticket's):

1. reads ``drafts.kranto-<doc>`` and ``kranto-<doc>`` (``GET …/data/doc``); a published
   ``kranto-<doc>`` is refused (Kranto never drafts over a published post);
2. refuses a slug another post already has (a GROQ read over drafts and published posts);
3. a draft already there is overwritten only when nobody edited it since Kranto wrote it: Kranto
   writes the hash of what it wrote into ``<META>.contentHash`` (``legacy.SANITY_META``, a field
   stored in the documents) and compares it with the
   draft's fields now; the patch carries ``ifRevisionID``, so a change in between is a 409;
4. otherwise one ``create`` of ``drafts.kranto-<doc>`` (``_type: post``, no ``publishedAt``:
   Studio lists it under Draft Posts, and publishing needs the owner to set the date).

What it never does, by construction: publish (no op does), delete, write an id that does not
start with ``drafts.kranto-``, touch categories (it looks one up by its title and references it;
a missing one is said), send email (example.com's own webhook mails on the owner's publish).
"""

from __future__ import annotations

import hashlib
import json
import math
import re

from .... import legacy
from ....connections.sanity import api_base, dataset_of, site
from ....scrub import scrub
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
    outcome_of,
    own_draft,
    press_draft,
)

SERVICE = "sanity"
KIND = "draft.sanity"
PREFIX = "kranto-"
DOC = r"[a-z0-9]+(-[a-z0-9]+)*"
SLUG = r"[a-z0-9]+(-[a-z0-9]+)*"
CATEGORIES = ("dispatch", "build")
ORIGINS = ("brief", "topic", "build", "markdown", "pick", "radar", "card")
TAGS_MAX = 12
WORDS_A_MINUTE = 230


# the field Kranto writes into a Sanity document; existing documents carry it, so it keeps its name
META = legacy.SANITY_META

def sanity_ids(doc: str) -> tuple[str, str]:
    """``(draft id, published id)`` of a cub's document ``doc``."""
    return f"drafts.{PREFIX}{doc}", f"{PREFIX}{doc}"


def tags_of(text: str | None) -> list[str]:
    """``"Kranto, AI agents"`` as a list: trimmed, unique, at most twelve of 40 characters."""
    out: list[str] = []
    for t in (text or "").split(","):
        t = " ".join(t.split())[:40]
        if t and t.casefold() not in {x.casefold() for x in out}:
            out.append(t)
    return out[:TAGS_MAX]


def fields_of(content: dict) -> dict:
    """The post's fields Kranto writes (and hashes), from a draft's content."""
    out = {"title": content["title"],
           "slug": {"_type": "slug", "current": content["slug"]},
           "markdownBody": content["body"],
           "tags": list(content.get("tags") or []),
           "readTime": max(1, math.ceil(len(content["body"].split()) / WORDS_A_MINUTE))}
    for key, name in (("excerpt", "excerpt"), ("email_teaser", "emailTeaser"),
                      ("x_post", "xPost"), ("linkedin_post", "linkedinPost")):
        if content.get(key):
            out[name] = content[key]
    return out


HASHED = ("title", "slug", "markdownBody", "tags", "excerpt", "emailTeaser", "xPost",
          "linkedinPost")


def written_hash(doc: dict) -> str:
    """The hash of a post's kranto-written fields as they are now (a Studio edit changes it)."""
    seen = {k: doc.get(k) for k in HASHED if doc.get(k) not in (None, "", [])}
    if isinstance(seen.get("slug"), dict):
        seen["slug"] = seen["slug"].get("current")
    return hashlib.sha256(json.dumps(seen, sort_keys=True, separators=(",", ":"))
                          .encode()).hexdigest()


def studio_link(store, doc: str) -> str | None:
    studio = site(store).get("studio")
    return f"{studio}/intent/edit/id={PREFIX}{doc};type=post" if studio else None


def post_link(store, slug: str) -> str | None:
    base = site(store).get("post_url")
    return f"{base}/{slug}" if base else None


class SanityAdapter:
    service = SERVICE
    provider = "sanity"
    title = "Sanity"
    cub_grantable = True
    kinds = (KIND,)
    ops = {
        "documents.draft": Op(
            "documents.draft", "draft",
            {"doc": ("str", {"pattern": DOC, "max_len": 80}, True),
             "title": ("str", {"max_len": 200}, True),
             "slug": ("str", {"pattern": SLUG, "max_len": 96}, True),
             "body": ("str", {"max_len": 200000}, True),
             "category": ("enum", {"choices": CATEGORIES}, True),
             "excerpt": ("str", {"max_len": 280}, False),
             "tags": ("str", {"max_len": 600}, False),
             "email_teaser": ("str", {"max_len": 1200}, False),
             "x_post": ("str", {"max_len": 280}, False),
             "linkedin_post": ("str", {"max_len": 1300}, False),
             "origin": ("enum", {"choices": ORIGINS}, False),
             "cites": ("str", {"max_len": 400}, False)},
            needs_credential=False, per_day=20),
        "documents.get": Op("documents.get", "read",
                            {"draft_ref": ("str", {"max_len": 20}, True)},
                            needs_credential=True, per_hour=60),
        "drafts.list": Op("drafts.list", "read", {"limit": ("int", {"lo": 1, "hi": 50}, False)},
                          needs_credential=False, per_hour=60),
    }

    # -- the operations a cub may be granted ------------------------------------------------

    def call(self, op: str, args: dict, ctx: BrokerContext) -> dict:
        return getattr(self, "_" + op.replace(".", "_"))(args, ctx)

    def _documents_draft(self, a: dict, ctx: BrokerContext) -> dict:
        if a["body"].lstrip().startswith("---"):
            raise BrokerError(-32005, "body: no frontmatter (a body that starts with ---): put "
                                      "the title, slug and tags in their own arguments")
        content = {"doc": a["doc"], "title": a["title"], "slug": a["slug"], "body": a["body"],
                   "category": a["category"], "excerpt": a.get("excerpt"),
                   "tags": tags_of(a.get("tags")), "email_teaser": a.get("email_teaser"),
                   "x_post": a.get("x_post"), "linkedin_post": a.get("linkedin_post"),
                   "origin": a.get("origin"), "cites": a.get("cites")}
        d = new_draft(ctx.store, cub=ctx.cub, service=SERVICE, content=content,
                      run_uuid=ctx.run_uuid)
        return {"draft_ref": d["ref"], "sanity_id": sanity_ids(a["doc"])[0], "where": "kranto",
                "slug": a["slug"], "created_at": d["created_at"]}

    def _documents_get(self, a: dict, ctx: BrokerContext) -> dict:
        d = own_draft(ctx.store, ctx.cub, SERVICE, a["draft_ref"])
        draft_id, pub_id = sanity_ids(d["content"]["doc"])
        found = self._docs(ctx, d["content"]["doc"])
        if isinstance(found, BrokerError):
            raise found
        draft = found.get(draft_id)
        return {"draft_ref": d["ref"], "sanity_id": draft_id, "in_sanity": draft is not None,
                "edited": bool(draft) and _edited(draft), "published": pub_id in found,
                "studio_url": studio_link(ctx.store, d["content"]["doc"])}

    def _drafts_list(self, a: dict, ctx: BrokerContext) -> dict:
        return drafts_list(ctx.store, ctx.cub, SERVICE, a.get("limit", 50), "title")

    # -- reads at Sanity ------------------------------------------------------------------

    def _docs(self, ctx: BrokerContext, doc: str) -> dict | BrokerError:
        """``{id: document}`` of the draft and the published post that exist, or why not."""
        r = ctx.send("GET", f"{api_base(ctx.instance)}/doc/{dataset_of(ctx.instance)}/"
                            + ",".join(sanity_ids(doc)))
        if not 200 <= r.status_code < 300:
            return BrokerError(-32008, f"Sanity answered {r.status_code}", status=r.status_code)
        body = _json(r)
        if any(isinstance(o, dict) and o.get("reason") == "permission"
               for o in body.get("omitted") or []):
            return BrokerError(-32008, "the token cannot read drafts: make an Editor token")
        return {x["_id"]: x for x in body.get("documents") or []
                if isinstance(x, dict) and isinstance(x.get("_id"), str)}

    def _slug_taken(self, ctx: BrokerContext, doc: str, slug: str) -> str | None:
        """The id of another post (draft or published) with this slug, or None."""
        r = ctx.send("GET", f"{api_base(ctx.instance)}/query/{dataset_of(ctx.instance)}",
                     params={"query": '*[_type == "post" && slug.current == $slug && '
                                      '!(_id in $ours)][0]._id',
                             "$slug": json.dumps(slug),
                             "$ours": json.dumps(list(sanity_ids(doc)))})
        if not 200 <= r.status_code < 300:
            raise BrokerError(-32008, f"Sanity answered {r.status_code}", status=r.status_code)
        other = _json(r).get("result")
        return other if isinstance(other, str) else None

    def _category(self, ctx: BrokerContext, word: str) -> str | None:
        """The id of the category titled ``Dispatch`` (or ``Dispatches``), or None."""
        r = ctx.send("GET", f"{api_base(ctx.instance)}/query/{dataset_of(ctx.instance)}",
                     params={"query": '*[_type == "category" && lower(title) in $titles && '
                                      '!(_id in path("drafts.**"))][0]._id',
                             "$titles": json.dumps([word, word + "es" if word.endswith("h")
                                                    else word + "s"])})
        if not 200 <= r.status_code < 300:
            return None
        found = _json(r).get("result")
        return found if isinstance(found, str) else None

    # -- the owner's press ----------------------------------------------------------------

    def perform(self, kind: str, ticket: dict, mode: str, ctx: BrokerContext) -> dict:
        from ....sources.base import SourceError

        d = press_draft(ctx.store, ticket, SERVICE, ("title", "slug", "category"))
        if isinstance(d, str):
            return {"state": "refused", "note": f"refused: {d}"}
        c = d["content"]
        draft_id, pub_id = sanity_ids(c["doc"])
        if mode != "live":
            where = ctx.label or "Sanity (not connected yet)"
            return {"state": "dry", "note": f"practice: nothing was sent; the draft stays in "
                                            f"Kranto. For real it would be filed as {draft_id} "
                                            f"in {where}, for you to publish in Studio"}
        if not ctx.connected:
            return {"state": "refused", "note": "refused: Sanity is not connected"
                    + (" (it needs you to reconnect it)" if ctx.connection else "")}
        try:
            found = self._docs(ctx, c["doc"])
            if isinstance(found, BrokerError):
                return {"state": "refused", "note": f"refused: {found.message}"}
            if pub_id in found:
                return {"state": "refused", "note": f"refused: {pub_id} is published already; "
                                                    "Kranto does not draft over a published post"}
            other = self._slug_taken(ctx, c["doc"], c["slug"])
            if other:
                return {"state": "refused", "note": f"refused: the post {other} already has the "
                                                    f"slug {c['slug']}"}
            category = self._category(ctx, c["category"])
        except BrokerError as exc:
            return {"state": "refused", "note": f"refused: {exc.message}"}
        except SourceError as exc:
            return outcome_of(exc, "Sanity", sending="nothing was written (Kranto only read)")
        doc = fields_of(c)
        if category:
            doc["categories"] = [{"_type": "reference", "_ref": category,
                                  "_key": f"kranto-{c['category']}"}]
        doc[META] = {"origin": c.get("origin") or "markdown", "draftRef": d["ref"],
                            "ticket": int(ticket["id"]), "cites": c.get("cites") or "",
                            "filedAt": iso(utcnow()), "contentHash": written_hash(doc)}
        existing = found.get(draft_id)
        if existing is not None:
            if _edited(existing):
                return {"state": "refused", "note": f"refused: {draft_id} was edited in Studio "
                                                    "since Kranto filed it; edit it there, or "
                                                    "delete it in Studio and redraft"}
            if (existing.get(META) or {}).get("contentHash") == \
                    doc[META]["contentHash"]:
                return {"state": "done", "note": f"filed already, unchanged: {draft_id}"
                        + _where(ctx.store, c["doc"])}
            mutation = {"patch": {"id": draft_id, "ifRevisionID": existing.get("_rev"),
                                  "set": doc}}
        else:
            mutation = {"create": {"_id": draft_id, "_type": "post", **doc}}
        try:
            r = ctx.send("POST", f"{api_base(ctx.instance)}/mutate/{dataset_of(ctx.instance)}"
                                 "?returnIds=true&visibility=sync",
                         json={"mutations": [mutation]})
        except SourceError as exc:
            return outcome_of(exc, "Sanity", sending=f"{draft_id} was written")
        if 200 <= r.status_code < 300:
            return {"state": "done", "note": f"filed: {draft_id}" + _where(ctx.store, c["doc"])
                    + ("" if category else f"; no category titled {c['category'].title()} in "
                                           "Sanity: set one in Studio")}
        if r.status_code == 409:
            return {"state": "refused", "note": f"refused: {draft_id} changed in Sanity while "
                                                "Kranto filed it; look in Studio, then redraft"}
        if r.status_code in (401, 403):
            return {"state": "refused", "note": f"refused: the token may not write drafts "
                                                f"(HTTP {r.status_code}): make an Editor token "
                                                "and connect it again"}
        why = _error(r)
        return {"state": "refused", "note": f"refused: Sanity answered {r.status_code}"
                + (f" ({why})" if why else "")}

    def ask(self, kind: str, fields: dict, store, rt=None) -> dict:
        """The plain dialog's parts (SEND): the title, where it goes (a draft in the owner's
        Sanity project, published by them in Studio), the body, and Sanity to connect when it is
        not."""
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        conn = connection_of(store, "sanity")
        needs = None
        if conn is None:
            # a fresh install: no blog was ever set (Post's line says "Blog: not set"), so
            # the row says what to do, not a platform the owner never chose
            needs = {"connect": "sanity", "line": "copy it, or choose where blog posts go",
                     "words": "No blog is set yet: copy the post, or choose where blog posts "
                              "go (Sanity) and send it there.",
                     "button": "Connect Sanity"}
        elif conn["state"] != "connected":
            needs = {"connect": "sanity", "line": "needs Sanity connected again",
                     "words": "Sanity is not connected any more: connect it again.",
                     "button": "Connect Sanity"}
        url = post_link(store, fields["slug"])
        to = (f"a draft in {conn['account']}" if conn else "a draft in your Sanity project") \
            + ", for you to publish in Studio" + (f" ({url})" if url else "")
        return {"verb": "Send to Sanity", "title": fields["title"], "to": to,
                "body": d["content"].get("body") or "", "needs": needs}

    def readback(self, kind: str, fields: dict, store) -> list[tuple[str, str]]:
        """The confirm's lines (the owner reads what they approve), from the ticket's
        fields and Kranto's own draft row: the whole body, the teaser and the two social texts
        the post will carry, where it will be filed and where it will be read."""
        d = draft_of(store, fields["draft_ref"]) or {"content": {}}
        c = d["content"]
        conn = connection_of(store, "sanity")
        doc = c.get("doc") or "?"
        body = c.get("body") or ""
        url = post_link(store, fields["slug"])
        lines = [("Draft", f"{fields['draft_ref']}, in Kranto"),
                 ("Files as", f"{sanity_ids(doc)[0]} in "
                              + (conn["account"] if conn else "Sanity (not connected)")),
                 ("Title", fields["title"]),
                 ("Slug", fields["slug"] + (f" ({url} once you publish)" if url else "")),
                 ("Category", fields["category"].title()),
                 ("Tags", ", ".join(c.get("tags") or []) or "none"),
                 ("Excerpt", c.get("excerpt") or "none"),
                 ("Length", f"{len(body.split())} words, {len(body):,} characters"),
                 ("Body", body),
                 ("Email teaser", c.get("email_teaser") or "none (the email uses the excerpt)"),
                 ("X post", c.get("x_post") or "none"),
                 ("LinkedIn post", c.get("linkedin_post") or "none"),
                 ("Sources", c.get("cites") or "none"),
                 ("Publishing", "Kranto never publishes: you read it and publish it in Studio")]
        link = studio_link(store, doc)
        if link:
            lines.append(("Studio", link))
        return lines


def _edited(draft: dict) -> bool:
    """Whether a draft's kranto-written fields changed since Kranto wrote them (or Kranto never
    wrote it: no hash)."""
    said = (draft.get(META) or {}).get("contentHash")
    return not said or said != written_hash(draft)


def _where(store, doc: str) -> str:
    link = studio_link(store, doc)
    return f" ({link})" if link else " (Studio: Draft Posts)"


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error(r) -> str | None:
    """Sanity's error type (``mutationError``, ...) when it is a short slug, never its text."""
    err = _json(r).get("error")
    kind = err.get("type") if isinstance(err, dict) else err
    if isinstance(kind, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", kind):
        return scrub(kind)
    return None


def register_kind() -> None:
    """``draft.sanity``: "File this draft in Sanity", 72 hours, 3 a day."""
    _F = tickets.Field
    tickets.register(tickets.Kind(KIND, "File this draft in Sanity", {
        "draft_ref": _F("str", pattern=r"draft:[0-9]{1,12}", max_len=20, label="Draft"),
        "title": _F("str", max_len=200, label="Title"),
        "slug": _F("str", pattern=SLUG, max_len=96, label="Slug"),
        "category": _F("enum", CATEGORIES, label="Category")},
        expires_hours=None, per_day=3,
        meta={"verb": "Send to Sanity", "button": "Send to Sanity", "noun": "post",
              "done": "Sent to Sanity", "not_done": "not sent to Sanity",
              "question": "Send this post to Sanity?"}))
