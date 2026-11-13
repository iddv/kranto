"""Source adapters: the things kranto watch.

A source turns one configured feed into a list of ``Item``s. Adapters raise
``SourceError`` when a fetch fails. They never return an empty list to mean
"something went wrong": an outage has to look different from a quiet feed.
"""

from __future__ import annotations

import copy
import html
import ipaddress
import re
import socket
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from ..scrub import scrub
from . import pacing

USER_AGENT = "the server/0.1 (+https://github.com/iddv/kranto)"
MAX_RESPONSE_BYTES = 5_000_000
EXCERPT_CHARS = 200
# A title is a line, not a document. Feeds are untrusted: a 1.5 MB title once
# went whole into a judge request and into the append-only library.
MAX_TITLE_CHARS = 500
# Whole-request limit. httpx's timeout is per read, so a server dripping one
# byte at a time could hold a fetch, and the ingest lock, indefinitely.
REQUEST_DEADLINE_SECONDS = 60.0


class SourceError(Exception):
    """A fetch failed. ``transient`` errors (rate limits, timeouts) are expected to clear.

    ``needs_login`` marks a source that reads through a connected account whose
    connection is missing or was refused: the run continues, and the source's row
    says "Needs login" instead of failing silently. ``retry_at`` (a transient error
    only) is when the host may be asked again: its ``Retry-After``, or the backoff.
    ``status`` is the reply's HTTP status when there was one; ``sent`` is False when the
    request never left (a refused address, a host still cooling down), which a broker's
    send needs to tell apart from a request whose outcome is unknown."""

    def __init__(self, message: str, *, transient: bool = True, needs_login: bool = False,
                 retry_at: datetime | None = None, status: int | None = None,
                 sent: bool = True):
        super().__init__(message)
        self.transient = transient
        self.needs_login = needs_login
        self.retry_at = retry_at
        self.status = status
        self.sent = sent


class TooLarge(SourceError):
    """A response over ``MAX_RESPONSE_BYTES``: refused, never truncated."""

    def __init__(self, message: str):
        super().__init__(message, transient=False)


class Pacer:
    """Keeps requests to one host at least ``interval`` seconds apart, process-wide."""

    def __init__(self, interval: float, *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def wait(self) -> None:
        with self._lock:
            if self._last is not None:
                remaining = self.interval - (self.clock() - self._last)
                if remaining > 0:
                    self.sleep(remaining)
            self._last = self.clock()


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    body: str
    url: str | None = None
    link: str | None = None
    published_at: datetime | None = None
    meta: dict = field(default_factory=dict)
    comments: tuple[str, ...] = ()
    # How many of each kind of personal data or secret were removed; never content.
    redactions: dict = field(default_factory=dict)
    # For an item a deep dive reached: where it was reached from, shown to
    # the judge as context. Never part of the excerpt.
    reached_from: str | None = None
    # Set when the body was found to be no content (an empty page, sign-in
    # chrome, a cookie-consent wall) and blanked: says what was there.
    capture_note: str | None = None

    def __post_init__(self) -> None:
        # Personal data and secrets are removed here, before the text reaches a
        # prompt, the library or a log. Authors are not kept at all.
        if len(self.title) > MAX_TITLE_CHARS:
            object.__setattr__(self, "title", self.title[:MAX_TITLE_CHARS].rstrip() + " ...")
        counts = Counter(self.redactions)
        object.__setattr__(self, "title", scrub(self.title, counts))
        object.__setattr__(self, "body", scrub(self.body, counts))
        object.__setattr__(self, "comments", tuple(scrub(c, counts) for c in self.comments))
        if self.reached_from is not None:
            object.__setattr__(self, "reached_from", scrub(self.reached_from, counts))
        object.__setattr__(self, "redactions", dict(counts))

    def text_for_prefilter(self) -> str:
        return f"{self.title}\n{self.body[:2000]}"

    def canonical_url(self) -> str | None:
        """What the item is about, as a URL: the linked article when there is
        one, else the item's own page. Two items with the same canonical URL are
        the same content, whichever source or submission they arrived through."""
        return canonical_url(self.link) or canonical_url(self.url)

    def excerpt(self) -> str:
        """A verbatim, non-LLM excerpt kept for audit."""
        text = " ".join((self.body or self.title).split())
        if len(text) <= EXCERPT_CHARS:
            return text
        cut = text.rfind(" ", 0, EXCERPT_CHARS)
        return text[: cut if cut > EXCERPT_CHARS // 2 else EXCERPT_CHARS] + " ..."


def safe_url(url: str | None) -> str | None:
    """Only absolute http(s) URLs survive. Feed items supply their own links, and a
    ``javascript:`` or ``data:`` link rendered as an href would run in the UI."""
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return url.strip()
    return None


# Query parameters that identify a campaign or a referrer, never the content.
# Hosts where ``ref`` names a branch or tag, not a referrer: ?ref=v1 and ?ref=v2
# are different files.
REF_IS_CONTENT = frozenset({"github.com", "gitlab.com"})
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "ref_url", "_hsenc", "_hsmi",
})


