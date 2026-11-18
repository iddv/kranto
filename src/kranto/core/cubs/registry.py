"""Installed cubs: the ``cubs`` table, one row per state change, the
newest row of each cub counting (``installed``, ``paused``, ``removed``), and each installed
cub as a ``Feature`` whose callables forward over its pipe, so the registry, the scheduler,
``GET /api/features``, settings, the bus, tickets and the pin serve Kranto's own features and
cubs through one code path.

``loaded()`` is that tuple of Features, set by the runtime when it starts and again whenever a
cub is installed, updated, removed, paused or resumed; ``core.registry.features()`` is Kranto's
own features plus it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...store import Store, iso, utcnow
from ...stored.cubs import CubSource, Grants
from ..manifest import Feature, ManifestError
from . import files

log = logging.getLogger("kranto.core.cubs")
STATES = ("installed", "paused", "removed")
_LOADED: tuple[Any, ...] = ()


def loaded() -> tuple[Any, ...]:
    """The installed (and paused) cubs as Features, as the runtime last loaded them."""
    return _LOADED


def set_loaded(features: tuple[Any, ...]) -> None:
    global _LOADED
    _LOADED = tuple(features)


@dataclass
class Installed:
    """A cub as the registry knows it: its newest row, its approved manifest and grants."""

    id: str
    version: str
    trust: str
    state: str
    source_kind: str
    source: dict[str, Any]
    sha: str | None
    tree_hash: str
    manifest_hash: str
    grants: Grants
    bears_range: str | None
    note: str | None
    created_at: str
    dir: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    feature: Feature | None = None

    @property
    def requirements(self) -> str | None:
        return self.manifest.get("requirements")

    @property
    def entry(self) -> str:
        return self.manifest.get("entry") or "main.py"


def latest_rows(store: Store) -> dict[str, dict[str, Any]]:
    """The newest row of every cub that ever had one."""
    rows = store.query("SELECT c.* FROM cubs c WHERE c.id = (SELECT MAX(id) FROM cubs d "
                       "WHERE d.cub = c.cub) ORDER BY c.cub")
    return {r["cub"]: dict(r) for r in rows}


def latest(store: Store, cid: str) -> dict[str, Any] | None:
    r = store.query_one("SELECT * FROM cubs WHERE cub = ? ORDER BY id DESC LIMIT 1", (cid,))
    return dict(r) if r else None


def append(store: Store, row: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A new row: the cub's newest with ``changes`` (a state, a note, a new version)."""
    new = {k: v for k, v in row.items() if k != "id"}
    new.update(changes)
    if isinstance(new.get("source"), dict):
        new["source"] = CubSource.write(new["source"])
    if isinstance(new.get("grants"), Grants):
        new["grants"] = new["grants"].to_json()
    elif isinstance(new.get("grants"), dict):
        new["grants"] = Grants.write(new["grants"])
    new["created_at"] = iso(utcnow())
    new["id"] = store.insert("cubs", new)
    return new


def installed(cfg: Any, row: dict[str, Any]) -> Installed:
    return Installed(
        id=row["cub"], version=row["version"], trust=row["trust"], state=row["state"],
        source_kind=row["source_kind"],
        source=CubSource.load(row["source"]).extra,
        sha=row.get("sha"), tree_hash=row["tree_hash"], manifest_hash=row["manifest_hash"],
        grants=Grants.load(row["grants"]),
        bears_range=row.get("bears_range"), note=row.get("note"), created_at=row["created_at"],
        dir=files.cub_dir(cfg, row["cub"]))


def read_manifest(cub: Installed, *, update_of: str | None = None) -> dict[str, Any]:
    """The cub's ``cub.yaml`` as vendored, validated against what this Kranto can grant now
    (defaults filled). Raises ManifestError."""
    from .. import registry as core_registry
    path = cub.dir / "src" / "cub.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"its cub.yaml cannot be read: {exc.strerror}") from None
    data = core_registry.load_cub_yaml(text)
    return core_registry.validate_cub(data, update_of=update_of or cub.id)


def ensure_pin(store: Store, cub: Installed) -> None:
    """``cub_pins`` holds the cub's hashes at its version (written by the install; a cub row
    without its pin is a bug the doctor names)."""
    r = store.query_one("SELECT manifest_hash, tree_hash FROM cub_pins WHERE cub = ? ORDER BY "
                        "id DESC LIMIT 1", (cub.id,))
    if r is None or r["manifest_hash"] != cub.manifest_hash or r["tree_hash"] != cub.tree_hash:
        raise ManifestError("its pin does not match its registry row")


# The owner's own site cub, from before Kranto shipped its blog writer (the ``cubs`` row,
# G4): it keeps its id, its settings, its drafts and its asks, so the owner's
# blog posts keep working on their data, but a person reads it as "Blog", never the site's name,
# and its build launch post (builds left) is not offered. Its verbs' tool names read the same way
# (the page's mcp/tools.py: kranto_f_examplecom_* is kranto_f_blog_*).
SITE_CUBS = {"examplecom": {
    "title": "Blog",
    "says": "Drafts a blog post from a week of briefs, a topic or your own markdown, for you to "
            "read and file as a draft; you publish it yourself.",
    "tile": "Blog posts, filed as drafts"}}
