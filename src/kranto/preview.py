"""The preview: a second Kranto built from a branch, serving a copy of the
owner's data on its own port, that cannot send.

One switch makes it safe: ``preview: {enabled: true}`` in the copy's ``kranto.yaml`` (the copy
script, ``scripts/preview/``, writes it with ``copied_at``). ``kranto serve`` reads it once and
puts ``KRANTO_PREVIEW=1`` and ``DO_NOT_TRACK=1`` in its own environment, so every check in the
process, and every process it starts, sees the switch without reading the file again; a command
run by hand (``kranto update``) passes its home and reads the file.

What the switch does, each line with its test (``tests/test_preview.py``):

1. every posting cub is in practice: ``core.cubs.settings.live_kinds`` is empty, ``cub.live``
   (``core.cubs.install.set_mode``) refuses, ``core.tickets.confirm`` refuses before any state is
   written, and a broker's request other than a GET (``BrokerContext.send``) never leaves;
2. a ticket's confirm never performs, and a cub broker's sends are the same
   ``BrokerContext.send``;
3. usage reports are never sent (``telemetry.local.effective`` is ``off``, why ``preview``);
4. ``kranto update``, the update check (``update.check.run_check``, ``update.launch.launch``) and
the
   cubs' own updates (``core.cubs.updates.run``, ``install.apply_update``) are off;
5. ``/api/status`` carries ``preview`` (the status bar's sentence and the copy's date);
6. ``kranto serve`` refuses to start with the switch on when its home or loop home is the live
   install's, or its port is live's (``refusal``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from . import legacy, product

ENV = "KRANTO_PREVIEW"
NOTHING_SENT = "This is the preview: nothing is sent"
LIVE_PORT = 8765
# the unit live runs as: an install from before the rename keeps its old unit
LIVE_UNITS = (legacy.UNIT, product.UNIT)
# the features the preview never runs, whatever the copied settings say (line 2):
# none since Invest and the radar left Kranto (cut 2)
FORCED_OFF: tuple[str, ...] = ()
# the live install's folders on this machine by name, whatever the unit says
LIVE_HOMES = legacy.live_homes()

_cache: dict[str, tuple[float, dict]] = {}


class PreviewRefused(RuntimeError):
    """What the preview will not do, in the words the person reads."""

    def __init__(self, message: str = NOTHING_SENT) -> None:
        super().__init__(message)
        self.message = message


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() not in ("", "0", "false", "no", "off")


def section(home: Path | str | None) -> dict[str, Any]:
    """``preview:`` of ``home``'s config file as a mapping (empty when it has none, the file is
    missing or broken, or the value is not a mapping). Cached by the file's mtime."""
    if home is None:
        return {}
    from .config import config_path

    path = config_path(Path(home))
    if path is None:
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    got = raw.get("preview") if isinstance(raw, dict) else None
    out = got if isinstance(got, dict) else {}     # a stored null or a word reads as no section
    _cache[str(path)] = (mtime, out)
    return out


def enabled(home: Path | str | None = None, environ: Mapping[str, str] | None = None) -> bool:
    """Whether this is the preview: ``$KRANTO_PREVIEW`` set, or ``preview.enabled: true`` in
    ``home``'s config (``$KRANTO_HOME``'s when no home is given)."""
    env = os.environ if environ is None else environ
    if _truthy(env.get(ENV)):
        return True
    home = home if home is not None else env.get("KRANTO_HOME")
    return section(home).get("enabled") is True


def refuse(home: Path | str | None = None, message: str = NOTHING_SENT) -> None:
    """Raise ``PreviewRefused`` when this is the preview."""
    if enabled(home):
        raise PreviewRefused(message)


def enter(home: Path) -> bool:
    """``kranto serve``'s one read: with the switch on, mark this process and its children."""
    if not enabled(home):
        return False
    os.environ[ENV] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    return True


def copied_on(home: Path | str | None) -> str | None:
    """The day the copy was taken, in words ("11 November"), or None."""
    raw = section(home).get("copied_at")
    if not isinstance(raw, str):
        return None
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return f"{when.day} {when.strftime('%B')}"


QUIET = "Nothing is posted; no update or usage report goes out."


