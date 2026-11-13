"""A story's idea, and a card's story: chosen by rule from stored rows,
never by a model call.

A story (an item of a brief) has an idea when, in this order:

1. **a card was made from it**: Idea from this asks ``theme.card`` with ``story``
   (``brief:<id>:<item>``, the item counted from 1), and the ideas run keeps it in its summary
   (``runs.summary`` → ``extra.story``) beside the cards it wrote (``idea_ids``);
2. **a card cites one of its observations** (``idea_citations``);
3. **a card is of the theme its observations sit in** on the latest map (``snapshot_points``
   → ``clusters.lineage_id`` → ``ideas.lineage_id``).

The first rule that matches gives the idea; the others it found are counted (``more``). With
none, the story offers Idea from this on its theme (the lineage holding most of its
observations on the latest map), or says why it cannot (``no_theme``).

A card's story is the newest story of the last briefs that matches it by the same rules.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

NOT_ON_MAP = "An idea needs this story on the map: after tonight's map."
ONLY_SEARCH = "Only search results back this story, so it is on no theme yet."
NO_MAP = "An idea needs the map, which is made once enough is kept: after the first map."
BRIEFS_SCANNED = 30


def story_ref(brief_id: int, n: int) -> str:
    """The story's name as ``theme.card``'s ``story`` and ``post.write``'s ``about`` take it."""
    return f"brief:{int(brief_id)}:{int(n) + 1}"


def _obs_ids(item: Any) -> list[int]:
    ids = item.get("observation_ids") if isinstance(item, dict) else None
    return [int(i) for i in ids or [] if isinstance(i, int) and not isinstance(i, bool)]


def _latest_snapshot(store: Any) -> int | None:
    r = store.query_one("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1")
    return int(r["id"]) if r else None


def _marks(n: int) -> str:
    return ",".join("?" * n)


def _asked(raw: Any) -> tuple[str | None, list[int]]:
    """An ideas run's ``story`` and the cards it wrote, read through the summary's contract
    (``stored.runs``): a run without them, or one stored oddly, has none."""
    from .stored import runs as stored_runs
    s = stored_runs.summary_of("ideas", raw)
    ids = s.extra.get("idea_ids")
    cards = [i for i in ids if isinstance(i, int) and not isinstance(i, bool)] \
        if isinstance(ids, list) else []
    return s.text("story"), cards


def _from_story(store: Any, ref: str) -> list[int]:
    """Rule 1: the cards an ideas run wrote when Idea from this was asked on this story."""
    out: list[int] = []
    for r in store.query("SELECT summary FROM runs WHERE kind = 'ideas' AND summary LIKE ? "
                         "ORDER BY rowid DESC LIMIT 20", (f"%{ref}%",)):
        story, cards = _asked(r["summary"])
        if story == ref:
            out += [i for i in cards if i not in out]
    return out


def _citing(store: Any, obs: list[int]) -> list[int]:
    """Rule 2: the cards that cite one of these observations, newest first."""
    if not obs:
        return []
    return [int(r["idea_id"]) for r in store.query(
        f"SELECT DISTINCT idea_id FROM idea_citations WHERE observation_id IN ({_marks(len(obs))}) "
        "ORDER BY idea_id DESC", tuple(obs))]


def _themes_of(store: Any, snapshot: int | None, obs: list[int]) -> list[tuple[str, int]]:
    """The lineages these observations sit in on the latest map, most observations first:
    ``[(lineage_id, how many)]``."""
    if snapshot is None or not obs:
        return []
    got: Counter[str] = Counter()
    for r in store.query(
            f"SELECT c.lineage_id AS lineage FROM snapshot_points p JOIN clusters c ON "
            f"c.snapshot_id = p.snapshot_id AND c.cluster = p.cluster WHERE p.snapshot_id = ? "
            f"AND p.observation_id IN ({_marks(len(obs))})", (snapshot, *obs)):
        if r["lineage"]:
            got[str(r["lineage"])] += 1
    return got.most_common()


def _of_lineages(store: Any, lineages: list[str]) -> list[int]:
    """Rule 3: the cards of these themes, newest first."""
    if not lineages:
        return []
    return [int(r["id"]) for r in store.query(
        f"SELECT id FROM ideas WHERE status = 'shown' AND lineage_id IN ({_marks(len(lineages))}) "
        "ORDER BY id DESC", tuple(lineages))]


def _shown(store: Any, ids: list[int]) -> dict[int, str]:
    """The cards of ``ids`` that are shown, by id: their titles."""
    if not ids:
        return {}
    return {int(r["id"]): str(r["title"]) for r in store.query(
        f"SELECT id, title FROM ideas WHERE status = 'shown' AND id IN ({_marks(len(ids))})",
        tuple(ids))}


def _states(store: Any, ids: list[int]) -> dict[int, str]:
    """Where each card sits on Ideas (waiting, later, posted, passed), as Ideas says it."""
    if not ids:
        return {}
    from . import grades, outcomes
    from .web.ideas_api import card_state, drafts_of
    kinds = outcomes.by_kind(store, ids)
    drafts = drafts_of(store, ids)
    latest = grades.latest(store, "idea", ids)
    return {i: card_state((latest.get(str(i)) or {}).get("grade"), kinds.get(i) or {},
                          drafts.get(i)) for i in ids}


