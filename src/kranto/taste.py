"""Taste: what the owner's ▲ and ▼ do to the order of the cards.

A deterministic function of what Kranto stores; no model, no embedder, no agent:

- **The graded items** are the owner's latest grade on each idea card and each observation
  (``grades.latest``, the one reader; a cleared grade counts as none), each weighing
  ``sign · K · 0.5^(age / half_life)``: +1 useful, −1 not useful or wrong; ``K`` 1 for a card
  and ``observation_weight`` for an observation. A grade older than four half-lives is not read.
- **An item** (a card, an observation, a theme of the latest map) is compared by five fields:
  its centred unit vector (the stored embeddings, minus the latest map's mean, re-normalised;
  a card's is the mean of its cited observations'), its observation ids, its sources, its
  theme lineages and its topics.
- **Resemblance** ``r(c, x)`` in [0, 1] is the strongest of: shared evidence (the overlap
  coefficient), the same theme (1), reading alike (the centred cosine ramped from ``cos_low``
  to ``cos_high``) and, only when a side has no vector, the same topic (``topic_weight``).
  A shared source is not one (one archive source would lift every dispatch card).
- ``taste(c) = Σ weight(x) · r(c, x)`` over the graded items other than ``c``, rounded to three
  decimals (each part to four) before anything is compared.
- **The order** is ``(own, −taste, −asks, −cited, −sources, −id)``: the cards the owner graded
  useful first, those graded not useful last, every other card by taste and then by today's
  order (``cards.fact_order``). A card nothing resembles keeps its place among the others.

The same data gives the same order: every input is a stored row, the mean is summed in float64
in observation-id order, and ``now`` is an argument. ``rank`` is cached per database on (the
newest feedback row, the newest card, the latest snapshot, ``now`` to the minute, the settings);
the latest map's mean and the cards' raw vectors per snapshot.
"""

from __future__ import annotations

import threading
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from .config import GradingConfig
from .store import Store, iso, utcnow

SIGN = {"useful": 1, "not_useful": -1, "wrong": -1}
HALF_LIVES_READ = 4            # a grade older than four half-lives (1/16) is not read


@dataclass
class Item:
    """What a card, an observation or a theme is compared by."""
    key: tuple[str, str]                      # ("idea", "112"), ("observation", "438")
    vec: np.ndarray | None
    obs: frozenset[int]
    src: frozenset[int]
    themes: frozenset[str]
    topics: frozenset[int]


@dataclass
class Graded:
    key: tuple[str, str]
    value: str
    created_at: str
    weight: float                             # sign · K · decay, unrounded
    title: str = ""


@dataclass
class Rank:
    """One card's rank: its ``taste``, the ``parts`` it is the sum of (strongest first), the
    owner's own grade, the one ``line`` the card shows, and its place among the shown cards."""
    id: int
    taste: float
    parts: list[dict[str, Any]]
    own: str | None
    line: str
    key: tuple
    position: int | None = None

    def api(self) -> dict[str, Any]:
        return {"position": self.position, "taste": self.taste, "line": self.line,
                "parts": self.parts}


@dataclass
class _Model:
    """What ``rank`` reads once per cache key: the items and the graded ones."""
    snapshot: int | None
    items: dict[tuple[str, str], Item]
    graded: dict[tuple[str, str], Graded]
    themes: dict[str, Item] = field(default_factory=dict)


def parse_ts(ts: str) -> datetime:
    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def settings(cfg: GradingConfig | None) -> GradingConfig:
    return cfg if cfg is not None else GradingConfig()


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _vec(blob: Any, dim: int | None) -> np.ndarray | None:
    """A stored float32 embedding as float64, None when empty or of another size than the map's."""
    if not blob:
        return None
    v = np.frombuffer(bytes(blob), dtype=np.float32).astype(np.float64)
    if not v.size or (dim is not None and v.size != dim) or not np.isfinite(v).all():
        return None
    return v


# -- per-snapshot caches ------------------------------------------------------------------

