"""The registry of features: what the core does with every manifest (the table).

- ``check()``: every manifest valid (schema 1), ids unique, each event kind published by exactly
  one feature, purposes, actions, routes and tables each owned once;
- ``jobs(rt)``: the scheduler's ``Job`` for each feature job, off (interval 0) while the feature
  or its ``when`` setting is off, so Health lists it as off rather than leaving it out;
- ``deliver(rt)``: hand new events to the subscriptions that have handlers;
- ``pin(store)``: record each manifest's hash at its version: a first-party feature's
  new hash at a new version is recorded; any other change refuses to run that feature;
- ``describe(rt)``: ``GET /api/features``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from ..store import Store, iso, utcnow
from . import api, events, settings, tickets
from .context import FeatureContext, record_run
from .manifest import ManifestError, manifest_hash, validate

log = logging.getLogger("kranto.core.registry")


def first_party() -> tuple:
    from .. import features as pkg
    return tuple(pkg.FEATURES)


def features() -> tuple:
    """Kranto's own features, then the installed cubs as the cub runtime loaded them
   : one list for the registry, the scheduler, settings and the page."""
    from .cubs import registry as cubs
    return first_party() + cubs.loaded()


def is_cub(feature) -> bool:
    return getattr(feature, "data", None) is not None


def by_id(fid: str):
    f = next((f for f in features() if f.id == fid), None)
    if f is None:
        raise KeyError(fid)
    return f


def _search_kinds() -> tuple[str, ...]:
    from ..websearch import KINDS
    return tuple(KINDS)


def check() -> list[dict]:
    """Every manifest, validated; raises ManifestError on the first problem. A cub that no
    longer validates is the cub runtime's to pause, never a reason for Kranto not to start: it
    is left out here."""
    out, seen, kinds, purposes, actions = [], set(), {}, {}, {}
    for f in features():
        try:
            m = validate(f.to_manifest(), read_families=api.READ_FAMILIES,
                         request_kinds=tickets.kind_names(), core_kinds=events.CORE_KINDS,
                         search_kinds=_search_kinds(),
                         source="cub" if is_cub(f) else "feature", broker_ops=broker_ops())
        except ManifestError:
            if not is_cub(f):
                raise
            log.warning("cub %s no longer validates; its runtime pauses it", f.id)
            continue
        if f.id in seen:
            raise ManifestError(f"two features are called {f.id}")
        seen.add(f.id)
        for kind in m["events"]["publish"]:
            if kind in kinds:
                raise ManifestError(f"{kind} is published by {kinds[kind]} and {f.id}")
            kinds[kind] = f.id
        for p in m["model"]["purposes"]:
            if p in purposes:
                raise ManifestError(f"the purpose {p} is {purposes[p]}'s")
            purposes[p] = f.id
        for a in m["actions"]:
            if a["kind"] in actions:
                raise ManifestError(f"the action {a['kind']} is declared twice")
            actions[a["kind"]] = f.id
        for name in f.api:
            if name.split(".", 1)[0] in api.READ_FAMILIES and name not in api.V1:
                raise ManifestError(f"{f.id}.api: {name} uses a v1 family but is not a v1 read")
        out.append(m)
    return out


def enabled(cfg, feature) -> bool:
    """A feature's own ``<id>.enabled``; for a cub also ``cubs.enabled`` and
    ``cubs.<id>.enabled``, the owner's switches. On the preview a feature of
    ``preview.FORCED_OFF`` is off, whatever the copied settings say (line 2)."""
    from .. import preview
    if feature.id in preview.FORCED_OFF and preview.enabled(getattr(cfg, "root", None)):
        return False
    if is_cub(feature):
        from .cubs import settings as cub_settings
        if not (cub_settings.enabled(cfg) and cub_settings.cub_enabled(cfg, feature.id)):
            return False
    return bool(settings.section(cfg, feature.id).get(f"{feature.id}.enabled", True))


def context(rt, feature, **kw) -> FeatureContext:
    return FeatureContext(feature, rt, **kw)


def _runner(rt_ref, feature, job):
    """The scheduler's callable for one feature job: a context, the job, its run row. A job
    returns ``{"status": ..., ...}`` (its summary); one that raises is a failed run."""

    def run():
        rt = rt_ref()
        if refused(rt.store, feature):
            return None
        started = utcnow()
        from .. import activity
        ctx = context(rt, feature, run_uuid=activity.run_uuid(job.kind))
        try:
            summary = job.run(ctx) or {}
            status = summary.pop("status", "ok") if isinstance(summary, dict) else "ok"
            error = None
        except Exception as exc:  # noqa: BLE001 - recorded; the scheduler keeps going
            log.exception("%s raised", job.kind)
            status, summary, error = "failed", {}, f"{type(exc).__name__}: {exc}"[:300]
        record_run(rt.store, job.kind, status if status in ("ok", "degraded", "failed",
                                                            "skipped") else "ok",
                   started, summary, error, run_uuid=ctx.run_uuid)
        return summary

    return run


def jobs(rt_ref) -> list:
    """The scheduler's jobs for every feature. ``rt_ref`` returns the live Runtime (its config
    changes when a setting is written)."""
    out = []
    for f in first_party():
        for j in f.jobs:
            out.append(_FeatureJob(j.kind, j.every_hours, _runner(rt_ref, f, j), rt_ref, f, j))
    return out


class _FeatureJob:
    """A scheduler ``Job`` whose interval is 0 (off) while its feature or ``when`` is off."""

    def __init__(self, kind, every, run, rt_ref, feature, job) -> None:
        self.kind, self._every, self.run = kind, every, run
        self._rt_ref, self.feature, self.job = rt_ref, feature, job

    @property
    def every_hours(self) -> float:
        cfg = self._rt_ref().cfg
        if not enabled(cfg, self.feature):
            return 0
        if self.job.when and not settings.section(cfg, self.feature.id).get(self.job.when):
            return 0
        return self._every


def deliver(rt) -> dict:
    out: dict = {}
    cubs = getattr(rt, "cubs", None)
    if cubs is not None:
        out.update(cubs.deliver_all())
    subs = [(f.id, s.kind, s.min_trust, s.handler) for f in first_party()
            for s in f.events.subscribes if s.handler is not None and enabled(rt.cfg, f)]
    if not subs:
        return out
    by = {f.id: f for f in first_party()}
    out.update(events.deliver(rt.store, subs, lambda fid: context(rt, by[fid])))
    return out


# -- pins -----------------------------------------------------------------------------------------


def _latest_pin(store: Store, fid: str):
    return store.query_one("SELECT * FROM cub_pins WHERE cub = ? ORDER BY id DESC LIMIT 1",
                           (fid,))


def pin(store: Store, now: datetime | None = None) -> dict[str, str]:
    """Record each feature's manifest hash; ``{id: "pinned" | "same" | "refused: ..."}``."""
    out = {}
    for f in first_party():             # a cub's pin is written by its install, never here
        h = manifest_hash(f.to_manifest())
        last = _latest_pin(store, f.id)
        if last is not None and last["manifest_hash"] == h:
            out[f.id] = "same"
            continue
        if last is not None and f.trust != "first-party" and last["version"] == f.version:
            out[f.id] = "refused: its manifest changed without a new version"
            continue
        store.insert("cub_pins", {"cub": f.id, "version": f.version, "trust": f.trust,
                                  "manifest_hash": h, "created_at": iso(now or utcnow())})
        out[f.id] = "pinned"
    return out


