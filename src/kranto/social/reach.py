"""Reach: what a post Kranto sent drew, read back once a day, and what was learned from it.

Read live from each site's documents on 14 November 2026 (``docs/posting.md``, "What each
site gives back"):

- **Bluesky**: ``app.bsky.feed.getPosts`` on the public AppView, no sign-in, up to 25 posts a
  call: ``replyCount``, ``repostCount``, ``likeCount``, ``quoteCount``. It takes the post's
  ``at://`` address with the account's DID (an address with the handle was refused), so the send
  keeps the address ``createRecord`` answers.
- **Mastodon**: ``GET /api/v1/statuses/:id`` on the person's server, through their posting
  connection: ``replies_count``, ``reblogs_count``, ``favourites_count`` and, from Mastodon 4.5,
  ``quotes_count``. No views.
- **Threads**: ``GET /{media-id}/insights?metric=views,likes,replies,reposts,quotes`` with the
  person's token, which needs ``threads_manage_insights``; each metric as ``values[0].value``
  or ``total_value.value``.
- **LinkedIn** gives a member's own numbers only to approved partners, and **X** charges for
  each read (and Kranto never posts to X): their rows carry the address and no numbers, and the
  Sent group says why once (``NO_NUMBERS``).

Never the text of anyone's reply: counts only.

**When:** the daily job ``post.reach`` reads each post once a day for its first 14 days, then
once a week until it is 60 days old. **The preview never reads** (the job does nothing there).

**Stored:** ``post_reach``, one row a reading, never edited. The first row of a sent post is
written by the send itself (``sent``): no numbers yet, the site's own ids and the post's shape
(site, parts, card, length, weekday and hour, its angle's kind), which is what ``learned``
compares.

**Learned** (``learned``): per site, what the numbers support with at least ``MIN_SIDE`` posts
on each side of a comparison: the better hour of the day, one post against a thread, a link card
against none. Fewer, and it says how many more it needs; never invented lore.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..store import Store, iso, utcnow

log = logging.getLogger("kranto.social.reach")

KIND = "post.reach"                     # the job's runs.kind
READS = ("bluesky", "mastodon", "threads")
NO_NUMBERS = {"linkedin": "LinkedIn gives its numbers only to approved partners",
              "x": "X charges for each read"}
DAILY_DAYS = 14
LAST_DAYS = 60
MIN_SIDE = 8                            # posts on each side of a comparison, at least
BSKY_APPVIEW = "https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts"
THREADS_API = "https://graph.threads.net/v1.0"
COUNTS = ("replies", "reposts", "likes", "quotes", "views")
SENT = "sent"                           # the note of a post's first row, written at the send
DEADLINE_S = 15.0


def _at(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _int(v: Any) -> int | None:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


# -- at the send ------------------------------------------------------------------------------


def sent(store: Any, ticket_id: int, site: str, ids: dict[str, Any], content: dict[str, Any],
         *, parts: int = 1, now: datetime | None = None) -> None:
    """A post went out: its first ``post_reach`` row, no numbers yet, the site's own ``ids``
    (Bluesky's ``uri``, Mastodon's ``id`` and ``instance``, Threads' ``id``, LinkedIn's ``urn``)
    and its shape. Called by the adapters after a send that answered done; a failure here never
    touches the send's outcome."""
    now = now or utcnow()
    from .hours import local
    try:
        when = local(now)
        angle = content.get("angle_kind")
        shape = {"site": site, "ids": {k: v for k, v in ids.items() if isinstance(v, str)},
                 "parts": int(parts), "card": isinstance(content.get("card"), dict),
                 "length": len(str(content.get("text") or "")),
                 "weekday": when.strftime("%A"), "hour": when.hour,
                 "angle": angle if isinstance(angle, str) else None}
        from ..stored.cubs import PostReachShape
        store.insert("post_reach", {"ticket_id": int(ticket_id), "site": site, "read_at": iso(now),
                                    "shape": PostReachShape.write(shape), "note": SENT,
                                    "created_at": iso(now)})
    except Exception:  # noqa: BLE001 - the post went out; its reach row is not worth a failure
        log.exception("could not keep the shape of a sent post (ask %s)", ticket_id)


def _shape(raw: Any) -> dict[str, Any]:
    """A stored shape as an object, whatever was stored (null, not JSON, a list: ``{}``); its
    ``ids`` as an object too."""
    from ..stored.cubs import PostReachShape
    try:
        v = dict(PostReachShape.load(raw).extra)
    except (TypeError, ValueError):
        return {}
    if not isinstance(v.get("ids"), dict):
        v["ids"] = {}
    return v


