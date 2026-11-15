"""Kranto's blog writer (the owner's examplecom cub made general: a site name and a tone).

Four drafters, each one the owner asks for (Write a post, the console's ``post.write``, or the
cub's own forms; no schedule):

- **about an idea card** (``draft_card``): one model call over the card's title, line, thesis
  and insight and its sources' claims (fenced: they are data). The sources list under the post is
  built by this code from the card's own sources (``cards.get``), so every link is the card's;
- **about a news item** (``draft_item``): one model call over the item and its sources; the
  links again are the item's own;
- **this week's news** (``draft_week``): every item verbatim from the week's News briefs, an
  opening from one model call over the headlines only;
- **your own markdown** (``draft_markdown``): no model call; kept as written.

Each ends in a draft held by Kranto (``documents.draft``: nothing reaches Sanity before your
approval) and one ``draft.sanity`` ask that waits until you answer it. On Post it is a blog post
you can copy or download with no account; with a Sanity account, approving it files the draft
there, never published. The model's words go into the post's text only, never into the kind,
the draft ref, the Sanity id or ``because``, which names the card, the brief or the briefs.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC

from bears_cub import Cub

cub = Cub()
KIND = "draft.sanity"
STATES = {"done": "filed", "dry": "practiced", "declined": "closed", "expired": "closed",
          "refused": "refused", "unknown": "unknown"}
MAX_ITEMS = 12
EXCERPT = 280


# -- small helpers ------------------------------------------------------------------------------


def _one(v) -> str:
    """A form's value: a choice comes as a list of strings, the command line's as a string."""
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v if v is not None else "").strip()


def _int(v) -> int | None:
    try:
        return int(_one(v))
    except ValueError:
        return None


def slugify(text: str, limit: int = 80) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return slug[:limit].strip("-") or "post"


def _cut(text, n: int) -> str:
    """At most ``n`` characters, cut at a word."""
    text = " ".join(str(text or "").split())
    if len(text) <= n:
        return text
    return text[:n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _since(ctx, days: int) -> str:
    return ctx.now_minus(days=days).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _untitled(body: str) -> str:
    """A model's body without a ``# Title`` line of its own (the post's title is separate)."""
    return re.sub(r"\A\s*#\s[^\n]*\n+", "", str(body or "").strip()).strip()


def _write(ctx, *, task: str, material: dict, fields: tuple[str, ...], max_tokens: int,
           kind: str = "long") -> dict:
    """The drafter's one reason-tier call (``blog_post``), through Kranto's prose engine: the
    floor, plain words, the blog's template, the person's voice card and their closest samples
    go in with the task (``blog.tone`` was moved into the voice card)."""
    site = _cut(ctx.settings["blog.site"], 80) or "my blog"
    props = {k: {"type": "string"} for k in fields}
    composed = ctx.prose.compose(
        material, site="blog", kind=kind,
        task=f"{task} You write for {site}. Answer JSON with {', '.join(fields)}.")
    reply = ctx.model.complete(
        purpose="blog_post", tier="reason", max_tokens=max_tokens,
        schema={"type": "object", "properties": props, "required": list(props)},
        messages=composed["messages"])
    out = _answer(reply, fields)
    # the person's disclosure line for the blog (off unless they set one: P-6)
    out["_disclosure"] = str(composed.get("disclosure") or "")[:200]
    return out


UNREAD = "The model answered in a form Kranto could not read: try again."


class Unread(Exception):
    """The model answered, but in no form the writer reads (fix 1)."""


def _answer(reply: dict, fields: tuple[str, ...] = ("title", "excerpt", "body")) -> dict:
    out = reply.get("structured")
    if isinstance(out, dict):
        return dict(out)
    # a provider that answers the schema as text: its JSON, read once, a code fence around it
    # allowed; else the prose a model writes when no schema held it ("Title: … Excerpt: …
    # then the body", fix 1)
    raw = str(reply.get("text") or "")
    text = re.sub(r"\A\s*```(?:json)?\s*|\s*```\s*\Z", "", raw)
    try:
        got = json.loads(text)
    except ValueError:
        got = _from_prose(raw, fields)
    if not isinstance(got, dict):
        got = {}
    if raw.strip() and not any(str(got.get(k) or "").strip() for k in ("body", "intro")):
        raise Unread(raw[:200])
    return got


def _from_prose(text: str, fields: tuple[str, ...]) -> dict:
    """``Title:``, ``Excerpt:`` (or ``Intro:``) lines and the body after them, labels in bold
    or not; a ``# Title`` heading counts as the title."""
    out: dict[str, str] = {}
    rest = []
    for line in str(text or "").strip().splitlines():
        m = re.match(r"\s*\**\s*(title|excerpt|intro|body)\s*\**\s*:\s*\**\s*(.*)$", line, re.I)
        if m and m.group(1).lower() != "body" and m.group(1).lower() not in out:
            out[m.group(1).lower()] = m.group(2).strip().strip("*").strip()
            continue
        if m and m.group(1).lower() == "body":
            line = m.group(2)
        if "title" not in out and not rest and re.match(r"\s*#\s+\S", line):
            out["title"] = re.sub(r"^\s*#\s+", "", line).strip()
            continue
        rest.append(line)
    body = "\n".join(rest).strip()
    if "intro" in fields and "intro" not in out:
        out["intro"] = body
    elif body:
        out["body"] = body
    return out