def canonical_url(url: str | None) -> str | None:
    """A comparable form of ``url``: https, lowercase host without ``www.`` or a
    default port, no fragment, no tracking parameters, remaining parameters
    sorted, no trailing slash. None for anything ``safe_url`` rejects.

    A fragment that routes a single-page app (``#/post/1``, ``#!/post/1``) is the
    page, so it is kept; any other fragment is a position within the page."""
    url = safe_url(url)
    if not url:
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.")
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    keep_ref = host in REF_IS_CONTENT
    query = sorted(
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
        and (k.lower() not in TRACKING_PARAMS or (keep_ref and k.lower() == "ref"))
    )
    path = parsed.path.rstrip("/")
    fragment = parsed.fragment if parsed.fragment.startswith(("/", "!")) else ""
    return urlunparse(("https", host, path, "", urlencode(query), fragment))


class Source(Protocol):
    kind: str

    @property
    def label(self) -> str: ...

    def fetch(self) -> list[Item]: ...

    def enrich(self, item: Item) -> Item: ...


# -- HTTP ----------------------------------------------------------------------

Resolver = Callable[[str], list[str]]


def quiet_http_loggers() -> None:
    """httpx and httpcore log each request at INFO and DEBUG, with its full URL and,
    at DEBUG, headers. A connected account's credentials travel in headers, and a
    Stack Exchange key in the query string, so these loggers are held at WARNING
    whatever the root level is, wherever an ``HTTP`` is made."""
    import logging

    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _resolve(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def check_public_url(url: str, *, resolver: Resolver = _resolve) -> None:
    """Refuse URLs that point at private, loopback, or link-local addresses.

    Source URLs can come from a model (the scout), so they are untrusted input.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SourceError(f"not an http(s) URL: {url}", transient=False, sent=False)
    try:
        addresses = resolver(parsed.hostname)
    except OSError as exc:
        raise SourceError(f"cannot resolve {parsed.hostname}: {exc}", transient=False,
                          sent=False) from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            raise SourceError(
                f"{parsed.hostname} resolves to non-public address {ip}", transient=False,
                sent=False)


class Auth(Protocol):
    """A connected account, as the HTTP layer sees it (``connections.ConnectionAuth``).

    The token never passes through an adapter: ``headers`` is asked for at send
    time, only for requests to ``host``, and may refresh the token first. It is
    given the method and URL because a DPoP proof (Bluesky) is bound to them.
    ``params`` adds query parameters the same way (a Stack Exchange key); they
    are never part of the URL an error message names. ``observe`` sees each
    reply and returns True to have the request sent once more (a DPoP nonce the
    server asked for)."""

    host: str

    def headers(self, method: str, url: str) -> dict[str, str]: ...

    def params(self) -> dict[str, str]: ...

    def observe(self, response: httpx.Response) -> bool: ...

    def refused(self) -> None: ...


class HTTP:
    """Small wrapper: user agent, timeouts, size cap, public-address check, error mapping.

    ``with_auth`` returns the same client with a connected account's headers added
    per request (``Auth``); adapters call ``get_json`` as usual and never see a token."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        allow_private: bool = False,
        resolver: Resolver = _resolve,
        timeout: float = 20.0,
        deadline: float = REQUEST_DEADLINE_SECONDS,
        hosts: pacing.Hosts | None = None,
    ) -> None:
        self._deadline = deadline
        # None: the process-wide pacing (``pacing.HOSTS``), read at send time.
        self._hosts = hosts
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        )
        self._allow_private = allow_private
        self._resolver = resolver
        self._auth: Auth | None = None
        self._owner = True
        quiet_http_loggers()

    def close(self) -> None:
        if self._owner:
            self._client.close()

    def with_auth(self, auth: Auth) -> HTTP:
        """This client, with ``auth``'s headers on every request to ``auth.host``.

        Same connection pool, public-address check, size cap and deadline. Closing
        the copy leaves the original open."""
        authed = copy.copy(self)
        authed._auth = auth
        authed._owner = False
        return authed

    @property
    def auth_host(self) -> str | None:
        """The host a connected account's requests go to (a Bluesky account's PDS)."""
        return self._auth.host if self._auth is not None else None

    @property
    def auth_account(self) -> str | None:
        """The connected account's own id at the provider (X's user id), when it has one."""
        return getattr(self._auth, "account_id", None) if self._auth is not None else None

    def get(
        self, url: str, *, params: dict | None = None, max_redirects: int = 3,
        deadline: float | None = None, headers: dict | None = None, errors: bool = True,
    ) -> httpx.Response:
        """GET ``url``. ``deadline`` shortens the whole-request limit for this call. With
        ``errors`` off, a 4xx reply other than 401 and the throttles is returned, for an API
        whose error body says why (X's spent credits)."""
        return self._send("GET", url, params=params, max_redirects=max_redirects,
                          deadline=deadline, headers=headers, errors=errors)

    def post(self, url: str, *, data: dict | None = None, json: dict | None = None,
             headers: dict | None = None, deadline: float | None = None,
             errors: bool = True) -> httpx.Response:
        """POST, never following a redirect. With ``errors`` off, a 4xx reply is
        returned instead of raised, for OAuth endpoints whose error body says why."""
        return self._send("POST", url, data=data, json=json, headers=headers,
                          max_redirects=0, deadline=deadline, errors=errors)

    def patch(self, url: str, *, json: dict | None = None, headers: dict | None = None,
              deadline: float | None = None, errors: bool = True) -> httpx.Response:
        """PATCH, never following a redirect (a broker's change of a draft's status)."""
        return self._send("PATCH", url, json=json, headers=headers, max_redirects=0,
                          deadline=deadline, errors=errors)

    def _send(
        self, method: str, url: str, *, params: dict | None = None, data: dict | None = None,
        json: dict | None = None, headers: dict | None = None, max_redirects: int = 3,
        deadline: float | None = None, errors: bool = True,
    ) -> httpx.Response:
        hosts = self._hosts or pacing.HOSTS
        started = time.monotonic()
        limit = self._deadline if deadline is None else min(deadline, self._deadline)
        # A source's own fetch waits out a short throttle (``pacing``). A request with
        # its own deadline (gathering for one item, a preview) is never retried, and
        # waits for a host only as long as its deadline allows.
        retries = hosts.retries if deadline is None else 0
        wait_limit = None if deadline is None else min(hosts.max_wait, limit)
        retried, throttled = False, 0
        attempts = max_redirects + 2 + retries  # one more for a retry the account asks for
        for _ in range(attempts):
            if not self._allow_private:
                check_public_url(url, resolver=self._resolver)
            sent = dict(headers or {})
            query = dict(params) if params else None
            host = urlparse(url).hostname or ""
            authed = self._auth is not None and host == self._auth.host
            if authed:
                # Added here, at send time, and only for the account's own host: a
                # redirect elsewhere goes without it.
                sent.update(self._auth.headers(method, url))
                extra = _auth_params(self._auth)
                if extra:
                    query = {**(query or {}), **extra}
            asked = time.monotonic()
            try:
                with hosts.slot(host, max_wait=wait_limit):
                    # Time spent waiting for the host is pacing, not the server's slowness.
                    started += time.monotonic() - asked
                    with self._client.stream(method, url, params=query, data=data, json=json,
                                             headers=sent) as response:
                        if method == "GET" and response.is_redirect \
                                and response.headers.get("location"):
                            url = str(response.url.join(response.headers["location"]))
                            if urlparse(url).scheme not in ("http", "https"):
                                raise SourceError(f"redirect to a non-http URL: {url[:200]}",
                                                  transient=False)
                            params = None
                            continue
                        chunks, size = [], 0
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise TooLarge(f"{url}: response larger than 5MB")
                            if time.monotonic() - started > limit:
                                raise SourceError(
                                    f"{url}: no complete response within {limit:.0f}s")
                            chunks.append(chunk)
                        body = b"".join(chunks)
            except pacing.Deferred as exc:
                raise SourceError(f"{url}: paced: {exc}",
                                  retry_at=hosts.retry_at(exc.seconds), sent=False) from None
            except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
                # httpx builds the next request for a redirect even when it does not
                # follow it, and raises InvalidURL (not an HTTPError) for a Location
                # such as mailto:. Neither clears by retrying.
                raise SourceError(f"{url}: {type(exc).__name__}: {_quiet(exc, authed)}",
                                  transient=False) from (None if authed else exc)
            except httpx.TimeoutException as exc:
                # A slow host is backed off like a throttling one, and the request retried
                # while the whole-request deadline allows.
                delay = hosts.backoff(throttled)
                hosts.cool(host, delay)
                if throttled < retries and time.monotonic() - started + delay < limit:
                    throttled += 1
                    continue
                raise SourceError(f"{url}: {type(exc).__name__}: {_quiet(exc, authed)}",
                                  retry_at=hosts.retry_at(delay)) from (None if authed else exc)
            except httpx.HTTPError as exc:
                # The exception's text names the URL, never the request's headers.
                raise SourceError(f"{url}: {type(exc).__name__}: {_quiet(exc, authed)}") \
                    from (None if authed else exc)
            # The body is already decoded; drop the encoding headers so httpx
            # does not try to decompress it a second time. The raw bytes are kept: a
            # decoded value outside ASCII (xeiaso.net's X-Clacks-Overhead) would be
            # encoded again as ASCII by httpx and raise UnicodeEncodeError.
            kept = [
                (k, v) for k, v in response.headers.raw
                if k.lower() not in (b"content-encoding", b"content-length", b"transfer-encoding")
            ]
            result = httpx.Response(
                response.status_code, headers=kept, content=body, request=response.request
            )
            if authed and not retried and _auth_observe(self._auth, result):
                retried = True
                continue
            if result.status_code == 401 and authed:
                self._auth.refused()
                raise SourceError(f"{url}: HTTP 401: the connected account's token was refused",
                                  needs_login=True, status=401)
            if result.status_code in pacing.THROTTLE_STATUS:
                # The server's Retry-After, else exponential backoff with jitter; the host
                # is left alone until then by every request in the process.
                after = pacing.retry_after_seconds(result.headers.get("retry-after"))
                if after is None:
                    after = pacing.reset_after_seconds(result.headers)
                delay = after if after is not None else hosts.backoff(throttled)
                hosts.cool(host, delay)
                if throttled < retries and delay <= hosts.max_wait:
                    throttled += 1
                    continue
                raise SourceError(f"{url}: HTTP {result.status_code}",
                                  retry_at=hosts.retry_at(delay), status=result.status_code)
            if result.status_code >= 500:
                raise SourceError(f"{url}: HTTP {result.status_code}",
                                  status=result.status_code)
            if result.status_code >= 400 and errors:
                raise SourceError(f"{url}: HTTP {result.status_code}", transient=False,
                                  status=result.status_code)
            return result
        raise SourceError(f"{url}: too many redirects", transient=False)

    def get_json(self, url: str, *, params: dict | None = None,
                 deadline: float | None = None, headers: dict | None = None):
        response = self.get(url, params=params, deadline=deadline, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"{url}: response is not JSON", transient=False) from exc


def _auth_params(auth: Auth) -> dict[str, str]:
    fn = getattr(auth, "params", None)
    return fn() if fn is not None else {}


def _auth_observe(auth: Auth, response: httpx.Response) -> bool:
    fn = getattr(auth, "observe", None)
    return bool(fn(response)) if fn is not None else False


def _quiet(exc: Exception, authed: bool) -> str:
    """An httpx error's text; for a connected account's request, without the query
    string, which may carry the account's key."""
    text = str(exc)
    return re.sub(r"\?[^\s'\"]*", "?...", text) if authed else text


# -- text helpers ----------------------------------------------------------------


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    text = html.unescape("".join(parser.parts))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def from_timestamp(seconds) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(seconds), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
