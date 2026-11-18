"""The daily ``cubs.updates`` (step 5, as the owner set it on 2026-10-23).

Every installed cub's source is read again (the same fetch as Look for an update). An update
that adds no permission and no send, and whose ``kranto`` range holds this Kranto, is applied by
itself while ``cubs.auto_update`` is on (the default); its run says "<Cub> updated to 1.2.1 by
itself" in Activity and the cub's page says the same. Any other update stays staged for one
press: its run stops for the owner, and Needs you says "<Cub> 1.2.0 asks for one more
permission · Review". With ``cubs.auto_update`` off, every update waits for the press;
with ``cubs.check_updates`` off too, the job looks for nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ... import activity
from ...store import utcnow
from ...stored.cubs import CubSource
from . import install, registry
from . import settings as cub_settings

log = logging.getLogger("kranto.core.cubs")
KIND = "cubs.updates"
ONE = "cub.update"           # one cub's update, applied or waiting: its own run, its own row


def _title(rt, cid: str) -> str:
    cubs = getattr(rt, "cubs", None)
    cub = cubs.installed.get(cid) if cubs is not None else None
    return ((cub.manifest.get("title") if cub is not None else None) or cid)


def folder_gone(row) -> str | None:
    return _folder_gone(row)


def shipped_now(cid: str, gone: str) -> str | None:
    """Where a cub Kranto ships lives now, when the folder it was added from was that cub's
    folder in an installed tool an update since replaced (the crossing removes the old tool;
    ``legacy.shipped_cub``): this Kranto's own copy of it, or None."""
    from ... import legacy
    from ...cubs import examples_dir
    if legacy.shipped_cub(gone) != cid:
        return None
    here = examples_dir() / cid
    return str(here) if (here / "cub.yaml").is_file() and str(here) != gone else None


def _folder_gone(row) -> str | None:
    """The folder a cub was added from, when it is no longer there: the cub keeps running as
    installed, with nothing to look at (a reference cub a release no longer ships, a folder
    the owner deleted). Not a failure: the owner adds it again from where it lives now."""
    if row["source_kind"] != "folder":
        return None
    path = CubSource.load(row["source"]).extra.get("path")
    if not isinstance(path, str) or not path:
        return None
    try:
        return None if Path(path).is_dir() else path
    except OSError:                 # a folder Kranto may not look into (another user's): not "gone"
        return None


def _shipped(cid: str) -> bool:
    """Whether this Kranto ships a cub of that id (the folder ``kranto paths examples`` names)."""
    from ...cubs import examples_dir

    try:
        return (examples_dir() / cid / "cub.yaml").is_file()
    except OSError:
        return False


def gone_words(cid: str, path: str) -> dict:
    """What a cub whose source folder is gone says (live's examplecom pointed at a
    folder that no longer exists, its daily look said ok, and it would never update).
    A cub this Kranto ships is pointed at Kranto's own copy; any other comes from a folder or a
    git address the person gives (the project keeps no collection of features to point at)."""
    if _shipped(cid):
        fix = f'kranto cub source {cid} "$(kranto paths examples)/{cid}"'
        where = "Point it at this Kranto's own copy"
    else:
        fix = f"kranto cub source {cid} <its folder or git URL>"
        where = "Say where it lives now"
    return {"path": path, "fix": fix,
            "words": f"Its source folder is gone ({path}); it gets no updates. {where}: {fix}"}


def _said_once(rt, cid: str, title: str, gone: dict) -> None:
    """Needs you, once a cub: its source is gone (a waiting run of its own)."""
    if rt.store.query_one("SELECT 1 FROM run_marks WHERE kind = ? AND subject_id = ? LIMIT 1",
                          (GONE, cid)):
        return
    from ..context import record_run
    started = utcnow()
    with activity.run(rt.store, GONE, origin="schedule", title=f"{title}'s source is gone",
                      subject=("cub", cid, title)):
        activity.waiting(f"{title}'s source is gone: it gets no updates",
                         {"verb": "Review", "href": f"cub/{cid}?sel=settings"},
                         subject=("cub", cid, title))
        record_run(rt.store, GONE, "ok", started, {"line": gone["words"], "cub": cid},
                   run_uuid=activity.run_uuid(GONE))


GONE = "cub.source"