def _disclosed(body: str, got: dict) -> str:
    line = got.get("_disclosure") or ""
    return f"{body}\n\n*{line}*" if line else body


def _polish(ctx, text: str, angle: str, kind: str = "long") -> tuple[str, dict]:
    """The engine's check, then one rewrite of only the flagged spans (at most two rounds);
    what remains is kept and said on the row (``prose``)."""
    if not text:
        return text, {}
    got = ctx.prose.check(text, site="blog", kind=kind, take=angle)
    rounds = 0
    if any(f.get("scope", "span") == "span" or f.get("rule") == "site.length"
           for f in got.get("flags") or []):
        fixed = ctx.prose.revise(text, got["flags"], purpose="blog_post", tier="reason",
                                 site="blog", kind=kind, take=angle)
        text, rounds = fixed.get("text") or text, int(fixed.get("rounds") or 0)
        got = {**got, **{k: fixed[k] for k in ("flags", "score", "verdict") if k in fixed}}
    return text, {"score": got.get("score"), "verdict": got.get("verdict"), "rounds": rounds,
                  "left": [f.get("rule") for f in got.get("flags") or []],
                  "angle": angle or None}


def _angle(fields) -> str:
    """The person's angle for this post (Write a post's angle step: their sentence or a
    proposal they picked), if any; ``take`` is its old name (a redraft of a 1.1 post)."""
    raw = fields.get("angle") or fields.get("take")
    return _cut(raw, 600) if raw else ""


NO_ANGLE = ("It has no angle, so it is a plain summary: give it one sentence of yours and "
            "write it again for a post that says something.")


def _sources(items: list[dict]) -> str:
    """The post's sources, from the card's or the item's own links (never the model's)."""
    rows = [f"{i}. [{s.get('label') or s.get('source') or s['url']}]({s['url']})"
            for i, s in enumerate(items, 1)]
    return ("\n\n## Sources\n\n" + "\n".join(rows)) if rows else ""


# -- filing -------------------------------------------------------------------------------------


def _file(ctx, post: dict, trigger: str) -> dict:
    """The draft in Kranto (``documents.draft``), then the ask that names it, then the row."""
    tags = ", ".join(t for t in [*(x.strip() for x in str(ctx.settings["blog.tags"] or "")
                                   .split(",")), *post.get("tags", [])] if t)[:600]
    args = {"doc": post["doc"][:80].strip("-"), "title": post["title"][:200],
            "slug": post["slug"], "body": post["body"], "category": "dispatch",
            "origin": post["origin"]}
    if post.get("excerpt"):
        args["excerpt"] = post["excerpt"]
    if tags:
        args["tags"] = tags
    if post.get("cites"):
        args["cites"] = ", ".join(c["label"] for c in post["cites"])[:400]
    draft = ctx.broker("sanity").call("documents.draft", **args)
    ref = draft["draft_ref"]
    t = ctx.ticket(KIND, {"draft_ref": ref, "title": args["title"], "slug": args["slug"],
                          "category": args["category"]},
                   because=post.get("because") or {}, subject={"kind": "blog_post", "id": ref})
    row = {"id": ref, "title": args["title"], "slug": args["slug"], "doc": args["doc"],
           "origin": post["origin"], "excerpt": post.get("excerpt") or "",
           "words": len(post["body"].split()), "cites": post.get("cites") or [],
           "body_markdown": post["body"], "inputs": post.get("inputs") or {},
           "prose": post.get("prose") or {},
           "ticket": t.ticket_id, "date": ctx.today(), "state": "waiting", "trigger": trigger}
    ctx.kv.put(f"post:{ref}", row)
    ctx.events.publish("blog.drafted", {"draft_ref": ref, "origin": post["origin"],
                                        "ticket_id": t.ticket_id},
                       subject={"kind": "blog_post", "id": ref}, dedupe=f"drafted:{ref}")
    return row


