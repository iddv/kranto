"""The toot cub: the weekly editor's pick becomes a short Mastodon post,
which you read and approve.

Rules it keeps: the post's text is the model's caption of the card's title and one-liner
(fenced: the card is data), cut by the cub's own code to the instance's character limit (500
when not connected; never more than the 500 a ``post.mastodon`` ticket carries); the cub never
names the account (Kranto fills it from the connection); one post per nominated card (``once``);
the model's words go into the text only, never into the kind, the draft ref or ``because``,
which names the card (``because.ideas``, 1.1.0) and its evidence; a pick the loop already
built is skipped (``built``).
"""
from __future__ import annotations

import json
import re

from bears_cub import Cub, NotConnected

cub = Cub()
TICKET_TEXT = 500                 # what a post.mastodon ticket's text holds at most
STATES = {"done": "posted", "dry": "practiced", "declined": "closed", "expired": "closed",
          "refused": "refused", "unknown": "unknown"}


def _limit(ctx) -> int:
    try:
        limit = int(ctx.broker("mastodon").call("instance.limits")["max_characters"])
    except NotConnected:
        limit = 500
    return min(limit, TICKET_TEXT)


TASK = ("Write one Mastodon post of at most {room} characters, spaces included, from an idea "
        "card: about what its fact means for the reader's world, not a tool to build. Open on "
        "the reader's interest (why they should care), with the person's angle when there is "
        "one, then the card's fact that backs it, in connected sentences. Every fact comes "
        "from the card. Answer JSON with text.")


UNREAD = "The model answered in a form Kranto could not read: try again."


class Unread(Exception):
    """The model answered, but in no form the cub reads (fix 1)."""


def _said(reply: dict) -> str:
    """The post's text: the schema's ``text``, else JSON written as text, else the prose
    itself with a ``Text:`` label or quotes taken off."""
    got = reply.get("structured")
    if isinstance(got, dict) and isinstance(got.get("text"), str):
        return got["text"]
    raw = str(reply.get("text") or "").strip()
    bare = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", raw)
    if bare.startswith("{"):
        try:
            parsed = json.loads(bare)
        except ValueError:
            return ""
        return str(parsed.get("text") or "") if isinstance(parsed, dict) else ""
    bare = re.sub(r"\A\**\s*(?:text|post)\s*\**\s*:\s*\**\s*", "", bare, flags=re.I)
    return bare.strip().strip('"“”')


def _fit(text: str, room: int) -> str:
    """At most ``room`` characters: the last full sentence that fits, else cut at a word with
    "…" (never mid-word, as the toot of old did)."""
    text = text.strip()
    if len(text) <= room:
        return text
    head = text[:room]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", head)]
    if ends and ends[-1] >= room // 3:
        return head[:ends[-1]].strip()
    return head[:room - 1].rsplit(" ", 1)[0].rstrip(",;:—- ") + "…"


def card_material(idea: dict, angle: str = "", hint: str = "") -> dict:
    return {"angle": angle or None, "title": idea["title"],
            "facts": idea.get("one_liner") or "", "hint": hint or None}


