"""Kranto's first-party features: each a package with one manifest.

A feature lives in ``the server/features/<id>/``, declares ``FEATURE`` (a ``core.Feature``) in its
``__init__.py`` and imports nothing of the server but ``kranto.core`` and itself (a test holds
it). This list is the registry: the core reads it for the scheduler's jobs, the bus's kinds,
the settings, the routes, ``GET /api/features`` and the docs. Third-party mods are not loaded
in this release (MR-RESEARCH the runtime is phase 1, 0.5); when they are, they join the same
list through the same validator, with their own trust.
"""

from __future__ import annotations

from .news import FEATURE as NEWS

# Invest and the trend radar left Kranto in wave 3 (cut 2): their tables stay,
# untouched, and `kranto archive` writes them out.
FEATURES: tuple = (NEWS,)