def _said(row: dict) -> dict:
    plain = "" if (row.get("inputs") or {}).get("angle") or row.get("origin") == "markdown" \
        else f" {NO_ANGLE}"
    return {"say": f"Drafted “{row['title']}”: it waits on Post. Nothing is sent until you "
                   f"choose Send.{plain}", "draft_ref": row["id"],
            "refresh": ["posts", "rows", "count"]}


# -- about an idea card -------------------------------------------------------------------------


CARD_TASK = ("You write a blog post of 120 to 200 words in markdown (no title line) about an "
             "idea card, built on the person's angle: its first sentence makes the angle's "
             "claim, prediction or question, and the card and its sources back it. No fixed "
             "sections. Cite a source as [n] using only the numbers given; every fact comes "
             "from the card and its sources. A title under 80 characters that says the claim, "
             "and a one-sentence excerpt.")
ITEM_TASK = ("You write a blog post of 120 to 200 words in markdown (no title line) about one "
             "news item, built on the person's angle: its first sentence makes the angle's "
             "claim, prediction or question, and the item's facts back it. No fixed sections. "
             "Every fact comes from the item. A title under 80 characters that says the claim, "
             "and a one-sentence excerpt.")
WEEK_TASK = ("You write intro, a three-sentence opening for a weekly post, from its items. "
             "Nothing the items do not say.")


def card_material(card: dict, srcs: list[dict], angle: str = "") -> dict:
    about = "\n".join(x for x in (card.get("title"), card.get("one_liner"), card.get("thesis"),
                                  card.get("insight"), card.get("why")) if x)
    facts = "\n".join(f"[{s['n']}] {s.get('source') or ''}: {s.get('claim') or ''}"
                      for s in srcs) or "(no sources)"
    return {"angle": angle or None, "title": about, "facts": facts}


def card_post(ctx, card: dict, angle: str = "") -> dict | None:
    srcs = [s for s in card.get("sources") or [] if s.get("url")][:8]
    got = _write(ctx, fields=("title", "excerpt", "body"), max_tokens=1100, task=CARD_TASK,
                 material=card_material(card, srcs, angle))
    body = _untitled(got.get("body"))
    if not body:
        return None
    body, prose = _polish(ctx, body, angle)
    body = re.sub(r"\[(\d{1,2})\](?!\()", lambda m: f"[{m.group(1)}]" if any(
        s["n"] == int(m.group(1)) for s in srcs) else "", body)
    title = _cut(got.get("title") or card.get("title") or "An idea", 120)
    return {"doc": f"card-{card['id']}-{slugify(title, 50)}", "slug": slugify(title, 96),
            "title": title, "body": _disclosed(body, got) + _sources(srcs), "origin": "card",
            "prose": prose,
            "excerpt": _cut(got.get("excerpt") or card.get("one_liner"), EXCERPT),
            "tags": [card["topic"]["name"]] if (card.get("topic") or {}).get("name") else [],
            "cites": [{"kind": "idea", "id": card["id"], "label": f"idea {card['id']}"}],
            "because": {"ideas": [int(card["id"])]}}


@cub.action("draft_card")
def draft_card(ctx, fields):
    n = _int(fields.get("card"))
    if n is None:
        return {"ok": False, "say": "Name the idea card by its number."}
    card = ctx.read.card(n)
    try:
        post = card_post(ctx, card, _angle(fields))
    except Unread:
        return {"ok": False, "say": UNREAD}
    if post is None:
        return {"ok": False, "say": "The model wrote nothing: try again."}
    post["inputs"] = {"action": "draft_card", "card": n, "angle": _angle(fields) or None}
    return _said(_file(ctx, post, "owner"))


# -- about a news item --------------------------------------------------------------------------


def item_material(it: dict, angle: str = "") -> dict:
    return {"angle": angle or None, "title": it.get("headline") or "",
            "facts": f"{it.get('body') or ''}\n{it.get('why') or ''}".strip()}


