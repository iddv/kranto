"""What Kranto is doing: the one activity read across the server and the
build loop, and the owner's Stop of a run."""
from __future__ import annotations

from .base import ok

ROUTES = [
    # ?subject=topic:12 &kind= &limit= &all=1 &hours= &run=<id>
    ("GET", "/api/activity", ok(lambda a, r: a.activity(r.data))),
    ("POST", "/api/activity/stop", ok(lambda a, r: a.activity_stop(r.data))),
]
