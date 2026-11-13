"""Kranto's core as a feature sees it (MR-RESEARCH).

A feature (``the server/features/<id>/``) imports this package and its own, nothing else of
the server: a test reads every feature module for it (the import contract,). What it
needs from the core is here or on the ``FeatureContext`` its jobs and actions receive.

- ``manifest``: ``Feature`` and its blocks, ``to_manifest()``, the one validator;
- ``context``: ``FeatureContext``, the scoped clients, ``record_run``;
- ``events``: the bus; ``api``: the v1 read surface; ``tickets``: high-trust tickets;
- ``settings``: a feature's ``kranto.yaml`` section;
- ``text``: the helpers a feature's prompt and checks use (fencing, scrubbing, dates, the
  registrable domain of a URL).
"""

from . import api, cli, events, manifest, settings, text, tickets
from .context import CapReached, FeatureContext, PermissionDenied, record_run
from .manifest import (
    UI,
    Action,
    Docs,
    Events,
    Feature,
    Form,
    FormField,
    Group,
    Job,
    Model,
    Nav,
    Permissions,
    Prompt,
    Setting,
    Settings,
    Spend,
    Subscribe,
    Telemetry,
    Tile,
    TodayRow,
    UIList,
    Widget,
    placed,
)

__all__ = ["Action", "CapReached", "Docs", "Events", "Feature", "FeatureContext", "Form",
           "FormField", "Group", "Job", "Model", "Nav", "PermissionDenied", "Permissions",
           "Prompt", "Setting", "Settings", "Spend", "Subscribe", "Telemetry", "Tile", "TodayRow",
           "UI", "UIList", "Widget", "api", "cli", "events", "manifest", "placed",
           "record_run", "settings", "text", "tickets"]
