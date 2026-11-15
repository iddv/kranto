"""The cubs as the page and the command line read them (``GET /api/cubs``,
``GET /api/cubs/{id}``; ``kranto cub list`` and ``inspect``): from the registry rows, the
pins, the settings in force and the runs; never a secret, never the cub's process."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from typing import Any, cast

from ...store import iso, utcnow
from ...stored.cubs import Grants, InstallDetail
from .. import api, asks, tickets
from . import files, registry, sandbox
from . import settings as cub_settings

TREE_TTL_S = 60
_TREE: dict[str, tuple[float, str, bool]] = {}


def _tree_ok(cub: Any) -> bool:
    """Whether the cub's files hash to its pin, for the page: kept a minute (the page polls;
    a tree is up to 40 MiB). The runtime hashes the tree in full before every spawn."""
    src = cub.dir / "src"
    hit = _TREE.get(cub.id)
    now = time.monotonic()
    if hit and now - hit[0] < TREE_TTL_S and hit[1] == cub.tree_hash:
        return hit[2]
    ok = src.is_dir() and files.tree_hash(src) == cub.tree_hash
    _TREE[cub.id] = (now, cub.tree_hash, ok)
    return bool(ok)


def _kinds_prefix(m: dict[str, Any], cid: str) -> list[str]:
    return [j["kind"] for j in m.get("jobs", [])] or [f"{cid}."]


def _manifest(cfg: Any, cid: str) -> dict[str, Any]:
    try:
        return json.loads((files.cub_dir(cfg, cid) / "cub.json").read_text()).get("manifest") \
            or {}
    except (OSError, ValueError):
        return {}


def _installed_at(store: Any, cid: str) -> str | None:
    """When the current install began: the first row after the last removal."""
    rows = store.query("SELECT state, created_at FROM cubs WHERE cub = ? ORDER BY id", (cid,))
    at = None
    for r in rows:
        if r["state"] == "removed":
            at = None
        elif at is None:
            at = r["created_at"]
    return at


def _pending_update(store: Any, cfg: Any, cid: str) -> dict[str, Any] | None:
    """The update staged for the owner's press, never one that offers nothing (a version
    installed already, a staged folder gone): ``install.stale_why``."""
    from . import install
    for job_id in install.awaiting_updates(store, cfg, cid)[:1]:
        j = install.job(store, cfg, job_id)
        if j and j["state"] == "awaiting_confirm":
            c = j.get("cub") or {}
            added = (c.get("delta") or {}).get("added") or {}
            return {"version": c.get("version"), "sha": c.get("sha"), "job": j["id"],
                    "needs": j.get("needs"),
                    "adds": [f"{block}: {', '.join(map(str, items))}"
                             for block, items in added.items()],
                    "why": install.waits_why(c) if c else None}
    return None


def _last_update(store: Any, cid: str) -> dict[str, Any] | None:
    """The cub's last update applied: its version, when, and by whom (``itself``: the daily
    ``cubs.updates`` under ``cubs.auto_update``; ``you``: a press or the command line)."""
    # an update from before 0.5.16 has no version on its installed step: the registry row its
    # pin wrote (the cub's newest at that moment) says it
    r = store.query_one(
        "SELECT i.created_at, i.detail, (SELECT p.detail FROM cub_installs p WHERE p.job_id = "
        "i.job_id AND p.step = 'placing' ORDER BY p.id DESC LIMIT 1) AS placing, "
        "(SELECT c.version FROM cubs c WHERE c.cub = i.cub AND c.created_at <= i.created_at "
        "ORDER BY c.id DESC LIMIT 1) AS pinned "
        "FROM cub_installs i WHERE i.cub = ? AND i.kind = 'update' AND i.step = 'installed' "
        "ORDER BY i.id DESC LIMIT 1", (cid,))
    if r is None:
        return None
    try:
        door = json.loads(r["placing"] or "{}").get("door")
        version = InstallDetail.load(r["detail"]).extra.get("version") or r["pinned"]
    except ValueError:
        door, version = None, r["pinned"]
    return {"version": version, "at": r["created_at"],
            "by": "itself" if door == "auto" else "you"}


def row(rt: Any, cid: str, r: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """One cub's line."""
    cfg, store = rt.cfg, rt.store
    r = r or registry.latest(store, cid)
    if r is None:
        return None
    cub = registry.installed(cfg, r)
    m = (rt.cubs.installed[cid].manifest if getattr(rt, "cubs", None) is not None
         and cid in rt.cubs.installed else None) or _manifest(cfg, cid)
    pin = store.query_one("SELECT manifest_hash, tree_hash FROM cub_pins WHERE cub = ? ORDER BY "
                          "id DESC LIMIT 1", (cid,))
    pinned = pin is not None and pin["manifest_hash"] == cub.manifest_hash \
        and pin["tree_hash"] == cub.tree_hash
    live = [k for k in cub_settings.live_kinds(cfg, cid) if k in cub.grants.requests]
    cap = cub_settings.cub_value(cfg, cid, "calls_per_day", trust=cub.trust)
    since = iso(utcnow() - timedelta(days=1))
    from . import brokers
    services = ["http", *brokers.ADAPTERS]           # what calls_per_day counts (host.py)
    smarks = ",".join("?" * len(services))
    calls = store.query_one(f"SELECT COUNT(*) AS n FROM cub_calls WHERE cub = ? AND status = "
                            f"'ok' AND service IN ({smarks}) AND created_at >= ?",
                            (cid, *services, since))["n"]
    month = 0.0
    purposes = cub.grants.model.purposes
    if purposes:
        from types import SimpleNamespace
        fake = SimpleNamespace(permissions=SimpleNamespace(model=SimpleNamespace(
            purposes=purposes)))
        month = api.spend_of(store, fake)["month_usd"]
    kinds = _kinds_prefix(m, cid)
    marks = ",".join("?" * len(kinds))
    last = store.query_one(f"SELECT kind, status, finished_at FROM runs WHERE kind IN ({marks}) "
                           "ORDER BY finished_at DESC LIMIT 1", tuple(kinds)) if m else None
    open_n = sum(1 for t in tickets.listing(store, cub=cid, open_only=True, limit=500))
    mode = rt.cubs.mode_word(cid) if getattr(rt, "cubs", None) is not None else \
        ("paused" if r["state"] == "paused" else "practice")
    return {"id": cid, "title": m.get("title") or cid, "version": cub.version,
            "trust": cub.trust, "state": cub.state,
            "enabled": bool(cub_settings.cub_enabled(cfg, cid)), "mode": mode, "live": live,
            "source": {"kind": cub.source_kind, **cub.source, "sha": cub.sha},
            "installed_at": _installed_at(store, cid), "pinned": pinned,
            "tree_ok": _tree_ok(cub) if cub.state != "removed" else False,
            "update": _pending_update(store, cfg, cid) if cub.state != "removed" else None,
            "updated": _last_update(store, cid),
            "paused": {"note": cub.note} if cub.state == "paused" else None,
            "limits": cub_settings.limits(cfg, cid, cub.trust),
            "spend": {"month_usd": month, "cap_usd": _cap(rt, cub),
                      "calls_today": int(calls), "calls_per_day": cap},
            "tickets_open": open_n, "asks": asks.count(store, cid),
            "last_run": dict(last) if last else None,
            # a folder source that is no longer there: no update can be read
            "source_gone": _gone(cid, r)}


