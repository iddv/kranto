"""Why a Claude Code session stopped, from its stream-json events (moved from
``chat/failure.py``): ``classify(evs)`` is ``{"status": error|stopped, "class", "detail"}`` for
a failed session (an API error such as a 401, a budget or turn stop, no ``result`` at all), None
when it finished cleanly."""
from __future__ import annotations

import re

# an exit reason a run reports for a session with no result: what it means
EXITS = {"max_budget": ("stopped", "budget"), "max_turns": ("stopped", "turns"),
         "timeout": ("stopped", "timeout"), "error": ("error", "error")}


def _money(v) -> str:
    try:
        return f"${float(v):.2f}"
    except (TypeError, ValueError):
        return "$?"


def classify(evs: list[tuple[int, dict]], exit_reason: str | None = None) -> dict | None:
    """``{"status": error|stopped, "class", "detail"}`` for a failed session, None when it
    finished cleanly. ``evs``: ``[(line number, event)]``; ``exit_reason``: what the run said
    of a session with no result."""
    result = next((e for _, e in reversed(evs) if e.get("type") == "result"), None)
    retries = [e for _, e in evs if e.get("type") == "system" and e.get("subtype") == "api_retry"]
    if result is None:
        if exit_reason in EXITS and exit_reason != "error":
            st, cls = EXITS[exit_reason]
            return {"status": st, "class": cls, "detail": f"{cls}: the session was stopped "
                                                          f"({exit_reason}) before it finished"}
        return {"status": "stopped", "class": "no-result",
                "detail": "the session ended without a result (killed, timed out or crashed)"}
    sub, term = result.get("subtype") or "", result.get("terminal_reason")
    if not result.get("is_error") and sub == "success" and term in (None, "completed"):
        return None
    errs = " ".join(str(x) for x in result.get("errors") or [])
    if sub == "error_max_budget_usd" or term == "budget_exhausted":
        m = re.search(r"\$\s?([\d.]+)", errs)
        cap = f"the ${m.group(1)} cap" if m else "its cap"
        return {"status": "stopped", "class": "budget",
                "detail": f"budget: reached {cap} ({_money(result.get('total_cost_usd'))} spent"
                          f", {result.get('num_turns') or '?'} turns)"}
    if sub == "error_max_turns" or term == "max_turns":
        return {"status": "stopped", "class": "turns",
                "detail": f"turns: reached the turn limit ({result.get('num_turns') or '?'} turns)"}
    text = " ".join(str(result.get("result") or errs or "").split())[:200]
    status = next((r.get("error_status") for r in reversed(retries) if r.get("error_status")),
                  None) or result.get("api_error_status")
    err = next((r.get("error") for r in reversed(retries) if r.get("error")), None)
    why = text.split(": ", 1)[1] if text.startswith("Failed to authenticate: ") else text
    if status == 401 or err == "authentication_failed" or "authenticate" in text.lower():
        return {"status": "error", "class": "401-auth",
                "detail": f"401 {err or 'authentication_failed'}" + (f" ({why})" if why else "")}
    if status == 429 or err == "rate_limit":
        return {"status": "error", "class": "429-rate-limit",
                "detail": "429 rate limited" + (f" ({why})" if why else "")}
    if isinstance(status, int) and status >= 500:
        return {"status": "error", "class": "api-5xx",
                "detail": f"{status} {err or 'server error'}" + (f" ({why})" if why else "")}
    if term == "api_error" or status:
        code = f" {status}" if isinstance(status, int) else ""
        return {"status": "error", "class": "api-error",
                "detail": f"API error{code}" + (f" {err}" if err else "")
                          + (f" ({why})" if why else "")}
    return {"status": "error", "class": "error",
            "detail": f"{sub or term or 'error'}" + (f": {why}" if why else "")}
