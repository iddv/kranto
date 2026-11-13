"""Domain operations over the store: topics, sources, items, observations."""

from __future__ import annotations

import re
import sqlite3
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from . import sources as sources_mod
from .embed import Embedder
from .store import Store, blob_to_vec, iso, utcnow, vec_to_blob
from .stored.misc import TopicChanged
from .stored.observations import Tags
from .stored.sources import Params, Validation

# Outcomes after which an item is never looked at again.
TERMINAL_OUTCOMES = frozenset(
    {"contributed", "gated", "skipped", "parse_failed", "prefiltered", "item_error", "duplicate",
     "near_duplicate", "removed", "stale", "screened_out", "sponsored"}
)
# Outcomes that mean a model has already read this content. A prefiltered item
# does not count: another source's topics may admit it. A screened-out one does:
# the screen read it with its topics as context, as the judge does.
JUDGED_OUTCOMES = ("contributed", "gated", "skipped", "screened_out")
# ``admitted_by`` of observations that are children of another (observation_links):
# a deep dive's and those gathered with an item at ingest.
CHILD_ADMISSIONS = ("deep_dive", "gathered")
# ``admitted_by`` of observations imported from another library (``importers.py``): they
# keep the time they were observed there, are on the map but never arrivals, and are
# cited by the map's idea runs only when ``parallax.card_evidence`` is set.
IMPORTED = "import"


@dataclass(frozen=True)
class Topic:
    id: int
    name: str
    description: str
    embedding: np.ndarray
    # ``user`` (the owner's own) or ``project`` (one the page created for a project it
    # keeps; migration 23). Set at insert, never updated.
    kind: str = "user"
    ref: str | None = None


def _topic(r: sqlite3.Row) -> Topic:
    return Topic(r["id"], r["name"], r["description"], blob_to_vec(r["embedding"]),
                 r["kind"] or "user", r["ref"])


@dataclass(frozen=True)
class SourceRow:
    id: int
    kind: str
    params: dict[str, Any]
    label: str
    origin: str
    status: str | None
    # What the test fetch found (kranto.stored.sources): None for a Parallax import.
    validation: Validation | None


# -- topics ----------------------------------------------------------------------


TOPIC_KINDS = ("user", "project")
# A project topic's ``ref``: the page's key for the project it gathers for.
PROJECT_REF = re.compile(r"project:[a-z0-9]{1,40}")


def topic_by_ref(store: Store, ref: str) -> Topic | None:
    """The current topic with this ``ref`` (active or paused), or None."""
    row = store.query_one(
        "SELECT t.* FROM topics_now t WHERE t.ref = ? AND NOT EXISTS "
        "(SELECT 1 FROM topics newer WHERE newer.supersedes = t.id) ORDER BY t.id LIMIT 1",
        (ref,))
    return _topic(row) if row else None


def add_topic(
    store: Store, embedder: Embedder, name: str, description: str, *, now: datetime | None = None,
    kind: str = "user", ref: str | None = None,
) -> int:
    return add_topic_once(store, embedder, name, description, now=now, kind=kind, ref=ref)[0]


def add_topic_once(
    store: Store, embedder: Embedder, name: str, description: str, *, now: datetime | None = None,
    kind: str = "user", ref: str | None = None,
) -> tuple[int, bool]:
    """Add a topic: ``(id, existing)``. A project topic is keyed by its ``ref``: adding one
    whose ``ref`` is already a topic returns that topic (``existing`` True) and adds nothing."""
    name, description = name.strip(), description.strip()
    if kind not in TOPIC_KINDS:
        raise ValueError(f"a topic's kind is {' or '.join(TOPIC_KINDS)}")
    if kind == "project":
        if not isinstance(ref, str) or not PROJECT_REF.fullmatch(ref):
            raise ValueError("a project topic needs a ref like project:<id> "
                             "(lowercase letters and digits, at most 40)")
    elif ref is not None:
        raise ValueError("only a project topic has a ref")
    if ref is not None and (found := topic_by_ref(store, ref)) is not None:
        return found.id, True
    if not name or not description:
        raise ValueError("a topic needs a name and a description")
    # A topic is a question asked of every item, so it takes the query prefix.
    vec = embedder.embed_query(f"{name}: {description}")
    row = {
        "name": name,
        "description": description,
        "embedding": vec_to_blob(vec),
        "embedding_model": embedder.model_name,
        "created_at": iso(now or utcnow()),
    }
    if ref is None:
        from .features.news.brief import news_topics_row
        with store.tx():
            topic_id = store.insert("topics", row)
            store.set_status("topic", topic_id, "active", now=now)
            # News on for a topic the owner makes: its first brief comes when its
            # first read ends; the topic's page can turn it off
            store.insert("news_topics", news_topics_row(topic_id, str(row["created_at"])))
        return topic_id, False
    row |= {"kind": kind, "ref": ref}
    with store.tx():
        # checked again inside the write lock: two requests with one ref add one topic
        if (found := topic_by_ref(store, ref)) is not None:
            return found.id, True
        topic_id = store.insert("topics", row)
        store.set_status("topic", topic_id, "active", now=now)
    return topic_id, False


