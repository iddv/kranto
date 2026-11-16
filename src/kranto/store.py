"""The library: one SQLite file, append-only by construction.

Every table except ``settings``, ``schema_meta`` and ``oauth_states`` (a sign-in in
progress, marked used and removed within the hour) is append-only. Triggers
reject UPDATE and DELETE, so the discipline does not depend on callers
remembering it. A changed belief is a new row that points at the old one
(``supersedes``); a changed status is a new ``status_events`` row.

Rows leave in one way only: a purge (``Store.purge``), used by compaction to
remove observations past their retention age and the raw text behind them
. The DELETE triggers of ``PURGEABLE_TABLES`` let a row go only while a
purge token row exists in ``settings``; the token is written and removed
inside the purge's own transaction, which also records every removal in
``purges``. No trigger ever allows an UPDATE.

The one exception is the full-text index over observations
(``observations_fts``): it holds no data of its own, only an index derived
from the observations table, and FTS5 must update and delete rows in its
shadow tables to maintain it. SQLite cannot put triggers on a virtual table,
and triggers on the shadow tables would break every insert, so these tables
are left out of the append-only set; the index can always be rebuilt from
the observations.

Schema changes are ordered migrations. A migration may only add tables,
columns, indexes and triggers; it never rewrites existing rows.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import numpy as np

# oauth_states (migration 18): an OAuth flow's state is marked used and removed
# within the hour; it is bookkeeping for a login in progress, not library data.
# cub_kv (migration 31): a cub's own working state, held by the host under its quota.
MUTABLE_TABLES = frozenset({"settings", "schema_meta", "sqlite_sequence", "oauth_states",
                            "search_cache", "cub_kv"})
# The tables migration 13 made purgeable. Its script is fixed: it ran on existing
# databases with exactly these, before any later table existed.
PURGEABLE_AT_MIGRATION_13 = ("observations", "snapshot_points", "llm_calls", "syntheses")
# The only tables rows ever leave, and only inside Store.purge(): expired
# observations, their map points, the model calls that hold their raw text,
# cached explanations that cite them, text signatures older than the window they
# are compared over (migration 14, #35), the links between a deep dive's
# parent and its children (migration 15, #67), and a run's marks past ``activity.keep_days``
# or ``activity.max_rows`` (migration 39), and what a browser read when the person forgets it
# or its retention age passes (migration 43).
PURGEABLE_TABLES = PURGEABLE_AT_MIGRATION_13 + ("item_signatures", "observation_links",
                                                "run_marks", "browser_captures")
PURGE_TOKEN = "purge_token"
# Tables FTS5 creates for each full-text index, as <name>_<suffix>.
FTS5_SHADOW_SUFFIXES = ("data", "idx", "content", "docsize", "config")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def month_start(dt: datetime) -> datetime:
    dt = dt.astimezone(UTC)
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def vec_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


# Migration 35's arithmetic for one card ``i``: the topics whose sources its evidence came
# from, how many of its citations each and the share of them (a source in two topics counts
# for both); the cited observation's source, else the source with the label it was cited by.
_M35_SHARES = """
    SELECT t.id, t.name, t.kind, COUNT(*) AS n,
           ROUND(CAST(COUNT(*) AS REAL) / json_array_length(i.card, '$.evidence'), 4) AS share
    FROM json_each(i.card, '$.evidence') e
    LEFT JOIN observations o ON o.id = json_extract(e.value, '$.observation_id')
    JOIN topic_sources ts ON ts.source_id = COALESCE(o.source_id, (
        SELECT s.id FROM sources s WHERE s.label = COALESCE(
            json_extract(e.value, '$.source'),
            (SELECT es.source_label FROM evidence_snapshots es
             WHERE es.idea_id = i.id
               AND es.observation_id = json_extract(e.value, '$.observation_id')
             ORDER BY es.id DESC LIMIT 1))
        ORDER BY s.id LIMIT 1))
    JOIN topics t ON t.id = ts.topic_id
    WHERE e.type = 'object'
    GROUP BY t.id
