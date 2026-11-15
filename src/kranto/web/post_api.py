"""Post: the drafts the posting cubs wrote, what was sent, and the accounts.

| Route                          | Answers                                                       |
|--------------------------------|---------------------------------------------------------------|
| GET  /api/post                 | ``{line, drafts, sent, earlier, accounts}`` (``types.Post``)  |
| GET  /api/post/d/{id}          | one draft's sheet: its words as markdown, its ask, its account |
| GET  /api/post/d/{id}.md       | Download: the draft as ``<title>.md``                         |
| POST /api/post/d/{id}/edit     | ``post.edit``: the owner's words, filed as the next draft     |
| POST /api/post/write           | ``{about, as, angle}`` starts Write a post's job (409: cannot) |
| POST /api/post/angles          | ``{about, as}``: three proposed angles (one model call, no row) |
| POST /api/post/write/dismiss   | ``{about, as}``: a failed write's line on Post put away        |

``failed`` in ``GET /api/post`` is Write a post's jobs that failed in the last week and were not
dismissed, each with its reason and the link that fixes it (no model key: Settings › Watching).

One read for the Post page, the home's one thing and the console's ``kranto_details``. A draft is
a ``cub_drafts`` row; where it stands is its newest ask's (``core.tickets``, ``core.asks``):

- **waiting**: its ask is open, or practiced or refused and may be offered again (the row offers
  Send again). A draft's ask has no time limit, so a draft leaves this group only when it is
  sent, declined, or replaced by the next draft of its series;
- **sent**: its ask was done ("Sent on 3 Nov", the platform's own words and the link they hold);
- **earlier**: the rest, newest first: replaced by a newer draft, declined, not sure it went out,
  a draft with no ask. Each can still be opened, copied and downloaded.

Copy and Download need no account, no model and no network: the markdown is the draft's own
words, read from the row. Every GET writes nothing; the one write besides Write a post is Edit.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..core import asks, tickets

LINE = "Drafts wait here until you have seen them."
LIMIT = 60                       # the newest drafts read; older ones are in the cubs' own pages
URL = re.compile(r"https?://[^\s)\]>,;]+")

# the accounts a draft may go through, in the page's order: (key, word, how it is found)
ACCOUNTS = (("newsletter", "Newsletter"), ("mastodon", "Mastodon"), ("blog", "Blog"))


def _newsletter_services() -> tuple[str, ...]:
    from ..core.cubs.brokers.newsletter import NewsletterAdapter
    return NewsletterAdapter.services()


def kind_of(kind: str | None, service: str) -> str:
    """The draft's kind in a word, the account key it goes through: ``newsletter``, ``mastodon``
    (a short post) or ``blog`` (a blog post); else the service's own name."""
    k = tickets.canonical(kind) if kind else ""
    if k == "send.newsletter" or service in _newsletter_services():
        return "newsletter"
    if k == "post.mastodon" or service == "mastodon":
        return "mastodon"
    if k == "draft.sanity" or service in ("sanity", "blog"):
        return "blog"
    return service


WORD = {"newsletter": "newsletter", "mastodon": "short post", "blog": "blog post"}


def title_of(content: dict[str, Any]) -> str:
    """The draft's title: its subject, its title, else its text's first line."""
    for key in ("subject", "title"):
        if isinstance(content.get(key), str) and content[key].strip():
            return content[key].strip()
    text = str(content.get("text") or content.get("body") or "").strip()
    return (text.splitlines() or ["Untitled draft"])[0][:80]


def markdown_of(content: dict[str, Any]) -> str:
    """The draft as markdown, from its own words only: ``# <title>`` and the body (a short post
    is its text alone). What Copy puts on the clipboard and Download saves. A source's
    machine label written as a link's words ("obs 12825", "exa 3") reads as its outlet
    (``relabel``,)."""
    body = content.get("body")
    if not isinstance(body, str):
        return relabel(str(content.get("text") or "")).rstrip() + "\n"
    head = f"# {title_of(content)}\n\n"
    excerpt = content.get("excerpt")
    lead = f"*{excerpt.strip()}*\n\n" if isinstance(excerpt, str) and excerpt.strip() else ""
    return head + lead + relabel(body).rstrip() + "\n"


# a source's label as the writers' material names it: an observation, a search hit, a GitHub
# or Hacker News result ("obs 12825", "exa 3", "gh 2", "hn 1")
_LABEL = r"(?:obs|exa|gh|hn|xai)\s?#?[0-9]{1,9}"
_LINKED = re.compile(r"\[(" + _LABEL + r")\]\((https?://[^\s)]+)\)", re.IGNORECASE)
# a label with no address: in brackets ("[obs 12]"), or a list of them in parentheses
# ("(obs 12, exa 3)"); never a bare word in a sentence ("gh 2" could be anything)
_BARE = re.compile(r"\[" + _LABEL + r"\](?!\()|\(\s*" + _LABEL + r"(?:\s*[,;·]\s*" + _LABEL
                   + r")*\s*\)", re.IGNORECASE)