def status(home: Path | str | None) -> dict[str, Any] | None:
    """``/api/status``'s ``preview``: None on any install but the preview."""
    if not enabled(home):
        return None
    sec = section(home)
    day = copied_on(home)
    # what is true (10, Gemini 13): Welcome's key test does reach the model's provider, so
    # the line says what never goes out: a post, an update, a usage report
    if sec.get("empty") is True:          # kranto-preview fresh: an empty home, for Welcome
        line = f"Preview: an empty home. {QUIET}"
    else:
        line = (f"Preview: a copy of your data from {day}. {QUIET}" if day
                else f"Preview: a copy of your data. {QUIET}")
    return {"line": line, "copied_at": sec.get("copied_at") if isinstance(
        sec.get("copied_at"), str) else None,
        "commits": sec.get("commits") if isinstance(sec.get("commits"), dict) else None}


def mark_away(home: Path | str, days: int = 9, now: datetime | None = None) -> dict[str, Any]:
    """``kranto-preview away [days]``: write the home's last-visit marker
    (``home.visit``) ``days`` ago on the preview's copy, so "While you were away" can be seen
    there (a copy is otherwise never away: the marker starts at the first draw). Refuses on any
    home whose own config file does not carry ``preview.enabled: true``: the environment is not
    enough, so it never writes live's marker. Answers the marker as stored."""
    import json
    from datetime import timedelta

    from .core.home import VISIT_KEY
    from .store import Store, iso, utcnow
    if section(home).get("enabled") is not True:
        raise PreviewRefused(f"{home} is not a preview's home: nothing was written")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365:
        raise ValueError("days is a whole number from 1 to 365")
    db = legacy.db_file(Path(home) / "data")
    if not db.exists():
        raise PreviewRefused(f"no library at {db}: nothing was written")
    marker = {"at": iso((now or utcnow()) - timedelta(days=days)), "previous": None}
    store = Store.open(db)
    try:
        store.set_setting(VISIT_KEY, json.dumps(marker))
    finally:
        store.close()
    return marker


# -- the guard ----------------------------------------------------------------------------------


def _resolved(p: Path | str | None) -> Path | None:
    if not p:
        return None
    try:
        return Path(p).expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def _live_unit_port(user_home: Path) -> int | None:
    import re

    from . import paths
    for unit in LIVE_UNITS:
        try:
            text = (paths.unit_dir(user_home) / unit).read_text()
        except OSError:
            continue
        m = re.search(r"^ExecStart=.*\s--port[ =](\d+)", text, re.M)
        if m:
            return int(m.group(1))
    return None


def live_places(user_home: Path) -> set[Path]:
    """The live install's folders: the names of the home ``kranto.service`` names (its
    pointer and its unit), and that home's loop home and task folder."""
    from . import paths

    found = {_resolved(Path(user_home) / p.removeprefix("~/")) for p in LIVE_HOMES}
    for unit in LIVE_UNITS:
        _add_live_home(found, paths.recorded_home(Path(user_home), unit=unit))
    return {p for p in found if p is not None}


def _add_live_home(found: set, live_home: Path | None) -> None:
    found.add(_resolved(live_home))
    if live_home is not None:
        from .config import config_path
        path = config_path(Path(live_home))
        try:
            raw = yaml.safe_load(path.read_text()) if path else {}
            brb = (raw or {}).get("brb") or {}
            found.add(_resolved(brb.get("loop_home")))
            found.add(_resolved(brb.get("root")))
        except (OSError, yaml.YAMLError, AttributeError):
            pass


def refusal(home: Path, loop_home: Path | None, port: int | None,
            user_home: Path | None = None) -> str | None:
    """Why ``kranto serve`` must not start as the preview here, or None. Only asked with the
    switch on: a home or a loop home that is (or holds, or sits in) one of live's folders, or
    live's port."""
    user_home = Path(user_home or Path.home())
    live = live_places(user_home)
    for what, p in (("home", home), ("loop home", loop_home)):
        rp = _resolved(p)
        if rp is None:
            continue
        for lp in live:
            if rp == lp or lp in rp.parents or rp in lp.parents:
                return (f"this is the preview, and its {what} {rp} is the live install's "
                        f"({lp}): the preview runs only on a copy")
    ports = {LIVE_PORT, _live_unit_port(user_home)}
    if port is not None and int(port) in ports:
        return f"this is the preview, and port {port} is the live install's: use 8766"
    return None
