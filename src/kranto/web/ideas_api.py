"""Idea cards as JSON: what Kranto UI and the console read (PLAN.md 1(d), 2.5).

The page never opens the server's database (handover rule 4); it reads cards here.

| Method and path      | Does                                                        |
|----------------------|-------------------------------------------------------------|
| GET /api/ideas       | every card in the owner's order (``rank``); ``status``,     |
|                      | ``topic``, ``origin`` and ``kind`` (a pitch's) filters      |
| GET /api/ideas/{id}  | one card, with the tickets that rest on it (``tickets``)    |
| POST /api/ideas/{id}/outcome | an outcome on the card (``outcomes.py``): the kinds  |
|                      | Kranto still writes (``outcomes.WRITABLE``)                  |
| POST /api/ideas/{id}/later | {days?}: Later (``idea.later``): off the list for ``days``  |
|                      | (7; 0 brings it back), an ``outcomes`` row, never the loop's  |
| POST /api/themes/{lineage}/card | one card on that theme now, in the background       |
|                      | (``cards.card_theme``, the owner's D-1): 202, ``started``   |

Cards made from the owner's dispatches are listed only when asked for: ``origin=dispatch``
(those alone), ``origin=all`` (with the rest), or a ``kind``. A reader that does not know
them (an older UI) never sees a few hundred archive cards arrive.

Each card carries its text (title, thesis, pattern, ...), status, score, the owner's
latest grade (``list_ideas``'s query), its **rank** (``taste.rank``, ``{position, taste, line,
parts}``; ``position`` is its place among the shown cards, None on an
unsupported one; ``line`` the one line a row shows, "" when there is none; each part
``{weight, why, target, target_id, value, graded_at, title}``), #96's fields (``who``,
``smallest_v1``, ``demand``, ``citations``), the topics of its theme, its ``output_kind`` and
an ``embedding``.

- **#96's fields** are the card writer's. A card written before them has ``who`` None,
  ``smallest_v1`` "" and ``demand`` None, and its ``citations`` are built from its
  supported ``evidence`` (live observation, else the card's own snapshot), so every card
  has URL, date and claim per citation.
- **The insight fields** (``insight``, ``existing`` as ``[{n, name, covers}]``, ``gap``,
  ``moment``, ``mechanism``) are written by a card prompt that states the insight first; they
  are None on every other card.
- **Topics** come from the card's evidence, written once at its insert (``idea_topics``,
  migration 35; L2): a topic counts when a cited observation came from one of its
  sources, ``n`` is how many citations did and ``share`` the part of the evidence (a source in
  two topics counts for both); user topics come first. ``topic`` is the user topic with the
  largest share, never a project topic, None when there is none (a dispatch card's archive
  evidence). ``?topic=<id or name>`` lists the cards with that topic among theirs, filtered in
  SQL before any record is built. The theme's ``topic_mix`` is not used: one member from a
  topic's sources in a theme of hundreds is not the card's.
- **editor_notes** (``kind``, ``existing``, ``absorber``, ``facets``, ``integration_point``,
  ``channel``) are written by a card prompt made for the weekly editor; None elsewhere.
- **outcome** is the card's latest outcome of any kind and **editor** its latest ``editor``
  outcome (the class the weekly editor gave it, ``detail.week``, ``detail.why``); None when
  there is none. **outcomes** is the latest outcome of each kind (``{kind: outcome}``) and
  **built** what the loop made of the card (``outcomes.built``: ``{state, kind, idea, repo,
  url, at}``, None when nothing was built or the owner closed it since), so a page says "built
  -> Repo Recall" without the loop's snapshot. Builds left Kranto (CUT): these read the rows the
  loop wrote before; no new loop row comes.
- **state** is where the card sits on Ideas, from the server's rows alone
  (``card_state``): ``waiting``, ``later`` (with **later_until**, else None), ``posted`` (a draft
  was written about it) or ``passed``. The list answers **first** (``{words, at, observations,
  needed}``: when the first cards come) while there is no card and no filter.
- **output_kind** is the card's own as stored, else None (its old default, ``app``, was the
  build loop's first maker; ``intake`` and ``default_output_kind``, which only the loop read,
  left with builds).
- **Dispatch cards** (``origin`` ``dispatch``, ``ideate/dispatches.py``) add ``pitch``
  (verbatim), ``pitch_text``, ``pitch_kind`` (oss, commercial, founder), ``pitch_label``,
  ``dispatch``, ``lineages`` and ``links``; their ``score`` is None (a dispatch is not
  rated) and their citations say ``verified: "url_match"``.
- **embedding** is the card's title and one-liner (``one_liner``, else the thesis's first
  sentence) embedded by the library's local embedder, no model call; kept in memory per
  card text. ``?embedding=ref`` returns only the model and a link to the card.

Under the same guard as every route (an allowed Host); the POST, like every write, needs an
owner's token and a same-origin request.
"""