# -- what is due -------------------------------------------------------------------------------


def posts(store: Store) -> list[dict[str, Any]]:
    """Every sent post Kranto kept a first row for: ``{ticket_id, site, sent_at, shape, last}``
    with ``last`` its newest reading's time (None: never read)."""
    rows = store.query(
        "SELECT r.ticket_id, r.site, r.read_at AS sent_at, r.shape, "
        "(SELECT MAX(x.read_at) FROM post_reach x WHERE x.ticket_id = r.ticket_id "
        " AND x.id > r.id) AS last "
        "FROM post_reach r WHERE r.note = ? AND r.id = (SELECT MIN(id) FROM post_reach y "
        "WHERE y.ticket_id = r.ticket_id) ORDER BY r.id", (SENT,))
    return [{**dict(r), "shape": _shape(r["shape"])} for r in rows]


def due(store: Store, now: datetime | None = None) -> list[dict[str, Any]]:
    """The posts to read now: a site that gives numbers; daily (20 hours since the last
    reading) for ``DAILY_DAYS``, weekly after, none past ``LAST_DAYS``."""
    now = now or utcnow()
    out = []
    for p in posts(store):
        if p["site"] not in READS:
            continue
        age = now - _at(p["sent_at"])
        if age > timedelta(days=LAST_DAYS) or age < timedelta(hours=1):
            continue
        gap = timedelta(hours=20) if age <= timedelta(days=DAILY_DAYS) else timedelta(days=6.5)
        if p["last"] is None or now - _at(p["last"]) >= gap:
            out.append(p)
    return out


# -- the readers (each site's documented shape) ------------------------------------------------


def read_bluesky(http: Any, uris: list[str]) -> dict[str, dict[str, int | None]]:
    """``{uri: counts}`` from the public AppView: no sign-in; 25 a call."""
    out: dict[str, dict[str, int | None]] = {}
    for i in range(0, len(uris), 25):
        chunk = uris[i:i + 25]
        # httpx writes a list as the key repeated: ?uris=a&uris=b, the AppView's own form
        r = http.get(BSKY_APPVIEW, params={"uris": chunk}, deadline=DEADLINE_S, errors=False)
        if not 200 <= r.status_code < 300:
            continue
        try:
            body = r.json()
        except ValueError:
            continue
        for post in (body.get("posts") if isinstance(body, dict) else None) or []:
            if isinstance(post, dict) and isinstance(post.get("uri"), str):
                # the AppView leaves a count of zero out: a count missing from a post it
                # answered for is 0 (views it gives only to the signed-in author: none)
                out[post["uri"]] = {"replies": _int(post.get("replyCount", 0)),
                                    "reposts": _int(post.get("repostCount", 0)),
                                    "likes": _int(post.get("likeCount", 0)),
                                    "quotes": _int(post.get("quoteCount", 0)), "views": None}
    return out


def read_mastodon(send: Any, instance: str, status_id: str) -> dict[str, int | None] | None:
    r = send("GET", f"https://{instance}/api/v1/statuses/{status_id}")
    if not 200 <= r.status_code < 300:
        return None
    try:
        body = r.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    return {"replies": _int(body.get("replies_count")), "reposts": _int(body.get("reblogs_count")),
            "likes": _int(body.get("favourites_count")), "quotes": _int(body.get("quotes_count")),
            "views": None}


def _metric(item: dict[str, Any]) -> int | None:
    """One Threads insight's number: ``total_value.value``, else the last of ``values``."""
    total = item.get("total_value")
    if isinstance(total, dict) and _int(total.get("value")) is not None:
        return _int(total.get("value"))
    values = item.get("values")
    if isinstance(values, list) and values and isinstance(values[-1], dict):
        return _int(values[-1].get("value"))
    return None