def refused(store: Store, feature) -> str | None:
    """Why a feature may not run: a non-first-party manifest that differs from its pin; for a
    cub, why its runtime paused it."""
    if is_cub(feature):
        from .cubs import registry as cubs
        row = cubs.latest(store, feature.id)
        if row is None or row["state"] == "removed":
            return "not installed"
        if row["state"] == "paused":
            return f"paused: {row['note'] or 'by the core'}"
        pin_row = _latest_pin(store, feature.id)
        if pin_row is None or pin_row["manifest_hash"] != row["manifest_hash"] \
                or pin_row["tree_hash"] != row["tree_hash"]:
            return "its pin is not the one approved"
        return None
    if feature.trust == "first-party":
        return None
    last = _latest_pin(store, feature.id)
    if last is None:
        return "not pinned yet"
    if last["manifest_hash"] != manifest_hash(feature.to_manifest()):
        return "its manifest is not the one approved"
    return None


# -- the listing ----------------------------------------------------------------------------------


def _last_run(store: Store, kinds: list[str]) -> dict | None:
    if not kinds:
        return None
    r = store.query_one(f"SELECT kind, status, finished_at FROM runs WHERE kind IN "
                        f"({','.join('?' * len(kinds))}) ORDER BY finished_at DESC LIMIT 1",
                        tuple(kinds))
    return dict(r) if r else None


