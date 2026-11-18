#!/usr/bin/env python3
"""The odd install: a Kranto library
generated, never copied from anyone's, holding what the writers can store rather than what one
install happens to contain.

Everything we tested against used to look like the maintainer's install, and the maintainer
never added a source without a topic, so a null similarity never existed in any database we
tested. This writes one where every odd value the contract types allow is present: every
nullable field null, every optional path taken.

Variants:

  odd      every case in CASES
  empty    a library with nothing in it (no topic, no source)
  projects project topics only, no user topic (Watch's last-topic rule, Ideas of a project)
  upgraded v0.2.0's writers, then each release that first carried a migration, each writing on
           the same home with its own code (scripts/dev/odd_old.py), then this tree's migrations:
           rows and JSON as every older version wrote them. Built by --upgrade (git worktrees
           and 'uv sync --locked' per tag: minutes, the network for the old locks), committed
           in tests/fixtures/odd_install/upgraded/; --variant upgraded copies the committed one.

Rows go in through the writers the product calls (``library.add_topic``,
``library.add_source(..., validation=Validation(...))``, ...), so a case is a shape a writer
can make; the contract types' ``odd()`` values supply the shapes, so a field added to a type is
in the next library with no edit here. Where a writer needs a model or the network, the case
builds the contract type the writer would have stored. A run's summary from an older or odd
writer (``[]``, ``{}``) goes in with ``store.insert``, as the column allows it.

Usage:
  odd_install.py --variant odd --out DIR     write DIR/kranto.yaml (the default config),
                                             DIR/data/kranto.db and DIR/manifest.json
  odd_install.py --upgrade --out DIR [--worktrees W]
                                             build the upgraded home in DIR (the tags'
                                             worktrees under W, default DIR/../.worktrees)
Under pytest, ``tests/test_odd_install.py`` builds each variant in a temporary folder.
Nothing here reads the network or a model: the stub embedder stands in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kranto import config as config_mod
from kranto import library
from kranto import stored as stored_mod
from kranto.embed import StubEmbedder
from kranto.prose.learner import Learned
from kranto.prose.profile import ProfileRow
from kranto.store import Store
from kranto.stored import runs as stored_runs
from kranto.stored.cards import Card, Dropped, InputIds
from kranto.stored.sources import Params, Validation

VARIANTS = ("odd", "empty", "projects", "upgraded")
# v0.2.0 (migrations 1-22), then each release that first carried a migration
CHAIN = ("v0.2.0", "v0.3.23", "v0.3.73", "v0.3.81", "v0.3.83", "v0.4.1", "v0.4.6", "v0.4.10",
         "v0.4.11", "v0.5.6", "v0.5.9", "v0.5.11", "v0.5.14")
ROOT = Path(__file__).resolve().parents[2]
UPGRADED = ROOT / "tests" / "fixtures" / "odd_install" / "upgraded"
NOW = "2026-10-23T12:00:00Z"


@dataclass
class Ctx:
    """What a case writes with, and what the cases wrote so far (ids by name)."""

    store: Store
    embedder: StubEmbedder
    topics: dict[str, int] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)
    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Case:
    area: str
    name: str
    types: tuple[type, ...]               # the contract types it exercises
    write: Callable[[Ctx], None]


def _feed(name: str) -> dict[str, Any]:
    return {"url": f"https://odd.example/{name}/feed.xml"}


# -- topics --

def topics(ctx: Ctx) -> None:
    lib, s, e = library, ctx.store, ctx.embedder
    ctx.topics["user"] = lib.add_topic(s, e, "Tea", "tea growing and the tea trade")
    ctx.topics["paused"] = lib.add_topic(s, e, "Ceramics", "kilns, glazes, studio pottery")
    lib.set_topic_status(s, ctx.topics["paused"], "paused", "paused by the maintainer")
    ctx.topics["archived"] = lib.add_topic(s, e, "Old", "a topic the maintainer archived")
    lib.set_topic_status(s, ctx.topics["archived"], "archived", "archived by the maintainer")
    ctx.topics["project"] = lib.add_topic(s, e, "A project", "what a project gathers for",
                                          kind="project", ref="project:oddproject")
    ctx.topics["no_sources"] = lib.add_topic(s, e, "Empty", "a topic with no source at all")


# -- sources --

def validation_odd_values(ctx: Ctx) -> None:
    """One source for each odd value of the Validation type (derived: every optional field
    null, every list empty, every word, plus its named cases: the unmeasured row, a pack's, a
    hand-added one, a preset's, a site watched through live search, an invalid one, a
    wildcard), each proposed, linked to the user topic."""
    for i, v in enumerate(Validation.odd()):
        status = "invalid" if v.status == "invalid" else "proposed" if i % 2 else "approved"
        sid = library.add_source(ctx.store, "rss", _feed(f"v{i}"), label=f"Odd feed {i}",
                                 origin="scout", status=status, validation=v)
        if i % 3 == 0:
            library.link_topic_source(ctx.store, ctx.topics["user"], sid)
        ctx.sources[f"validation-{i}"] = sid


def described_without_a_topic(ctx: Ctx) -> None:
    """Add sources by describing them, no topic chosen: the similarity is not measured
    (the row whose null similarity once broke a page, as resolve.take stores it)."""
    v = Validation(status="valid", items=12, recent=3, median_similarity=None, topic_id=None,
                   role="core", why="a blog about tea", from_text="tea blogs",
                   batch="fromtext:1")
    ctx.sources["described"] = library.add_source(
        ctx.store, "rss", _feed("described"), label="Described, no topic", origin="manual",
        status="proposed", validation=v)


def parallax_import(ctx: Ctx) -> None:
    """A Parallax import: no validation at all (the column is NULL), status imported."""
    ctx.sources["imported"] = library.add_source(
        ctx.store, "rss", _feed("imported"), label="Imported", origin="import",
        status="imported", validation=None)


def linking(ctx: Ctx) -> None:
    """A source linked to no topic, one linked to two, one unlinked again."""
    s = ctx.store
    ctx.sources["unlinked"] = library.add_source(s, "rss", _feed("unlinked"), label="Unlinked")
    two = library.add_source(s, "rss", _feed("two"), label="Two topics")
    library.link_topic_source(s, ctx.topics["user"], two)
    library.link_topic_source(s, ctx.topics["paused"], two)
    gone = library.add_source(s, "rss", _feed("gone"), label="Unlinked again")
    library.link_topic_source(s, ctx.topics["user"], gone)
    library.unlink_topic_source(s, ctx.topics["user"], gone, by="owner", note="not useful")
    project = library.add_source(s, "rss", _feed("project"), label="A project's feed")
    library.link_topic_source(s, ctx.topics["project"], project)


def params_of_each_kind(ctx: Ctx) -> None:
    """A source of each kind the catalog adds without an account: the params as each writer
    stores them."""
    for kind, params in (("hackernews", {"feed": "top"}), ("hackernews", {"query": "tea"}),
                         ("arxiv", {"query": "tea fermentation"}), ("reddit",
                                                                    {"subreddit": "tea"}),
                         ("websearch", {"site": "odd.example"})):
        ctx.sources[f"{kind}-{len(ctx.sources)}"] = library.add_source(
            ctx.store, kind, Params(extra=params).kwargs(), label=f"{kind} source",
            status="approved")


def odd_run_summaries(ctx: Ctx) -> None:
    """Ingest runs whose summary is ``[]`` and ``{}`` (a summary that is JSON but not an
    object reached the topic page's path through source_health._from_runs), and a failed run
    with an error and an empty summary."""
    for i, (status, summary, error) in enumerate((("ok", "[]", None), ("ok", "{}", None),
                                                  ("failed", "{}", "the feed timed out"))):
        ctx.store.insert("runs", {"run_uuid": f"odd-ingest-{i}", "kind": "ingest",
                                  "status": status, "started_at": NOW, "finished_at": NOW,
                                  "summary": summary, "error": error})


def run_summaries_of_every_kind(ctx: Ctx) -> None:
    """For each run kind with a type, a run per odd value of its summary, in each status, as
    the writers store it (``stored.runs.text_for``); and a feature's job, a compact run, an
    update check with summaries of their own shape."""
    statuses = ("ok", "degraded", "failed", "skipped")
    for kind, cls in stored_runs.KINDS.items():
        for i, summary in enumerate(cls.odd()):
            ctx.store.insert("runs", {
                "run_uuid": f"odd-typed-{kind}-{i}", "kind": kind, "status": statuses[i % 4],
                "started_at": NOW, "finished_at": NOW,
                "summary": stored_runs.text_for(kind, summary.to_dict()),
                "error": "the run failed" if statuses[i % 4] == "failed" else None})
    for kind, summary in (("news.brief", {"status": "skipped", "briefs": 0, "not_due": True}),
                          ("compact", {"rollups": 0, "removed": 0}),
                          ("update", {"state": "up to date", "latest": None})):
        ctx.store.insert("runs", {
            "run_uuid": f"odd-job-{kind}", "kind": kind, "status": "ok", "started_at": NOW,
            "finished_at": NOW, "summary": stored_runs.text_for(kind, summary), "error": None})


def cards_of_every_shape(ctx: Ctx) -> None:
    """A card for each odd value of the card's type (the derived ones and its named cases: a
    card from the first prompt, a dispatch card, an evidence entry with no observation id),
    shown and unsupported, each with an odd dropped list, through ``cards.insert_card`` (the
    writers' insert, which writes its topics and citations too); a card from before #96 whose
    demand is the statement alone."""
    from kranto.ideate import cards

    dropped = Dropped.odd()
    shapes = [c.to_dict() for c in Card.odd()]
    shapes.append({"title": "Before #96", "thesis": "t", "demand": "people ask for it",
                   "evidence": [{"n": 1, "claim": "c", "observation_id": 1}], "ratings": {}})
    for i, card in enumerate(shapes):
        cards.insert_card(ctx.store, {
            "snapshot_id": None, "fingerprint": f"odd:{i}", "lineage_id": None,
            "origin": "dispatch" if card.get("pitch") else "cluster",
            "evidence_key": f"odd-card-{i}", "input_ids": InputIds.write([1, 2]),
            "title": card.get("title") or f"Odd card {i}", "card": Card.write(card),
            "score": 0.0 if i % 2 else 0.5, "status": "unsupported" if i % 3 == 2 else "shown",
            "dropped": dropped[i % len(dropped)].to_json(), "gen_call_id": None,
            "verify_call_id": None, "run_uuid": f"odd-cards-{i}", "created_at": NOW})


def settings_and_marks(ctx: Ctx) -> None:
    """The settings blobs as their writers store them (a watch pause past and one to come, a
    halt, live switched on, a failed key test, a Sanity site, a newsletter sender with a
    check), each odd value of their types; a waiting mark with needs and one without; a mark
    whose detail was over the cap; an event with an odd payload."""
    from kranto import activity
    from kranto.core import events
    from kranto.stored import settings as stored_settings

    s = ctx.store
    for key, cls in (("watch_paused", stored_settings.WatchPause),
                     ("money.halted", stored_settings.MoneyHalt),
                     ("money.live", stored_settings.MoneyLive),
                     ("setup.key_test", stored_settings.KeyTest),
                     ("sanity.site", stored_settings.SanitySite),
                     ("newsletter.sender", stored_settings.NewsletterSender),
                     ("money.broker.ibkr.approved", stored_settings.ToolsApproved)):
        for v in cls.odd():                    # the last one written stays
            stored_settings.set_blob(s, key, v)
    stored_settings.set_blob(s, "watch_paused", stored_settings.WatchPause(
        until="2099-01-01T00:00:00Z", reason="a usage limit", provider="claude_code"))
    stored_settings.set_blob(s, "setup.key_test", stored_settings.KeyTest(
        ok=False, detail="the key was refused", base_url="https://odd.example", at=NOW))
    with activity.run(s, "odd.waiting", origin="test", by="odd") as r:
        r.waiting("Review the odd proposals", {"verb": "Review", "href": "#/activity"})
    with activity.run(s, "odd.waiting.bare", origin="test", by="odd") as r:
        r.waiting("Something waits", None)
    with activity.run(s, "odd.detail", origin="test", by="odd"):
        activity.progress("a long step", detail={"blob": "x" * 20000})
    activity.settle(s)
    events.core_publish(s, "money.halted", {"by": "odd", "nested": {"a": [1, None, "x"]}})


def prose_rows(ctx: Ctx) -> None:
    """The prose profile's two settings rows at each odd value of their types, the last
    written staying."""
    from kranto.prose import learner, profile
    from kranto.stored import settings as stored_settings

    for key, cls in ((profile.ProfileRow.SETTING, profile.ProfileRow),
                     (learner.Learned.SETTING, learner.Learned)):
        for v in cls.odd():
            stored_settings.set_blob(ctx.store, key, v)


def cubs_of_every_grant(ctx: Ctx) -> None:
    """A cub for each odd value of its grants (none at all, every block empty, no requests
    and no events, narrowed to topics, storage none), installed, paused and removed, through
    ``registry.append``; none has its folder on disk (a cub whose files went missing)."""
    from kranto.core.cubs import registry
    from kranto.stored.cubs import Grants

    states = ("installed", "paused", "removed")
    for i, g in enumerate(Grants.odd()):
        registry.append(ctx.store, {
            "cub": f"oddcub{i}", "state": states[i % 3], "version": "1.0.0",
            "trust": "stranger", "source_kind": "folder",
            "source": {"kind": "folder", "path": f"/nowhere/oddcub{i}"}, "sha": None,
            "tree_hash": "0" * 64, "manifest_hash": "0" * 64, "grants": g,
            "bears_range": None, "note": "odd" if i % 2 else None})


def features_odd(ctx: Ctx) -> None:
    """News: a brief failed (items ``[]``, an error), one quiet, one ok with an item whose
    sources are empty, each column through its contract (``T.write``, as the writer's type
    writes it): the writers need a model. Invest and the radar left Kranto (cut 2) but
    their rows stay on an install that had them: a proposal of each verdict with its steps NULL,
    a trend active and one dismissed (pricing NULL), a chain with no falsifiers and a chain whose
    record lacks links and candidates, a series value NULL, as plain JSON text (their
    contracts left with them); no route may break on them."""
    import json

    from kranto.features.news.stored import BriefChecks, BriefItems

    s, tid = ctx.store, ctx.topics["user"]
    for status, items, err in (("failed", [], "the model call failed"), ("quiet", [], None),
                               ("ok", [{"headline": "A thing", "body": "b", "sources": []}],
                                None)):
        s.insert("news_briefs", {
            "topic_id": tid, "period_start": NOW, "period_end": NOW, "status": status,
            "items": BriefItems.write(items), "quiet": "nothing new" if status == "quiet"
            else None, "error": err, "checks": BriefChecks.write({}), "created_at": NOW})
    for verdict in ("proposed", "journal", "watch", "not_investable"):
        s.insert("invest_proposals", {
            "topic_id": tid, "thesis": json.dumps({"title": f"odd {verdict}"}),
            "verdict": verdict, "mode": "paper", "cites": "[]",
            "created_at": NOW})
    for key, state in (("odd-trend", "active"), ("odd-gone", "dismissed")):
        s.insert("radar_trends", {"key": key, "title": key, "kind": "secular", "origin": "owner",
                                  "state": state, "created_at": NOW})
    for chain in ({"links": [], "candidates": []}, {}):
        s.insert("radar_chains", {
            "trend_key": "odd-trend", "chain": json.dumps(chain), "checks": "[]",
            "falsifiers": "[]",
            "created_at": NOW})
    s.insert("radar_series", {"trend_key": "odd-trend", "kind": "arxiv", "month": "2026-09",
                              "value": None, "source": "odd", "fetched_at": NOW})


def projects_only(ctx: Ctx) -> None:
    """The ``projects`` variant: project topics only (``kind = 'project'``, ``ref =
    'project:...'``), no user topic; a feed linked to each, one linked to both; an observation
    from each feed through ``library.record_observation``; a card citing both, so its topic is
    none and its shares are the projects' (``cards.topic_fields``)."""
    from kranto.ideate import cards
    from kranto.sources.base import Item
    from kranto.stored.observations import LlmRequest

    lib, s, e = library, ctx.store, ctx.embedder
    for name in ("alpha", "beta"):
        ctx.topics[name] = lib.add_topic(s, e, f"Project {name}", f"what {name} gathers for",
                                         kind="project", ref=f"project:{name}")
        sid = lib.add_source(s, "rss", _feed(name), label=f"{name} feed", status="approved")
        lib.link_topic_source(s, ctx.topics[name], sid)
        ctx.sources[name] = sid
    both = lib.add_source(s, "rss", _feed("both"), label="Both projects' feed")
    lib.link_topic_source(s, ctx.topics["alpha"], both)
    lib.link_topic_source(s, ctx.topics["beta"], both)
    ctx.sources["both"] = both
    call = s.insert("llm_calls", {"purpose": "judge", "tier": "judge", "model": "odd",
                                  "prompt_version": "odd", "request": LlmRequest.write({}),
                                  "status": "ok", "attempts": 1, "created_at": NOW})
    cited = []
    for name in ("alpha", "beta", "both"):
        summary = f"an observation from the {name} feed"
        cited.append(lib.record_observation(
            s, source_id=ctx.sources[name], item=Item(id=f"odd-{name}", title="",
                                                      body=summary),
            fields={"kind": "beat", "summary": summary, "why_it_matters": "w",
                    "content_quality": 0.5, "durability": 0.5, "opportunity": 0.5,
                    "signal": 0.125, "override": False, "override_reason": None, "tags": []},
            embedding=e.embed_documents([summary])[0], embedding_model=e.model_name,
            llm_call_id=call, prompt_version="odd", run_uuid="odd-projects",
            admitted_by="topic", topic_similarity=None))
    card = {"title": "A projects' card", "thesis": "t",
            "evidence": [{"n": i + 1, "claim": "c", "observation_id": o}
                         for i, o in enumerate(cited)]}
    cards.insert_card(s, {
        "snapshot_id": None, "fingerprint": "odd:projects", "lineage_id": None,
        "origin": "cluster", "evidence_key": "odd-projects", "input_ids": InputIds.write(cited),
        "title": card["title"], "card": Card.write(card), "score": 0.5, "status": "shown",
        "dropped": Dropped.write([]), "gen_call_id": None, "verify_call_id": None,
        "run_uuid": "odd-projects", "created_at": NOW})


# Tables the schema-driven case leaves alone: the key-value ones (a made-up key means nothing),
# the migrations' own records, and those an insert here would only duplicate a case above.
SCHEMA_SKIP = frozenset({"settings", "schema_meta", "schema_migrations", "purge_tokens"})
_CHECK_IN = re.compile(r"\b(\w+)\s+\w+[^,]*?CHECK\s*\(\s*\1\s+IN\s*\(([^)]*)\)", re.S | re.I)


def _allowed(sql: str) -> dict[str, list[Any]]:
    """Each column's ``CHECK (col IN (...))`` words, as the CREATE TABLE says them."""
    out: dict[str, list[Any]] = {}
    for col, words in _CHECK_IN.findall(sql or ""):
        vals: list[Any] = []
        for w in words.split(","):
            w = w.strip()
            vals.append(w.strip("'\"") if w[:1] in "'\"" else int(w) if w.lstrip("-").isdigit()
                        else w)
        out[col] = vals
    return out


def every_table(ctx: Ctx) -> None:
    """For every table (step 4): a row with every nullable column NULL and every
    JSON column at its contract's empty value; then a row for each odd value of each JSON
    column's contract. The other columns: a CHECK's first word, an existing parent for a
    foreign key (a child table waits for a pass after its parent's), a time for a time, a
    made-up text otherwise. A row the schema refuses (a UNIQUE pair, a trigger) is skipped and
    listed in the manifest's ``schema_skipped``."""
    stored_mod.load_all()
    conn = ctx.store._conn
    frozen = stored_mod.frozen_tables()
    tables = [(r[0], r[1]) for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "AND sql NOT LIKE 'CREATE VIRTUAL TABLE%' ORDER BY name")]
    virtual = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL%'")}
    n = 0
    todo = [(t, sql) for t, sql in tables if not (
        t in SCHEMA_SKIP or t in frozen or any(t.startswith(v + "_") for v in virtual))]
    while todo:                                 # a child waits for its parent's row
        waiting = [(t, sql) for t, sql in todo if _table_rows(ctx, t, sql, n_from=n) is None]
        n += 1000
        if len(waiting) == len(todo):
            ctx.skipped.extend(f"{t}: no parent row for a foreign key" for t, _ in waiting)
            return
        todo = waiting


