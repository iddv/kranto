"""The strike gate: which candidates are worth an interruption.

Candidates come from idea cards (``card``) and bursts in the map (``burst``).
(Watches, origin ``watch``, were retired; their old candidates keep their decisions.)
Each is decided exactly once, and every decision is a
row in ``strike_decisions`` with its reason, promoted or not, so "why did it
not tell me" always has an answer.

The rules follow the peak detector in Huginn (MIT): an absolute threshold, a
refractory period, and a warm-up. In the order they are checked:

1. ``no_threshold``: the origin has no configured threshold.
2. ``below_threshold``: the score is under the origin's threshold. Scores are
   on different scales per origin (a product of five ratings, ``1 - q``, a
   cosine similarity), so the thresholds are per origin.
3. ``stale``: the candidate is older than a week when the gate first sees it.
   A week-old burst is history, not news.
4. ``warmup``: the library has fewer map snapshots than ``warmup_snapshots``, or
   its first map is younger than ``warmup_days``. Snapshot count alone was met by
   two maps taken minutes apart, and a new library struck within the hour.
5. ``refractory``: a strike about the same subject was sent less than
   ``refractory_days`` ago.
6. ``weekly_cap``: ``max_per_week`` strikes were already sent in the last
   seven days (a rolling window, so the cap cannot be doubled across a
   calendar boundary).

Otherwise the candidate is ``promoted`` to a ``messages`` row of kind
``strike``. Within one pass, candidates are considered strongest first (score
over threshold), so a weak candidate cannot take the week's last slot from a
strong one recorded in the same run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import notify
from .config import StrikeConfig
from .store import Store, iso, utcnow
from .stored.misc import CandidateEvidenceIds, CandidateLinks

STALE_AFTER = timedelta(days=7)
WEEK = timedelta(days=7)
REASONS = ("promoted", "below_threshold", "no_threshold", "warmup", "refractory",
           "weekly_cap", "stale")


@dataclass(frozen=True)
class Decision:
    candidate_id: int
    origin: str
    subject_key: str
    score: float
    threshold: float | None
    promoted: bool
    reason: str
    detail: str
    message_id: int | None = None


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def pending(store: Store) -> list:
    return store.query(
        "SELECT c.* FROM strike_candidates c WHERE NOT EXISTS "
        "(SELECT 1 FROM strike_decisions d WHERE d.candidate_id = c.id) ORDER BY c.id"
    )


def _strength(row, cfg: StrikeConfig) -> float:
    threshold = cfg.threshold(row["origin"])
    if threshold is None:
        return float("-inf")
    return row["score"] / threshold if threshold > 0 else float("inf")


def run_gate(store: Store, cfg: StrikeConfig, *, now: datetime | None = None) -> list[Decision]:
    """Decide every undecided candidate. Returns the decisions made in this pass."""
    now = now or utcnow()
    rows = sorted(pending(store), key=lambda r: (-_strength(r, cfg), r["id"]))
    return [_decide(store, cfg, row, now) for row in rows]


def _decide(store: Store, cfg: StrikeConfig, c, now: datetime) -> Decision:
    origin, score = c["origin"], float(c["score"])
    threshold = cfg.threshold(origin)
    with store.tx():
        # Checked inside the transaction: a concurrent gate (cron and server) may
        # have decided this candidate since it was listed.
        existing = store.query_one(
            "SELECT * FROM strike_decisions WHERE candidate_id = ?", (c["id"],))
        if existing is not None:
            return Decision(c["id"], origin, c["subject_key"], score, existing["threshold"],
                            bool(existing["promoted"]), existing["reason"], existing["detail"],
                            existing["message_id"])
        reason, detail = _check(store, cfg, c, threshold, score, now)
        message_id = None
        if reason == "promoted":
            message_id = _promote(store, c, threshold, now)
        store.insert("strike_decisions", {
            "candidate_id": c["id"], "promoted": int(reason == "promoted"), "reason": reason,
            "threshold": threshold, "detail": detail, "message_id": message_id,
            "created_at": iso(now),
        })
    return Decision(c["id"], origin, c["subject_key"], score, threshold, reason == "promoted",
                    reason, detail, message_id)


def _check(store: Store, cfg: StrikeConfig, c, threshold: float | None, score: float,
           now: datetime) -> tuple[str, str]:
    origin = c["origin"]
    if threshold is None:
        return "no_threshold", f"no strike threshold is configured for origin '{origin}'"
    if score < threshold:
        return "below_threshold", (f"score {score:.3f} is below the {origin} threshold "
                                   f"{threshold:.3f}")
    age = now - _parse(c["created_at"])
    if age > STALE_AFTER:
        return "stale", (f"recorded {age.days} days before the gate saw it; older than "
                         f"{STALE_AFTER.days} days is history, not news")
    snapshots = store.query_one(
        "SELECT COUNT(*) AS n FROM snapshots WHERE created_at <= ?", (iso(now),))["n"]
    if snapshots < cfg.warmup_snapshots:
        return "warmup", (f"warming up: {snapshots} of {cfg.warmup_snapshots} map snapshots "
                          "taken; no strikes until the library has a baseline")
    first = store.query_one("SELECT MIN(created_at) AS t FROM snapshots")["t"]
    if cfg.warmup_days > 0 and first and \
            now - _parse(first) < timedelta(days=cfg.warmup_days):
        return "warmup", (f"warming up: the first map is from {first}; no strikes until it "
                          f"is {cfg.warmup_days:g} days old")
    if cfg.refractory_days > 0:
        last = store.query_one(
            "SELECT d.created_at, d.message_id FROM strike_decisions d "
            "JOIN strike_candidates s ON s.id = d.candidate_id "
            "WHERE d.promoted = 1 AND s.subject_key = ? ORDER BY d.id DESC LIMIT 1",
            (c["subject_key"],))
        if last and now - _parse(last["created_at"]) < timedelta(days=cfg.refractory_days):
            return "refractory", (f"a strike about {c['subject_key']} was sent at "
                                  f"{last['created_at']} (message {last['message_id']}); quiet "
                                  f"for {cfg.refractory_days:g} days after a strike")
    sent = store.query_one(
        "SELECT COUNT(*) AS n FROM strike_decisions WHERE promoted = 1 AND created_at > ?",
        (iso(now - WEEK),))["n"]
    if sent >= cfg.max_per_week:
        return "weekly_cap", (f"{sent} strikes already sent in the last 7 days; the cap is "
                              f"{cfg.max_per_week}")
    return "promoted", f"score {score:.3f} reached the {origin} threshold {threshold:.3f}"


def _promote(store: Store, c, threshold: float, now: datetime) -> int:
    key = f"strike:candidate:{c['id']}"
    body = (f"{c['body']}\n\nWhy this reached you: {c['origin']} score {c['score']:.3f} "
            f"against a threshold of {threshold:.3f}.")
    message_id = notify.emit(
        store, "strike", c["title"], body, dedup_key=key, origin=c["origin"],
        links=CandidateLinks.load(c["links"]).items,
        evidence_ids=CandidateEvidenceIds.load(c["evidence_ids"]).items, now=now,
    )
    if message_id is None:
        message_id = store.query_one("SELECT id FROM messages WHERE dedup_key = ?", (key,))["id"]
    return message_id


def recent_decisions(store: Store, *, since: datetime | None = None, limit: int = 50) -> list[dict]:
    """Decisions joined with their candidates, newest first."""
    where, params = ("WHERE d.created_at >= ?", (iso(since), limit)) if since else ("", (limit,))
    rows = store.query(
        "SELECT d.id AS decision_id, d.promoted, d.reason, d.threshold, d.detail, d.message_id, "
        "d.created_at AS decided_at, c.id AS candidate_id, c.origin, c.subject_key, c.score, "
        "c.title, c.created_at FROM strike_decisions d "
        f"JOIN strike_candidates c ON c.id = d.candidate_id {where} ORDER BY d.id DESC LIMIT ?",
        params,
    )
    return [dict(r) for r in rows]


def closest(store: Store, *, since: datetime, limit: int = 3) -> list[dict]:
    """Candidates decided since ``since`` that were not promoted, nearest the threshold first."""
    rows = [r for r in recent_decisions(store, since=since, limit=10_000)
            if not r["promoted"] and r["threshold"] is not None]
    for r in rows:
        r["ratio"] = r["score"] / r["threshold"] if r["threshold"] > 0 else float("inf")
    rows.sort(key=lambda r: (-r["ratio"], -r["candidate_id"]))
    return rows[:limit]
