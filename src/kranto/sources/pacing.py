"""Polite fetching: pacing per host, and backoff on rate limits and timeouts.

Every request ``HTTP`` sends goes through ``HOSTS``, process-wide:

- **One at a time per host**, at least the host's gap apart, measured from the end
  of one request to the start of the next: ``fetch.min_gap_seconds``, or the host's
  own gap (``HOST_GAPS``, which ``fetch.hosts`` extends; arXiv asks for three seconds).
- **A 429 or 503** is retried after the server's ``Retry-After`` (seconds or an
  HTTP date), else after an exponential backoff with jitter. **A timeout** is
  retried the same way. A wait of at most ``fetch.max_wait_seconds`` is slept
  through, at most ``fetch.retries`` times. A longer wait is not: the host is left
  alone until then, and the request raises a transient ``SourceError`` carrying
  ``retry_at``, so the source is paced (deferred), never failed.
- **While a host cools down**, every request to it waits, when the wait is short,
  or is deferred at once without being sent. Four arXiv searches in one run share
  one cooldown instead of each drawing its own 429.

The clock, sleep and jitter are injectable for tests, which never wait.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

DEFAULT_GAP_SECONDS = 1.0
# Hosts that ask for a longer gap than the default.
# arXiv asks for three seconds; Reddit is read one request a second with your own app
HOST_GAPS = {"export.arxiv.org": 3.0, "oauth.reddit.com": 1.0}
DEFAULT_RETRIES = 2
DEFAULT_MAX_WAIT_SECONDS = 30.0
BACKOFF_BASE_SECONDS = 4.0
# A Retry-After further out than this is read as this: a server's day-long answer
# should not park a source for a day when the next run may find it open.
MAX_RETRY_AFTER_SECONDS = 6 * 3600.0
THROTTLE_STATUS = frozenset({429, 503})


class Deferred(Exception):
    """The host is cooling down for longer than the caller may wait."""

    def __init__(self, host: str, seconds: float):
        super().__init__(f"{host} asked to be left alone for {seconds:.0f}s")
        self.host, self.seconds = host, seconds


def retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    """A ``Retry-After`` header in seconds from now (delta-seconds or an HTTP date);
    None when absent or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (when - (now or datetime.now(UTC))).total_seconds()
    return min(max(0.0, seconds), MAX_RETRY_AFTER_SECONDS)


def reset_after_seconds(headers, *, now: float | None = None) -> float | None:
    """Seconds until a rate-limit window resets, from ``x-rate-limit-reset`` (X: epoch
    seconds) when a 429 carries no ``Retry-After``; None when absent or unreadable."""
    value = (headers.get("x-rate-limit-reset") or "").strip() if headers is not None else ""
    if not value.isdigit():
        return None
    seconds = float(value) - (time.time() if now is None else now)
    return min(max(0.0, seconds), MAX_RETRY_AFTER_SECONDS)


class _Host:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.last_end: float | None = None
        self.cool_until = 0.0


class Hosts:
    """The pacing and cooldown state of every host, shared by every ``HTTP`` in the process."""

    def __init__(self, *, default_gap: float = DEFAULT_GAP_SECONDS,
                 gaps: dict[str, float] | None = None, retries: int = DEFAULT_RETRIES,
                 max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
                 backoff_base: float = BACKOFF_BASE_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None,
                 wall: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.default_gap = default_gap
        self.gaps = {**HOST_GAPS, **(gaps or {})}
        self.retries, self.max_wait, self.backoff_base = retries, max_wait, backoff_base
        self.clock, self.sleep, self.wall = clock, sleep, wall
        self.rng = rng or random.Random()
        self._hosts: dict[str, _Host] = {}
        self._guard = threading.Lock()

    def configure(self, cfg) -> None:
        """Take the gaps and limits from a ``config.FetchConfig``."""
        self.default_gap = cfg.min_gap_seconds
        self.gaps = {**HOST_GAPS, **{h.lower(): float(s) for h, s in cfg.hosts.items()}}
        self.retries, self.max_wait = cfg.retries, cfg.max_wait_seconds

    def gap(self, host: str) -> float:
        return self.gaps.get(host.lower(), self.default_gap)

    def _host(self, host: str) -> _Host:
        with self._guard:
            return self._hosts.setdefault(host.lower(), _Host())

    @contextmanager
    def slot(self, host: str, *, max_wait: float | None = None) -> Iterator[None]:
        """Hold ``host`` for one request: wait for its gap and any cooldown, then send.
        Raises ``Deferred`` without waiting when the cooldown is longer than ``max_wait``."""
        limit = self.max_wait if max_wait is None else max_wait
        state = self._host(host)
        with state.lock:
            now = self.clock()
            cooling = state.cool_until - now
            if cooling > limit:
                raise Deferred(host, cooling)
            ready = state.cool_until
            if state.last_end is not None:
                ready = max(ready, state.last_end + self.gap(host))
            if ready > now:
                self.sleep(ready - now)
            try:
                yield
            finally:
                state.last_end = self.clock()

    def backoff(self, attempt: int) -> float:
        """The wait before retry ``attempt`` (0, 1, ...): exponential, with jitter."""
        base = self.backoff_base * (2 ** attempt)
        return base + self.rng.uniform(0, base / 2)

    def cool(self, host: str, seconds: float) -> None:
        """Leave ``host`` alone for ``seconds`` from now (a longer cooldown already set wins)."""
        state = self._host(host)
        with self._guard:
            state.cool_until = max(state.cool_until, self.clock() + seconds)

    def cooling(self, host: str) -> float:
        """Seconds until ``host`` may be asked again (0 when it may now)."""
        state = self._hosts.get(host.lower())
        return max(0.0, state.cool_until - self.clock()) if state else 0.0

    def retry_at(self, seconds: float) -> datetime:
        """The wall-clock time ``seconds`` from now, for a source's "retrying at"."""
        return self.wall() + timedelta(seconds=seconds)

    def sleep_for(self, seconds: float) -> None:
        if seconds > 0:
            self.sleep(seconds)


HOSTS = Hosts()
