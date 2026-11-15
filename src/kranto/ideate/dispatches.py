"""Idea cards from the operator's Parallax dispatches, without a model.

A dispatch (``parallax-dispatches/dispatches/<id>.md``, schema 2) is an article that finds
one connection across four clusters, makes a falsifiable prediction, and closes with
three pitches: an OSS idea, a commercial pitch and a founder pitch. They are labelled in
bold (``**An OSS idea.**``, ``**Commercial pitch.**``, ``**OSS project worth
building.**``...) or, in a few early ones, led in prose ("OSS project worth starting this
week: ...", "For commercial: ...", "The founder move is ..."). Each pitch becomes one
card, its paragraph kept verbatim as the card's core (``pitch``), with:

- ``thesis``: the dispatch's opening argument, the paragraphs before its first section;
- ``prediction``: its "My bet" (or "falsifiable") paragraph, verbatim, with ``by`` when
  the paragraph names a quarter, a month, a year or a window in months;
- ``who``: only when the pitch says who buys ("The buyer is ...");
- ``dispatch``: id, title, slug, date, strategy and cluster ids, and ``lineages``: the
  archive themes those clusters were at the time (``importers.lineage_at``).

**Citations.** The dispatch's inline links are its evidence. Each is matched by canonical
URL to an observation in the library (the imported archive); a match is the
verification, recorded as ``verified: "url_match"``, and the claim is the dispatch's own
sentence around the link. Links that match nothing are kept as plain ``links``. A card
with fewer than ``MIN_SUPPORTED`` matched citations is stored ``unsupported``, as the card
writer stores one; nothing here relaxes that.

Dispatch cards are written to ``ideas`` with ``origin`` ``dispatch`` and no score (a
dispatch is not rated). They are not strike candidates: importing an archive interrupts
nobody. Writing them is idempotent per dispatch and pitch kind.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from .. import library
from ..importers import ARCHIVE, latest_themes, lineage_at
from ..sources import canonical_url
from ..store import Store, iso, utcnow
from ..stored import runs as stored_runs
from ..stored.cards import Card, Dropped, InputIds
from .cards import MIN_SUPPORTED, citations, evidence_snapshot, insert_card

DISPATCH_CARD_VERSION = "dispatch-1"
ORIGIN = "dispatch"
KINDS = ("oss", "commercial", "founder")
PUBLIC_URL = "https://example.com/blog/{slug}"
THESIS_MAX_CHARS = 1500
CLAIM_MAX_CHARS = 400
TITLE_MAX_CHARS = 110

_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_BOLD_LEAD = re.compile(r"^\*\*([^*]+?)\*\*\s*")
_KIND_WORD = re.compile(r"^(?:an?\s+|the\s+|for\s+)?(oss|open[- ]source|commercial|founder)\b",
                        re.I)
_PITCH_NOUN = re.compile(r"\b(pitch|idea|project|play|opportunity|move)\b", re.I)
# Where a prose lead ends: "OSS project worth starting this week: ...", "Founder pitch.
# The gap ...", "The OSS play here is ...".
_LEAD_END = re.compile(r"[:.]\s|\s(?:here\s+)?is\s")
_PREDICTION = re.compile(r"^(my bet|the bet|a bet|one falsifiable|prediction|one prediction|"
                         r"a falsifiable)", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]?\s+(?=[A-Z0-9\"'(\[])")
_FOOTER = re.compile(r"^This article was generated from the \[Parallax", re.I)
_CLAUSE = re.compile(r"\s(?:that|which|who|so that)\s|:\s|;\s|\s[-—–]\s")
# "The buyer is ...", "Buyers: ...", "The customer is ...", "Customers are ...",
# "Customers: ..." (not "The customers are trapped", which refers back to customers already
# named and says what they are, not who they are).
_BUYER = re.compile(r"^(?:(?:the\s+)?buyers?(?:\s+(?:is|are)\s+|\s*:\s*)"
                    r"|(?:the\s+)?customer\s+is\s+|customers\s+are\s+|customers?\s*:\s*)(.+)$",
                    re.I)
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
NUMBERS = {"three": 3, "six": 6, "nine": 9, "twelve": 12, "eighteen": 18, "twenty-four": 24,
           "thirty-six": 36}


def plain(markdown: str) -> str:
    """Markdown as text: links become their words, emphasis and code marks go."""
    text = _LINK.sub(lambda m: m.group(1), markdown)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])", r"\1", text)
    return " ".join(text.split())


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


@dataclass
class Pitch:
    kind: str
    label: str
    markdown: str
    labelled: bool

    @property
    def text(self) -> str:
        return plain(self.markdown)

    @property
    def body(self) -> str:
        """The pitch after its label."""
        text = self.text
        lead = plain(self.label)
        if text.startswith(lead):
            text = text[len(lead):].lstrip(" .:")
        return text[:1].upper() + text[1:] if text else text


@dataclass
class Dispatch:
    dispatch_id: str
    path: Path
    meta: dict
    title: str
    intro: list[str]
    paragraphs: list[str]
    pitches: list[Pitch] = field(default_factory=list)
    prediction: str | None = None
    problem: str | None = None

    @property
    def date(self) -> str:
        at = self.meta.get("generated_at") or self.meta.get("published_at")
        return str(at) if at else self.dispatch_id[:10]

    @property
    def provenance(self) -> dict:
        slug = self.meta.get("slug")
        return {
            "dispatch_id": self.dispatch_id, "title": self.title, "slug": slug,
            "url": PUBLIC_URL.format(slug=slug) if slug else None,
            "date": self.date[:10], "generated_at": self.date,
            "strategy": self.meta.get("strategy"),
            "cluster_ids": [str(c) for c in self.meta.get("cluster_ids") or []],
            "excerpt": self.meta.get("excerpt"),
            "file": f"dispatches/{self.path.name}",
        }


def _front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    _, head, body = text.split("---", 2)
    meta = yaml.safe_load(head) or {}
    for k, v in list(meta.items()):
        if isinstance(v, datetime | date):
            meta[k] = v.isoformat().replace("+00:00", "Z")
    return meta, body


def _blocks(body: str) -> list[str]:
    return [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]


def _pitch_kind(paragraph: str) -> tuple[str, str, bool] | None:
    """``(kind, label, labelled)`` when a paragraph opens a pitch; else None."""
    m = _BOLD_LEAD.match(paragraph)
    if m:
        k = _KIND_WORD.match(m.group(1).strip())
        if k:
            return _kind(k.group(1)), m.group(0).strip(), True
    text = plain(paragraph)
    end = _LEAD_END.search(text)
    lead = text[:end.start()] if end else text
    k = _KIND_WORD.match(lead)
    if k and len(lead) <= 70 and (_PITCH_NOUN.search(lead) or lead.lower() == "for commercial"):
        return _kind(k.group(1)), text[:end.end()].rstrip() if end else lead, False
    return None


def _kind(word: str) -> str:
    word = word.lower()
    return "oss" if word in ("oss", "open source", "open-source") else word


def parse(path: Path) -> Dispatch:
    """A dispatch file, with ``problem`` set when it does not have the three pitches."""
    meta, body = _front_matter(path.read_text(encoding="utf-8"))
    dispatch_id = str(meta.get("dispatch_id") or path.stem)
    blocks = [b for b in _blocks(body) if not _FOOTER.match(b)]
    title = str(meta.get("title") or "")
    if not title:
        heading = next((b for b in blocks if b.startswith("# ")), "")
        title = heading[2:].strip()
    d = Dispatch(dispatch_id, path, meta, title, [], [])
    if meta.get("schema_version") != 2:
        d.problem = (f"schema {meta.get('schema_version')}: a data dump of clusters, "
                     "no prose and no pitches")
        return d
    in_intro = True
    for b in blocks:
        if b.startswith("#"):
            if b.startswith("## "):
                in_intro = False
            continue
        d.paragraphs.append(b)
        if in_intro:
            d.intro.append(b)
    found = [(i, *k) for i, p in enumerate(d.paragraphs) if (k := _pitch_kind(p))]
    missing = [k for k in KINDS if k not in {f[1] for f in found}]
    if missing:
        d.problem = "no " + " and no ".join(f"{k} pitch" for k in missing)
        return d
    chosen: dict[str, tuple] = {}
    # The pitches close the article, in order: the last founder pitch, the last
    # commercial one before it, the last OSS one before that.
    limit = len(d.paragraphs)
    for kind in ("founder", "commercial", "oss"):
        hits = [f for f in found if f[1] == kind and f[0] < limit]
        if not hits:
            d.problem = "the three pitches are not in order (OSS, commercial, founder)"
            return d
        chosen[kind] = hits[-1]
        limit = hits[-1][0]
    if chosen["founder"][0] - chosen["oss"][0] > 4:
        d.problem = "the three pitches are not together at the end"
        return d
    d.pitches = [Pitch(k, chosen[k][2], d.paragraphs[chosen[k][0]], chosen[k][3]) for k in KINDS]
    first_pitch = chosen["oss"][0]
    bets = [p for p in d.paragraphs[:first_pitch]
            if _PREDICTION.match(plain(p)) or "falsifiable" in plain(p)[:160].lower()]
    d.prediction = bets[-1] if bets else None
    return d


def thesis(d: Dispatch) -> str:
    """The opening argument: the paragraphs before the first section, up to
    ``THESIS_MAX_CHARS`` (at least the first paragraph)."""
    out: list[str] = []
    for p in d.intro:
        text = plain(p)
        if out and len(" ".join(out)) + len(text) > THESIS_MAX_CHARS:
            break
        out.append(text)
    return "\n\n".join(out)


def prediction_by(text: str, written: str) -> str | None:
    """The date a prediction resolves by, when it names one; ISO, end of the period."""
    t = text.lower()
    m = re.search(r"\b(?:by|before)\s+(?:the\s+)?(?:end\s+of\s+)?q([1-4])\s+(\d{4})", t)
    if m:
        year, month = int(m.group(2)), int(m.group(1)) * 3
        return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    m = re.search(r"\b(?:by|before)\s+(?:the\s+)?(?:end\s+of\s+)?(" + "|".join(MONTHS)
                  + r")\s+(\d{4})", t)
    if m:
        year, month = int(m.group(2)), MONTHS[m.group(1)]
        return date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    m = re.search(r"\bby\s+(?:the\s+)?end\s+of\s+(\d{4})", t)
    if m:
        return f"{m.group(1)}-12-31"
    words = "|".join(NUMBERS)
    m = re.search(rf"\b(\d+|{words})(?:\s*(?:to|-)\s*(\d+|{words}))?[\s-]+months?\b", t)
    if m:
        months = _number(m.group(2) or m.group(1))
        start = date.fromisoformat(written[:10])
        year, month = divmod(start.month - 1 + months, 12)
        year, month = start.year + year, month + 1
        return date(year, month, min(start.day, calendar.monthrange(year, month)[1])).isoformat()
    return None


def _number(word: str) -> int:
    return int(word) if word.isdigit() else NUMBERS[word]


def title_of(p: Pitch) -> str:
    """The pitch's first clause: what it proposes, without how."""
    first = (sentences(p.body) or [p.body])[0].rstrip(".")
    if len(first) <= TITLE_MAX_CHARS:
        title = first
    else:
        # not right after a comma: ", MIT-licensed, that scores ..." still describes the thing
        cuts = [m.start() for m in _CLAUSE.finditer(first)
                if 25 <= m.start() <= TITLE_MAX_CHARS and first[m.start() - 1] != ","]
        title = first[:cuts[0]] if cuts else \
            first[:first.rfind(" ", 0, TITLE_MAX_CHARS)] + "…"
    return title.strip().rstrip(",;:")


