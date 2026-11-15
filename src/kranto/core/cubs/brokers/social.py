"""Short posts for the sites people use: the asks a variant waits on.

Every variant Kranto's writer makes (``kranto.social``) is a ``cub_drafts`` row of the filer
``social`` (Kranto's own, trust ``core``), service the site's id, and one ask:

- ``post.open``: the site's composer is opened by the person (a plain link the page follows;
  the server sends nothing). Its confirm is **I posted it**: the performer makes no request off
  the machine and records ``posted by you``. Kranto's own kind: never grantable to a cub.
- ``post.bluesky`` (``bluesky``), ``post.mastodon`` (``mastodon``), ``post.threads``
  (``threads``), ``post.linkedin`` (``linkedin``, which has no Open): Kranto posts the draft
  after the person's yes, when they switched the site to Post directly.

Every posting kind waits until it is answered (no time limit), is confirmed on the page only,
and is refused on the preview before anything is written (``core.tickets.confirm``).
"""

from __future__ import annotations

from ... import tickets
from .base import draft_of, press_draft

FILER = "social"
SITE_IDS = ("bluesky", "mastodon", "x", "threads", "linkedin")
POSTED_BY_YOU = "posted by you"
_F = tickets.Field


def _open_perform(store, ticket: dict, context, mode: str = "live") -> dict:
    """I posted it: the person's record that they posted the draft themselves. No request."""
    d = press_draft(store, ticket, tuple(SITE_IDS), ("text",))
    if isinstance(d, str):
        return {"state": "refused", "note": f"refused: {d}"}
    return {"state": "done", "note": POSTED_BY_YOU}


def _open_ask(fields: dict, store, rt=None) -> dict:
    from ...sites import name_of
    site = name_of(fields.get("site"))
    first = " ".join(str(fields.get("text") or "").split())
    return {"verb": "I posted it", "title": first[:80] + ("…" if len(first) > 80 else ""),
            "to": f"your {site} account, posted by you in {site}",
            "body": str(fields.get("text") or ""), "needs": None}


def _open_readback(fields: dict, store) -> list[tuple[str, str]]:
    from ...sites import name_of
    return [("Site", name_of(fields.get("site"))), ("Text", str(fields.get("text") or "")),
            ("What Kranto does", "nothing is sent: this records that you posted it")]


def register_kinds() -> None:
    tickets.register(tickets.Kind(
        "post.open", "I posted it", {
            "draft_ref": _F("str", pattern=r"draft:[0-9]{1,12}", max_len=20, label="Draft"),
            "site": _F("enum", SITE_IDS, label="Site"),
            "text": _F("str", max_len=5000, label="Text")},
        expires_hours=None, per_day=60, first_party_only=True, perform=_open_perform,
        readback=_open_readback, ask=lambda f, s, rt: _open_ask(f, s, rt),
        meta={"verb": "I posted it", "button": "I posted it", "noun": "post",
              "done": "Posted by you", "not_done": "not posted",
              "question": "Did you post it?"}))
    tickets.register(tickets.Kind(
        "post.bluesky", "Post to Bluesky", {
            "draft_ref": _F("str", pattern=r"draft:[0-9]{1,12}", max_len=20, label="Draft"),
            "text": _F("str", max_len=1000, label="Text"),
            "parts": _F("int", lo=1, hi=4, label="Posts in the thread"),
            "language": _F("str", pattern=r"[a-z]{2}(-[A-Za-z]{2})?", max_len=5,
                           label="Language")},
        expires_hours=None, per_day=30, first_party_only=True,
        meta={"verb": "Post to Bluesky", "button": "Post to Bluesky", "noun": "post",
              "done": "Posted", "not_done": "not posted",
              "question": "Post this to Bluesky?"}))
    for kind, name, most in (("post.linkedin", "LinkedIn", 3000), ("post.threads", "Threads", 500)):
        tickets.register(tickets.Kind(
            kind, f"Post to {name}", {
                "draft_ref": _F("str", pattern=r"draft:[0-9]{1,12}", max_len=20, label="Draft"),
                "text": _F("str", max_len=most * 2, label="Text")},
            expires_hours=None, per_day=30, first_party_only=True,
            meta={"verb": f"Post to {name}", "button": f"Post to {name}", "noun": "post",
                  "done": "Posted", "not_done": "not posted",
                  "question": f"Post this to {name}?"}))


def parts_of(content: dict) -> list[str]:
    """A variant's posts in order: ``parts`` (a list of ``{text}``), else its ``text`` as one.
    A draft written before short posts had parts, or a part stored as null, reads as text."""
    raw = content.get("parts")
    if isinstance(raw, list):
        out = [p["text"] for p in raw if isinstance(p, dict)
               and isinstance(p.get("text"), str) and p["text"].strip()]
        if out:
            return out
    text = content.get("text")
    return [text] if isinstance(text, str) and text.strip() else []


def draft_site(store, ref: str) -> str | None:
    d = draft_of(store, ref)
    return (d or {}).get("service")
