"""The ``afk`` command."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
import time
from pathlib import Path

from . import __version__, library, memory, search, sources
from . import config as config_mod
from .intern import override_lifted
from .llm import pause_words, watch_pause
from .runtime import Runtime, open_runtime
from .store import Store
from .stored.map import RollupKeywords
from .stored.observations import Tags
from .stored.sources import Validation as StoredValidation
from .tick import run_ingest

RESPONSIBLE_USE_URL = "https://github.com/iddv/kranto/blob/main/RESPONSIBLE_USE.md"


class CLIError(Exception):
    pass


def _cfg(args) -> config_mod.Config:
    return config_mod.load(config_mod.find_workspace(args.workspace))


def _store(args) -> tuple[config_mod.Config, Store]:
    cfg = _cfg(args)
    return cfg, Store.open(cfg.db_path)


def _runtime(args) -> Runtime:
    factory = getattr(args, "runtime_factory", None)
    cfg = _cfg(args)
    return factory(cfg) if factory else open_runtime(cfg)


def quiet_http_loggers() -> None:
    """httpx and httpcore held at WARNING (``sources.base.quiet_http_loggers``)."""
    from .sources.base import quiet_http_loggers as quiet

    quiet()


def _short(text: str, width: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 3] + "..."


# -- workspace -------------------------------------------------------------------


def cmd_init(args) -> int:
    path = config_mod.init_workspace(Path(args.directory))
    cfg = config_mod.load(path.parent)
    Store.open(cfg.db_path).close()
    print(f"created {path}")
    print(f"library: {cfg.db_path}")
    print(f"next: export {cfg.llm.api_key_env}=... and add a topic with 'afk topics add'")
    print(f"responsible use: {RESPONSIBLE_USE_URL}")
    return 0


def cmd_pause(args) -> int:
    _, store = _store(args)
    store.pause(args.reason)
    print(f"paused: {args.reason}")
    return 0


def cmd_resume(args) -> int:
    _, store = _store(args)
    store.resume()
    print("resumed")
    return 0


def cmd_status(args) -> int:
    cfg, store = _store(args)
    spent = store.month_spend()
    paused = store.pause_reason()
    obs = store.query_one("SELECT COUNT(*) AS n FROM observations")["n"]
    rollups = store.query_one("SELECT COUNT(*) AS n, COALESCE(SUM(replaced_count), 0) AS r "
                              "FROM rollups")
    last = store.query_one("SELECT status, finished_at, error FROM runs ORDER BY finished_at DESC")
    print(f"workspace:    {cfg.root}")
    print(f"observations: {obs}")
    if rollups["n"]:
        print(f"rollups:      {rollups['n']} (in place of {rollups['r']} compacted observations)")
    print(f"sources:      {len(library.list_sources(store, 'approved'))} approved")
    print(f"spend:        ${spent:.4f} {cfg.budget.of()} this month")
    print(f"paused:       {paused if paused else 'no'}")
    provider_pause = watch_pause(store)
    if provider_pause:
        print(f"provider:     {pause_words(provider_pause)}")
    key_state = ("set" if cfg.llm.api_key() else f"missing (${cfg.llm.key_env})") \
        if cfg.llm.key_env else "none needed"
    print(f"api key:      {key_state}")
    if last:
        print(f"last run:     {last['status']} at {last['finished_at']}"
              + (f" ({last['error']})" if last["error"] else ""))
    return 0


def cmd_export(args) -> int:
    _, store = _store(args)
    if args.table == "bundle":
        from .bundle import export_bundle

        if args.output == "-":
            raise CLIError("a bundle is a directory: pass -o DIR")
        manifest = export_bundle(store, Path(args.output))
        print(f"wrote {manifest['n']} observations in {manifest['k']} clusters to {args.output}")
        return 0
    if args.output == "-":
        count = store.export_jsonl(args.table, sys.stdout)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            count = store.export_jsonl(args.table, fh)
    print(f"exported {count} rows from {args.table}", file=sys.stderr)
    return 0


# -- topics and sources --------------------------------------------------------------


def _print_scout(results) -> None:
    search = results[0].search if results else None
    if search and search.get("live"):
        print(f"from live search: {search['results']} results from "
              f"{', '.join(search['backends'])}, searched {search['searched_at'][:10]}")
    elif search:
        print(search.get("note") or "")
    order = {"approved": 0, "proposed": 1, "no_feed": 2, "invalid": 3}
    for r in sorted(results, key=lambda r: (order.get(r.status, 3),
                                            -(r.validation.median_similarity or 0))):
        v = r.validation
        ident = f"{r.source_id:>4}" if r.source_id else "   -"
        if v.status == "valid":
            sim = "  -  " if v.median_similarity is None else f"{v.median_similarity:.2f}"
            stats = f"sim {sim}  {v.items:>3} items  {v.recent:>3} in 30d"
        else:
            stats = f"{v.status}: {_short(v.error or '', 60)}"
        role = "wildcard" if r.proposal.role == "wildcard" else ""
        print(f"{ident}  {r.status:<9} {r.proposal.kind:<11} {_short(r.label, 34):<34} {stats}"
              + (f"  {role}" if role else ""))
        if r.proposal.why and r.status != "invalid":
            cites = ", ".join(r.proposal.cites)
            source = ("from memory" if r.proposal.from_memory or not cites
                      else f"from {cites}")
            print(f"      {_short(r.proposal.why, 100)} ({source})")


def _scout(rt: Runtime, topic_id: int, approve: bool) -> int:
    from . import websearch
    from .llm import LLMError
    from .scout import scout_topic

    topic = next((t for t in library.active_topics(rt.store) if t.id == topic_id), None)
    if topic is None:
        raise CLIError(f"no active topic {topic_id}")
    searcher = websearch.for_runtime(rt, "scout")
    state = searcher.state()
    names = [state["web_label"]] if state["web"] else []
    names += [websearch.LABELS[b] for b in state["free"]]
    print(searcher.off_reason() or f"searching the live web first ({', '.join(names)})")
    print(f"scouting sources for '{topic.name}' (one {rt.cfg.llm.models['reason']} call, "
          "then a test fetch of each proposal)...")
    threshold = rt.cfg.ingest.prefilter_min_similarity if approve else None
    try:
        results = scout_topic(rt.store, rt.llm, rt.embedder, rt.http, topic,
                              auto_approve_min_similarity=threshold,
                              connections=getattr(rt, "connections", None), xcfg=rt.cfg.x,
                              searcher=searcher)
    except LLMError as exc:
        raise CLIError(f"scouting failed: {exc}") from exc
    if not results:
        raise CLIError("the scout's reply contained no usable proposals; nothing was added "
                       "(the call is recorded in llm_calls)")
    _print_scout(results)
    pending = sum(1 for r in results if r.status == "proposed")
    if pending:
        print(f"\n{pending} proposed; approve with 'afk sources approve <id>'")
    wild = sum(1 for r in results if r.proposal.role == "wildcard" and r.status == "proposed")
    if wild:
        print(f"{wild} of them are wildcards: unrelated to the topic, never auto-approved. "
              "An approved wildcard is watched without the topic prefilter.")
    return 0


def cmd_topics_add(args) -> int:
    rt = _runtime(args)
    try:
        try:
            topic_id, existing = library.add_topic_once(
                rt.store, rt.embedder, args.name, args.description,
                kind=getattr(args, "kind", "user"), ref=getattr(args, "ref", None))
        except ValueError as exc:
            raise CLIError(str(exc)) from exc
        if existing:
            print(f"topic {topic_id} already has ref {args.ref}; nothing added")
            return 0
        print(f"topic {topic_id}: {args.name}")
        if not args.no_scout:
            return _scout(rt, topic_id, args.approve)
    finally:
        rt.close()
    return 0


def cmd_topics_scout(args) -> int:
    rt = _runtime(args)
    try:
        return _scout(rt, args.topic_id, args.approve)
    finally:
        rt.close()


def cmd_topics_edit(args) -> int:
    """A topic's new name or description, as Edit... on its page does (a revision; its id kept)."""
    if args.name is None and args.description is None:
        raise CLIError("say --name, --description or both")
    rt = _runtime(args)
    try:
        try:
            change = library.edit_topic(rt.store, rt.embedder, args.topic_id, name=args.name,
                                        description=args.description, by="cli")
        except ValueError as exc:
            raise CLIError(str(exc)) from exc
    finally:
        rt.close()
    if change is None:
        print(f"topic {args.topic_id}: the same words, nothing changed")
    else:
        print(f"topic {args.topic_id}: {' and '.join(change['changed'])} changed "
              f"(was {change['before']['name']!r})")
    return 0