_LOCK = threading.RLock()
_MU: dict[tuple[str, int], np.ndarray | None] = {}
_CARD_RAW: dict[tuple[str, int], dict[int, np.ndarray | None]] = {}
_RANKS: dict[str, tuple[tuple, dict[int, Rank], _Model]] = {}


_MEMORY: weakref.WeakKeyDictionary[Store, str] = weakref.WeakKeyDictionary()


def _db_key(store: Store) -> str:
    """The cache's name for a database: its path, or a token of its own for an in-memory one
    (an id could be reused by the next store)."""
    if store.path is not None:
        return str(store.path)
    with _LOCK:
        if store not in _MEMORY:
            _MEMORY[store] = f"memory:{uuid.uuid4().hex}"
        return _MEMORY[store]


def clear_cache() -> None:
    """Forget every cached mean, card vector and order (the tests' fresh start)."""
    with _LOCK:
        _MU.clear()
        _CARD_RAW.clear()
        _RANKS.clear()


def latest_snapshot(store: Store) -> int | None:
    row = store.query_one("SELECT MAX(id) AS id FROM snapshots")
    return int(row["id"]) if row and row["id"] is not None else None


def _mu(store: Store, snapshot: int | None) -> np.ndarray | None:
    """The latest map's mean embedding, summed in float64 in observation-id order."""
    if snapshot is None:
        return None
    key = (_db_key(store), snapshot)
    with _LOCK:
        if key in _MU:
            return _MU[key]
    total, n, dim = None, 0, None
    for r in store.query("SELECT o.embedding FROM snapshot_points p JOIN observations o "
                         "ON o.id = p.observation_id WHERE p.snapshot_id = ? "
                         "ORDER BY o.id", (snapshot,)):
        v = _vec(r["embedding"], dim)
        if v is None:
            continue
        if total is None:
            total, dim = np.zeros(v.size, dtype=np.float64), v.size
        total += unit(v)
        n += 1
    mu = (total / n) if total is not None and n else None
    with _LOCK:
        _MU[key] = mu
    return mu


def _centre(v: np.ndarray | None, mu: np.ndarray | None) -> np.ndarray | None:
    if v is None:
        return None
    if mu is None:
        return unit(unit(v))
    if v.size != mu.size:
        return None
    c = unit(unit(v) - mu)
    return c if float(np.linalg.norm(c)) else None


def _card_raw(store: Store, snapshot: int | None, dim: int | None,
              idea_ids: list[int]) -> dict[int, np.ndarray | None]:
    """Each card's mean cited embedding (unit), None when none of its citations resolves."""
    key = (_db_key(store), snapshot or 0)
    with _LOCK:
        have = _CARD_RAW.setdefault(key, {})
        todo = [i for i in idea_ids if i not in have]
    if todo:
        sums: dict[int, list[np.ndarray]] = {}
        for at in range(0, len(todo), 500):
            part = todo[at:at + 500]
            for r in store.query(
                    "SELECT c.idea_id, o.id AS oid, o.embedding FROM idea_citations c "
                    "JOIN observations o ON o.id = c.observation_id "
                    f"WHERE c.idea_id IN ({','.join('?' * len(part))}) "
                    "GROUP BY c.idea_id, o.id ORDER BY c.idea_id, o.id", tuple(part)):
                v = _vec(r["embedding"], dim)
                if v is not None:
                    sums.setdefault(int(r["idea_id"]), []).append(unit(v))
        got = {i: (unit(np.mean(np.stack(sums[i]), axis=0)) if i in sums else None)
               for i in todo}
        with _LOCK:
            have.update(got)
    with _LOCK:
        return {i: have.get(i) for i in idea_ids}


# -- the items ------------------------------------------------------------------------------


def _source_topics(store: Store) -> dict[int, set[int]]:
    """Each source's user topics now (``topic_links``)."""
    out: dict[int, set[int]] = {}
    for r in store.query("SELECT l.topic_id, l.source_id FROM topic_links l "
                         "JOIN topics t ON t.id = l.topic_id WHERE COALESCE(t.kind, 'user') "
                         "= 'user'"):
        out.setdefault(int(r["source_id"]), set()).add(int(r["topic_id"]))
    return out