"""

# The kinds whose skipped runs are still rows: the update check's skip with an
# error is how a check that keeps failing is seen (update.check, activity's Fix rows)
SKIP_RECORDED = frozenset({"update"})


def _nothing_to_do(row: dict[str, Any]) -> bool:
    """A skipped runs row that is a scheduled job with nothing to do. Not one somebody asked
    for (a press, the CLI, the assistant: only the scheduler's own runs, ``origin`` schedule),
    not one the owner stopped part way (``stopped_by``, or an error that says so: work was done,
    the rest waits) and not a refusal (``refused``: Activity says why)."""
    if row.get("status") != "skipped" or row.get("kind") in SKIP_RECORDED:
        return False
    from . import activity  # lazy: activity imports the store

    now = activity.current()
    if now is None or now.origin != "schedule":
        return False
    if str(row.get("error") or "").startswith("stopped by"):
        return False
    summary = row.get("summary")
    try:
        got = json.loads(summary) if isinstance(summary, str) else summary
    except ValueError:
        got = None
    return not (isinstance(got, dict) and (got.get("stopped_by") or got.get("refused")))

_MIGRATIONS: list[tuple[int, str]] = [
    # 1: core library
    (1, """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        embedding BLOB NOT NULL,
        embedding_model TEXT NOT NULL,
        supersedes INTEGER REFERENCES topics(id),
        created_at TEXT NOT NULL
    );

    CREATE TABLE sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        params TEXT NOT NULL,
        label TEXT NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('manual', 'scout', 'import')),
        origin_call_id INTEGER REFERENCES llm_calls(id),
        validation TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (kind, params)
    );

    CREATE TABLE topic_sources (
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        source_id INTEGER NOT NULL REFERENCES sources(id),
        created_at TEXT NOT NULL,
        PRIMARY KEY (topic_id, source_id)
    );

    CREATE TABLE status_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL CHECK (entity IN ('topic', 'source')),
        entity_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX status_events_entity ON status_events (entity, entity_id, id);

    CREATE TABLE llm_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_uuid TEXT,
        purpose TEXT NOT NULL,
        tier TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_version TEXT NOT NULL,
        request TEXT NOT NULL,
        response TEXT,
        status TEXT NOT NULL CHECK (status IN ('ok', 'error')),
        error TEXT,
        http_status INTEGER,
        attempts INTEGER NOT NULL,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        cost_usd REAL,
        latency_ms INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE INDEX llm_calls_created ON llm_calls (created_at);
    CREATE INDEX llm_calls_run ON llm_calls (run_uuid);

    CREATE TABLE items_seen (
        source_id INTEGER NOT NULL REFERENCES sources(id),
        item_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        llm_call_id INTEGER REFERENCES llm_calls(id),
        run_uuid TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY (source_id, item_id)
    );

    CREATE TABLE observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER REFERENCES sources(id),
        item_id TEXT,
        run_uuid TEXT,
        llm_call_id INTEGER REFERENCES llm_calls(id),
        prompt_version TEXT,
        kind TEXT NOT NULL,
        title TEXT,
        summary TEXT NOT NULL,
        why_it_matters TEXT NOT NULL,
        content_quality REAL NOT NULL,
        durability REAL NOT NULL,
        opportunity REAL NOT NULL,
        signal REAL NOT NULL,
        override INTEGER NOT NULL DEFAULT 0,
        override_reason TEXT,
        tags TEXT NOT NULL DEFAULT '[]',
        source_url TEXT,
        source_excerpt TEXT,
        item_published_at TEXT,
        embedding BLOB NOT NULL,
        embedding_model TEXT NOT NULL,
        supersedes INTEGER REFERENCES observations(id),
        external_id TEXT UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE INDEX observations_created ON observations (created_at);
    CREATE INDEX observations_source ON observations (source_id);

    CREATE TABLE runs (
        run_uuid TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('ok', 'degraded', 'failed', 'skipped')),
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        summary TEXT NOT NULL,
        error TEXT
    );
    """),
    # 2: why an item reached the judge, so exploration can be evaluated later
    (2, """
    ALTER TABLE observations ADD COLUMN admitted_by TEXT;
    ALTER TABLE observations ADD COLUMN topic_similarity REAL;
    ALTER TABLE items_seen ADD COLUMN topic_similarity REAL;
    """),
    # 3: "is this row superseded" is asked on every read; without this it is quadratic
    (3, """
    CREATE INDEX observations_supersedes ON observations (supersedes);
    CREATE INDEX observations_signal ON observations (signal);
    CREATE INDEX topic_sources_source ON topic_sources (source_id);
    """),
    # 4: the map. Clusters are recomputed from scratch per snapshot; cluster ids
    # are ephemeral, lineage ids carry identity across snapshots.
    (4, """
    CREATE TABLE snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL,
        embedding_model TEXT NOT NULL,
        n INTEGER NOT NULL,
        k INTEGER NOT NULL,
        params TEXT NOT NULL,
        quality TEXT NOT NULL,
        density TEXT NOT NULL,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE snapshot_points (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        observation_id INTEGER NOT NULL REFERENCES observations(id),
        cluster INTEGER NOT NULL,
        x REAL NOT NULL,
        y REAL NOT NULL,
        PRIMARY KEY (snapshot_id, observation_id)
    );
    CREATE INDEX snapshot_points_cluster ON snapshot_points (snapshot_id, cluster);

    CREATE TABLE clusters (
        snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
        cluster INTEGER NOT NULL,
        lineage_id TEXT NOT NULL,
        size INTEGER NOT NULL,
        share REAL NOT NULL,
        centroid BLOB NOT NULL,
        centroid_2d TEXT NOT NULL,
        keywords TEXT NOT NULL,
        name TEXT,
        name_call_id INTEGER REFERENCES llm_calls(id),
        source_mix TEXT NOT NULL,
        max_source_share REAL NOT NULL,
        cross_source INTEGER NOT NULL,
        topic_mix TEXT NOT NULL,
        representatives TEXT NOT NULL,
        trajectory TEXT NOT NULL,
        PRIMARY KEY (snapshot_id, cluster)
    );
    CREATE INDEX clusters_lineage ON clusters (lineage_id);
    """),
    # 5: ideation. Explanations are cached by their exact inputs; idea cards keep
    # the evidence they cite and what verification dropped; verdicts are graded
    # by a person and never edited (the latest one counts).
    (5, """
    CREATE TABLE syntheses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cache_key TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL,
        input_ids TEXT NOT NULL,
        text TEXT NOT NULL,
        llm_call_id INTEGER REFERENCES llm_calls(id),
        created_at TEXT NOT NULL
    );

    CREATE TABLE ideas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id INTEGER REFERENCES snapshots(id),
        fingerprint TEXT NOT NULL,
        lineage_id TEXT,
        origin TEXT NOT NULL,
        evidence_key TEXT NOT NULL,
        input_ids TEXT NOT NULL,
        title TEXT NOT NULL,
        card TEXT NOT NULL,
        score REAL NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('shown', 'unsupported')),
        dropped TEXT NOT NULL,
        gen_call_id INTEGER REFERENCES llm_calls(id),
        verify_call_id INTEGER REFERENCES llm_calls(id),
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX ideas_evidence ON ideas (evidence_key);

    CREATE TABLE verdicts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL CHECK (target IN ('idea', 'observation')),
        target_id INTEGER NOT NULL,
        verdict TEXT NOT NULL CHECK (verdict IN ('useful', 'not_useful', 'wrong')),
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX verdicts_target ON verdicts (target, target_id, id);
    """),
    # 6: the channel. Messages are what reaches a person: strikes (rare, gated),
    # heartbeats (patient silence made visible) and alarms (broken silence made
    # visible). Candidates are anything that might deserve a strike; a gate
    # decides which become messages.
    (6, """
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('strike', 'heartbeat', 'alarm')),
        dedup_key TEXT NOT NULL UNIQUE,
        origin TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        links TEXT NOT NULL DEFAULT '[]',
        evidence_ids TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE INDEX messages_created ON messages (created_at);

    CREATE TABLE deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL REFERENCES messages(id),
        target TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX deliveries_message ON deliveries (message_id);

    CREATE TABLE strike_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        origin TEXT NOT NULL,
        subject_key TEXT NOT NULL,
        score REAL NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        links TEXT NOT NULL DEFAULT '[]',
        evidence_ids TEXT NOT NULL DEFAULT '[]',
        detail TEXT NOT NULL DEFAULT '{}',
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX strike_candidates_subject ON strike_candidates (subject_key, created_at);
    """),
    # 8: watches. A saved question, embedded once as a query, checked against
    # every new observation at ingest. Status lives in watch_events because the
    # CHECK on status_events.entity only admits 'topic' and 'source', and a
    # migration may not rebuild an existing table to widen it.
    (8, """
    CREATE TABLE watches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL,
        embedding BLOB NOT NULL,
        embedding_model TEXT NOT NULL,
        min_similarity REAL NOT NULL,
        min_signal REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE watch_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        watch_id INTEGER NOT NULL REFERENCES watches(id),
        status TEXT NOT NULL CHECK (status IN ('active', 'retired')),
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX watch_events_watch ON watch_events (watch_id, id);
    """),
    # 10: strikes. The gate decides each candidate exactly once and records why
    # (UNIQUE candidate_id); a person grades messages, observations, clusters and
    # ideas, and the latest grade on a target counts. Cluster grades name the
    # lineage, which outlives the snapshot, so target_id is text.
    (10, """
    CREATE TABLE strike_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL UNIQUE REFERENCES strike_candidates(id),
        promoted INTEGER NOT NULL CHECK (promoted IN (0, 1)),
        reason TEXT NOT NULL CHECK (reason IN ('promoted', 'below_threshold', 'no_threshold',
                                               'warmup', 'refractory', 'weekly_cap', 'stale')),
        threshold REAL,
        detail TEXT NOT NULL,
        message_id INTEGER REFERENCES messages(id),
        created_at TEXT NOT NULL
    );
    CREATE INDEX strike_decisions_created ON strike_decisions (created_at);

    CREATE TABLE grades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL CHECK (target IN ('message', 'observation', 'cluster', 'idea')),
        target_id TEXT NOT NULL,
        grade TEXT NOT NULL CHECK (grade IN ('worth_waking', 'not_worth_it', 'missed',
                                             'useful', 'not_useful', 'wrong')),
        note TEXT,
        context TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX grades_target ON grades (target, target_id, id);
    """),
    # 11: the URL an item is about. Items were deduplicated per source and
    # item id only, so a resubmitted link, or one article reached through two
    # sources, was judged and stored again. Earlier rows have NULL.
    (11, """
    ALTER TABLE items_seen ADD COLUMN canonical_url TEXT;
    CREATE INDEX items_seen_canonical ON items_seen (canonical_url);
    """),
    # 12: full-text index over observations for lexical search, fused with
    # the embedding rank. External content: the index stores no copy of the
    # text, only postings for rows of observations. Filled from existing rows
    # here, and kept in step by a trigger on every insert. Observations are
    # never updated or deleted, so no other trigger is needed.
    (12, """
    CREATE VIRTUAL TABLE observations_fts USING fts5(
        title, summary, why_it_matters, tags,
        content='observations', content_rowid='id', tokenize='porter unicode61'
    );
    INSERT INTO observations_fts (rowid, title, summary, why_it_matters, tags)
        SELECT id, title, summary, why_it_matters, tags FROM observations;
    CREATE TRIGGER observations_fts_insert AFTER INSERT ON observations BEGIN
        INSERT INTO observations_fts (rowid, title, summary, why_it_matters, tags)
        VALUES (new.id, new.title, new.summary, new.why_it_matters, new.tags);
    END;
    """),
    # 13: retention and compaction. An observation past its retention age is
    # clustered with the others of its week into rollups, then removed with the
    # raw text behind it. Deletion is a recorded act: the DELETE triggers of the
    # purgeable tables let a row go only while a purge token exists in settings,
    # which only Store.purge() writes, inside the transaction that also records
    # each removal in purges. UPDATE stays forbidden on every library table.
    (13, """
    CREATE TABLE rollups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        first_at TEXT NOT NULL,
        last_at TEXT NOT NULL,
        size INTEGER NOT NULL,
        source_mix TEXT NOT NULL,
        platform_mix TEXT NOT NULL,
        topic_mix TEXT NOT NULL,
        mean_signal REAL NOT NULL,
        kind_counts TEXT NOT NULL,
        keywords TEXT NOT NULL,
        name TEXT,
        summary TEXT,
        summary_call_id INTEGER REFERENCES llm_calls(id),
        urls TEXT NOT NULL,
        centroid BLOB NOT NULL,
        embedding_model TEXT NOT NULL,
        replaced_count INTEGER NOT NULL,
        replaced_fingerprint TEXT NOT NULL,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX rollups_period ON rollups (period_start);
    CREATE VIRTUAL TABLE rollups_fts USING fts5(
        name, summary, keywords,
        content='rollups', content_rowid='id', tokenize='porter unicode61'
    );
    CREATE TRIGGER rollups_fts_insert AFTER INSERT ON rollups BEGIN
        INSERT INTO rollups_fts (rowid, name, summary, keywords)
        VALUES (new.id, new.name, new.summary, new.keywords);
    END;

    CREATE TABLE purges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_uuid TEXT,
        table_name TEXT NOT NULL,
        row_count INTEGER NOT NULL,
        reason TEXT NOT NULL,
        rollup_ids TEXT NOT NULL DEFAULT '[]',
        detail TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX purges_table ON purges (table_name, created_at);

    CREATE TABLE source_retention (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        days REAL,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX source_retention_source ON source_retention (source_id, id);

    CREATE TABLE evidence_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL REFERENCES ideas(id),
        observation_id INTEGER NOT NULL,
        source_label TEXT,
        observed_at TEXT,
        summary TEXT NOT NULL,
        url TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX evidence_snapshots_idea ON evidence_snapshots (idea_id);

    CREATE TRIGGER observations_fts_delete AFTER DELETE ON observations BEGIN
        INSERT INTO observations_fts (observations_fts, rowid, title, summary, why_it_matters,
                                      tags)
        VALUES ('delete', old.id, old.title, old.summary, old.why_it_matters, old.tags);
    END;
    """ + "".join(f"""
    DROP TRIGGER IF EXISTS {table}_no_delete;
    CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
    WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = '{PURGE_TOKEN}')
    BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;
    """ for table in PURGEABLE_AT_MIGRATION_13)),
    # 14: stories and origins. An item's own text, before the judge sees it,
    # is kept as a MinHash signature (hash values, no text) for the window it is
    # compared over, then purged with a record. A story link says an item is the
    # same text as an earlier one, and names the story's root (its earliest
    # member); links hold ids only and stay, like items_seen. Clusters gain the
    # number of distinct stories they hold and the mix of origins (registrable
    # domains) those stories come from.
    (14, f"""
    CREATE TABLE item_signatures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        item_id TEXT NOT NULL,
        method TEXT NOT NULL,
        signature BLOB NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (source_id, item_id)
    );
    CREATE INDEX item_signatures_created ON item_signatures (created_at);
    CREATE TRIGGER item_signatures_no_delete BEFORE DELETE ON item_signatures
    WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = '{PURGE_TOKEN}')
    BEGIN SELECT RAISE(ABORT, 'item_signatures is append-only'); END;

    CREATE TABLE story_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        item_id TEXT NOT NULL,
        matched_source_id INTEGER NOT NULL REFERENCES sources(id),
        matched_item_id TEXT NOT NULL,
        root_source_id INTEGER NOT NULL REFERENCES sources(id),
        root_item_id TEXT NOT NULL,
        similarity REAL NOT NULL,
        judged INTEGER NOT NULL CHECK (judged IN (0, 1)),
        run_uuid TEXT,
        created_at TEXT NOT NULL,
        UNIQUE (source_id, item_id)
    );
    CREATE INDEX story_links_root ON story_links (root_source_id, root_item_id);

    ALTER TABLE clusters ADD COLUMN stories INTEGER;
    ALTER TABLE clusters ADD COLUMN origin_mix TEXT;
    ALTER TABLE clusters ADD COLUMN max_origin_share REAL;
    """),
    # 15: deep dives. An observation that scores high is queued (deep_dives);
    # a separate job gathers its discussion, the links it and its comments point
    # at, and the repositories it names, and judges each as an item of its own.
    # What is kept becomes an ordinary observation, linked to its parent by a row
    # in observation_links, never by editing either. A dive's progress is events
    # (deep_dive_events; the latest terminal one counts). Links are removed with
    # either end, inside a recorded purge.
    (15, f"""
    CREATE TABLE deep_dives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
        reason TEXT NOT NULL CHECK (reason IN ('signal', 'operator')),
        signal REAL,
        note TEXT,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE deep_dive_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deep_dive_id INTEGER NOT NULL REFERENCES deep_dives(id),
        status TEXT NOT NULL CHECK (status IN ('done', 'dropped', 'failed', 'retry')),
        detail TEXT NOT NULL DEFAULT '{{}}',
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX deep_dive_events_dive ON deep_dive_events (deep_dive_id, id);

    CREATE TABLE observation_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER NOT NULL REFERENCES observations(id),
        child_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
        relation TEXT NOT NULL CHECK (relation IN ('discussion', 'link', 'repository')),
        deep_dive_id INTEGER REFERENCES deep_dives(id),
        created_at TEXT NOT NULL
    );
    CREATE INDEX observation_links_parent ON observation_links (parent_id);

    CREATE TRIGGER observation_links_no_delete BEFORE DELETE ON observation_links
    WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = '{PURGE_TOKEN}')
    BEGIN SELECT RAISE(ABORT, 'observation_links is append-only'); END;
    """),
    # 16: look before judging. An item is screened by a short tier-1 call
    # before it is gathered for and judged. The screen's call is recorded on the
    # item's items_seen row, whatever the item's outcome, so it expires with the
    # item at its source's retention age (it holds the item's text). For an item
    # the screen dropped (outcome 'screened_out') it is also the llm_call_id.
    (16, """
    ALTER TABLE items_seen ADD COLUMN screen_call_id INTEGER REFERENCES llm_calls(id);
    """),
    # 17: source health. One row per source per ingest run, and
    # one per "Fetch now", so a source's status, last fetch and recent fetches are a
    # query instead of parsing runs.summary. ``state`` is what the row shows: ok,
    # paced (a rate limit or another transient refusal), failing, needs_login (the
    # connected account is missing or was refused). The error text is scrubbed.
    (17, """
    CREATE TABLE source_fetches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        run_uuid TEXT,
        trigger TEXT NOT NULL CHECK (trigger IN ('run', 'manual')),
        state TEXT NOT NULL CHECK (state IN ('ok', 'paced', 'failing', 'needs_login')),
        fetched INTEGER NOT NULL,
        new INTEGER NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX source_fetches_source ON source_fetches (source_id, id);
    """),
    # 18: connected accounts (section 3). The library holds who and
    # what (provider, instance, account label, read-only scopes) and what happened
    # (connection_events), never a secret: tokens and client secrets are encrypted in
    # data/secrets/ (connections.vault), so an export or a bundle stays safe.
    # oauth_states is short-lived and mutable (a state is marked used, and rows
    # older than an hour are removed); it holds a hash of the state, never the state
    # or the PKCE verifier, which are in the vault.
    (18, """
    CREATE TABLE connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        instance TEXT NOT NULL,
        account TEXT NOT NULL,
        scopes TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE connection_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        connection_id INTEGER NOT NULL REFERENCES connections(id),
        event TEXT NOT NULL CHECK (event IN ('connected', 'tested', 'needs_login',
                                             'disconnected')),
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX connection_events_connection ON connection_events (connection_id, id);
    CREATE TABLE oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        instance TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        created_at TEXT NOT NULL,
        used_at TEXT
    );
    """),
    # 19: feedback (LEARNING.md 2.4, track L1). The owner's grades, pairs and confirmed
    # actions on anything Kranto surface, from the app, the review queue and chat, in
    # one append-only table: the latest grade row on a target counts, and a cleared grade
    # is a new row with value 'skip'. No CHECK on target or value: feedback.py validates
    # against its vocabulary, so a new maker or target needs no migration. ``grades`` is
    # untouched; grades.latest and grades.history read both.
    (19, """
    CREATE TABLE feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT NOT NULL,
        reasons TEXT NOT NULL DEFAULT '[]',
        pair TEXT,
        note TEXT,
        origin TEXT NOT NULL,
        context TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX feedback_target ON feedback (target, target_id, id);
    CREATE INDEX feedback_created ON feedback (created_at);
    """),
    # 20: mute a source from Kranto UI (UI-v4.md 2.3, "mute…"). Append-only like
    # source_retention: the latest row per source wins. ``muted_until`` set: the source
    # is not fetched until then; ``read_less`` 1: it is read at half its items per run.
    # A row with neither is "back to normal", so an undo is one more row.
    (20, """
    CREATE TABLE source_mutes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL REFERENCES sources(id),
        muted_until TEXT,
        read_less INTEGER NOT NULL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX source_mutes_source ON source_mutes (source_id, id);
    """),
    # 21: polite fetching (sources.pacing). A paced fetch (a 429 or 503, a timeout)
    # records when the host may be asked again: the source is deferred until then,
    # and its row says "paced, retrying at ...". Null on every other fetch.
    (21, """
    ALTER TABLE source_fetches ADD COLUMN retry_at TEXT;
    """),
    # 22: themes of an imported archive (importers.import_parallax_themes). One row per
    # lineage of the archive's own clustering, as of one bundle (``bundle``: its
    # generation time and substrate fingerprint); importing a newer bundle adds rows, and
    # the latest row per (archive, lineage_id) is the theme. ``history`` is the lineage's
    # size per epoch, ``names`` every name it was given. Members are the imported
    # observations in the theme's cluster in that bundle, by observation id: no foreign
    # key, so retention can still remove an observation, and a member that is gone is
    # simply not found.
    (22, """
    CREATE TABLE archive_themes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        archive TEXT NOT NULL,
        lineage_id TEXT NOT NULL,
        bundle TEXT NOT NULL,
        name TEXT,
        names TEXT NOT NULL DEFAULT '[]',
        keywords TEXT NOT NULL DEFAULT '[]',
        alive INTEGER NOT NULL CHECK (alive IN (0, 1)),
        size INTEGER NOT NULL,
        first_at TEXT NOT NULL,
        last_at TEXT NOT NULL,
        epochs INTEGER NOT NULL,
        history TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (archive, lineage_id, bundle)
    );
    CREATE INDEX archive_themes_lineage ON archive_themes (archive, lineage_id, id);
    CREATE TABLE archive_theme_members (
        theme_id INTEGER NOT NULL REFERENCES archive_themes(id),
        observation_id INTEGER NOT NULL,
        PRIMARY KEY (theme_id, observation_id)
    );
    CREATE INDEX archive_theme_members_observation ON archive_theme_members (observation_id);
    """),
    # 23: project topics (the page's PJ plan). ``kind`` is ``user`` (the owner's own
    # topics, every row before this) or ``project`` (a topic the page created for one of
    # its projects through the JSON API); ``ref`` is the caller's key for it
    # (``project:<id>``), null for user topics. Set at insert, never updated; an edited
    # topic's new row carries both on.
    (23, """
    ALTER TABLE topics ADD COLUMN kind TEXT NOT NULL DEFAULT 'user';
    ALTER TABLE topics ADD COLUMN ref TEXT;
    CREATE INDEX topics_ref ON topics (ref);
    """),
    # 24: outcomes (PLAN 4.7): what happened to an idea card after it was written, one row
    # per step that decided (the weekly editor's class first), written by the page through
    # POST /api/ideas/{id}/outcome. Append-only like every library table (outcomes.py).
    (24, """
    CREATE TABLE outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        value TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX outcomes_idea ON outcomes (idea_id, kind, id);
    """),
    # 25: model providers: which provider served a call, the prompt tokens
    # read from and written to the provider's cache (``prompt_tokens`` stays the whole
    # prompt), and what a plan-billed call would have cost at list prices (its ``cost_usd``
    # is 0, so the dollar budget counts dollars only). Null on every row from before.
    (25, """
    ALTER TABLE llm_calls ADD COLUMN provider TEXT;
    ALTER TABLE llm_calls ADD COLUMN cache_read_tokens INTEGER;
    ALTER TABLE llm_calls ADD COLUMN cache_write_tokens INTEGER;
    ALTER TABLE llm_calls ADD COLUMN equiv_usd REAL;
    """),
    # 26: what a paid API other than a model costs: one row per request that
    # returned resources, X's reads first. ``kind`` is the price line (``post_read``,
    # ``owned_read``, ``user_read``, ``list_read``, ``xai_post``), ``count`` the resources the
    # reply held, ``usd`` that at list price (``pricing.X_PRICES``). Kranto cannot see a
    # provider's same-day deduplication, so the sum is an estimate from above. ``source_id``
    # and ``run_uuid`` are null for a request no source or run made (a preview, a Test).
    # Append-only; never purged: ids and counts only, no text.
    (26, """
    CREATE TABLE api_spend (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        source_id INTEGER,
        run_uuid TEXT,
        kind TEXT NOT NULL,
        count INTEGER NOT NULL,
        usd REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX api_spend_provider ON api_spend (provider, created_at);
    CREATE INDEX api_spend_source ON api_spend (source_id, created_at);
    """),
    # 27: live web search: the day cache, one row per backend, query and day,
    # holding titles, links, dates and snippets only (never page bodies). Mutable like
    # ``oauth_states``: rows older than ``search.cache_hours`` are removed when a search writes.
    # ``api_spend.caller`` names which caller (the scout, cards, the editor...) made a search.
    (27, """
    CREATE TABLE search_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        backend TEXT NOT NULL,
        kind TEXT NOT NULL,
        recency TEXT NOT NULL DEFAULT '',
        query_hash TEXT NOT NULL,
        day TEXT NOT NULL,
        results_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX search_cache_key ON search_cache (backend, query_hash, recency, day);
    ALTER TABLE api_spend ADD COLUMN caller TEXT;
    """),
    # 28: News (the first feature on the core: ``features/news``). Both
    # append-only. ``news_topics``: the owner's News setting per topic, the newest row counting
    # (off until a row turns it on). ``news_briefs``: one row per brief, never edited: a re-run
    # is a new row; ``items`` are the checked items with their citations (observation ids,
    # dated result URLs), ``checks`` what the code dropped or rewrote, ``search`` the live
    # search's backend, time and the results cited.
    (28, """
    CREATE TABLE news_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        enabled INTEGER NOT NULL,
        cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekdays', 'weekly')),
        hour INTEGER NOT NULL,
        weekday INTEGER,
        origin TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX news_topics_topic ON news_topics (topic_id, id);
    CREATE TABLE news_briefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        run_uuid TEXT,
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('ok', 'quiet', 'failed')),
        items TEXT NOT NULL DEFAULT '[]',
        quiet TEXT,
        search TEXT,
        error TEXT,
        llm_call_id INTEGER,
        prompt_version TEXT,
        model TEXT,
        cost_usd REAL,
        equiv_usd REAL,
        checks TEXT NOT NULL DEFAULT '{}',
        previous_id INTEGER REFERENCES news_briefs(id),
        trigger TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX news_briefs_topic ON news_briefs (topic_id, id);
    """),
    # 29: Invest, paper mode (``features/invest``). All append-only.
    # ``invest_proposals``: one row per proposal as it was made (the thesis, the instrument as
    # resolved, the quote, the position, the order code built, the checks, the verdict:
    # proposed, journal, watch or not_investable); a refresh is a new row. ``invest_events``:
    # the audit log (every check, press, refresh, dismissal). ``invest_outcomes``: the price
    # and SPY's at the proposal and at 1 day, 7 days and the horizon. Orders are core.money's
    # (``money_orders``, migration 30).
    (29, """
    CREATE TABLE invest_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER,
        brief_id INTEGER,
        thesis TEXT NOT NULL,
        instrument TEXT,
        candidates TEXT,
        quote TEXT,
        position TEXT,
        order_json TEXT,
        checks TEXT,
        verdict TEXT NOT NULL CHECK (verdict IN ('proposed', 'journal', 'watch',
                                                 'not_investable')),
        reason TEXT,
        mode TEXT NOT NULL,
        cites TEXT NOT NULL DEFAULT '[]',
        expires_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE invest_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER REFERENCES invest_proposals(id),
        kind TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{}',
        door TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_events_proposal ON invest_events (proposal_id, id);
    CREATE TABLE invest_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER NOT NULL REFERENCES invest_proposals(id),
        at TEXT NOT NULL,
        price REAL,
        spy REAL,
        created_at TEXT NOT NULL
    );
    """),
    # 30: the feature core (MR-RESEARCH), all append-only. ``events``:
    # the bus, one row per fact a feature or the core published, with the publisher's ``trust``
    # and a payload of ids and small facts, never a document. ``event_cursors``: how
    # far each subscriber has read a kind (the newest row per feature and kind counts).
    # ``mod_pins``: each feature's manifest hash as it was first seen at a version.
    # ``mod_requests``: a request ticket for one of the core's high-trust actions, with its
    # typed fields and its provenance (``because``: event and observation ids); its states are
    # rows of ``mod_request_states``, the newest counting. ``mod_calls``: every call the core's
    # broker made for a feature: the audit and the rate limiter's source.
    # ``broker_pins``: a broker tool's schema hash as the owner approved it.
    # ``money_orders``: core.money's order states, one row per step. Numbers 28 and
    # 29 are News's and Invest's.
    (30, """
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,
        feature TEXT NOT NULL,
        trust TEXT NOT NULL,
        subject_kind TEXT,
        subject_id TEXT,
        payload TEXT NOT NULL DEFAULT '{}',
        run_uuid TEXT,
        origin TEXT
    );
    CREATE INDEX events_kind ON events (kind, id);
    CREATE TABLE event_cursors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature TEXT NOT NULL,
        kind TEXT NOT NULL,
        last_id INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX event_cursors_key ON event_cursors (feature, kind, id);
    CREATE TABLE mod_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature TEXT NOT NULL,
        version TEXT NOT NULL,
        trust TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX mod_pins_feature ON mod_pins (feature, id);
    CREATE TABLE mod_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature TEXT NOT NULL,
        kind TEXT NOT NULL,
        trust TEXT NOT NULL,
        subject_kind TEXT,
        subject_id TEXT,
        fields TEXT NOT NULL,
        fields_hash TEXT NOT NULL,
        because TEXT NOT NULL DEFAULT '{}',
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX mod_requests_kind ON mod_requests (kind, fields_hash);
    CREATE TABLE mod_request_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL REFERENCES mod_requests(id),
        state TEXT NOT NULL,
        door TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX mod_request_states_request ON mod_request_states (request_id, id);
    CREATE TABLE mod_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        feature TEXT NOT NULL,
        service TEXT NOT NULL,
        op TEXT NOT NULL,
        status TEXT NOT NULL,
        request_id INTEGER,
        ms INTEGER,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX mod_calls_service ON mod_calls (service, created_at);
    CREATE TABLE broker_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        tool TEXT NOT NULL,
        schema_hash TEXT NOT NULL,
        origin TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE money_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL REFERENCES mod_requests(id),
        client_ref TEXT NOT NULL,
        state TEXT NOT NULL,
        mode TEXT NOT NULL,
        account TEXT,
        notional_usd REAL,
        order_json TEXT NOT NULL DEFAULT '{}',
        broker_ref TEXT,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX money_orders_ref ON money_orders (client_ref, id);
    """),
    # 31: the cub runtime (the rename of). ``cubs``: the registry of
    # installed cubs, one row per state change (the newest per cub counts). ``cub_installs``:
    # every step of an install, update or removal. ``cub_pins``, ``cub_tickets``,
    # ``cub_ticket_states``, ``cub_calls`` and ``cub_orders`` replace migration 30's
    # ``mod_pins``, ``mod_requests``, ``mod_request_states``, ``mod_calls`` and
    # ``money_orders``: each old table's rows are copied with their ids, so every id a page or
    # a log line carries still names the same row; the old tables stay, frozen (no code reads
    # or writes them after this). ``cub_kv``: a cub's own key-value store, held by the host
    # under a quota (mutable, ``MUTABLE_TABLES``). ``cub_drafts``: drafts a broker adapter
    # holds for a cub. ``cub_dedupe``: ``events.publish``'s dedupe keys.
    (31, """
    CREATE TABLE cubs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('installed', 'paused', 'removed')),
        version TEXT NOT NULL,
        trust TEXT NOT NULL,
        source_kind TEXT NOT NULL CHECK (source_kind IN ('folder', 'git', 'index', 'generated')),
        source TEXT NOT NULL DEFAULT '{}',
        sha TEXT,
        tree_hash TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        grants TEXT NOT NULL DEFAULT '{}',
        bears_range TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cubs_cub ON cubs (cub, id);
    CREATE TABLE cub_installs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        cub TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('add', 'update', 'remove')),
        step TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_installs_job ON cub_installs (job_id, id);
    CREATE TABLE cub_pins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        version TEXT NOT NULL,
        trust TEXT NOT NULL,
        manifest_hash TEXT NOT NULL,
        tree_hash TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_pins_cub ON cub_pins (cub, id);
    INSERT INTO cub_pins (id, cub, version, trust, manifest_hash, tree_hash, created_at)
        SELECT id, feature, version, trust, manifest_hash, NULL, created_at FROM mod_pins;
    CREATE TABLE cub_tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        kind TEXT NOT NULL,
        trust TEXT NOT NULL,
        subject_kind TEXT,
        subject_id TEXT,
        fields TEXT NOT NULL,
        fields_hash TEXT NOT NULL,
        because TEXT NOT NULL DEFAULT '{}',
        run_uuid TEXT,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_tickets_kind ON cub_tickets (kind, fields_hash);
    CREATE INDEX cub_tickets_cub ON cub_tickets (cub, id);
    INSERT INTO cub_tickets (id, cub, kind, trust, subject_kind, subject_id, fields, fields_hash,
                             because, run_uuid, expires_at, created_at)
        SELECT id, feature, kind, trust, subject_kind, subject_id, fields, fields_hash, because,
               NULL, expires_at, created_at FROM mod_requests;
    CREATE TABLE cub_ticket_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL REFERENCES cub_tickets(id),
        state TEXT NOT NULL CHECK (state IN ('needs_confirm', 'confirmed', 'done', 'dry',
                                             'declined', 'expired', 'refused', 'unknown')),
        door TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_ticket_states_ticket ON cub_ticket_states (ticket_id, id);
    INSERT INTO cub_ticket_states (id, ticket_id, state, door, note, created_at)
        SELECT id, request_id, state, door, note, created_at FROM mod_request_states;
    CREATE TABLE cub_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        service TEXT NOT NULL,
        op TEXT NOT NULL,
        status TEXT NOT NULL,
        ticket_id INTEGER,
        run_uuid TEXT,
        ms INTEGER,
        bytes_in INTEGER,
        bytes_out INTEGER,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_calls_cub ON cub_calls (cub, created_at);
    CREATE INDEX cub_calls_service ON cub_calls (service, created_at);
    INSERT INTO cub_calls (id, cub, service, op, status, ticket_id, run_uuid, ms, bytes_in,
                           bytes_out, detail, created_at)
        SELECT id, feature, service, op, status, request_id, NULL, ms, NULL, NULL, detail,
               created_at FROM mod_calls;
    CREATE TABLE cub_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL REFERENCES cub_tickets(id),
        client_ref TEXT NOT NULL,
        state TEXT NOT NULL,
        mode TEXT NOT NULL,
        account TEXT,
        notional_usd REAL,
        order_json TEXT NOT NULL DEFAULT '{}',
        broker_ref TEXT,
        detail TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_orders_ref ON cub_orders (client_ref, id);
    INSERT INTO cub_orders (id, ticket_id, client_ref, state, mode, account, notional_usd,
                            order_json, broker_ref, detail, created_at)
        SELECT id, request_id, client_ref, state, mode, account, notional_usd, order_json,
               broker_ref, detail, created_at FROM money_orders;
    CREATE TABLE cub_kv (
        cub TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (cub, key)
    );
    CREATE TABLE cub_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        service TEXT NOT NULL,
        ref TEXT NOT NULL UNIQUE,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        external_id TEXT,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX cub_drafts_cub ON cub_drafts (cub, id);
    CREATE TABLE cub_dedupe (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cub TEXT NOT NULL,
        key TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (cub, key)
    );
    """),
    # 32: the trend radar, all append-only. ``radar_trends``: a
    # trend's definition, one row per version (the newest per ``key`` counts; a dismissal is a
    # row with state 'dismissed'), from the owner, the model or the backtest. ``radar_series``:
    # one value of one timestamped series for one month, with where it came from and when it
    # was fetched (a later fetch of the same month is a new row; a read as of a time takes the
    # newest fetched by then). ``radar_stages``: each run's reading of a trend at its last
    # complete month (the scores and the stage), for the page and the ledger. ``radar_chains``:
    # the analyst's beneficiary chain for a trend: its links, candidates and falsifiers
    # as validated, the code's checks of every candidate, the material it cited, the prompt's
    # version and the model call; a newer chain is a new row.
    (32, """
    CREATE TABLE radar_trends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        title TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('secular', 'cyclical')),
        terms TEXT NOT NULL DEFAULT '{}',
        chain_from TEXT,
        pricing TEXT,
        instruments TEXT NOT NULL DEFAULT '[]',
        benchmark TEXT,
        origin TEXT NOT NULL CHECK (origin IN ('owner', 'model', 'backtest')),
        state TEXT NOT NULL CHECK (state IN ('active', 'dismissed')),
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX radar_trends_key ON radar_trends (key, id);
    CREATE TABLE radar_series (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trend_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        month TEXT NOT NULL,
        value REAL,
        source TEXT NOT NULL,
        detail TEXT,
        fetched_at TEXT NOT NULL
    );
    CREATE INDEX radar_series_key ON radar_series (trend_key, kind, month, id);
    CREATE TABLE radar_stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trend_key TEXT NOT NULL,
        month TEXT NOT NULL,
        stage TEXT NOT NULL,
        scores TEXT NOT NULL DEFAULT '{}',
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX radar_stages_key ON radar_stages (trend_key, id);
    CREATE TABLE radar_chains (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trend_key TEXT NOT NULL,
        chain TEXT NOT NULL,
        checks TEXT NOT NULL DEFAULT '{}',
        falsifiers TEXT NOT NULL DEFAULT '[]',
        material TEXT NOT NULL DEFAULT '{}',
        report TEXT NOT NULL DEFAULT '{}',
        prompt_version TEXT,
        llm_call_id INTEGER,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX radar_chains_key ON radar_chains (trend_key, id);
    """),
    # 33: the radar's call ledger, append-only and hash-chained.
    # ``radar_calls``: a trend's recorded stage change (live), or an entry of the backtest's
    # rules (backtest: never a live call), with every number that produced it, the evidence,
    # the chain and the instruments as they stood, the falsifiers, and the prompt's and the
    # code's versions. ``radar_scores``: a call's score at +3, +6 or +12 months; a score never
    # edits a call. Both carry ``seq`` (one sequence across the two) and ``row_hash`` =
    # sha256(``prev_hash`` + the row's canonical JSON), so a rewritten or removed row breaks
    # every hash after it; the head is published in the run's summary and ``/radar.xml``.
    (33, """
    CREATE TABLE radar_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seq INTEGER NOT NULL UNIQUE,
        call_id TEXT NOT NULL UNIQUE,
        trend_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('live', 'backtest')),
        rule TEXT NOT NULL,
        month TEXT NOT NULL,
        stage_from TEXT,
        stage_to TEXT NOT NULL,
        dismissed INTEGER NOT NULL DEFAULT 0,
        body TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL,
        made_at TEXT NOT NULL
    );
    CREATE INDEX radar_calls_trend ON radar_calls (trend_key, id);
    CREATE TABLE radar_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seq INTEGER NOT NULL UNIQUE,
        call_id TEXT NOT NULL,
        horizon INTEGER NOT NULL CHECK (horizon IN (3, 6, 12)),
        body TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL,
        scored_at TEXT NOT NULL,
        UNIQUE (call_id, horizon)
    );
    """),
    # 34: the radar watches the owner's topics. ``radar_topics``: the owner's "watch for
    # trends" switch per topic, the newest row counting (``origin`` ``owner``), and the
    # proposer's asks (``origin`` ``asked``, the switch carried over), so a topic is asked at
    # most once a run and only when it kept something new. ``radar_proposals``: a trend the
    # proposer found in a topic's kept evidence, with its why, its source terms and the
    # observations it cites; the newest row of a key counts (proposed, followed, dismissed), so
    # a dismissal is remembered and a followed trend is not proposed again. ``radar_trends``
    # gains the topic a trend came from.
    (34, """
    CREATE TABLE radar_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        watch INTEGER NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('owner', 'asked')),
        created_at TEXT NOT NULL
    );
    CREATE INDEX radar_topics_topic ON radar_topics (topic_id, id);
    CREATE TABLE radar_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        title TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('secular', 'cyclical')),
        why TEXT NOT NULL,
        terms TEXT NOT NULL DEFAULT '{}',
        cites TEXT NOT NULL DEFAULT '[]',
        state TEXT NOT NULL CHECK (state IN ('proposed', 'followed', 'dismissed')),
        note TEXT,
        trend_key TEXT,
        llm_call_id INTEGER,
        prompt_version TEXT,
        run_uuid TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX radar_proposals_key ON radar_proposals (key, id);
    CREATE INDEX radar_proposals_topic ON radar_proposals (topic_id, id);
    ALTER TABLE radar_trends ADD COLUMN topic_id INTEGER;
    """),
    # 35: a card knows its topic and its citations, each as a child of the card
    # (one parent per row; an observation and a topic hold no card id: no join table).
    # ``idea_topics``: one row per card, written at its insert from the evidence it chose
    # (``ideate/cards.topic_fields``): ``topic_id`` the user topic with the largest share of
    # its evidence (NULL when none: a dispatch card's archive evidence), ``shares`` the list
    # the card's row shows (``[{id, name, kind, n, share}]``, user topics first); the newest
    # row of a card counts. ``idea_citations``: one row per citation, indexed by the
    # observation, so "which cards cite this" is one lookup. For the cards that exist, both are
    # filled here from the cards' own JSON and ``topic_sources`` (the arithmetic /api/ideas did
    # at every read, by source id; by the cited label when the observation was compacted).
    # CON's stricter shape: ``ideas`` gets no column, so no row is rewritten.
    (35, """
    CREATE TABLE idea_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL REFERENCES ideas(id),
        topic_id INTEGER REFERENCES topics(id),
        shares TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE INDEX idea_topics_idea ON idea_topics (idea_id, id);
    CREATE INDEX idea_topics_topic ON idea_topics (topic_id, idea_id);
    CREATE TABLE idea_citations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL REFERENCES ideas(id),
        observation_id INTEGER NOT NULL,
        n INTEGER,
        role TEXT NOT NULL CHECK (role IN ('evidence', 'demand')),
        created_at TEXT NOT NULL
    );
    CREATE INDEX idea_citations_obs ON idea_citations (observation_id, idea_id);
    CREATE INDEX idea_citations_idea ON idea_citations (idea_id, id);
    INSERT INTO idea_citations (idea_id, observation_id, n, role, created_at)
        SELECT i.id, json_extract(e.value, '$.observation_id'), json_extract(e.value, '$.n'),
               'evidence', i.created_at
        FROM ideas i, json_each(i.card, '$.evidence') e
        WHERE e.type = 'object' AND json_type(e.value, '$.observation_id') = 'integer'
        ORDER BY i.id, e.key;
    INSERT INTO idea_citations (idea_id, observation_id, n, role, created_at)
        SELECT i.id, json_extract(e.value, '$.observation_id'), json_extract(e.value, '$.n'),
               'demand', i.created_at
        FROM ideas i, json_each(i.card, '$.demand.evidence') e
        WHERE json_type(i.card, '$.demand') = 'object' AND e.type = 'object'
          AND json_type(e.value, '$.observation_id') = 'integer'
        ORDER BY i.id, e.key;
    INSERT INTO idea_topics (idea_id, topic_id, shares, created_at)
        SELECT i.id,
               (SELECT x.id FROM (""" + _M35_SHARES + """) x WHERE x.kind = 'user'
                ORDER BY x.share DESC, x.name LIMIT 1),
               COALESCE((SELECT json_group_array(json_object('id', x.id, 'name', x.name,
                                                             'kind', x.kind, 'n', x.n,
                                                             'share', x.share))
                         FROM (SELECT * FROM (""" + _M35_SHARES + """)
                               ORDER BY kind != 'user', share DESC, name) x), '[]'),
               i.created_at
        FROM ideas i ORDER BY i.id;
    """),
    # 36: a build's grade names its card: the UI writes ``context.card`` (the
    # the server card the build came from) and ``context.idea`` (the loop's idea) on every grade
    # of a build; this expression index makes "the grade of this card's build" one lookup.
    (36, """
    CREATE INDEX feedback_card ON feedback (json_extract(context, '$.card'));
    """),
    # 37: a watch has a topic: the topic it was asked under (Watch this... from a
    # topic's evidence or theme), NULL for the whole library as every watch before it. It files
    # the watch under the topic; the match stays library-wide (whether a watch should match its
    # topic's sources only is the owner's decision, D-6).
    (37, """
    ALTER TABLE watches ADD COLUMN topic_id INTEGER REFERENCES topics(id);
    CREATE INDEX watches_topic ON watches (topic_id, id);
    """),
    # 38: the owner edits a topic. A topic keeps its id: ``topic_revisions`` holds each
    # edit of its name and description (the embedding made from them, who made it and which
    # fields changed), the newest row counting, the ``topics`` row as written at its insert
    # under them. ``topic_source_events``: a source added to or removed from one topic
    # (``link``, ``unlink``), the newest row of a pair counting; a pair with none is linked as
    # ``topic_sources`` says. Every reader goes through two views: ``topics_now`` (a topic
    # with its newest name and description) and ``topic_links`` (the pairs linked now), so a
    # rename is seen everywhere at once and nothing is copied or rewritten. Archiving is a
    # status (``status_events``, ``archived``), as pausing is.
    (38, """
    CREATE TABLE topic_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        embedding BLOB NOT NULL,
        embedding_model TEXT NOT NULL,
        changed TEXT NOT NULL DEFAULT '[]',
        by TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX topic_revisions_topic ON topic_revisions (topic_id, id);
    CREATE TABLE topic_source_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        source_id INTEGER NOT NULL REFERENCES sources(id),
        op TEXT NOT NULL CHECK (op IN ('link', 'unlink')),
        by TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX topic_source_events_pair ON topic_source_events (topic_id, source_id, id);
    CREATE VIEW topics_now AS
        SELECT t.id, COALESCE(r.name, t.name) AS name,
               COALESCE(r.description, t.description) AS description,
               COALESCE(r.embedding, t.embedding) AS embedding,
               COALESCE(r.embedding_model, t.embedding_model) AS embedding_model,
               t.supersedes, t.created_at, t.kind, t.ref, t.name AS first_name
        FROM topics t LEFT JOIN topic_revisions r ON r.id = (
            SELECT MAX(x.id) FROM topic_revisions x WHERE x.topic_id = t.id);
    CREATE VIEW topic_links AS
        SELECT ts.topic_id, ts.source_id, ts.created_at FROM topic_sources ts
        WHERE COALESCE((SELECT e.op FROM topic_source_events e WHERE e.topic_id = ts.topic_id
                        AND e.source_id = ts.source_id ORDER BY e.id DESC LIMIT 1),
                       'link') = 'link';
    """),
    # 39: background work you can see. ``runs`` stays the end record and the
    # scheduler's due-ness; a run's life as it goes is ``run_marks``: started, progress,
    # waiting (it stopped for the owner), stopping (the owner pressed Stop), ended, dismissed
    # (the owner put a failure away). ``state`` is the ended mark's (ok, degraded, failed,
    # skipped, stopped); ``pid``/``pstart`` the process that wrote ``started`` (a run whose
    # process is gone is cut off, never running forever). Rows leave only through the recorded
    # purge (``activity.keep_days``, ``activity.max_rows``). The two indexes ``runs`` lacked:
    # the scheduler's due-ness reads and the recent runs scanned the table every tick.
    (39, f"""
    CREATE TABLE run_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_uuid TEXT NOT NULL,
        kind TEXT NOT NULL,
        ts TEXT NOT NULL,
        mark TEXT NOT NULL CHECK (mark IN ('started', 'progress', 'waiting', 'stopping',
                                           'ended', 'dismissed')),
        state TEXT,
        trigger TEXT,
        by TEXT,
        subject_kind TEXT,
        subject_id TEXT,
        subject_name TEXT,
        title TEXT,
        words TEXT,
        error TEXT,
        step INTEGER,
        steps INTEGER,
        pid INTEGER,
        pstart INTEGER,
        needs TEXT,
        detail TEXT
    );
    CREATE INDEX run_marks_run ON run_marks (run_uuid, id);
    CREATE INDEX run_marks_ts ON run_marks (ts);
    CREATE INDEX run_marks_kind ON run_marks (kind, mark, id);
    CREATE INDEX runs_finished ON runs (finished_at);
    CREATE INDEX runs_kind_finished ON runs (kind, finished_at);
    CREATE TRIGGER run_marks_no_delete BEFORE DELETE ON run_marks
    WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = '{PURGE_TOKEN}')
    BEGIN SELECT RAISE(ABORT, 'run_marks is append-only'); END;
    """),
    # 40: News's articles (``features/news/articles.py``). Both append-only
    # (``ctx.db`` refuses anything else). ``news_articles``: one row per article written for a
    # brief item (``brief_id``, ``item_n``), never edited: Deep dive now on an item that has one
    # writes a new row and the newest counts. ``body`` holds the checked sections, numbers,
    # timeline, series, entities, relations, themes, idea seed and the lead image; ``sources``
    # the cited lines in reading order; ``material`` every label of the material without its
    # text, the searches' and the pages' log; ``checks`` what the code dropped or rewrote.
    # ``news_article_pages``: the pages the deep dive read (the cut text), so the checks can be
    # replayed and a page fetched in the last 7 days is reused.
    (40, """
    CREATE TABLE news_articles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES topics(id),
        brief_id INTEGER NOT NULL REFERENCES news_briefs(id),
        item_n INTEGER NOT NULL,
        run_uuid TEXT,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('ok', 'quiet', 'failed')),
        kind TEXT,
        headline TEXT,
        standfirst TEXT,
        body TEXT NOT NULL DEFAULT '{}',
        sources TEXT NOT NULL DEFAULT '[]',
        material TEXT NOT NULL DEFAULT '{}',
        words INTEGER,
        diagram TEXT,
        quiet TEXT,
        error TEXT,
        llm_call_id INTEGER,
        model TEXT,
        prompt_version TEXT,
        cost_usd REAL,
        equiv_usd REAL,
        checks TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX news_articles_item ON news_articles (brief_id, item_n, id);
    CREATE INDEX news_articles_topic ON news_articles (topic_id, id);
    CREATE TABLE news_article_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        article_id INTEGER REFERENCES news_articles(id),
        label TEXT NOT NULL,
        url TEXT NOT NULL,
        observation_id INTEGER,
        fetched_at TEXT NOT NULL,
        chars INTEGER NOT NULL,
        text TEXT NOT NULL,
        image TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX news_article_pages_url ON news_article_pages (url, fetched_at);
    """),
    # 41: prepared presses (``web/verbs_api.py``): a verb an assistant asked
    # for that waits for the owner's press, because the ladder says "Ask me in the UI". One
    # row per state, append-only: ``open`` when it is prepared, then ``pressed`` (the owner
    # pressed it on the page; ``run_uuid`` is the run that did it) or ``dismissed``; the newest
    # row of a ``prepared_uuid`` is its state, and an open one past ``expires_at`` reads as
    # expired. ``fields`` are the verb's typed fields as the assistant gave them; ``by`` who
    # prepared it (``console:claude``, ``mcp:codex``).
    (41, """
    CREATE TABLE prepared (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prepared_uuid TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('open', 'pressed', 'dismissed')),
        verb TEXT NOT NULL,
        subject_kind TEXT,
        subject_id TEXT,
        subject_name TEXT,
        fields TEXT NOT NULL DEFAULT '{}',
        by TEXT,
        page TEXT,
        mark TEXT,
        words TEXT,
        run_uuid TEXT,
        expires_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX prepared_uuid ON prepared (prepared_uuid, id);
    CREATE INDEX prepared_created ON prepared (created_at);
    """),
    # 42: invest cards: one model run with research tools makes a card; code
    # resolves its instrument, prices and sizes it. All append-only: a card's row is what the
    # run made, and what became of it is its newest ``invest_card_events`` row of kind
    # ``state`` (``proposed``, ``watch``, ``refused``, ``sent``, ``submitted``, ``filled``,
    # ``discarded``, ``dismissed``, ``expired``); a later resolution, price or size is a row of
    # its own (``invest_resolutions``, events). ``invest_calendar``: dated events with their
    # source; ``invest_fills``: every trade the broker reports, Kranto's or not; ``invest_marks``:
    # each card's price against its benchmark over time.
    (42, """
    CREATE TABLE invest_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        state TEXT NOT NULL,
        ask TEXT NOT NULL DEFAULT '{}',
        topic_ids TEXT NOT NULL DEFAULT '[]',
        thesis TEXT NOT NULL DEFAULT '{}',
        instrument TEXT,
        resolution TEXT,
        quote TEXT,
        position TEXT,
        order_json TEXT,
        checks TEXT NOT NULL DEFAULT '{}',
        evidence TEXT NOT NULL DEFAULT '{}',
        calendar_ids TEXT NOT NULL DEFAULT '[]',
        trace TEXT NOT NULL DEFAULT '{}',
        run_uuid TEXT,
        llm_call_ids TEXT NOT NULL DEFAULT '[]',
        prompt_version TEXT,
        by TEXT,
        expires_at TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_cards_created ON invest_cards (created_at);
    CREATE TABLE invest_card_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL REFERENCES invest_cards(id),
        kind TEXT NOT NULL,
        state TEXT,
        detail TEXT NOT NULL DEFAULT '{}',
        door TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_card_events_card ON invest_card_events (card_id, id);
    CREATE TABLE invest_resolutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL REFERENCES invest_cards(id),
        instrument TEXT,
        steps TEXT NOT NULL DEFAULT '[]',
        verdict TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_resolutions_card ON invest_resolutions (card_id, id);
    CREATE TABLE invest_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity TEXT NOT NULL,
        entity_cik TEXT,
        kind TEXT NOT NULL,
        date TEXT NOT NULL,
        confirmed INTEGER NOT NULL DEFAULT 0,
        computed INTEGER NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT '{}',
        reminder_at TEXT,
        card_id INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_calendar_date ON invest_calendar (date);
    CREATE TABLE invest_fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        broker_ref TEXT NOT NULL,
        client_ref TEXT,
        account TEXT,
        conid INTEGER,
        symbol TEXT,
        side TEXT,
        quantity REAL,
        price REAL,
        commission REAL,
        traded_at TEXT,
        card_id INTEGER,
        outside INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_fills_ref ON invest_fills (broker_ref);
    CREATE TABLE invest_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL REFERENCES invest_cards(id),
        at TEXT NOT NULL,
        price REAL,
        bench REAL,
        bench_symbol TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX invest_marks_card ON invest_marks (card_id, at);
    """),
    # 43: the browser extension. ``browser_captures``: what a paired
    # browser read or saved, one row per send, never edited; a later read of the same page is a
    # row of its own whose ``supersedes`` names the one before. Its rows leave only through the
    # recorded purge (Forget, retention), so the text the person read can be removed for good.
    # ``item_id`` is ``browser:<sha256 of site + canonical url>``; no author is kept (the door
    # drops it). ``browser_capture_events``: what became of a page (``consumed`` by the ingest,
    # ``updated_same``, ``forgotten``, ``removed``), append-only; a forgotten page keeps a line
    # with its site and section, never its text. ``browser_clients``: each paired browser's
    # rows (``paired``, the ``sites`` its extension reported, ``forgotten``), append-only; the
    # newest row of a token says its state.
    (43, f"""
    CREATE TABLE browser_captures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_name TEXT NOT NULL,
        browser TEXT,
        site TEXT NOT NULL,
        url TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        item_id TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('watch', 'save')),
        extractor TEXT,
        title TEXT,
        published_at TEXT,
        section TEXT,
        score INTEGER,
        comment_count INTEGER,
        visible_comments INTEGER NOT NULL DEFAULT 0,
        read_dwell_ms INTEGER,
        read_scroll REAL,
        link TEXT,
        lang TEXT,
        text TEXT NOT NULL DEFAULT '',
        comments TEXT NOT NULL DEFAULT '[]',
        size_bytes INTEGER NOT NULL DEFAULT 0,
        supersedes INTEGER,
        source_id INTEGER,
        captured_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX browser_captures_item ON browser_captures (item_id, id);
    CREATE INDEX browser_captures_created ON browser_captures (created_at);
    CREATE INDEX browser_captures_source ON browser_captures (source_id, id);
    CREATE TRIGGER browser_captures_no_delete BEFORE DELETE ON browser_captures
    WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = '{PURGE_TOKEN}')
    BEGIN SELECT RAISE(ABORT, 'browser_captures is append-only'); END;
    CREATE TABLE browser_capture_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL,
        capture_id INTEGER,
        kind TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{{}}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX browser_capture_events_item ON browser_capture_events (item_id, id);
    CREATE TABLE browser_clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('paired', 'sites', 'forgotten')),
        browser TEXT,
        label TEXT,
        sites TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL
    );
    CREATE INDEX browser_clients_token ON browser_clients (token_name, id);
    """),
    # 44: posts at an hour, and what a sent post drew. ``post_due``: the person's yes to send
    # one waiting ask at a time they chose (``held``), and what became of it, one row a change,
    # never edited: moved (a newer ``held`` row), ``cancelled``, ``missed`` (its hour passed
    # while Kranto was stopped: the ask waits again for a new yes), ``void`` (the ask was
    # answered, edited or declined before the hour), ``spent`` (Kranto sent it at its hour:
    # the yes is used up whatever the site answered). The newest row of a ticket says where it
    # stands. ``fields_hash`` binds the yes to the words the person read. ``post_reach``: one
    # row a reading of a sent post's numbers (each nullable: a site that does not give one
    # stores null); ``shape`` is the post's shape (site, parts, card, length, weekday and hour
    # sent) for what was learned.
    (44, """
    CREATE TABLE post_due (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('held', 'cancelled', 'missed', 'void', 'spent')),
        due_at TEXT NOT NULL,
        fields_hash TEXT NOT NULL,
        door TEXT,
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX post_due_ticket ON post_due (ticket_id, id);
    CREATE TABLE post_reach (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        site TEXT NOT NULL,
        read_at TEXT NOT NULL,
        replies INTEGER,
        reposts INTEGER,
        likes INTEGER,
        quotes INTEGER,
        views INTEGER,
        shape TEXT NOT NULL DEFAULT '{}',
        note TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX post_reach_ticket ON post_reach (ticket_id, id);
    """),
]


def _derived_tables(conn: sqlite3.Connection) -> set[str]:
    """Full-text indexes and their shadow tables: derived data, not library rows."""
    virtual = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND sql LIKE 'CREATE VIRTUAL TABLE%'")]
    return set(virtual) | {f"{v}_{suffix}" for v in virtual for suffix in FTS5_SHADOW_SUFFIXES}


def _known_tables() -> frozenset[str]:
    """The tables this version's migrations create."""
    pattern = re.compile(r"CREATE\s+(?:VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", re.I)
    return frozenset(m.group(1) for _, script in _MIGRATIONS for m in pattern.finditer(script))


def _library_tables(conn: sqlite3.Connection) -> list[str]:
    """The append-only tables: every table a known migration created that is neither mutable
    nor derived. A table from a newer version (the database after a rollback) is left to that
    version's rules: making it append-only here would break the newer version when it comes
    back (``oauth_states``, mutable, came in migration 18)."""
    derived = _derived_tables(conn)
    known = _known_tables()
    return [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        if row[0] not in MUTABLE_TABLES and row[0] not in derived and row[0] in known
    ]


def _append_only_triggers(conn: sqlite3.Connection) -> None:
    for table in _library_tables(conn):
        for op in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()} "
                f"BEFORE {op} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )


