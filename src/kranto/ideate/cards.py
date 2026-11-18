"""Idea cards: selection by math, generation by a model, citations verified.

Selection never asks a model. Candidates come from the latest map, in order:

1. rising: cross-source lineages that entered a burst state this snapshot
   (Kleinberg's two-state model over new arrivals) with more arrivals than
   the previous per-source rates explain (BH-corrected q < 0.05). Parallax's
   phase-4 artifact checks carry over: arrivals as shares of all arrivals,
   not counts; a per-source baseline; no single-source dominance.
2. bridging: clusters drawing substantially on sources of two or more
   topics, which is where cross-pollination shows up.
3. cross-source: clusters no single source dominates, by mean signal.

A run is refused when the map has not changed since the last run, and a
candidate is skipped when a card was already written from exactly the same
evidence: re-framing the same observations is how Parallax's weekly
dispatches went stale.

Generation (tier 2) writes one card or declines. Every citation must name an
observation that was in the prompt, and a verification call (tier 1) checks
each cited claim against the observation's text. Unsupported claims are
dropped and recorded; a card left with fewer than two supported citations is
kept but marked ``unsupported`` and hidden by default. The five ratings mirror
VISION's fitness terms and are multiplied in code, like the judge's.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .. import activity, library, notify, prompts, stories
from ..config import MAX_TOKENS
from ..grades import add_grade
from ..intern import extract_json_object
from ..llm import BudgetExceeded, FatalLLMError, LLMClient, LLMError, Paused
from ..map import read as map_read
from ..sources import safe_url
from ..store import Store, iso, utcnow
from ..stored import runs as stored_runs
from ..stored.cards import Card, Dropped, InputIds, Shares
from ..tick import RunLocked, run_lock

RATINGS = ("pattern_strength", "precondition_presence", "execution_gap",
           "demand_validation", "test_cheapness")
EVIDENCE_SIZE = 10
SUMMARY_CHARS = 400
WHY_CHARS = 200
MIN_SUPPORTED = 2
# demand_validation above this must be shown by the observations it cites:
# every strike in the QA sweep rested on a demand rating its own reason called
# unsupported.
DEMAND_UNCHECKED_MAX = 0.3
# A lineage is not carded again within this many days, even when its evidence set
# shifted with the map; the same idea was shown twice otherwise.
RECARD_AFTER_DAYS = 7
BRIDGE_MIN_TOPIC_SHARE = 0.2
# Evidence from this many days before the snapshot is offered to the card model first.
RECENT_DAYS = 90


@dataclass(frozen=True)
class Candidate:
    origin: str
    lineage_id: str
    cluster: int
    why_selected: str
    observation_ids: list[int]
    subject: str = ""            # the cluster's name (or keywords): the prior-art search


@dataclass
class IdeasReport:
    run_uuid: str
    status: str = "ok"
    error: str | None = None
    fingerprint: str | None = None
    candidates: int = 0
    already_carded: int = 0
    shown: int = 0
    unsupported: int = 0
    declined: int = 0
    malformed: int = 0
    idea_ids: list[int] = field(default_factory=list)
    # the themes the owner's grades left out of this run: ``{lineage_id, name,
    # taste, why}``, each at or under ``grading.theme_skip_below``
    taste_skipped: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        return json.dumps({k: v for k, v in self.__dict__.items()
                           if k not in ("run_uuid", "status", "error")})


# Completion budgets. The tier-2 model reasons before it answers: in the
# 2026-09-25 QA runs a card used up to 3,932 completion tokens, 2,531 of them
# reasoning, and every card call at 1500 was cut off. Unused tokens cost
# nothing, so the cap only has to be comfortably above what a reply needs.
CARD_MAX_TOKENS = MAX_TOKENS["card"]
# Citation checks run on the tier-2 model. Re-run on the QA sweep's 37 graded
# claims: tier 1 passed 5 of 13 claims that overreach materially (2 of 13 good claims
# failed); tier 2 passed 3 of 13 (3 good claims failed), at about $0.009 a card.
# Its replies used at most 1,244 tokens.
VERIFY_TIER = "reason"
VERIFY_MAX_TOKENS = MAX_TOKENS["verify"]


# -- selection -------------------------------------------------------------------


def _evidence(store: Store, snapshot: Any, cluster: dict[str, Any],
              archive: bool = False) -> list[int]:
    """Representatives first, then high-signal members spread across sources; one
    observation per story, so a crosspost or a deep dive's child is not cited as
    a second voice. Observations from the last ``RECENT_DAYS`` before the
    snapshot are taken before older ones (#95: a card's one surviving citation was
    two years old, which says nothing about "why now"). An imported archive's
    observations are left out unless ``archive`` (``parallax.card_evidence``)."""
    members = store.query(
        "SELECT o.id, o.signal, o.source_id, o.item_id, "
        "COALESCE(o.item_published_at, o.created_at) AS at FROM snapshot_points p "
        "JOIN observations o ON o.id = p.observation_id "
        "WHERE p.snapshot_id = ? AND p.cluster = ? AND (? OR COALESCE(o.admitted_by, '') != ?) "
        "ORDER BY o.signal DESC, o.id",
        (snapshot["id"], cluster["cluster"], int(archive), library.IMPORTED),
    )
    story_of = stories.story_keys(store, members)
    since = iso(datetime.fromisoformat(snapshot["created_at"]) - timedelta(days=RECENT_DAYS))
    recent = {m["id"] for m in members if (m["at"] or "") >= since}
    allowed = {m["id"] for m in members}
    chosen: list[int] = []
    told: set[str] = set()

    def take(oid: int) -> None:
        key = story_of.get(oid, f"obs:{oid}")
        if oid not in chosen and key not in told:
            chosen.append(oid)
            told.add(key)

    for fresh in (True, False):
        for oid in cluster["representatives"][:3]:
            if oid in allowed and (oid in recent) == fresh:
                take(oid)
        by_source: dict[int, list[int]] = {}
        for m in members:
            if (m["id"] in recent) == fresh:
                by_source.setdefault(m["source_id"], []).append(m["id"])
        queues = list(by_source.values())
        while len(chosen) < EVIDENCE_SIZE and any(queues):
            for q in queues:
                while q and (q[0] in chosen or story_of[q[0]] in told):
                    q.pop(0)
                if q and len(chosen) < EVIDENCE_SIZE:
                    take(q.pop(0))
    return chosen[:EVIDENCE_SIZE]


def _project_cluster(c: dict[str, Any], project_names: set[str]) -> bool:
    """Whether project topics (migration 23) hold at least half of a cluster's topic mix."""
    total = sum(c["topic_mix"].values())
    mine = sum(n for t, n in c["topic_mix"].items() if t in project_names)
    return bool(total) and mine * 2 >= total