def _card_topics(store: Store) -> dict[int, set[int]]:
    """Each card's user topics, from its newest ``idea_topics`` row (its shares and topic)."""
    from .ideate.cards import card_topics

    ids = [int(r["idea_id"]) for r in store.query("SELECT DISTINCT idea_id FROM idea_topics")]
    out: dict[int, set[int]] = {}
    for i, row in card_topics(store, ids).items():
        tops = {int(row["topic_id"])} if isinstance(row["topic_id"], int) else set()
        tops |= {int(s.id) for s in row["shares"]
                 if isinstance(s.id, int) and (s.kind or "user") == "user"}
        out[i] = tops
    return out


def _lineages(store: Store, snapshot: int | None) -> dict[int, str]:
    """Each point of the latest map: its cluster's lineage."""
    if snapshot is None:
        return {}
    return {int(r["observation_id"]): str(r["lineage_id"]) for r in store.query(
        "SELECT p.observation_id, c.lineage_id FROM snapshot_points p JOIN clusters c "
        "ON c.snapshot_id = p.snapshot_id AND c.cluster = p.cluster WHERE p.snapshot_id = ?",
        (snapshot,))}


def _citations(store: Store) -> dict[int, set[int]]:
    """Each card's cited observations that are still in the library."""
    out: dict[int, set[int]] = {}
    for r in store.query("SELECT DISTINCT c.idea_id, c.observation_id FROM idea_citations c "
                         "JOIN observations o ON o.id = c.observation_id"):
        out.setdefault(int(r["idea_id"]), set()).add(int(r["observation_id"]))
    return out


def graded(store: Store, now: datetime, cfg: GradingConfig) -> dict[tuple[str, str], Graded]:
    """The owner's latest grade on each card and observation, with its weight; a cleared grade,
    a purged observation and a grade older than four half-lives are left out."""
    from . import grades

    horizon = now - timedelta(days=cfg.half_life_days * HALF_LIVES_READ)
    out: dict[tuple[str, str], Graded] = {}
    for target, table in (("idea", "ideas"), ("observation", "observations")):
        ids = [str(r["target_id"]) for r in store.query(
            "SELECT DISTINCT target_id FROM feedback WHERE kind = 'grade' AND target = ? "
            "UNION SELECT DISTINCT target_id FROM grades WHERE target = ? "
            "UNION SELECT DISTINCT CAST(target_id AS TEXT) FROM verdicts WHERE target = ?",
            (target, target, target))]
        latest = grades.latest(store, target, ids)
        alive = {str(r["id"]): r for r in _rows_by_id(
            store, table, [int(i) for i in latest if str(i).isdigit()])}
        k = 1.0 if target == "idea" else cfg.observation_weight
        for tid, g in latest.items():
            sign = SIGN.get(str(g.get("grade")))
            at = g.get("created_at")
            if sign is None or tid not in alive or not at:
                continue
            when = parse_ts(str(at))
            if when < horizon:
                continue
            days = max(0.0, (now - when).total_seconds() / 86400.0)
            out[(target, tid)] = Graded((target, tid), str(g["grade"]), str(at),
                                        sign * k * 0.5 ** (days / cfg.half_life_days),
                                        str(alive[tid]["title"] or ""))
    return out


def _rows_by_id(store: Store, table: str, ids: list[int]) -> list[Any]:
    out = []
    for at in range(0, len(ids), 500):
        part = ids[at:at + 500]
        out += store.query(f"SELECT id, title, {'source_id' if table == 'observations' else 'NULL'}"
                           f" AS source_id FROM {table} WHERE id IN "
                           f"({','.join('?' * len(part))})", tuple(part))
    return out


