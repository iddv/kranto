"""One bad row never takes a page down, for the features: they import only
the core, so ``kranto.rowsafe``'s row helpers are named here. ``row(out, what, id)`` builds one
row of a list in its block; ``each(items, build, what)`` a whole list; a row that raises is
listed as "Couldn't read this <thing>" with its error's id (``rowsafe``)."""

from __future__ import annotations

from ..rowsafe import Unreadable, each, is_unreadable, note, readable, row, unreadable

__all__ = ["Unreadable", "each", "is_unreadable", "note", "readable", "row", "unreadable"]
