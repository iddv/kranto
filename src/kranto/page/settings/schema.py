"""What ``loop.yaml`` may hold, checked against ``DEFAULTS``.

``check(data)`` returns problems, each ``{"kind", "key", "detail"}``:

- ``unknown``: a key Kranto does not read (a typo, or a key from a newer version). Never an
  error: the file keeps it, Kranto ignores it, ``Config.problems`` lists it and the log says
  so once. An unknown key must never stop Kranto from starting.
- ``type``: a key Kranto reads, with a value of the wrong kind (``term.idle_min: "soon"``).
  Said the same way; the key then reads as what the file says, and its reader falls back to
  its default where it checks.

The shape is ``DEFAULTS``: a mapping's keys are known; a key whose default is None takes any
value; an empty mapping (``ask``) takes any key. A key in ``RETIRED`` is one an older Kranto
read: not a typo, so it is neither listed nor said.
"""
from __future__ import annotations

from .store import DEFAULTS

# spend caps are a number of dollars, or null (no cap)
USD_CAPS = {"term.daily_usd"}

# Keys an older Kranto read and this one does not: the file keeps them and nothing reads
# them. A whole section is retired by its name. The build loop and everything around it
# (pitches, the weekly editor, the checks, publishing, maintenance, projects) left in 0.7;
# the project chat's keys went before that.
RETIRED = {
    # top-level settings and sections of the build loop
    "tasks_dir", "concurrency", "daily_usd", "tick_s", "intake_every_s", "pitch_per_tick",
    "intake", "ideas", "fetch", "pitch", "exam", "corpus", "github", "publish", "revise",
    "mcp", "capabilities", "nudge", "feed", "chat", "maintain", "projects", "gate",
    # the build section's keys but the two the console still reads
    *(f"build.{k}" for k in (
        "policy", "harness", "owner", "max_usd", "models", "stage_caps", "retries",
        "max_resumes", "auto_repair", "flow", "fix_rounds", "kill_grace_s", "undo_s",
        "command", "revise_command")),
    # the page's own reads of the server's database file
    "kranto.db", "kranto.include_unsupported",
}


def _kind(v) -> str:
    if isinstance(v, bool):
        return "true or false"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "a mapping"
    return type(v).__name__


def _fits(default, value) -> bool:
    if default is None or value is None:
        return True
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, (list, tuple)):
        return isinstance(value, (list, tuple))
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


def check(data, defaults: dict = DEFAULTS) -> list[dict]:
    """The problems of a parsed ``loop.yaml`` (``{}`` for an empty file)."""
    out: list[dict] = []
    if data is None:
        return out
    if not isinstance(data, dict):
        return [{"kind": "type", "key": "", "detail": "loop.yaml is not a mapping of keys"}]

    def walk(node: dict, spec: dict, path: tuple):
        for k, v in node.items():
            here = (*path, str(k))
            key = ".".join(here)
            if k not in spec:
                if key not in RETIRED:
                    out.append({"kind": "unknown", "key": key, "detail": "not a key Kranto reads"})
                continue
            d = spec[k]
            if key in USD_CAPS and v is not None and (isinstance(v, bool)
                                                     or not isinstance(v, (int, float))):
                out.append({"kind": "type", "key": key,
                            "detail": f"should be a number of dollars or null, is {_kind(v)}"})
                continue
            if not _fits(d, v):
                out.append({"kind": "type", "key": key,
                            "detail": f"should be {_kind(d)}, is {_kind(v)}"})
                continue
            if isinstance(d, dict) and d and isinstance(v, dict):
                walk(v, d, here)

    walk(data, defaults, ())
    return out


def describe(problems: list[dict], limit: int = 5) -> str:
    """One line for a log or a status: ``loop.yaml: 2 unknown keys (ignored): a.b, c; 1 wrong
    value: term.idle_min: should be a number, is text``."""
    unk = [p["key"] for p in problems if p["kind"] == "unknown"]
    bad = [f"{p['key']}: {p['detail']}" for p in problems if p["kind"] == "type"]
    parts = []
    if unk:
        parts.append(f"{len(unk)} unknown key{'s' if len(unk) != 1 else ''} (ignored): "
                     + ", ".join(unk[:limit]) + (", ..." if len(unk) > limit else ""))
    if bad:
        parts.append(f"{len(bad)} wrong value{'s' if len(bad) != 1 else ''}: "
                     + "; ".join(bad[:limit]) + ("; ..." if len(bad) > limit else ""))
    return "loop.yaml: " + "; ".join(parts) if parts else ""