def _model(store: Store, now: datetime, cfg: GradingConfig) -> _Model:
    snap = latest_snapshot(store)
    mu = _mu(store, snap)
    dim = int(mu.size) if mu is not None else None
    gr = graded(store, now, cfg)
    ideas = store.query("SELECT id, lineage_id FROM ideas ORDER BY id")
    raw = _card_raw(store, snap, dim, [int(r["id"]) for r in ideas])
    cites, ctops = _citations(store), _card_topics(store)
    items: dict[tuple[str, str], Item] = {}
    for r in ideas:
        i = int(r["id"])
        items[("idea", str(i))] = Item(
            ("idea", str(i)), _centre(raw.get(i), mu), frozenset(cites.get(i, ())), frozenset(),
            frozenset({str(r["lineage_id"])}) if r["lineage_id"] else frozenset(),
            frozenset(ctops.get(i, ())))
    stops = _source_topics(store)
    lineage_of = _lineages(store, snap)
    obs_ids = sorted(int(k[1]) for k in gr if k[0] == "observation")
    for at in range(0, len(obs_ids), 500):
        part = obs_ids[at:at + 500]
        for o in store.query("SELECT id, source_id, embedding FROM observations WHERE id IN "
                             f"({','.join('?' * len(part))}) ORDER BY id", tuple(part)):
            oid, sid = int(o["id"]), o["source_id"]
            items[("observation", str(oid))] = Item(
                ("observation", str(oid)), _centre(_vec(o["embedding"], dim), mu),
                frozenset({oid}), frozenset({int(sid)}) if sid is not None else frozenset(),
                frozenset({lineage_of[oid]}) if oid in lineage_of else frozenset(),
                frozenset(stops.get(int(sid), ())) if sid is not None else frozenset())
    return _Model(snap, items, gr)


def theme_items(store: Store, snapshot: int | None) -> dict[str, Item]:
    """The themes of a map as items: the centroid, the members, their
    sources and their sources' topics."""
    if snapshot is None:
        return {}
    mu = _mu(store, snapshot)
    dim = int(mu.size) if mu is not None else None
    stops = _source_topics(store)
    members: dict[int, set[int]] = {}
    srcs: dict[int, set[int]] = {}
    for r in store.query("SELECT p.cluster, p.observation_id, o.source_id FROM snapshot_points p "
                         "JOIN observations o ON o.id = p.observation_id WHERE p.snapshot_id = ?",
                         (snapshot,)):
        members.setdefault(int(r["cluster"]), set()).add(int(r["observation_id"]))
        if r["source_id"] is not None:
            srcs.setdefault(int(r["cluster"]), set()).add(int(r["source_id"]))
    out: dict[str, Item] = {}
    for r in store.query("SELECT cluster, lineage_id, centroid FROM clusters WHERE snapshot_id = ? "
                         "ORDER BY cluster", (snapshot,)):
        c, lin = int(r["cluster"]), str(r["lineage_id"])
        ss = srcs.get(c, set())
        out[lin] = Item(("theme", lin), _centre(_vec(r["centroid"], dim), mu),
                        frozenset(members.get(c, ())), frozenset(ss), frozenset({lin}),
                        frozenset(set().union(*(stops.get(s, set()) for s in ss)) if ss else ()))
    return out


# -- the function ---------------------------------------------------------------------------


def resemblance(c: Item, x: Item, cfg: GradingConfig) -> tuple[float, str]:
    """``r(c, x)`` in [0, 1] and its word: the strongest of the features, never a sum."""
    best, why = 0.0, ""
    shared = c.obs & x.obs
    if shared:                                 # the overlap coefficient: shared over the smaller
        f = len(shared) / min(len(c.obs), len(x.obs))
        best, why = f, ("cites the same evidence" if f >= 1
                        else f"shares {len(shared)} of its evidence")
    if c.themes & x.themes and best < 1.0:
        best, why = 1.0, "same theme"
    # vectors of two sizes (two embedding models, or no map to say which is current) are no
    # vector: the topic stands in, as when a side has none
    if c.vec is not None and x.vec is not None and c.vec.shape == x.vec.shape:
        cos = float(c.vec @ x.vec)
        f = min(1.0, max(0.0, (cos - cfg.cos_low) / (cfg.cos_high - cfg.cos_low)))
        if f > best:
            best, why = f, f"reads alike ({cos:.2f})"
    elif c.topics & x.topics and cfg.topic_weight > best:
        best, why = cfg.topic_weight, "same topic"
    return best, why