_SEP = re.compile(r"your library(?:\s*·\s*your library)+")


def _site(url: str) -> str:
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return {"news.ycombinator.com": "Hacker News", "github.com": "GitHub",
            "arxiv.org": "arXiv"}.get(host, host or "the source")


def relabel(text: str) -> str:
    """A draft's words with each source's machine label read as its outlet:
    ``[obs 12825](https://site/…)`` becomes ``[site](https://site/…)``, two links to one address
    are written once, and a label with no address reads "your library". For drafts already
    stored; the newsletter writer now writes the outlets itself."""
    seen: set[str] = set()

    def linked(m: re.Match[str]) -> str:
        url = m.group(2)
        if url in seen:
            return ""
        seen.add(url)
        return f"[{_site(url)}]({url})"

    out = _LINKED.sub(linked, text)
    out = _BARE.sub(lambda m: "(your library)" if m.group(0).startswith("(") else
                    "your library", out)
    out = _SEP.sub("your library", out)
    # a link written once leaves its separator behind: "a · · b" → "a · b"
    return re.sub(r"(\s·)(?:\s·)+", r"\1", out)


def filename(title: str) -> str:
    """``<title>.md``: letters, digits, spaces and dashes kept, at most 80 characters."""
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", title).strip()
    safe = re.sub(r"\s+", " ", safe)[:80].strip()
    return (safe or "draft") + ".md"


def _weekday(at: str) -> str:
    try:
        return datetime.fromisoformat(str(at).replace("Z", "+00:00")).strftime("%A")
    except ValueError:
        return ""


def fact_of(kind: str, t: dict[str, Any] | None, created_at: str, cub: str) -> str:
    """One fact for the row: "Monday's issue", "from #143", else none (the page says its kind).
    Never the cub's id (G4: "blog post · by examplecom")."""
    ideas = ((t or {}).get("because") or {}).get("ideas") or []
    if ideas:
        return f"from #{ideas[0]}"
    if kind == "newsletter" and _weekday(created_at):
        return f"{_weekday(created_at)}'s issue"
    return ""


def account_of(store, key: str) -> dict[str, Any]:
    """One account, from Kranto's own rows (no secret is read): ``{key, word, state, account,
    platform}`` with ``state`` ``connected``, ``needs_login`` or ``not set``."""
    from ..core.cubs.brokers.base import connection_of
    word = dict(ACCOUNTS)[key]
    platform = None
    if key == "newsletter":
        from .. import newsletter
        p = newsletter.named(store)
        provider, platform = (p.id, p.name) if p is not None else (None, None)
    else:
        provider = "mastodon" if key == "mastodon" else "sanity"
    conn = connection_of(store, provider)
    return {"key": key, "word": word, "state": conn["state"] if conn else "not set",
            "account": conn["account"] if conn else None, "platform": platform}


def _drafts(store, limit: int = LIMIT) -> list[dict[str, Any]]:
    rows = store.query("SELECT * FROM cub_drafts ORDER BY id DESC LIMIT ?", (int(limit),))
    out = []
    for r in rows:
        try:
            content = json.loads(r["content"])
        except (TypeError, ValueError):
            continue                     # a row Kranto cannot read is not drawn
        if isinstance(content, dict):
            out.append({**dict(r), "content": content})
    return out


def _newest_ask(store, cub: str, ref: str) -> dict[str, Any] | None:
    r = store.query_one("SELECT id FROM cub_tickets WHERE cub = ? AND "
                        "json_extract(fields, '$.draft_ref') = ? ORDER BY id DESC LIMIT 1",
                        (cub, ref))
    return tickets.get(store, r["id"]) if r else None


def _group(store, t: dict[str, Any] | None) -> str:
    if t is None:
        return "earlier"
    if t["state"] == tickets.OPEN:
        return "waiting"
    if t["state"] == "done":
        return "sent"
    if t["state"] in asks.AGAIN and asks.again_why_not(store, t) is None:
        return "waiting"
    return "earlier"