def cmd_topics_archive(args) -> int:
    """Archive a topic (not read, off the lists, its evidence and cards kept), or restore it."""
    _, store = _store(args)
    status = "active" if args.restore else library.ARCHIVED
    try:
        changed = library.set_topic_status(store, args.topic_id, status, "via afk topics archive")
    except ValueError as exc:
        raise CLIError(str(exc)) from exc
    word = "restored" if args.restore else "archived"
    print(f"topic {args.topic_id} {word}" if changed else f"topic {args.topic_id} was {word}")
    return 0


def cmd_topics_list(args) -> int:
    _, store = _store(args)
    kind = getattr(args, "kind", "user")
    for t in library.active_topics(store):
        if kind not in ("all", t.kind):
            continue
        tag = f"  [{t.ref}]" if t.ref else ""
        print(f"{t.id:>4}  {t.name}{tag}\n      {_short(t.description, 100)}")
    return 0


DESCRIBE_ORDER = ("valid", "unverified", "invalid", "not_found", "refused", "connect_first",
                  "already_proposed", "already_watching")


def cmd_sources_describe(args) -> int:
    """Resolve a pasted list or description of sources: one model call, a
    test fetch of each, recorded as proposals. Approving is a second command (D6)."""
    from . import websearch
    from .llm import LLMError
    from .resolve import resolve_text

    path = args.file if args.file is not None else args.from_text
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    rt = _runtime(args)
    try:
        topic = None
        if args.topic is not None:
            topic = next((t for t in library.active_topics(rt.store) if t.id == args.topic),
                         None)
            if topic is None:
                raise CLIError(f"no active topic {args.topic}")
        if not args.json:
            print(f"resolving {len(text):,} characters (one {rt.cfg.llm.models['reason']} "
                  "call, then a test fetch of each source)...")
        try:
            batch = resolve_text(rt.store, rt.llm, rt.embedder, rt.http, text, topic=topic,
                                 connections=getattr(rt, "connections", None), xcfg=rt.cfg.x,
                                 every_hours=rt.cfg.ingest.every_hours,
                                 searcher=websearch.for_runtime(rt, "resolve"))
        except ValueError as exc:
            raise CLIError(str(exc)) from exc
        except LLMError as exc:
            raise CLIError(f"resolving failed: {exc} (the call is recorded in llm_calls)") \
                from exc
    finally:
        rt.close()
    if args.json:
        print(json.dumps(batch.to_json(), indent=1))
        return 0
    for line in sorted(batch.lines, key=lambda x: DESCRIBE_ORDER.index(x.status)):
        ident = f"{line.source_id:>4}" if line.source_id else "   -"
        cost = f"  X ${line.cost['run']:.2f} a run" if line.cost else ""
        print(f"{ident}  {line.status:<16} {_short(line.label or line.preset or '', 34):<34} "
              f"«{_short(line.from_text, 40)}»{cost}")
        if line.why:
            print(f"      {_short(line.why, 100)}")
    print(f"\n{batch.message()}")
    ready = [str(x.source_id) for x in batch.lines
             if x.status in ("valid", "unverified") and x.source_id]
    if ready:
        print("Approve in Settings › Add source, or: afk sources approve " + " ".join(ready)
              + (f" --topic {args.topic}" if args.topic is not None else ""))
    return 0


def cmd_sources_approve(args) -> int:
    from .resolve import approve

    _, store = _store(args)
    try:
        result = approve(store, args.source_ids, args.topic, strict=False,
                         note=args.note or "approved with afk sources approve")
    except ValueError as exc:
        raise CLIError(str(exc)) from exc
    for source_id in result["approved"]:
        print(f"source {source_id}: approved")
    for s in result["skipped"]:
        print(f"source {s['id']}: not approved: {s['why']}")
    return 0 if not result["skipped"] else 1


def cmd_sources_add(args) -> int:
    if args.from_text is not None:
        if args.topic and len(args.topic) > 1:
            raise CLIError("--from-text takes one --topic")
        args.file, args.topic = None, (args.topic or [None])[0]
        return cmd_sources_describe(args)
    if not args.kind or not args.value:
        raise CLIError("give KIND and VALUE, or --from-text FILE")
    cfg, store = _store(args)
    params = sources.params_from_value(args.kind, args.value)
    http = sources.HTTP()
    try:
        adapter = sources.build(args.kind, params, http)
        validation = None
        if not args.no_check:
            items = adapter.fetch()
            validation = StoredValidation.checked_by("manual", len(items))
            print(f"fetched {len(items)} items from {adapter.label}")
        source_id = library.add_source(
            store, args.kind, params, label=adapter.label, validation=validation
        )
    except sources.SourceError as exc:
        raise CLIError(f"could not fetch {args.kind} {args.value!r}: {exc}") from exc
    finally:
        http.close()
    for topic_id in args.topic or []:
        library.link_topic_source(store, topic_id, source_id)
    print(f"source {source_id}: {adapter.label} (approved)")
    return 0


def cmd_sources_list(args) -> int:
    _, store = _store(args)
    for s in library.list_sources(store, args.status):
        print(f"{s.id:>4}  {s.status or '-':<9} {s.kind:<11} {s.label}")
    return 0


def cmd_sources_set(args) -> int:
    _, store = _store(args)
    known = {s.id for s in library.list_sources(store)}
    if args.source_id not in known:
        raise CLIError(f"no source {args.source_id}")
    store.set_status("source", args.source_id, args.status, args.note)
    print(f"source {args.source_id}: {args.status}")
    return 0


def cmd_sources_forget(args) -> int:
    from .xrecheck import remove_post

    _, store = _store(args)
    target = args.target.strip()
    n = remove_post(store, observation_id=int(target)) if target.isdigit() \
        else remove_post(store, url=target)
    if not n:
        print(f"nothing kept for {target}")
        return 1
    print(f"removed {n} observation{'s' if n != 1 else ''} (recorded in purges: removed at "
          "the person's request)")
    return 0


def cmd_sources_retention(args) -> int:
    from .retention import retention_days, set_source_retention

    cfg, store = _store(args)
    value = args.days.strip().lower()
    if value == "default":
        days = None
    else:
        try:
            days = float(value)
        except ValueError as exc:
            raise CLIError("DAYS must be a number of days (0: keep forever) or 'default'") \
                from exc
    try:
        set_source_retention(store, args.source_id, days, args.note)
    except ValueError as exc:
        raise CLIError(str(exc)) from exc
    effective = retention_days(store, cfg.retention)[args.source_id]
    print(f"source {args.source_id}: observations kept "
          + (f"{effective:g} days" if effective > 0 else "forever")
          + (" (the default for its kind)" if days is None else ""))
    return 0


# -- running and reading ----------------------------------------------------------------


def _after_job(rt: Runtime) -> None:
    """The gate and delivery follow every job, from cron as from the scheduler."""
    from .delivery import after_job

    decisions, report = after_job(rt.cfg, rt.store)
    promoted = sum(1 for d in decisions if d.promoted)
    if decisions:
        print(f"strike gate: {len(decisions)} candidates decided, {promoted} promoted")
    if report.attempted:
        print(f"delivery: {report.sent} sent, {report.failed} failed")
    if report.note and "no targets" not in report.note:
        print(f"delivery: {report.note}")


def _run_progress(out=None, clock=time.monotonic):
    """``afk run``'s progress lines, to stderr (stdout keeps the report): each source as it
    starts and once its new items are known, then every 10 items or 30 s."""
    out = out or sys.stderr
    t0 = clock()
    last = {"at": t0, "key": None}

    def show(p) -> None:
        now = clock()
        head = f"[{p.source_index}/{p.sources}] {_short(p.source or '', 40)}"
        if p.items is None:
            line = f"{head}: reading"
        elif p.item == 0:
            line = f"{head}: {p.items} new item{'s' if p.items != 1 else ''} to read"
        elif p.item % 10 == 0 or now - last["at"] >= 30:
            line = f"{head}: {p.item} of {p.items} items"
        else:
            return
        key = (p.source_index, p.items, p.item)
        if key == last["key"]:
            return
        last.update(at=now, key=key)
        m, s = divmod(int(now - t0), 60)
        print(f"{line}; {p.done_items} read and {p.kept} kept so far, {m}m{s:02d}s",
              file=out, flush=True)

    return show


