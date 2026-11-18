"""Usage reports: counters on this machine, one daily report, an allow-list.

- ``record(name, **fields)``: one line, through the allow-list (``local.py``);
- ``status(home)``: the mode and why, what was sent, what is next (the CLI, Settings ›
  Privacy & access);
- ``set_mode(home, mode)``: the one setter (``kranto telemetry basic``, the wizard, Welcome,
  Settings › Privacy & access all write through it);
- ``report.build``, ``send.run`` and ``send.make_job``: the daily report and the hourly job.

Nothing leaves the machine unless the person chose ``basic`` or ``detailed``. Then one report
a day goes to ``local.DEFAULT_ENDPOINT`` (the controller's relay on AWS in the EU), unless
``$KRANTO_TELEMETRY_ENDPOINT`` or ``telemetry.endpoint`` names another."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from .local import (
    DNT,
    ENV_ENDPOINT,
    ENV_MODE,
    MODES,
    SENDING,
    TelemetryError,
    configure,
    configured,
    current_mode,
    effective,
    record,
)

__all__ = ["DNT", "ENV_ENDPOINT", "ENV_MODE", "MODES", "SENDING", "TelemetryError",
           "configure", "configured", "current_mode", "dismiss", "effective", "record",
           "remind", "set_mode", "status", "MEANING", "SUMMARY"]

# What each mode means, in one line (the CLI, the wizard, Welcome, Settings › Privacy & access).
MEANING = {
    "off": "nothing is counted and nothing is sent",
    "local": "counted on this machine only; nothing is sent",
    "basic": "one small report a day, and an error report when something fails, with no "
             "identifier",
    "detailed": "the daily report and error reports with a random id you can reset, and how "
                "Kranto's assistant tools are used: which verbs were called and how they ended, "
                "assistant sessions' length and Kranto's slash commands, hour by hour",
}
# The sentences shown before the choice.
SUMMARY = ("Kranto can send one small report a day about how it is used: the version, the "
           "operating system, which pages and buttons were used and how often, what the model "
           "calls cost. When something fails, an error report goes within minutes, with the "
           "error's type, where in Kranto's code it happened and its message with every word "
           "that could be yours removed. Never your topics, cards, posts, prompts, paths or "
           "keys. Reports carry no "
           "identifier. You can read every report before and after it is sent (kranto "
           "telemetry show), and stop at any time (kranto telemetry off, Settings › Privacy & "
           "access, or DO_NOT_TRACK=1). If you choose to send, reports go to a relay the "
           "maintainer runs on AWS in the EU; every field is listed in "
           "docs/privacy/what-kranto-sends.md.")
DOCS_LINK = "https://github.com/iddv/kranto/blob/main/docs/privacy/what-kranto-sends.md"


def set_mode(home: Path, mode: str) -> dict:
    """Write ``telemetry.mode`` and when it was answered; the new status. ``off`` also
    deletes the counters kept so far. Raises ``TelemetryError``."""
    from .. import config as config_mod
    from .. import setup
    from . import local

    if mode not in MODES:
        raise TelemetryError(f"the mode is one of {', '.join(MODES)}")
    path = config_mod.config_path(Path(home))
    if path is None:
        raise TelemetryError(f"no config file in {home}")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        setup.write_config_values(path, {("telemetry", "mode"): mode,
                                         ("telemetry", "answered_at"): now})
    except setup.SetupError as exc:
        raise TelemetryError(str(exc)) from exc
    if mode == "off":
        import shutil
        shutil.rmtree(local.tdir(home) / "local", ignore_errors=True)
    if mode not in SENDING:
        from . import errors
        errors.forget(home)          # the error reports waiting are never sent
    if mode != "detailed":
        from . import assistant
        assistant.forget(home)       # the assistant's events go with detailed only
    local.refresh()
    return status(home)


REMIND_AFTER_DAYS = 7


def remind(home: Path, st: dict | None = None) -> bool:
    """Today's one row: the question unanswered, ``local``, counting for seven
    days, and never dismissed."""
    from . import local

    st = st or status(home)
    if st["answered"] or st["mode"] != "local":
        return False
    state = local.read_state(home)
    if state.get("reminder_dismissed"):
        return False
    first = state.get("first_seen")
    if not first:
        state["first_seen"] = datetime.now(UTC).strftime("%Y-%m-%d")
        local.write_state(home, state)
        return False
    try:
        since = datetime.strptime(first[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return False
    return datetime.now(UTC) - since >= timedelta(days=REMIND_AFTER_DAYS)


def dismiss(home: Path) -> None:
    from . import local

    state = local.read_state(home)
    state["reminder_dismissed"] = datetime.now(UTC).isoformat(timespec="seconds")
    local.write_state(home, state)


def status(home: Path, environ=None) -> dict:
    """``{mode, why, meaning, answered, answered_at, endpoint, endpoint_from, sending,
    why_not, last_sent, next, sent_days, bytes_today, errors: {waiting, sent, last_sent}}``."""
    from . import local, send

    eff = effective(home, environ)
    sent = send.sent(home)
    why_not = None
    if eff.mode not in SENDING:
        why_not = MEANING[eff.mode]
    elif not eff.endpoint:
        why_not = "no endpoint is set: nothing leaves this machine"
    nxt = None
    if why_not is None:
        nxt = send.next_send(home, eff, datetime.now(UTC)).isoformat(timespec="minutes")
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    try:
        today_bytes = (local.tdir(home) / "local" / f"{today}.jsonl").stat().st_size
    except OSError:
        today_bytes = 0
    from . import errors
    err_sent = errors.sent(home)
    errs = {"waiting": sum(int(e.get("count") or 1) for e in errors.waiting(home))
            if why_not is None else 0,
            "sent": len(err_sent), "last_sent": err_sent[0] if err_sent else None}
    from . import assistant
    a_sent = assistant.sent(home)
    a_on = why_not is None and eff.mode == assistant.TIER
    asst = {"sending": a_on, "waiting": assistant.waiting_count(home) if a_on else 0,
            "sent": len(a_sent), "last_sent": a_sent[0] if a_sent else None}
    return {"mode": eff.mode, "why": eff.why, "meaning": MEANING[eff.mode], "errors": errs,
            "assistant": asst,
            "answered": eff.answered, "answered_at": eff.answered_at,
            "endpoint": eff.endpoint, "endpoint_from": eff.endpoint_from,
            "sending": why_not is None, "why_not": why_not,
            "last_sent": sent[0] if sent else None, "next": nxt,
            "sent_days": [s.get("day") for s in sent], "bytes_today": today_bytes,
            "dnt": local.dnt(environ)}
