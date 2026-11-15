"""The page's own small reads and writes: the header a host may still read, and the console's
settings in loop.yaml (``term.…``; the old ``api/loop/settings`` writer left with the loop, CUT)."""
from __future__ import annotations

from .base import ok

ROUTES = [
    ("GET", "/api/header", ok(lambda a, r: a.header())),
    ("POST", "/api/term/settings", ok(lambda a, r: a.term_setting(r.data))),
]