def cmd_run(args) -> int:
    from .delivery import ping_heartbeat

    memory.enter_scope("afk run")
    rt = _runtime(args)
    try:
        report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                            connections=rt.connections, on_progress=_run_progress())
        ping_heartbeat(rt.cfg, report.status)
        _after_job(rt)
    finally:
        rt.close()
    for s in report.sources:
        if s.not_reached:
            print(f"{_short(s.label, 32):<32} not reached (run stopped)")
            continue
        line = (f"{_short(s.label, 32):<32} fetched={s.fetched} new={s.new} "
                f"prefiltered={s.prefiltered} judged={s.judged} contributed={s.contributed} "
                f"gated={s.gated} skipped={s.skipped}")
        if s.duplicates:
            line += f" duplicates={s.duplicates}"
        if s.near_duplicates or s.linked:
            line += f" near_duplicates={s.near_duplicates} linked={s.linked}"
        if s.removed or s.stale:
            line += f" removed={s.removed} stale={s.stale}"
        if s.explored:
            line += f" explored={s.explored}"
        if s.screened:
            line += f" screened={s.screened} screened_out={s.screened_out}"
        if s.looked or s.look_capped:
            line += (f" looked={s.looked} gathered={s.gathered} children={s.children}"
                     + (f" look_capped={s.look_capped}" if s.look_capped else ""))
        if s.override_set:
            line += (f" override={s.override_set}/{s.rated} lifted={s.override_lifted}"
                     f" refused={s.override_refused}")
        if s.sponsored or s.sponsor_links:
            line += f" sponsored={s.sponsored} sponsor_links={s.sponsor_links}"
        if s.no_content:
            line += f" no_content={s.no_content}"
        if s.deferred:
            line += f" deferred={s.deferred}"
        errors = s.llm_errors + s.item_errors + s.parse_failed
        if errors:
            line += f" errors={errors}"
        if s.fetch_error:
            line += f" FETCH ERROR: {s.fetch_error}"
        print(line)
    print(f"run {report.run_uuid[:8]} {report.status}: {report.contributed} new observations, "
          f"${report.spend_usd:.4f}" + (f" ({report.error})" if report.error else ""))
    return 1 if report.status == "failed" else 0


def _print_rows(rows) -> None:
    for r in rows:
        print(f"{r['id']:>6}  {r['created_at'][:10]}  {r['signal']:.2f}  "
              f"{_short(r['label'] or '', 18):<18}  {_short(r['summary'], 90)}")


def cmd_list(args) -> int:
    _, store = _store(args)
    where, params = ["1 = 1"], []
    if args.source:
        where.append("o.source_id = ?")
        params.append(args.source)
    if args.min_signal is not None:
        where.append("o.signal >= ?")
        params.append(args.min_signal)
    rows = store.query(
        f"""SELECT o.id, o.created_at, o.signal, o.summary, s.label FROM observations o
            LEFT JOIN sources s ON s.id = o.source_id WHERE {' AND '.join(where)}
            ORDER BY o.id DESC LIMIT ?""",
        (*params, args.limit),
    )
    _print_rows(rows)
    return 0


def cmd_search(args) -> int:
    rt = _runtime(args)
    try:
        hits = search.search(rt.index, rt.embedder, args.query, args.k)
        if not hits and not rt.store.query_one("SELECT 1 FROM rollups LIMIT 1"):
            print("the library is empty")
            return 0
        if search.off_topic(hits):
            best = search.floor2(max(h.score for h in hits))
            print(f"the library may not cover this (closest {best:.2f}, below "
                  f"{search.OFF_TOPIC_BELOW:.2f}, as close as unrelated queries get); "
                  "showing the nearest anyway\n")
        for hit in hits:
            r = rt.store.query_one(
                "SELECT o.summary, s.label FROM observations o "
                "LEFT JOIN sources s ON s.id = o.source_id WHERE o.id = ?", (hit.observation_id,),
            )
            print(f"{hit.observation_id:>6}  {hit.score:.3f}  "
                  f"{_short(r['label'] or '', 18):<18}  {_short(r['summary'], 80)}")
        rollups = search.search_rollups(rt.index, rt.embedder, args.query, k=3)
        if rollups:
            print("\ncompacted weeks (rollups; similarity to a centroid, not to one observation):")
        for hit in rollups:
            r = rt.store.query_one("SELECT * FROM rollups WHERE id = ?", (hit.rollup_id,))
            if r is None:                       # compacted again since the index was built
                continue
            words = ", ".join(map(str, RollupKeywords.load(r["keywords"]).items[:3]))
            label = r["name"] or words or f"rollup {r['id']}"
            print(f"  r{r['id']:<5} {hit.score:.3f}  {r['period_start'][:10]}  "
                  f"{r['size']:>4} obs  {_short(label, 40)}")
            if r["summary"]:
                print(textwrap.fill(r["summary"], 100, initial_indent="         ",
                                    subsequent_indent="         "))
    finally:
        rt.close()
    return 0


