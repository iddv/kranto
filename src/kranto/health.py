"""Kranto's health word and why, in one line.

The status bar's word (Healthy, Degraded, Paused) was worked out in the browser alone, from the
last ingest's status, the judge's errors in a day and the loop's pid, and nothing said why: on
2026-10-29 the owner saw Degraded and neither the page nor the console could say it was one
judge call that came back empty. Here the word and its reason are worked out once, on the
server, and every reader serves this answer: ``/api/today``'s ``ingest.health`` (the status bar
in New and Classic, the phone's), ``/api/activity``'s ``health`` (the console's
``kranto_incidents``).

The rules are the ones the page had, in its order:

- **Paused**: watching is paused (the owner), the provider paused watching until a time (a
  spend limit, a usage window), or the build loop is paused;
- **Reading for the first time**: sources are watched and no read has ended yet;
- **Degraded**: the last read failed or had problems, more
  than one judge call in five failed in the last 24 hours, or the build loop is not running;
- **Healthy** otherwise, with no reason.

``reason`` is one line in plain words (never a setting key, a uuid or a class name); ``trace``
opens the run it is about (``#/afk/<run>/trace``), else None. Reads only.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import paths
from .activity import words as W
from .activity.incidents import classify, provider_words
from .llm import watch_pause
from .store import Store, iso, utcnow
from .stored.runs import IngestSummary

JUDGE_ERROR_SHARE = 0.2          # more than one judge call in five failed: Degraded
# an ingest run in Activity's words ("Reading your sources"): "news check" read as the News
# feature to the console (the headless check offered to start a brief)
WHAT = "read of your sources"
FIRST_READ = "Reading for the first time"     # the word while no read has ended yet


def health(store: Store, *, now: datetime | None = None,
           loop: dict[str, Any] | None = None) -> dict[str, Any]:
    """``{"word", "tone", "reason", "at", "run", "trace"}``. ``loop``: the build loop's
    ``{"paused": bool, "running": bool}`` (``loop_state``), None without one."""
    now = now or utcnow()
    loop = loop or {}
    pause = store.pause_reason()
    if pause:
        return _word("Paused", f"Watching is paused: {W.plain(pause)}")
    waiting = watch_pause(store, now)
    if waiting:
        until = waiting["until"].replace("T", " ")[11:16]
        why = f": {W.plain(waiting['reason'])}" if waiting.get("reason") else ""
        return _word("Paused", f"Watching waits until {until} UTC{why}")
    if loop.get("paused"):
        return _word("Paused", "The build loop is paused")

    last = store.query_one("SELECT * FROM runs WHERE kind = 'ingest' AND status != 'skipped' "
                           "ORDER BY finished_at DESC LIMIT 1")
    if last is None:
        # a home with nothing to watch is not broken, only new (the fresh home's
        # bar said "Degraded" before Welcome's first step)
        from .library import list_sources
        if not list_sources(store, status="approved"):
            return {**_word("Not set up yet", "Choose a topic to watch on Welcome"),
                    "tone": "grey"}
        # sources watched, no read ended yet: the first read (fix 7: the bar
        # said "Degraded" all through a stranger's first sixteen minutes)
        from .product import NAME
        return {**_word(FIRST_READ, f"{NAME} is reading your sources for the first time"),
                "tone": "grey"}
    when = _when(last["finished_at"] or last["started_at"], now)
    if last["status"] == "failed":
        return _word("Degraded", f"The last {WHAT} failed {when}: {_failed_cause(store, last)}",
                     last)
    if last["status"] == "degraded":
        return _word("Degraded", f"The last {WHAT} {when} had problems: "
                                 f"{_degraded_cause(store, last)}", last)
    judged = store.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(status = 'error'), 0) AS errors FROM llm_calls "
        "WHERE purpose = 'judge' AND created_at >= ?", (iso(now - timedelta(hours=24)),))
    n, errors = (int(judged["n"]), int(judged["errors"])) if judged else (0, 0)
    if n and errors / n > JUDGE_ERROR_SHARE:
        return _word("Degraded", f"{errors} of {n} judge calls failed in the last 24 hours: "
                                 f"{_judge_cause(store, now)}")
    if loop.get("running") is False:
        return _word("Degraded", "The build loop is not running")
    return _word("Healthy", None)


def _word(word: str, reason: str | None, run: Any = None) -> dict[str, Any]:
    uuid = run["run_uuid"] if run is not None else None
    return {"word": word, "tone": "green" if word == "Healthy" else "amber",
            "reason": reason, "at": (run["finished_at"] if run is not None else None),
            "run": uuid, "trace": f"#/afk/{uuid}/trace" if uuid else None}


def _when(ts: str | None, now: datetime) -> str:
    """``at 12:42`` today (UTC), ``on 28 Oct at 12:42`` before."""
    if not ts:
        return ""
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    hm = t.strftime("%H:%M")
    return f"at {hm}" if t.date() == now.date() else f"on {t.day} {t.strftime('%b')} at {hm}"


def _calls(store: Store, run_uuid: str) -> list[Any]:
    return store.query("SELECT * FROM llm_calls WHERE run_uuid = ? AND status = 'error' "
                       "ORDER BY id DESC", (run_uuid,))


def _call_cause(row: Any) -> str | None:
    """What one failed call was, in words: an empty reply, a refusal; None for anything else."""
    error, raw = str(row["error"] or ""), str(row["response"] or "")
    name = provider_words(str(row["provider"] or "")) or "the model provider"
    if "declined to answer" in error or ('"content_filter"' in raw and "no content" in error):
        return f"a safety filter at {name} declined one item"
    if ("empty reply" in error or error.startswith("reply had no content")) \
            and not row["prompt_tokens"] and not row["completion_tokens"]:
        return f"{name} sent an empty reply"
    return None


def _failed_cause(store: Store, run: Any) -> str:
    # a run before failed on an empty reply as "provider reported cost None...": the
    # call that ended it says what it was
    for row in _calls(store, run["run_uuid"])[:1]:
        said = _call_cause(row)
        if said:
            return said
    return _error_words(run["error"]) or "no reason was recorded"


def _error_words(error: str | None) -> str | None:
    if not error:
        return None
    key = classify(error)
    if key is not None and key["cause"] != "low credit":
        who = key["name"] or "your model"
        return {"missing": f"no key is set for {who}", "expired": f"the {who} key has expired",
                "out of credit": f"{who} is out of credit"}.get(
                    key["cause"], f"the {who} key was refused")
    text = " ".join(str(W.plain(error)).split())
    return text if len(text) <= 140 else text[:139].rstrip() + "…"


def _degraded_cause(store: Store, run: Any) -> str:
    summary = IngestSummary.load(run["summary"])
    per = summary.sources
    total: Counter[str] = Counter()
    for s in per:
        for k in ("empty_replies", "refused", "llm_errors", "item_errors"):
            total[k] += int(getattr(s, k) or 0)
    calls = _calls(store, run["run_uuid"])
    names = {provider_words(str(r["provider"] or "")) for r in calls} - {""}
    who = names.pop() if len(names) == 1 else "the model provider"
    parts = []
    if total["empty_replies"]:
        n = total["empty_replies"]
        parts.append(f"{who} sent {_n(n, 'empty reply', 'empty replies')} (read again next run)")
    if total["refused"]:
        parts.append(f"a safety filter declined {_n(total['refused'], 'item')}")
    other_calls = total["llm_errors"] - total["empty_replies"]
    if other_calls > 0:
        parts.append(f"{_n(other_calls, 'model call')} failed")
    rejected = total["item_errors"] - total["refused"]
    if rejected > 0:
        parts.append(f"the model rejected {_n(rejected, 'item')}")
    failing = [s for s in per if s.fetch_state in ("failing", "needs_login")]
    login = [s for s in failing if s.fetch_state == "needs_login"]
    if login:
        n = len(login)
        parts.append(f"{_n(n, 'source')} {'needs' if n == 1 else 'need'} you to sign in again")
    if len(failing) > len(login):
        n = len(failing) - len(login)
        parts.append(f"{_n(n, 'source')} {'keeps' if n == 1 else 'keep'} failing to fetch")
    if run["error"] and not parts:
        parts.append(_error_words(run["error"]) or "")
    parts = [p for p in parts if p]
    if not parts:
        return "some items or sources were not read"
    more = f"; and {len(parts) - 2} more in its trace" if len(parts) > 2 else ""
    return "; ".join(parts[:2]) + more


def _judge_cause(store: Store, now: datetime) -> str:
    rows = store.query("SELECT * FROM llm_calls WHERE purpose = 'judge' AND status = 'error' "
                       "AND created_at >= ? ORDER BY id DESC LIMIT 50",
                       (iso(now - timedelta(hours=24)),))
    said = Counter(_call_cause(r) or _error_words(r["error"]) or "an error" for r in rows)
    return said.most_common(1)[0][0] if said else "see Activity"


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def loop_state(home: Path | None) -> dict[str, Any] | None:
    """The build loop at ``home`` as the page's status reads it: ``paused`` (its PAUSE file)
    and ``running`` (its ``daemon.pid`` names a live process). None without a loop (the page
    not mounted). Files only: never a call into the page, whose activity read asks for this."""
    if home is None:
        return None
    layout = paths.LoopLayout(Path(home))
    try:
        pid = int(layout.pid.read_text().strip())
    except (OSError, ValueError):
        pid = None
    return {"paused": layout.pause.exists(), "running": _alive(pid)}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:                                   # a zombie is not running
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][:1] != "Z"
    except (OSError, IndexError):
        return True


def served(app: Any, now: datetime | None = None) -> dict[str, Any]:
    """``health`` as the server serves it: with the build loop when the page is mounted and
    builds are on (with builds off, a loop that is not running is not a fault)."""
    from .config import builds_on
    home = (paths.loop_home(app.rt.cfg.brb.loop_home)
            if app.brb.mounted and builds_on(app.rt.cfg) else None)
    h = health(app.rt.store, now=now, loop=loop_state(home))
    if h["word"] in ("Healthy", FIRST_READ):
        missing = model_missing(app.rt)
        if missing:
            return _word("Degraded", missing)
    return h


def model_missing(rt: Any) -> str | None:
    """Why the watcher's model cannot be called right now, when Claude Code is the model and
    this machine's check (``setup.logins``, cached) says it is not installed or not signed in;
    None otherwise. The bar said Healthy, and Watching "Works", with every model call failing.
    A key provider's trouble is the key's incident, from its first failure."""
    try:
        if rt.cfg.llm.provider_name != "claude_code":
            return None
        from . import setup
        cc = setup.logins().get("claude") or {}
    except Exception:  # noqa: BLE001 - a check that cannot say says nothing
        return None
    if cc.get("ok") is not False:
        return None
    if cc.get("installed") is False:
        return ("Claude Code, the model that reads for you, is not installed on this machine: "
                "nothing is read until it is (Settings › Watching)")
    return ("Claude Code, the model that reads for you, is not signed in on this machine: "
            "nothing is read until it is (Settings › Watching)")


__all__ = ["health", "loop_state", "model_missing", "served"]