def _row(rt, d: dict[str, Any], t: dict[str, Any] | None, accounts: dict[str, dict[str, Any]],
         group: str) -> dict[str, Any]:
    """A draft's row. Its ask's line and button only while it waits: an earlier draft's line
    is what happened to it (``said``)."""
    kind = kind_of(t["kind"] if t else None, d["service"])
    ask = asks.row(rt, t) if t and group == "waiting" else None
    note = str((t or {}).get("note") or "")
    link = URL.search(note) if t and t["state"] == "done" else None
    acct = accounts.get(kind)
    return {"id": int(d["id"]), "ref": d["ref"], "cub": d["cub"], "kind": kind,
            "word": WORD.get(kind, kind), "title": title_of(d["content"]),
            "fact": fact_of(kind, t, d["created_at"], d["cub"]), "at": d["created_at"],
            "ticket": ask["ticket"] if ask else None, "again": ask["again"] if ask else None,
            "verb": ask["verb"] if ask else None, "line": ask["meta"] if ask else None,
            "said": (t or {}).get("said"),
            "note": note or None if t and t["state"] in ("done", "unknown") else None,
            "link": link.group(0) if link else None,
            "account": bool(acct and acct["state"] == "connected")}


def post_read(rt, jobs=None) -> dict[str, Any]:
    """``GET /api/post``: the drafts waiting, sent and earlier (newest first), the accounts,
    and the writes that failed (``failed``)."""
    store = rt.store
    accounts = {k: account_of(store, k) for k, _ in ACCOUNTS}
    groups: dict[str, list] = {"waiting": [], "sent": [], "earlier": []}
    for d in _drafts(store):
        t = _newest_ask(store, d["cub"], d["ref"])
        group = _group(store, t)
        groups[group].append(_row(rt, d, t, accounts, group))
    return {"line": LINE, "drafts": groups["waiting"], "sent": groups["sent"],
            "earlier": groups["earlier"], "accounts": [accounts[k] for k, _ in ACCOUNTS],
            "failed": failed_writes(store, jobs)}


def draft_sheet(rt, draft_id: int) -> dict[str, Any] | None:
    """``GET /api/post/d/{id}``: one draft's row with its group, its markdown and the account
    it would go through; None when there is no such draft."""
    store = rt.store
    r = store.query_one("SELECT * FROM cub_drafts WHERE id = ?", (int(draft_id),))
    if r is None:
        return None
    try:
        content = json.loads(r["content"])
    except (TypeError, ValueError):
        content = None
    if not isinstance(content, dict):
        return None
    d = {**dict(r), "content": content}
    t = _newest_ask(store, d["cub"], d["ref"])
    accounts = {k: account_of(store, k) for k, _ in ACCOUNTS}
    group = _group(store, t)
    row = _row(rt, d, t, accounts, group)
    return {**row, "group": group, "markdown": markdown_of(content),
            "filename": filename(row["title"]),
            "words": len(str(content.get("body") or content.get("text") or "").split()),
            "account_of": accounts.get(row["kind"]),
            **editable(store, d, t, group, row["kind"])}


# -- Edit (the verb ``post.edit``) --------------------------------------------
#
# The owner's words are filed as the next draft of the same series: a new ``cub_drafts`` row
# (``content`` gains ``edited: true`` and ``edited_from: <the draft edited>``), the old ask
# closed "replaced by #<ticket>", a new ask with the same fields but the new draft's ref and
# words. No row is changed in place (a press refuses a draft whose words changed since it was
# shown: ``brokers.base.press_draft``). Readers of ``content`` and the two new keys:
# ``title_of``, ``markdown_of``, ``_row``, ``draft_sheet`` and ``editable`` here, the adapters'
# ``perform``/``ask``/``readback`` (newsletter: subject, body, audience; mastodon: text; sanity:
# title, slug, body, tags, excerpt), the cubs' ``drafts.list``/``emails.get`` (subject, title):
# each reads the keys it knows by name and ignores the rest, so ``edited``/``edited_from`` are
# read only by ``editable`` (a missing key: not edited). Every performer sends from the draft's
# own ``content`` (its body or text), so an edited draft is sent as edited.

# the most a short post may hold, by kind (the ask's own field: ``post.mastodon``'s text, 500)
SHORT_MAX = {"mastodon": 500}
TITLE_MAX = 200
BODY_MAX = 200000
# the ask's field that repeats the draft's words, by the content key it repeats
ASK_FIELDS = {"subject": "subject", "title": "title", "text": "text"}


def _shape(content: dict[str, Any]) -> tuple[str | None, str]:
    """``(title key, words key)``: ``subject`` or ``title`` (or none, a short post) and
    ``body`` (a long post) or ``text`` (a short post)."""
    title = "subject" if "subject" in content else "title" if "title" in content else None
    return title, "body" if isinstance(content.get("body"), str) else "text"