def cmd_websearch(args) -> int:
    """``afk websearch``: the live web, dated (the owner's check that a backend works)."""
    from . import websearch

    rt = _runtime(args)
    try:
        backends = tuple(b for b in (args.backend or "").split(",") if b) or None
        try:
            results = websearch.for_runtime(rt).search(
                args.query, recency=args.recency, kind=args.kind, n=args.n, backends=backends)
        except ValueError as exc:
            print(f"afk websearch: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(results.to_dict(), indent=2))
            return 0
        if not results.live:
            print(results.note)
            return 1
        print(f"searched {results.searched_at[:10]} with {', '.join(results.labels)}"
              + (" (cached)" if results.cached else ""))
        if results.note:
            print(f"note: {results.note}")
        for label, hit in results.numbered():
            print(f"[{label}] {hit.date or 'undated':<10}  {_short(hit.title, 70)}")
            print(f"{'':>10}{hit.url}")
        if not results.hits:
            print("no results")
    finally:
        rt.close()
    return 0


def cmd_show(args) -> int:
    cfg, store = _store(args)
    r = store.query_one(
        "SELECT o.*, s.label FROM observations o LEFT JOIN sources s ON s.id = o.source_id "
        "WHERE o.id = ?", (args.observation_id,),
    )
    if r is None:
        hint = (" (observations past their retention age are compacted into rollups; "
                "'afk search' finds those)"
                if store.query_one("SELECT 1 FROM purges LIMIT 1") else "")
        raise CLIError(f"no observation {args.observation_id}{hint}")
    print(f"#{r['id']}  {r['kind']}  signal {r['signal']:.3f} = "
          f"{r['content_quality']:.2f} x {r['durability']:.2f} x {r['opportunity']:.2f}"
          + ("  OVERRIDE: " + r["override_reason"]
             if override_lifted(r, cfg.ingest.signal_threshold) else ""))
    print(f"source:  {r['label']}  ({r['admitted_by']})")
    print(f"url:     {r['source_url']}")
    print(f"title:   {r['title']}")
    print(f"excerpt: {r['source_excerpt']}\n")
    print(textwrap.fill(r["summary"], 100))
    print()
    print(textwrap.fill("Why: " + r["why_it_matters"], 100))
    tags = Tags.load(r["tags"]).items
    if tags:
        print(f"\ntags: {', '.join(tags)}")
    from .library import children_of, parent_of

    parent = parent_of(store, r["id"])
    if parent is not None:
        print(f"\nread one step from #{parent['id']} ({parent['relation']}): "
              f"{_short(parent['title'] or parent['summary'], 80)}")
    children = children_of(store, r["id"])
    if children:
        print("\none step away:")
        for c in children:
            print(f"  #{c['id']} {c['relation']:<10} signal {c['signal']:.3f}  "
                  f"{_short(c['title'] or c['summary'], 70)}")
    if args.raw and r["llm_call_id"]:
        call = store.query_one("SELECT * FROM llm_calls WHERE id = ?", (r["llm_call_id"],))
        print(f"\n--- llm call {call['id']} ({call['model']}, {call['prompt_version']}, "
              f"${call['cost_usd'] or 0:.5f}) ---")
        print(call["response"])
    return 0


def cmd_snapshot(args) -> int:
    from .map.snapshot import take_snapshot

    rt = _runtime(args)
    try:
        print("clustering the library (UMAP takes a minute on large libraries)...")
        report = take_snapshot(rt.store, rt.embedder, rt.llm, force=args.force,
                               stories_cfg=rt.cfg.stories)
        _after_job(rt)
    finally:
        rt.close()
    if report.status != "ok":
        print(f"snapshot {report.status}: {report.error}")
        return 0 if report.status == "skipped" else 1
    q = report.quality
    null = q["structure_null"]
    print(f"snapshot {report.snapshot_id}: {report.n} observations, k={report.k} "
          f"({report.continued_lineages} lineages continued, {report.new_lineages} new)")
    print(f"silhouette {q['silhouette_umap']:.3f} (10-d UMAP), {q['silhouette_native']:.3f} "
          f"(original space); structure-free null {null['null_mean']:.4f} "
          f"+/- {null['null_sd']:.4f} vs {null['real']:.4f}")
    if null.get("covariance_z") is not None:
        verdict = ("clusters above a single blob" if null["clustered"] else
                   "NOT clearly above a single blob: browse by it, do not read themes into it")
        print(f"single-blob null {null['covariance_null_mean']:.4f} "
              f"+/- {null['covariance_null_sd']:.4f}, z = {null['covariance_z']}: {verdict}")
    names = f"names: {report.names_generated} new, {report.names_reused} reused"
    if report.names_failed:
        names += f", {report.names_failed} failed"
    if report.names_skipped:
        names += f" (skipped: {report.names_skipped})"
    print(names)
    return 0


def cmd_compact(args) -> int:
    from .retention import compact

    rt = _runtime(args)
    try:
        report = compact(rt.store, rt.cfg.retention, rt.llm, stories_cfg=rt.cfg.stories,
                         activity_cfg=rt.cfg.activity)
        _after_job(rt)
    finally:
        rt.close()
    removed = ", ".join(f"{n} {t}" for t, n in report.removed.items() if n) or "nothing"
    print(f"compact {report.status}: {report.expired} observations past their retention age, "
          f"{report.periods} weeks, {report.rollups} rollups ({report.summaries_written} "
          f"summarised); removed {removed}"
          + (f" ({report.error})" if report.error else ""))
    if report.summaries_skipped:
        print(f"summaries skipped: {report.summaries_skipped}")
    return 1 if report.status == "failed" else 0


def cmd_ideas(args) -> int:
    from . import websearch
    from .ideate.cards import generate_ideas

    rt = _runtime(args)
    try:
        report = generate_ideas(rt.store, rt.llm, max_cards=args.max or
                                rt.cfg.ideas.max_cards_per_run, force=args.force,
                                archive_evidence=rt.cfg.parallax.card_evidence,
                                project_topics=rt.cfg.ideas.project_topics,
                                searcher=websearch.for_runtime(rt, "cards"),
                                grading=rt.cfg.grading)
        _after_job(rt)
    finally:
        rt.close()
    print(f"ideas {report.status}: {report.shown} shown, {report.unsupported} with unsupported "
          f"evidence, {report.declined} declined, {report.malformed} malformed, "
          f"{report.already_carded} candidates already carded"
          + (f" ({report.error})" if report.error else ""))
    for s in report.taste_skipped:
        print(f"  left out: {s['name'] or s['lineage_id']} ({s['why']})")
    return 1 if report.status == "failed" else 0


def cmd_ideas_card(args) -> int:
    """One card on one theme now (the owner's D-1): one card call and its check."""
    from . import websearch
    from .ideate.cards import card_theme

    rt = _runtime(args)
    try:
        report = card_theme(rt.store, rt.llm, args.lineage,
                            archive_evidence=rt.cfg.parallax.card_evidence,
                            searcher=websearch.for_runtime(rt, "cards"))
        _after_job(rt)
    finally:
        rt.close()
    words = ("carded: #" + ", #".join(map(str, report.idea_ids)) if report.idea_ids
             else "already carded with this evidence" if report.already_carded
             else "the model declined" if report.declined else "no card")
    print(f"card {report.status}: {words}" + (f" ({report.error})" if report.error else ""))
    return 1 if report.status == "failed" else 0


def cmd_ideas_list(args) -> int:
    from .ideate.cards import list_ideas

    cfg, store = _store(args)
    for i in list_ideas(store, include_unsupported=args.all, grading=cfg.grading):
        c = i["card"]
        verdict = f"  [{i['verdict']}]" if i["verdict"] else ""
        print(f"#{i['id']}  {i['score']:.3f}  {i['origin']:<12} {c.title or ''}{verdict}")
        if i["rank"] is not None and i["rank"].line and not i["verdict"]:
            print(f"      {i['rank'].line}")
        print(textwrap.fill(c.thesis or "", 100, initial_indent="      ",
                            subsequent_indent="      "))
        cites = ", ".join(f"#{oid}" for oid in c.cited_ids())
        print(f"      evidence: {cites}\n")
    return 0


def cmd_ideas_grade(args) -> int:
    from .ideate.cards import grade

    _, store = _store(args)
    grade(store, args.idea_id, args.verdict, args.note)
    print(f"idea {args.idea_id}: {args.verdict}")
    return 0


def cmd_explain(args) -> int:
    from .ideate.explain import ExplainError, explain_neighbourhood
    from .llm import LLMError

    rt = _runtime(args)
    try:
        syn = explain_neighbourhood(rt.store, rt.llm, rt.index, args.observation_id)
    except (ExplainError, LLMError) as exc:
        raise CLIError(str(exc)) from exc
    finally:
        rt.close()
    print(textwrap.fill(syn.text, 100))
    print("\n" + "  ".join(f"[{n}] #{oid}" for n, oid in enumerate(syn.input_ids, 1))
          + ("  (cached)" if syn.cached else ""))
    return 0


def cmd_messages(args) -> int:
    from . import notify

    _, store = _store(args)
    for m in notify.recent_messages(store, args.limit, args.kind):
        print(f"{m['created_at']}  {m['kind']:<9} {m['title']}")
        print(textwrap.fill(m["body"], 100, initial_indent="    ", subsequent_indent="    "))
    return 0


def cmd_strikes(args) -> int:
    from . import delivery, gate

    cfg, store = _store(args)
    if args.run:
        decisions, report = delivery.after_job(cfg, store)
        print(f"strike gate: {len(decisions)} candidates decided, "
              f"{sum(1 for d in decisions if d.promoted)} promoted")
        print(f"delivery: {report.sent} sent, {report.failed} failed"
              + (f" ({report.note})" if report.note else ""))
        for error in report.errors:
            print(f"  {error}")
    pending = gate.pending(store)
    if pending:
        print(f"{len(pending)} candidates not yet gated")
    for d in gate.recent_decisions(store, limit=args.limit):
        threshold = f"{d['threshold']:.3f}" if d["threshold"] is not None else "-"
        print(f"{d['decided_at'][:16]}  {d['origin']:<5} {d['score']:.3f}/{threshold}  "
              f"{d['reason']:<15} {_short(d['title'], 60)}")
        if args.verbose:
            print(f"      {d['detail']}")
    print(f"delivery {delivery.describe(cfg)}")
    return 0


def cmd_heartbeat(args) -> int:
    from . import delivery
    from .heartbeat import send_heartbeat
    from .scheduler import Job, is_due
    from .store import utcnow

    cfg, store = _store(args)
    job = Job("heartbeat", cfg.notify.heartbeat_every_hours, lambda: None)
    if not args.now and not is_due(store, job, utcnow()):
        print("the heartbeat is not due yet; pass --now to send it anyway")
        return 0
    delivery.after_job(cfg, store)  # gate first, so the heartbeat counts this week's decisions
    report = send_heartbeat(store, cfg)
    if report.already_sent:
        print(f"this week's heartbeat ({report.heartbeat.stats['week']}) was already sent")
    else:
        print(report.heartbeat.title)
        print(report.heartbeat.body)
    _, delivered = delivery.after_job(cfg, store)
    if delivered.attempted or (delivered.note and "no targets" not in delivered.note):
        print(f"delivery: {delivered.sent} sent, {delivered.failed} failed"
              + (f" ({delivered.note})" if delivered.note else ""))
    return 0


def cmd_grade(args) -> int:
    from .feedback import KEPT, NOT_KEPT
    from .grades import add_grade

    if args.target not in KEPT:             # builds, themes, messages, sources: 
        print(NOT_KEPT, file=sys.stderr)
        return 2
    _, store = _store(args)
    add_grade(store, args.target, args.target_id, args.grade, args.note)
    print(f"{args.target} {args.target_id}: {args.grade}")
    return 0


def cmd_pack(args) -> int:
    from .packs import load_pack

    rt = _runtime(args)
    try:
        report = load_pack(rt.store, rt.embedder, rt.http, Path(args.file),
                           check=not args.no_check)
    finally:
        rt.close()
    print(f"topics: {', '.join(report.topics) or 'none (broad sources only)'}")
    print(f"{len(report.added)} sources approved: {', '.join(report.added)}")
    for what, why in report.failed:
        print(f"  skipped {what}: {why}")
    return 0


def cmd_provider_show(args) -> int:
    from . import providers
    root = config_mod.find_workspace(args.workspace)
    found = providers.detect(root)
    found["last_call"] = _last_call(root)
    if args.json:
        print(json.dumps(found, indent=2))
        return 0
    cur = found["current"] or {}
    print(f"watching with: {cur.get('label')} ({cur.get('provider')}"
          + (f" at {cur['endpoint']}" if cur.get("endpoint") else "")
          + f"); judge {cur.get('models', {}).get('judge')}, reason "
          f"{cur.get('models', {}).get('reason')}; key "
          f"{'set' if cur.get('key_set') else 'missing'}")
    last = found["last_call"]
    if last:
        print(f"last call: {last['provider']} ({last['model']}) at {last['at']}")
    for name in providers.KEY_CHOICES:          # Claude Code's row, with no key, follows
        row = found[name]
        where = f" at {row['base_url']}" if row.get("base_url") else ""
        print(f"  {row['label']:<18} ${row['env']} {'set' if row['key_set'] else 'not set'}{where}")
    cc = found["claude_code"]
    print(f"  {'Claude Code':<18} " + (
        f"{cc['version']}, {'signed in' if cc['logged_in'] else 'not signed in'}"
        if cc["installed"] else "not installed")
        + ("" if cc["offered"] else " (not offered as the watcher's model in this release)"))
    if cc["offered"]:
        print(f"    {cc['terms']}")
    return 0


def _last_call(root) -> dict | None:
    """The ledger's newest call (``providers.last_call``), from a library that exists."""
    from . import providers
    try:
        path = config_mod.load(root, dotenv=False).db_path
    except config_mod.ConfigError:
        return None
    if not path.exists():
        return None
    store = Store.open(path)
    try:
        return providers.last_call(store)
    finally:
        store.close()


def cmd_provider_test(args) -> int:
    """Test a provider's key as it is set (environment or the workspace's .env); spends
    nothing. The key is never taken on the command line."""
    from . import providers
    root = config_mod.find_workspace(args.workspace)
    name = args.provider or providers.detect(root)["current"]["provider"]
    result = providers.test(name, base_url=args.base_url, root=root)
    print(f"{providers.LABELS.get(name, name)}: {'ok' if result.ok else 'FAILED'}: "
          f"{result.detail}")
    return 0 if result.ok else 1


def cmd_provider_xai(args) -> int:
    """The xAI key for X search through Grok (never the watcher's model): test it, and with
    --key-stdin keep it in the workspace's .env (0600). Spends nothing."""
    from . import providers, setup
    root = config_mod.find_workspace(args.workspace)
    key = sys.stdin.readline().strip() if args.key_stdin else None
    try:
        result = providers.xai_key(root, key)
    except setup.SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"xAI (Grok), for X search only: {'ok' if result['ok'] else 'FAILED'}: "
          f"{result['detail']}")
    if result["changed"]:
        print(f"written: XAI_API_KEY in {root / '.env'} (mode 600); restart Kranto for the "
              "running server to use it")
    return 0 if result["ok"] else 1