def _caption(ctx, idea: dict, link: bool, *, angle: str = "", hint: str = "") -> dict:
    """The caption, through Kranto's prose engine: composed with the floor,
    the Mastodon template and the person's voice, then checked against the instance's limit
    and rewritten only where it reads like AI. ``toot.tone`` was moved into the voice card;
    the form's one-off tone is a hint for this post."""
    limit = _limit(ctx)
    url = idea.get("url") if link else None
    room = min(limit - (len(url) + 2 if url else 0), 280)
    limits = {"max_chars": room, "unit": "characters", "links": 0}
    composed = ctx.prose.compose(card_material(idea, angle, hint), site="mastodon",
                                 kind="short", task=TASK.format(room=room), limits=limits)
    reply = ctx.model.complete(
        purpose="toot_caption", tier="reason", max_tokens=200,
        schema={"type": "object", "properties": {"text": {"type": "string"}},
                "required": ["text"]},
        messages=composed["messages"])
    text = " ".join(_said(reply).split())
    if not text and str(reply.get("text") or "").strip():
        raise Unread(str(reply.get("text"))[:200])
    got = ctx.prose.check(text, site="mastodon", kind="short", limits=limits, take=angle)
    rounds = 0
    if any(f.get("scope", "span") == "span" or f.get("rule") == "site.length"
           for f in got.get("flags") or []):
        fixed = ctx.prose.revise(text, got["flags"], purpose="toot_caption", tier="reason",
                                 site="mastodon", kind="short", limits=limits, take=angle)
        text, rounds = " ".join(str(fixed.get("text") or text).split()), fixed.get("rounds", 0)
        got = {**got, **{k: fixed[k] for k in ("flags", "score", "verdict") if k in fixed}}
    text = _fit(text, room)
    line = str(composed.get("disclosure") or "")
    if line and len(text) + len(line) + 2 <= room:
        text += f"\n\n{line}"
    if url:
        text += f"\n\n{url}"
    return {"text": text, "prose": {"score": got.get("score"), "verdict": got.get("verdict"),
                                    "rounds": rounds, "angle": angle or None,
                                    "left": [f.get("rule") for f in got.get("flags") or []]}}


def _file(ctx, idea: dict, caption: dict, trigger: str) -> dict:
    text = caption["text"]
    visibility, language = ctx.settings["toot.visibility"], ctx.settings["toot.language"]
    draft = ctx.broker("mastodon").call("statuses.draft", text=text, visibility=visibility,
                                        language=language)
    ref = draft["draft_ref"]
    evidence = [int(o) for o in idea.get("evidence_ids") or []][:20]
    t = ctx.ticket("post.mastodon", {"draft_ref": ref, "text": text, "visibility": visibility,
                                     "language": language},
                   because={"ideas": [int(idea["id"])], "observations": evidence},
                   subject={"kind": "toot_post", "id": ref})
    row = {"id": ref, "text": text, "idea_id": idea["id"], "idea_title": idea["title"],
           "chars": len(text), "visibility": visibility, "state": "waiting",
           "cites": [{"kind": "idea", "id": idea["id"], "label": f"idea {idea['id']}"}]
           + [{"kind": "obs", "id": o, "label": f"obs {o}"} for o in evidence[:6]],
           "ticket": t.ticket_id, "date": ctx.today(), "trigger": trigger,
           "prose": caption.get("prose") or {}}
    ctx.kv.put(f"post:{ref}", row)
    ctx.events.publish("toot.drafted", {"draft_ref": ref, "idea_id": idea["id"],
                                        "ticket_id": t.ticket_id},
                       subject={"kind": "toot_post", "id": ref}, dedupe=f"drafted:{ref}")
    return row


def _hint(fields) -> str:
    """The form's tone for this one post (plain is the voice card's own, so no hint)."""
    tone = fields.get("tone")
    tone = tone[0] if isinstance(tone, list) and tone else tone
    return f"a {tone} tone" if tone and tone != "plain" else ""


@cub.job("draft_pick")
def draft_pick(ctx):
    """Daily: the newest card the weekly editor nominated, once. A card counts as posted only
    once its ticket is filed, so a run the model failed is tried again on its next day. A card
    the loop already built (Kranto says ``built``) is not a pick to announce: it is skipped."""
    picks = ctx.read.ideas(editor_class="nominee", limit=5)["ideas"]
    for idea in picks:
        done = f"picked:{idea['id']}"
        if ctx.kv.get(done) is not None or idea.get("built"):
            continue
        row = _file(ctx, idea, _caption(ctx, idea, ctx.settings["toot.link"]), "schedule")
        ctx.kv.put(done, row["id"])
        return {"summary": {"idea": idea["id"], "ticket": row["ticket"]},
                "line": f"drafted a post for idea {idea['id']}: it waits for your approval"}
    return {"status": "skipped", "line": "no new editor's pick"}


