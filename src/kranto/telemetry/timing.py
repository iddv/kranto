"""The server's own numbers (sections 4.2, 4.5): request latency by route pattern,
and error fingerprints.

``TimingMiddleware`` is plain ASGI, beside ``GuardMiddleware``: for each HTTP request it notes
the matched route's pattern (``/api/sources/{source_id}``: Starlette's ``scope["route"]``,
never the address), the status class and the time to the first byte of the answer (a live
feed is not slow for staying open). The counts are kept in memory and written as one ``api``
line per route every five minutes (and before the daily job), so a request costs a dict
update. An exception that escapes a route is recorded as an ``error`` line (``where: api``)
and raised on as before.

``fingerprint(exc)``: the exception's class name and up to five frames of Kranto's own code
(``the server.``, ``the page.``, ``kranto.``), innermost first, as ``module.function:line``. The
message is never read, so whatever it carried (a path, a token, a name) cannot leave."""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any

from . import local
from .report import BUCKETS_MS, bucket

FLUSH_S = 300.0
OWN = ("kranto", "kranto.page", "kranto")
MAX_FRAMES = 5

_lock = threading.Lock()
_counts: dict[str, dict] = {}
_flushed = time.monotonic()


def fingerprint(exc: BaseException) -> str | None:
    """``KeyError:kranto.page.loop.gate.hold:212:kranto.page.loop.gate.evaluate:100``-shaped, or
    None when no frame is Kranto's own (the line's pattern refuses it then anyway)."""
    from ..errtrace import own_module

    frames = []
    for fs in reversed(traceback.extract_tb(exc.__traceback__)):
        mod = own_module(fs.filename)
        if mod is None or mod.split(".")[0] not in OWN:
            continue
        frames.append(f"{mod}.{fs.name}:{fs.lineno}")
        if len(frames) == MAX_FRAMES:
            break
    if not frames:
        return None
    return f"{type(exc).__name__}:" + ":".join(frames)


def record_error(exc: BaseException, where: str, *, route: str | None = None,
                 job: str | None = None) -> None:
    """The error in the day's counters and, when the person chose to send, as an error report
    (``errors.report``). Never raises."""
    if local.configured() is None:
        return
    from . import errors

    errors.report(exc, where, route=route, job=job)
    try:
        fp = fingerprint(exc)
    except Exception:  # noqa: BLE001 - a fingerprint that cannot be made is not kept
        return
    if fp:
        local.record("error", fingerprint=fp, where=where)


def note(route: str, status: int, ms: float) -> None:
    with _lock:
        c = _counts.setdefault(route, {"n2": 0, "n3": 0, "n4": 0, "n5": 0, "slow": 0,
                                       "h": [0] * (len(BUCKETS_MS) + 1)})
        cls = f"n{min(max(status // 100, 2), 5)}"
        c[cls] += 1
        c["h"][bucket(ms)] += 1
        if ms > 1000:
            c["slow"] += 1
    if time.monotonic() - _flushed > FLUSH_S:
        flush()


def flush() -> None:
    """Write what was counted since the last flush, one line per route."""
    global _flushed
    with _lock:
        counts = dict(_counts)
        _counts.clear()
        _flushed = time.monotonic()
    for route, c in counts.items():
        local.record("api", route=route, **{k: v for k, v in c.items() if v})


def route_of(scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path else "other"


class TimingMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or local.configured() is None:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        seen: dict[str, Any] = {}             # status (an int), ms (a float)

        async def timed(message):
            if message.get("type") == "http.response.start" and "status" not in seen:
                seen["status"] = int(message.get("status") or 500)
                seen["ms"] = (time.perf_counter() - start) * 1000
            await send(message)

        try:
            await self.app(scope, receive, timed)
        except Exception as exc:
            record_error(exc, "api", route=route_of(scope))
            seen.setdefault("status", 500)
            raise
        finally:
            ms = seen.get("ms", (time.perf_counter() - start) * 1000)
            note(route_of(scope), seen.get("status", 500), ms)
            from . import assistant  # a page's own press on a verb's route
            assistant.note_request(scope, route_of(scope), seen.get("status", 500), ms)