def item_post(ctx, brief: dict, n: int, angle: str = "") -> dict | None:
    items = brief.get("items") or []
    if not 1 <= n <= len(items):
        return None
    it = items[n - 1]
    srcs = [s for s in it.get("sources") or [] if s.get("url")][:8]
    got = _write(ctx, fields=("title", "excerpt", "body"), max_tokens=900, task=ITEM_TASK,
                 material=item_material(it, angle))
    body = _untitled(got.get("body"))
    if not body:
        return None
    body, prose = _polish(ctx, body, angle)
    title = _cut(got.get("title") or it.get("headline") or "A news item", 120)
    return {"doc": f"brief-{brief['id']}-{n}", "slug": slugify(title, 96), "title": title,
            "body": _disclosed(body, got) + _sources(srcs), "origin": "brief", "prose": prose,
            "excerpt": _cut(got.get("excerpt") or it.get("headline"), EXCERPT),
            "cites": [{"kind": "brief", "id": brief["id"], "label": f"brief {brief['id']}"}],
            "because": {"briefs": [int(brief["id"])]}}


@cub.action("draft_item")
def draft_item(ctx, fields):
    b, n = _int(fields.get("brief")), _int(fields.get("item"))
    if b is None or n is None:
        return {"ok": False, "say": "Name the brief and its item."}
    brief = ctx.read.brief(b)
    if not 1 <= n <= len(brief.get("items") or []):
        return {"ok": False, "say": f"Brief {b} has no item {n}."}
    try:
        post = item_post(ctx, brief, n, _angle(fields))
    except Unread:
        return {"ok": False, "say": UNREAD}
    if post is None:
        return {"ok": False, "say": "The model wrote nothing: try again."}
    post["inputs"] = {"action": "draft_item", "brief": b, "item": n,
                      "angle": _angle(fields) or None}
    return _said(_file(ctx, post, "owner"))


# -- this week's news ---------------------------------------------------------------------------


def _item(it: dict) -> str:
    when = f" ({it['date']})" if it.get("date") else ""
    links = " · ".join(f"[{s.get('label') or 'source'}]({s['url']})" for s in it["sources"])
    why = f"\n\n*Why it matters:* {it['why']}" if it["why"] else ""
    return f"## {it['headline']}{when}\n\n{it['body']}{why}" + (f"\n\n{links}" if links else "")


def week_post(ctx, topic: dict | None, angle: str = "") -> dict | None:
    topics = [topic] if topic else ctx.read.topics()["topics"]
    since = _since(ctx, ctx.settings["blog.week_days"])
    items, ids = [], []
    briefs = [b for t in topics for b in ctx.read.briefs(topic_id=int(t["id"]), since=since,
                                                         limit=10)["briefs"] if b.get("items")]
    for b in sorted(briefs, key=lambda b: b["id"], reverse=True):
        for it in ctx.read.brief(b["id"]).get("items") or []:
            if len(items) >= MAX_ITEMS:
                break
            items.append({"headline": it["headline"], "body": it["body"],
                          "why": it.get("why") or "", "date": it.get("date"),
                          "sources": [s for s in it.get("sources") or [] if s.get("url")]})
            if b["id"] not in ids:
                ids.append(b["id"])
    if not items:
        return None
    got = _write(ctx, fields=("intro",), max_tokens=300, task=WEEK_TASK, kind="intro",
                 material={"angle": angle or None, "title": "the week's news",
                           "facts": "\n".join(f"- {it['headline']}: {it['body']}"
                                              for it in items)})
    intro, prose = _polish(ctx, " ".join(str(got.get("intro") or "").split()), angle,
                           "intro")
    day = ctx.now_minus(days=0).astimezone(UTC)
    year, week, _ = day.isocalendar()
    name = topic["name"] if topic else "The week"
    title = f"{name}: the week to {day.strftime('%-d %B %Y')}"[:200]
    return {"doc": f"week-{'t' + str(topic['id']) if topic else 'all'}-{year}-w{week:02d}",
            "slug": slugify(f"{name} week {week} {year}", 96), "title": title,
            "body": _disclosed((intro + "\n\n" if intro else "")
                               + "\n\n".join(_item(it) for it in items), got),
            "origin": "brief", "excerpt": _cut(intro, EXCERPT), "prose": prose,
            "tags": [topic["name"]] if topic else [],
            "cites": [{"kind": "brief", "id": i, "label": f"brief {i}"} for i in ids],
            "because": {"briefs": ids}}


