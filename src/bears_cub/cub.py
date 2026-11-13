"""``Cub``: the one object a cub's entry file makes, and the decorators that name its handlers
. The handlers' names are the manifest's: ``jobs[].method``,
``events.subscribe[].method``, ``actions[].method``, ``provides`` and ``stages[].id``."""

from __future__ import annotations

from collections.abc import Callable

_INSTANCES: list[Cub] = []


class Cub:
    """``cub = Cub()`` once in the entry file; then ``@cub.job("compose")`` and friends."""

    def __init__(self) -> None:
        self.jobs: dict[str, Callable] = {}
        self.events: dict[str, Callable] = {}          # by method name
        self.event_kinds: dict[str, Callable] = {}     # by event kind
        self.actions: dict[str, Callable] = {}
        self.reads: dict[str, Callable] = {}
        self.stages: dict[str, Callable] = {}
        _INSTANCES.append(self)

    @staticmethod
    def _named(table: dict, name: str, what: str) -> Callable:
        if not isinstance(name, str) or not name:
            raise ValueError(f"@cub.{what} needs the name the manifest gives it")

        def register(fn: Callable) -> Callable:
            if name in table:
                raise ValueError(f"two {what} handlers are called {name}")
            table[name] = fn
            return fn
        return register

    def job(self, method: str) -> Callable:
        """A scheduled job: ``(ctx) -> dict | None`` (``{status, summary, line}``)."""
        return self._named(self.jobs, method, "job")

    def event(self, kind: str) -> Callable:
        """A push handler for a subscribed kind: ``(ctx, events) -> int | None`` (how many it
        handled, oldest first; None: all). Its function name is the subscription's
        ``method``."""
        def register(fn: Callable) -> Callable:
            if kind in self.event_kinds or fn.__name__ in self.events:
                raise ValueError(f"two event handlers for {kind}")
            self.event_kinds[kind] = fn
            self.events[fn.__name__] = fn
            return fn
        return register

    def action(self, method: str) -> Callable:
        """An action the owner runs: ``(ctx, fields) -> dict | None`` (``{say, refresh}``)."""
        return self._named(self.actions, method, "action")

    def read(self, name: str) -> Callable:
        """A read the page's lists, tiles and rows call: ``(ctx, params) -> dict``."""
        return self._named(self.reads, name, "read")

    def stage(self, ident: str) -> Callable:
        """A build stage (code stages, after 0.5): ``(ctx, stage) -> dict``."""
        return self._named(self.stages, ident, "stage")

    def handlers(self) -> dict[str, list[str]]:
        """What ``hello`` tells the host this file registered."""
        return {"jobs": sorted(self.jobs), "events": sorted(self.events),
                "actions": sorted(self.actions), "reads": sorted(self.reads),
                "stages": sorted(self.stages)}


def the_cub() -> Cub:
    """The ``Cub`` the entry file made (the last one, if it made several)."""
    if not _INSTANCES:
        raise RuntimeError("the entry file made no Cub(): write cub = Cub() at its top")
    return _INSTANCES[-1]