from __future__ import annotations

import hashlib
import re
import threading
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import outcomes, rowsafe
from ..ideate.cards import card_topics as stored_topics
from ..ideate.cards import evidence_view, facts, ideas_of_topic, list_ideas
from ..ideate.dispatches import KINDS as PITCH_KINDS
from ..ideate.dispatches import ORIGIN as DISPATCH_ORIGIN
from ..store import Store
from ..stored.cards import Card, EditorNotes, Existing, PriorArt, PriorArtHit
from ..stored.map import ClusterKeywords

STATUSES = ("shown", "unsupported")
_SENTENCE = re.compile(r"(?<=[.!?])\s")


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def topic_names(store: Store) -> dict[int, str]:
    """Topic id -> its name now: a topic edited since (a newer row that ``supersedes`` it) has
    its newest row's name (a card's shares keep the name it had when written)."""
    rows = store.query("SELECT id, name, supersedes FROM topics_now ORDER BY id")
    newer = {r["supersedes"]: r["id"] for r in rows if r["supersedes"] is not None}
    names = {r["id"]: r["name"] for r in rows}
    out = {}
    for tid in names:
        cur, seen = tid, set()
        while cur in newer and cur not in seen:
            seen.add(cur)
            cur = newer[cur]
        out[tid] = names[cur]
    return out