@cub.action("draft_week")
def draft_week(ctx, fields):
    want = _one(fields.get("topic"))
    topic = next((t for t in ctx.read.topics()["topics"] if str(t["id"]) == want), None) \
        if want else None
    if want and topic is None:
        return {"ok": False, "say": "Choose one of your topics, or none for every topic."}
    try:
        post = week_post(ctx, topic, _angle(fields))
    except Unread:
        return {"ok": False, "say": UNREAD}
    if post is None:
        return {"ok": False, "say": f"No brief of the last {ctx.settings['blog.week_days']} "
                                    "days has items."}
    post["inputs"] = {"action": "draft_week", "topic": want, "angle": _angle(fields) or None}
    return _said(_file(ctx, post, "owner"))


# -- your own markdown --------------------------------------------------------------------------


@cub.action("draft_markdown")
def draft_markdown(ctx, fields):
    text = str(fields.get("markdown") or "").replace("\r\n", "\n").strip()
    m = re.match(r"#\s+(.+)\n+", text)
    if not m or not text[m.end():].strip():
        return {"ok": False, "say": "The markdown needs a # Title line and a body."}
    title = m.group(1).strip()
    slug = slugify(title, 96)
    post = {"doc": f"post-{slug}", "slug": slug, "title": title, "body": text[m.end():].strip(),
            "origin": "markdown", "cites": [], "because": {"labels": ["your markdown"]},
            "inputs": {"action": "draft_markdown"}}
    return _said(_file(ctx, post, "owner"))


# -- redraft and the core's answers -------------------------------------------------------------


@cub.action("redraft")
def redraft(ctx, fields):
    ref = fields["post_id"]               # the subject's id, given as <subject without blog_>_id
    row = ctx.kv.get(f"post:{ref}")
    if row is None:
        return {"ok": False, "say": "That post is not one of this cub's."}
    inputs = dict(row.get("inputs") or {})
    action = inputs.pop("action", None)
    drafters = {"draft_card": draft_card, "draft_item": draft_item, "draft_week": draft_week}
    if action not in drafters:
        return {"ok": False, "say": "Your own markdown is kept as you wrote it: edit it and keep "
                                    "it again."}
    ctx.withdraw({"kind": "blog_post", "id": ref}, note="redrafted")
    out = drafters[action](ctx, inputs)
    if out.get("ok", True):
        row["state"] = "closed"
        ctx.kv.put(f"post:{ref}", row)
    return out


@cub.event("ticket.resolved")
def on_resolved(ctx, events):
    """The core's word on our asks: filed, practiced, declined, replaced, refused, unknown."""
    for ev in events:
        p = ev["payload"]
        if p.get("cub") != ctx.cub_id or p.get("kind") != KIND:
            continue
        t = ctx.tickets.get(p["ticket_id"])
        row = ctx.kv.get(f"post:{t['fields']['draft_ref']}")
        if row is None:
            continue
        row["state"] = STATES.get(p["state"], p["state"])
        row["note"] = t.get("note")
        ctx.kv.put(f"post:{t['fields']['draft_ref']}", row)
    return len(events)


# -- the page's reads ---------------------------------------------------------------------------


def _posts(ctx) -> list[dict]:
    rows = [v for _, v in ctx.kv.items("post:") if isinstance(v, dict)]
    for r in rows:
        if r.get("state") == "waiting" and r.get("ticket"):
            st = ctx.tickets.get(r["ticket"]).get("state")
            if st and st != "needs_confirm":
                r["state"] = STATES.get(st, st)
    return sorted(rows, key=lambda r: (r["date"], r["ticket"]), reverse=True)


def _view(r: dict) -> dict:
    return {k: v for k, v in r.items() if k != "inputs"}


@cub.read("posts")
def posts(ctx, params):
    rows = [_view(r) for r in _posts(ctx)]
    return {"waiting": [r for r in rows if r["state"] == "waiting"],
            "filed": [r for r in rows if r["state"] == "filed"],
            "closed": [r for r in rows if r["state"] not in ("waiting", "filed")]}


@cub.read("rows")
def rows(ctx, params):
    return {"rows": [{"id": r["id"], "title": r["title"],
                      "meta": f"{r['words']} words · from {r['origin']}",
                      "at": r["date"], "ticket": r["ticket"]}
                     for r in _posts(ctx) if r["state"] == "waiting"]}


@cub.read("count")
def count(ctx, params):
    return {"count": sum(1 for r in _posts(ctx) if r["state"] == "waiting")}


@cub.read("topic_choices")
def topic_choices(ctx, params):
    return {"choices": [{"value": str(t["id"]), "word": t["name"][:60]}
                        for t in ctx.read.topics()["topics"]]}