# Topic kinds held as paused for this process (``configure``): with builds off (PR
# 1.1) a project topic is not read or matched, and is listed as paused, without a status row
# being written, so turning builds on again finds it exactly as it was.
HELD_KINDS: frozenset[str] = frozenset()


def configure(*, held_kinds: frozenset[str] | set[str] | tuple[str, ...] = ()) -> None:
    """Set the topic kinds held as paused (the runtime sets it from ``builds.enabled``)."""
    global HELD_KINDS
    HELD_KINDS = frozenset(held_kinds)


def held(topic: Topic) -> bool:
    """Whether ``topic`` is held as paused by a switch (not by the owner's Pause)."""
    return topic.kind in HELD_KINDS


def active_topics(store: Store) -> list[Topic]:
    """The topics read and matched: active, not superseded, and of a kind not held."""
    return [t for t in _active_topics(store) if t.kind not in HELD_KINDS]


def _active_topics(store: Store) -> list[Topic]:
    rows = store.query(
        """
        SELECT t.* FROM topics_now t
        WHERE NOT EXISTS (SELECT 1 FROM topics newer WHERE newer.supersedes = t.id)
          AND (SELECT status FROM status_events s WHERE s.entity = 'topic' AND s.entity_id = t.id
               ORDER BY s.id DESC LIMIT 1) = 'active'
        ORDER BY t.id
        """
    )
    return [_topic(r) for r in rows]


# A topic is active (read and matched) or paused (its sources are not fetched; nothing is
# removed). Pausing is the owner's switch on the Topics tab. Archived is paused and off
# the owner's lists: its evidence, themes and cards stay readable, and Undo (or Restore)
# makes it active or paused again. Only ``topics_with_status(archived=True)`` lists it.
TOPIC_STATUSES = ("active", "paused")
ARCHIVED = "archived"
# what an owner's edit may hold (``edit_topic``)
NAME_MAX, DESCRIPTION_MAX = 120, 2000


def topics_with_status(store: Store, *, archived: bool = False,
                       stored: bool = False) -> list[tuple[Topic, str, str]]:
    """Every current topic, active or paused (and archived ones when ``archived``):
    ``(topic, status, created_at)``. A topic of a held kind (``configure``) reads as paused
    unless ``stored`` asks for the status as written."""
    out = _topics_with_status(store, archived=archived)
    if stored or not HELD_KINDS:
        return out
    return [(t, "paused" if s == "active" and t.kind in HELD_KINDS else s, c)
            for t, s, c in out]


def _topics_with_status(store: Store, *, archived: bool) -> list[tuple[Topic, str, str]]:
    rows = store.query(
        """
        SELECT t.*, (SELECT status FROM status_events s WHERE s.entity = 'topic'
                     AND s.entity_id = t.id ORDER BY s.id DESC LIMIT 1) AS status
        FROM topics_now t
        WHERE NOT EXISTS (SELECT 1 FROM topics newer WHERE newer.supersedes = t.id)
        ORDER BY t.id
        """
    )
    keep = (*TOPIC_STATUSES, ARCHIVED) if archived else TOPIC_STATUSES
    return [(_topic(r), r["status"], r["created_at"]) for r in rows if r["status"] in keep]


