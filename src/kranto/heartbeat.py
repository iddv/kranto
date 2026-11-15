"""The weekly heartbeat: patient silence made distinguishable from broken silence.

Sent every week whether or not anything struck. It says what ran and how it
ended, what it cost, how much the library grew, how many strikes were sent,
which candidates came closest to a strike (score against threshold, and why
each was held back), and what exploration yielded: the fraction of items the
prefilter would have skipped that the judge kept anyway.

One heartbeat per ISO week (the message's dedup key), however often the job
runs. The job records a ``runs`` row of kind ``heartbeat`` so the scheduler
knows when it is next due.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import activity, gate, notify
from .config import Config
from .store import Store, iso, utcnow
from .stored import runs as stored_runs

WINDOW = timedelta(days=7)
CLOSEST = 3


def iso_week(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def dedup_key(now: datetime) -> str:
    return f"heartbeat:{iso_week(now)}"


def run_counts(store: Store, since: datetime) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in store.query(
        "SELECT kind, status, COUNT(*) AS n FROM runs WHERE finished_at >= ? AND kind != "
        "'heartbeat' GROUP BY kind, status ORDER BY kind", (iso(since),),
    ):
        out.setdefault(r["kind"], {})[r["status"]] = r["n"]
    return out


def exploration_yield(store: Store, since: datetime) -> list[dict[str, Any]]:
    """Observations added since ``since`` by how their item reached the judge.

    For exploration, also how many items were judged that way (from the
    ingest run summaries), so the yield is a rate, not just a count.
    """
    rows = [dict(r) for r in store.query(
        "SELECT COALESCE(admitted_by, 'unknown') AS admitted_by, COUNT(*) AS n, "
        "AVG(signal) AS mean_signal FROM observations WHERE created_at >= ? "
        "GROUP BY COALESCE(admitted_by, 'unknown') ORDER BY n DESC", (iso(since),))]
    explored = 0
    for r in store.query("SELECT summary FROM runs WHERE kind = 'ingest' AND finished_at >= ?",
                         (iso(since),)):
        explored += sum(s.explored for s in stored_runs.IngestSummary.load(r["summary"]).sources)
    by = {r["admitted_by"]: r for r in rows}
    if explored or "exploration" in by:
        entry = by.setdefault("exploration", {"admitted_by": "exploration", "n": 0,
                                              "mean_signal": None})
        if entry not in rows:
            rows.append(entry)
        entry["judged"] = explored
    return rows


@dataclass
class Heartbeat:
    title: str
    body: str
    stats: dict[str, Any]


def compact(n: int) -> str:
    """A token count as a reader takes it in: 950, 12k, 1.2M."""
    if n >= 999_500:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if n >= 10_000:
        return f"{n / 1_000:.0f}k"
    if n >= 1_000:
        return f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return str(n)


def compose(store: Store, cfg: Config, now: datetime) -> Heartbeat:
    since = now - WINDOW
    runs = run_counts(store, since)
    spend_week = store.spend_since(since)
    spend_month = store.month_spend(now)
    counted = store.query_one("SELECT COUNT(*) AS n FROM observations WHERE created_at >= ?",
                              (iso(since),))
    assert counted is not None                 # COUNT(*) always answers one row
    added = counted["n"]
    decisions = gate.recent_decisions(store, since=since, limit=10_000)
    strikes = sum(1 for d in decisions if d["promoted"])
    held: dict[str, int] = {}
    for d in decisions:
        if not d["promoted"]:
            held[d["reason"]] = held.get(d["reason"], 0) + 1
    closest = gate.closest(store, since=since, limit=CLOSEST)
    exploration = exploration_yield(store, since)

    lines = [f"Week {iso_week(now)}: {since.date().isoformat()} to {now.date().isoformat()}."]
    if strikes:
        lines.append(f"{strikes} strike{'s' if strikes != 1 else ''} sent this week.")
    else:
        lines.append("No strikes this week. Nothing crossed a threshold; quiet is the "
                     "expected state, and this message is here so quiet is not mistaken "
                     "for broken.")
    lines.append("\nRuns:")
    if runs:
        for kind, counts in runs.items():
            parts = ", ".join(f"{counts[s]} {s}" for s in ("ok", "degraded", "failed", "skipped")
                              if counts.get(s))
            lines.append(f"- {kind}: {parts}")
    else:
        lines.append("- none. If the scheduler or cron is meant to be running, it is not.")
    # Tokens, not dollars (the owner's ruling, 2026-10-09): what a call costs depends on the
    # model and its price that day; Settings › Spend has the dollars and the cap.
    used = store.tokens_since(since)
    lines.append("\nModel calls: " + (f"{compact(used['in'])} tokens in, "
                                      f"{compact(used['out'])} out in these 7 days."
                                      if used else "none in these 7 days."))
    lines.append(f"Observations added: {added}.")
    decided = len(decisions)
    lines.append(f"Strike candidates decided: {decided}"
                 + (" (held back: " + ", ".join(f"{n} {r.replace('_', ' ')}"
                                                 for r, n in sorted(held.items())) + ")"
                    if held else "") + ".")
    lines.append("\nClosest to a strike:")
    if closest:
        for c in closest:
            # a candidate decided no_threshold has none to be held against
            against, t = "with no threshold", c.get("threshold")
            if t is not None:
                against = f"against threshold {t:.3f}"
            lines.append(f"- {c['origin']} {c['score']:.3f} {against} "
                         f"({c['reason'].replace('_', ' ')}): {c['title']}")
    else:
        lines.append("- no candidates were held back this week.")
    lines.append("\nExploration yield (observations added, by how the item was admitted):")
    if exploration:
        for e in exploration:
            mean = f", mean signal {e['mean_signal']:.2f}" if e["mean_signal"] is not None else ""
            if e["admitted_by"] == "exploration":
                judged = e.get("judged", 0)
                rate = f" ({e['n'] / judged:.0%})" if judged else ""
                lines.append(f"- exploration: {e['n']} kept of {judged} judged{rate}{mean}")
            else:
                lines.append(f"- {e['admitted_by']}: {e['n']}{mean}")
    else:
        lines.append("- no observations were added.")

    stats = {
        "week": iso_week(now), "runs": runs, "spend_week_usd": round(spend_week, 6),
        "spend_month_usd": round(spend_month, 6), "tokens_week": used,
        "observations_added": added,
        "strikes": strikes, "candidates_decided": decided, "held": held,
        "closest": [{k: c[k] for k in ("candidate_id", "origin", "score", "threshold",
                                       "reason", "title")} for c in closest],
        "exploration": exploration,
    }
    # in the page's words: "Heartbeat 2026-W46: 0 strikes, 0 new
    # observations" read as jargon on Needs you
    urgent = "nothing urgent" if not strikes else f"{strikes} strike{'s' if strikes != 1 else ''}"
    title = f"This week: {urgent}, {added} new item{'s' if added != 1 else ''} kept"
    return Heartbeat(title, "\n".join(lines), stats)


@dataclass
class HeartbeatReport:
    run_uuid: str
    message_id: int | None
    already_sent: bool
    heartbeat: Heartbeat


def send_heartbeat(store: Store, cfg: Config, *, now: datetime | None = None,
                   after_first_read: bool = False) -> HeartbeatReport:
    """Emit this week's heartbeat (once per ISO week) and record the run. ``after_first_read``
    (the server's job): none until a read has ended."""
    now = now or utcnow()
    beat = compose(store, cfg, now)
    if after_first_read and store.query_one(
            "SELECT 1 FROM runs WHERE kind = 'ingest' AND status != 'skipped' LIMIT 1") is None:
        # the scheduler's on a new home (fix 13): no heartbeat on Needs you
        # before the first read has ended; a skip, so it looks again within the hour. ``kranto
        # heartbeat --now`` still sends one (it says when nothing ran).
        report = HeartbeatReport(activity.run_uuid("heartbeat"), None, False, beat)
        store.insert("runs", {"run_uuid": report.run_uuid, "kind": "heartbeat",
                              "status": "skipped", "started_at": iso(now),
                              "finished_at": iso(now), "summary": "{}",
                              "error": "nothing read yet"})
        return report
    message_id = notify.emit(store, "heartbeat", beat.title, beat.body,
                             dedup_key=dedup_key(now), origin="heartbeat", now=now)
    report = HeartbeatReport(activity.run_uuid("heartbeat"), message_id, message_id is None, beat)
    # Recorded as ok even when this week's heartbeat already existed: a skipped
    # run does not count as done for the scheduler, which would retry every tick.
    store.insert("runs", {
        "run_uuid": report.run_uuid, "kind": "heartbeat", "status": "ok",
        "started_at": iso(now), "finished_at": iso(now),
        "summary": stored_runs.text_for("heartbeat", {"message_id": message_id,
                                                      "already_sent": message_id is None,
                                                      **beat.stats}),
        "error": None,
    })
    return report