def cmd_provider_openai(args) -> int:
    """The OpenAI key for a post writer's own model (never the watcher's): test it, and with
    --key-stdin keep it in the workspace's .env (0600). Spends nothing. The writer's model is
    then set with the verb prose.voice (writer_model, provider "openai")."""
    from . import providers, setup
    root = config_mod.find_workspace(args.workspace)
    key = sys.stdin.readline().strip() if args.key_stdin else None
    try:
        result = providers.openai_key(root, key)
    except setup.SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"OpenAI, for a writer's own model only: {'ok' if result['ok'] else 'FAILED'}: "
          f"{result['detail']}")
    if result["changed"]:
        print(f"written: OPENAI_API_KEY in {root / '.env'} (mode 600); restart Kranto for the "
              "running server to use it")
    return 0 if result["ok"] else 1


def cmd_provider_use(args) -> int:
    """Make a provider the watcher's: test, then write llm.provider, the tiers' models and,
    with --key-stdin, the key into the workspace's .env (0600)."""
    from . import providers, setup
    root = config_mod.find_workspace(args.workspace)
    if args.provider == "claude_code" and not args.accept_terms:
        print(f"{providers.CLAUDE_CODE_TERMS}\nTo choose it anyway: afk provider use claude_code "
              "--accept-terms", file=sys.stderr)
        return 2
    key = sys.stdin.readline().strip() if args.key_stdin else None
    try:
        result = providers.choose(root, args.provider, key=key, base_url=args.base_url,
                                  terms=args.accept_terms)
    except setup.SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{providers.LABELS.get(args.provider, args.provider)}: "
          f"{'ok' if result['ok'] else 'FAILED'}: {result['test']['detail']}")
    if not result["ok"]:
        return 1
    m = result["models"]
    print(f"written: llm.provider {args.provider}, judge {m['judge']}, reason {m['reason']}"
          + (f", base_url {result['base_url']}" if result["base_url"] else "")
          + (f"; the key is in {root / '.env'} (readable by you only)" if key else "")
          + ("" if result["changed"] else " (nothing changed)"))
    print("a running server takes it at its next start; Settings › Watching changes it at once")
    return 0


def cmd_provider_replay(args) -> int:
    """ 6: this library's newest screens and judges asked again through the Claude
    API, in three variants; says what the numbers support. Spends up to --max-usd."""
    from .providers import replay
    cfg, store = _store(args)
    samples = replay.sample(store, args.screens, args.judges)
    if not samples:
        print("no recorded screens or judges to replay yet", file=sys.stderr)
        return 1
    model = replay.variant_config(cfg, "plain").models["judge"]
    est = replay.estimate(samples, model)
    print(f"{len(samples)} recorded calls x {len(replay.VARIANTS)} variants on {model}: at most "
          f"${est:.4f} (cap ${args.max_usd:.2f}); every call is recorded and counted")
    if est > args.max_usd:
        print("over the cap: lower --screens/--judges or raise --max-usd", file=sys.stderr)
        return 2
    if not args.yes and input("go on? [y/N] ").strip().lower() not in ("y", "yes"):
        return 1
    out = replay.summary(replay.run(cfg, store, samples))
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    for name, r in out["variants"].items():
        print(f"{name:<11} screens {r['screens_agree'][0]}/{r['screens_agree'][1]}, judges kept "
              f"{r['judges_agree'][0]}/{r['judges_agree'][1]} (exact "
              f"{r['judges_exact'][0]}/{r['judges_exact'][1]}); cache read "
              f"{r['cache_read_per_call']}, in {r['input_per_call']}, out "
              f"{r['output_per_call']} tokens a call; ${r['usd_per_call']:.6f} a call, "
              f"${r['usd_total']:.4f} in all; p50 {r['latency_p50_ms']} ms; errors {r['errors']}")
    for line in out["supports"] or ["nothing to change: keep the defaults"]:
        print(f"supports: {line}")
    return 0


def cmd_doctor(args) -> int:
    from . import doctor

    cfg, store = _store(args)
    checks = doctor.run(cfg, store, check_embedder=not args.skip_embedder)
    for c in checks:
        print(f"{c.status:<5} {c.name:<14} {c.detail}")
    return 1 if any(c.status == doctor.FAIL for c in checks) else 0


def cmd_import(args) -> int:
    if args.format == "parallax-dispatches":
        return _import_dispatches(args)
    from .importers import import_parallax, import_parallax_themes

    cfg, store = _store(args)
    snapshot = Path(args.snapshot) if args.snapshot else None
    report = import_parallax(store, [Path(p) for p in args.paths], snapshot=snapshot,
                             stories=cfg.stories)
    print(f"{report.files} files, {report.read} records: {report.imported} imported, "
          f"{report.already_present} already present")
    for reason, n in sorted(report.skipped.items()):
        print(f"  skipped {n}: {reason}")
    if report.snapshot:
        s = report.snapshot
        print(f"snapshot: {s['snapshot']} observations; {s['in_both']} in the records, "
              f"{s['snapshot_only']} only in the snapshot (not imported: no ratings there), "
              f"{s['records_only']} records not in the snapshot; "
              f"{s['embeddings_differ']} embeddings differ")
        t = import_parallax_themes(store, snapshot,
                                   history_dir=Path(args.history) if args.history else None)
        print(f"themes ({t.bundle}): {t.written} written, {t.already_present} already present, "
              f"of {t.lineages} lineages; {t.alive} alive, {t.named} named, "
              f"{t.members} members")
    days = cfg.retention.days_for_kind("parallax")
    print("retention for the archive: " + ("kept forever" if days <= 0 else
                                           f"{days:g} days (retention.by_kind.parallax)"))
    return 0