SITE_DROPPED = (".draft_build",)          # a build's launch post: builds left


def _drop_submits(node: Any, gone: set[str]) -> Any:
    """``node`` without the forms (any dict) whose ``submit`` is one of ``gone``."""
    if isinstance(node, list):
        return [_drop_submits(x, gone) for x in node
                if not (isinstance(x, dict) and x.get("submit") in gone)]
    if isinstance(node, dict):
        return {k: _drop_submits(v, gone) for k, v in node.items()}
    return node


def shown_manifest(cid: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest as a person reads it: a site cub's words are the blog's (``SITE_CUBS``);
    every other cub's are its own. Its kinds, ids and settings are untouched."""
    words = SITE_CUBS.get(cid)
    if not words or not isinstance(manifest, dict):
        return manifest
    m = dict(manifest)
    m["title"], m["says"] = words["title"], words["says"]
    gone = {a["kind"] for a in m.get("actions") or []
            if isinstance(a, dict) and str(a.get("kind", "")).endswith(SITE_DROPPED)}
    if gone:
        m["actions"] = [a for a in m.get("actions") or []
                        if not (isinstance(a, dict) and a.get("kind") in gone)]
        if "ui" in m:
            m["ui"] = _drop_submits(m["ui"], gone)
    ui = m.get("ui")
    if isinstance(ui, dict) and isinstance(ui.get("tile"), dict):
        m["ui"] = {**ui, "tile": {**ui["tile"], "line": words["tile"]}}
    return m


# The site cub as a registry alias (the ``cubs`` row; CUT, handed over by): an
# install row of the owner's ``examplecom`` that points at a git source's ``cubs/examplecom``
# or at the old
# example is read as Kranto's built-in ``blog``, at Kranto's version. Its rows are read, never
# rewritten: the cub keeps its id underneath, so its process, its folder, its tickets and asks
# (``f.examplecom.*``) keep working on their data. Listed, it is one cub, ``blog`` (none of its own
# once Kranto's blog writer is installed beside it); a page's ``/api/cubs/blog/...`` reaches it
# while it stands in for the blog; the blog writer reads the examplecom settings it has no value of
# its own for (``settings.cub_value``).
SITE_ALIASES = {"examplecom": "blog"}            # the old site cub's id -> the built-in it reads as


def is_site_row(row: dict[str, Any] | None) -> bool:
    """Whether a registry row is the owner's site cub read as the built-in (``SITE_ALIASES``):
    its id is one, and its source names it (a git source's ``cubs/examplecom``, the old example's
    folder) or says nowhere at all. Never assumes the stored shape of ``source``."""
    if not isinstance(row, dict) or row.get("cub") not in SITE_ALIASES:
        return False
    try:
        src = CubSource.load(row.get("source")).extra
    except (TypeError, ValueError):
        src = {}
    where = " ".join(str(v) for k, v in src.items() if k in ("url", "path", "subdirectory"))
    return not where.strip() or row["cub"] in where


def _live(row: dict[str, Any] | None) -> bool:
    return isinstance(row, dict) and row.get("state") in ("installed", "paused")


def listed(rows: dict[str, dict[str, Any]]) -> list[tuple[str, str, dict[str, Any]]]:
    """``(the id shown, the cub's own id, its row)`` for every cub, in id order: a site cub is
    shown as its built-in (``blog``) while no built-in row of that id is live, and not at all
    once one is (one blog cub, never two)."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for cid, row in rows.items():
        target = SITE_ALIASES.get(cid)
        if target and is_site_row(row) and _live(row):
            if _live(rows.get(target)):
                continue
            out.append((target, cid, row))
        else:
            out.append((cid, cid, row))
    return sorted(out, key=lambda x: (x[0], x[1] != x[0]))


def resolve(store: Store, cid: str) -> str:
    """The cub a page's id means: ``blog`` is the site cub while it stands in for Kranto's blog
    writer (no live ``blog`` row, a live site row); every other id is itself."""
    for old, target in SITE_ALIASES.items():
        if cid == target and not _live(latest(store, target)):
            row = latest(store, old)
            if _live(row) and is_site_row(row):
                return old
    return cid


def alias_sources(cid: str) -> tuple[str, ...]:
    """The ids whose settings ``cid`` reads where it has none of its own (``blog``:
    ``examplecom``)."""
    return tuple(old for old, target in SITE_ALIASES.items() if target == cid)


def builtin_version(cid: str) -> str | None:
    """The version Kranto ships of a built-in cub (its folder's ``cub.yaml``), or None."""
    try:
        import yaml

        from ...cubs import examples_dir
        data = yaml.safe_load((examples_dir() / cid / "cub.yaml").read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return None
    except Exception:  # noqa: BLE001 - a YAML error: no version to say
        return None
    v = data.get("version") if isinstance(data, dict) else None
    return str(v) if isinstance(v, str | int | float) else None


def describe_row(cub: Installed) -> dict[str, Any]:
    return {"id": cub.id, "version": cub.version, "trust": cub.trust, "state": cub.state,
            "source": {"kind": cub.source_kind, **cub.source, "sha": cub.sha},
            "note": cub.note, "installed_at": cub.created_at}
