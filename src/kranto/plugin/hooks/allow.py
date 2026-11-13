"""Kranto's plugin hook (PreToolUse): Kranto's own tools are not asked about twice.

Kranto decides on its side what an assistant may do with each of its tools (the owner's ladder,
Settings › Assistant: done, prepared for the owner's approval, or off; keys, the broker and a
ticket's confirm never). So the client's own permission prompt for a Kranto tool would ask the
owner a second time about the same thing: this answers ``allow`` for Kranto's tools only
(``mcp__plugin_kranto_kranto__*``, ``mcp__kranto__*``) and nothing else. Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys

KRANTO_TOOL = re.compile(r"mcp__(plugin_kranto_kranto|kranto)__kranto_[a-z0-9_]{1,100}")
REASON = "Kranto decides on its side, by the owner's ladder (Settings › Assistant)"


def decide(event: dict) -> dict | None:
    name = event.get("tool_name")
    if isinstance(name, str) and KRANTO_TOOL.fullmatch(name):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "allow",
                                       "permissionDecisionReason": REASON}}
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    out = decide(event) if isinstance(event, dict) else None
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
