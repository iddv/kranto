"""Topic packs: a YAML file of topics with hand-picked sources.

A pack is the no-scout way to start: no model call, just topics and sources a
person already trusts. Every source is test-fetched before it is approved;
ones that fail are reported and skipped, not silently added.

A pack may also have a top-level ``sources`` list: broad sources linked to no
topic. Their items skip the topic prefilter and are all judged, which is the
broad lane: the aperture that topic-first sourcing would otherwise close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import library, sources
from .embed import Embedder
from .store import Store
from .stored.sources import Validation


@dataclass
class PackReport:
    topics: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def load_pack(
    store: Store, embedder: Embedder, http: sources.HTTP, path: Path, *, check: bool = True
) -> PackReport:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = raw if isinstance(raw, dict) else {}
    topics = raw.get("topics") or []
    broad = raw.get("sources") or []
    if not isinstance(topics, list) or not isinstance(broad, list) or not (topics or broad):
        raise ValueError(f"{path}: expected a 'topics' list, a 'sources' list, or both")
    report = PackReport()
    for t in topics:
        if not isinstance(t, dict) or not t.get("name") or not t.get("description"):
            raise ValueError(f"{path}: every topic needs a name and a description")
        existing = {x.name: x.id for x in library.active_topics(store) if x.kind == "user"}
        topic_id = existing.get(t["name"]) or library.add_topic(
            store, embedder, str(t["name"]), str(t["description"]))
        report.topics.append(str(t["name"]))
        for s in t.get("sources") or []:
            _add(store, http, s, topic_id, check, report)
    for s in broad:
        _add(store, http, s, None, check, report)
    return report


def _add(store: Store, http: sources.HTTP, entry, topic_id: int | None, check: bool,
         report: PackReport) -> None:
    entry = entry if isinstance(entry, dict) else {}
    kind, value = str(entry.get("kind", "")), str(entry.get("value", ""))
    try:
        params = sources.params_from_value(kind, value)
        adapter = sources.build(kind, params, http)
        validation = None
        if check:
            validation = Validation.checked_by("pack", len(adapter.fetch()))
    except (ValueError, TypeError, sources.SourceError) as exc:
        report.failed.append((f"{kind} {value}", str(exc)))
        return
    source_id = library.add_source(store, kind, params, label=adapter.label,
                                   validation=validation)
    if topic_id is not None:
        library.link_topic_source(store, topic_id, source_id)
    report.added.append(adapter.label)