def candidates(store: Store, snapshot: Any, archive: bool = False,
               project_topics: str = "skip") -> list[Candidate]:
    """``archive``: whether an imported archive's observations may be evidence. A cluster
    left with fewer than ``MIN_SUPPORTED`` observations to cite (one made of the archive,
    say) is not a candidate: no card written from it could be shown.

    ``project_topics`` (``ideas.project_topics``): with ``skip``, a cluster that is mostly
    project topics' is not a candidate, and a project topic does not count towards a
    bridge; with ``cards``, they are like any other. With no project topic, either gives
    the same candidates."""
    rows = map_read.clusters(store, snapshot["id"])
    project_names: set[str] = set()
    if project_topics == "skip":
        # the map's topic mix is by name: a name a user topic also has stays the user's
        kinds: dict[str, set[str]] = {}
        for t, _, _ in library.topics_with_status(store):
            kinds.setdefault(t.name, set()).add(t.kind)
        project_names = {name for name, k in kinds.items() if k == {"project"}}
    if project_names:
        rows = [c for c in rows if not _project_cluster(c, project_names)]
    out: list[Candidate] = []
    seen: set[int] = set()

    def add(origin: str, c: dict[str, Any], why: str) -> None:
        if c["cluster"] in seen:
            return
        seen.add(c["cluster"])
        evidence = _evidence(store, snapshot, c, archive)
        if len(evidence) >= MIN_SUPPORTED:
            subject = c.get("name") or ", ".join((c.get("keywords") or [])[:4])
            out.append(Candidate(origin, c["lineage_id"], c["cluster"], why, evidence,
                                 " ".join(str(subject or "").split())[:120]))

    rising = [c for c in rows if c["rising"]]
    for c in sorted(rising, key=lambda c: c["movement"]["q_value"]):
        m = c["movement"]
        add("rising", c, (
            f"{m['new_in_cluster']} of the {m['new_total']} observations added since "
            f"{m['since'][:10]} landed in their theme, where the sources that were running "
            f"explain about {m['expected_new']:.1f}; the theme has entered a burst, and no "
            "single source dominates it."))

    for c in rows:
        total = sum(c["topic_mix"].values())
        strong = [t for t, n in c["topic_mix"].items()
                  if total and n / total >= BRIDGE_MIN_TOPIC_SHARE and t not in project_names]
        # Distinct stories, not observations; maps from before count observations.
        if len(strong) >= 2 and (c.get("stories") or c["size"]) >= 10:
            add("bridging", c, (
                "they sit together in meaning although they come from sources watched for "
                f"different topics ({', '.join(sorted(strong))}): the same shape turning up "
                "in unrelated places."))

    cross = [c for c in rows if c["cross_source"]]
    signal = {r["cluster"]: r["s"] for r in store.query(
        "SELECT p.cluster, AVG(o.signal) AS s FROM snapshot_points p JOIN observations o "
        "ON o.id = p.observation_id WHERE p.snapshot_id = ? GROUP BY p.cluster",
        (snapshot["id"],))}
    for c in sorted(cross, key=lambda c: -signal.get(c["cluster"], 0)):
        add("cross_source", c, (
            f"they form a group of "
            f"{c['stories'] if c.get('stories') else c['size']} "
            f"{'distinct stories' if c.get('stories') else 'observations'} drawn from "
            f"{len(c['source_mix'])} sources, none supplying more than 70%, and no single "
            "origin either: a theme that independent sources converged on."))
    return out


def by_taste(store: Store, snapshot: Any, cands: list[Candidate], grading: Any = None,
             now: datetime | None = None) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """The candidates in the owner's order: each theme's ``taste`` against the
    graded cards and evidence, highest first, today's order among equals; a theme at or under
    ``grading.theme_skip_below`` is left out of this run, with why (``{lineage_id, name, taste,
    why}``). No grade: today's order, nothing left out. No model: ``taste`` is arithmetic."""
    from .. import taste

    cfg = taste.settings(grading)
    tastes = taste.theme_tastes(store, snapshot["id"], now, cfg)
    scored = [(tastes.get(c.lineage_id, (0.0, []))[0], n, c) for n, c in enumerate(cands)]
    kept, skipped = [], []
    for t, _, c in sorted(scored, key=lambda x: (-x[0], x[1])):
        if t <= cfg.theme_skip_below:
            parts = tastes[c.lineage_id][1]
            skipped.append({"lineage_id": c.lineage_id, "name": c.subject, "taste": t,
                            "why": "not carded: " + taste.line(None, parts, cfg).removeprefix(
                                "ranked down: ")})
        else:
            kept.append(c)
    return kept, skipped


def evidence_key(ids: list[int], prompt_version: str) -> str:
    return hashlib.sha256(json.dumps([sorted(ids), prompt_version]).encode()).hexdigest()


# -- generation ------------------------------------------------------------------


def _line(r: Any) -> str:
    """One observation as the card model sees it; verify sees exactly the same text."""
    when = (r["item_published_at"] or r["created_at"] or "")[:10]
    summary = " ".join(r["summary"].split())[:SUMMARY_CHARS]
    why = " ".join(r["why_it_matters"].split())[:WHY_CHARS]
    return (f"{r['source_label'] or 'unknown source'}, {when}: {summary} "
            f"(why it mattered: {why})")


def _render(rows: list[Any]) -> str:
    return "\n".join(f"[{i}] {_line(r)}" for i, r in enumerate(rows, 1))


