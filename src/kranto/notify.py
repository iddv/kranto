"""The channel: what reaches a person.

Three kinds of message share one channel:

- ``strike``: rare and justified. Something crossed a threshold that is worth
  an interruption. Strikes are promoted from candidates by a gate.
- ``heartbeat``: patient silence made visible. Nothing crossed the threshold;
  here is what came closest.
- ``alarm``: broken silence made visible. A run failed, the key was rejected,
  the budget ran out.

Parallax had no channel. When its API key died, three months of failing runs
looked exactly like a quiet fleet. Here, every message is a row, the Atom
feed at ``/feed.xml`` serves them to any reader, and delivery to other targets
is layered on top.

``emit`` is idempotent on ``dedup_key``: the same event never produces two
messages, however many times it is reported.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from xml.sax.saxutils import escape

from .links import Links
from .store import Store, iso, utcnow
from .stored.misc import (
    CandidateDetail,
    CandidateEvidenceIds,
    CandidateLinks,
    MessageEvidenceIds,
    MessageLinks,
)

KINDS = ("strike", "heartbeat", "alarm")


def emit(
    store: Store,
    kind: str,
    title: str,
    body: str,
    *,
    dedup_key: str,
    origin: str,
    links: Iterable[str] = (),
    evidence_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> int | None:
    """Record a message. Returns its id, or None if this dedup_key already exists."""
    if kind not in KINDS:
        raise ValueError(f"message kind must be one of {', '.join(KINDS)}")
    if store.query_one("SELECT 1 FROM messages WHERE dedup_key = ?", (dedup_key,)):
        return None
    return store.insert("messages", {
        "kind": kind, "dedup_key": dedup_key, "origin": origin,
        "title": title.strip()[:200], "body": body.strip(),
        "links": MessageLinks.write(list(links)),
        "evidence_ids": MessageEvidenceIds.write(list(evidence_ids)),
        "created_at": iso(now or utcnow()),
    })


def record_candidate(
    store: Store,
    *,
    origin: str,
    subject_key: str,
    score: float,
    title: str,
    body: str,
    links: Iterable[str] = (),
    evidence_ids: Iterable[int] = (),
    detail: dict | None = None,
    run_uuid: str | None = None,
    now: datetime | None = None,
) -> int:
    """Record something that might deserve a strike. A gate decides later.

    ``subject_key`` identifies what the candidate is about across time (a
    lineage, a watch, an idea's evidence), so the gate can enforce a quiet
    period per subject.
    """
    return store.insert("strike_candidates", {
        "origin": origin, "subject_key": subject_key, "score": float(score),
        "title": title.strip()[:200], "body": body.strip(),
        "links": CandidateLinks.write(list(links)),
        "evidence_ids": CandidateEvidenceIds.write(list(evidence_ids)),
        "detail": CandidateDetail.write(detail or {}), "run_uuid": run_uuid,
        "created_at": iso(now or utcnow()),
    })


def alarm_for_run(store: Store, *, kind: str, run_uuid: str, status: str,
                  error: str | None) -> int | None:
    """One alarm per failed run. Other statuses are recorded on the runs table only.

    A run failed by a refused model key says it once for the key, not once a run:
    the first such run of any kind gives "Your OpenRouter key is refused (expired)", and the
    runs after it add nothing until this kind has run well again."""
    if status != "failed":
        return None
    from .activity import incidents
    got = incidents.classify(error)
    if got is not None and got["provider"] != "?":
        ok = store.query_one("SELECT MAX(finished_at) AS at FROM runs WHERE kind = ? "
                             "AND status = 'ok'", (kind,))
        after = (ok["at"] if ok is not None else None) or ""
        if store.query_one("SELECT 1 FROM messages WHERE dedup_key LIKE ? AND created_at >= ? "
                           "LIMIT 1", (f"auth:{got['provider']}:%", after)):
            return None
        what = (f"The key works: {kind}'s calls wait and try again on its next run"
                if got["cause"] == incidents.LOW_CREDIT else
                f"Every run that calls a model stops until it is renewed in "
                f"{incidents.KEY_PLACE}")
        return emit(
            store, "alarm", incidents.title(got["name"], got["cause"]),
            f"{incidents.title(got['name'], got['cause'])}: {error}. {what}; nothing it had not "
            "finished was marked as seen, and the next run after that picks up where this one "
            "stopped.",
            dedup_key=f"auth:{got['provider']}:{run_uuid}", origin=kind,
        )
    return emit(
        store, "alarm", f"{kind} run failed",
        f"The {kind} run {run_uuid[:8]} failed: {error or 'no error recorded'}. "
        "Nothing it had not finished was marked as seen; fix the cause and the next "
        "run picks up where this one stopped.",
        dedup_key=f"run-failed:{run_uuid}", origin=kind,
    )


def budget_alarm(store: Store, *, spent: float, budget: float, alarm_fraction: float,
                 now: datetime | None = None) -> int | None:
    """One alarm per month when spend crosses the alarm fraction, one when it is exhausted."""
    now = now or utcnow()
    month = iso(now)[:7]
    if budget > 0 and spent >= budget:
        return emit(
            store, "alarm", "Monthly budget exhausted",
            f"Spend this month is ${spent:.4f} of ${budget:.2f}. No model calls will be made "
            "until the month rolls over or the budget is raised.",
            dedup_key=f"budget-exhausted:{month}", origin="budget", now=now,
        )
    if budget > 0 and spent >= budget * alarm_fraction:
        return emit(
            store, "alarm", f"Spend passed {alarm_fraction:.0%} of the monthly budget",
            f"Spend this month is ${spent:.4f} of ${budget:.2f}.",
            dedup_key=f"budget-alarm:{month}", origin="budget", now=now,
        )
    return None


def recent_messages(store: Store, limit: int = 50, kind: str | None = None) -> list[dict]:
    where, params = ("WHERE kind = ?", (kind, limit)) if kind else ("", (limit,))
    rows = store.query(
        f"SELECT * FROM messages {where} ORDER BY id DESC LIMIT ?", params
    )
    out = []
    for r in rows:
        d = dict(r)
        d["links"] = MessageLinks.load(d["links"]).items
        d["evidence_ids"] = MessageEvidenceIds.load(d["evidence_ids"]).items
        out.append(d)
    return out


def atom_feed(store: Store, *, base_url: str, limit: int = 100, kranto: bool = False) -> str:
    """Messages as an Atom feed, newest first, so any feed reader can follow an instance.
    Entries link into Kranto UI when it is mounted (``kranto``)."""
    messages = recent_messages(store, limit)
    updated = messages[0]["created_at"] if messages else iso(utcnow())
    base = base_url.rstrip("/")
    to = Links(kranto, base)
    entries = []
    for m in messages:
        links = "".join(
            f'<link rel="related" href="{escape(url, {chr(34): "&quot;"})}"/>'
            for url in m["links"] if url.startswith(("http://", "https://"))
        )
        evidence = "".join(
            f'<link rel="related" href="{escape(to.observation(i))}"/>'
            for i in m["evidence_ids"]
        )
        entries.append(
            "<entry>"
            f"<id>urn:kranto:message:{m['id']}</id>"
            f"<title>[{m['kind']}] {escape(m['title'])}</title>"
            f"<updated>{m['created_at']}</updated>"
            f"<category term=\"{m['kind']}\"/>"
            f'<link rel="alternate" href="{escape(to.message(m["id"]))}"/>'
            f"{links}{evidence}"
            f'<content type="text">{escape(m["body"])}</content>'
            "</entry>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<title>kranto</title>"
        f"<id>urn:kranto:feed:{escape(base)}</id>"
        f'<link rel="self" href="{base}/feed.xml"/>'
        f"<updated>{updated}</updated>"
        "<author><name>kranto</name></author>"
        + "".join(entries)
        + "</feed>"
    )
