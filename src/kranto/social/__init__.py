"""Short posts for the sites people use: Kranto's own writer (Write a post › Short posts).

**Site first.** The person's own site comes first: with their blog connected (Sanity with the
posts' address), Write a post writes the blog post (the blog writer, step one), and every short
post is written **from that post's own words and links to its address**. With no blog
connected, a short post is about the card or the news item and links to its best source.

For each site the person ticked (``core.sites.choices``) the writer makes one variant, in the
site's own form, through the prose engine every writer uses:

1. ``prose.compose``: the person's voice, the floor, the site's template, the site's limits and
   playbook (``core.sites``), the angle leading;
2. one model call (the metered client, under the writer's own model when one is set:
   ``writer_model("social")``; no default is chosen);
3. Kranto's code keeps only what the site can carry: addresses that are not the post's link are
   taken off, tags past the site's count, then the site's limit counted the site's way;
4. ``prose.check``; a flag on a span (or the length) goes to ``prose.revise``, which rewrites
   only the flagged words; what is still flagged is stored with the draft and shown;
5. the link (and, when the person switched it on for the site, the disclosure line) is added by
   code, never by the model.

Each variant is a ``cub_drafts`` row of the filer ``social`` (service: the site) and one ask: Open
(``post.open``) unless the person switched the site to Post directly, then the site's own send.
Nothing here sends: every send is the person's press in the confirm dialog.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from ..core import sites as sites_mod
from ..core.cubs.brokers.base import connection_of, new_draft
from ..core.cubs.brokers.social import FILER

PURPOSE = "post_social"
PROMPT_VERSION = "post-social@1"
MAX_PARTS = 3

TASK = (
    "Write a {name} post{about}. {shape} Open on the angle: a claim, a prediction or a "
    "question that makes a reader who follows the topic want the next sentence. Then the one "
    "or two facts that back it, in connected sentences. Trust the reader: no explaining what "
    "they know, no summary of what you just said, no announcing what comes (\"Here's\", "
    "\"Let's dive in\", \"A thread\", \"1/\"). Short. Every fact comes from the material. Do "
    "not write any web address: Kranto adds the link itself. Answer JSON: "
    "{{\"parts\": [\"...\"]}}, one string a post.")
ONE = "One post of at most {room} characters, spaces included."
THREAD = ("One post of at most {room} characters, or, only when the material has three or more "
          "points worth a reader's time, a thread of two or three posts, each at most {room} "
          "characters, the first standing alone.")
ABOUT_POST = " about the person's own blog post below (its words are in the sources fence), " \
             "in {name}'s own form, so that a reader wants to open the post"
ABOUT_CARD = ""
SCHEMA = {"type": "object",
          "properties": {"parts": {"type": "array", "items": {"type": "string"},
                                   "minItems": 1, "maxItems": MAX_PARTS}},
          "required": ["parts"]}


class SocialError(ValueError):
    def __init__(self, words: str, code: int = 400) -> None:
        super().__init__(words)
        self.words, self.code = words, code


@dataclass
class Material:
    """What every variant of one write is written from: ``title`` and ``facts`` for the model,
    ``link`` the address the posts point to, ``link_to`` ``post`` (the person's own) or
    ``source``, ``card`` the link card's words, ``because`` what the asks rest on."""

    title: str
    facts: str
    link: str | None = None
    link_to: str = "source"
    card: dict[str, Any] | None = None
    because: dict[str, Any] = field(default_factory=dict)
    blog_draft: int | None = None


def blog_target(store) -> dict[str, Any] | None:
    """The person's own site, when it can be the post's home: the Sanity connection, connected,
    with the posts' address set (Settings › Posting, Sanity). None otherwise."""
    from ..connections.sanity import site
    conn = connection_of(store, "sanity")
    if conn is None or conn["state"] != "connected":
        return None
    base = site(store).get("post_url")
    return {"post_url": base, "account": conn["account"]} if base else None


def from_blog(store, draft: dict[str, Any], because: dict[str, Any]) -> Material:
    """The blog post Kranto just drafted, as the material of its short posts: its own words and
    the address it will have (``post_url``/``slug``)."""
    from ..core.cubs.brokers.sanity import post_link
    c = draft["content"]
    title = str(c.get("title") or "").strip()
    excerpt = str(c.get("excerpt") or "").strip()
    body = str(c.get("body") or "").strip()
    slug = c.get("slug")
    link = post_link(store, slug) if isinstance(slug, str) and slug else None
    facts = "\n\n".join(x for x in (f"Title: {title}", f"Teaser: {excerpt}" if excerpt else "",
                                    body[:6000]) if x)
    return Material(title=title, facts=facts, link=link, link_to="post",
                    card={"url": link, "title": title, "description": excerpt} if link else None,
                    because=because, blog_draft=int(draft["id"]))


def from_sources(material: dict[str, str], best: str | None, because: dict[str, Any],
                 card_title: str = "") -> Material:
    """A card or a news item as the material, linking to its best source."""
    return Material(title=material["title"], facts=material["facts"], link=best,
                    link_to="source",
                    card={"url": best, "title": card_title[:300], "description": ""}
                    if best else None, because=because)


def _parts(reply: dict) -> list[str]:
    got = reply.get("structured")
    if not isinstance(got, dict):
        raw = re.sub(r"\A\s*```(?:json)?\s*|\s*```\s*\Z", "", str(reply.get("text") or ""))
        try:
            got = json.loads(raw)
        except ValueError:
            got = {"parts": [raw]} if raw.strip() and not raw.lstrip().startswith("{") else None
    if not isinstance(got, dict):
        return []
    raw_parts = got.get("parts")
    if isinstance(raw_parts, str):
        raw_parts = [raw_parts]
    if not isinstance(raw_parts, list) and isinstance(got.get("text"), str):
        raw_parts = [got["text"]]
    if not isinstance(raw_parts, list):
        return []
    out = [" ".join(str(p).split()) if "\n" not in str(p) else str(p).strip()
           for p in raw_parts if isinstance(p, str) and p.strip()]
    return out[:MAX_PARTS]


def _span_flags(flags: list[dict]) -> bool:
    return any(f.get("scope", "span") == "span" or f.get("rule") == "site.length"
               for f in flags or [])


def disclosure_line(profile, site_id: str) -> str:
    """The disclosure line for a site: the person's own words for it in the prose profile,
    else "Drafted with <product>." (shown only where they switched it on: off by default)."""
    from .. import product
    own = (profile.disclosure or {}).get(site_id)
    return own.strip() if isinstance(own, str) and own.strip() else f"Drafted with {product.NAME}."


def write_variant(rt, choice: sites_mod.Choice, m: Material, angle: str, *, complete,
                  profile, language: str = "en") -> dict[str, Any]:
    """One site's variant: ``{site, parts, extras, prose}`` (the model's words cleaned, checked,
    revised and fitted; the link and the disclosure added by code)."""
    from .. import prose
    site = choice.site
    thread_ok = choice.direct and site.thread
    first_room = sites_mod.room(site, m.link)
    if site.id == "mastodon" and choice.direct:
        # post.mastodon's ask holds the text as written (500 characters), the link in full
        first_room = min(first_room, 500 - len(f"\n\n{m.link}" if m.link else ""))
    disclose = disclosure_line(profile, site.id) if choice.disclose else ""
    limits = {"max_chars": first_room, "unit": site.unit, "links": 0,
              "hashtags": site.hashtags}
    shape = (THREAD if thread_ok else ONE).format(room=first_room)
    about = ABOUT_POST.format(name=site.name) if m.link_to == "post" else ABOUT_CARD
    task = TASK.format(name=site.name, about=about, shape=shape)
    material = {"angle": angle or None, "title": m.title, "facts": m.facts,
                "format": "Answer with the JSON only."}
    messages = prose.compose(material, site.id, profile, task=task, kind="short",
                             language=language, limits=limits, features=site.playbook,
                             embedder=getattr(rt, "embedder", None))
    parts = _parts(complete(messages, SCHEMA))
    if not parts:
        raise SocialError(f"the model's answer for {site.name} held no post", 502)
    if not thread_ok:
        parts = parts[:1]
    allowed = {u for u in (m.link,) if u}
    out_parts: list[str] = []
    removed: list[str] = []
    left: list[str] = []
    rounds = 0
    score = verdict = None
    for i, text in enumerate(parts):
        room_i = first_room if i == 0 else site.limit
        lim_i = {**limits, "max_chars": room_i}
        text, gone = sites_mod.clean(site, text, allowed)
        removed += gone
        got = prose.check(text, site.id, profile, kind="short", limits=lim_i, take=angle)
        if _span_flags(got.get("flags") or []):
            fixed = prose.revise(text, got["flags"], profile, complete=complete, site=site.id,
                                 kind="short", limits=lim_i, take=angle)
            rounds += int(fixed.get("rounds") or 0)
            text = str(fixed.get("text") or text).strip()
            text, gone = sites_mod.clean(site, text, allowed)
            removed += gone
            got = prose.check(text, site.id, profile, kind="short", limits=lim_i, take=angle)
        text, cut = sites_mod.fit(site, text, room_i)
        if cut:
            removed.append("the end of a sentence past the limit")
            # what is stored is the check of the words kept, not of the words before the cut
            got = prose.check(text, site.id, profile, kind="short", limits=lim_i, take=angle)
        left += [str(f.get("rule")) for f in got.get("flags") or []
                 if f.get("rule") != "site.length"]
        if i == 0:
            score, verdict = got.get("score"), got.get("verdict")
        out_parts.append(text)
    extras: list[dict[str, Any]] = []
    if disclose:
        last = out_parts[-1]
        room_last = first_room if len(out_parts) == 1 else site.limit
        if sites_mod.count(site, f"{last}\n\n{disclose}") <= room_last:
            out_parts[-1] = f"{last}\n\n{disclose}"
        else:
            extras.append({"key": "disclose", "words": "No disclosure line: the post had no room "
                                                       "for it", "drop": False})
    if m.link and not site.open_takes_url:
        out_parts[0] = f"{out_parts[0]}\n\n{m.link}"
    if m.link:
        where = "your blog post" if m.link_to == "post" else "the source"
        words = f"Links to {where}: {m.link}"
        if m.link_to == "post":
            words += ". Put it on your blog before you post this."
        extras.append({"key": "link", "words": words, "drop": False})
    else:
        extras.append({"key": "link", "words": "No link: the card has no source address",
                       "drop": False})
    if choice.direct and site.id == "bluesky" and m.card:
        extras.append({"key": "card", "words": f"Link card: {m.card.get('title') or m.link}",
                       "drop": False})
    if removed:
        extras.append({"key": "removed", "words": "Kranto took off " + "; ".join(
            dict.fromkeys(removed)), "drop": False})
    return {"site": site.id, "parts": out_parts, "extras": extras,
            "prose": {"score": score, "verdict": verdict, "rounds": rounds,
                      "angle": angle or None, "left": sorted(set(left))}}


def file_variant(store, choice: sites_mod.Choice, v: dict[str, Any], m: Material, *,
                 group: str, about: str, language: str) -> dict[str, Any]:
    """The variant's draft and its one ask (Open, or the site's own send when the person
    switched it to Post directly). ``{draft, ref, ticket, kind}``."""
    from ..core import tickets as tk
    site = choice.site
    parts = v["parts"]
    text = parts[0]
    content: dict[str, Any] = {
        "site": site.id, "group": group, "about": about, "about_title": m.title[:200],
        "parts": [{"text": p} for p in parts], "text": text, "link": m.link,
        "link_to": m.link_to, "extras": v["extras"], "prose": v["prose"],
        "language": language, "blog_draft": m.blog_draft}
    if choice.direct and site.id == "bluesky" and m.card:
        content["card"] = m.card
    if site.id == "mastodon":
        content["visibility"] = "public"
    if choice.instance:
        content["instance"] = choice.instance
    d = new_draft(store, cub=FILER, service=site.id, content=content, run_uuid=None)
    kind = site.direct_kind if choice.direct and site.direct_kind else "post.open"
    if kind == "post.open":
        fields: dict[str, Any] = {"draft_ref": d["ref"], "site": site.id, "text": text}
    elif kind == "post.bluesky":
        fields = {"draft_ref": d["ref"], "text": text, "parts": len(parts), "language": language}
    else:                              # post.mastodon
        fields = {"draft_ref": d["ref"], "text": text, "visibility": "public",
                  "language": language}
    tid = tk.file(store, cub=FILER, trust="core", granted=(kind,), kind=kind, fields=fields,
                  because=m.because or None, subject=("post_variant", f"{about}:{site.id}"),
                  capped=False)
    return {"draft": int(d["id"]), "ref": d["ref"], "ticket": tid, "kind": kind}


def new_group() -> str:
    return "w" + secrets.token_hex(6)


def write_all(rt, choices: list[sites_mod.Choice], m: Material, angle: str, *, about: str,
              complete, profile, language: str = "en") -> dict[str, Any]:
    """Every ticked site's variant of one write. A site whose variant failed is said, and the
    others are kept: ``{group, written: [site], failed: {site: why}}``."""
    group = new_group()
    written, failed = [], {}
    for choice in choices:
        try:
            v = write_variant(rt, choice, m, angle, complete=complete, profile=profile,
                              language=language)
            file_variant(rt.store, choice, v, m, group=group, about=about, language=language)
            written.append(choice.site.id)
        except Exception as exc:  # noqa: BLE001 - one site's failure never loses the others
            failed[choice.site.id] = str(getattr(exc, "words", None) or exc)[:200]
    return {"group": group, "written": written, "failed": failed}
