"""The page's usage counters: lines handed to the host's
recorder.

The page keeps nothing itself and decides nothing: ``kranto serve`` gives it the server's
``record`` (``set_sink``, through ``host_api.telemetry_sink``), which applies the mode, the
allow-list and ``DO_NOT_TRACK``. Without a sink (the page alone, ``brb`` on the command
line) ``record`` does nothing. It never raises.

``telemetry.json`` is the page's part of the allow-list: the page nodes (nodes.json) and the
origins. ``schema()`` reads it for the host; a test keeps the nodes equal to nodes.json. The
registry's ``action`` line and the build's ``build`` line left with the build factory.

``facts(loop_home)``: the few numbers the daily report takes from the page's settings (whether
Open in Claude Code is on); never a name. The build loop's numbers left with it.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

_log = logging.getLogger("kranto.page.telemetry")
_sink: Callable[..., None] | None = None
CAP = 999


def set_sink(fn: Callable[..., None] | None) -> None:
    """The host's recorder (None: record nothing)."""
    global _sink
    _sink = fn


def record(name: str, **fields) -> None:
    fn = _sink
    if fn is None:
        return
    try:
        fn(name, **fields)
    except Exception:                    # noqa: BLE001 - counting never breaks what it counts
        _log.debug("telemetry line not kept", exc_info=True)


def schema() -> dict:
    return json.loads((Path(__file__).parent / "telemetry.json").read_text())


def origin_of(origin: str | None) -> str:
    """``agent:<name>`` is counted as ``agent``: never the name."""
    o = str(origin or "")
    return "agent" if o.startswith("agent:") else o


def facts(loop_home: str | Path) -> dict:
    """The page's numbers for the daily report (the host checks them against the list)."""
    out: dict = {}
    home = Path(loop_home)
    try:
        from .settings.store import Config
        cfg = Config(home).data
        term = cfg.get("term") or {}
        if isinstance(term.get("enabled"), bool):
            out["settings.term_enabled"] = term["enabled"]
    except Exception:                    # noqa: BLE001 - a report without them is still one
        pass
    return out