def _original_version(store, d: dict[str, Any]) -> int:
    """The draft the writer wrote that this one was edited from (itself when not edited): its
    ``edited_from`` followed back, at most 50 steps."""
    cur: dict[str, Any] = d
    seen: set[int] = set()
    while isinstance(cur["content"].get("edited_from"), int) and len(seen) < 50:
        seen.add(cur["id"])
        r = store.query_one("SELECT * FROM cub_drafts WHERE id = ?",
                            (cur["content"]["edited_from"],))
        if r is None or r["id"] in seen:
            break
        try:
            content = json.loads(r["content"])
        except (TypeError, ValueError):
            break
        if not isinstance(content, dict):
            break
        cur = {**dict(r), "content": content}
    return int(cur["id"])


def editable(store, d: dict[str, Any], t: dict[str, Any] | None, group: str,
             kind: str) -> dict[str, Any]:
    """What the draft's editor needs (``GET /api/post/d/{id}``): ``edit`` (``{title, body}``
    for a long post, ``{parts: [{text}]}`` for a short one; the words as the page shows them,
    sources by outlet), ``limit`` (``{max, unit}`` or None), ``can_edit`` and why not,
    ``edited`` (the owner's words), ``edited_from`` and ``original_draft`` (the writer's own
    version)."""
    content = d["content"]
    tkey, wkey = _shape(content)
    words = relabel(str(content.get(wkey) or ""))
    edit: dict[str, Any] = {"title": str(content.get(tkey) or "") if tkey else None}
    if wkey == "body":
        edit["body"] = words
    else:
        edit["parts"] = [{"text": words}]
    why = None
    if t is not None and t["state"] == "confirmed":
        why = "This draft is being sent."
    elif group != "waiting":
        why = "Only a draft that waits can be edited: copy this one instead."
    edited_from = content.get("edited_from")
    return {"edit": edit, "can_edit": why is None, "cannot_edit": why,
            "limit": {"max": SHORT_MAX[kind], "unit": "characters"} if kind in SHORT_MAX
            and wkey == "text" else None,
            "edited": content.get("edited") is True,
            "edited_from": edited_from if isinstance(edited_from, int) else None,
            "original_draft": _original_version(store, d)}


def edit_draft(rt, draft_id: int, body: dict[str, Any], door: str = "ui") -> dict[str, Any]:
    """``POST /api/post/d/{id}/edit`` (``post.edit``): the owner's version of a waiting draft,
    filed as the next draft of its series (above). ``{title?, body?}`` (a long post) or
    ``{parts: [{text}]}`` (a short post: one part), or ``drop`` (an extra's key, when the draft
    has extras). ``{id, ref, ticket, withdrew, say}``; a ``WriteError`` says what is wrong."""
    from ..core.cubs.brokers.base import new_draft
    store = rt.store
    r = store.query_one("SELECT * FROM cub_drafts WHERE id = ?", (int(draft_id),))
    if r is None:
        raise WriteError("no such draft", 404)
    try:
        content = json.loads(r["content"])
    except (TypeError, ValueError):
        content = None
    if not isinstance(content, dict):
        raise WriteError("this draft cannot be read, so it cannot be edited", 409)
    d = {**dict(r), "content": content}
    t = _newest_ask(store, d["cub"], d["ref"])
    group = _group(store, t)
    kind = kind_of(t["kind"] if t else None, d["service"])
    can = editable(store, d, t, group, kind)
    if not can["can_edit"]:
        raise WriteError(can["cannot_edit"], 409)
    assert t is not None                    # a waiting draft has its ask
    tkey, wkey = _shape(content)
    new = {k: v for k, v in content.items() if k not in ("edited", "edited_from")}
    title, words, parts, drop = (body.get("title"), body.get("body"), body.get("parts"),
                                 body.get("drop"))
    if title is None and words is None and parts is None and drop is None:
        raise WriteError("send title and body, parts, or drop")
    if title is not None:
        if tkey is None:
            raise WriteError("a short post has no title")
        if not isinstance(title, str) or not title.strip() or len(title) > TITLE_MAX:
            raise WriteError(f"the title is 1 to {TITLE_MAX} characters")
        new[tkey] = " ".join(title.split())
    if parts is not None:
        if not isinstance(parts, list) or not parts or not all(
                isinstance(p, dict) and isinstance(p.get("text"), str) for p in parts):
            raise WriteError("parts is a list of {text}")
        if len(parts) > 1:
            raise WriteError("this draft is one post: send one part")
        words = parts[0]["text"]
    if words is not None:
        if not isinstance(words, str) or not words.strip():
            raise WriteError("the draft's words cannot be empty")
        limit = SHORT_MAX.get(kind) if wkey == "text" else BODY_MAX
        if limit and len(words) > limit:
            raise WriteError(f"{len(words):,} characters: at most {limit:,} for this post")
        new[wkey] = words.rstrip() + ("\n" if wkey == "body" else "")
    if drop is not None:
        stored = content.get("extras")
        extras: list[Any] = stored if isinstance(stored, list) else []
        keys = [e.get("key") for e in extras if isinstance(e, dict) and e.get("drop") is True]
        if drop not in keys:
            raise WriteError(f"this draft has no extra {drop!r} that can be removed")
        new["extras"] = [e for e in extras if not (isinstance(e, dict) and e.get("key") == drop)]
    new["edited"], new["edited_from"] = True, int(d["id"])
    from ..core import tickets as tk
    made = new_draft(store, cub=d["cub"], service=d["service"], content=new, run_uuid=None)
    fields = {**t["fields"], "draft_ref": made["ref"]}
    for ckey, fkey in ASK_FIELDS.items():
        if fkey in fields and isinstance(new.get(ckey), str):
            fields[fkey] = new[ckey]
    withdrew = t["state"] == tk.OPEN
    subject = (t["subject_kind"], t["subject_id"]) if t.get("subject_kind") else None
    try:
        tid = tk.file(store, cub=t["cub"], trust=t["trust"], granted=(t["kind"],),
                      kind=t["kind"], fields=fields, because=t["because"] or None,
                      subject=subject, note="edited by you", capped=False)
    except tk.TicketError as exc:
        raise WriteError(f"the edit could not wait for your yes: {exc}", exc.code) from None
    st = tk.state_of(store, t["id"])
    if st and st["state"] in (tk.OPEN, *asks.AGAIN):
        tk.append_state(store, t["id"], "expired", door=door, note=f"{tk.REPLACED}{tid}")
        old = tk.get(store, t["id"])
        if old:
            tk.resolved(store, old, "expired")
    say = "Saved. The original draft is under Earlier drafts."
    if withdrew:
        say = ("Saved. The send that waited for your yes was withdrawn; this version waits "
               "instead. The original is under Earlier drafts.")
    if d["ref"] != made["ref"] and ":" in d["ref"] and not d["ref"].startswith("draft:"):
        say += " The original filed at your newsletter platform stays there as a draft."
    return {"ok": True, "id": int(made["id"]), "ref": made["ref"], "ticket": tid,
            "withdrew": withdrew, "say": say}


