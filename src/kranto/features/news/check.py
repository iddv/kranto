"""The checks on a brief, in code (the table). The model's reply is strangers' text
summarised by a model, so nothing it writes is shown until these have run:

- citations: every cite is an ``obs N`` of the block or a result label it holds; a cite that
  names nothing goes, and an item left citing nothing is dropped;
- dates: an item's date is its newest cited line's; older than ``max_age_days`` is
  background, shown last under Earlier;
- length: a body of two sentences at most, body and why ``max_words`` together, a headline
  under 90; asked once shorter (``brief``), then cut at the sentence;
- names: ``scrub`` on body and why; a named person a cited line does not name, said or acting
  by name, becomes "a person";
- URLs: a URL in the text that no cited line has is removed;
- novelty: an item about what the previous brief said is a repeat, dropped, unless it says
  what is new or is dated later;
- count: more than ``max_items``, the lowest-signal go; none left is a quiet brief.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from kranto.core.text import scrub, words

HEADLINE_MAX = 90
MAX_SENTENCES = 2
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_CITE = re.compile(r"^\s*\[?\s*([a-z]{2,6})\s+(\d{1,9})\s*\]?\s*$")
_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z]\.)?\s[A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b")
_SPEECH = ("said", "says", "told", "wrote", "writes", "posted", "argued", "argues", "noted",
           "announced", "tweeted", "claimed", "claims")
_ROLES = ("researcher", "engineer", "ceo", "founder", "professor", "scientist", "analyst",
          "executive", "developer", "author", "investor", "reporter", "chief")
_DEVELOPMENT = re.compile(r"\b(since|now|new|newly|update[sd]?|follow[- ]up|latest)\b", re.I)
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "its", "is",
         "at", "by", "as", "from", "new", "says", "after", "into", "over", "than"}


@dataclass
class Line:
    """One line of the material a cite may name: an observation or a search result."""

    label: str                 # "obs 12" | "exa 3" | "hn 2"
    kind: str                  # obs | web
    date: str | None           # YYYY-MM-DD
    title: str
    url: str | None
    text: str                  # title, summary or snippet: what the line says
    signal: float = 0.0
    ident: int | None = None   # an observation's id
    source: str | None = None


@dataclass
class Report:
    bad_citations: int = 0
    dropped_uncited: int = 0
    background: int = 0
    shortened: int = 0
    cut: int = 0
    names_replaced: int = 0
    urls_removed: int = 0
    repeats: int = 0
    over_count: int = 0
    unsupported_names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def sentences(text: str) -> list[str]:
    text = " ".join(str(text or "").split())
    return [s for s in _SENT.split(text) if s] if text else []


def too_long(item: dict[str, Any], max_words: int) -> bool:
    return (len(sentences(item.get("body", ""))) > MAX_SENTENCES
            or words(item.get("body")) + words(item.get("why")) > max_words
            or len(item.get("headline", "")) >= HEADLINE_MAX)


def cut(item: dict[str, Any], max_words: int) -> dict[str, Any]:
    """Cut an over-long item at the sentence: the body's first sentences that fit, the why's
    first sentence, the headline at a word under 90 characters."""
    out = dict(item)
    why = sentences(out.get("why", ""))[:1]
    out["why"] = why[0] if why else ""
    room = max(10, max_words - words(out["why"]))
    kept: list[str] = []
    for s in sentences(out.get("body", ""))[:MAX_SENTENCES]:
        if words(" ".join(kept + [s])) > room and kept:
            break
        kept.append(s)
    body = " ".join(kept)
    if words(body) > room:
        body = " ".join(body.split()[:room]).rstrip(",;:") + "..."
    out["body"] = body
    head = out.get("headline", "")
    if len(head) >= HEADLINE_MAX:
        head = head[:HEADLINE_MAX - 4].rsplit(" ", 1)[0] + "..."
    out["headline"] = head
    return out


def _cites(raw: Any, lines: dict[str, Line], rep: Report) -> list[str]:
    out = []
    for c in raw if isinstance(raw, list) else []:
        m = _CITE.match(str(c).lower())
        label = f"{m.group(1)} {m.group(2)}" if m else None
        if label in lines:
            if label not in out:
                out.append(label)
        else:
            rep.bad_citations += 1
    return out


def _names(text: str, cited: str, rep: Report) -> str:
    """A person the cited lines do not name, said or acting by name, becomes "a person"."""
    def repl(m: re.Match[Any]) -> str:
        name = m.group(1)
        if name in cited:
            return str(name)
        before = text[max(0, m.start() - 30):m.start()].lower()
        after = text[m.end():m.end() + 12].lower()
        if any(after.lstrip(" ,").startswith(v) for v in _SPEECH) or \
                any(r in before.split()[-2:] for r in _ROLES):
            rep.names_replaced += 1
            return "a person"
        if name not in rep.unsupported_names:
            rep.unsupported_names.append(name)
        return str(name)
    return _NAME.sub(repl, text)


def _urls(text: str, allowed: set[str], rep: Report) -> str:
    def repl(m: re.Match[Any]) -> str:
        url = m.group(0).rstrip(".,;:")
        if url in allowed:
            return str(m.group(0))
        rep.urls_removed += 1
        return ""
    return " ".join(_URL.sub(repl, text).split())


def _content(headline: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", headline.lower()) if w not in _STOP}


def is_repeat(item: dict[str, Any], previous: list[dict[str, Any]], lines: dict[str, Line]) -> bool:
    """About what the previous brief said: a shared observation or URL, or half the headline's
    words; unless the item says what is new or is dated after the previous item."""
    obs = {lines[c].ident for c in item["cites"] if lines[c].ident is not None}
    urls = {lines[c].url for c in item["cites"] if lines[c].url}
    head = _content(item["headline"])
    for p in previous:
        shared = bool(obs & set(p.get("observation_ids") or [])) or \
            bool(urls & set(p.get("urls") or []))
        ph = _content(p.get("headline", ""))
        similar = bool(head) and len(head & ph) * 2 >= len(head)
        if shared or similar:
            later = (item.get("date") or "") > (p.get("date") or "")
            if later or _DEVELOPMENT.search(item.get("body", "")):
                continue
            return True
    return False


def check(reply_items: list[Any], lines: dict[str, Line], previous: list[dict[str, Any]], *,
          today: date,
          max_items: int, max_words: int, max_age_days: int) -> tuple[list[dict[str, Any]], Report]:
    """The checked items (in the order shown: dated first, background last) and what the
    checks did. ``reply_items``: the model's items, already shortened where it was asked."""
    rep = Report()
    kept = []
    for raw in reply_items if isinstance(reply_items, list) else []:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {k: " ".join(str(raw.get(k) or "").split())
                                for k in ("headline", "body", "why")}
        item["cites"] = _cites(raw.get("cites"), lines, rep)
        if not item["cites"] or not item["headline"] or not item["body"]:
            rep.dropped_uncited += 1
            continue
        cited = [lines[c] for c in item["cites"]]
        dates = sorted(d for d in (c.date for c in cited) if d)
        item["date"] = dates[-1] if dates else None
        old = item["date"] is not None and \
            item["date"] < (today - timedelta(days=max_age_days)).isoformat()
        item["background"] = bool(old)
        rep.background += int(old)
        if too_long(item, max_words):
            item = cut(item, max_words)
            rep.cut += 1
        text_of = " ".join(f"{c.title} {c.text}" for c in cited)
        allowed = {c.url for c in cited if c.url}
        for k in ("body", "why", "headline"):
            item[k] = _urls(_names(scrub(item[k]), text_of, rep), allowed, rep)
        item["observation_ids"] = [c.ident for c in cited if c.ident is not None]
        item["urls"] = sorted(allowed)
        item["signal"] = max((c.signal for c in cited), default=0.0)
        item["sources"] = [{"label": c.label, "kind": c.kind, "id": c.ident, "title": c.title,
                            "url": c.url, "date": c.date, "source": c.source} for c in cited]
        if is_repeat(item, previous, lines):
            rep.repeats += 1
            continue
        kept.append(item)
    if len(kept) > max_items:
        order = sorted(range(len(kept)), key=lambda i: kept[i]["signal"], reverse=True)
        keep = set(order[:max_items])
        rep.over_count = len(kept) - max_items
        kept = [k for i, k in enumerate(kept) if i in keep]
    kept.sort(key=lambda it: it["background"])            # stable: dated first, Earlier last
    return kept, rep
