"""``afk news``: on, off, run, list, show, article, articles, eval."""

from __future__ import annotations

import json
from typing import Any, cast

from kranto.core import cli as core_cli

from . import api, articles, brief, evals
from .stored import BriefItems


def _topic(ctx: Any, ref: str) -> dict[str, Any]:
    topics = ctx.read("topics.list")["topics"]
    t = next((t for t in topics if str(t["id"]) == ref or t["name"].lower() == ref.lower()),
             None)
    if t is None:
        raise core_cli.CommandError(f"no topic {ref!r} (topics: "
                                    f"{', '.join(x['name'] for x in topics) or 'none'})")
    return cast("dict[str, Any]", t)


def cmd(args: Any) -> int:
    ctx = core_cli.context(args, "news")
    try:
        return _cmd(ctx, args)
    finally:
        core_cli.close(ctx)


def _cmd(ctx: Any, args: Any) -> int:
    if args.news_cmd in ("on", "off"):
        t = _topic(ctx, args.topic)
        out = api.toggle(ctx, {"topic_id": t["id"], "on": args.news_cmd == "on",
                               "cadence": args.cadence, "hour": args.hour})
        s = out["news"]
        print(f"News {'on' if s['enabled'] else 'off'} for {t['name']}"
              + (f": {s['cadence']} at {s['hour']:02d}:00, next {out['next_due']}"
                 if s["enabled"] else ""))
        return 0
    if args.news_cmd == "run":
        topics = [_topic(ctx, args.topic)] if args.topic else \
            [t for t in ctx.read("topics.list")["topics"]
             if brief.topic_setting(ctx, t["id"])["enabled"]]
        if not topics:
            print("News is on for no topic: afk news on TOPIC")
            return 0
        for t in topics:
            made = brief.write(ctx, t, trigger="cli")
            if made is None:
                print(f"{t['name']}: a brief is being written already")
                continue
            items = BriefItems.load(made.get("items")).items
            print(f"{t['name']}: brief {made['id']}, {made['status']}, {len(items)} items"
                  + (f" ({made['error']})" if made.get("error") else ""))
        return 0
    if args.news_cmd == "list":
        params = {"limit": args.limit}
        if args.topic:
            params["topic_id"] = _topic(ctx, args.topic)["id"]
        for b in api.briefs_list(ctx, params)["briefs"]:
            print(f"{b['id']:>5}  {b['created_at'][:16]}  topic {b['topic_id']}  {b['status']:<6} "
                  f"{len(b['items'])} items")
        return 0
    if args.news_cmd == "article":
        return _article(ctx, args)
    if args.news_cmd == "articles":
        params = {"limit": args.limit, "status": "all"}
        if args.topic:
            params["topic_id"] = _topic(ctx, args.topic)["id"]
        for a in api.articles_list(ctx, params)["articles"]:
            print(f"{a['id']:>5}  {a['created_at'][:16]}  brief {a['brief_id']} item "
                  f"{a['item_n']}  {a['status']:<6} {a['words'] or 0:>4} words  "
                  f"{a['headline'] or a['quiet'] or a['error'] or ''}"[:160])
        return 0
    if args.news_cmd == "show" and args.article:
        return _show_article(api.articles_get(ctx, {"id": args.id}), args.json)
    if args.news_cmd == "show":
        b = api.briefs_get(ctx, {"id": args.id})
        if args.json:
            print(json.dumps(b, indent=2, ensure_ascii=False))
            return 0
        print(f"Brief {b['id']} ({b['status']}), {b['period_start'][:16]} to "
              f"{b['period_end'][:16]}")
        if b["quiet"]:
            print(b["quiet"])
        for i in b["items"]:
            print(f"\n{'Earlier: ' if i.get('background') else ''}{i['headline']} ({i['date']})")
            print(f"  {i['body']}")
            print(f"  Why: {i['why']}")
            for s in i.get("sources", []):
                print(f"  [{s['label']}] {s.get('date') or 'undated'} {s.get('url') or ''}")
        meta = b["search"]
        print("\n" + (f"Searched {(meta.get('searched_at') or '')[:10]} with "
                      f"{', '.join(meta.get('labels') or [])}" if meta.get("live")
                      else meta.get("note") or "no live search"))
        return 0
    if args.news_cmd == "eval" and args.articles:
        params = {"limit": args.limit, "status": "all"}
        if args.topic:
            params["topic_id"] = _topic(ctx, args.topic)["id"]
        rows = api.articles_list(ctx, params)["articles"]
        arts = [api.articles_get(ctx, {"id": a["id"]}) for a in reversed(rows)
                if "unreadable" not in a]
        card = evals.article_scorecard(arts)
        print(json.dumps(card, indent=2) if args.json else evals.article_text(card))
        return 0 if card["injection"]["passed"] else 1
    if args.news_cmd == "eval":
        params = {"limit": args.limit}
        if args.topic:
            params["topic_id"] = _topic(ctx, args.topic)["id"]
        briefs = list(reversed(api.briefs_list(ctx, params)["briefs"]))
        card = evals.scorecard(briefs)
        print(json.dumps(card, indent=2) if args.json else evals.text(card))
        return 0 if card["injection"]["passed"] else 1
    raise core_cli.CommandError(f"unknown news command {args.news_cmd}")