def parts_of(c: Item, model: _Model, cfg: GradingConfig) -> tuple[float, list[dict[str, Any]]]:
    """``taste(c)`` and each graded item's part of it, strongest first."""
    parts: list[dict[str, Any]] = []
    for key in sorted(model.graded, key=lambda k: (k[0], int(k[1]) if k[1].isdigit() else 0)):
        if key == c.key:
            continue
        x = model.items.get(key)
        if x is None:
            continue
        r, why = resemblance(c, x, cfg)
        if r <= 0:
            continue
        g = model.graded[key]
        w = round(g.weight * r, 4)
        if w == 0:
            continue
        parts.append({"weight": w, "why": why, "target": key[0], "target_id": key[1],
                      "value": g.value, "graded_at": g.created_at, "title": g.title})
    parts.sort(key=lambda p: (-abs(p["weight"]), p["target"], int(p["target_id"])))
    return round(sum(p["weight"] for p in parts), 3), parts


def line(own: str | None, parts: list[dict[str, Any]], cfg: GradingConfig) -> str:
    """The one line a card shows for its rank."""
    if own == "useful":
        return "you graded it useful"
    if own in ("not_useful", "wrong"):
        return "you graded it not useful"
    total = round(sum(p["weight"] for p in parts), 3)
    if not parts or abs(total) < 0.05:
        return ""
    weight = {"idea": 1.0, "observation": cfg.observation_weight}
    strong = [p for p in parts if abs(p["weight"]) >= cfg.strong_at * weight[p["target"]]]
    head = "ranked up: " if total > 0 else "ranked down: "
    bits = []
    for kind, noun, lead in (("idea", "card", "like"), ("observation", "observation", "near")):
        up = sum(1 for p in strong if p["target"] == kind and p["weight"] > 0)
        dn = sum(1 for p in strong if p["target"] == kind and p["weight"] < 0)
        words = []
        if up:
            words.append(f"{up} {noun}{'s' if up != 1 else ''} you upvoted")
        if dn:
            words.append(f"{dn} you downvoted" if up
                         else f"{dn} {noun}{'s' if dn != 1 else ''} you downvoted")
        if words:
            bits.append(f"{lead} " + " and ".join(words))
    if bits:
        return head + " · ".join(bits)
    return head + ("reads a little like what you upvoted" if total > 0
                   else "reads a little like what you downvoted")


def facts_of(card_json: Any) -> tuple[int, int, int]:
    """(asks, cited, sources) of a stored card, as ``cards.facts`` counts them; zeros when the
    stored card cannot be read (it is then listed as unreadable by the page, not here)."""
    from .ideate.cards import facts

    try:
        from .stored.cards import Card

        f = facts(Card.load(card_json))
    except Exception:                          # noqa: BLE001  a row the reader cannot type
        return (0, 0, 0)
    return (f["asks"], f["cited"], f["sources"])


def minute(now: datetime | None) -> datetime:
    return (now or utcnow()).replace(second=0, microsecond=0)


def rank(store: Store, now: datetime | None = None,
         cfg: GradingConfig | None = None) -> dict[int, Rank]:
    """Every card's rank, by id: ``position`` is its place (1 first) among the shown cards in
    ``key`` order, None on an unsupported card. Cached until a grade, a card, a map, the
    minute or the settings change."""
    cfg = settings(cfg)
    now = minute(now)
    fb = store.query_one("SELECT MAX(id) AS n FROM feedback")
    ic = store.query_one("SELECT MAX(id) AS n, COUNT(*) AS c FROM ideas")
    key = (fb["n"] if fb else None, ic["n"] if ic else None, ic["c"] if ic else 0,
           latest_snapshot(store), now.isoformat(), cfg)
    db = _db_key(store)
    with _LOCK:
        hit = _RANKS.get(db)
        if hit is not None and hit[0] == key:
            return hit[1]
    model = _model(store, now, cfg)
    own = {int(k[1]): g.value for k, g in model.graded.items() if k[0] == "idea"}
    out: dict[int, Rank] = {}
    shown: list[Rank] = []
    for r in store.query("SELECT id, status, card FROM ideas ORDER BY id"):
        i = int(r["id"])
        item = model.items[("idea", str(i))]
        t, parts = parts_of(item, model, cfg)
        mine = own.get(i)
        bucket = 0 if mine == "useful" else 2 if mine in ("not_useful", "wrong") else 1
        a, c, s = facts_of(r["card"])
        out[i] = Rank(i, t, parts, mine, line(mine, parts, cfg), (bucket, -t, -a, -c, -s, -i))
        if r["status"] == "shown":
            shown.append(out[i])
    for n, x in enumerate(sorted(shown, key=lambda x: x.key), 1):
        x.position = n
    with _LOCK:
        _RANKS[db] = (key, out, model)
    return out