# -- Write a post (the verb ``post.write``) -------------------------------------------

WRITING = "Writing the draft. It will be on Post in about a minute."
ABOUT = re.compile(r"card:(?P<card>[0-9]{1,9})|brief:(?P<brief>[0-9]{1,9}):(?P<item>[0-9]{1,3})"
                   r"|week")
# the posting cub that writes each kind of post, and its action for each subject
WRITERS: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    "blog": ("blog", {"card": ("blog.draft_card", "draft_card"),
                      "item": ("blog.draft_item", "draft_item"),
                      "week": ("blog.draft_week", "draft_week")}),
    "toot": ("toot", {"card": ("toot.draft", "draft_card")}),
}
BUILT_IN = ("blog",)              # added by Kranto from its own folder the first time it is asked


TAKE_MAX = 600


class WriteError(ValueError):
    def __init__(self, words: str, code: int = 400) -> None:
        super().__init__(words)
        self.words, self.code = words, code


def plan_write(about: Any, as_: Any, take: Any = None,
               angle: Any = None) -> tuple[str, str, str, dict[str, Any]]:
    """``(cub, kind, method, fields)`` for ``about`` (``card:<n>``, ``brief:<id>:<n>``, the
    item from 1, or ``week``) as ``as_`` (``blog``, the default, or ``toot``), or a
    ``WriteError`` in words. ``angle``: one sentence, the owner's own or a proposal they picked
    (Write a post's angle step, P-9), passed to the writer, which builds the post
    on it; none writes a plain summary. ``take`` is its old name, read when ``angle`` is
    absent."""
    if angle is None or (isinstance(angle, str) and not angle.strip()):
        angle = take
    take = angle
    as_ = str(as_ or "blog")
    if as_ not in WRITERS:
        raise WriteError("as is blog or toot")
    m = ABOUT.fullmatch(str(about or ""))
    if m is None:
        raise WriteError("about is card:<number>, brief:<id>:<item> or week")
    subject = "card" if m.group("card") else "item" if m.group("brief") else "week"
    cub, actions = WRITERS[as_]
    if subject not in actions:
        raise WriteError("a short post is about one idea card: write a blog post about this "
                         "instead")
    kind, method = actions[subject]
    if subject == "card":
        n = int(m.group("card"))
        fields: dict[str, Any] = {"card": n} if as_ == "blog" else {"idea": str(n)}
    elif subject == "item":
        fields = {"brief": int(m.group("brief")), "item": int(m.group("item"))}
    else:
        fields = {}
    if take is not None:
        if not isinstance(take, str) or len(take) > TAKE_MAX:
            raise WriteError(f"angle is one sentence of at most {TAKE_MAX} characters")
        if take.strip():
            fields["angle"] = " ".join(take.split())
    return cub, kind, method, fields