def _theme_row(store: Any, snapshot: int, lineage: str) -> dict[str, Any] | None:
    r = store.query_one("SELECT lineage_id, name, keywords, size FROM clusters WHERE "
                        "snapshot_id = ? AND lineage_id = ?", (snapshot, lineage))
    if r is None:
        return None
    name = r["name"]
    if not name:
        from .stored.map import ClusterKeywords
        kw = ClusterKeywords.load(r["keywords"]).items[:4]
        words = [k if isinstance(k, str) else str((k or [""])[0]) for k in kw]
        name = ", ".join(w for w in words if w) or "a theme"
    return {"lineage_id": str(r["lineage_id"]), "name": " ".join(str(name).split())[:120],
            "size": int(r["size"])}


def story_ideas(store: Any, brief_id: int, items: list[Any]) -> dict[str, dict[str, Any]]:
    """Each story's idea and theme, keyed by the item's number as text (as ``articles``):
    ``{idea: {id, title, state, rule, more} | None, theme: {lineage_id, name, size} | None,
    no_theme: str | None, story: "brief:<id>:<item>"}``."""
    snapshot = _latest_snapshot(store)
    out: dict[str, dict[str, Any]] = {}
    found: dict[int, tuple[list[int], int]] = {}
    themes: dict[int, list[tuple[str, int]]] = {}
    for n, item in enumerate(items):
        obs = _obs_ids(item)
        themes[n] = _themes_of(store, snapshot, obs)
        ref = story_ref(brief_id, n)
        rules = (_from_story(store, ref), _citing(store, obs),
                 _of_lineages(store, [lin for lin, _ in themes[n]]))
        shown = _shown(store, sorted({i for ids in rules for i in ids}))
        for rule, ids in enumerate(rules, start=1):
            ids = [i for i in ids if i in shown]
            if ids:
                rest = {i for later in rules[rule:] for i in later if i in shown} - set(ids)
                found[n] = (ids, rule) if not rest else (ids + sorted(rest, reverse=True), rule)
                break
    states = _states(store, sorted({i for ids, _ in found.values() for i in ids[:1]}))
    titles = _shown(store, sorted({i for ids, _ in found.values() for i in ids[:1]}))
    for n, item in enumerate(items):
        idea = None
        if n in found:
            ids, rule = found[n]
            idea = {"id": ids[0], "title": titles.get(ids[0], ""), "state": states.get(ids[0]),
                    "rule": rule, "more": len(ids) - 1}
        theme, why = None, None
        if snapshot is None:
            why = NO_MAP
        elif not _obs_ids(item):
            why = ONLY_SEARCH
        elif not themes[n]:
            why = NOT_ON_MAP
        else:
            theme = _theme_row(store, snapshot, themes[n][0][0])
            why = None if theme else NOT_ON_MAP
        out[str(n)] = {"idea": idea, "theme": theme, "no_theme": why,
                       "story": story_ref(brief_id, n)}
    return out


def card_story(store: Any, idea_id: int) -> dict[str, Any] | None:
    """The newest story of the last briefs that matches this card by the three rules:
    ``{brief_id, n, headline, date, topic_id}``, or None."""
    from .features.news.stored import BriefItems
    card = store.query_one("SELECT id, lineage_id FROM ideas WHERE id = ?", (int(idea_id),))
    if card is None:
        return None
    cited = {int(r["observation_id"]) for r in store.query(
        "SELECT observation_id FROM idea_citations WHERE idea_id = ?", (int(idea_id),))}
    snapshot = _latest_snapshot(store)
    on_theme: set[int] = set()
    if snapshot is not None and card["lineage_id"]:
        on_theme = {int(r["observation_id"]) for r in store.query(
            "SELECT p.observation_id FROM snapshot_points p JOIN clusters c ON "
            "c.snapshot_id = p.snapshot_id AND c.cluster = p.cluster WHERE p.snapshot_id = ? "
            "AND c.lineage_id = ?", (snapshot, card["lineage_id"]))}
    asked: set[str] = set()
    for r in store.query("SELECT summary FROM runs WHERE kind = 'ideas' AND summary LIKE "
                         "'%brief:%' ORDER BY rowid DESC LIMIT 50"):
        story, cards = _asked(r["summary"])
        if story and int(idea_id) in cards:
            asked.add(story)
    best: tuple[int, dict[str, Any]] | None = None
    for b in store.query("SELECT id, topic_id, items, created_at FROM news_briefs WHERE "
                         "status = 'ok' ORDER BY id DESC LIMIT ?", (BRIEFS_SCANNED,)):
        items = BriefItems.load(b["items"]).items
        for n, item in enumerate(items):
            obs = set(_obs_ids(item))
            rule = 1 if story_ref(b["id"], n) in asked else 2 if obs & cited else \
                3 if obs & on_theme else 0
            if rule and (best is None or rule < best[0]):
                best = (rule, {"brief_id": int(b["id"]), "n": n, "topic_id": int(b["topic_id"]),
                               "headline": str(item.get("headline") or ""),
                               "date": item.get("date") or str(b["created_at"])[:10]})
        if best is not None and best[0] == 1:
            break
    return best[1] if best else None