def _import_dispatches(args) -> int:
    from .ideate.dispatches import import_dispatches

    if len(args.paths) != 1 or not Path(args.paths[0]).is_dir():
        print("give the dispatches directory (parallax-dispatches/dispatches)", file=sys.stderr)
        return 2
    _, store = _store(args)
    report = import_dispatches(store, Path(args.paths[0]), only=args.only or None,
                               limit=args.limit)
    for o in report.outcomes:
        if o.status == "lacking":
            print(f"{o.dispatch_id}  lacks the pitches: {o.detail}")
            continue
        print(f"{o.dispatch_id}  {o.status}: {o.title}")
        for c in o.cards:
            line = f"  #{c['idea_id']} {c['kind']:<10} {c['status']}"
            if c.get("new"):
                line += f", {c['citations']} citations: {c['title']}"
            print(line)
    print(f"{report.read} dispatches read: {report.carded} carded, {report.already} already "
          f"carded, {report.lacking} lacking the pitches; {report.cards} cards written "
          f"({report.shown} shown, {report.unsupported} unsupported); {report.matched} of "
          f"{report.links} links matched an observation")
    if report.skip_records:
        print(f"{len(report.skip_records)} skip records (runs that wrote no dispatch): "
              + ", ".join(report.skip_records))
    return 0


def _serve(app, stop, *, host: str, port: int) -> None:
    """uvicorn's server, its signal handler also beginning Kranto's stop (``stopping.py``): the
    scheduler hears SIGTERM at once, not after the open requests drain. Open requests get
    ``HTTP_GRACE_S``: a page's live feed and Open in Claude Code's terminal never end by
    themselves, and uvicorn waits for every open response before it stops."""
    import signal

    import uvicorn

    from . import stopping

    class Server(uvicorn.Server):
        def handle_exit(self, sig, frame) -> None:
            super().handle_exit(sig, frame)
            stop.begin(signal.Signals(sig).name)

    server = Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                   timeout_graceful_shutdown=stopping.HTTP_GRACE_S))
    server.run()
    if not server.started:
        sys.exit(3)                     # as uvicorn.run: the server could not start


def _cubs_gc(rt) -> dict:
    """The daily ``cubs.gc``, its run recorded as every job's is (due-ness reads runs)."""
    from .core.context import record_run
    from .store import utcnow
    started = utcnow()
    out = rt.cubs.gc() if rt.cubs is not None else {}
    record_run(rt.store, "cubs.gc", "ok", started, out)
    return out


def _idle_embedder(rt) -> None:
    """A scheduler tick: the embedding model is let go after ``embed.IDLE_SECONDS`` unused,
    and its memory handed back (memory.py)."""
    drop = getattr(rt.embedder, "drop_if_idle", None)
    if drop is not None and drop():
        memory.release()


def early_briefs(rt):
    """The read's ``on_progress`` under ``kranto serve``: once a topic in
    its first read has kept ``EARLY_KEPT`` items, News writes its first brief from them, between
    two items of the read, and the read goes on. It runs in the read's own thread, so it never
    runs beside it (the scheduler runs one job at a time; the read holds its lock throughout).
    One that fails is logged and the read goes on; the first read's own brief still follows."""
    import logging

    from . import activity
    from .core import registry
    from .core import settings as feature_settings
    from .core.context import record_run
    from .features.news import brief
    from .progress import read_counts
    from .store import utcnow

    seen = {"kept": -1}

    def hook(p) -> None:
        if p.kept < brief.EARLY_KEPT or p.kept == seen["kept"]:
            return
        seen["kept"] = p.kept
        try:
            news = registry.by_id("news")
            if not registry.enabled(rt.cfg, news) or not feature_settings.section(
                    rt.cfg, "news").get("news.enabled", True):
                return
            kept = {t: c["kept"] for t, c in read_counts(rt.store, p.run_uuid).items()}
            if not any(k >= brief.EARLY_KEPT for k in kept.values()):
                return
            ctx = registry.context(rt, news, run_uuid=activity.run_uuid("news.brief"))
            started = utcnow()
            summary = brief.run_early(ctx, kept)
            status = summary.pop("status", "ok")
            if status != "skipped":
                record_run(rt.store, "news.brief", status, started, summary, None,
                           run_uuid=ctx.run_uuid)
        except Exception:  # noqa: BLE001 - the read goes on; the first read's brief follows
            logging.getLogger("kranto.news").exception("the early first brief failed")

    return hook


def server_jobs(rt, *, update_job: bool = False, port: int | None = None) -> list:
    """The scheduler's jobs under ``kranto serve`` (``afk serve`` without ``update_job``):
    the server's own, the update check and the usage reports, the features', the cubs'
    sweep. Every one is a run; the tests walk this list."""
    from . import websearch
    from .delivery import notifying, ping_heartbeat
    from .heartbeat import send_heartbeat
    from .ideate.cards import generate_ideas
    from .map.snapshot import take_snapshot
    from .retention import compact
    from .scheduler import Job
    from .xrecheck import run_recheck

    def ingest():
        report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                            connections=rt.connections, on_progress=early_briefs(rt))
        ping_heartbeat(rt.cfg, report.status)
        if rt.connections is not None:
            rt.connections.cleanup()  # sign-ins older than an hour
        return report

    # Each job is followed by the strike gate and delivery (notifying);
    # compaction follows the snapshot, so the map it leaves was drawn with
    # everything; the heartbeat runs last so it sees what the others decided.
    jobs = [
        Job("ingest", rt.cfg.ingest.every_hours, notifying(rt.cfg, rt.store, ingest)),
        Job("snapshot", rt.cfg.map.every_hours, notifying(
            rt.cfg, rt.store, lambda: take_snapshot(rt.store, rt.embedder, rt.llm,
                                                  stories_cfg=rt.cfg.stories))),
        Job("compact", rt.cfg.retention.every_hours, notifying(
            rt.cfg, rt.store, lambda: compact(rt.store, rt.cfg.retention, rt.llm,
                                              stories_cfg=rt.cfg.stories,
                                              activity_cfg=rt.cfg.activity))),
        # kept X posts deleted on X leave the library; skipped, at no
        # cost, without X posts or a connection
        Job("xrecheck", rt.cfg.x.recheck_days * 24
            if rt.cfg.x.recheck_max and rt.cfg.x.recheck_days else 0,
            lambda: run_recheck(rt.cfg, rt.store, rt.connections, rt.http)),
        Job("ideas", rt.cfg.ideas.every_hours, notifying(
            rt.cfg, rt.store, lambda: generate_ideas(
                rt.store, rt.llm, max_cards=rt.cfg.ideas.max_cards_per_run,
                archive_evidence=rt.cfg.parallax.card_evidence,
                project_topics=rt.cfg.ideas.project_topics,
                searcher=websearch.for_runtime(rt, "cards"), grading=rt.cfg.grading))),
        Job("heartbeat", rt.cfg.notify.heartbeat_every_hours, notifying(
            rt.cfg, rt.store, lambda: send_heartbeat(rt.store, rt.cfg, after_first_read=True))),
    ]
    if update_job:
        # kranto serve: the daily update check (section 3); no model, one
        # GitHub request
        from .paths import loop_home
        from .update.check import make_job

        jobs.append(make_job(rt.cfg.root, rt.store, rt.cfg.update.check_every_hours,
                             port=port, loop_home=loop_home(rt.cfg.brb.loop_home)
                             if rt.cfg.brb.enabled else None))
        # usage reports: counted here unless off; sent by this job only when
        # the person chose basic or detailed (to the controller's relay by default)
        from . import telemetry
        from .telemetry import send as telemetry_send

        telemetry.configure(rt.cfg.root)
        from .telemetry import errors as telemetry_errors
        telemetry_errors.start(rt.cfg.root)   # error reports, within minutes, with consent
        jobs.append(telemetry_send.make_job(rt.cfg.root, rt.store, lambda: rt.cfg))
        try:
            from kranto.page.host_api import telemetry_sink
            telemetry_sink(telemetry.record)
        except (ImportError, AttributeError):
            pass                                 # a the page without it records nothing
    # the features' jobs, each off while its feature is; the bus's
    # delivery after every round of jobs
    from .core import registry as features
    features.check()
    features.pin(rt.store)
    jobs += features.jobs(lambda: rt)
    # the cub runtime's daily sweep; the cubs' own jobs come
    # and go as they are installed, so the scheduler reads them every tick
    jobs.append(Job("cubs.gc", 24, lambda: _cubs_gc(rt)))
    # every cub's update looked for daily; a safe one applied by itself (step 5)
    from .core.cubs import updates as cub_updates
    jobs.append(Job(cub_updates.KIND, 24, lambda: cub_updates.run(rt)))
    # the numbers of the posts Kranto sent, read once a day (and LinkedIn's token reminder):
    # no model, a few requests to the sites the person posted to; nothing on the preview
    from .social import reach
    jobs.append(Job(reach.KIND, 24, lambda: reach.run(rt)))
    return jobs