def _table_rows(ctx: Ctx, t: str, sql: str, n_from: int) -> int | None:
    """One table's rows for :func:`every_table`: how many went in, or None when a foreign key's
    parent has no row yet."""
    import sqlite3

    conn = ctx.store._conn
    n = n_from
    cols = list(conn.execute(f'PRAGMA table_info("{t}")'))
    fks = {r[3]: (r[2], r[4]) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')}
    allowed = _allowed(sql)
    sole_key = sum(1 for c in cols if c[5]) == 1
    base: dict[str, Any] = {}
    counted: list[str] = []                     # made-up integers: each row its own
    for _, name, kind, notnull, default, pk in cols:
        kind = (kind or "").upper()
        contract = stored_mod.contract_for(t, name)
        if pk and kind == "INTEGER" and sole_key and name not in fks:
            continue                            # the row's id
        if name in fks:
            parent, key = fks[name]
            got = conn.execute(f'SELECT "{key or "id"}" FROM "{parent}" LIMIT 1').fetchone()
            if got is None and (notnull or pk):
                return None
            base[name] = got[0] if got is not None else None
        elif pk and kind == "INTEGER":         # a part of a key of several columns
            n += 1
            base[name] = n
            counted.append(name)
        elif pk:                                # a text key: SQLite lets it be NULL, no writer does
            n += 1
            base[name] = f"odd-{t}-{name}-{n}"
        elif contract is not None:
            base[name] = contract.empty().to_json() if notnull else None
        elif not notnull:
            base[name] = None
        elif default is not None:
            continue                            # the schema's own default
        elif name in allowed:
            base[name] = allowed[name][0]
        elif kind == "INTEGER":
            n += 1
            base[name] = n
            counted.append(name)
        elif kind == "REAL":
            base[name] = 0.0
        elif kind == "BLOB":
            base[name] = b""
        elif name.endswith("_at") or name in ("ts", "day", "at"):
            base[name] = NOW
        elif name == "month":
            base[name] = "2026-10"
        else:
            n += 1
            base[name] = f"odd-{t}-{name}-{n}"
    rows = [dict(base)]
    for _, name, _kind, _notnull, _default, _pk in cols:
        contract = stored_mod.contract_for(t, name)
        if contract is None:
            continue
        for v in contract.odd():
            row = dict(base)
            row[name] = v.to_json()
            rows.append(row)
    went, refused = 0, []
    for i, row in enumerate(rows):
        for k, v in list(row.items()):          # each row its own made-up values (UNIQUE ones)
            if isinstance(v, str) and v.startswith(f"odd-{t}-"):
                row[k] = f"{v}-{i}"
            elif k in counted:
                row[k] = v + i * 100_000
        try:
            if row:
                ctx.store.insert(t, row)
            else:                               # every column has its default
                conn.execute(f'INSERT INTO "{t}" DEFAULT VALUES')
            went += 1
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            refused.append(str(exc)[:120])      # a trigger's or a UNIQUE's no
    if refused:
        ctx.skipped.append(f"{t}: {len(refused)} of {len(rows)} rows refused ({refused[0]})")
    return went


def _all_contracts() -> tuple[type, ...]:
    """Every column's contract (the schema case writes each column's odd values)."""
    stored_mod.load_all()
    return tuple(stored_mod.COLUMNS.values())


ALL_CONTRACTS = _all_contracts()

CASES: list[Case] = [
    Case("topics", "a user topic, a paused one, an archived one, a project topic, one with "
         "no sources", (), topics),
    Case("sources", "every odd value of sources.validation", (Validation,),
         validation_odd_values),
    Case("sources", "a source described without a topic (no similarity)", (Validation,),
         described_without_a_topic),
    Case("sources", "a Parallax import: validation NULL", (Validation,), parallax_import),
    Case("sources", "linked to none, to two, unlinked again, a project's", (), linking),
    Case("sources", "params of each kind", (Params,), params_of_each_kind),
    Case("runs", "ingest summaries [] and {}, a failed run", (), odd_run_summaries),
    Case("ideas", "a card of every odd shape, shown and unsupported, with odd dropped lists",
         (Card, Dropped, InputIds), cards_of_every_shape),
    Case("settings", "every settings blob as its writer stores it; waiting marks; an over-cap"
         " detail; an odd event; the activity mirror with nothing running",
         (*stored_mod.SETTINGS.values(), *stored_mod.FILES.values()), settings_and_marks),
    Case("settings", "the prose profile's two rows at each odd value of their types",
         (ProfileRow, Learned), prose_rows),
    Case("cubs", "a cub of every odd grant, installed, paused and removed, its folder gone",
         (), cubs_of_every_grant),
    Case("features", "News: failed, quiet, NULL steps; the retired Invest and radar rows: a "
         "chain without links", (), features_odd),
    Case("runs", "every odd summary of each typed kind, in each status; a job, a compact run,"
         " an update check", tuple(stored_runs.KINDS.values()), run_summaries_of_every_kind),
    # last: its rows' parents are the cases' rows above
    Case("schema", "every table: every nullable column NULL, every JSON column at each odd value"
         " of its contract", ALL_CONTRACTS, every_table),
]

PROJECTS: list[Case] = [
    Case("topics", "project topics only, no user topic; a feed in each and one in both; an "
         "observation from each; a card citing both", (Card, InputIds), projects_only),
]


def generator_hash() -> str:
    """The generator's source and the contract types': a committed fixture is current while
    this is unchanged."""
    from kranto import stored
    h = hashlib.sha256(Path(__file__).read_bytes())
    for p in sorted(Path(stored.__file__).parent.glob("*.py")):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def upgraded_hash() -> str:
    """What the committed upgraded home was made by: the chain and the per-version writer
    (odd_old.py). This tree's migrations run on it when it is opened, so a later change to the
    schema or the contracts needs no new copy; a change to these does."""
    h = hashlib.sha256(" ".join(CHAIN).encode())
    h.update((Path(__file__).parent / "odd_old.py").read_bytes())
    return h.hexdigest()[:16]


def _migrations(db: Path) -> int:
    import sqlite3
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT key FROM schema_meta WHERE key LIKE 'migration:%'").fetchall()
    return max((int(k.split(":", 1)[1]) for (k,) in rows if k.split(":", 1)[1].isdigit()),
               default=0)


def build_upgraded(home: Path, worktrees: Path) -> dict[str, Any]:
    """The upgraded home: each tag of CHAIN in its own git worktree with its locked
    environment, its odd_old.py writes on the same home, then this tree opens it (the rest of
    the migrations). Returns the manifest (per tag: the migrations after it, what it wrote and
    what it could not)."""
    import shutil
    import subprocess
    if home.exists():
        shutil.rmtree(home)
    config_mod.init_workspace(home)
    db = home / "data" / "kranto.db"
    steps = []
    for tag in CHAIN:
        wt = worktrees / tag
        if not wt.exists():
            subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(wt), tag],
                           check=True, capture_output=True)
        subprocess.run(["uv", "sync", "--locked", "--quiet"], cwd=wt, check=True)
        got = subprocess.run([str(wt / ".venv" / "bin" / "python"), "-I",
                              str(Path(__file__).parent / "odd_old.py"), str(home), tag],
                             capture_output=True, text=True, timeout=600)
        if got.returncode != 0:
            raise RuntimeError(f"{tag}: odd_old.py failed:\n{got.stderr[-2000:]}")
        out = json.loads(got.stdout.strip().splitlines()[-1])
        steps.append({"tag": tag, "migrations": _migrations(db), "wrote": out["wrote"],
                      "skipped": out["skipped"]})
    store = Store.open(db)                      # this tree's migrations, as an update does
    counts = {t: store.query_one(f'SELECT COUNT(*) AS n FROM "{t}"')["n"]
              for t in ("topics", "sources", "runs")}
    store.close()
    manifest = {"variant": "upgraded", "generator": upgraded_hash(), "chain": list(CHAIN),
                "steps": steps, "migrations": _migrations(db), "counts": counts,
                "topics": {}, "sources": {}, "cases": [s["tag"] for s in steps],
                "schema_skipped": []}
    (home / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def build(home: Path, variant: str = "odd") -> dict[str, Any]:
    """Write the variant's library under ``home/data/kranto.db``; return its manifest. The
    upgraded variant is the committed copy (``--upgrade`` makes it), opened by this tree."""
    if variant not in VARIANTS:
        raise ValueError(f"variant is one of {', '.join(VARIANTS)}")
    if variant == "upgraded":
        import shutil
        if home.exists():
            shutil.rmtree(home)
        shutil.copytree(UPGRADED, home)
        Store.open(home / "data" / "kranto.db").close()     # this tree's migrations
        return dict(json.loads((home / "manifest.json").read_text()))
    config_mod.init_workspace(home)          # the default config, as `afk init` writes it
    store = Store.open(home / "data" / "kranto.db")
    ctx = Ctx(store, StubEmbedder())
    for case in CASES if variant == "odd" else PROJECTS if variant == "projects" else []:
        case.write(ctx)
        ctx.written.append(f"{case.area}: {case.name}")
    counts = {t: store.query_one(f'SELECT COUNT(*) AS n FROM "{t}"')["n"]
              for t in ("topics", "sources", "runs")}
    store.close()
    manifest = {"variant": variant, "generator": generator_hash(), "cases": ctx.written,
                "schema_skipped": sorted(set(ctx.skipped)),
                "counts": counts, "topics": ctx.topics, "sources": ctx.sources}
    (home / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--variant", choices=VARIANTS, default="odd")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--upgrade", action="store_true", help="build the upgraded home in --out")
    ap.add_argument("--worktrees", type=Path, help="--upgrade: where the tags' worktrees go")
    a = ap.parse_args(argv)
    if a.upgrade:
        m = build_upgraded(a.out, a.worktrees or a.out.parent / ".worktrees")
        print(f"upgraded: {a.out} (migrations {m['migrations']}; "
              + ", ".join(f"{s['tag']} wrote {len(s['wrote'])}, skipped {len(s['skipped'])}"
                          for s in m["steps"]) + ")")
        return 0
    m = build(a.out, a.variant)
    print(f"{a.variant}: {a.out} ({', '.join(f'{k} {v}' for k, v in m['counts'].items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