@cub.action("draft_card")
def draft_card(ctx, fields):
    idea = ctx.read.idea(int(fields["idea"]))
    # the angle (Write a post's angle step); ``take`` is its old name
    angle = " ".join(str(fields.get("angle") or fields.get("take") or "").split())[:600]
    try:
        caption = _caption(ctx, idea, bool(fields.get("link")), angle=angle, hint=_hint(fields))
    except Unread:
        return {"ok": False, "say": UNREAD}
    _file(ctx, idea, caption, "owner")
    plain = "" if angle else (" It has no angle, so it only says what the card says: give it "
                              "one sentence of yours and write it again.")
    return {"say": f"Post drafted: it waits for your approval (Post toot).{plain}",
            "refresh": ["posts", "rows", "count"]}


@cub.action("redraft")
def redraft(ctx, fields):
    ref = fields["post_id"]               # the subject's id, given as <subject without toot_>_id
    row = ctx.kv.get(f"post:{ref}")
    if row is None:
        return {"ok": False, "say": "That post is not one of this cub's."}
    idea = ctx.read.idea(int(row["idea_id"]))
    try:                                # written first: an unreadable answer withdraws nothing
        caption = _caption(ctx, idea, ctx.settings["toot.link"], hint=_hint(fields))
    except Unread:
        return {"ok": False, "say": UNREAD}
    ctx.withdraw({"kind": "toot_post", "id": ref}, note="redrafted")
    _file(ctx, idea, caption, "owner")
    row["state"] = "closed"
    ctx.kv.put(f"post:{ref}", row)
    return {"say": "Redrafted: the new post waits for your approval.",
            "refresh": ["posts", "rows", "count"]}


@cub.event("ticket.resolved")
def on_resolved(ctx, events):
    for ev in events:
        p = ev["payload"]
        if p.get("cub") != ctx.cub_id:
            continue
        t = ctx.tickets.get(p["ticket_id"])
        ref = (t.get("fields") or {}).get("draft_ref")
        if not ref:
            continue
        row = ctx.kv.get(f"post:{ref}")
        if row is None:
            continue
        row["state"] = STATES.get(p["state"], p["state"])
        row["note"] = t.get("note")
        ctx.kv.put(f"post:{ref}", row)
    return len(events)


def _posts(ctx) -> list[dict]:
    """Our posts, newest first. One still "waiting" is read again from the core (1.3.0): its
    answer may have come while this cub was not handling it."""
    rows = [v for _, v in ctx.kv.items("post:") if isinstance(v, dict)]
    for r in rows:
        if r.get("state") == "dry run":            # an earlier version's word for it
            r["state"] = "practiced"
        if r.get("state") == "waiting" and r.get("ticket"):
            st = ctx.tickets.get(r["ticket"]).get("state")
            if st and st != "needs_confirm":
                r["state"] = STATES.get(st, st)
    return sorted(rows, key=lambda r: (r["date"], r["ticket"]), reverse=True)


@cub.read("posts")
def posts(ctx, params):
    rows = _posts(ctx)
    return {"waiting": [r for r in rows if r["state"] == "waiting"],
            "posted": [r for r in rows if r["state"] == "posted"],
            "practiced": [r for r in rows if r["state"] == "practiced"],
            "closed": [r for r in rows if r["state"] in ("closed", "refused", "unknown")]}


@cub.read("rows")
def rows(ctx, params):
    return {"rows": [{"id": r["id"], "title": r["text"][:80],
                      "meta": f"{r['chars']} characters · {r['idea_title'][:40]}",
                      "at": r["date"], "ticket": r["ticket"]}
                     for r in _posts(ctx) if r["state"] == "waiting"]}


@cub.read("count")
def count(ctx, params):
    return {"count": sum(1 for r in _posts(ctx) if r["state"] == "waiting")}


@cub.read("idea_choices")
def idea_choices(ctx, params):
    return {"choices": [{"value": str(i["id"]), "word": i["title"][:60]}
                        for i in ctx.read.ideas(limit=20)["ideas"]]}
