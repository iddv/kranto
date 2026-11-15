"""The echo cub: a handler per thing the runtime's tests look at."""

import time

from bears_cub import Cub, NotGranted

cub = Cub()


@cub.job("tick")
def tick(ctx):
    topics = ctx.read.topics()["topics"]
    ctx.kv.put("ticks", (ctx.kv.get("ticks") or 0) + 1)
    ctx.events.publish("echo.said", {"topics": len(topics)}, dedupe=f"tick:{ctx.run_uuid}")
    return {"summary": {"topics": len(topics), "mode": ctx.mode}, "line": "ticked"}


@cub.job("boom")
def boom(ctx):
    raise ValueError("the handler's own bug")


@cub.job("slow")
def slow(ctx):
    for _ in range(600):
        if ctx.cancelled:
            return {"status": "skipped", "line": "cancelled"}
        time.sleep(0.05)
    return {"line": "finished"}


@cub.job("noisy")
def noisy(ctx):
    print("a print goes to the log, not the pipe")
    return {"line": "printed"}


@cub.job("ask")
def ask(ctx):
    try:
        ctx.read.get("ideas.list")
    except NotGranted as exc:
        return {"status": "degraded", "line": f"refused: {exc.message}"}
    return {"line": "read ideas"}


@cub.action("say")
def say(ctx, fields):
    return {"say": f"you said {fields.get('text')}", "refresh": ["count"]}


@cub.event("ticket.resolved")
def on_resolved(ctx, events):
    ctx.kv.put("resolved", [e["id"] for e in events])
    return None


@cub.read("count")
def count(ctx, params):
    return {"count": ctx.kv.get("ticks") or 0}


@cub.job("leak")
def leak(ctx):
    token = "ghp_" + "A1b2C3d4" * 5          # made here: the repository holds no such literal
    import sys
    print(f"stderr says {token}", file=sys.stderr)
    ctx.log.info(f"a log line with {token}")
    ctx.kv.get(f"key:{token}")
    return {"line": "leaked nothing"}
