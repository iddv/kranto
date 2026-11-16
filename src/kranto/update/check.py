"""The update check (section 3): one request a day, cached in the home.

``run_check`` asks the source for the newest release on the channel, records it in
``<home>/data/update.json`` with what is installed, and, when ``download`` is on and the
release is newer, stages its wheels under ``<home>/update/releases/<tag>/`` and verifies
them (``apply.verify_set``); a set that fails is deleted and the reason kept. Any failure
(offline, 401, rate limit) is recorded as ``error`` with a redacted message; nothing else
changes. The scheduler runs it as the ``update`` job (``make_job``), so ``runs`` keeps its
history and a failed check is retried hourly like any skipped job.

The settings are read from the config file at each check, so Settings › System › Updates applies at
the next check without a restart.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from .. import activity, paths
from .. import config as config_mod
from ..stored import runs as stored_runs
from .apply import (
    SetError,
    cache_path,
    history,
    installed,
    read_json,
    redact,
    releases_dir,
    state_path,
    vkey,
    write_json,
)
from .sources import NotModified, Release, SourceError, make_source


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@lru_cache(maxsize=4)
def installed_here(env: str | None = None) -> dict:
    """What this process runs (it cannot change under a running process: an update restarts
    it)."""
    return installed(Path(env) if env else None)


def settings(home: Path) -> config_mod.UpdateConfig:
    """``update:`` as the config file says now (the defaults when it has none or is broken:
    a check never fails on a settings typo; the server reported it when it started)."""
    from dataclasses import replace

    from .sources import connection_file

    path = config_mod.config_path(Path(home))
    try:
        raw = yaml.safe_load(path.read_text()) if path else {}
        cfg = config_mod.parse_update((raw or {}).get("update"))
    except (OSError, yaml.YAMLError, config_mod.ConfigError, AttributeError):
        cfg = config_mod.UpdateConfig()
    if cfg.token_env_file is None:            # Kranto's own GitHub connection, when there is one
        cfg = replace(cfg, token_env_file=connection_file())
    return cfg


def available(cache: dict, inst: dict | None = None) -> str | None:
    """The version on offer, or None: newer than what is installed (``main``: other commits
    than the installed ones). An install from git on a release channel is also offered the
    release of its own version: the same code, as the release's verified wheels, which is
    how a ``main`` install moves to ``stable`` (a git install at a tagged commit reports the
    tag's version)."""
    latest = (cache or {}).get("latest")
    inst = inst or (cache or {}).get("installed") or {}
    if not latest:
        return None
    spec = inst.get("spec") or {}
    if latest.get("commits"):
        have = spec.get("commits") or {}
        same = spec.get("kind") == "git" and all(have.get(k) == v
                                                 for k, v in latest["commits"].items())
        return None if same else latest["version"]
    new, have = vkey(latest["version"]), vkey(inst.get("version"))
    if new > have or (spec.get("kind") == "git" and new == have):
        return latest["version"]
    return None


def stage(home: Path, source, release: Release) -> dict:
    """Download and verify ``release``'s set into ``<home>/update/releases/<tag>/``. Returns
    the cache's ``staged`` entry; raises SetError or SourceError (the partial set is gone)."""
    dest = releases_dir(home) / release.tag
    if dest.is_dir():
        try:
            source.verify(dest, release)
            return {"version": release.version, "tag": release.tag, "dir": str(dest),
                    "verified_at": _now()}
        except SetError:
            shutil.rmtree(dest, ignore_errors=True)
    part = dest.with_name(dest.name + ".partial")
    shutil.rmtree(part, ignore_errors=True)
    try:
        source.download(release, part)
        source.verify(part, release)
    except (SetError, SourceError):
        shutil.rmtree(part, ignore_errors=True)
        raise
    part.rename(dest)
    return {"version": release.version, "tag": release.tag, "dir": str(dest),
            "verified_at": _now()}


def stage_tag(home: Path, tag: str, ucfg: config_mod.UpdateConfig | None = None, *,
              source=None) -> dict:
    """Stage one named release (``kranto update --to vX``), whatever the channel offers."""
    from .sources import GitHubReleases, release_of

    ucfg = ucfg or settings(home)
    source = source or GitHubReleases(ucfg.repo, token_env_file=ucfg.token_env_file)
    rels, _ = source.releases()
    r = next((x for x in rels if x.get("tag_name") == tag and not x.get("draft")), None)
    if r is None:
        raise SourceError(f"{tag} is not a published release of {ucfg.repo}")
    return stage(home, source, release_of(r))


PREVIEW_WHY = "this is the preview: it is never updated (kranto-preview refresh builds it again)"


def run_check(home: Path, ucfg: config_mod.UpdateConfig | None = None, *, source=None,
              env: str | None = None, stage_it: bool | None = None) -> dict:
    """Check now; returns the new cache (``ok``, ``error``, ``latest``, ``staged``...)."""
    home = Path(home)
    from .. import preview
    if preview.enabled(home):
        # nothing is asked and nothing is written: the preview is built from its branch
        return {"ok": True, "error": None, "latest": None, "staged": None,
                "preview": PREVIEW_WHY}
    ucfg = ucfg or settings(home)
    source = source or make_source(ucfg)
    cache = read_json(cache_path(home), {}) or {}
    inst = installed_here(env)
    cache["installed"] = {k: inst[k] for k in ("version", "versions", "channel", "spec")}
    cache["channel"] = ucfg.channel
    if cache.get("checked_channel") != ucfg.channel:
        cache.pop("etag", None)          # another channel: the cached list says nothing
    try:
        rel, etag = source.latest(ucfg.channel, cache.get("etag"))
        cache["latest"] = rel.as_dict() if rel else None
        if etag:
            cache["etag"] = etag
    except NotModified:
        pass
    except SourceError as exc:
        now = _now()
        cache.update(checked_at=now, ok=False, error=redact(exc)[:300],
                     failing_since=cache.get("failing_since") or now)
        write_json(cache_path(home), cache)
        return cache
    cache.pop("failing_since", None)
    cache.update(checked_at=_now(), ok=True, error=None, checked_channel=ucfg.channel)
    offer = available(cache, inst)
    staged = cache.get("staged") or {}
    if offer and (ucfg.download if stage_it is None else stage_it) and \
            not (cache["latest"] or {}).get("commits"):
        rel = Release(**cache["latest"])
        try:
            cache["staged"] = stage(home, source, rel)
            cache["stage_error"] = None
        except (SetError, SourceError) as exc:
            cache["staged"] = None
            cache["stage_error"] = redact(exc)[:300]
    elif staged and staged.get("version") != offer:
        cache["staged"] = None
    write_json(cache_path(home), cache)
    return cache


def in_window(window: str, now: datetime) -> bool:
    """``now`` (local time) is inside ``"HH:MM-HH:MM"`` (which may wrap past midnight)."""
    a, b = config_mod.quiet_window(window)
    m = now.hour * 60 + now.minute
    return a <= m < b if a < b else (m >= a or m < b)


def _term_running(record: Path) -> bool:
    """Whether a version of the page Open in Claude Code session's record says it is running."""
    try:
        return json.loads(record.read_text()).get("state") == "running"
    except (OSError, ValueError, AttributeError):
        return False


def idle_blockers(home: Path, ucfg: config_mod.UpdateConfig, cache: dict, *,
                  now: datetime | None = None, loop_home: Path | None = None,
                  can: bool | None = None) -> list[str]:
    """Why ``auto: idle`` must not update now (empty: it may). section 6: a
    staged stable release, inside the quiet window, nothing building or paused, no Open in
    Claude Code session running (the page's ``<loop home>/term/<id>/session.json``; the
    project chat it replaced was the same rule), no update in the last 24 h, and not a version
    rolled back in the last 7 days."""
    from datetime import timedelta

    from .apply import is_prerelease

    now = now or datetime.now().astimezone()
    out = []
    if ucfg.auto != "idle":
        return ["auto is off"]
    offer = available(cache)
    if not offer:
        return ["nothing to update to"]
    if is_prerelease(offer) or (cache.get("latest") or {}).get("commits"):
        out.append("only a stable release updates by itself")
    if (cache.get("staged") or {}).get("version") != offer:
        out.append(f"{offer} is not staged")
    if not in_window(ucfg.quiet_window, now):
        out.append(f"outside the quiet window {ucfg.quiet_window}")
    if not (can_apply() if can is None else can):
        out.append("this server cannot restart itself")
    if loop_home is not None:
        lh = Path(loop_home)
        if paths.LoopLayout(lh).pause.exists():
            out.append("Kranto is paused")
        if any(_term_running(f) for f in (lh / "term").glob("*/session.json")):
            out.append("a Claude Code session is open (an update would end it)")
    for h in history(home, 50):
        try:
            when = datetime.fromisoformat(str(h.get("finished")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if h.get("state") == "done" and now - when < timedelta(hours=24):
            out.append("an update ran in the last 24 hours")
            break
        if h.get("state") == "rolled_back" and h.get("to") == offer \
                and now - when < timedelta(days=7):
            out.append(f"{offer} was rolled back this week (Try again is in Needs you)")
            break
    return out


def make_job(home: Path, store, every_hours: float, *, port: int | None = None,
             loop_home: Path | None = None, unit: str | None = None):
    """The scheduler's ``update`` job: a check that records a ``runs`` row (ok, or skipped
    with the reason when the check failed); with ``auto: idle``, then the update itself
    when nothing stands in the way (``idle_blockers``)."""
    from .. import legacy
    from ..scheduler import Job
    from ..store import utcnow
    from .launch import LaunchError, launch

    def run():
        started = utcnow()
        try:
            cache = run_check(home)
            status = "ok" if cache.get("ok") else "skipped"
            summary = {"latest": (cache.get("latest") or {}).get("version"),
                       "available": available(cache), "staged": bool(cache.get("staged")),
                       **({"why": cache["preview"]} if cache.get("preview") else {})}
            error = cache.get("error")
            ucfg = settings(home)
            if cache.get("ok") and ucfg.auto == "idle" and port:
                blockers = idle_blockers(home, ucfg, cache, loop_home=loop_home)
                summary["auto"] = blockers or "launched"
                if not blockers:
                    try:
                        launch(home, cache["staged"]["tag"], when="after-build", port=port,
                               unit=unit or legacy.unit_name(),
                               keep=ucfg.keep_backups)
                    except LaunchError as exc:
                        summary["auto"] = f"not launched: {exc}"
        except Exception as exc:  # noqa: BLE001 - a broken check never stops the scheduler
            status, summary, error = "skipped", {}, redact(f"{type(exc).__name__}: {exc}")[:300]
        _record(store, started, status, summary, error)
    return Job("update", every_hours, run)


def _record(store, started, status: str, summary: dict, error: str | None) -> None:
    from ..store import iso, utcnow
    store.insert("runs", {"run_uuid": activity.run_uuid("update"), "kind": "update",
                          "status": status, "started_at": iso(started),
                          "finished_at": iso(utcnow()),
                          "summary": stored_runs.text_for("update", summary),
                          "error": error})


def check_pressed(home: Path, store, *, by: str = "ui") -> None:
    """Check for updates now, pressed (Settings › System › Updates, ⌘K, Activity's Try again): a
    run of the update check like the daily one's, its ``runs`` row recorded the same way, so a
    check that works clears its Fix row and one that fails counts as a try. It
    never updates by itself: that stays the daily job's, under ``auto: idle``."""
    from ..store import utcnow
    started = utcnow()
    with activity.run(store, "update", origin="press", by=by):
        try:
            cache = run_check(home)
            status = "ok" if cache.get("ok") else "skipped"
            summary = {"latest": (cache.get("latest") or {}).get("version"),
                       "available": available(cache), "staged": bool(cache.get("staged")),
                       "pressed": True,
                       **({"why": cache["preview"]} if cache.get("preview") else {})}
            error = cache.get("error")
        except Exception as exc:  # noqa: BLE001 - said on the page, and kept as a try
            status, summary, error = "skipped", {"pressed": True}, \
                redact(f"{type(exc).__name__}: {exc}")[:300]
        _record(store, started, status, summary, error)


# -- what the surfaces show --------------------------------------------------------------------


def apply_state(home: Path) -> dict:
    """The helper's state file; a run whose helper died mid-way reads as ``failed``, and names
    the way back by hand (``RECOVER.txt``) when the helper left it (``recover``)."""
    from .apply import FINAL, recover_path
    from .launch import running

    st = read_json(state_path(home), None) or {"state": "idle"}
    recover = recover_path(home)
    if st.get("state", "idle") not in (*FINAL, "idle") and not running(home):
        st = {**st, "state": "failed", "reason": st.get("reason") or
              f"the update helper stopped while {st.get('state')}; see its log "
              f"({st.get('log') or 'journalctl --user -u kranto-update'})"}
    if st.get("state") == "failed" and recover.is_file():
        st = {**st, "recover": str(recover)}
    return st


def can_apply() -> bool:
    """Whether this server can restart itself on a new version: it runs under systemd (the
    helper restarts the unit) and can start a transient unit on a Python outside its venv."""
    import os

    from .launch import why_not

    return bool(os.environ.get("INVOCATION_ID")) and why_not() is None


FAILING_DAYS = 2


def failing(cache: dict, now: datetime | None = None) -> str | None:
    """The check's error in plain words when it has failed for more than ``FAILING_DAYS``
    (the header's pill says so instead of staying silent), else None."""
    from datetime import timedelta

    from .sources import gh_error

    since = cache.get("failing_since")
    if cache.get("ok", True) or not since:
        return None
    try:
        start = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return None
    if (now or datetime.now(UTC)) - start <= timedelta(days=FAILING_DAYS):
        return None
    return gh_error(cache.get("error"), 160)


_REPORTED: set[str] = set()


def _report_selfcheck(home: Path, st: dict, failed: list[dict]) -> None:
    """A version the self-check rolled back goes to the error reports (ERR, B1), once per
    rollback in this process: the helper that found it runs outside Kranto and imports nothing of
    it, so the server it put back says it, if the person chose to send. Never raises."""
    key = str(st.get("finished") or st.get("started") or "")
    if key in _REPORTED:
        return
    _REPORTED.add(key)
    try:
        from ..telemetry import errors
        f = failed[0]
        errors.report_failure("UpdateSelfCheck", "update", home=Path(home),
                              message=f"the new version answered {f.get('status') or 'nothing'} "
                                      f"on a page of the self-check")
    except Exception:  # noqa: BLE001 - a report never fails the summary
        pass


def summary(home: Path) -> dict:
    """``/api/status``'s ``update``: what the header pill needs, from two small files.
    ``check_failing``: the check's error once it has failed for more than two days."""
    cache = read_json(cache_path(home), {}) or {}
    inst = installed_here()
    st = apply_state(home)
    latest = cache.get("latest") or {}
    sc = st.get("selfcheck") if isinstance(st.get("selfcheck"), dict) else None
    failed = [f for f in (sc or {}).get("failed") or [] if isinstance(f, dict)]
    if failed and st.get("state") == "rolled_back":
        _report_selfcheck(home, st, failed)
    return {"available": available(cache, inst), "installed": inst.get("version"),
            "channel": inst.get("channel"), "chosen": settings(home).channel,
            "state": st.get("state", "idle"),
            "detail": st.get("detail"), "reason": st.get("reason"),
            # the self-check that rolled it back (RCA D1): how many pages failed, the first
            # one's error id (Needs you's Send this error files it), None when it passed
            "broke": {"pages": len(failed), "error_id": next(
                (f.get("error_id") for f in failed if f.get("error_id")), None)}
            if failed and st.get("state") in ("rolled_back", "failed") else None,
            "to": st.get("to"), "notes": (latest.get("notes") or [])[:3],
            "notes_url": latest.get("notes_url"), "can_apply": can_apply(),
            "checked_at": cache.get("checked_at"), "check_failing": failing(cache),
            "failing_since": cache.get("failing_since") if not cache.get("ok", True) else None}


def candidate_path(home: Path) -> Path:
    return Path(home) / "update" / "candidate.json"


def promote_path(home: Path) -> Path:
    return Path(home) / "update" / "promote.json"


def candidate(home: Path):
    """The gate's candidate for stable (``stored.release.Candidate``), or None when the gate
    has written none (or nothing readable)."""
    from ..stored.release import Candidate

    try:
        raw = candidate_path(home).read_text()
    except OSError:
        return None
    return Candidate.parse(raw)


def view(home: Path) -> dict:
    """``GET /api/update``: the cache, the apply state, the settings and the last five
    updates; on the maintainer's install, the candidate for stable."""
    cache = read_json(cache_path(home), {}) or {}
    inst = installed_here()
    s = settings(home)
    cand = candidate(home) if s.maintainer else None
    return {**cache, "installed": {k: inst[k] for k in ("version", "versions", "channel",
                                                        "spec")},
            "available": available(cache, inst), "apply": apply_state(home),
            "settings": {"source": s.source, "repo": s.repo, "channel": s.channel,
                         "check_every_hours": s.check_every_hours, "download": s.download,
                         "auto": s.auto, "quiet_window": s.quiet_window,
                         "keep_backups": s.keep_backups, "maintainer": s.maintainer},
            "candidate": cand.to_dict() if cand is not None else None,
            "previous": read_json(Path(home) / "update" / "previous.json", None),
            "history": history(home, 5), "can_apply": can_apply()}


def _ago(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        s = (datetime.now(UTC) - datetime.fromisoformat(ts.replace("Z", "+00:00"))) \
            .total_seconds()
    except ValueError:
        return ts
    s = max(0, int(s))
    return f"{s // 60}m ago" if s < 5400 else f"{s // 3600}h ago" if s < 172800 \
        else f"{s // 86400}d ago"


def moving(home: Path, inst: dict) -> str:
    """``, moving to stable at the next promotion`` for an install that runs a nightly build
    and chose stable (nothing is ever downgraded: it stays on its build until a stable newer
    than it is promoted), else ``""``."""
    if inst.get("channel") == "nightly" and settings(home).channel == "stable":
        return ", moving to stable at the next promotion"
    return ""


def status_line(home: Path) -> str:
    """``kranto status``'s update line (without the label)."""
    cache = read_json(cache_path(home), {}) or {}
    inst = installed_here()
    st = apply_state(home)
    here = f"{inst.get('version')} ({inst.get('channel')}{moving(home, inst)})"
    state = st.get("state", "idle")
    if state in ("rolled_back", "failed"):
        # after a rollback, or the way back by hand (RECOVER.txt, which removes itself), the
        # version that runs is not the one the update went to: say which one is back
        back = inst.get("version") if inst.get("version") and st.get("to") \
            and inst.get("version") != st.get("to") and not st.get("recover") else None
        return (f"{here} · update to {st.get('to')} {state.replace('_', ' ')}: "
                f"{st.get('reason') or 'see kranto-update in the journal'}"
                + (f" · the way back by hand: {st['recover']} (sh {st['recover']})"
                   if st.get("recover") else "")
                + (f" · {back} is back and running" if back else ""))
    if state not in ("idle", "done", "cancelled"):
        return f"{here} · updating to {st.get('to')}: {state}" + \
            (f" ({st['detail']})" if st.get("detail") else "")
    if not cache.get("checked_at"):
        return f"{here} · not checked yet"
    if not cache.get("ok"):
        from .sources import gh_error

        return (f"{here} · check failed {_ago(cache.get('checked_at'))}: "
                f"{gh_error(cache.get('error'))}")
    offer = available(cache, inst)
    if not offer:
        return f"{here} · up to date, checked {_ago(cache.get('checked_at'))}"
    since = ((cache.get("latest") or {}).get("published_at") or "")[:10]
    staged = (cache.get("staged") or {}).get("version") == offer
    what = f"{offer} available" if offer != inst.get("version") else \
        f"{offer} available as a release (this install is from git)"
    return (f"{here} · {what}" + (f" since {since}" if since else "")
            + (", staged ('kranto update')" if staged else
               f", not staged: {cache['stage_error']}" if cache.get("stage_error") else ""))