def cmd_serve(args) -> int:
    import logging

    from .scheduler import Scheduler
    from .web.app import create_app

    memory.enter_scope("afk serve")
    rt = _runtime(args)
    scheduler = None
    if not args.no_scheduler:
        from .core import registry as features
        jobs = server_jobs(rt, update_job=getattr(args, "update_job", False),
                           port=args.port)
        # a post the person said yes to at an hour goes then, on its own lane, so a long job
        # never makes it late (``kranto.social.hours``)
        from .social.hours import HoursLane
        scheduler = Scheduler(rt.store, jobs,
                              ticks=[lambda: features.deliver(rt), memory.Watch().check,
                                     lambda: _idle_embedder(rt)],
                              job_source=lambda: rt.cubs.jobs() if rt.cubs else [],
                              lanes=[HoursLane(rt)])
    from .web.app import LOOPBACK_HOSTS

    allowed = set(LOOPBACK_HOSTS) | {h.strip("[]").lower() for h in args.allow_host or []}
    if args.host not in ("0.0.0.0", "::"):
        allowed.add(args.host.strip("[]").lower())
    if args.host not in LOOPBACK_HOSTS:
        print(f"warning: binding to {args.host} exposes the UI to your network: writes need "
              "a kranto token, but anyone who can reach it can read everything", file=sys.stderr)
        if args.host in ("0.0.0.0", "::") and not args.allow_host:
            print("warning: requests are accepted only for the names in --allow-host "
                  "(and loopback); add the name or address you will browse to",
                  file=sys.stderr)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    quiet_http_loggers()
    lanes = f", lanes: {', '.join(lane.name for lane in scheduler.lanes)}" \
        if scheduler and scheduler.lanes else ""
    print(f"{getattr(args, 'banner', 'kranto')} on http://{args.host}:{args.port}  "
          f"(scheduler {'on' if scheduler else 'off'}{lanes})", flush=True)
    from . import setup as setup_mod
    setup_mod.warm()           # the logins' checks, before the first page asks for them
    from . import stopping

    stop = stopping.Stop()
    if scheduler is not None:
        stop.on_begin.append(scheduler.request_stop)
    try:
        _serve(create_app(rt, scheduler, allowed_hosts=allowed, bind_host=args.host,
                          port=args.port, stop=stop),
               stop, host=args.host, port=args.port)
    finally:
        rt.close()
    return 0