def model(store: Store, now: datetime | None = None,
          cfg: GradingConfig | None = None) -> _Model:
    """The graded items behind ``rank`` (Your grades, the ideas run's themes)."""
    cfg = settings(cfg)
    rank(store, now, cfg)
    with _LOCK:
        return _RANKS[_db_key(store)][2]


def theme_tastes(store: Store, snapshot: int | None, now: datetime | None = None,
                 cfg: GradingConfig | None = None) -> dict[str, tuple[float, list[dict[str, Any]]]]:
    """Each theme of a map: its taste against the owner's graded items, and the parts."""
    cfg = settings(cfg)
    m = model(store, now, cfg)
    return {lin: parts_of(it, m, cfg) for lin, it in theme_items(store, snapshot).items()}


def summary(store: Store, now: datetime | None = None,
            cfg: GradingConfig | None = None) -> dict[str, Any]:
    """What the owner's grades did (Your grades,): the counts over the window,
    the cards they moved (the five that moved most), the next ideas run's themes in order with
    the ones it will skip, and the sources (``source_rule``)."""
    cfg = settings(cfg)
    now = minute(now)
    since = iso(now - timedelta(days=cfg.window_days))
    rows = store.query("SELECT target, value FROM feedback WHERE kind = 'grade' AND target IN "
                       "('idea', 'observation') AND created_at >= ?", (since,))
    counts = {"cards": sum(1 for r in rows if r["target"] == "idea" and r["value"] != "skip"),
              "evidence": sum(1 for r in rows if r["target"] == "observation"
                              and r["value"] != "skip"),
              "cleared": sum(1 for r in rows if r["value"] == "skip")}
    counts["grades"] = counts["cards"] + counts["evidence"]
    ranks = rank(store, now, cfg)
    titles = {int(r["id"]): r["title"] for r in store.query("SELECT id, title FROM ideas "
                                                             "WHERE status = 'shown'")}
    shown = [r for r in ranks.values() if r.position is not None]
    moved = [r for r in shown if r.taste != 0 and r.own is None]
    top = sorted(moved, key=lambda r: (-abs(r.taste), r.id))[:5]
    snap = latest_snapshot(store)
    themes: list[dict[str, Any]] = []
    names = {str(r["lineage_id"]): r["name"] for r in store.query(
        "SELECT lineage_id, name FROM clusters WHERE snapshot_id = ?", (snap,))} if snap else {}
    for lin, (t, parts) in theme_tastes(store, snap, now, cfg).items():
        if t == 0:
            continue
        themes.append({"lineage_id": lin, "name": names.get(lin) or "", "taste": t,
                       "skip": t <= cfg.theme_skip_below, "line": line(None, parts, cfg),
                       "parts": parts[:3]})
    themes.sort(key=lambda x: (-x["taste"], x["lineage_id"]))
    return {"window_days": cfg.window_days, "counts": counts,
            "ideas": {"shown": len(shown), "moved": len(moved),
                      "graded": sum(1 for r in shown if r.own is not None),
                      "still": len(shown) - len(moved) - sum(1 for r in shown if r.own),
                      "top": [{"id": r.id, "title": titles.get(r.id, ""), "taste": r.taste,
                               "line": r.line, "position": r.position} for r in top]},
            "themes": themes}