def mode_of(rt, feature, values: dict, on: bool) -> str:
    """The word on its mode tag: ``off`` while it is off; its own ``mode(ctx)``, else a
    ``<id>.mode`` setting, else ``live``."""
    if not on:
        return "off"
    if feature.mode is not None:
        try:
            return str(feature.mode(context(rt, feature)))
        except Exception:  # noqa: BLE001 - a listing never fails on one feature's word
            log.exception("%s: its mode could not be read", feature.id)
            return "unknown"
    return str(values.get(f"{feature.id}.mode") or "live")


def tile_of(rt, feature, on: bool) -> dict | None:
    """The home tile with its count read now (row 1), so the home is one read. A
    count that cannot be read is null and the tile says its line only."""
    t = feature.ui.tile
    if t is None:
        return None
    count = None
    line = t.line
    if on and t.count and t.count in feature.api:
        try:
            got = feature.api[t.count](context(rt, feature), {})
            count = int(got["count"]) if isinstance(got, dict) and "count" in got else None
            # the count read may say the tile's line for now: words on its own tile only,
            # never the band
            if isinstance(got, dict) and isinstance(got.get("line"), str) and got["line"]:
                line = got["line"][:120]
        except Exception:  # noqa: BLE001 - as above
            log.exception("%s: its tile's count could not be read", feature.id)
    return {"line": line, "count": count, "words": t.words, "tone": t.tone}


def _described(rt, f) -> dict:
    """One feature's row of ``describe``."""
    from . import asks
    m = f.to_manifest()
    values = settings.section(rt.cfg, f.id)
    pin_row = _latest_pin(rt.store, f.id)
    open_n = sum(1 for t in tickets.listing(rt.store, cub=f.id, open_only=True))
    on = enabled(rt.cfg, f)
    cubs = getattr(rt, "cubs", None)
    cub = cubs.describe(f.id) if is_cub(f) and cubs is not None else None
    if cub is not None and cub["state"] != "installed":
        on = False
    return {
        "id": f.id, "title": f.title, "says": f.says, "version": f.version,
        "trust": f.trust, "enabled": on, "mode": mode_of(rt, f, values, on),
        "pinned": refused(rt.store, f) is None if is_cub(f)
        else bool(pin_row and pin_row["manifest_hash"] == manifest_hash(m)),
        "refused": refused(rt.store, f),
        "last_run": _last_run(rt.store, [j.kind for j in f.jobs]),
        "tickets_open": open_n, "spend": api.spend_of(rt.store, f),
        # what it asks you now, as Needs you lists it (open, or a draft offered again: SEND)
        "asks": asks.count(rt.store, f.id),
        "tile": tile_of(rt, f, on),
        "settings": settings.describe(f, values), "manifest": m,
        **({"cub": cub} if cub is not None else {})}


def listed(cfg, feature) -> bool:
    """Whether the page lists ``feature``: every cub (one the owner turned off is listed, so
    it can be turned on again), and Kranto's own features while they are on. A built-in feature
    that is off has no row, so no Settings page and no palette entry; its
    settings file's ``<id>.enabled: true`` brings it back."""
    return is_cub(feature) or enabled(cfg, feature)