def lineage_themes(store: Store, lineage_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per lineage: its latest cluster row's name, size and topic_mix."""
    ids = sorted({i for i in lineage_ids if i})
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict[str, dict[str, Any]] = {}
    for r in store.query(
            f"SELECT lineage_id, snapshot_id, name, keywords, size, topic_mix FROM clusters "
            f"WHERE lineage_id IN ({marks}) ORDER BY snapshot_id", tuple(ids)):
        out[r["lineage_id"]] = dict(r)               # the latest snapshot wins
    return out


def card_topics(stored: dict[str, Any] | None,
                names: dict[int, str]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """A card's topics as written at its insert (``idea_topics``, migration 35), user topics
    first, each with its current name, and its topic: the user topic with the largest share
    (never a project topic), None when it has none."""
    shares = [{"id": t.id, "name": names.get(t.id, t.name) if t.id is not None else t.name,
               "kind": t.kind or "user", "n": t.n, "share": t.share}
              for t in (stored or {}).get("shares") or []]
    tid = (stored or {}).get("topic_id")
    return shares, next((t for t in shares if t["id"] == tid), None) if tid else None


def one_liner(card: Card) -> str:
    text = (card.one_liner or "").strip()
    if text:
        return text
    thesis = " ".join((card.thesis or "").split())
    return _SENTENCE.split(thesis, maxsplit=1)[0] if thesis else ""


def embedding_text(title: str, card: Card) -> str:
    return "\n".join(x for x in (title, one_liner(card)) if x)


def _citation(c: dict[str, Any], kind: str = "evidence") -> dict[str, Any]:
    observed = c.get("observed_at")
    date = c.get("date") or (str(observed)[:10] if observed else None)
    out = {"observation_id": c.get("observation_id"), "url": c.get("url"), "date": date,
           "observed_at": observed, "claim": str(c.get("claim") or ""),
           "source": c.get("source"), "for": c.get("for") or kind}
    if c.get("verified"):          # how it was checked: "url_match" for a dispatch's links
        out["verified"] = c["verified"]
    return out


def citations(idea: dict[str, Any], views: dict[Any, Any]) -> list[dict[str, Any]]:
    """The card writer's ``citations``, else its supported evidence as citations."""
    card: Card = idea["card"]
    if card.citations:
        return [_citation(c) for c in card.citations]
    out = []
    for e in card.evidence:
        view = views.get((idea["id"], e.observation_id), {})
        out.append(_citation({**view, **{k: v for k, v in e.to_dict().items()
                                          if v is not None}}))
    return out


def evidence(idea: dict[str, Any], views: dict[Any, Any]) -> list[dict[str, Any]]:
    out = []
    for e in idea["card"].evidence:
        view = views.get((idea["id"], e.observation_id), {})
        mine = {"summary": e.summary, "source": e.source, "observed_at": e.observed_at,
                "url": e.url}
        out.append({"n": e.n, "claim": e.claim, "observation_id": e.observation_id,
                    **{k: view.get(k, mine[k]) for k in mine},
                    # an entry with no observation id has no view: the card's own words
                    "compacted": view.get("compacted", True)})
    return out


def demand(card: Card) -> dict[str, Any] | None:
    d = card.demand_of()
    if d is None:
        return None
    ev = [e.to_dict(nulls=True) for e in d.evidence]
    return {"statement": d.statement, "evidence": ev,
            "supported": d.supported if d.supported is not None else len(ev)}


def dispatch_fields(card: Card) -> dict[str, Any]:
    """What a card made from one of the owner's dispatches carries besides the card's
    usual fields (``ideate/dispatches.py``): the pitch verbatim, its kind, the dispatch,
    the archive themes its clusters were, and the links that matched no observation."""
    return {"pitch": card.pitch or "", "pitch_text": card.pitch_text or "",
            "pitch_kind": card.pitch_kind, "pitch_label": card.pitch_label,
            "dispatch": card.dispatch or {}, "lineages": card.lineages, "links": card.links}


def existing_record(e: Existing) -> dict[str, Any]:
    return {"n": e.n, "name": e.name, "covers": e.covers}


def editor_notes_record(notes: EditorNotes) -> dict[str, Any] | None:
    """The weekly editor's notes: each key only when it was written; None when none was."""
    out = {k: v for k, v in notes.api().items() if v not in ([], "")}
    if notes.existing:
        out["existing"] = [existing_record(e) for e in notes.existing]
    return out or None


def _hit(h: PriorArtHit, what: bool = False) -> dict[str, Any]:
    out = {"label": h.label or "", "url": h.url or "", "title": h.title or "",
           "date": h.date}
    return {**out, "what": h.what or ""} if what else out


def prior_art_record(p: PriorArt) -> dict[str, Any]:
    """The card's prior-art search as the page reads it: every key, whatever an older or
    partial record left out."""
    return {"live": bool(p.live), "searched_at": p.searched_at or "", "query": p.query or "",
            "backends": p.backends, "note": p.note, "results": p.results or 0,
            "hits": [_hit(h) for h in p.hits], "existing": [_hit(h, True) for h in p.existing]}


def card_record(idea: dict[str, Any], views: dict[Any, Any], theme: dict[str, Any] | None,
                stored: dict[str, Any] | None, names: dict[int, str],
                outcome: dict[str, Any] | None = None,
                editor: dict[str, Any] | None = None) -> dict[str, Any]:
    card: Card = idea["card"]
    tops, top = card_topics(stored, names)
    dispatch = idea.get("origin") == DISPATCH_ORIGIN
    return {
        "id": idea["id"], "title": idea["title"], "status": idea["status"],
        # a dispatch is not rated: its cards have no score rather than a zero
        "score": None if dispatch else idea["score"], "grade": idea.get("verdict"),
        # the owner's order (taste.rank,): place, taste, the line, its parts
        "rank": idea["rank"].api() if idea.get("rank") is not None else None,
        # what it stands on: the list's order, and the words the pages show
        "facts": idea.get("facts") or facts(card),
        "created_at": idea["created_at"], "origin": idea.get("origin"),
        "lineage_id": idea.get("lineage_id"),
        "theme": ({"lineage_id": idea.get("lineage_id"), "name": theme["name"],
                   "keywords": ClusterKeywords.load(theme["keywords"]).items[:5],
                   "size": theme["size"], "snapshot_id": theme["snapshot_id"]}
                  if theme else None),
        "topics": tops, "topic": top,
        # the card writer's own word, as stored (a card from before it, or an odd value,
        # has none: no build's default kind any more)
        "output_kind": card.output_kind if isinstance(card.output_kind, str)
        and card.output_kind else None,
        "one_liner": one_liner(card),
        "who": card.who or None,
        "smallest_v1": card.smallest_v1 or "",
        "demand": demand(card),
        "citations": citations(idea, views),
        "dropped": [{"n": d.n, "claim": d.claim, "reason": d.reason}
                    for d in idea.get("dropped") or []],
        "thesis": card.thesis or "", "pattern": card.pattern or "",
        "where_now": card.where_now or "", "cheapest_test": card.cheapest_test or "",
        "risks": card.risks or "", "why_selected": card.why_selected or "",
        "prediction": card.prediction.api() if card.prediction else {},
        # a rating from an older prompt may have no reason (or no value: then it is not one)
        "ratings": {k: {**r.to_dict(nulls=True), "reason": r.reason or ""}
                    for k, r in card.ratings.items() if r.value is not None},
        # a card written by a prompt that states its insight first (None on older cards)
        "insight": card.insight or None,
        "existing": [existing_record(e) for e in card.existing] or None,
        "gap": card.gap or None, "moment": card.moment or None,
        "mechanism": card.mechanism or None,
        # a card written by the card prompt made for the weekly editor (None elsewhere)
        "editor_notes": editor_notes_record(card.editor_notes) if card.editor_notes else None,
        # live search's prior art: when, from which backends, what exists; None on
        # cards written before it
        "prior_art": prior_art_record(card.prior_art) if card.prior_art else None,
        "novelty_dropped": [{"field": d.field or "", "sentence": d.sentence or "",
                             "reason": d.reason or ""} for d in card.novelty_dropped],
        "outcome": outcome, "editor": editor,
        "evidence": evidence(idea, views),
        **(dispatch_fields(card) if dispatch else {}),
    }


STATES = ("waiting", "later", "posted", "passed")
PASS_GRADES = ("not_useful", "wrong")
# a draft about a card that was declined or refused does not make it posted
NOT_POSTED = ("declined", "refused")


def drafts_of(store: Store, idea_ids: list[int]) -> dict[int, list[str]]:
    """Per card, the latest state of each cub ticket (a draft) resting on it (``because.ideas``,
    CON L4): one read of the tickets' JSON, which are few by construction."""
    want = {int(i) for i in idea_ids}
    out: dict[int, list[str]] = {}
    if not want:
        return out
    for r in store.query(
            "SELECT b.value AS idea, (SELECT s.state FROM cub_ticket_states s WHERE s.ticket_id "
            "= t.id ORDER BY s.id DESC LIMIT 1) AS state FROM cub_tickets t, "
            "json_each(t.because, '$.ideas') b"):
        try:
            n = int(r["idea"])
        except (TypeError, ValueError):
            continue
        if n in want:
            out.setdefault(n, []).append(str(r["state"] or "needs_confirm"))
    return out


def card_state(grade: Any, kinds: dict[str, dict[str, Any]] | None, drafts: list[str] | None,
               now: Any = None) -> str:
    """Where a card sits on Ideas, from what the server keeps, never the build
    loop's ledger: ``passed`` when the owner's grade is not useful or wrong (Pass writes it);
    ``posted`` when a draft was written about it and not declined; ``later`` while a Later is
    ahead (``outcomes.later_until``); ``passed`` too when the build loop finished with it in an
    earlier release (built, or closed: its words stay on the card); else ``waiting``."""
    if grade in PASS_GRADES:
        return "passed"
    if any(s not in NOT_POSTED for s in drafts or []):
        return "posted"
    if outcomes.later_until(kinds, now):
        return "later"
    if outcomes.built(kinds) is not None or "verdict" in (kinds or {}):
        return "passed"
    return "waiting"


def read_ideas(store: Store, status: str | None = None,
               topic: int | None = None, grading: Any = None) -> list[dict[str, Any]]:
    """Every card (or those of one ``status``, or with ``topic`` among its topics: one indexed
    read before any record is built) as the API returns it, in the owner's order
    (``list_ideas``), without embeddings."""
    ideas = list_ideas(store, include_unsupported=True,
                       ids=ideas_of_topic(store, topic) if topic is not None else None,
                       grading=grading)
    if status:
        ideas = [i for i in ideas if i["status"] == status]
    views = evidence_view(store, ideas)
    themes = lineage_themes(store, [x for i in ideas if (x := i.get("lineage_id"))])
    stored, names = stored_topics(store, [i["id"] for i in ideas]), topic_names(store)
    kinds = outcomes.by_kind(store, [i["id"] for i in ideas])
    drafts = drafts_of(store, [i["id"] for i in ideas])
    out: list[dict[str, Any]] = []
    for i in ideas:
        # one card that cannot be read is listed as such, never the whole list (RCA A3); a
        # reader that builds from cards (the page's intake) skips it by ``unreadable``
        with rowsafe.row(out, "idea", i.get("id"), title=i.get("title"),
                         status=i.get("status"), origin=i.get("origin"),
                         created_at=i.get("created_at")):
            k = kinds.get(i["id"]) or {}
            rec = card_record(i, views, themes.get(i.get("lineage_id") or ""), stored.get(i["id"]),
                              names, max(k.values(), key=lambda r: r["id"]) if k else None,
                              k.get("editor"))
            rec["outcomes"], rec["built"] = k, outcomes.built(k)
            rec["state"] = card_state(rec["grade"], k, drafts.get(i["id"]))
            rec["later_until"] = outcomes.later_until(k) if rec["state"] == "later" else None
            out.append(rec)
    return out


class IdeasAPI:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._vectors: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @property
    def rt(self) -> Any:
        return self.app.rt

    def _embed(self, records: list[dict[str, Any]], how: str) -> None:
        embedder = self.rt.embedder
        records = [r for r in records if not rowsafe.is_unreadable(r)]
        for r in records:
            ref = {"model": embedder.model_name, "dim": embedder.dim,
                   "href": f"/api/ideas/{r['id']}"}
            r["embedding"] = ref
        if how == "ref":
            return
        texts = {r["id"]: embedding_text(r["title"], Card(one_liner=r["one_liner"]))
                 for r in records}
        keys = {i: hashlib.sha256(f"{embedder.model_name}\n{t}".encode()).hexdigest()
                for i, t in texts.items()}
        with self._lock:
            todo = [i for i in texts if keys[i] not in self._vectors]
            if todo:
                vectors = embedder.embed_documents([texts[i] for i in todo])
                for i, v in zip(todo, vectors, strict=True):
                    self._vectors[keys[i]] = [round(float(x), 6) for x in v]
            for r in records:
                r["embedding"]["text"] = texts[r["id"]]
                r["embedding"]["vector"] = self._vectors[keys[r["id"]]]

    def _grading(self) -> Any:
        return getattr(self.rt.cfg, "grading", None)

    @staticmethod
    def _how(request: Request) -> str | None:
        how = request.query_params.get("embedding", "inline")
        return how if how in ("inline", "ref") else None

    def list_ideas(self, request: Request) -> Response:
        q = request.query_params
        status = q.get("status") or None
        if status not in (None, *STATUSES):
            return _error(f"status must be one of {', '.join(STATUSES)}")
        how = self._how(request)
        if how is None:
            return _error("embedding must be inline or ref")
        origin, kind = q.get("origin") or None, q.get("kind") or None
        if kind not in (None, *PITCH_KINDS):
            return _error(f"kind must be one of {', '.join(PITCH_KINDS)}")
        if kind and not origin:
            origin = DISPATCH_ORIGIN
        topic = q.get("topic")
        tid = None
        if topic:
            tid = int(topic) if topic.isdigit() else next(
                (i for i, n in topic_names(self.rt.store).items() if n == topic), -1)
        records = read_ideas(self.rt.store, status, tid, self._grading())
        if origin is None:      # dispatch cards are asked for (origin=dispatch, or all)
            records = [r for r in records if r.get("origin") != DISPATCH_ORIGIN]
        elif origin != "all":
            records = [r for r in records if r.get("origin") == origin]
        if kind:
            records = [r for r in records if r.get("pitch_kind") == kind]
        self._embed(records, how)
        out = {"ideas": records, "count": len(records)}
        if not records and not (status or tid is not None or origin or kind):
            out["first"] = self._first()
        return JSONResponse(out)

    def _first(self) -> dict[str, Any]:
        """Ideas' empty page: when the first cards come, from the library's count
        and the scheduler's own next map: ``{words, at, observations, needed}``."""
        from ..map.compute import MIN_OBSERVATIONS
        from ..progress import ideas_wait, observation_count
        scheduler = getattr(self.app, "scheduler", None)
        total = observation_count(self.rt.store)
        return {**ideas_wait(self.rt.store, scheduler.next_runs() if scheduler else {}, total,
                             MIN_OBSERVATIONS),
                "observations": total, "needed": MIN_OBSERVATIONS}

    async def later(self, request: Request) -> Response:
        """``POST /api/ideas/{id}/later`` ``{days?}`` (``idea.later``): put a card off for
        ``days`` (7 by default; 0 brings it back now). Written in the server alone (``outcomes``),
        never the build loop's ledger. ``{id, state, later_until, outcome}``."""
        from starlette.concurrency import run_in_threadpool

        from ..core import verbs
        from .app import MAX_JSON_BYTES, _json_body, path_id

        idea_id = path_id(request.path_params["idea_id"])
        body = await _json_body(request) if (request.headers.get("content-length") or "0") \
            != "0" else {}
        if body is None:
            return _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        days = body.get("days", outcomes.LATER_DAYS)
        by = verbs.acting_by()
        source = "cli" if by == "cli" else "ui"
        try:
            got = await run_in_threadpool(outcomes.later, self.rt.store, idea_id, days,
                                          source=source)
        except LookupError as exc:
            return _error(str(exc), 404)
        except ValueError as exc:
            return _error(str(exc))
        until = outcomes.later_until({"decision": got})
        return JSONResponse({"id": idea_id, "state": "later" if until else "waiting",
                             "later_until": until, "outcome": got})

    def get_idea(self, request: Request) -> Response:
        from .app import path_id

        idea_id = path_id(request.path_params["idea_id"])
        how = self._how(request)
        if how is None:
            return _error("embedding must be inline or ref")
        record = next((r for r in read_ideas(self.rt.store, grading=self._grading())
                       if r["id"] == idea_id), None)
        if record is None:
            return _error("no such idea", 404)
        if rowsafe.is_unreadable(record):     # its own page: the error page, by the row's id
            raise rowsafe.Unreadable(record)
        from ..core import tickets
        record["tickets"] = tickets.resting_on(self.rt.store, "ideas", idea_id)
        # "In the news": the newest story that matches the card by rule
        from ..news_ideas import card_story
        try:
            record["news"] = card_story(self.rt.store, idea_id)
        except Exception:  # noqa: BLE001 - the card still answers without its story
            record["news"] = None
        self._embed([record], how)
        return JSONResponse(record)

    async def add_outcome(self, request: Request) -> Response:
        """``{kind, value, detail?, source?}`` on one card; ``{"id", "outcome"}``."""
        from starlette.concurrency import run_in_threadpool

        from .app import MAX_JSON_BYTES, _json_body, path_id

        idea_id = path_id(request.path_params["idea_id"])
        body = await _json_body(request)
        if body is None:
            return _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        try:
            row_id = await run_in_threadpool(outcomes.add, self.rt.store, idea_id, body)
        except LookupError as exc:
            return _error(str(exc), 404)
        except ValueError as exc:
            return _error(str(exc))
        got = outcomes.history(self.rt.store, idea_id)[-1]
        return JSONResponse({"id": row_id, "outcome": got})

    async def card_theme(self, request: Request) -> Response:
        """One card on a theme of the latest map, on the owner's request (CON D-1): started in
        the background (one card call and its check, about $0.06, under the card writer's lock
        and the budget); 202 ``{"started", "lineage"}``. The card appears with the theme's
        cards; a run that cannot (no such theme, too little evidence, a run already writing
        cards, the budget) is recorded in Runs with its reason."""
        import threading

        from .. import websearch
        from ..ideate.cards import card_theme
        from .app import _json_body

        lineage = str(request.path_params["lineage"])
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", lineage):
            return _error("not a theme")
        # Idea from this: an optional hint and the story it was asked from
        body = await _json_body(request) if (request.headers.get("content-length") or "0") \
            != "0" else {}
        if body is None:
            return _error("expected a JSON object")
        hint, story = body.get("hint"), body.get("story")
        if hint is not None and (not isinstance(hint, str) or len(hint) > 600):
            return _error("hint is text of at most 600 characters")
        if story is not None and (not isinstance(story, str)
                                  or not re.fullmatch(r"brief:[0-9]{1,9}:[0-9]{1,3}", story)):
            return _error("story is brief:<id>:<item>")
        rt = self.rt

        from .. import activity

        def run() -> None:
            # Card it now is a run of kind ideas: its row, its marks, its trace
            with activity.run(rt.store, "ideas", origin="press", by="ui",
                              subject=("theme", lineage, None)):
                card_theme(rt.store, rt.llm, lineage,
                           archive_evidence=rt.cfg.parallax.card_evidence,
                           searcher=websearch.for_runtime(rt, "cards"),
                           hint=hint.strip() if hint and hint.strip() else None,
                           story=story or None)
        threading.Thread(target=run, name=f"card-theme-{lineage}", daemon=True).start()
        return JSONResponse({"started": True, "lineage": lineage}, status_code=202)

    def routes(self) -> list[Route]:
        return [
            Route("/api/ideas", self.list_ideas),
            Route("/api/ideas/{idea_id}", self.get_idea),
            Route("/api/ideas/{idea_id}/outcome", self.add_outcome, methods=["POST"]),
            Route("/api/ideas/{idea_id}/later", self.later, methods=["POST"]),
            Route("/api/themes/{lineage}/card", self.card_theme, methods=["POST"]),
        ]
