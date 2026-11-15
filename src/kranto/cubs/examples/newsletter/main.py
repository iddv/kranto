"""The newsletter cub: the week's News briefs become one newsletter issue,
which you read and send through the newsletter platform you connected (it never names one).

Rules it keeps: every item of the body is a brief's item, verbatim from ``briefs.get`` (the cub
adds nothing but the intro, which its one model call writes from the headlines only, inside a
fence); the ticket's subject is the draft's; the cub sends nothing: the ticket waits for your
press, and while ``send.newsletter`` is dry (the default) the press sends nothing either.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from bears_cub import Cub

cub = Cub()
KIND = "send.newsletter"
STATES = {"done": "sent", "dry": "practiced", "declined": "closed", "expired": "closed",
          "refused": "refused", "unknown": "unknown"}


def _since(ctx, days: int) -> str:
    return ctx.now_minus(days=days).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _week(ctx) -> list[dict]:
    """The briefs of the last 7 days that say something, for the chosen topics (the setting,
    else every topic), newest first."""
    topics = ctx.settings["newsletter.topics"] or [t["id"] for t in ctx.read.topics()["topics"]]
    out: dict[int, dict] = {}
    for t in topics:
        for b in ctx.read.briefs(topic_id=int(t), since=_since(ctx, 7), limit=10)["briefs"]:
            if b.get("items"):
                out[b["id"]] = b
    return sorted(out.values(), key=lambda b: b["id"], reverse=True)


TASK = ("You write a two-sentence intro for a newsletter issue from its headlines. Plain "
        "words, no hype. Answer with the intro only.")


def _intro(ctx, headlines: str, hint: str) -> tuple[str, dict]:
    """The intro, through Kranto's prose engine: the floor, the newsletter's
    template and the person's voice card (``newsletter.intro`` moved into it), then checked and
    rewritten only where it reads like AI."""
    composed = ctx.prose.compose({"title": "this week's issue", "facts": headlines,
                                  "hint": hint or None},
                                 site="newsletter", kind="intro", task=TASK)
    reply = ctx.model.complete(purpose="newsletter_intro", tier="reason", max_tokens=200,
                               messages=composed["messages"])
    intro = " ".join(str(reply.get("text") or "").split())
    # what the intro was written from: the checker flags a person or a handle the headlines lack
    sources = headlines.strip() or None
    got = ctx.prose.check(intro, site="newsletter", kind="intro", take="", sources=sources)
    rounds = 0
    if intro and any(f.get("scope", "span") == "span" or f.get("rule") == "site.length"
           for f in got.get("flags") or []):
        fixed = ctx.prose.revise(intro, got["flags"], purpose="newsletter_intro", tier="reason",
                                 site="newsletter", kind="intro", take="", sources=sources)
        intro, rounds = " ".join(str(fixed.get("text") or intro).split()), fixed.get("rounds", 0)
        got = {**got, **{k: fixed[k] for k in ("flags", "score", "verdict") if k in fixed}}
        if sources:
            # revise's own last look has no sources: what is left is checked with them
            got = ctx.prose.check(intro, site="newsletter", kind="intro", take="",
                                  sources=sources)
    line = str(composed.get("disclosure") or "")
    if line:
        intro = f"{intro} {line}".strip()
    return intro, {"score": got.get("score"), "verdict": got.get("verdict"), "rounds": rounds,
                   "left": [f.get("rule") for f in got.get("flags") or []]}


def _hint(tone) -> str:
    """The form's tone for this one issue (plain is the voice card's own, so no hint)."""
    tone = tone[0] if isinstance(tone, list) and tone else tone
    return f"a {tone} tone" if tone and tone != "plain" else ""


def _assemble(ctx, briefs: list[dict], hint: str, subject: str | None) -> dict | None:
    items, cites = [], []
    for b in briefs:
        full = ctx.read.brief(b["id"])
        for it in full.get("items") or []:
            if len(items) >= ctx.settings["newsletter.max_items"]:
                break
            items.append({"headline": it["headline"], "body": it["body"],
                          "why": it.get("why") or "", "date": it.get("date"),
                          "sources": [s for s in it.get("sources") or [] if s.get("url")]})
            cites.append({"kind": "brief", "id": b["id"], "label": f"brief {b['id']}"})
    if not items:
        return None
    headlines = "\n".join(f"- {it['headline']}" for it in items)
    intro, prose = _intro(ctx, headlines, hint)
    first = items[0]["headline"][:60]
    subject = (subject or f"{ctx.settings['newsletter.subject_prefix']}: {first}")[:200]
    body = intro + "\n\n" + "\n\n".join(_item(it) for it in items)
    return {"subject": subject, "body": body, "items": items, "cites": cites,
            "briefs": sorted({b["id"] for b in briefs}), "intro": intro, "prose": prose}


_SITES = {"news.ycombinator.com": "Hacker News", "github.com": "GitHub", "arxiv.org": "arXiv"}


def _outlet(s: dict) -> str:
    """A source's link words: its outlet's name, else its address's site; never the
    material's label ("obs 12825", "exa 3":)."""
    # the address's site, read as text (a cub imports nothing that reaches the web)
    host = str(s["url"]).split("//", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
    host = host.lower().removeprefix("www.")
    if host in _SITES:
        return _SITES[host]
    name = str(s.get("source") or "").strip()
    return name if name and len(name) <= 60 else host or "the source"


def _item(it: dict) -> str:
    when = f" ({it['date']})" if it.get("date") else ""
    seen: set[str] = set()
    links = []
    for s in it["sources"]:
        if s["url"] not in seen:
            seen.add(s["url"])
            links.append(f"[{_outlet(s)}]({s['url']})")
    links = " · ".join(links)
    why = f"\n*Why it matters:* {it['why']}" if it["why"] else ""
    return f"**{it['headline']}**{when}\n{it['body']}{why}" + (f"\n{links}" if links else "")


def _when(ctx) -> str:
    """``now``, or the next time of day ``newsletter.send_at`` names (UTC, ``HH:MM``)."""
    at = str(ctx.settings["newsletter.send_at"] or "now").strip()
    m = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", at)
    if not m:
        return "now"
    now = ctx.now_minus(days=0).astimezone(UTC)
    t = datetime(now.year, now.month, now.day, int(m.group(1)), int(m.group(2)), tzinfo=UTC)
    if t <= now + timedelta(minutes=30):
        t += timedelta(days=1)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _file(ctx, issue: dict, trigger: str) -> dict:
    draft = ctx.broker("newsletter").call("emails.create_draft", subject=issue["subject"],
                                          body=issue["body"])
    ref = draft["draft_ref"]
    t = ctx.ticket(KIND, {"draft_ref": ref, "subject": issue["subject"], "audience": "all",
                          "when": _when(ctx)},
                   because={"briefs": issue["briefs"]},
                   subject={"kind": "newsletter_issue", "id": ref})
    row = {"id": ref, "subject": issue["subject"], "intro": issue["intro"], "date": ctx.today(),
           "briefs": [f"brief {b}" for b in issue["briefs"]], "brief_ids": issue["briefs"],
           "item_count": len(issue["items"]), "where": draft["where"], "cites": issue["cites"],
           "body_markdown": issue["body"], "prose": issue.get("prose") or {},
           "ticket": t.ticket_id, "state": "waiting", "trigger": trigger}
    ctx.kv.put(f"issue:{ref}", row)
    ctx.events.publish("newsletter.drafted", {"draft_ref": ref, "brief_ids": issue["briefs"],
                                              "ticket_id": t.ticket_id},
                       subject={"kind": "newsletter_issue", "id": ref},
                       dedupe=f"drafted:{ref}")
    return row


@cub.job("compose")
def compose(ctx):
    """Monday 08:00: the week's briefs become one issue and one ticket. A run that filed today's
    issue is not repeated (at least once: a second delivery skips); a run that failed before
    filing (the model did not answer) is, when the job is due again."""
    done = f"composed:{ctx.today()}"
    if ctx.kv.get(done) is not None:
        return {"status": "skipped", "line": "already composed today"}
    briefs = _week(ctx)
    if not briefs:
        return {"status": "skipped", "line": "no briefs this week"}
    issue = _assemble(ctx, briefs, "", None)
    if issue is None:
        return {"status": "skipped", "line": "the week's briefs have no items"}
    row = _file(ctx, issue, "schedule")
    ctx.kv.put(done, row["id"])
    return {"summary": {"items": len(issue["items"]), "ticket": row["ticket"]},
            "line": f"issue drafted: {row['subject']} ({len(issue['items'])} items), "
                    "it waits for your approval (Send)"}


@cub.action("compose_now")
def compose_now(ctx, fields):
    week = _week(ctx)
    chosen = {int(x) for x in (fields.get("briefs") or [])}
    briefs = [b for b in week if b["id"] in chosen] or week
    issue = _assemble(ctx, briefs, _hint(fields.get("intro")),
                      fields.get("subject") or None)
    if issue is None:
        return {"ok": False, "say": "No brief of the last week has items."}
    _file(ctx, issue, "owner")
    return {"say": "Issue drafted: it waits for Send.",
            "refresh": ["issues", "rows", "count"]}


@cub.action("redraft")
def redraft(ctx, fields):
    ref = fields["issue_id"]          # the subject's id, given as <subject without newsletter_>_id
    row = ctx.kv.get(f"issue:{ref}")
    if row is None:
        return {"ok": False, "say": "That issue is not one of this cub's."}
    ctx.withdraw({"kind": "newsletter_issue", "id": ref}, note="redrafted")
    briefs = [b for b in _week(ctx) if b["id"] in row.get("brief_ids", [])] or _week(ctx)
    issue = _assemble(ctx, briefs, _hint(fields.get("intro")), None)
    if issue is None:
        return {"ok": False, "say": "No brief of the last week has items."}
    _file(ctx, issue, "owner")
    row["state"] = "closed"
    ctx.kv.put(f"issue:{ref}", row)
    return {"say": "Redrafted: the new issue waits for Send.",
            "refresh": ["issues", "rows", "count"]}


@cub.event("ticket.resolved")
def on_resolved(ctx, events):
    """The core's word on our tickets: sent, practiced, declined, expired, refused, unknown.
    Any kind of ours that names one of our issues' drafts (1.4.0: an earlier release's name of
    the kind too; 1.3.1 skipped it, so an issue it had expired stayed "waiting")."""
    for ev in events:
        p = ev["payload"]
        if p.get("cub") != ctx.cub_id:
            continue
        t = ctx.tickets.get(p["ticket_id"])
        ref = (t.get("fields") or {}).get("draft_ref")
        if not ref:
            continue
        row = ctx.kv.get(f"issue:{ref}")
        if row is None:
            continue
        row["state"] = STATES.get(p["state"], p["state"])
        if p["state"] == "done" and str(t.get("note") or "").startswith("scheduled"):
            row["state"] = "scheduled"
        row["note"] = t.get("note")
        ctx.kv.put(f"issue:{ref}", row)
    return len(events)


def _issues(ctx) -> list[dict]:
    """Our issues, newest first. One still "waiting" is read again from the core (1.4.0): its
    answer may have come before this version handled it (an earlier release's kind)."""
    rows = [v for _, v in ctx.kv.items("issue:") if isinstance(v, dict)]
    for r in rows:
        if r.get("state") == "dry run":            # an earlier version's word for it
            r["state"] = "practiced"
        if r.get("state") == "waiting" and r.get("ticket"):
            st = ctx.tickets.get(r["ticket"]).get("state")
            if st and st != "needs_confirm":
                r["state"] = STATES.get(st, st)
    return sorted(rows, key=lambda r: (r["date"], r["ticket"]), reverse=True)


@cub.read("issues")
def issues(ctx, params):
    rows = _issues(ctx)
    return {"waiting": [r for r in rows if r["state"] == "waiting"],
            "sent": [r for r in rows if r["state"] in ("sent", "scheduled")],
            "practiced": [r for r in rows if r["state"] == "practiced"],
            "closed": [r for r in rows if r["state"] in ("closed", "refused", "unknown")]}


@cub.read("rows")
def rows(ctx, params):
    return {"rows": [{"id": r["id"], "title": r["subject"],
                      "meta": f"{r['item_count']} items · draft in {r['where']}",
                      "at": r["date"], "ticket": r["ticket"]}
                     for r in _issues(ctx) if r["state"] == "waiting"]}


@cub.read("count")
def count(ctx, params):
    return {"count": sum(1 for r in _issues(ctx) if r["state"] == "waiting")}


@cub.read("brief_choices")
def brief_choices(ctx, params):
    return {"choices": [{"value": str(b["id"]),
                         "word": f"{str(b.get('created_at') or '')[:10]} · topic "
                                 f"{b['topic_id']} · {len(b.get('items') or [])} items"}
                        for b in _week(ctx)]}