def _article(ctx: Any, args: Any) -> int:
    """``afk news article BRIEF ITEM [--dry-run]``: the deep dive for one item now (one model
    call), or with ``--dry-run`` the material and the prompt it would send (no call, no row)."""
    r = ctx.db.query_one("SELECT * FROM news_briefs WHERE id = ?", (args.brief,))
    if r is None:
        raise core_cli.CommandError(f"no brief {args.brief}")
    topic = _topic(ctx, str(r["topic_id"]))
    out = articles.write(ctx, topic, dict(r), args.item, trigger="cli", dry_run=args.dry_run)
    if out is None:
        print("an article for this item is being written already")
        return 1
    if args.dry_run:
        meta = out.get("material") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        print(out.get("prompt") or f"(no call: {out.get('quiet')})")
        print(f"\n-- {len(out.get('prompt') or '')} characters; lines {meta.get('counts')}; "
              f"pages {json.dumps((meta.get('log') or {}).get('pages'))}")
        return 0
    print(f"article {out['id']}: {out['status']}"
          + (f", {out.get('words')} words, figure {out.get('diagram')}" if out["status"] == "ok"
             else f" ({out.get('quiet') or out.get('error')})"))
    return 0 if out["status"] != "failed" else 1


def _show_article(a: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
        return 0
    print(f"Article {a['id']} ({a['status']}), {a['topic']}, brief {a['brief_id']} item "
          f"{a['item_n']}, {a['created_at'][:16]}")
    if a["status"] != "ok":
        print(a.get("quiet") or a.get("error") or "")
        return 0
    print(f"\n{a['headline']}\n{a['standfirst']}")
    for s in a["body"]["sections"]:
        print(f"\n{s['title']}")
        for p in s["paragraphs"]:
            print(f"  {p['text']} [{', '.join(p['cites'])}]")
    for x in a["body"]["numbers"]:
        print(f"  {x['value']} {x['unit']} {x['label']} [{', '.join(x['cites'])}]")
    print("\nSources")
    for i, s in enumerate(a["sources"], 1):
        print(f"  {i}. [{s['label']}] {s.get('date') or 'undated'} {s.get('title') or ''} "
              f"{s.get('url') or ''}")
    print(f"\nFigure: {a['diagram']}; checks: {json.dumps(a['checks'])}")
    return 0


def add(sub: Any) -> None:
    p = sub.add_parser("news", help="News: a short cited brief per topic (off until you turn "
                                    "it on for a topic)")
    news = p.add_subparsers(dest="news_cmd", required=True)
    for verb, words in (("on", "turn News on for a topic"), ("off", "turn News off")):
        q = news.add_parser(verb, help=words)
        q.add_argument("topic", help="a topic's id or name")
        q.add_argument("--cadence", choices=brief.CADENCES)
        q.add_argument("--hour", type=int, help="local hour, 0 to 23 (default 7)")
        q.set_defaults(func=cmd)
    q = news.add_parser("run", help="write a brief now (each topic News is on for, or one)")
    q.add_argument("topic", nargs="?")
    q.set_defaults(func=cmd)
    q = news.add_parser("list", help="briefs, newest first")
    q.add_argument("topic", nargs="?")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=cmd)
    q = news.add_parser("show", help="one brief with its citations (--article: one article)")
    q.add_argument("id", type=int)
    q.add_argument("--article", action="store_true", help="ID is an article's")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd)
    q = news.add_parser("article", help="the deep dive for one brief item now: reads the pages "
                                        "behind it and calls the model once (--dry-run: the "
                                        "prompt only, no call)")
    q.add_argument("brief", type=int, help="the brief's id")
    q.add_argument("item", type=int, help="the item's number in the brief, from 0")
    q.add_argument("--dry-run", action="store_true")
    q.set_defaults(func=cmd)
    q = news.add_parser("articles", help="articles, newest first, every try")
    q.add_argument("topic", nargs="?")
    q.add_argument("--limit", type=int, default=20)
    q.set_defaults(func=cmd)
    q = news.add_parser("eval", help="the scorecard over recent briefs (citations, novelty, "
                                     "readability, injection); costs nothing")
    q.add_argument("topic", nargs="?")
    q.add_argument("--limit", type=int, default=30)
    q.add_argument("--articles", action="store_true",
                   help="score the articles instead (citations, figures, grounding, injection)")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd)