def parse_card(text: str, n_inputs: int) -> tuple[str, dict[str, Any] | None]:
    """Return ("declined" | "malformed" | "ok", card)."""
    obj = extract_json_object(text)
    if obj is None or "card" not in obj:
        return "malformed", None
    card = obj["card"]
    if card is None:
        return "declined", None
    if not isinstance(card, dict):
        return "malformed", None
    title = str(card.get("title") or "").strip()
    got = card.get("evidence")
    evidence: list[Any] = got if isinstance(got, list) else []
    got = card.get("ratings")
    ratings_in: dict[str, Any] = got if isinstance(got, dict) else {}
    ratings: dict[str, dict[str, Any]] = {}
    for key in RATINGS:
        raw = ratings_in.get(key)
        cites: list[int] = []
        if isinstance(raw, list):
            value, reason = (raw[0] if raw else None), (raw[1] if len(raw) > 1 else "")
            if len(raw) > 2 and isinstance(raw[2], list):
                cites = [n for n in raw[2] if isinstance(n, int) and not isinstance(n, bool)]
        else:
            value, reason = raw, ""
        if value is None:
            return "malformed", None
        try:
            ratings[key] = {"value": max(0.0, min(1.0, float(value))), "reason": str(reason)}
        except (TypeError, ValueError):
            return "malformed", None
        if cites:
            ratings[key]["cites"] = cites
    if not title or not evidence:
        return "malformed", None
    got = card.get("prior_art")
    prior_in: list[Any] = got if isinstance(got, list) else []
    prior = [{"result": " ".join(str(e.get("result") or "").strip("[] ").lower().split()),
              "what": str(e.get("what") or "").strip()[:300]}
             for e in prior_in
             if isinstance(e, dict) and str(e.get("result") or "").strip()][:12]
    got = card.get("demand")
    demand_in: dict[str, Any] = got if isinstance(got, dict) else {}
    got = demand_in.get("evidence")
    demand_list: list[Any] = got if isinstance(got, list) else []
    got = card.get("prediction")
    prediction: dict[str, Any] = got if isinstance(got, dict) else {}
    by: str | None = str(prediction.get("by") or "")
    try:
        by = date.fromisoformat(by or "").isoformat()
    except ValueError:
        by = None
    return "ok", {
        "title": title[:120],
        "pattern": str(card.get("pattern") or ""),
        "where_now": str(card.get("where_now") or ""),
        "thesis": str(card.get("thesis") or ""),
        "who": _text_or_none(card.get("who")),
        "smallest_v1": str(card.get("smallest_v1") or "").strip(),
        "demand": {"statement": _text_or_none(demand_in.get("statement")),
                   "evidence": _claims(demand_list)},
        "evidence": _claims(evidence),
        "prediction": {"statement": str(prediction.get("statement") or ""), "by": by},
        "cheapest_test": str(card.get("cheapest_test") or ""),
        "risks": str(card.get("risks") or ""),
        "ratings": ratings,
        "prior_art_cited": prior,
        **_v1_fields(card),
    }


# A card prompt that writes the insight first (the page the card v1) adds these. Kept only when
# the reply has them, so a card from an earlier prompt stores what it stored before.
V1_TEXT = ("insight", "gap", "moment", "mechanism")


def _v1_fields(card: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: v for k in V1_TEXT if (v := _text_or_none(card.get(k)))}
    existing = []
    for e in (got if isinstance(got := card.get("existing"), list) else []):
        if isinstance(e, dict) and _text_or_none(e.get("name")):
            n = e.get("n")
            existing.append({"n": n if isinstance(n, int) and not isinstance(n, bool) else None,
                             "name": _text_or_none(e.get("name")),
                             "covers": _text_or_none(e.get("covers"))})
    if existing:
        out["existing"] = existing
    notes = _editor_notes(card.get("editor_notes"))
    if notes:
        out["editor_notes"] = notes
    return out


# The card prompt made for the weekly editor (the page's editor reads cards as candidates) adds
# an ``editor_notes`` block: what kind of idea it is, what exists, who could absorb it, its
# facets, where it would sit and where its people gather. Not citations: kept as written,
# cleaned of empty values, and only when the reply has it.
EDITOR_TEXT = ("kind", "gap", "absorber", "integration_point", "channel")


