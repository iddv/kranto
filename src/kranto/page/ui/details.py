"""Details: the record behind a row or a dialog.

The screen shows what decides; the record is one tap away (the Details drawer, ui/Details.svelte)
and one call away (the console's ``kranto_details``), and both read this one function, so the
drawer and the tool never disagree. A record is its title, the page it opens on, and short groups
of facts in the design's order (What · Who, when · The rules it meets · Evidence · The run · Log),
each a list of [label, value] rows; its last line names the call that reads it.

``sel`` names the object as a row's ``data-sel`` does: ``b<build key>``, ``prep:<uuid>`` (an
assistant's prepared item), ``ask:<id>`` (a cub's ask), ``i<idea id>`` or ``card:<n>``,
``s<source id>``. the server's objects are read through its JSON API, never its database. Every
stored value is read for what it is (a missing key, a null, a list or a dict): a record never
fails on a shape it did not expect, it says less.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from .http import HttpError

ORDER = ("What", "Who, when", "The rules it meets", "Evidence", "What could go wrong",
         "The cheapest test", "Asked of you", "The run", "Log")
LONG = 600


def _words(k: str) -> str:
    """a key in words: created_at → created at"""
    return str(k).replace("_", " ").strip()


def _when(v) -> str | None:
    """a time in words: an epoch or an ISO string as "2026-10-29 18:54 UTC"; else None"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and 1e9 < v < 1e11:
        return datetime.fromtimestamp(v, UTC).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(v, str) and re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d", v):
        return v[:16].replace("T", " ") + " UTC"
    return None


def _value(v) -> str | None:
    """a stored value as words, whatever its shape; None for nothing"""
    if v is None or v == "" or v == [] or v == {}:
        return None
    w = _when(v)
    if w:
        return w
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:g}" if isinstance(v, float) else str(v)
    if isinstance(v, list):
        parts = [p for p in (_value(x) if not isinstance(x, dict) else _brief(x) for x in v[:8]) if p]
        more = f" and {len(v) - 8} more" if len(v) > 8 else ""
        return ("; ".join(parts) + more) or None
    if isinstance(v, dict):
        return _brief(v)
    s = str(v)
    return s if len(s) <= LONG else s[:LONG] + "…"


def _brief(d: dict) -> str | None:
    """a small dict in one line: its title or name, else its first few facts"""
    for k in ("title", "name", "label", "words", "text"):
        if isinstance(d.get(k), str) and d[k]:
            return _value(d[k])
    parts = [f"{_words(k)} {_value(v)}" for k, v in list(d.items())[:4] if _value(v) and not isinstance(v, (dict, list))]
    return ", ".join(parts) or None


def _rows(d: dict, keys=None, skip=()) -> list[list[str]]:
    out = []
    for k in keys if keys is not None else list(d):
        if k in skip or k not in d:
            continue
        v = _value(d.get(k))
        if v is not None:
            out.append([_words(k), v])
    return out


def _record(sel: str, kind: str, title: str, page: str | None, groups: dict[str, list]) -> dict:
    return {"sel": sel, "kind": kind, "title": title or sel, "page": page,
            "groups": [{"h": h, "rows": groups[h]} for h in ORDER if groups.get(h)],
            "tool": f"kranto_details {sel}"}


def _prepared(a, uuid: str, sel: str) -> dict:
    body = a.afk("GET", "/api/prepared")
    items = body.get("prepared") if isinstance(body, dict) else None
    p = next((x for x in items or [] if isinstance(x, dict) and x.get("uuid") == uuid), None)
    if p is None:
        raise HttpError(404, f"no prepared item {uuid!r}")
    rawf = p.get("fields")
    fields: dict = rawf if isinstance(rawf, dict) else {}
    return _record(sel, "prepared", p.get("title") or "prepared", p.get("page") or "#/needs", {
        "What": [["action", f"{p.get('title') or ''} ({p.get('verb')})"]] + _rows(fields) + _rows(p, ("says", "subject_kind", "subject_id", "subject_name")),
        "Who, when": _rows(p, ("by_words", "created_at", "expires_at", "state", "uuid")),
        "The rules it meets": _rows(p, ("locked", "words")),
    })


def _ask(a, tid: str, sel: str) -> dict:
    body = a.afk("GET", f"/api/tickets/{tid}/ask")
    d = body if isinstance(body, dict) else {}
    title = d.get("title") or d.get("question") or f"ask {tid}"
    rest = [k for k in d if k not in ("title", "question")]
    who = [k for k in rest if re.search(r"(^by|_by$|^at$|_at$|expires|cub|version|history|id$)", k)]
    rules = [k for k in rest if re.search(r"(rule|policy|mode|trust|class|stops|blocked|why)", k)]
    what = [k for k in rest if k not in who and k not in rules]
    return _record(sel, "ask", title, d.get("page") or "#/needs", {
        "What": _rows(d, what), "Who, when": _rows(d, who), "The rules it meets": _rows(d, rules)})