class Store:
    """Thread-safe handle on the library database."""

    def __init__(self, conn: sqlite3.Connection, path: Path | None) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        self.path = path
        # the last run of each kind that had nothing to do (``insert`` of a skipped run, 
        # PR 1.3): kept here, not in ``runs``; the scheduler's recheck and the run's ended mark
        # read it. A restart forgets it, and the job looks once more.
        self.skips: dict[str, dict[str, Any]] = {}

    @classmethod
    def open(cls, path: Path | str) -> Store:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        store = cls(conn, path if str(path) != ":memory:" else None)
        store._configure()
        store.migrate()
        return store

    @classmethod
    def memory(cls) -> Store:
        conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        store = cls(conn, None)
        store._configure()
        store.migrate()
        return store

    def _configure(self) -> None:
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # REPLACE resolves a conflict by deleting the old row, and SQLite fires
        # DELETE triggers for that only with recursive triggers on. Without this,
        # INSERT OR REPLACE overwrote rows in append-only tables.
        self._conn.execute("PRAGMA recursive_triggers = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if self.path is not None:
            self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def lock_path(self, kind: str) -> Path | None:
        """Where a job of this kind takes its file lock; None for an in-memory store.

        Named after the database file, so two databases in one directory do not
        block each other."""
        if self.path is None:
            return None
        path = Path(self.path)
        return path.parent / f"{path.name}.{kind}.lock"

    def missing_tables(self) -> list[str]:
        """Tables the migrations create that are not in the database."""
        expected = {name for _, script in _MIGRATIONS
                    for name in re.findall(r"CREATE (?:VIRTUAL )?TABLE (\w+)", script)}
        present = {r["name"] for r in self.query(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        return sorted(expected - present)

    # -- transactions -------------------------------------------------------

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    @contextmanager
    def purge(self) -> Iterator[sqlite3.Connection]:
        """A transaction in which rows of ``PURGEABLE_TABLES`` may be deleted.

        The purge token exists only inside this transaction, so no other
        connection ever sees it, and a rollback takes it away with everything
        else. The caller records each removal in ``purges`` in the same
        transaction. Foreign keys are off for its duration: rows that stay (an
        ``items_seen`` row, a newer observation that supersedes a removed one)
        keep the ids of rows that went, and cannot be updated to drop them.
        """
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = OFF")
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._conn.execute(
                        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                        (PURGE_TOKEN, "compaction", iso(utcnow())),
                    )
                    yield self._conn
                    self._conn.execute("DELETE FROM settings WHERE key = ?", (PURGE_TOKEN,))
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                self._conn.execute("COMMIT")
            finally:
                self._conn.execute("PRAGMA foreign_keys = ON")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def insert(self, table: str, row: dict[str, Any]) -> int:
        if table == "runs" and _nothing_to_do(row):
            # a job that had nothing to do is not a run: no row, only the
            # note the scheduler and the ended mark read; returns 0, no rowid
            self.skips[str(row.get("kind"))] = {
                "at": row.get("finished_at"), "error": row.get("error"),
                "run_uuid": row.get("run_uuid")}
            return 0
        cols = ", ".join(row)
        marks = ", ".join(f":{c}" for c in row)
        with self._lock:
            cur = self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", row)
            return int(cur.lastrowid)

    def skipped_at(self, kind: str) -> datetime | None:
        """When a job of ``kind`` last had nothing to do in this process, or None."""
        at = (self.skips.get(kind) or {}).get("at")
        if not at:
            return None
        return datetime.fromisoformat(str(at).replace("Z", "+00:00"))

    def skip_of(self, run_uuid: str) -> dict[str, Any] | None:
        """The skip a run was (``insert``), by its uuid: its error, for its ended mark."""
        return next((s for s in self.skips.values() if s.get("run_uuid") == run_uuid), None)

    # -- schema -------------------------------------------------------------

    def applied_migrations(self) -> set[int]:
        if not self._has_table("schema_meta"):
            return set()
        rows = self.query("SELECT key FROM schema_meta WHERE key LIKE 'migration:%'")
        return {int(r["key"].split(":", 1)[1]) for r in rows}

    @staticmethod
    def migration_numbers() -> list[int]:
        """Every migration this version knows, ascending."""
        return sorted(n for n, _ in _MIGRATIONS)

    def schema_version(self) -> int:
        return max(self.applied_migrations(), default=0)

    def _has_table(self, name: str) -> bool:
        return (
            self.query_one(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
            )
            is not None
        )

    def migrate(self) -> None:
        """Apply every numbered migration not yet recorded, in ascending order.

        Each applied migration is recorded individually (``migration:N``), so
        branches that each own a pre-assigned number can merge in any order.
        Databases from before this scheme stored a single ``version``; every
        number up to it is marked applied the first time they are opened.
        """
        numbers = [n for n, _ in _MIGRATIONS]
        if len(numbers) != len(set(numbers)):
            raise RuntimeError("duplicate migration numbers")
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            legacy = self._conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            ).fetchone()
            if legacy is not None:
                self._conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + "".join(
                        f"INSERT OR IGNORE INTO schema_meta (key, value) "
                        f"VALUES ('migration:{n}', 'legacy');\n"
                        for n in range(1, int(legacy[0]) + 1)
                    )
                    + "DELETE FROM schema_meta WHERE key = 'version';\nCOMMIT;"
                )
            applied = self.applied_migrations()
            for number, script in sorted(_MIGRATIONS):
                if number in applied:
                    continue
                # The record commits in the same transaction as the migration,
                # so a crash cannot leave a half-applied schema.
                self._conn.executescript(
                    f"BEGIN IMMEDIATE;\n{script}\n"
                    f"INSERT INTO schema_meta (key, value) VALUES ('migration:{number}', "
                    f"'{iso(utcnow())}');\nCOMMIT;"
                )
            _append_only_triggers(self._conn)

    def append_only_tables(self) -> list[str]:
        with self._lock:
            return sorted(_library_tables(self._conn))

    # -- settings (the one mutable table) ------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str, *, now: datetime | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, iso(now or utcnow())),
            )

    def delete_setting(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))

    # -- pause ---------------------------------------------------------------

    def pause_reason(self) -> str | None:
        return self.get_setting("paused")

    def pause(self, reason: str) -> None:
        self.set_setting("paused", reason or "paused")

    def resume(self) -> None:
        """Lift the pause, and a provider's pause (``watch_paused``): resuming by hand means
        now, for instance after raising a spend limit at the provider."""
        self.delete_setting("paused")
        self.delete_setting("watch_paused")

    # -- spend ---------------------------------------------------------------

    def month_spend(self, now: datetime | None = None) -> float:
        return self.spend_since(month_start(now or utcnow()))

    def spend_since(self, start: datetime) -> float:
        """Model spend recorded since ``start``, including calls purged since.

        A purge of ``llm_calls`` records the removed calls' cost per UTC day, so
        compaction never lowers the spend the budget is checked against. Purged
        cost counts from the day of ``start``: exact from midnight (the month's
        start), at most one day early otherwise.
        """
        row = self.query_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM llm_calls WHERE created_at >= ?",
            (iso(start),),
        )
        purged = self.query_one(
            "SELECT COALESCE(SUM(day.value), 0) AS total FROM purges p, "
            "json_each(p.detail, '$.cost_by_day') day "
            "WHERE p.table_name = 'llm_calls' AND day.key >= ?",
            (iso(start)[:10],),
        )
        return float(row["total"]) + float(purged["total"])

    # -- tokens --------------------------------------------------------------
    # What the UI shows for a measured amount (the owner's ruling, 2026-10-09): tokens
    # read and written, from llm_calls. Calls compaction removed keep only their cost, so
    # token counts cover the calls still in the library; None when there is no token data.

    def tokens_since(self, start: datetime) -> dict | None:
        """{"in", "out"} tokens of the model calls since ``start``; None if none has counts."""
        row = self.query_one(
            "SELECT COUNT(prompt_tokens) AS n, COALESCE(SUM(prompt_tokens), 0) AS i, "
            "COALESCE(SUM(completion_tokens), 0) AS o FROM llm_calls WHERE created_at >= ?",
            (iso(start),))
        return {"in": int(row["i"]), "out": int(row["o"])} if row["n"] else None

    def run_tokens(self, run_uuids: list[str]) -> dict[str, dict]:
        """{run_uuid: {"in", "out"}} for the runs whose calls carry token counts."""
        if not run_uuids:
            return {}
        marks = ",".join("?" * len(run_uuids))
        rows = self.query(
            "SELECT run_uuid, COALESCE(SUM(prompt_tokens), 0) AS i, "
            "COALESCE(SUM(completion_tokens), 0) AS o FROM llm_calls "
            f"WHERE run_uuid IN ({marks}) AND prompt_tokens IS NOT NULL GROUP BY run_uuid",
            tuple(run_uuids))
        return {r["run_uuid"]: {"in": int(r["i"]), "out": int(r["o"])} for r in rows}

    # -- status events -------------------------------------------------------

    def current_status(self, entity: str, entity_id: int) -> str | None:
        row = self.query_one(
            "SELECT status FROM status_events WHERE entity = ? AND entity_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (entity, entity_id),
        )
        return row["status"] if row else None

    def set_status(
        self, entity: str, entity_id: int, status: str, note: str | None = None,
        *, now: datetime | None = None,
    ) -> None:
        self.insert(
            "status_events",
            {
                "entity": entity,
                "entity_id": entity_id,
                "status": status,
                "note": note,
                "created_at": iso(now or utcnow()),
            },
        )

    # -- export --------------------------------------------------------------

    def export_jsonl(self, table: str, out: IO[str]) -> int:
        if table not in self.append_only_tables() and table != "settings":
            raise ValueError(f"unknown table: {table}")
        count = 0
        for row in self.query(f"SELECT * FROM {table} ORDER BY rowid"):
            record = {}
            for key in row.keys():  # noqa: SIM118 - sqlite3.Row iterates values
                value = row[key]
                if isinstance(value, bytes):
                    value = [round(float(x), 6) for x in blob_to_vec(value)]
                record[key] = value
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
        return count