def ensure_writer(rt, cid: str, *, door: str) -> None:
    """The writing cub, installed and running: Kranto's own ``blog`` is added from Kranto's folder
    the first time a post is asked for (the owner's press of Write draft, or the console's
    ``post.write`` on their behalf), as the newsletter and toot cubs are added from it; any
    other missing writer is the owner's to add. A ``WriteError`` says what stops it."""
    cubs = getattr(rt, "cubs", None)
    if cubs is None:
        raise WriteError("posting is not running in this Kranto", 409)
    cubs.fresh()
    cub = cubs.installed.get(cid)
    if cub is None and cid in BUILT_IN:
        from ..core.cubs import install
        from ..cubs import examples_dir
        try:
            job = install.start(rt, str(examples_dir() / cid), kind="add", background=False)
            if job.get("state") != "awaiting_confirm":
                raise WriteError(f"Kranto could not add its blog writer: {job.get('error')}", 409)
            install.install(rt, job["id"], door=door)
        except install.InstallError as exc:
            raise WriteError(f"Kranto could not add its blog writer: {exc.words}", 409) from None
        cubs.fresh()
        cub = cubs.installed.get(cid)
    if cub is None:
        raise WriteError("short posts need the toot cub: add it on Settings › Posting", 409)
    if cub.state != "installed":
        raise WriteError(f"{cub.manifest.get('title') or cid} is paused: resume it first", 409)


def write(rt, about: Any, as_: Any, *, door: str, take: Any = None,
          angle: Any = None) -> dict[str, Any]:
    """The work of one Write draft, run in the background (``web/jobs.py``): the writer
    added if it must be, then its action, which ends in a draft and its ask on Post."""
    cid, kind, method, fields = plan_write(about, as_, take, angle)
    ensure_writer(rt, cid, door=door)
    try:
        out = rt.cubs.action(cid, kind, method, fields, door=door)
    except Exception as exc:  # noqa: BLE001 - said in words; the job keeps them for the page
        raise WriteError(not_written(str(exc)), 502) from None
    if isinstance(out, dict) and out.get("ok") is False:
        raise WriteError(not_written(str(out.get("say") or out.get("error") or "")))
    return {"cub": cid, "say": (out or {}).get("say") if isinstance(out, dict) else None}


# -- the angle step (rule 4, P-9): three angles to pick, for a card or an item --

ANGLES_PURPOSE = "post_angles"
NO_ANGLES_KEY = ("No angles were proposed: no model key is set. Add one on Settings › Watching, "
                 "or type your own sentence.")


def material_for(rt, about: Any) -> dict[str, str]:
    """``{title, facts}`` of a card (``card:<n>``) or a news item (``brief:<id>:<n>``), as the
    blog writer gives them to the model; a ``WriteError`` for anything else."""
    from types import SimpleNamespace
    m = ABOUT.fullmatch(str(about or ""))
    if m is None or about == "week":
        raise WriteError("angles are for one idea card (card:<n>) or one news item "
                         "(brief:<id>:<item>)")
    if m.group("card"):
        from ..core.api import ReadError, cards_get
        try:
            card = cards_get(SimpleNamespace(store=rt.store), {"id": int(m.group("card"))})
        except ReadError as exc:
            raise WriteError(str(exc), 404) from None
        title = "\n".join(str(x) for x in (card.get("title"), card.get("one_liner"),
                                           card.get("thesis"), card.get("insight"),
                                           card.get("why")) if x)
        facts = "\n".join(f"[{s['n']}] {s.get('source') or ''}: {s.get('claim') or ''}"
                          for s in card.get("sources") or []) or "(no sources)"
        return {"title": title, "facts": facts}
    from ..core import registry
    from ..features import FEATURES
    from ..features.news.api import briefs_get
    news = next((f for f in FEATURES if f.id == "news"), None)
    if news is None:
        raise WriteError("News is not part of this Kranto", 409)
    try:
        brief = briefs_get(registry.context(rt, news), {"id": int(m.group("brief"))})
    except ValueError:
        raise WriteError(f"no brief {m.group('brief')}", 404) from None
    items = brief.get("items") or []
    n = int(m.group("item"))
    if not 1 <= n <= len(items):
        raise WriteError(f"brief {m.group('brief')} has no item {n}", 404)
    it = items[n - 1]
    return {"title": str(it.get("headline") or ""),
            "facts": f"{it.get('body') or ''}\n{it.get('why') or ''}".strip()}