def who_of(p: Pitch) -> str | None:
    """Who buys, when the pitch says so in a sentence of its own."""
    found = None
    for s in sentences(p.body):
        m = _BUYER.match(s)
        if m and not m.group(1).lower().startswith("not "):
            found = m.group(1).rstrip(".")
    return found[:300] if found else None


def link_claims(d: Dispatch) -> list[tuple[str, str]]:
    """``(url, claim)`` for each inline link, in order: the claim is the sentence of the
    dispatch the link sits in (its first appearance)."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for p in d.paragraphs:
        for s in sentences(_LINK.sub(lambda m: f"{m.group(1)}\x00{m.group(2)}\x01", p)):
            for url in re.findall(r"\x00([^\x01]+)\x01", s):
                if url in seen or not url.startswith(("http://", "https://")):
                    continue
                seen.add(url)
                claim = plain(re.sub(r"\x00[^\x01]+\x01", "", s))
                out.append((url, claim[:CLAIM_MAX_CHARS]))
    return out


@dataclass
class DispatchOutcome:
    dispatch_id: str
    title: str
    status: str
    detail: str = ""
    cards: list[dict] = field(default_factory=list)


@dataclass
class DispatchReport:
    run_uuid: str
    read: int = 0
    carded: int = 0
    lacking: int = 0
    already: int = 0
    cards: int = 0
    shown: int = 0
    unsupported: int = 0
    links: int = 0
    matched: int = 0
    skip_records: list[str] = field(default_factory=list)
    outcomes: list[DispatchOutcome] = field(default_factory=list)

    def summary(self) -> str:
        return json.dumps({k: v for k, v in self.__dict__.items()
                           if k not in ("run_uuid", "outcomes")})


def evidence_key(dispatch_id: str, kind: str) -> str:
    return hashlib.sha256(json.dumps([dispatch_id, kind, DISPATCH_CARD_VERSION]).encode()) \
        .hexdigest()


def _by_url(store: Store) -> dict[str, int]:
    """Canonical URL -> observation id, the oldest observation of each URL (the one the
    import keeps), archive rows and the library's own alike."""
    out: dict[str, int] = {}
    for r in store.query("SELECT id, source_url FROM observations WHERE source_url IS NOT NULL "
                         "AND NOT EXISTS (SELECT 1 FROM observations n WHERE n.supersedes = "
                         "observations.id) ORDER BY id"):
        url = canonical_url(r["source_url"])
        if url:
            out.setdefault(url, r["id"])
    return out