def set_topic_status(store: Store, topic_id: int, status: str, note: str | None = None) -> bool:
    """Pause, resume, archive or restore a topic. False when it already had that status."""
    if status not in (*TOPIC_STATUSES, ARCHIVED):
        raise ValueError(f"a topic is {', '.join(TOPIC_STATUSES)} or {ARCHIVED}")
    rows = topics_with_status(store, archived=True, stored=True)
    current = {t.id: s for t, s, _ in rows}
    if topic_id not in current:
        raise ValueError(f"no topic {topic_id}")
    if any(t.id == topic_id and held(t) for t, _, _ in rows):
        raise ValueError("a project's topic stays paused while builds are off "
                         "(builds.enabled in the config)")
    if current[topic_id] == status:
        return False
    store.set_status("topic", topic_id, status, note)
    return True


def edit_topic(store: Store, embedder: Embedder, topic_id: int, *, name: str | None = None,
               description: str | None = None, by: str, note: str | None = None,
               now: datetime | None = None) -> dict[str, Any] | None:
    """The owner's edit of a topic's name or description: a new ``topic_revisions`` row
    (its id kept, so every page, card and cub that names it reads the new words at once), its
    embedding made again from them. None changes nothing; the same words change nothing
    (returns None). A project topic follows its project and is not edited here."""
    found = next((t for t, _, _ in topics_with_status(store, archived=True)
                  if t.id == topic_id), None)
    if found is None:
        raise ValueError(f"no topic {topic_id}")
    if found.kind != "user":
        raise ValueError("a project's topic follows its project: it is not edited here")
    new_name = found.name if name is None else " ".join(str(name).split())
    new_desc = found.description if description is None else str(description).strip()
    if not new_name or not new_desc:
        raise ValueError("a topic needs a name and a description")
    if len(new_name) > NAME_MAX:
        raise ValueError(f"a topic's name is at most {NAME_MAX} characters")
    if len(new_desc) > DESCRIPTION_MAX:
        raise ValueError(f"a topic's description is at most {DESCRIPTION_MAX} characters")
    if any(t.id != topic_id and t.name.casefold() == new_name.casefold()
           for t, _, _ in topics_with_status(store, archived=True)):
        raise ValueError(f"another topic is called {new_name}")
    changed = [k for k, old, new in (("name", found.name, new_name),
                                     ("description", found.description, new_desc)) if old != new]
    if not changed:
        return None
    vec = embedder.embed_query(f"{new_name}: {new_desc}")
    at = iso(now or utcnow())
    rid = store.insert("topic_revisions", {
        "topic_id": topic_id, "name": new_name, "description": new_desc,
        "embedding": vec_to_blob(vec), "embedding_model": embedder.model_name,
        "changed": TopicChanged.write(list(changed)), "by": by, "note": note,
        "created_at": at})
    return {"id": rid, "topic_id": topic_id, "changed": changed, "by": by, "created_at": at,
            "before": {"name": found.name, "description": found.description},
            "after": {"name": new_name, "description": new_desc}}


