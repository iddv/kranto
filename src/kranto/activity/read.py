"""the server's half of the one activity read: ``GET /api/activity``.

    {"seq", "running": [Run], "waiting": [Run], "next": [Scheduled], "recent": [Run],
     "folded": [Fold], "failing": [Fail], "counts": {...}, "quiet": "..."}

- **running**: the runs in progress in this process (their words as of now, before the writer's
  next batch), and any other process's whose ``started`` has no end and whose process lives
  (``python -m kranto run`` beside the server);
- **waiting**: runs that stopped for the owner whose subject still waits (a cub's update
  not yet confirmed);
- **next**: each scheduled kind that is on, soonest first, with its last run and whether it
  is failing;
- **recent**: the last day's runs, newest first; the hourly skipped re-checks and the usage
  reports **folded** into one line a kind (``all=1`` unfolds);
- **failing**: the Fix rows (the owner's D-6): a kind that failed twice in a row or has
  been failing for two days, until its next good run or the owner's Dismiss.

Bounded (``LIMIT``, ``LIMIT_MAX``), every word scrubbed at write and passed through
``words.plain`` here, no payload. Nothing is written.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from ..store import Store, iso, utcnow
from ..stored.activity import Needs
from ..stored.runs import RunSummary
from . import find, incidents, open_runs
from . import words as W

LIMIT = 50
LIMIT_MAX = 500
RECENT_HOURS = 24
FAILING_DAYS = 2            # failing this long reaches Needs you after one failure (D-6)
FAILING_IN_A_ROW = 2
WAITING_DAYS = 14           # a waiting run whose subject cannot be checked stays open this long
STOPPABLE = frozenset({"ingest", "news.brief"})
FOLD_ALWAYS = frozenset({"telemetry"})        # a row an hour that is never news
QUIET_SKIP = frozenset({"telemetry", "cubs.gc", "cubs.updates", "xrecheck", "heartbeat"})


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _summary(raw: object) -> dict[str, Any]:
    """A run's summary as the activity reads it: its keys, any kind (``stored.runs``); {} for
    NULL, broken JSON or a non-object."""
    return RunSummary.load(raw if isinstance(raw, (str, bytes, dict)) else None).to_dict()


def _why(status: str, summary: dict[str, Any], error: str | None) -> str | None:
    """Why a run skipped or failed, in its own words."""
    for k in ("why", "line", "note"):
        if isinstance(summary.get(k), str) and summary[k]:
            return W.plain(summary[k])
    if summary.get("not_due") and not summary.get("briefs"):
        return "nothing was due"
    if error:
        return W.plain(error)
    return None


class Reader:
    """One read of the activity: the store, the scheduler (None: none in this process), the
    features' titles (for a kind without words of its own) and the cubs' job kinds (stoppable
    between host calls)."""

    def __init__(self, store: Store, scheduler: Any = None, *, titles: dict[str, Any] | None = None,
                 cub_kinds: set[Any] | None = None, now: datetime | None = None,
                 cfg: Any = None, off_kinds: set[Any] | None = None) -> None:
        self.store, self.scheduler, self.cfg = store, scheduler, cfg
        from . import settle
        settle(store)                       # what this process queued is in what it reads
        self.titles = titles or {}
        self.cub_kinds = set(cub_kinds or ())
        # the jobs of a feature that is off: what they left waiting is not drawn while it is
        # off (.2: no row for a feature that is off); turned on, it is back
        from .words import RETIRED_KINDS
        self.off_kinds = set(off_kinds or ()) | RETIRED_KINDS
        self.now = now or utcnow()

    # -- one run --------------------------------------------------------------------------------

    def _feature_title(self, kind: str) -> str | None:
        return self.titles.get(kind.partition(".")[0])

    def _cost(self, uuids: list[str]) -> dict[str, dict[str, Any]]:
        if not uuids:
            return {}
        marks = ",".join("?" * len(uuids))
        rows = self.store.query(
            f"SELECT run_uuid, COUNT(*) AS n, COALESCE(SUM(cost_usd), 0) AS usd, "
            f"COALESCE(SUM(prompt_tokens), 0) AS tin, COALESCE(SUM(completion_tokens), 0) AS tout "
            f"FROM llm_calls WHERE run_uuid IN ({marks}) GROUP BY run_uuid", tuple(uuids))
        return {r["run_uuid"]: {"calls": int(r["n"]), "usd": round(float(r["usd"]), 4),
                                "tokens": {"in": int(r["tin"]), "out": int(r["tout"])}}
                for r in rows}

    def _marks(self, uuids: list[str]) -> dict[str, dict[str, Any]]:
        """Each run's started mark and its newest words, waiting and ended marks."""
        if not uuids:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for chunk in (uuids[i:i + 400] for i in range(0, len(uuids), 400)):
            marks = ",".join("?" * len(chunk))
            for m in self.store.query(
                    f"SELECT * FROM run_marks WHERE run_uuid IN ({marks}) ORDER BY id",
                    tuple(chunk)):
                d = out.setdefault(m["run_uuid"], {})
                d.setdefault("first", dict(m))
                if m["mark"] == "started":
                    d["started"] = dict(m)
                elif m["mark"] in ("progress", "waiting", "ended", "stopping"):
                    d[m["mark"]] = dict(m)
                    if m["words"]:
                        d["words"] = m["words"]
                    if m["step"] is not None:
                        d["step"], d["steps"] = m["step"], m["steps"]
        return out

    def view(self, *, uuid: str, kind: str, state: str, started: str | None,
             finished: str | None = None, marks: dict[str, Any] | None = None,
             error: str | None = None, summary: dict[str, Any] | None = None,
             cost: dict[str, Any] | None = None, live: Any = None) -> dict[str, Any]:
        marks = marks or {}
        st = marks.get("started") or {}
        wait = marks.get("waiting") or {}
        subject = None
        sub = wait if wait.get("subject_kind") else st
        if sub.get("subject_kind"):
            subject = {"kind": sub["subject_kind"], "id": sub.get("subject_id"),
                       "name": sub.get("subject_name")}
        if live is not None and live.subject:
            subject = {"kind": str(live.subject[0]),
                       "id": str(live.subject[1]) if len(live.subject) > 1 else None,
                       "name": live.subject[2] if len(live.subject) > 2 else None}
        words = (live.words if live is not None else None) or marks.get("words")
        if state == "waiting":
            words = wait.get("words") or words
        step = live.step if live is not None else marks.get("step")
        steps = live.steps if live is not None else marks.get("steps")
        title = (live.title if live is not None else None) or st.get("title") or W.title_of(
            kind, state, self._feature_title(kind), subject.get("name") if subject else None)
        a, b = _ts(started), _ts(finished) if finished else self.now
        cost = cost or {}
        needs = None
        if state == "waiting" and wait.get("needs"):
            got = Needs.parse(wait["needs"])
            needs = got.to_dict() if got is not None else None
        summary = summary or {}
        stoppable = state == "running" and find(uuid) is not None and (
            kind in STOPPABLE or kind in self.cub_kinds)
        return {
            "id": f"afk:{uuid}", "uuid": uuid, "kind": kind, "title": W.plain(title),
            "words": W.plain(words), "state": state,
            "glyph": W.STATES.get(state, ("", ""))[0],
            "trigger": {"origin": (live.origin if live is not None else st.get("trigger"))
                        or "schedule",
                        "by": live.by if live is not None else st.get("by"), "at": started},
            "subject": subject, "feature": kind.partition(".")[0] if "." in kind else "core",
            "started": started, "finished": finished,
            "elapsed_s": round((b - a).total_seconds(), 1) if a and b else None,
            "usd": cost.get("usd", 0.0), "calls": cost.get("calls", 0),
            "tokens": cost.get("tokens"),
            "progress": {"step": step, "steps": steps} if step is not None else None,
            "trace": f"#/afk/{uuid}/trace", "stoppable": stoppable,
            "stopping": bool(marks.get("stopping")) or bool(live and live.stop_requested()),
            "needs": needs, "error": W.plain(error) if state == "failed" else None,
            "why": _why(state, summary, error) if state in ("skipped", "stopped", "degraded")
            else None,
            "verb": W.forms(kind, self._feature_title(kind))["verb"] if state == "failed"
            else None,
        }

    # -- the groups -----------------------------------------------------------------------------

    def running(self) -> list[dict[str, Any]]:
        from .. import proc
        live = {r.uuid: r for r in open_runs() if r.store is self.store}
        since = iso(self.now - timedelta(days=2))
        rows = self.store.query(
            "SELECT m.run_uuid, m.kind, m.ts, m.pid, m.pstart FROM run_marks m "
            "WHERE m.mark = 'started' AND m.ts >= ? AND NOT EXISTS (SELECT 1 FROM run_marks e "
            "WHERE e.run_uuid = m.run_uuid AND e.mark = 'ended') AND NOT EXISTS (SELECT 1 FROM "
            "runs r WHERE r.run_uuid = m.run_uuid) ORDER BY m.id", (since,))
        found = [r for r in rows if r["run_uuid"] in live or proc.running(r["pid"], r["pstart"])]
        uuids = list({*live, *[r["run_uuid"] for r in found]})
        marks, cost = self._marks(uuids), self._cost(uuids)
        out: list[dict[str, Any]] = []
        for r in found:
            u = r["run_uuid"]
            with _row(out, u, r["kind"], "running"):
                out.append(self.view(uuid=u, kind=r["kind"], state="running", started=r["ts"],
                                     marks=marks.get(u), cost=cost.get(u), live=live.get(u)))
        for u, run in live.items():              # started, not yet committed: never
            if u not in {x.get("uuid") for x in out}:
                with _row(out, u, run.kind, "running"):
                    out.append(self.view(uuid=u, kind=run.kind, state="running",
                                         started=iso(run.started), marks=marks.get(u),
                                         cost=cost.get(u), live=run))
        return out[:LIMIT]

    def _still_waits(self, uuid: str, kind: str, mark: dict[str, Any]) -> bool:
        if kind == "cub.update":
            # the cub's update still waits for the press: its job's last step (cubs/install.py)
            row = self.store.query_one(
                "SELECT 1 FROM cub_installs c WHERE c.cub = ? AND c.kind = 'update' "
                "AND c.step = 'awaiting_confirm' AND c.id = (SELECT MAX(x.id) FROM "
                "cub_installs x WHERE x.job_id = c.job_id) LIMIT 1", (mark.get("subject_id"),))
            return row is not None
        if kind == "verb":
            # a prepared item waits while it is open (a filed issue's "Prepared: File a
            # Kranto issue" stayed in Needs you for a week after the owner filed it)
            run = self.store.query_one("SELECT summary FROM runs WHERE run_uuid = ?", (uuid,))
            pid = _summary(run["summary"]).get("prepared") if run is not None else None
            if pid:
                p = self.store.query_one(
                    "SELECT state, expires_at FROM prepared WHERE prepared_uuid = ? "
                    "ORDER BY id DESC LIMIT 1", (str(pid),))
                return p is not None and p["state"] == "open" and \
                    (not p["expires_at"] or p["expires_at"] >= iso(self.now))
        at = _ts(mark.get("ts"))
        return at is not None and self.now - at < timedelta(days=WAITING_DAYS)

    def waiting(self) -> list[dict[str, Any]]:
        since = iso(self.now - timedelta(days=WAITING_DAYS))
        rows = self.store.query(
            "SELECT m.* FROM run_marks m WHERE m.mark = 'waiting' AND m.ts >= ? "
            "AND m.id = (SELECT MAX(x.id) FROM run_marks x WHERE x.run_uuid = m.run_uuid "
            "AND x.mark = 'waiting') ORDER BY m.id DESC LIMIT ?", (since, LIMIT))
        keep = [dict(r) for r in rows if r["kind"] not in self.off_kinds
                and self._still_waits(r["run_uuid"], r["kind"], dict(r))]
        # one waiting run per subject: the newest says it
        seen: set[Any] = set()
        out: list[dict[str, Any]] = []
        uuids = [r["run_uuid"] for r in keep]
        marks, cost = self._marks(uuids), self._cost(uuids)
        ends = {r["run_uuid"]: dict(r) for r in self.store.query(
            f"SELECT run_uuid, started_at, finished_at FROM runs WHERE run_uuid IN "
            f"({','.join('?' * len(uuids))})", tuple(uuids))} if uuids else {}
        for r in keep:
            key = (r["kind"], r["subject_kind"], r["subject_id"])
            if key in seen:
                continue
            seen.add(key)
            e = ends.get(r["run_uuid"]) or {}
            with _row(out, r["run_uuid"], r["kind"], "waiting"):
                out.append(self.view(uuid=r["run_uuid"], kind=r["kind"], state="waiting",
                                     started=e.get("started_at") or r["ts"],
                                     finished=e.get("finished_at") or r["ts"],
                                     marks=marks.get(r["run_uuid"]),
                                     cost=cost.get(r["run_uuid"])))
        return out

    def recent(self, *, hours: float = RECENT_HOURS, limit: int = LIMIT, unfold: bool = False,
               kind: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        since = iso(self.now - timedelta(hours=hours))
        args: list[Any] = [since]
        where = "finished_at >= ?"
        if kind:
            where += " AND kind = ?"
            args.append(kind)
        rows = [dict(r) for r in self.store.query(
            f"SELECT run_uuid, kind, status, started_at, finished_at, summary, error FROM runs "
            f"WHERE {where} ORDER BY finished_at DESC LIMIT ?", (*args, LIMIT_MAX * 4))]
        # runs that ended with no runs row (a job that raised, one cut off by a restart)
        bare = [dict(r) for r in self.store.query(
            "SELECT e.run_uuid, e.kind, e.state AS status, e.ts AS finished_at, e.error, "
            "e.words, (SELECT s.ts FROM run_marks s WHERE s.run_uuid = e.run_uuid AND "
            "s.mark = 'started' LIMIT 1) AS started_at FROM run_marks e WHERE e.mark = 'ended' "
            "AND e.ts >= ? " + ("AND e.kind = ? " if kind else "") +
            "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_uuid = e.run_uuid) "
            "ORDER BY e.id DESC LIMIT ?", (*args, LIMIT_MAX))]
        for b in bare:
            b["summary"] = json.dumps({"note": b.pop("words")} if b.get("words") else {})
        rows = sorted(rows + bare, key=lambda r: r["finished_at"] or "", reverse=True)
        stopped = {r["run_uuid"] for r in self.store.query(
            "SELECT run_uuid FROM run_marks WHERE mark = 'ended' AND state = 'stopped' "
            "AND ts >= ?", (since,))}
        waiting = {r["run_uuid"] for r in self.store.query(
            "SELECT run_uuid FROM run_marks WHERE mark = 'waiting' AND ts >= ?", (since,))}
        shown: list[dict[str, Any]] = []
        folds: dict[Any, Any] = {}
        for r in rows:
            status = "stopped" if r["run_uuid"] in stopped or \
                _summary(r["summary"]).get("stopped_by") else r["status"]
            fold = not unfold and (status == "skipped" or r["kind"] in FOLD_ALWAYS) \
                and r["run_uuid"] not in waiting
            if fold:
                f = folds.setdefault((r["kind"], status), {"kind": r["kind"], "state": status,
                                                            "n": 0, "first": r["finished_at"],
                                                            "last": r["finished_at"],
                                                            "why": None})
                f["n"] += 1
                if r["kind"] == "telemetry":
                    # a usage report counts as sent only when one was posted (
                    # fix 14: "1 sent today" on a home with reports off)
                    posted = (_summary(r["summary"]) or {}).get("posted")
                    f["sent"] = f.get("sent", 0) + (1 if isinstance(posted, list) and posted
                                                    else 0)
                f["first"] = r["finished_at"]
                f["why"] = f["why"] or _why(status, _summary(r["summary"]), r["error"])
                continue
            if len(shown) < limit:
                shown.append({**r, "status": status})
        uuids = [r["run_uuid"] for r in shown]
        marks, cost = self._marks(uuids), self._cost(uuids)
        out: list[dict[str, Any]] = []
        for r in shown:
            with _row(out, r["run_uuid"], r["kind"], r["status"]):
                out.append(self.view(uuid=r["run_uuid"], kind=r["kind"], state=r["status"],
                                     started=r["started_at"], finished=r["finished_at"],
                                     marks=marks.get(r["run_uuid"]), error=r["error"],
                                     summary=_summary(r["summary"]),
                                     cost=cost.get(r["run_uuid"])))
        folded = []
        for f in sorted(folds.values(), key=lambda f: f["last"] or "", reverse=True)[:LIMIT]:
            t = W.title_of(f["kind"], "scheduled", self._feature_title(f["kind"]))
            what = "skipped" if f["state"] == "skipped" else W.STATES.get(f["state"],
                                                                         ("", "ran"))[1]
            line = f"{t} · {what} {f['n']} time{'' if f['n'] == 1 else 's'} today"
            if f["kind"] == "telemetry" and f["state"] == "ok":
                sent = int(f.pop("sent", 0) or 0)
                line = f"{t} · {sent} sent today" if sent else f"{t} · counted here, not sent"
            folded.append({**f, "title": W.plain(t),
                           "line": W.plain(line + (f": {f['why']}" if f["why"] else "")),
                           "why": W.plain(f["why"])})
        return out, folded

    def failing(self) -> list[dict[str, Any]]:
        """The Fix rows: a kind failing twice in a row, or for ``FAILING_DAYS``; one a kind.
        A kind an incident holds (a refused model key) has none: the incident says it."""
        return self._scan()[0]

    def incidents(self) -> list[dict[str, Any]]:
        """The blocking incidents: one a provider whose key is refused, from the
        first failure, naming every kind it stops."""
        return self._scan()[1]

    def _scan(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if getattr(self, "_scanned", None) is None:
            self._scanned = self._scan_now()
        return self._scanned

    def _scan_now(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        since = iso(self.now - timedelta(days=30))
        rows = self.store.query(
            "SELECT rowid AS rid, run_uuid, kind, status, error, finished_at FROM runs "
            "WHERE finished_at >= ? "
            # a skipped run with no error ran and found nothing to do: it ends a failing streak
            # (Toot's one failure of 21 Oct stayed a Fix row for a week of skipped runs)
            "AND (status != 'skipped' OR error IS NULL OR kind = 'update') "
            "ORDER BY kind, finished_at DESC", (since,))
        bare = self.store.query(
            "SELECT e.id AS rid, e.run_uuid, e.kind, e.state AS status, e.error, "
            "e.ts AS finished_at "
            "FROM run_marks e WHERE e.mark = 'ended' AND e.state = 'failed' AND e.ts >= ? "
            "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_uuid = e.run_uuid)", (since,))
        # a run that had nothing to do is no row now: its ended mark, skipped
        # with no error, still ends a failing streak
        quiet = self.store.query(
            "SELECT e.id AS rid, e.run_uuid, e.kind, e.state AS status, e.error, "
            "e.ts AS finished_at "
            "FROM run_marks e WHERE e.mark = 'ended' AND e.state = 'skipped' "
            "AND e.error IS NULL AND e.ts >= ? "
            "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_uuid = e.run_uuid)", (since,))
        by: dict[str, list[Any]] = {}
        for r in [*rows, *bare, *quiet]:
            # what an off feature's runs left, or a retired one's, is no Fix row and no incident
            # while it is off
            if r["kind"] in self.off_kinds:
                continue
            by.setdefault(r["kind"], []).append(dict(r))
        dismissed = {r["kind"]: (r["id"], r["ts"]) for r in self.store.query(
            "SELECT kind, MAX(id) AS id, MAX(ts) AS ts FROM run_marks WHERE mark = 'dismissed' "
            "GROUP BY kind")}
        held: dict[str, list[dict[str, Any]]] = {}     # provider: its kinds' failed runs
        vague: list[tuple[str, list[dict[str, Any]]]] = []
        out: list[dict[str, Any]] = []
        for kind, rs in by.items():
            tries = _tries(kind, rs)
            got = incidents.classify(tries[0]["error"]) if tries else None
            if got is not None and got["provider"] == "?":
                vague.append((kind, tries))
                continue
            if got is not None:
                held.setdefault(got["provider"], []).extend(
                    {**t, "kind": kind, "_auth": incidents.classify(t["error"]) or got}
                    for t in tries)
                continue
            with _row(out, f"fail:{kind}", kind, "failing"):
                row = self._fail_row(kind, tries, dismissed)
                if row is not None:
                    out.append(row)
        # a cub's error naming only the class joins the incident another kind shows; alone,
        # it is a Fix row like any other
        for kind, tries in vague:
            if held:
                first = min(held, key=lambda p: min(t["finished_at"] or "" for t in held[p]))
                held[first].extend({**t, "kind": kind, "_auth": None} for t in tries)
                continue
            with _row(out, f"fail:{kind}", kind, "failing"):
                row = self._fail_row(kind, tries, dismissed)
                if row is not None:
                    out.append(row)
        out.sort(key=lambda f: f.get("last") or "", reverse=True)
        found: list[dict[str, Any]] = []
        for provider, runs in held.items():
            # fixed is fixed, whatever kind fixed it: only the failures after the last
            # good call to the provider, a passing key test or the owner's Dismiss hold it
            cut = self._cleared_at(provider)
            runs = [r for r in runs if (r["finished_at"] or "") > cut]
            if not runs:
                continue
            with _row(found, f"auth:{provider}", "incident", "failing"):
                found.append(self._incident(provider, runs))
        for i in found:                     # the band is Kranto's own (incidents.BAND_CLASSES)
            i["band"] = incidents.band(i)
        # Kranto's own first, then by age
        found.sort(key=lambda i: (not i["band"], i.get("since") or ""))
        return out, found

    def _cleared_at(self, provider: str) -> str:
        """When ``auth:<provider>`` was last shown fixed: the provider's last good call, its
        last passing key test, the owner's last Dismiss of it (an ISO time; "" never)."""
        at = []
        names = incidents.call_providers(provider)
        if names:
            row = self.store.query_one(
                f"SELECT MAX(created_at) AS at FROM llm_calls WHERE status = 'ok' AND provider IN "
                f"({','.join('?' * len(names))})", names)
            at.append((row["at"] if row is not None else None) or "")
        try:
            from .. import setup
            test = setup.last_key_test(self.store)
        except Exception:  # noqa: BLE001 - a read never fails on the key test's blob
            test = None
        if test and test.get("ok") and self._key_test_for(test.get("base_url")) == provider:
            at.append(str(test.get("at") or ""))
        row = self.store.query_one(
            "SELECT MAX(ts) AS ts FROM run_marks WHERE mark = 'dismissed' AND kind = ?",
            (f"auth:{provider}",))
        at.append((row["ts"] if row is not None else None) or "")
        return max(at)

    @staticmethod
    def _key_test_for(base_url: Any) -> str:
        """The provider a key test's endpoint is: ``openrouter`` or its host."""
        from urllib.parse import urlparse
        host = (urlparse(str(base_url or "")).hostname or "").lower()
        return "openrouter" if host == "openrouter.ai" or host.endswith(".openrouter.ai") \
            else host

    def _incident(self, provider: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
        runs.sort(key=lambda r: (r["finished_at"] or "", r["rid"]))
        first, last = runs[0], runs[-1]
        named = next((r["_auth"] for r in reversed(runs) if r.get("_auth")), None) or {}
        name, cause = named.get("name") or "", named.get("cause") or "refused"
        low = cause == incidents.LOW_CREDIT
        kinds: list[dict[str, Any]] = []
        for r in runs:
            if r["kind"] in {k["kind"] for k in kinds}:
                continue
            f = W.forms(r["kind"], self._feature_title(r["kind"]))
            kinds.append({"kind": r["kind"], "title": W.plain(f["scheduled"]),
                          "noun": incidents.noun(r["kind"], str(f["scheduled"])),
                          "since": r["finished_at"],
                          "tries": sum(1 for x in runs if x["kind"] == r["kind"])})
        at = _ts(first["finished_at"])
        local = at.astimezone() if at else None
        when = f"{local:%H:%M} on {local.day} {local:%b}" if local else "its first failure"
        from .. import rowsafe
        eid = rowsafe.note_failure(f"auth:{provider}", last["error"],
                                   where=f"activity:auth:{provider}")["id"]
        return {"id": f"auth:{provider}", "class": f"auth:{provider}", "provider": provider,
                "name": name, "cause": cause, "blocking": incidents.blocking(cause),
                "tone": "amber" if low else "red", "error_id": eid,
                "title": incidents.title(name, cause),
                "words": incidents.sentence(name, cause, when, [k["noun"] for k in kinds]),
                "since": first["finished_at"], "last": last["finished_at"],
                "tries": len(runs), "kinds": kinds,
                "error": W.plain(last["error"]) or "the key was refused",
                "verb": "Check the key" if low else incidents.VERB, "href": incidents.KEY_HREF,
                "trace": f"#/afk/{last['run_uuid']}/trace", "dismiss": True,
                "clears": incidents.clears(name, cause),
                "runs": [{"uuid": r["run_uuid"], "kind": r["kind"], "at": r["finished_at"],
                          "error": W.plain(r["error"]), "trace": f"#/afk/{r['run_uuid']}/trace"}
                         for r in runs[-10:]]}

    def _fail_row(self, kind: str, tries: list[dict[str, Any]],
                  dismissed: dict[str, Any]) -> dict[str, Any] | None:
        """One kind's Fix row from its failing streak (newest first), or None when it is not
        failing (or was put away)."""
        if not tries:
            return None
        first, last = tries[-1], tries[0]
        since_t = _ts(first["finished_at"])
        long = since_t is not None and self.now - since_t >= timedelta(days=FAILING_DAYS)
        if len(tries) < FAILING_IN_A_ROW and not long:
            return None
        if kind in dismissed and self._dismissed_after(dismissed[kind], last):
            return None
        f = W.forms(kind, self._feature_title(kind))
        from .. import rowsafe  # the Fix row's Send this error files it by this id (B3)
        eid = rowsafe.note_failure(kind, last["error"], where=f"activity:{kind}")["id"]
        return {"id": f"fail:{kind}", "kind": kind, "error_id": eid,
                "title": W.plain(f["scheduled"]), "since": first["finished_at"],
                "last": last["finished_at"], "tries": len(tries),
                "error": W.plain(last["error"]) or "it failed without a reason",
                "verb": f["verb"] or "Run again",
                "trace": f"#/afk/{last['run_uuid']}/trace",
                "runs": [{"uuid": t["run_uuid"], "at": t["finished_at"],
                          "error": W.plain(t["error"]),
                          "trace": f"#/afk/{t['run_uuid']}/trace"} for t in tries[:10]]}

    def _dismissed_after(self, dismissed: tuple[Any, ...], last: dict[str, Any]) -> bool:
        """Whether the owner's Dismiss came after the latest failure: by the marks' order
        (the failure's ended mark), else by time for a run from before marks."""
        mid, mts = dismissed
        end = self.store.query_one("SELECT MAX(id) AS id FROM run_marks WHERE run_uuid = ? "
                                   "AND mark = 'ended'", (last["run_uuid"],))
        if end is not None and end["id"] is not None:
            return bool(mid > end["id"])
        return (mts or "") >= (last["finished_at"] or "")

    def next(self, failing: list[dict[str, Any]],
             found: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if self.scheduler is None:
            return []
        try:
            at = self.scheduler.next_runs()
            jobs = {j.kind: j for j in self.scheduler.jobs}
        except Exception:  # noqa: BLE001 - a page's read never fails on the scheduler
            return []
        fails = {f["kind"]: f for f in failing}
        for i in found or []:            # a kind an incident holds is failing since its first
            for k in i.get("kinds") or []:
                fails.setdefault(k["kind"], {"since": k["since"], "tries": k["tries"]})
        last = {r["kind"]: dict(r) for r in self.store.query(
            "SELECT r.kind, r.status, r.finished_at, r.summary, r.error FROM runs r "
            "WHERE r.rowid IN (SELECT MAX(rowid) FROM runs GROUP BY kind)")}
        out = []
        for kind, when in at.items():
            if when is None:
                continue
            j = jobs.get(kind)
            every = float(getattr(j, "every_hours", 0) or 0)
            lr = last.get(kind)
            f = fails.get(kind)
            row = {"kind": kind, "title": W.plain(W.title_of(kind, "scheduled",
                                                             self._feature_title(kind))),
                   "at": when, "every_words": _every(every, getattr(j, "job", None)),
                   "last": {"state": lr["status"], "at": lr["finished_at"],
                            "why": _why(lr["status"], _summary(lr["summary"]), lr["error"])}
                   if lr else None,
                   "failing_since": f.get("since") if f else None,
                   "failures_in_a_row": (f.get("tries") or 0) if f else 0}
            out.append(row)
        out.sort(key=lambda r: r["at"])
        return out

    def quiet(self, nxt: list[dict[str, Any]], scheduler_on: bool) -> str:
        if not scheduler_on:
            return ("Nothing is scheduled: Kranto runs with the scheduler off "
                    "(kranto serve --no-scheduler).")
        first = next((n for n in nxt if n["kind"] not in QUIET_SKIP), None)
        if first is None:
            return "Nothing is running."
        when = _ts(first["at"])
        clock = when.astimezone().strftime("%H:%M") if when else ""
        return f"Nothing is running. Next: {first['title'][0].lower()}{first['title'][1:]} " \
               f"at {clock}."

    # -- the whole read ---------------------------------------------------------------------------

    def read(self, *, subject: str | None = None, kind: str | None = None,
             limit: int = LIMIT, unfold: bool = False,
             hours: float = RECENT_HOURS) -> dict[str, Any]:
        running = self.running()
        waiting = self.waiting()
        recent, folded = self.recent(hours=hours, limit=limit, unfold=unfold, kind=kind)
        failing, found = self._scan()
        nxt = self.next(failing, found)
        if kind:
            running = [r for r in running if r["kind"] == kind]
            waiting = [r for r in waiting if r["kind"] == kind]
            failing = [f for f in failing if f["kind"] == kind]
            nxt = [n for n in nxt if n["kind"] == kind]
        if subject:
            running, waiting, recent = (_about(subject, rs) for rs in (running, waiting, recent))
        failed_recent = sum(1 for r in recent if r.get("state") == "failed")
        return {"seq": self._seq(), "running": running, "waiting": waiting, "next": nxt,
                "recent": recent, "folded": folded, "failing": failing, "incidents": found,
                "counts": {"running": len(running), "waiting": len(waiting),
                           "failed_recent": failed_recent, "failing": len(failing),
                           "incidents": len(found)},
                "quiet": self.quiet(nxt, self.scheduler is not None) if not running else None,
                "scheduler": self.scheduler is not None, "now": iso(self.now)}

    def one(self, uuid: str) -> dict[str, Any] | None:
        """One run with its marks, for the live trace (``run=``)."""
        live = find(uuid)
        row = self.store.query_one("SELECT * FROM runs WHERE run_uuid = ?", (uuid,))
        marks = [dict(m) for m in self.store.query(
            "SELECT id, kind, ts, mark, state, words, error, step, steps, detail FROM run_marks "
            "WHERE run_uuid = ? ORDER BY id LIMIT 2000", (uuid,))]
        if live is None and row is None and not marks:
            return None
        m = self._marks([uuid]).get(uuid)
        kind = (live.kind if live else None) or (row["kind"] if row else None) or \
            marks[0]["kind"]
        ended = (m or {}).get("ended") or {}
        if live is not None:
            state = "running"
        elif ended.get("state") == "stopped":
            state = "stopped"
        elif row is not None:
            state = row["status"]
        else:
            state = ended.get("state") or "running"
        if state not in ("running", "stopped") and m is not None and m.get("waiting") and \
                self._still_waits(uuid, kind, m["waiting"]):
            state = "waiting"
        view = self.view(uuid=uuid, kind=kind, state=state,
                         started=row["started_at"] if row else (m or {}).get("started", {}).get(
                             "ts"),
                         finished=row["finished_at"] if row else ended.get("ts"), marks=m,
                         error=row["error"] if row else ended.get("error"),
                         summary=_summary(row["summary"]) if row else {},
                         cost=self._cost([uuid]).get(uuid), live=live)
        for x in marks:
            x["words"] = W.plain(x["words"])
            x["error"] = W.plain(x["error"])
        return {"run": view, "marks": marks, "over": live is None and (row is not None
                                                                        or bool(ended))}

    def _seq(self) -> int:
        row = self.store.query_one("SELECT MAX(id) AS n FROM run_marks")
        return int(row["n"] or 0) if row else 0


def _tries(kind: str, rs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A kind's failing streak, newest first: its failed runs since its last good one (ok,
    degraded, or skipped with no error: it ran and had nothing to do)."""
    rs.sort(key=lambda r: (r["finished_at"] or "", r["rid"]), reverse=True)
    tries = []
    for r in rs:
        bad = r["status"] == "failed" or (kind == "update" and r["status"] == "skipped"
                                          and bool(r.get("error")))
        if not bad:
            break
        tries.append(r)
    return tries


def _row(out: list[Any], ident: str, kind: str, state: str) -> AbstractContextManager[None]:
    """One activity row built in this block: one that raises is listed as "Couldn't read this
    run" with its kind and state, never the whole read (RCA A3)."""
    from .. import rowsafe
    return rowsafe.row(out, "run", f"afk:{ident}" if ":" not in ident else ident,
                       uuid=ident, kind=kind, state=state, title=W.plain(kind))


def _about(subject: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The runs about one subject (``topic:12``): their own, and the reading of the sources
    for a topic or a source."""
    k, _, i = subject.partition(":")
    out = []
    for r in rows:
        s = r.get("subject") or {}
        if (s.get("kind") == k and str(s.get("id")) == i) or \
                (k in ("topic", "source") and r.get("kind") == "ingest") or \
                (k == "kind" and r.get("kind") == i) or (k == "feature" and r.get("feature") == i):
            out.append(r)
    return out


def _every(hours: float, job: dict[str, Any] | None = None) -> str:
    if isinstance(job, dict) and job.get("at"):
        days = job.get("days") or []
        return f"{'on ' + ', '.join(days) if days else 'daily'} at {job['at']}"
    if hours <= 0:
        return "off"
    if hours < 1:
        return f"every {round(hours * 60)} minutes"
    if hours == 1:
        return "hourly"
    if hours == 24:
        return "daily"
    if hours == 168:
        return "weekly"
    if hours % 24 == 0:
        return f"every {int(hours // 24)} days"
    return f"every {hours:g} hours"