def _editor_notes(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {k: v for k in EDITOR_TEXT if (v := _text_or_none(raw.get(k)))}
    facets = [f for f in (_text_or_none(x) for x in raw.get("facets") or []
                          if isinstance(x, (str, int, float))) if f] \
        if isinstance(raw.get("facets"), list) else []
    if facets:
        out["facets"] = facets[:12]
    existing = _v1_fields({"existing": raw.get("existing")}).get("existing")
    if existing:
        out["existing"] = existing
    return out or None


def _claims(raw: list[Any]) -> list[dict[str, Any]]:
    out = []
    for e in raw:
        if isinstance(e, dict) and str(e.get("claim") or "").strip():
            raw_n = e.get("n")
            try:
                n = int(raw_n) if raw_n is not None else 0
            except (TypeError, ValueError):
                n = 0
            out.append({"n": n, "claim": str(e["claim"]).strip()})
    return out


def _text_or_none(value: object) -> str | None:
    """A free-text field the model may leave null; "null", "none" and blanks count as null."""
    text = str(value).strip() if value is not None else ""
    return None if text.lower() in ("", "null", "none", "n/a") else text


# -- prior art from live search --------------------------------------------

PRIOR_ART_N = 5
# A claim that nothing like this exists: kept only with a recent dated result that shows it.
NOVELTY = re.compile(
    r"(?i)\b(?:nothing(?: else)? (?:does|offers|provides|covers|handles) (?:this|that|it)"
    r"|no (?:existing|other|current) (?:tools?|products?|projects?|services?|solutions?|"
    r"librar(?:y|ies))|no one (?:has|is|offers|does|builds)|(?:is|be|would be) the first\b"
    r"|first[- ]ever|unlike anything|does(?:n't| not) (?:yet )?exist(?: yet)?"
    r"|no tool (?:does|exists|offers)|no competitors?|nobody (?:has|offers|does))")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def prior_art_search(searcher: Any, cand: Candidate) -> Any:
    """One live search on what the cluster is about, before the card is written: the web
    backend and GitHub, five results each, any date (prior art can be old)."""
    from .. import websearch
    if searcher is None:
        return websearch.Results(cand.subject, (), None, iso(utcnow()), note=websearch.NO_SEARCH)
    return searcher.search(cand.subject or cand.why_selected[:120], kind="code",
                           n=PRIOR_ART_N)


def prior_art_text(results: Any, weeks: int) -> str:
    """The card prompt's ``{prior_art}``: the dated results and the rules for them, or the
    sentence that there was no search."""
    if not results.live:
        return ("No prior-art search ran (" + (results.note or "no live search") + "). Write "
                "\"no prior-art search\" in \"pattern\", leave \"prior_art\" empty, and make "
                "no claim that nothing does this.")
    return (str(results.block("Prior art, searched for what these observations are about"))
            + "\n"
            "Rules for prior art:\n"
            "- \"pattern\" names where the pattern already works by citing a result ([exa 2]) "
            "or an observation ([3]).\n"
            "- The execution_gap rating's reason cites the results that show current attempts, "
            "or says the results show none.\n"
            "- List in \"prior_art\" what the results show already exists, each with its label "
            "and what it does; an empty list when they show nothing that does it.\n"
            "- A claim that nothing does this, that this would be the first, or that no tool "
            f"exists must cite a result dated in the last {weeks} weeks that shows the gap; "
            "without one, do not make it: such a sentence is removed from the card.")


def apply_prior_art(card: dict[str, Any], results: Any, now: datetime, weeks: int) -> None:
    """Store the search on the card (``prior_art``: when, which backends, the hits, and what
    the card says exists, each checked against the block) and drop every novelty claim that
    cites no result dated in the last ``weeks`` weeks (``novelty_dropped``)."""
    from .. import websearch
    cited = card.pop("prior_art_cited", [])
    existing = []
    for e in cited:
        hit = websearch.hit_for(results, e["result"]) if results.live else None
        if hit is not None:
            existing.append({"label": e["result"], "url": hit.url, "title": hit.title[:200],
                             "date": hit.date, "what": e["what"]})
    card["prior_art"] = {
        "live": results.live, "searched_at": results.searched_at, "query": results.query,
        "backends": list(results.labels or results.backends), "note": results.note,
        "results": len(results.hits),
        "hits": [{"label": label, "url": h.url, "title": h.title[:200], "date": h.date}
                 for label, h in results.numbered()][:2 * PRIOR_ART_N],
        "existing": existing}
    recent = (now - timedelta(weeks=weeks)).date().isoformat()
    dropped = []

    def keep(sentence: str) -> bool:
        if not NOVELTY.search(sentence):
            return True
        dated = [h for h in (websearch.hit_for(results, label)
                             for label in websearch.cited(results, sentence)) if h]
        return any(h.date and h.date >= recent for h in dated)

    for name in ("thesis", "pattern", "where_now"):
        parts = _SENTENCE.split(card.get(name) or "")
        kept = [p for p in parts if keep(p)]
        for p in parts:
            if p not in kept:
                dropped.append({"field": name, "sentence": p[:400],
                                "reason": "a novelty claim with no prior-art result dated in "
                                          f"the last {weeks} weeks"})
        card[name] = " ".join(kept)
    for key, rating in card["ratings"].items():
        if NOVELTY.search(rating.get("reason") or "") and not keep(rating["reason"]):
            dropped.append({"field": f"ratings.{key}", "sentence": rating["reason"][:400],
                            "reason": "a novelty claim with no prior-art result dated in the "
                                      f"last {weeks} weeks"})
            rating["reason"] = "(a novelty claim was removed: no dated prior-art result shows it)"
    if dropped:
        card["novelty_dropped"] = dropped


def score(card: dict[str, Any]) -> float:
    product = 1.0
    for key in RATINGS:
        product *= card["ratings"][key]["value"]
    return product


def _verdicts(text: str, n: int) -> list[tuple[bool, str]] | None:
    """(supported, unsupported part) per claim, or None if the reply is unusable."""
    obj = extract_json_object(text) or {}
    raw = obj.get("verdicts")
    if isinstance(raw, list) and len(raw) == n and all(isinstance(v, dict) for v in raw):
        return [(v.get("supported") is True, str(v.get("unsupported") or "").strip())
                for v in raw]
    raw = obj.get("supported")  # the reply format before #42
    if isinstance(raw, list) and len(raw) == n:
        return [(v is True, "") for v in raw]
    return None


def verify(llm: LLMClient, card: dict[str, Any], rows: list[Any],
           run_uuid: str) -> tuple[list[Any], list[Any], int | None]:
    """Split evidence into (supported, dropped), check the demand field's citations,
    and hold demand_validation to its evidence.

    Each claim is checked against exactly the text the card model saw for the cited
    observation. Unresolvable citations never reach the model. The demand field's
    citations are checked like evidence; the supported ones are left in
    ``card["demand"]["evidence"]`` and the others are dropped with ``"for": "demand"``.
    A demand rating above ``DEMAND_UNCHECKED_MAX`` needs at least one supported
    demand citation; cards written before #96 cite them in the rating, and those
    are checked as before. Otherwise the rating is capped and the card records why.
    """
    dropped, checkable = [], []
    for e in card["evidence"]:
        if 1 <= e["n"] <= len(rows):
            checkable.append(e)
        else:
            dropped.append({**e, "reason": "cites an observation that was not provided"})
    demand = card["ratings"]["demand_validation"]
    field = card.setdefault("demand", {"statement": None, "evidence": []})
    demand_claims = []
    for e in field["evidence"]:
        if 1 <= e["n"] <= len(rows):
            demand_claims.append(e)
        else:
            dropped.append({**e, "for": "demand",
                            "reason": "cites an observation that was not provided"})
    field["evidence"] = []
    if not demand_claims and demand["value"] > DEMAND_UNCHECKED_MAX:
        cites = [n for n in demand.get("cites", []) if 1 <= n <= len(rows)][:3]
        demand_claims = [{"n": n, "claim": f"People are asking for or paying for this: "
                                           f"{demand['reason']}", "rating": True}
                         for n in cites]
        if not cites:
            _cap_demand(card, "it cites no observation showing people asking or paying")
    claims = checkable + demand_claims
    if not claims:
        return [], dropped, None
    prompt = prompts.load("verify")
    pairs = "\n\n".join(
        f"Claim {i}: {e['claim']}\nObservation: {_line(rows[e['n'] - 1])}"
        for i, e in enumerate(claims, 1)
    )
    completion = llm.complete(
        tier=VERIFY_TIER, purpose="verify", prompt_version=prompt.version, run_uuid=run_uuid,
        messages=[{"role": "user", "content": prompt.render(pairs=pairs)}],
        max_tokens=llm.max_tokens("verify"), temperature=0.0,
    )
    verdicts = _verdicts(completion.text, len(claims))
    if verdicts is None:
        if demand["value"] > DEMAND_UNCHECKED_MAX and demand_claims:
            _cap_demand(card, "its evidence could not be checked")
        unusable = "verification reply was unusable"
        return [], dropped + [{**e, "reason": unusable} for e in checkable] + [
            {**e, "for": "demand", "reason": unusable} for e in demand_claims
            if not e.get("rating")], completion.call_id
    supported = []
    reason = "the observation does not support the claim"
    for e, (ok, part) in zip(checkable, verdicts, strict=False):
        if ok:
            supported.append(e)
        else:
            dropped.append({**e, "reason": f"{reason}: {part}" if part else reason})
    demand_ok = verdicts[len(checkable):]
    for e, (ok, part) in zip(demand_claims, demand_ok, strict=False):
        if e.get("rating"):
            continue
        if ok:
            field["evidence"].append(e)
        else:
            dropped.append({**e, "for": "demand",
                            "reason": f"{reason}: {part}" if part else reason})
    if demand["value"] > DEMAND_UNCHECKED_MAX and demand_claims \
            and not any(ok for ok, _ in demand_ok):
        _cap_demand(card, "the observations it cites do not show people asking or paying")
    return supported, dropped, completion.call_id


def _cap_demand(card: dict[str, Any], why: str) -> None:
    rating = card["ratings"]["demand_validation"]
    card["ratings"]["demand_validation"] = {
        **rating, "value": DEMAND_UNCHECKED_MAX, "rated": rating["value"],
        "reason": f"capped at {DEMAND_UNCHECKED_MAX}: {why} (rated {rating['value']:.2f}: "
                  f"{rating['reason']})",
    }


def generate_ideas(
    store: Store,
    llm: LLMClient,
    *,
    max_cards: int = 4,
    force: bool = False,
    clock: Callable[[], datetime] = utcnow,
    archive_evidence: bool = False,
    project_topics: str = "skip",
    searcher: Any = None,
    grading: Any = None,
) -> IdeasReport:
    """``archive_evidence``: ``parallax.card_evidence``, whether an imported archive's
    observations may be cited. ``project_topics``: ``ideas.project_topics``. ``searcher``:
    live search for each card's prior art (``websearch``, caller ``cards``); None: every card
    says there was no prior-art search. ``grading``: the ``grading.*`` settings: the themes are
    carded in the owner's order and one their downvotes sank is left out (``by_taste``)."""
    report = IdeasReport(run_uuid=activity.run_uuid("ideas"))
    started = clock()
    lock = store.lock_path("ideas")
    try:
        # Two overlapping runs carded the same evidence twice.
        with run_lock(lock) if lock else contextlib.nullcontext():
            _generate(store, llm, report, max_cards, force, clock, archive_evidence,
                      project_topics, searcher, grading)
    except RunLocked as exc:
        report.status, report.error = "skipped", str(exc)
    except (Paused, BudgetExceeded) as exc:
        report.status = "degraded" if report.idea_ids else "skipped"
        report.error = str(exc)
    except FatalLLMError as exc:
        report.status, report.error = "failed", str(exc)
    except ValueError as exc:
        report.status, report.error = "skipped", str(exc)
    except Exception as exc:  # recorded and alarmed, as ingest and snapshot do
        report.status, report.error = "failed", f"{type(exc).__name__}: {exc}"
    if report.status == "ok" and report.malformed:
        if report.declined or report.idea_ids:
            report.status = "degraded"
            report.error = f"{report.malformed} card calls returned no usable card"
        else:
            # Nothing usable came back. Failed runs are not consulted for the
            # map fingerprint, so the next scheduled run tries again.
            report.status = "failed"
            report.error = (f"all {report.malformed} card calls returned no usable card "
                            "(cut off at max_tokens or malformed)")
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "ideas", "status": report.status,
        "started_at": iso(started), "finished_at": iso(clock()),
        "summary": stored_runs.text_for("ideas", report.summary()), "error": report.error,
    })
    notify.alarm_for_run(store, kind="ideas", run_uuid=report.run_uuid,
                         status=report.status, error=report.error)
    return report