def topic_history(store: Store, topic_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """A topic's changes, newest first: its edits (``topic_revisions``), its sources added or
    removed (``topic_source_events``) and its status changes, each with who and when."""
    out = [{"what": "edit", "changed": TopicChanged.load(r["changed"]).items,
            "name": r["name"],
            "by": r["by"], "note": r["note"], "at": r["created_at"]}
           for r in store.query("SELECT * FROM topic_revisions WHERE topic_id = ? "
                                "ORDER BY id DESC LIMIT ?", (topic_id, limit))]
    out += [{"what": r["op"], "source_id": r["source_id"], "source": r["label"], "by": r["by"],
             "note": r["note"], "at": r["created_at"]}
            for r in store.query("SELECT e.*, s.label FROM topic_source_events e "
                                 "LEFT JOIN sources s ON s.id = e.source_id WHERE e.topic_id = ? "
                                 "ORDER BY e.id DESC LIMIT ?", (topic_id, limit))]
    out += [{"what": "status", "status": r["status"], "note": r["note"], "at": r["created_at"]}
            for r in store.query("SELECT * FROM status_events WHERE entity = 'topic' AND "
                                 "entity_id = ? ORDER BY id DESC LIMIT ?", (topic_id, limit))]
    return sorted(out, key=lambda x: x["at"], reverse=True)[:limit]


def topic_names_ever(store: Store, topic_id: int) -> set[str]:
    """Every name a topic has had: a map made before a rename counts its stories under the
    old name (``clusters.topic_mix``)."""
    return {r["name"] for r in store.query(
        "SELECT name FROM topics WHERE id = ? UNION SELECT name FROM topic_revisions "
        "WHERE topic_id = ?", (topic_id, topic_id))}


def paused_topic_sources(store: Store) -> set[int]:
    """Sources linked to topics none of which is active. Ingest skips them: without a
    topic their items would skip the prefilter and all be judged, as a broad source's."""
    active = {t.id for t in active_topics(store)}
    links: dict[int, set[int]] = {}
    for r in store.query("SELECT topic_id, source_id FROM topic_links"):
        links.setdefault(r["source_id"], set()).add(r["topic_id"])
    return {s for s, ts in links.items() if not ts & active}


def _pair_op(store: Store, topic_id: int, source_id: int) -> str | None:
    r = store.query_one("SELECT op FROM topic_source_events WHERE topic_id = ? AND "
                        "source_id = ? ORDER BY id DESC LIMIT 1", (topic_id, source_id))
    return r["op"] if r else None


def link_topic_source(store: Store, topic_id: int, source_id: int, *, by: str | None = None,
                      note: str | None = None) -> bool:
    """Link a source to a topic; a pair removed before is linked again by a ``link`` row.
    False when it was linked already. Opens no transaction: callers may hold one."""
    known = store.query_one("SELECT 1 FROM topic_sources WHERE topic_id = ? AND "
                            "source_id = ?", (topic_id, source_id)) is not None
    if not known:
        store.query("INSERT OR IGNORE INTO topic_sources (topic_id, source_id, created_at) "
                    "VALUES (?, ?, ?)", (topic_id, source_id, iso(utcnow())))
        if by is not None:
            _pair_event(store, topic_id, source_id, "link", by, note)
        return True
    if _pair_op(store, topic_id, source_id) != "unlink":
        return False
    _pair_event(store, topic_id, source_id, "link", by or "kranto", note)
    return True


def unlink_topic_source(store: Store, topic_id: int, source_id: int, *, by: str,
                        note: str | None = None) -> bool:
    """Remove a source from one topic (an ``unlink`` row; nothing is deleted, its evidence
    stays). The source keeps its other topics. False when it was not linked."""
    if store.query_one("SELECT 1 FROM topic_links WHERE topic_id = ? AND source_id = ?",
                       (topic_id, source_id)) is None:
        return False
    _pair_event(store, topic_id, source_id, "unlink", by, note)
    return True


def _pair_event(store: Store, topic_id: int, source_id: int, op: str, by: str,
                note: str | None) -> None:
    store.insert("topic_source_events", {"topic_id": topic_id, "source_id": source_id,
                                         "op": op, "by": by, "note": note,
                                         "created_at": iso(utcnow())})


def topics_for_source(store: Store, source_id: int) -> list[Topic]:
    wanted = {
        r["topic_id"]
        for r in store.query("SELECT topic_id FROM topic_links WHERE source_id = ?", (source_id,))
    }
    return [t for t in active_topics(store) if t.id in wanted]


# -- sources ---------------------------------------------------------------------


def add_source(
    store: Store,
    kind: str,
    params: dict[str, Any],
    *,
    label: str,
    origin: str = "manual",
    status: str = "approved",
    origin_call_id: int | None = None,
    validation: Validation | Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> int:
    """Insert a source, or return the existing id for the same (kind, params). ``validation``
    is stored as its contract writes it (a dict is read through the contract first, so the
    column only ever holds what ``Validation`` reads back)."""
    if validation is not None and not isinstance(validation, Validation):
        validation = Validation.from_dict(validation)
    canonical = sources_mod.canonical_params(kind, params)
    existing = store.query_one(
        "SELECT id FROM sources WHERE kind = ? AND params = ?", (kind, canonical)
    )
    if existing:
        source_id = int(existing["id"])
        if store.current_status("source", source_id) != status and status == "approved":
            store.set_status("source", source_id, status, "re-added", now=now)
        return source_id
    source_id = store.insert(
        "sources",
        {
            "kind": kind,
            "params": canonical,
            "label": label,
            "origin": origin,
            "origin_call_id": origin_call_id,
            "validation": validation.to_json() if validation is not None else None,
            "created_at": iso(now or utcnow()),
        },
    )
    store.set_status("source", source_id, status, now=now)
    return source_id


def list_sources(store: Store, status: str | None = None) -> list[SourceRow]:
    rows = store.query(
        """
        SELECT src.*, (SELECT s.status FROM status_events s WHERE s.entity = 'source'
                       AND s.entity_id = src.id ORDER BY s.id DESC LIMIT 1) AS status
        FROM sources src ORDER BY src.id
        """
    )
    out = [
        SourceRow(
            r["id"], r["kind"], Params.load(r["params"]).kwargs(), r["label"], r["origin"],
            r["status"], Validation.parse(r["validation"]),
        )
        for r in rows
    ]
    return [s for s in out if status is None or s.status == status]


# -- items -----------------------------------------------------------------------


def seen_item_ids(store: Store, source_id: int) -> set[str]:
    return {
        r["item_id"]
        for r in store.query("SELECT item_id FROM items_seen WHERE source_id = ?", (source_id,))
    }


def mark_seen(
    store: Store,
    source_id: int,
    item_id: str,
    outcome: str,
    *,
    run_uuid: str | None,
    llm_call_id: int | None = None,
    topic_similarity: float | None = None,
    canonical_url: str | None = None,
    now: datetime | None = None,
    screen_call_id: int | None = None,
) -> None:
    if outcome not in TERMINAL_OUTCOMES:
        raise ValueError(f"{outcome!r} is not a terminal outcome; the item must stay unconsumed")
    store.insert(
        "items_seen",
        {
            "source_id": source_id,
            "item_id": item_id,
            "outcome": outcome,
            "llm_call_id": llm_call_id,
            "run_uuid": run_uuid,
            "topic_similarity": topic_similarity,
            "canonical_url": canonical_url,
            "created_at": iso(now or utcnow()),
            "screen_call_id": screen_call_id,
        },
    )


def already_judged(store: Store, canonical_url: str | None) -> bool:
    """Whether the judge has already read the content at ``canonical_url``,
    through any source or submission."""
    if not canonical_url:
        return False
    marks = ", ".join("?" for _ in JUDGED_OUTCOMES)
    return store.query_one(
        f"SELECT 1 AS hit FROM items_seen WHERE canonical_url = ? AND outcome IN ({marks}) "
        "LIMIT 1",
        (canonical_url, *JUDGED_OUTCOMES),
    ) is not None


@dataclass(frozen=True)
class Child:
    """A gathered source kept as an observation of its own, linked to its parent."""

    item: sources_mod.Item
    fields: dict[str, Any]
    embedding: np.ndarray
    relation: str  # "discussion" | "link" | "repository"


def record_observation(
    store: Store,
    *,
    source_id: int,
    item: sources_mod.Item,
    fields: dict[str, Any],
    embedding: np.ndarray,
    embedding_model: str,
    llm_call_id: int,
    prompt_version: str,
    run_uuid: str,
    admitted_by: str,
    topic_similarity: float | None,
    now: datetime | None = None,
    parent: dict[str, Any] | None = None,
    screen_call_id: int | None = None,
    children: Sequence[Child] = (),
    child_admitted_by: str = "gathered",
) -> int:
    """Append the observation and consume the item in one transaction.

    ``parent`` (``parent_id``, ``relation``, ``deep_dive_id``) records a deep
    dive's child: the link to its parent is written in the same transaction, so
    a child never exists without it. ``children`` are gathered sources the
    judge kept with this item: each is its own observation from the same
    call, consumed under its own id and linked to this one, in this same
    transaction (``children_ids`` lists them). Returns the item's observation id."""
    created = iso(now or utcnow())
    with store.tx() as conn:
        observation_id = _insert_observation(
            conn, source_id=source_id, item=item, fields=fields, embedding=embedding,
            embedding_model=embedding_model, llm_call_id=llm_call_id,
            prompt_version=prompt_version, run_uuid=run_uuid, admitted_by=admitted_by,
            topic_similarity=topic_similarity, created=created, screen_call_id=screen_call_id)
        if parent is not None:
            _link(conn, parent["parent_id"], observation_id, parent["relation"],
                  parent.get("deep_dive_id"), created)
        for child in children:
            child_id = _insert_observation(
                conn, source_id=source_id, item=child.item, fields=child.fields,
                embedding=child.embedding, embedding_model=embedding_model,
                llm_call_id=llm_call_id, prompt_version=prompt_version, run_uuid=run_uuid,
                admitted_by=child_admitted_by, topic_similarity=None, created=created,
                screen_call_id=None)
            _link(conn, observation_id, child_id, child.relation, None, created)
        return observation_id


def children_ids(store: Store, observation_id: int) -> list[int]:
    """Observations linked to ``observation_id`` as its children, oldest first."""
    return [r["child_id"] for r in store.query(
        "SELECT child_id FROM observation_links WHERE parent_id = ? ORDER BY id",
        (observation_id,))]


def _link(conn: sqlite3.Connection, parent_id: int, child_id: int, relation: str,
          deep_dive_id: int | None,
          created: str) -> None:
    conn.execute(
        "INSERT INTO observation_links (parent_id, child_id, relation, deep_dive_id, "
        "created_at) VALUES (?, ?, ?, ?, ?)",
        (parent_id, child_id, relation, deep_dive_id, created),
    )


def _insert_observation(conn: sqlite3.Connection, *, source_id: int, item: sources_mod.Item,
                        fields: dict[str, Any],
                        embedding: np.ndarray, embedding_model: str, llm_call_id: int,
                        prompt_version: str, run_uuid: str, admitted_by: str,
                        topic_similarity: float | None, created: str,
                        screen_call_id: int | None) -> int:
    cur = conn.execute(
        """
        INSERT INTO observations (
            source_id, item_id, run_uuid, llm_call_id, prompt_version, kind, title, summary,
            why_it_matters, content_quality, durability, opportunity, signal, override,
            override_reason, tags, source_url, source_excerpt, item_published_at, embedding,
            embedding_model, admitted_by, topic_similarity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id, item.id, run_uuid, llm_call_id, prompt_version, fields["kind"],
            item.title, fields["summary"], fields["why_it_matters"],
            fields["content_quality"], fields["durability"], fields["opportunity"],
            fields["signal"], int(fields["override"]), fields["override_reason"],
            Tags.write(list(fields["tags"])),
            sources_mod.safe_url(item.url) or sources_mod.safe_url(item.link),
            item.excerpt(),
            iso(item.published_at) if item.published_at else None,
            vec_to_blob(embedding), embedding_model, admitted_by, topic_similarity, created,
        ),
    )
    conn.execute(
        "INSERT INTO items_seen (source_id, item_id, outcome, llm_call_id, run_uuid, "
        "topic_similarity, canonical_url, created_at, screen_call_id) "
        "VALUES (?, ?, 'contributed', ?, ?, ?, ?, ?, ?)",
        (source_id, item.id, llm_call_id, run_uuid, topic_similarity, item.canonical_url(),
         created, screen_call_id),
    )
    assert cur.lastrowid is not None           # an INSERT always has one
    return int(cur.lastrowid)


def observation_embed_text(fields: dict[str, Any]) -> str:
    return f"{fields['summary']}\n{fields['why_it_matters']}"


# -- reading ---------------------------------------------------------------------

_OBS_COLUMNS = """
    o.id, o.source_id, o.kind, o.title, o.summary, o.why_it_matters, o.content_quality,
    o.durability, o.opportunity, o.signal, o.override, o.override_reason, o.tags, o.source_url,
    o.source_excerpt, o.item_published_at, o.admitted_by, o.topic_similarity, o.created_at,
    o.llm_call_id, o.prompt_version, o.supersedes, s.label AS source_label, s.kind AS source_kind
"""

# By when the observation was made (``created_at``), which for the library's own rows is
# the order they were written; an imported archive keeps the time it was observed, so it
# sorts among its own months rather than above everything as the newest ids.
SORTS = {"new": "o.created_at DESC, o.id DESC", "signal": "o.signal DESC, o.id DESC",
         "old": "o.created_at ASC, o.id ASC"}


@dataclass(frozen=True)
class ObservationFilter:
    topic_id: int | None = None
    source_id: int | None = None
    # a kind (``beat``, ``mild_signal``, ``sharp_signal``), or ``!beat``: every kind but that
    kind: str | None = None
    min_signal: float | None = None
    text: str | None = None
    ids: tuple[int, ...] | None = None
    # only observations written after this ISO time (the "new since your last visit" view)
    since: str | None = None
    # only observations written before this ISO time (with ``since``: one week's papers)
    until: str | None = None
    # only observations from sources of this kind ("parallax": the imported archive)
    source_kind: str | None = None
    # with topic_id: archive observations matched to the topic by similarity
    # (``archive_topic_ids``, when ``parallax.topic_match`` is set), shown with its own
    topic_extra_ids: tuple[int, ...] | None = None


def _where(f: ObservationFilter) -> tuple[str, list[Any]]:
    clauses = ["NOT EXISTS (SELECT 1 FROM observations n WHERE n.supersedes = o.id)"]
    params: list[Any] = []
    if f.topic_id is not None:
        if f.topic_extra_ids:
            clauses.append("(o.source_id IN (SELECT source_id FROM topic_links WHERE "
                           f"topic_id = ?) OR o.id IN ({','.join('?' * len(f.topic_extra_ids))}))")
            params += [f.topic_id, *f.topic_extra_ids]
        else:
            clauses.append("o.source_id IN (SELECT source_id FROM topic_links WHERE "
                           "topic_id = ?)")
            params.append(f.topic_id)
    if f.source_id is not None:
        clauses.append("o.source_id = ?")
        params.append(f.source_id)
    if f.source_kind:
        clauses.append("o.source_id IN (SELECT id FROM sources WHERE kind = ?)")
        params.append(f.source_kind)
    if f.kind:
        clauses.append("o.kind != ?" if f.kind.startswith("!") else "o.kind = ?")
        params.append(f.kind.lstrip("!"))
    if f.min_signal is not None:
        clauses.append("o.signal >= ?")
        params.append(f.min_signal)
    if f.text:
        clauses.append("(o.summary LIKE ? OR o.title LIKE ? OR o.why_it_matters LIKE ?)")
        like = f"%{f.text}%"
        params += [like, like, like]
    if f.ids is not None:
        clauses.append(f"o.id IN ({','.join('?' * len(f.ids)) or 'NULL'})")
        params += list(f.ids)
    if f.since:
        clauses.append("o.created_at > ?")
        params.append(f.since)
    if f.until:
        clauses.append("o.created_at < ?")
        params.append(f.until)
    return " AND ".join(clauses), params


def find_observations(
    store: Store, f: ObservationFilter, *, sort: str = "new", limit: int = 50, offset: int = 0
) -> tuple[list[Any], int]:
    where, params = _where(f)
    counted = store.query_one(
        f"SELECT COUNT(*) AS n FROM observations o WHERE {where}", tuple(params))
    assert counted is not None                 # COUNT(*) always answers one row
    total = counted["n"]
    rows = store.query(
        f"SELECT {_OBS_COLUMNS} FROM observations o LEFT JOIN sources s ON s.id = o.source_id "
        f"WHERE {where} ORDER BY {SORTS.get(sort, SORTS['new'])} LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    return rows, int(total)


# Per store: (archive size, newest archive id) -> (ids, vectors)
_ARCHIVE_VECTORS: weakref.WeakKeyDictionary[Store, Any] = weakref.WeakKeyDictionary()


def archive_topic_ids(store: Store, topic_id: int, min_similarity: float) -> tuple[int, ...]:
    """Imported archive observations at least ``min_similarity`` like the topic (its query
    embedding against each observation's), worked out when asked: nothing is stored, so
    ``parallax.topic_match`` takes effect, and stops, at once. The archive's vectors are
    cached per process while its size and newest id stay the same."""
    if min_similarity <= 0:
        return ()
    row = store.query_one("SELECT embedding FROM topics_now WHERE id = ?", (topic_id,))
    if row is None:
        return ()
    state = store.query_one("SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m FROM observations "
                            "WHERE admitted_by = ?", (IMPORTED,))
    assert state is not None                   # COUNT(*) always answers one row
    key = (state["n"], state["m"])
    cached = _ARCHIVE_VECTORS.get(store)
    if cached is None or cached[0] != key:
        rows = store.query("SELECT id, embedding FROM observations WHERE admitted_by = ? "
                           "ORDER BY id", (IMPORTED,))
        cached = (key, np.array([r["id"] for r in rows], dtype=np.int64),
                  np.stack([blob_to_vec(r["embedding"]) for r in rows]) if rows
                  else np.zeros((0, 1), dtype=np.float32))
        _ARCHIVE_VECTORS[store] = cached
    _, ids, vectors = cached
    if not len(ids):
        return ()
    sims = vectors @ blob_to_vec(row["embedding"])
    return tuple(int(i) for i in ids[sims >= min_similarity])


def observations_by_id(store: Store, ids: list[int]) -> dict[int, object]:
    if not ids:
        return {}
    rows = store.query(
        f"SELECT {_OBS_COLUMNS} FROM observations o LEFT JOIN sources s ON s.id = o.source_id "
        f"WHERE o.id IN ({','.join('?' * len(ids))})",
        tuple(ids),
    )
    return {r["id"]: r for r in rows}


def get_observation(store: Store, observation_id: int) -> Any:
    return observations_by_id(store, [observation_id]).get(observation_id)


def recent_runs(store: Store, limit: int = 30) -> list[Any]:
    return store.query("SELECT * FROM runs ORDER BY finished_at DESC LIMIT ?", (limit,))


def llm_error_summary(store: Store, since: str) -> list[Any]:
    return store.query(
        """
        SELECT purpose, COALESCE(http_status, 0) AS http_status, COUNT(*) AS n,
               MAX(created_at) AS last_at, MAX(error) AS example
        FROM llm_calls WHERE status = 'error' AND created_at >= ?
        GROUP BY purpose, http_status ORDER BY n DESC
        """,
        (since,),
    )


def outcome_counts(store: Store, since: str) -> dict[str, int]:
    rows = store.query(
        "SELECT outcome, COUNT(*) AS n FROM items_seen WHERE created_at >= ? GROUP BY outcome",
        (since,),
    )
    return {r["outcome"]: r["n"] for r in rows}


def exploration_yield(store: Store) -> list[dict[str, Any]]:
    """How observations got past the prefilter, and what each route produced.

    Per ``admitted_by`` (``topic``, ``exploration``, ``no_topics``; imported rows
    have none): how many current observations, their mean signal, and how many
    sit in cross-source clusters of the latest map. The exploration sample
    exists to find what topic similarity misses; this is the check on whether
    it does.
    """
    snap = store.query_one("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1")
    rows = store.query(
        """
        SELECT COALESCE(o.admitted_by, 'unrecorded') AS admitted_by, COUNT(*) AS n,
               AVG(o.signal) AS mean_signal,
               SUM(CASE WHEN c.cross_source = 1 THEN 1 ELSE 0 END) AS in_cross_source
        FROM observations o
        LEFT JOIN snapshot_points p ON p.observation_id = o.id AND p.snapshot_id = ?
        LEFT JOIN clusters c ON c.snapshot_id = p.snapshot_id AND c.cluster = p.cluster
        WHERE NOT EXISTS (SELECT 1 FROM observations n WHERE n.supersedes = o.id)
        GROUP BY COALESCE(o.admitted_by, 'unrecorded')
        ORDER BY n DESC
        """,
        (snap["id"] if snap else -1,),
    )
    return [
        {"admitted_by": r["admitted_by"], "n": int(r["n"]),
         "mean_signal": float(r["mean_signal"]) if r["mean_signal"] is not None else None,
         "in_cross_source": int(r["in_cross_source"] or 0) if snap else None}
        for r in rows
    ]


# -- linked observations (``observation_links``: what a deep dive found, kept after it left) ----


def children_of(store: Store, observation_id: int) -> list[sqlite3.Row]:
    """The observations linked under this one (a deep dive's finds), oldest first."""
    return store.query(
        "SELECT l.relation, o.id, o.title, o.summary, o.signal, o.source_url "
        "FROM observation_links l JOIN observations o ON o.id = l.child_id "
        "WHERE l.parent_id = ? ORDER BY o.id", (observation_id,))


def parent_of(store: Store, observation_id: int) -> sqlite3.Row | None:
    """The observation this one is linked under, or None."""
    return store.query_one(
        "SELECT l.relation, o.id, o.title, o.summary FROM observation_links l "
        "JOIN observations o ON o.id = l.parent_id WHERE l.child_id = ?", (observation_id,))