def _gone(cid: str, row: Any) -> dict[str, Any] | None:
    from .updates import folder_gone, gone_words
    if row["state"] == "removed":
        return None
    path = folder_gone(row)
    return gone_words(cid, path) if path else None


def _cap(rt: Any, cub: Any) -> float | None:
    if getattr(rt, "cubs", None) is not None:
        return cast("float | None", rt.cubs.cap_usd(cub))
    own = cub_settings.own_value(rt.cfg, cub.id, "monthly_usd")
    if own is not None:
        return float(own)
    asked = cub.grants.model.monthly_usd
    return float(asked) if asked is not None else \
        cub_settings.cub_value(rt.cfg, cub.id, "monthly_usd", trust=cub.trust)


def as_alias(out: dict[str, Any] | None, shown: str, cid: str) -> dict[str, Any] | None:
    """A site cub's line as the built-in it reads as (``registry.SITE_ALIASES``): its id and
    words the built-in's, at Kranto's version, from Kranto; ``alias_of`` its own id, under which
    its rows, settings and drafts stay."""
    if out is None or shown == cid:
        return out
    from .registry import SITE_CUBS, builtin_version
    words = SITE_CUBS.get(cid) or {}
    return {**out, "id": shown, "alias_of": cid, "title": words.get("title") or out["title"],
            "version": builtin_version(shown) or out["version"],
            "source": {"kind": "built-in"}, "source_gone": None, "update": None}


def listing(rt: Any, *, removed: bool = False) -> dict[str, Any]:
    rows = registry.latest_rows(rt.store)
    from ...rowsafe import each
    # one cub that cannot be read is listed as such, never the whole list (RCA A3); the
    # owner's site cub is listed once, as Kranto's blog writer (registry.listed)
    cubs = each([x for x in registry.listed(rows) if removed or x[2]["state"] != "removed"],
                lambda x: as_alias(row(rt, x[1], x[2]), x[0], x[1]), "cub",
                ident=lambda x: x[0], keep=lambda x: {"name": x[0], "state": x[2]["state"]})
    return {"cubs": cubs, "enabled": cub_settings.enabled(rt.cfg),
            "stop_file": tickets.stop_file().exists(), "limits_mode": sandbox.limits_mode(),
            "sandbox": sandbox.sandboxed()}


def detail(rt: Any, cid: str) -> dict[str, Any] | None:
    """One cub with its grants, inventory, the last 20 runs and the manifest in words. ``blog``
    is the owner's site cub while it stands in for Kranto's blog writer (``registry.resolve``)."""
    from . import inspect
    shown, cid = cid, registry.resolve(rt.store, cid)
    out = as_alias(row(rt, cid), shown, cid)
    if out is None:
        return None
    r = registry.latest(rt.store, cid)
    if r is None:
        return None
    typed = Grants.load(r["grants"])
    grants = typed.wire()
    m = _manifest(rt.cfg, cid)
    try:
        record = json.loads((files.cub_dir(rt.cfg, cid) / "cub.json").read_text())
    except (OSError, ValueError):
        record = {}
    kinds = _kinds_prefix(m, cid)
    marks = ",".join("?" * len(kinds))
    runs = [dict(x) for x in rt.store.query(
        f"SELECT run_uuid, kind, status, started_at, finished_at, summary, error FROM runs "
        f"WHERE kind IN ({marks}) ORDER BY finished_at DESC LIMIT 20", tuple(kinds))] if m else []
    topics = None
    if typed.reads_topics:
        names = {t["id"]: t["name"] for t in rt.store.query("SELECT id, name FROM topics_now")}
        topics = [names.get(t, f"#{t}") for t in typed.reads_topics]
    return {**out, "grants": grants, "inventory": record.get("inventory"), "runs": runs,
            "words": inspect.words(m, grants, trust=r["trust"], cap_usd=out["spend"]["cap_usd"],
                                   topics=topics) if m else []}