def propose_angles(rt, about: Any, as_: Any = "blog") -> dict[str, Any]:
    """``POST /api/post/angles`` ``{about, as}``: three proposed angles (a claim, a prediction,
    a question), each one sentence in the owner's voice card; one model call under the
    writer's own model when one is set (P-11). Nothing is stored: the page shows them beside
    the box where the owner types their own, and the one picked goes to ``post.write`` as
    ``angle``."""
    from .. import prose
    from ..prose.angles import AnglesError
    as_ = str(as_ or "blog")
    plan_write(about, as_)                 # the same subjects and writers as Write a post
    material = material_for(rt, about)
    llm = getattr(rt, "llm", None)
    if llm is None or not llm.has_key:
        raise WriteError(NO_ANGLES_KEY, 409)
    profile = prose.load(rt.cfg, rt.store)
    writer = WRITERS[as_][0]
    own = profile.writer_model(writer)
    site = "blog" if as_ == "blog" else "mastodon"
    used: dict[str, Any] = {}

    def complete(messages: list[dict], schema: dict) -> dict:
        got = llm.complete(tier="reason", purpose=ANGLES_PURPOSE, messages=messages,
                           prompt_version="post-angles@1", max_tokens=400, temperature=0.7,
                           schema=schema, **({"provider": own["provider"],
                                              "model": own["model"]} if own else {}))
        used["model"] = got.model
        return {"text": got.text, "structured": got.structured}

    try:
        out = prose.angles(material, profile, complete=complete, site=site)
    except AnglesError as exc:
        raise WriteError(f"No angles this time ({exc}): try again, or type your own "
                         "sentence.", 502) from None
    except Exception as exc:  # noqa: BLE001 - the provider's refusal, in the owner's words
        raise WriteError(not_written(str(exc)).replace("No draft was written",
                                                       "No angles were proposed"), 502) \
            from None
    return {"about": about, "as": as_, "angles": out, "model": used.get("model"),
            "say": "Pick one, change it, or write your own sentence."}


NO_KEY = ("No draft was written: no model key is set. Add one on Settings › Watching, then "
          "choose Write a post again.")
FIX_KEY = "settings/watching"      # the page's link beside NO_KEY
FAILED_DAYS = 7                    # a failed write stays on Post this long unless dismissed


def preflight(rt) -> None:
    """A write that cannot start says so at once (4: with no key the job started, the
    page said "Writing the draft", and it failed a second later as "the model did not
    answer")."""
    llm = getattr(rt, "llm", None)
    if llm is not None and not llm.has_key:
        raise WriteError(NO_KEY, 409)


def write_key(about: Any, as_: Any) -> str:
    return f"post:{as_ or 'blog'}:{about}"


def _about_title(store, about: str) -> str | None:
    m = ABOUT.fullmatch(about or "")
    if m is None:
        return None
    if m.group("card"):
        r = store.query_one("SELECT title FROM ideas WHERE id = ?", (int(m.group("card")),))
        return str(r["title"]) if r and r["title"] else f"card #{m.group('card')}"
    return "this week's news" if about == "week" else "a news item"


def failed_writes(store, jobs) -> list[dict[str, Any]]:
    """Write a post's jobs that failed in the last week and were not dismissed, newest first:
    Post keeps each with its reason and Try again (4: a reload lost the failure)."""
    if jobs is None:
        return []
    import time

    from ..store import iso
    out = []
    for j in jobs.listing("post:"):
        if j["state"] != "failed" or j["dismissed"]:
            continue
        at = j["finished"] or j["started"] or 0
        if time.time() - at > FAILED_DAYS * 86400:
            continue
        _, as_, about = (j["key"].split(":", 2) + ["", ""])[:3]
        error = str(j["error"] or "No draft was written.")
        out.append({"about": about, "as": as_, "error": error,
                    "at": iso(datetime.fromtimestamp(at, UTC)),
                    "title": _about_title(store, about),
                    "fix": FIX_KEY if "model key" in error else None})
    return out


def not_written(why: str) -> str:
    """Why no draft was written, in the owner's words (the page's toast after Write draft): a
    missing key says so; a model that did not answer names the key to check; a cub's own
    words stand; the machinery's words ("the handler raised HostError …") never reach the
    owner."""
    low = why.lower()
    if "no api key" in low or "no model key" in low:
        return NO_KEY
    if "model did not answer" in low or "llmerror" in low or "budget" in low:
        return ("No draft was written: the model did not answer. Check the model key on "
                "Settings › Watching, then choose Write a post again.")
    if not why or "handler raised" in low or "error" in low.split(":", 1)[0]:
        return "No draft was written: the writer stopped. Activity has what happened."
    return f"No draft was written: {why}"


