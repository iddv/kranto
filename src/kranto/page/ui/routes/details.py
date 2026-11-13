"""Details: the record behind a row or a dialog, the drawer's read and
the console's ``kranto_details``, one function (ui/details.py)."""
from __future__ import annotations

from .. import details
from .base import ok

ROUTES = [
    # ?sel=b<build key> | prep:<uuid> | ask:<id> | i<idea id> | card:<n> | s<source id>
    ("GET", "/api/details", ok(lambda a, r: details.record(a, r.data))),
]
