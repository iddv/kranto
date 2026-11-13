"""The page's reads of the server (moved from ``projects/topic.py``): the page never opens
the server's database; it calls the server's JSON API on loopback with the command line's own token
(``cli``), never printed."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class AfkError(RuntimeError):
    """the server's API said no or could not be reached; the message says which, and ``code``
    the HTTP status (None: not reached)."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def afk_url(cfg) -> str | None:
    b = cfg.get("kranto") or {}
    return b.get("url") if b.get("enabled", True) else None


def call(url: str, method: str, path: str, body: dict | None = None, timeout: float = 30
         ) -> dict:
    """One request to the server's API on loopback, as the command line (``cli`` token, never
    printed); a write carries the server's own origin, as its guard requires."""
    from ..tokens import Store
    base = url.rstrip("/")
    data = json.dumps(body or {}).encode() if method == "POST" else None
    secret = Store().value("cli")
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Accept": "application/json", "Content-Type": "application/json",
        **({"Origin": base} if method == "POST" else {}),
        **({"Authorization": f"Bearer {secret}"} if secret else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error") or f"HTTP {e.code}"
        except ValueError:
            msg = f"HTTP {e.code}"
        raise AfkError(f"the server: {msg}", e.code) from None
    except (OSError, ValueError) as e:
        raise AfkError(f"the server's API at {base}: {type(e).__name__}: {e}") from None