class PostAPI:
    def __init__(self, app) -> None:
        self.app = app

    async def write(self, request: Request):
        """``POST /api/post/write`` ``{about, as}`` (the verb ``post.write``): answers at once
        with the job; the draft is on Post when it ends (no request waits on a model)."""
        from .app import _json_body
        from .auth import IDENTITY
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        about, as_ = body.get("about"), body.get("as") or "blog"
        # the angle; ``take``, round 1's name, is its alias
        take = body.get("angle")
        if take is None or (isinstance(take, str) and not take.strip()):
            take = body.get("take")
        try:
            plan_write(about, as_, take)
        except WriteError as exc:
            return JSONResponse({"error": exc.words}, status_code=exc.code)
        door = (request.scope.get(IDENTITY) or {}).get("origin") or "ui"
        door = door if door in ("ui", "cli") else "cli"
        rt = self.rt
        try:
            preflight(rt)
        except WriteError as exc:
            # kept as a failed job: Post lists it with its reason and the link that fixes it
            job = self.app.jobs.fail(write_key(about, as_), exc.words)
            return JSONResponse({"error": exc.words, "fix": FIX_KEY, "job": job},
                                status_code=exc.code)
        job = self.app.jobs.start(write_key(about, as_),
                                  lambda: write(rt, about, as_, door=door,
                                                **({"angle": take} if take else {})))
        return JSONResponse({"say": WRITING, "about": about, "as": as_, "job": job},
                            status_code=202)

    async def angles(self, request: Request):
        """``POST /api/post/angles`` ``{about, as}``: Write a post's angle step, three proposed
        sentences (one model call; nothing is stored)."""
        from .app import _json_body
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        try:
            out = await run_in_threadpool(propose_angles, self.rt, body.get("about"),
                                          body.get("as") or "blog")
        except WriteError as exc:
            return JSONResponse({"error": exc.words}, status_code=exc.code)
        return JSONResponse(out)

    async def job(self, request: Request):
        """``GET /api/post/write?about=&as=``: the job of that Write draft, if any."""
        q = request.query_params
        job = self.app.jobs.get(f"post:{q.get('as') or 'blog'}:{q.get('about')}")
        if job is None:
            return JSONResponse({"error": "no such job"}, status_code=404)
        return JSONResponse(job)

    async def dismiss(self, request: Request):
        """``POST /api/post/write/dismiss`` ``{about, as}``: a failed write's line on Post put
        away (the owner's; nothing else changes)."""
        from .app import _json_body
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        key = write_key(body.get("about"), body.get("as"))
        if not await run_in_threadpool(self.app.jobs.dismiss, key):
            return JSONResponse({"error": "no such write"}, status_code=404)
        return JSONResponse({"ok": True})

    @property
    def rt(self):
        return self.app.rt

    async def post(self, request: Request):
        return JSONResponse(await run_in_threadpool(post_read, self.rt, self.app.jobs))

    async def sheet(self, request: Request):
        out = await run_in_threadpool(draft_sheet, self.rt, request.path_params["id"])
        if out is None:
            return JSONResponse({"error": "no such draft"}, status_code=404)
        return JSONResponse(out)

    async def edit(self, request: Request):
        """``POST /api/post/d/{id}/edit`` (``post.edit``): the owner's words for a waiting
        draft, filed as its series' next draft (``edit_draft``)."""
        from .app import _json_body
        from .auth import IDENTITY
        body = await _json_body(request)
        if body is None:
            return JSONResponse({"error": "expected a JSON object"}, status_code=400)
        door = (request.scope.get(IDENTITY) or {}).get("origin") or "ui"
        try:
            out = await run_in_threadpool(edit_draft, self.rt, request.path_params["id"], body,
                                          "ui" if door == "ui" else "cli")
        except WriteError as exc:
            return JSONResponse({"error": exc.words}, status_code=exc.code)
        return JSONResponse(out)

    async def download(self, request: Request):
        out = await run_in_threadpool(draft_sheet, self.rt, request.path_params["id"])
        if out is None:
            return JSONResponse({"error": "no such draft"}, status_code=404)
        return Response(out["markdown"], media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition":
                                 f'attachment; filename="{out["filename"]}"'})

    def routes(self) -> list[Route]:
        return [Route("/api/post", self.post),
                Route("/api/post/write", self.write, methods=["POST"]),
                Route("/api/post/write/dismiss", self.dismiss, methods=["POST"]),
                Route("/api/post/angles", self.angles, methods=["POST"]),
                Route("/api/post/write", self.job),
                Route("/api/post/d/{id:int}.md", self.download),
                Route("/api/post/d/{id:int}/edit", self.edit, methods=["POST"]),
                Route("/api/post/d/{id:int}", self.sheet)]