def _generate(store: Store, llm: LLMClient, report: IdeasReport, max_cards: int, force: bool,
              clock: Callable[[], datetime], archive_evidence: bool = False,
              project_topics: str = "skip", searcher: Any = None, grading: Any = None) -> None:
    snapshot = map_read.latest(store)
    if snapshot is None:
        raise ValueError("no map yet; take a snapshot first")
    last = store.query_one(
        "SELECT summary FROM runs WHERE kind = 'ideas' AND status IN ('ok', 'degraded') "
        "ORDER BY finished_at DESC, rowid DESC LIMIT 1")
    if last and stored_runs.IdeasSummary.load(last["summary"]).fingerprint \
            == snapshot["fingerprint"] \
            and not force:
        raise ValueError("the map has not changed since the last idea run")
    report.fingerprint = snapshot["fingerprint"]
    llm.check_can_spend()

    prompt = prompts.load("card")
    cands, report.taste_skipped = by_taste(
        store, snapshot, candidates(store, snapshot, archive_evidence, project_topics), grading,
        clock())
    report.candidates = len(cands)
    calls = 0  # max_cards bounds tier-2 calls, including ones that decline
    for cand in cands:
        if calls >= max_cards:
            break
        key = evidence_key(cand.observation_ids, prompt.version)
        if store.query_one("SELECT 1 FROM ideas WHERE evidence_key = ?", (key,)):
            report.already_carded += 1
            continue
        if cand.lineage_id and store.query_one(
                "SELECT 1 FROM ideas WHERE lineage_id = ? AND created_at >= ?",
                (cand.lineage_id, iso(clock() - timedelta(days=RECARD_AFTER_DAYS)))):
            report.already_carded += 1
            continue
        calls += 1          # counted against max_cards: a failed call was still paid for
        _card_one(store, llm, report, snapshot, cand, key, prompt, clock, searcher)