def card_for(d: Dispatch, p: Pitch, rows: list, claims: dict[int, str], links: list[dict],
             themes: list[dict]) -> dict:
    """A card in the card writer's shape (``cards.parse_card``), from one pitch."""
    lineages = []
    for cid in d.provenance["cluster_ids"]:
        t = lineage_at(themes, cid, d.date)
        lineages.append({"cluster_id": cid, "lineage_id": t["lineage_id"] if t else None,
                         "name": t["name"] if t else None})
    evidence = [{"n": n, "claim": claims[r["id"]], **evidence_snapshot(r),
                 "verified": "url_match"} for n, r in enumerate(rows, 1)]
    body = p.body
    card = {
        "title": title_of(p),
        "pattern": "",
        "where_now": "",
        "thesis": thesis(d),
        "who": who_of(p),
        "smallest_v1": "",
        "demand": {"statement": None, "evidence": [], "supported": 0},
        "evidence": evidence,
        "prediction": {"statement": plain(d.prediction) if d.prediction else "",
                       "by": prediction_by(plain(d.prediction), d.date)
                       if d.prediction else None},
        "cheapest_test": "",
        "risks": "",
        "ratings": {},
        "one_liner": (sentences(body) or [body])[0],
        "pitch": p.markdown,
        "pitch_text": p.text,
        "pitch_kind": p.kind,
        "pitch_label": plain(p.label).rstrip(".:"),
        "dispatch": d.provenance,
        "lineages": lineages,
        "links": links,
        "why_selected": f"the {p.kind if p.kind != 'oss' else 'OSS'} pitch of your dispatch "
                        f"\"{d.title}\" ({d.date[:10]})",
    }
    card["citations"] = [{**c, "verified": "url_match"} for c in citations(card)]
    return card