def read_threads(send: Any, media_id: str) -> dict[str, int | None] | str | None:
    """Counts, or the words why the token cannot read them (a permission missing), or None."""
    r = send("GET", f"{THREADS_API}/{media_id}/insights",
             params={"metric": "views,likes,replies,reposts,quotes"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code in (400, 403) and isinstance(body, dict) and isinstance(
            body.get("error"), dict):
        return ("Threads did not give the numbers: your token needs the permission "
                "threads_manage_insights")
    if not 200 <= r.status_code < 300 or not isinstance(body, dict):
        return None
    got: dict[str, int | None] = {k: None for k in COUNTS}
    for item in body.get("data") or []:
        if isinstance(item, dict) and item.get("name") in got:
            got[item["name"]] = _metric(item)
    return got


# -- the daily job -----------------------------------------------------------------------------


def run(rt: Any, now: datetime | None = None) -> dict[str, Any]:
    """The daily ``post.reach`` job: read every due post's numbers, one row each; then
    LinkedIn's token reminder (``remind``). Nothing on the preview. Kranto never retries a read
    by itself: a post a site did not answer for is read at the next run."""
    from .. import preview
    from ..core.cubs.brokers.base import BrokerContext, connection_of
    from ..sources.base import SourceError
    now = now or utcnow()
    store = rt.store
    if preview.enabled(getattr(getattr(rt, "cfg", None), "root", None)):
        return {"read": 0, "skipped": "the preview reads nothing"}
    todo = due(store, now)
    read, said = 0, list[str]()

    def keep(p: dict[str, Any], counts: dict[str, int | None], note: str | None = None) -> None:
        nonlocal read
        store.insert("post_reach", {"ticket_id": int(p["ticket_id"]), "site": p["site"],
                                    "read_at": iso(now), **{k: counts.get(k) for k in COUNTS},
                                    "shape": "{}", "note": note, "created_at": iso(now)})
        read += 1

    sky = [p for p in todo if p["site"] == "bluesky" and (p["shape"].get("ids") or {}).get("uri")]
    if sky:
        try:
            got = read_bluesky(rt.http, [p["shape"]["ids"]["uri"] for p in sky])
        except SourceError as exc:
            got, said = {}, [*said, f"Bluesky did not answer ({exc})"[:160]]
        for p in sky:
            counted = got.get(p["shape"]["ids"]["uri"])
            if counted is not None:
                keep(p, counted)
    for site, provider in (("mastodon", "mastodon_post"), ("threads", "threads_post")):
        mine = [p for p in todo if p["site"] == site and (p["shape"].get("ids") or {}).get("id")]
        if not mine:
            continue
        conn = connection_of(store, provider)
        if conn is None or conn["state"] != "connected":
            said.append(f"{site}: not connected, its numbers were not read")
            continue
        ctx = BrokerContext(store=store, cub="social", rt=rt, connection=conn, provider=provider)
        for p in mine:
            ids = p["shape"]["ids"]
            c: dict[str, int | None] | str | None
            try:
                if site == "mastodon":
                    c = read_mastodon(ctx.send, ids.get("instance") or ctx.instance or "",
                                      ids["id"])
                else:
                    c = read_threads(ctx.send, ids["id"])
            except SourceError as exc:
                said.append(f"{site} did not answer ({exc})"[:160])
                break                          # the site is down or refused: tomorrow
            if isinstance(c, str):
                said.append(c)
                break
            if c is not None:
                keep(p, c)
    reminded = remind(store, now)
    return {"read": read, "due": len(todo), "said": said, "reminded": reminded}


def remind(store: Store, now: datetime | None = None) -> list[str]:
    """LinkedIn's 60 days (Needs you, a week before): its token cannot be refreshed by an app
    like Kranto, so a message says by which day the person makes a new one. The day is the
    connection's ``connected`` event plus 60 days (library rows only; no secret is read). One
    message a token (``dedup_key``)."""
    from .. import notify
    from ..core.cubs.brokers.base import connection_of
    now = now or utcnow()
    conn = connection_of(store, "linkedin_post")
    if conn is None or conn["state"] != "connected":
        return []
    ev = store.query_one("SELECT created_at FROM connection_events WHERE connection_id = ? AND "
                         "event = 'connected' ORDER BY id DESC LIMIT 1", (conn["id"],))
    if ev is None:
        return []
    by = _at(ev["created_at"]) + timedelta(days=60)
    if by - now > timedelta(days=7):
        return []
    from .hours import local
    day = local(by)
    words = f"{day.day} {day.strftime('%B')}"
    title = (f"LinkedIn needs a new token by {words} (5 minutes)" if by > now
             else "LinkedIn's token has run out: make a new one (5 minutes)")
    got = notify.emit(store, "alarm", title,
                      "LinkedIn's tokens last 60 days and an app like Kranto cannot renew one. "
                      "On Settings › Posting, LinkedIn (posting): make a new token with "
                      "openid, profile and w_member_social in LinkedIn's token tool, and paste "
                      "it. Until then Kranto cannot post to LinkedIn.",
                      dedup_key=f"linkedin-token:{conn['id']}:{iso(by)[:10]}"
                                + (":out" if by <= now else ""),
                      origin=KIND, links=["#/settings/posting"], now=now)
    return [title] if got else []


# -- what the page reads -----------------------------------------------------------------------


def newest(store: Store, ticket_id: int) -> dict[str, Any] | None:
    """A sent post's newest reading with numbers: ``{replies, …, read_at, words}``, or None."""
    r = store.query_one("SELECT * FROM post_reach WHERE ticket_id = ? AND (note IS NULL OR "
                        "note != ?) ORDER BY id DESC LIMIT 1", (int(ticket_id), SENT))
    if r is None:
        return None
    out = {k: r[k] for k in COUNTS}
    out["read_at"] = r["read_at"]
    out["words"] = words(out)
    return out


def words(c: dict[str, Any]) -> str:
    """"4 replies, 9 reposts, 31 likes" (a count the site gave none of is left out)."""
    parts = []
    for key, one, many in (("replies", "reply", "replies"), ("reposts", "repost", "reposts"),
                           ("likes", "like", "likes"), ("quotes", "quote", "quotes"),
                           ("views", "view", "views")):
        n = c.get(key)
        if isinstance(n, int):
            parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts) or "no numbers yet"


def foot(sites_sent: set[str]) -> str | None:
    """The Sent group's foot, once: the sites among those sent to whose numbers Kranto cannot
    read, in words; None when every one gives them."""
    gone = [s for s in ("linkedin", "x") if s in sites_sent]
    if not gone:
        return None
    from ..core.sites import name_of
    names = " and ".join(name_of(s) for s in gone)
    why = "; ".join(NO_NUMBERS[s] for s in gone)
    return f"No numbers from {names}: {why}."


def _score(c: dict[str, Any]) -> int:
    return sum(int(c.get(k) or 0) for k in ("replies", "reposts", "likes", "quotes"))


def learned(store: Store) -> dict[str, Any]:
    """``GET /api/post/learned``: per site, ``{site, word, posts, lines, needs}``. ``lines`` the
    comparisons the numbers support (at least ``MIN_SIDE`` posts on each side), each
    ``{key, words, posts}``; ``needs`` how many more posts with numbers it takes before there
    is anything to say. A post's score is its replies, reposts, likes and quotes at its newest
    reading."""
    from ..core.sites import name_of
    by: dict[str, list[tuple[dict[str, Any], int]]] = {}
    for p in posts(store):
        n = newest(store, p["ticket_id"])
        if n is None or p["site"] not in READS:
            continue
        by.setdefault(p["site"], []).append((p["shape"], _score(n)))
    out = []
    for site in READS:
        rows = by.get(site, [])
        lines = []
        for key, split, yes, no in (
                ("thread", lambda s: (s.get("parts") or 1) > 1, "threads", "single posts"),
                ("card", lambda s: bool(s.get("card")), "posts with a link card",
                 "posts without one")):
            a = [sc for sh, sc in rows if split(sh)]
            b = [sc for sh, sc in rows if not split(sh)]
            if len(a) >= MIN_SIDE and len(b) >= MIN_SIDE:
                ma, mb = sum(a) / len(a), sum(b) / len(b)
                if ma == mb:
                    lines.append({"key": key, "posts": len(rows),
                                  "words": f"{yes.capitalize()} and {no} drew the same"})
                    continue
                hi, lo, x = (yes, no, ma / mb if mb else None) if ma > mb else \
                    (no, yes, mb / ma if ma else None)
                times = f"{x:.1f} times" if x else "more than"
                lines.append({"key": key, "posts": len(rows),
                              "words": f"{hi.capitalize()} drew {times} what {lo} did "
                                       f"({len(rows)} posts)"})
        hours: dict[int, list[int]] = {}
        for sh, sc in rows:
            if isinstance(sh.get("hour"), int):
                hours.setdefault(sh["hour"], []).append(sc)
        best = [(sum(v) / len(v), h, len(v)) for h, v in hours.items() if len(v) >= MIN_SIDE]
        rest = len(rows) - max((n for _, _, n in best), default=0)
        if best and rest >= MIN_SIDE:
            _, h, _n = max(best)
            lines.append({"key": "hour", "posts": len(rows),
                          "words": f"Best hour so far: {h:02d}:00, from {len(rows)} posts"})
        out.append({"site": site, "word": name_of(site), "posts": len(rows), "lines": lines,
                    "needs": max(0, 2 * MIN_SIDE - len(rows)) if not lines else 0})
    return {"sites": out, "min_side": MIN_SIDE,
            "line": "Kranto compares only what at least 8 posts on each side support."}