def _card_one(store: Store, llm: LLMClient, report: IdeasReport, snapshot: Any,
              cand: Candidate, key: str, prompt: Any, clock: Callable[[], datetime],
              searcher: Any = None) -> None:
    """One card written from one candidate: its call, its check and its row, counted in
    ``report`` (shown, unsupported, declined or malformed)."""
    by_id = library.observations_by_id(store, cand.observation_ids)
    rows = [by_id[i] for i in cand.observation_ids if i in by_id]
    prior = prior_art_search(searcher, cand)
    weeks = searcher.cfg.recent_weeks if searcher is not None else 12
    try:
        completion = llm.complete(
            tier="reason", purpose="card", prompt_version=prompt.version,
            run_uuid=report.run_uuid, max_tokens=llm.max_tokens("card"), temperature=0.4,
            messages=[{"role": "user", "content": prompt.render_keeping(
                "prior_art", why_selected=cand.why_selected,
                today=clock().date().isoformat(), observations=_render(rows),
                prior_art=prior_art_text(prior, weeks))}],
        )
    except (FatalLLMError, Paused, BudgetExceeded):
        raise
    except LLMError:
        report.malformed += 1
        return
    outcome, card = parse_card(completion.text, len(rows))
    if outcome == "declined":
        report.declined += 1
        return
    if outcome == "malformed":
        report.malformed += 1
        return
    assert card is not None                    # "ok": parse_card made one
    apply_prior_art(card, prior, clock(), weeks)
    try:
        supported, dropped, verify_call = verify(llm, card, rows, report.run_uuid)
    except (FatalLLMError, Paused, BudgetExceeded):
        raise
    except LLMError:
        supported, verify_call = [], None
        dropped = [{**e, "reason": "verification call failed"} for e in card["evidence"]]
        dropped += [{**e, "for": "demand", "reason": "verification call failed"}
                    for e in card["demand"]["evidence"]]
        card["demand"]["evidence"] = []
    card["evidence"] = [{**e, **evidence_snapshot(rows[e["n"] - 1])} for e in supported]
    demand = card["demand"]
    demand["evidence"] = [{**e, **evidence_snapshot(rows[e["n"] - 1])}
                          for e in demand["evidence"]]
    demand["supported"] = len(demand["evidence"])
    card["citations"] = citations(card)
    # Which prompt versions wrote and checked it (the owner's additions and overrides
    # get their own version; llm_calls has the same, through the two call ids).
    card["prompts"] = {"card": prompt.version, "verify": prompts.load("verify").version}
    status = "shown" if len(supported) >= MIN_SUPPORTED else "unsupported"
    # The card and its strike candidate commit together: a card stored
    # without its candidate is never reconsidered, because a rerun skips
    # evidence that is already carded.
    with store.tx():
        idea_id = _store_card(store, snapshot, cand, key, rows, card, dropped, status,
                              completion.call_id, verify_call, report, clock)
    report.idea_ids.append(idea_id)
    if status == "shown":
        report.shown += 1
    else:
        report.unsupported += 1


ASKED = "asked"


def card_theme(store: Store, llm: LLMClient, lineage_id: str, *,
               clock: Callable[[], datetime] = utcnow, archive_evidence: bool = False,
               searcher: Any = None, hint: str | None = None,
               story: str | None = None) -> IdeasReport:
    """One card on one theme of the latest map, on the owner's request (asked
    for on 2026-10-22): the theme's current evidence, outside the daily selection, one
    card call and its check (about $0.06). Under the same lock and budget as the daily run; the
    same evidence already carded is not carded again. Its run is recorded with kind ``ideas``
    and the fingerprint of the last daily run, so the daily run decides as it would have.

    Asked from a news story (Idea from this): ``hint`` (the article's own
    idea seed, or the story's headline) goes with the reason the card was asked for, as data
    the card may use or not; ``story`` (``brief:<id>:<item>``) is kept in the run's summary
    beside the cards it wrote, so the story names its card (``features.news.ideas``)."""
    report = IdeasReport(run_uuid=activity.run_uuid("ideas"))
    started = clock()
    lock = store.lock_path("ideas")
    try:
        with run_lock(lock) if lock else contextlib.nullcontext():
            snapshot = map_read.latest(store)
            if snapshot is None:
                raise ValueError("no map yet; take a snapshot first")
            c = next((c for c in map_read.clusters(store, snapshot["id"])
                      if c["lineage_id"] == lineage_id), None)
            if c is None:
                raise ValueError(f"no theme {lineage_id} on the latest map")
            evidence = _evidence(store, snapshot, c, archive_evidence)
            if len(evidence) < MIN_SUPPORTED:
                raise ValueError("the theme has too little evidence to cite for a card")
            llm.check_can_spend()
            prompt = prompts.load("card")
            name = " ".join(str(c.get("name") or ", ".join((c.get("keywords") or [])[:4])
                                ).split())[:120]
            why = f"the owner asked for a card on this theme ({name})."
            if hint:
                why += (" They asked from a news story; an idea it suggests (a hint, not a "
                        f"source): {' '.join(str(hint).split())[:300]}")
            cand = Candidate(ASKED, c["lineage_id"], c["cluster"], why, evidence, name)
            report.candidates = 1
            key = evidence_key(cand.observation_ids, prompt.version)
            if store.query_one("SELECT 1 FROM ideas WHERE evidence_key = ?", (key,)):
                report.already_carded += 1
            else:
                _card_one(store, llm, report, snapshot, cand, key, prompt, clock, searcher)
    except RunLocked as exc:
        report.status, report.error = "skipped", str(exc)
    except (Paused, BudgetExceeded) as exc:
        report.status, report.error = "skipped", str(exc)
    except FatalLLMError as exc:
        report.status, report.error = "failed", str(exc)
    except ValueError as exc:
        report.status, report.error = "skipped", str(exc)
    if report.status == "ok" and report.malformed:
        report.status, report.error = "failed", "the card call returned no usable card"
    last = store.query_one(
        "SELECT summary FROM runs WHERE kind = 'ideas' AND status IN ('ok', 'degraded') "
        "ORDER BY finished_at DESC, rowid DESC LIMIT 1")
    report.fingerprint = stored_runs.IdeasSummary.load(last["summary"]).fingerprint if last \
        else None
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "ideas", "status": report.status,
        "started_at": iso(started), "finished_at": iso(clock()),
        "summary": stored_runs.text_for("ideas", {**json.loads(report.summary()),
                                                  "asked": lineage_id,
                                                  **({"story": story} if story else {})}),
        "error": report.error,
    })
    return report


def evidence_snapshot(row: Any) -> dict[str, Any]:
    """What a card keeps of an observation it cites, so it stays readable after
    compaction removes the observation: the derived summary, never the
    source's own text."""
    return {
        "observation_id": row["id"], "summary": row["summary"],
        "source": row["source_label"],
        "observed_at": row["item_published_at"] or row["created_at"],
        "url": safe_url(row["source_url"]),
    }