def _idea(a, iid: str, sel: str) -> dict:
    # an idea is its card (card:<n>); the build loop's own ideas (i<id>) left with it (CUT)
    n = iid.split(":", 1)[1] if iid.startswith("card:") else None
    card = None
    if n is not None:
        try:
            card = a.afk("GET", f"/api/ideas/{n}")
        except HttpError:
            card = None
    base: dict = {}
    c = card if isinstance(card, dict) else {}
    if not base and not c:
        raise HttpError(404, f"no idea {iid!r}")
    title = base.get("title") or c.get("title") or iid
    ev = c.get("citations") or c.get("evidence") or []
    # what cubs asked on the card, each in the owner's words: never a ticket's state name
    asked = [[_value(t.get("created_at")) or "", f"{t.get('cub') or ''}: {t.get('title') or ''} ({_ASKED.get(str(t.get('state')), str(t.get('state') or '').replace('_', ' '))})"]
             for t in c.get("tickets") or [] if isinstance(t, dict)]
    return _record(sel, "idea", title, f"#/ideas/{base.get('id') or iid}", {
        "What": _rows(base, ("status", "title", "source", "text")) + _rows(c, ("thesis", "for_whom", "output_kind", "theme")),
        "Who, when": _rows(base, ("created", "updated", "id")) + _rows(c, ("number", "created_at")),
        "The rules it meets": _rows(c, ("score", "rank", "grade", "signals", "topics")),
        "Evidence": _claims(c.get("citations")) or
        [[str(i + 1), _value(x) or ""] for i, x in enumerate(ev[:20]) if _value(x)],
        "What could go wrong": [["risks", v] for v in [_value(c.get("risks"))] if v],
        "The cheapest test": [["test", v] for v in [_value(c.get("cheapest_test"))] if v],
        "Asked of you": asked,
    })


def _claims(cites) -> list[list[str]]:
    """a card's claims, each with the source it rests on and that source's address (the drawer
    links an address): Details showed bare URLs and observation ids (11, Codex 5)"""
    out: list[list[str]] = []
    for i, x in enumerate((cites if isinstance(cites, list) else [])[:20]):
        if not isinstance(x, dict) or not x.get("claim"):
            continue
        where = str(x.get("source") or "") or (str(x.get("url") or "").split("/")[2:3] or [""])[0]
        out.append([f"{i + 1}. {where}".strip(), _value(x.get("claim")) or ""])
        if isinstance(x.get("url"), str) and x["url"].startswith(("https://", "http://")):
            out.append(["", x["url"]])
    return out


_ASKED = {"needs_confirm": "waits for you", "confirmed": "approved", "done": "done", "dry": "practiced: not sent",
          "expired": "not approved in time", "declined": "declined", "refused": "not sent", "unknown": "not sure it went out"}


def _source(a, sid: str, sel: str) -> dict:
    s = a.afk("GET", f"/api/sources/{sid}")
    d = s.get("source") if isinstance(s, dict) and isinstance(s.get("source"), dict) else (s if isinstance(s, dict) else {})
    if not d:
        raise HttpError(404, f"no source {sid!r}")
    return _record(sel, "source", d.get("label") or f"source {sid}", f"#/settings/sources/{sid}", {
        "What": _rows(d, ("status", "review", "kind", "site_name", "url", "description", "why", "detail")),
        "Who, when": _rows(d, ("created_at", "last_fetch", "id")),
        "The rules it meets": _rows(d, ("topics", "mute", "removal", "group", "role")),
        "The run": _rows(d, ("items_per_day", "kept_rate", "yield_per_day", "kept_30d", "judged_30d", "failing_runs", "last_error")),
    })


def record(a, q: dict) -> dict:
    """GET /api/details?sel=…: the record of the object a row or a dialog names."""
    sel = str((q or {}).get("sel") or "").strip()
    if not sel or len(sel) > 200:
        raise HttpError(400, "sel names the object: prep:<uuid>, ask:<id>, card:<n>, s<source id>")
    if sel.startswith("prep:"):
        return _prepared(a, sel[5:], sel)
    if sel.startswith("ask:"):
        return _ask(a, sel[4:], sel)
    if sel.startswith("card:"):
        return _idea(a, sel, sel)
    if sel.startswith("b") and len(sel) > 1:
        raise HttpError(404, "builds are not part of Kranto any more")
    if sel.startswith("icard:"):
        return _idea(a, sel[1:], sel)
    if sel.startswith("i") and len(sel) > 1:
        return _idea(a, sel[1:], sel)
    if sel.startswith("s") and sel[1:].isdigit():
        return _source(a, sel[1:], sel)
    raise HttpError(404, f"Details does not know {sel!r} yet: prep:<uuid>, ask:<id>, card:<n> or s<source id>")


def said(rec: dict) -> str:
    """the record in one line for the console, the answer first"""
    first: list = next((g["rows"] for g in rec.get("groups") or [] if g.get("rows")), [])
    facts = "; ".join(f"{k}: {v}" for k, v in first[:3])
    return f"{rec.get('title')}{' (' + rec['page'] + ')' if rec.get('page') else ''}: {facts}." if facts else str(rec.get("title"))