def describe(rt) -> dict:
    """``GET /api/features``: every feature the page lists (``listed``) with its manifest,
    trust, mode, pin, last run, open tickets, settings and its home tile resolved; every
    request kind's read-back schema."""
    from ..rowsafe import each
    shown = [f for f in features() if listed(rt.cfg, f)]
    # one feature or cub that cannot be read is listed as such, never the list (RCA A3)
    rows = each(shown, lambda f: _described(rt, f), "feature",
                keep=lambda f: {"title": f.title, "trust": f.trust})
    return {"features": rows, "api": m_api(), "reads": list(api.V1),
            # Invest's broker left Kranto (cut 2): null, for a page that reads it
            "broker": None,
            "request_kinds": list(tickets.kind_names()),
            "request_schemas": tickets.describe_kinds()}


CHECK_MAX_BYTES = 64 * 1024


def broker_ops() -> dict[str, set[str]]:
    """Each broker service's operations a cub may be granted (read and draft; a perform
    operation is never grantable): empty until a broker adapter is registered."""
    try:
        from .cubs import brokers
    except ImportError:
        return {}
    return brokers.grantable()


def published_kinds(skip: str | None = None) -> dict[str, str]:
    """Every event kind an installed feature or cub publishes, to its publisher."""
    out = {}
    for f in features():
        if f.id != skip:
            for kind in f.events.publishes:
                out[kind] = f.id
    return out


def validate_cub(data: dict, *, files: set[str] | None = None, update_of: str | None = None
                 ) -> dict:
    """A ``cub.yaml`` checked by the one validator against what this core can grant,
    its defaults filled. ``update_of``: the installed cub it replaces (its own kinds are not a
    clash)."""
    return validate(data, read_families=api.READ_FAMILIES, request_kinds=tickets.kind_names(),
                    core_kinds=events.CORE_KINDS, search_kinds=_search_kinds(), source="cub",
                    broker_ops=broker_ops(), files=files, published=published_kinds(update_of))


def load_cub_yaml(text: str) -> dict:
    """A ``cub.yaml``'s text as data: YAML, at most 64 KB, a mapping. ManifestError if not."""
    import yaml

    if not isinstance(text, str) or not text.strip():
        raise ManifestError("paste the cub's cub.yaml")
    if len(text.encode()) > CHECK_MAX_BYTES:
        raise ManifestError(f"a manifest is at most {CHECK_MAX_BYTES // 1024} KB")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"not YAML: {str(exc).splitlines()[0]}") from None
    if not isinstance(data, dict):
        raise ManifestError("a manifest is a mapping of keys")
    return data


def check_text(text: str) -> dict:
    """Read a cub's ``cub.yaml`` (pasted on the Cubs page) and check it with the one
    validator, against what this core can grant. Nothing is installed or run: the install
    dialog draws the answer in words. A cub added this way is ``unreviewed`` whatever its file
    says (the core decides trust,). The hash is the file's as written (the pin)."""
    try:
        data = load_cub_yaml(text)
        digest = manifest_hash(data)
        m = validate_cub(data)
    except ManifestError as exc:
        return {"ok": False, "error": str(exc)}
    if any(f.id == m["id"] for f in features()):
        return {"ok": False, "error": f"{m['id']} is already installed"}
    from .cubs import inspect
    from .manifest import grants_of
    words = inspect.words(m, grants_of(m), trust="unreviewed",
                          cap_usd=(m.get("model") or {}).get("monthly_usd"))
    m["trust"] = "unreviewed"
    return {"ok": True, "trust": "unreviewed", "manifest": json.loads(json.dumps(m, default=str)),
            "hash": digest, "installable": False, "words": words, "findings": [],
            "why": "a pasted cub.yaml is only checked: add the cub from its folder or its git "
                   "URL to install it (its code is read then)"}


def m_api() -> str:
    from .manifest import API
    return API


def manifests_json() -> str:
    return json.dumps(check(), indent=2, sort_keys=True)