# -- parser ----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="afk", description="Patient LLM Kranto watching the sources you care about."
    )
    parser.add_argument("--version", action="version", version=f"the server {__version__}")
    parser.add_argument(
        "-w", "--workspace", help="workspace directory (default: $KRANTO_HOME or current directory)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a workspace")
    p.add_argument("directory")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="library size, spend, last run")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("pause", help="pause watching: no model call until resumed (the page's "
                                      "Pause pauses building too)")
    p.add_argument("reason", nargs="?", default="paused from the command line")
    p.set_defaults(func=cmd_pause)

    p = sub.add_parser("resume", help="resume watching")
    p.set_defaults(func=cmd_resume)

    topics = sub.add_parser("topics", help="what you care about").add_subparsers(
        dest="topics_command", required=True
    )
    p = topics.add_parser("add", help="add a topic and scout sources for it")
    p.add_argument("name")
    p.add_argument("description", help="a sentence or two in plain language")
    p.add_argument("--no-scout", action="store_true", help="add the topic without proposals")
    p.add_argument("--approve", action="store_true",
                   help="approve proposals whose items resemble the topic (median similarity "
                        "at or above the prefilter threshold)")
    p.add_argument("--kind", choices=library.TOPIC_KINDS, default="user",
                   help="project: a topic gathered for one of the page's projects")
    p.add_argument("--ref", help="a project topic's key, project:<id>; adding one whose ref "
                                 "exists changes nothing")
    p.set_defaults(func=cmd_topics_add)
    p = topics.add_parser("scout", help="propose more sources for a topic")
    p.add_argument("topic_id", type=int)
    p.add_argument("--approve", action="store_true")
    p.set_defaults(func=cmd_topics_scout)
    p = topics.add_parser("edit", help="change a topic's name or description (its id is kept)")
    p.add_argument("topic_id", type=int)
    p.add_argument("--name")
    p.add_argument("--description")
    p.set_defaults(func=cmd_topics_edit)
    p = topics.add_parser("archive", help="archive a topic: not read, off the lists, its "
                                          "evidence and cards kept (--restore: back)")
    p.add_argument("topic_id", type=int)
    p.add_argument("--restore", action="store_true")
    p.set_defaults(func=cmd_topics_archive)
    p = topics.add_parser("list", help="list active topics")
    p.add_argument("--kind", choices=(*library.TOPIC_KINDS, "all"), default="user",
                   help="which topics: yours (default), project topics, or all")
    p.set_defaults(func=cmd_topics_list)

    srcs = sub.add_parser("sources", help="what the kranto watch").add_subparsers(
        dest="sources_command", required=True
    )
    p = srcs.add_parser("add", help="add and approve a source")
    p.add_argument("kind", nargs="?", choices=sorted(sources.KINDS))
    p.add_argument("value", nargs="?",
                   help="subreddit | HN feed (front/new/show/ask) or query | feed URL")
    p.add_argument("--topic", type=int, action="append", help="topic id this source serves")
    p.add_argument("--no-check", action="store_true", help="skip the test fetch")
    p.add_argument("--from-text", metavar="FILE",
                   help="the same as 'afk sources describe FILE' (proposes, approves nothing)")
    p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_sources_add)
    p = srcs.add_parser("describe", help="propose sources from a pasted list or description "
                                         "(one model call; approves nothing)")
    p.add_argument("file", metavar="FILE", help="a text file, or - for stdin")
    p.add_argument("--topic", type=int, help="the topic they are for")
    p.add_argument("--json", action="store_true", help="the batch as JSON")
    p.set_defaults(func=cmd_sources_describe, from_text=None)
    p = srcs.add_parser("list", help="list sources")
    p.add_argument("--status", choices=["proposed", "approved", "retired", "invalid"])
    p.set_defaults(func=cmd_sources_list)
    p = srcs.add_parser("retention", help="how long one source's observations are kept")
    p.add_argument("source_id", type=int)
    p.add_argument("days", metavar="DAYS",
                   help="days before compaction (0: forever), or 'default' for the "
                        "retention setting of the source's kind")
    p.add_argument("--note")
    p.set_defaults(func=cmd_sources_retention)
    p = srcs.add_parser("forget", help="remove a kept post now (a deletion request): its "
                                       "observation goes through the recorded purge")
    p.add_argument("target", help="the post's URL (an x.com status URL, or any observation's "
                                  "source URL) or the observation's id")
    p.set_defaults(func=cmd_sources_forget)
    p = srcs.add_parser("approve", help="approve proposed sources")
    p.add_argument("source_ids", metavar="ID", type=int, nargs="+")
    p.add_argument("--topic", type=int, help="also link them to this topic")
    p.add_argument("--note")
    p.set_defaults(func=cmd_sources_approve)
    p = srcs.add_parser("retire", help="mark a source retired")
    p.add_argument("source_id", type=int)
    p.add_argument("--note")
    p.set_defaults(func=cmd_sources_set, status="retired")

    prov = sub.add_parser("provider", help="the watcher's model provider: show, test, use")
    prov_sub = prov.add_subparsers(dest="provider_cmd", required=True)
    p = prov_sub.add_parser("show", help="what can serve the watcher's models here")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_provider_show)
    p = prov_sub.add_parser("test", help="test a provider's key as set; spends nothing")
    p.add_argument("provider", nargs="?",
                   choices=("anthropic", "openrouter", "openai_compat", "claude_code"))
    p.add_argument("--base-url", help="another endpoint's base URL")
    p.set_defaults(func=cmd_provider_test)
    p = prov_sub.add_parser("xai", help="the xAI key, for X search through Grok only (never "
                                        "the watcher's model): test it, or keep it")
    p.add_argument("--key-stdin", action="store_true",
                   help="read the key from the first line of stdin (never an argument)")
    p.set_defaults(func=cmd_provider_xai)
    p = prov_sub.add_parser("openai", help="the OpenAI key, for a post writer's own model only "
                                           "(never the watcher's): test it, or keep it")
    p.add_argument("--key-stdin", action="store_true",
                   help="read the key from the first line of stdin (never an argument)")
    p.set_defaults(func=cmd_provider_openai)
    p = prov_sub.add_parser("use", help="test a provider, then make it the watcher's")
    p.add_argument("provider", choices=("anthropic", "openrouter", "openai_compat",
                                        "claude_code"))
    p.add_argument("--accept-terms", action="store_true",
                   help="claude_code only: you have read what using your Claude login means")
    p.add_argument("--key-stdin", action="store_true",
                   help="read the key from the first line of stdin (never an argument)")
    p.add_argument("--base-url", help="another endpoint's base URL")
    p.set_defaults(func=cmd_provider_use)
    p = prov_sub.add_parser("replay", help="ask this library's newest screens and judges again "
                            "through the Claude API, three ways; spends up to --max-usd")
    p.add_argument("--screens", type=int, default=24)
    p.add_argument("--judges", type=int, default=16)
    p.add_argument("--max-usd", type=float, default=0.20)
    p.add_argument("--yes", action="store_true", help="do not ask before spending")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_provider_replay)

    p = sub.add_parser("run", help="one ingest pass over every approved source")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="recent observations")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--source", type=int)
    p.add_argument("--min-signal", type=float)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="search observations by meaning and by words")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("websearch", help="search the live web (dated results; the scout, cards "
                                         "and the editor use the same backends)")
    p.add_argument("query")
    p.add_argument("--recency", choices=["1w", "2w", "4w", "12w", "3mo", "6mo", "12mo"])
    p.add_argument("--kind", choices=["web", "discussion", "code", "papers"], default="web")
    p.add_argument("--backend", help="comma-separated: exa, anthropic, hackernews, github, arxiv")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_websearch)

    p = sub.add_parser("show", help="one observation in full")
    p.add_argument("observation_id", type=int)
    p.add_argument("--raw", action="store_true", help="include the raw model response")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("snapshot", help="re-cluster the library into a new map")
    p.add_argument("--force", action="store_true", help="even if nothing changed")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("compact", help="compact observations past their retention age into "
                                       "weekly rollups, and remove them")
    p.set_defaults(func=cmd_compact)

    ideas = sub.add_parser("ideas", help="idea cards from the latest map")
    ideas_sub = ideas.add_subparsers(dest="ideas_command")
    ideas.add_argument("--max", type=int, help="at most this many tier-2 calls")
    ideas.add_argument("--force", action="store_true", help="even if the map is unchanged")
    ideas.set_defaults(func=cmd_ideas)
    p = ideas_sub.add_parser("list", help="list idea cards, best first")
    p.add_argument("--all", action="store_true", help="include cards with unsupported evidence")
    p.set_defaults(func=cmd_ideas_list)
    p = ideas_sub.add_parser("card", help="one card on one theme now (one call, about $0.06)")
    p.add_argument("lineage", help="the theme's lineage id (afk map, the theme's sheet)")
    p.set_defaults(func=cmd_ideas_card)
    p = ideas_sub.add_parser("grade", help="record your verdict on a card")
    p.add_argument("idea_id", type=int)
    p.add_argument("verdict", choices=["useful", "not_useful"])
    p.add_argument("--note")
    p.set_defaults(func=cmd_ideas_grade)

    p = sub.add_parser("explain", help="what an observation's neighbourhood has in common")
    p.add_argument("observation_id", type=int)
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("import", help="import observations from another library, or idea "
                                      "cards from your Parallax dispatches")
    p.add_argument("format", choices=["parallax", "parallax-dispatches"],
                   help="parallax: observations (library.jsonl); parallax-dispatches: one "
                        "card per pitch of each dispatch, after the observations")
    p.add_argument("paths", nargs="+", help="library.jsonl files or directories containing "
                                            "them; for parallax-dispatches, the dispatches "
                                            "directory")
    p.add_argument("--snapshot", metavar="DIR",
                   help="parallax: a snapshot bundle (snapshots/latest) to reconcile with and "
                        "to take the themes from")
    p.add_argument("--history", metavar="DIR",
                   help="parallax: where the dated bundles are, for the themes' names "
                        "(default: the snapshot's parent directory)")
    p.add_argument("--only", action="append", metavar="ID",
                   help="parallax-dispatches: only this dispatch id (repeatable)")
    p.add_argument("--limit", type=int, metavar="N",
                   help="parallax-dispatches: the newest N dispatches that have pitches")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("serve", help="web UI, JSON API and the scheduler")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--allow-host", action="append", metavar="NAME",
                   help="another host name or address the UI may be reached by (repeatable); "
                        "loopback names and --host are always allowed")
    p.add_argument("--no-scheduler", action="store_true",
                   help="serve only; run ingest from cron with 'afk run' instead")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("messages", help="strikes, heartbeats and alarms, newest first")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("--kind", choices=["strike", "heartbeat", "alarm"])
    p.set_defaults(func=cmd_messages)

    p = sub.add_parser("strikes", help="strike candidates and why each was or was not sent")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.add_argument("-v", "--verbose", action="store_true", help="show each decision's reason")
    p.add_argument("--run", action="store_true",
                   help="run the gate and deliver pending messages now")
    p.set_defaults(func=cmd_strikes)

    p = sub.add_parser("heartbeat", help="send the weekly heartbeat if it is due")
    p.add_argument("--now", action="store_true",
                   help="send it now even if not due (still once per ISO week)")
    p.set_defaults(func=cmd_heartbeat)

    p = sub.add_parser("grade", help="grade an idea card or an observation (▲ useful, ▼ not "
                       "useful): cards like it rank higher or lower")
    p.add_argument("target", help="idea or observation (grades are kept on ideas and evidence "
                   "only)")
    p.add_argument("target_id", help="its id")
    p.add_argument("grade", choices=["useful", "not_useful"])
    p.add_argument("--note")
    p.set_defaults(func=cmd_grade)

    p = sub.add_parser("pack", help="add topics and sources from a pack file")
    p.add_argument("file")
    p.add_argument("--no-check", action="store_true", help="skip test fetches")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("doctor", help="check the key, models, pricing, sources and embedder")
    p.add_argument("--skip-embedder", action="store_true",
                   help="do not load the embedding model (it downloads ~500MB once)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("export", help="export a table as JSONL, or the latest map as a bundle")
    p.add_argument("table", nargs="?", default="observations",
                   help="a table name, or 'bundle' for a static copy of the latest map")
    p.add_argument("-o", "--output", default="-")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("features", help="Kranto's features: what each declares and may do")
    p.add_argument("id", nargs="?", help="one feature's manifest in full")
    p.add_argument("--json", action="store_true", help="the manifests as JSON")
    p.set_defaults(func=cmd_features)
    from .core.cubs import cli as cubs_cli
    cubs_cli.add_parser(sub).set_defaults(func=cmd_cub)
    # each feature's own commands (afk news ..., afk invest ...), from its manifest
    from .core.registry import features as _features
    for f in _features():
        if f.cli is not None:
            f.cli(sub)
    return parser


def cmd_cub(args) -> int:
    """``afk cub …``: ``kranto cub`` for this workspace."""
    from .core.cubs import cli as cubs_cli
    rt = _runtime(args) if getattr(args, "runtime_factory", None) else None
    return cubs_cli.run(args, config_mod.find_workspace(args.workspace), rt=rt)


def cmd_features(args) -> int:
    from .core import registry
    manifests = registry.check()
    if args.id:
        m = next((m for m in manifests if m["id"] == args.id), None)
        if m is None:
            raise CLIError(f"no feature {args.id} (features: "
                           f"{', '.join(x['id'] for x in manifests) or 'none'})")
        print(json.dumps(m, indent=2, sort_keys=True))
        return 0
    if args.json:
        print(json.dumps(manifests, indent=2, sort_keys=True))
        return 0
    from .core.manifest import API
    print(f"api: {API}")
    if not manifests:
        print("no features")
    for m in manifests:
        p = m
        grants = [f"reads {', '.join(p['reads']) or 'nothing'}",
                  f"model {', '.join(p['model']['purposes']) or 'none'}",
                  f"search {', '.join(p['search']) or 'none'}",
                  f"may request {', '.join(p['requests']) or 'nothing'}"]
        print(f"{m['id']} {m['version']} ({m['trust']}): {m['title']}")
        print(f"  {m['says']}")
        print(f"  {'; '.join(grants)}")
    return 0


def main(argv: list[str] | None = None, *, runtime_factory=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    quiet_http_loggers()
    args.runtime_factory = runtime_factory
    try:
        return int(args.func(args) or 0)
    except (config_mod.ConfigError, CLIError, ValueError) as exc:
        print(f"afk: {exc}", file=sys.stderr)
        return 2