def check(rt, *, apply: bool) -> list[dict]:
    """Look for every cub's update; apply the safe ones when ``apply``. One outcome a cub:
    ``{cub, title, version, state: up_to_date|updated|waiting|failed|kept, why}`` (``kept``:
    its folder is gone, so it stays as installed)."""
    out = []
    for cid, row in sorted(registry.latest_rows(rt.store).items()):
        if row["state"] == "removed":
            continue
        title = _title(rt, cid)
        o = {"cub": cid, "title": title, "version": row["version"], "state": "up_to_date",
             "why": None}
        out.append(o)
        if registry.is_site_row(row):
            # the owner's site cub reads as Kranto's built-in blog (registry.SITE_ALIASES): it
            # comes with Kranto, never from its old source, and no "source gone" is said of it
            o.update(state="kept", why="read as Kranto's own blog writer, which comes with Kranto")
            continue
        gone = _folder_gone(row)
        moved = shipped_now(cid, gone) if gone else None
        if moved:
            # a cub Kranto ships, added from the tool an update replaced: it updates from the
            # folder this Kranto ships from now on (the next look reads the new place)
            install.set_source(rt, cid, moved)
            gone = None
        if gone:
            g = gone_words(cid, gone)
            o.update(state="kept", why=f"stays as installed: {g['words']}")
            _said_once(rt, cid, title, g)
            continue
        try:
            j = install.start(rt, kind="update", cid=cid, background=False)
        except install.InstallError as exc:
            o.update(state="failed", why=exc.words)
            continue
        if j["state"] == "failed":
            o.update(state="failed", why=j.get("error"))
            continue
        if j["state"] != "awaiting_confirm" or not j.get("cub"):
            continue
        o["version"] = j["cub"]["version"]
        why = install.waits_why(j["cub"])
        if why is None and not apply:
            why = "waits for your approval: cubs.auto_update is off"
        if why is not None:
            o.update(state="waiting", why=why)
            _waiting(rt, cid, title, o["version"], why)
            continue
        try:
            _applied(rt, cid, title, j["id"], o["version"])
            o["state"] = "updated"
        except install.InstallError as exc:
            o.update(state="failed", why=exc.words)
    return out


def _applied(rt, cid: str, title: str, job_id: str, version: str) -> None:
    from ..context import record_run
    started = utcnow()
    with activity.run(rt.store, ONE, origin="schedule", by="itself",
                      title=f"{title} updated to {version} by itself",
                      subject=("cub", cid, title)):
        install.apply_update(rt, job_id, cid, door="auto")
        record_run(rt.store, ONE, "ok", started,
                   {"line": f"Updated to {version} by itself", "cub": cid, "version": version},
                   run_uuid=activity.run_uuid(ONE))


def _waiting(rt, cid: str, title: str, version: str, why: str) -> None:
    from ..context import record_run
    started = utcnow()
    with activity.run(rt.store, ONE, origin="schedule", title=f"{title} {version} {why}",
                      subject=("cub", cid, title)):
        activity.waiting(f"{title} {version} {why}",
                         {"verb": "Review", "href": f"cub/{cid}?sel=settings"},
                         subject=("cub", cid, title))
        record_run(rt.store, ONE, "ok", started,
                   {"line": f"{version} {why}", "cub": cid, "version": version},
                   run_uuid=activity.run_uuid(ONE))


def run(rt) -> dict:
    """The scheduler's job: its run recorded as every job's is (due-ness reads runs)."""
    from ..context import record_run
    started = utcnow()
    uuid = activity.run_uuid(KIND)
    v = cub_settings.values(rt.cfg)
    from ... import preview
    if preview.enabled(getattr(rt.cfg, "root", None)):
        summary = {"why": "this is the preview: the cubs are not updated here"}
        record_run(rt.store, KIND, "skipped", started, summary, run_uuid=uuid)
        return summary
    if getattr(rt, "cubs", None) is None or not (v["cubs.check_updates"]
                                                 or v["cubs.auto_update"]):
        summary = {"why": "looking for the cubs' updates is off"}
        record_run(rt.store, KIND, "skipped", started, summary, run_uuid=uuid)
        return summary
    outcomes = check(rt, apply=bool(v["cubs.auto_update"]))
    said = [f"{o['title']} updated to {o['version']} by itself" if o["state"] == "updated"
            else f"{o['title']} {o['version']} {o['why']}" if o["state"] == "waiting"
            else f"{o['title']}: {o['why']}" for o in outcomes
            if o["state"] not in ("up_to_date", "kept")]
    failed = [o for o in outcomes if o["state"] == "failed"]
    summary = {"line": "; ".join(said) if said else "every cub is up to date",
               "cubs": outcomes}
    record_run(rt.store, KIND, "degraded" if failed else "ok", started, summary,
               run_uuid=uuid)
    return summary