def import_dispatches(store: Store, directory: Path, *, only: list[str] | None = None,
                      limit: int | None = None, now: datetime | None = None) -> DispatchReport:
    """Cards from every dispatch in ``directory`` (``only``: these ids; ``limit``: the
    newest N), after the archive's observations are imported."""
    report = DispatchReport(run_uuid=uuid.uuid4().hex)
    started = now or utcnow()
    skipped = directory / "skipped"
    if skipped.is_dir():
        report.skip_records = sorted(p.name for p in skipped.iterdir() if p.is_file())
    paths = sorted(directory.glob("*.md"), reverse=True)
    if only:
        paths = [p for p in paths if p.stem in set(only)]
    by_url = _by_url(store)
    themes = latest_themes(store, ARCHIVE)
    taken = 0
    for path in paths:
        d = parse(path)
        if limit is not None and taken >= limit:
            break
        report.read += 1
        if d.problem:
            report.lacking += 1
            report.outcomes.append(DispatchOutcome(d.dispatch_id, d.title, "lacking", d.problem))
            continue
        taken += 1
        outcome = DispatchOutcome(d.dispatch_id, d.title, "carded")
        pairs = link_claims(d)
        matched_ids: list[int] = []
        claims: dict[int, str] = {}
        links: list[dict] = []
        for url, claim in pairs:
            oid = by_url.get(canonical_url(url))
            if oid is None:
                links.append({"url": url, "claim": claim})
            elif oid not in claims:
                claims[oid] = claim
                matched_ids.append(oid)
        report.links += len(pairs)
        report.matched += len(pairs) - len(links)
        by_id = library.observations_by_id(store, matched_ids)
        rows = [by_id[i] for i in matched_ids if i in by_id]
        new = 0
        for p in d.pitches:
            key = evidence_key(d.dispatch_id, p.kind)
            known = store.query_one("SELECT id, status FROM ideas WHERE evidence_key = ?", (key,))
            if known:
                outcome.cards.append({"kind": p.kind, "idea_id": known["id"],
                                      "status": known["status"], "new": False})
                continue
            card = card_for(d, p, rows, claims, links, themes)
            status = "shown" if len(card["evidence"]) >= MIN_SUPPORTED else "unsupported"
            idea_id = insert_card(store, {
                "snapshot_id": None, "fingerprint": f"dispatch:{d.dispatch_id}",
                "lineage_id": None, "origin": ORIGIN, "evidence_key": key,
                "input_ids": InputIds.write([r["id"] for r in rows]), "title": card["title"],
                "card": Card.write(card), "score": 0.0, "status": status,
                "dropped": Dropped.write([]), "gen_call_id": None, "verify_call_id": None,
                "run_uuid": report.run_uuid, "created_at": iso(now or utcnow()),
            })
            new += 1
            report.cards += 1
            report.shown += status == "shown"
            report.unsupported += status == "unsupported"
            outcome.cards.append({"kind": p.kind, "idea_id": idea_id, "status": status,
                                  "title": card["title"], "citations": len(card["evidence"]),
                                  "new": True})
        if new:
            report.carded += 1
        else:
            outcome.status = "already carded"
            report.already += 1
        report.outcomes.append(outcome)
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "dispatch_import", "status": "ok",
        "started_at": iso(started), "finished_at": iso(utcnow()),
        "summary": stored_runs.text_for("dispatch_import", report.summary()), "error": None,
    })
    return report


def dispatch_cards(store: Store) -> list[dict]:
    """Every dispatch card, newest dispatch first: id, status, kind, title and dispatch."""
    out = []
    for r in store.query("SELECT id, status, title, card FROM ideas WHERE origin = ? "
                         "ORDER BY id", (ORIGIN,)):
        card = Card.load(r["card"])
        out.append({"id": r["id"], "status": r["status"], "title": r["title"],
                    "kind": card.pitch_kind, "dispatch": card.dispatch or {},
                    "one_liner": card.one_liner})
    return sorted(out, key=lambda c: (c["dispatch"].get("date") or "", -c["id"]), reverse=True)