def citations(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Every supported citation of a card, flat and machine-readable: what the
    pitch, the brief and a build's REPORT quote. It lives in the card, so it outlasts
    the observations, which are purged after their retention age."""
    out = []
    for role in ("evidence", "demand"):
        entries = card["evidence"] if role == "evidence" else card["demand"]["evidence"]
        for e in entries:
            out.append({"observation_id": e["observation_id"], "url": e.get("url"),
                        "date": (e.get("observed_at") or "")[:10] or None,
                        "observed_at": e.get("observed_at"), "claim": e["claim"],
                        "source": e.get("source"), "for": role})
    return out


def evidence_view(store: Store,
                  ideas: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    """Per (idea id, observation id): the cited observation as a card shows it.

    The live observation when it is still in the library; otherwise the card's
    own snapshot, or for cards written before snapshots existed, the one
    compaction recorded in ``evidence_snapshots``. ``compacted`` says which."""
    ids = [oid for i in ideas for oid in i["card"].cited_ids()]
    live = library.observations_by_id(store, ids)
    legacy = {}
    if ideas:
        marks = ",".join("?" * len(ideas))
        for r in store.query(f"SELECT * FROM evidence_snapshots WHERE idea_id IN ({marks}) "
                             "ORDER BY id", tuple(i["id"] for i in ideas)):
            legacy[(r["idea_id"], r["observation_id"])] = {
                "summary": r["summary"], "source": r["source_label"],
                "observed_at": r["observed_at"], "url": r["url"]}
    out = {}
    for i in ideas:
        for e in i["card"].evidence:
            oid = e.observation_id
            if oid is None:                   # no writer stores one; never indexed
                continue
            row = live.get(oid)
            if row is not None:
                view = {**evidence_snapshot(row), "compacted": False}
            elif e.summary is not None:
                view = {"summary": e.summary, "source": e.source, "observed_at": e.observed_at,
                        "url": e.url, "compacted": True}
            elif (i["id"], oid) in legacy:
                view = {**legacy[(i["id"], oid)], "compacted": True}
            else:
                view = {"summary": None, "source": None, "observed_at": None, "url": None,
                        "compacted": True}
            out[(i["id"], oid)] = view
    return out


def topic_fields(store: Store, card: Card) -> tuple[int | None, list[dict[str, Any]]]:
    """A card's topic and the shares its row shows, from the evidence it
    cites: a topic counts when a cited observation came from one of its sources (a source in
    two topics counts for both), by source id; a cited observation already compacted counts by
    the label it was cited with. ``shares`` is ``[{id, name, kind, n, share}]``, user topics
    first; the topic is the user topic with the largest share, None when there is none (a
    dispatch card's archive evidence, or a card of project topics only)."""
    ev = card.evidence
    if not ev:
        return None, []
    ids = card.cited_ids()
    by_obs = {}
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        by_obs.update({r["id"]: r["source_id"] for r in store.query(
            f"SELECT id, source_id FROM observations WHERE id IN ({','.join('?' * len(part))})",
            tuple(part))})
    by_label = {r["label"]: r["id"] for r in store.query(
        "SELECT id, label FROM sources ORDER BY id DESC")}
    linked: dict[int, set[int]] = {}
    for r in store.query("SELECT topic_id, source_id FROM topic_links"):
        linked.setdefault(r["source_id"], set()).add(r["topic_id"])
    counts: dict[int, int] = {}
    for e in ev:
        sid = (by_obs.get(e.observation_id) if e.observation_id is not None else None) \
            or by_label.get(e.source or "")
        for t in linked.get(sid, ()) if sid is not None else ():
            counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None, []
    marks = ",".join("?" * len(counts))
    topics = {r["id"]: r for r in store.query(
        f"SELECT id, name, kind FROM topics_now WHERE id IN ({marks})", tuple(counts))}
    shares = sorted(({"id": t, "name": topics[t]["name"], "kind": topics[t]["kind"], "n": n,
                      "share": round(n / len(ev), 4)} for t, n in counts.items() if t in topics),
                    key=lambda s: (s["kind"] != "user", -s["share"], s["name"]))
    user = [s for s in shares if s["kind"] == "user"]
    return (user[0]["id"] if user else None), shares


def citation_rows(card: Card) -> list[dict[str, Any]]:
    """One row per citation of a card (``idea_citations``): its evidence, then its demand's."""
    out = []
    demand = d.evidence if (d := card.demand_of()) else []
    for role, items in (("evidence", card.evidence), ("demand", demand)):
        for e in items:
            if e.observation_id is not None:
                out.append({"observation_id": e.observation_id, "n": e.n, "role": role})
    return out


def insert_card(store: Store, row: dict[str, Any]) -> int:
    """A card's row and its children (``idea_topics``, ``idea_citations``, migration 35),
    each written once, at the card's insert."""
    card = Card.load(row["card"])
    topic_id, shares = topic_fields(store, card)
    idea_id = store.insert("ideas", row)
    store.insert("idea_topics", {"idea_id": idea_id, "topic_id": topic_id,
                                 "shares": Shares.write(shares), "created_at": row["created_at"]})
    for c in citation_rows(card):
        store.insert("idea_citations", {"idea_id": idea_id, **c, "created_at": row["created_at"]})
    return idea_id


def card_topics(store: Store, idea_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Per card, its newest ``idea_topics`` row: ``{"topic_id", "shares"}``."""
    ids = sorted({int(i) for i in idea_ids})
    out: dict[int, dict[str, Any]] = {}
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        for r in store.query(
                "SELECT idea_id, topic_id, shares FROM idea_topics WHERE id IN (SELECT MAX(id) "
                f"FROM idea_topics WHERE idea_id IN ({','.join('?' * len(part))}) "
                "GROUP BY idea_id)", tuple(part)):
            out[int(r["idea_id"])] = {"topic_id": r["topic_id"],
                                      "shares": Shares.load(r["shares"]).items}
    return out


def ideas_of_topic(store: Store, topic_id: int) -> set[int]:
    """The cards with ``topic_id`` among their topics (any share): the cards whose topic it is
    (``idea_topics_topic``), and those it has a share of (their shares list)."""
    return {int(r["idea_id"]) for r in store.query(
        "SELECT t.idea_id FROM idea_topics t WHERE t.id IN (SELECT MAX(id) FROM idea_topics "
        "GROUP BY idea_id) AND (t.topic_id = ? OR EXISTS (SELECT 1 FROM json_each(t.shares) s "
        "WHERE json_extract(s.value, '$.id') = ?))", (int(topic_id), int(topic_id)))}


def cited_by(store: Store, observation_id: int) -> list[int]:
    """The cards that cite an observation, newest first (``idea_citations_obs``)."""
    return [int(r["idea_id"]) for r in store.query(
        "SELECT DISTINCT idea_id FROM idea_citations WHERE observation_id = ? "
        "ORDER BY idea_id DESC", (int(observation_id),))]


def _store_card(store: Store, snapshot: Any, cand: Candidate, key: str, rows: list[Any],
                card: dict[str, Any], dropped: list[dict[str, Any]], status: str,
                gen_call_id: int | None, verify_call: int | None, report: IdeasReport,
                clock: Callable[[], datetime]) -> int:
    idea_id = insert_card(store, {
        "snapshot_id": snapshot["id"], "fingerprint": snapshot["fingerprint"],
        "lineage_id": cand.lineage_id, "origin": cand.origin, "evidence_key": key,
        "input_ids": InputIds.write([r["id"] for r in rows]), "title": card["title"],
        "card": Card.write({**card, "why_selected": cand.why_selected}),
        "score": score(card), "status": status, "dropped": Dropped.write(dropped),
        "gen_call_id": gen_call_id, "verify_call_id": verify_call,
        "run_uuid": report.run_uuid, "created_at": iso(clock()),
    })
    if status == "shown":
        _record_candidate(store, idea_id, cand, card, key, report.run_uuid, clock())
    return idea_id


def _record_candidate(store: Store, idea_id: int, cand: Candidate, card: dict[str, Any], key: str,
                      run_uuid: str, now: datetime) -> int:
    """Every shown card is a strike candidate; the gate decides whether it interrupts.

    The subject is the card's lineage when it has one, the same subject a burst
    on that lineage uses, so one theme cannot strike twice inside the
    refractory period by arriving once as a burst and once as a card.
    """
    lines = [card["thesis"]]
    if card["cheapest_test"]:
        lines.append(f"Cheapest test: {card['cheapest_test']}")
    lines.append(f"Selected because {cand.why_selected}")
    return notify.record_candidate(
        store, origin="card",
        subject_key=f"lineage:{cand.lineage_id}" if cand.lineage_id else f"idea:{key}",
        score=score(card), title=f"Idea: {card['title']}", body="\n\n".join(lines),
        evidence_ids=[e["observation_id"] for e in card["evidence"]],
        detail={"idea_id": idea_id, "selection": cand.origin, "lineage_id": cand.lineage_id,
                "ratings": {k: v["value"] for k, v in card["ratings"].items()}},
        run_uuid=run_uuid, now=now,
    )


# -- reading and grading -----------------------------------------------------------


VERDICTS = ("useful", "not_useful")       # a wrong reading is a ▼ with its why


def grade(store: Store, idea_id: int, verdict: str, note: str | None = None) -> None:
    """Grade a card. Recorded in ``grades``; earlier verdicts stay in ``verdicts``."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}")
    add_grade(store, "idea", idea_id, verdict, note)


def facts(card: Card | Mapping[str, Any]) -> dict[str, int]:
    """What a card stands on, counted from its verified citations: ``cited`` (claims
    the check supported), ``asks`` (supported demand citations: someone asks for it) and
    ``sources`` (distinct sites among its citations). Its writer's own ratings are its
    reasons, never multiplied into a number."""
    from urllib.parse import urlsplit

    if not isinstance(card, Card):            # a build's own copy of a card (feedback)
        card = Card.from_dict(card)
    hosts = {urlsplit(str(c.get("url") or "")).hostname or "" for c in card.citations}
    hosts.discard("")
    return {"cited": len(card.evidence),
            "asks": len(d.evidence) if (d := card.demand_of()) else 0, "sources": len(hosts)}


def fact_words(f: dict[str, Any]) -> list[str]:
    """``["3 cited", "1 asks for it", "4 sources"]``: a card's facts as the owner reads them."""
    return [f"{f['cited']} cited", f"{f['asks']} {'asks' if f['asks'] == 1 else 'ask'} for it",
            f"{f['sources']} source{'' if f['sources'] == 1 else 's'}"]


def fact_order(d: dict[str, Any]) -> tuple[Any, ...]:
    """Cards in order of what they stand on: demand, then citations, then sites, newest first."""
    f = d.get("facts") or facts(d.get("card") or Card.empty())
    return (-f["asks"], -f["cited"], -f["sources"], -int(d["id"]))


def list_ideas(store: Store, *, include_unsupported: bool = False,
               ids: set[int] | None = None, now: datetime | None = None,
               grading: Any = None) -> list[dict[str, Any]]:
    """The cards (or those of ``ids``) in the owner's order (``taste.rank``, the
    cards graded useful first, then by what they resemble of the owner's grades, then
    ``fact_order``; those graded not useful last), each with its ``rank``, its owner's latest
    grade (``verdict``, through ``grades.latest``, the one reader of a grade: #9) and its
    ``facts``. ``score`` stays in the row and is no one's order. ``grading``: the
    ``grading.*`` settings (``GradingConfig``), the defaults when None."""
    from .. import grades, taste

    if ids is not None and not ids:
        return []
    only = f"WHERE i.id IN ({','.join(str(int(i)) for i in sorted(ids))})" if ids else ""
    rows = store.query(
        f"""
        SELECT i.*,
               (SELECT json_object('candidate_id', c.id, 'decided', d.id IS NOT NULL,
                                   'promoted', d.promoted, 'reason', d.reason,
                                   'threshold', d.threshold, 'message_id', d.message_id)
                FROM strike_candidates c LEFT JOIN strike_decisions d ON d.candidate_id = c.id
                WHERE c.origin = 'card' AND json_extract(c.detail, '$.idea_id') = i.id
                ORDER BY c.id DESC LIMIT 1) AS strike
        FROM ideas i {only} ORDER BY i.id DESC
        """
    )
    rows = [r for r in rows if r["status"] == "shown" or include_unsupported]
    latest = grades.latest(store, "idea", [r["id"] for r in rows])
    ranks = taste.rank(store, now, grading)
    out = []
    for r in rows:
        d = dict(r)
        d["card"] = Card.load(d["card"])            # the type, never the dict (stored.cards)
        d["dropped"] = Dropped.load(d["dropped"]).items
        d["strike"] = json.loads(d["strike"]) if d["strike"] else None
        d["verdict"] = (latest.get(str(d["id"])) or {}).get("grade")
        d["facts"] = facts(d["card"])
        d["rank"] = ranks.get(int(d["id"]))
        out.append(d)
    return sorted(out, key=lambda d: d["rank"].key if d["rank"] else (1, 0, *fact_order(d)))
