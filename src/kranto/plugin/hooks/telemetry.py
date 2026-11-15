"""Kranto's plugin hook: what only the assistant's session sees, handed to the local Kranto for its
usage events (TEL, 2026-10-27), and the consent that stays the person's.

Run as ``python3 telemetry.py claude|codex`` on ``SessionStart``, ``SessionEnd``,
``UserPromptSubmit``, ``PostToolUse``/``PostToolUseFailure`` (Kranto's tools only), ``Stop`` and
``PreToolUse`` (Bash, Edit, Write). It reads the event on stdin and **reduces it first**: the
session id (Kranto keeps only a hash), the assistant, the model, console or outside, how the
session started or ended, a Kranto slash command's **name** (``/kranto:status``; the rest of the
prompt is never read further), a Kranto tool's verb name, and for a failed tool call its error
message, which Kranto's scrubber turns into a template of listed words before keeping. Then it
gives that to ``kranto telemetry event`` on stdin, which drops it unless the person chose to
send (detailed for these events; a console error follows the error reports' rule).

**It never touches the network and never holds a credential**: it starts a local command and
writes nothing itself. **It never slows or breaks a session**: every failure is silent, exit 0;
only a session's start waits for Kranto (at most ``START_WAIT_S``), for the one line Kranto shows
once to an install that never answered its telemetry question; every other event is handed
over without waiting. Its only output is that line, as ``{"systemMessage": ...}``.

``PreToolUse``: raising the telemetry consent is the person's own choice (the ladder's lock), so a
command that runs ``kranto telemetry basic|detailed`` or an edit that writes a sending mode into
``kranto.yaml`` is denied, with the page's address; ``kranto telemetry off`` passes.
Stdlib only."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

START_WAIT_S = 2.5
KRANTO_TOOL = re.compile(r"mcp__(?:plugin_kranto_kranto|kranto)__kranto_([a-z0-9_]{1,100})")
COMMAND = re.compile(r"\s*/kranto:([a-z][a-z0-9-]{0,40})(?:\s|$)")
VERB = re.compile(r"[a-z][a-z0-9_]{0,40}(?:\.[a-z0-9_-]{1,60}){1,2}")
TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,60}")
RAISE = re.compile(r"\bkranto\s+telemetry\s+(basic|detailed)\b")
YAML_RAISE = re.compile(r"\bmode\s*:\s*['\"]?(basic|detailed)\b")
DENY = ("Sending Kranto's usage reports is the owner's consent, given by them on the page "
        "(Settings › Privacy & access, #/settings/privacy) or in their own terminal; an "
        "assistant may prepare it (verb settings.telemetry) but never make it. Turning reports "
        "off needs no approval: kranto telemetry off.")


def _word(v) -> str | None:
    """A short token as an enum would be (a model's name, a reason): anything else, none."""
    return v if isinstance(v, str) and TOKEN.fullmatch(v) else None


def reduce(raw: dict, environ) -> dict | None:
    """The event as Kranto may keep it, or None. Nothing of the prompt beyond a Kranto slash
    command's name, nothing of a tool's input or result but the verb's name."""
    name = raw.get("hook_event_name")
    sid = raw.get("session_id") if isinstance(raw.get("session_id"), str) else None
    base = {"session": sid,
            "place": "console" if environ.get("KRANTO_MCP_CONSOLE") else "outside"}
    if name == "SessionStart":
        return {**base, "event": "start", "source": _word(raw.get("source")),
                "model": _word(raw.get("model"))}
    if name == "SessionEnd":
        return {**base, "event": "end", "reason": _word(raw.get("reason"))}
    if name == "Stop":
        return {**base, "event": "stop"}
    if name == "UserPromptSubmit":
        prompt = raw.get("prompt")
        m = COMMAND.match(prompt) if isinstance(prompt, str) else None
        return {**base, "event": "prompt", "command": m.group(1)} if m else None
    if name in ("PostToolUse", "PostToolUseFailure"):
        tool = raw.get("tool_name")
        m = KRANTO_TOOL.fullmatch(tool) if isinstance(tool, str) else None
        if not m:
            return None
        ev = {**base, "event": "tool", "tool": m.group(1)}
        ti = raw.get("tool_input")
        if m.group(1) == "act" and isinstance(ti, dict):    # the compact profile's one door
            v = ti.get("verb") or ti.get("kind")
            if isinstance(v, str) and VERB.fullmatch(v):
                ev["verb"] = v
        resp = raw.get("tool_response")
        failed = name == "PostToolUseFailure" or (isinstance(resp, dict) and (
            resp.get("isError") is True or resp.get("is_error") is True))
        if failed:
            err = raw.get("error")
            if not isinstance(err, str) and isinstance(resp, dict):
                err = resp.get("error") if isinstance(resp.get("error"), str) else ""
            err = err if isinstance(err, str) else ""
            ev.update(event="tool_failed", message=err[:2000],
                      failure="timeout" if re.search(r"time[ds]? ?out", err, re.I) else "error")
        return ev
    return None


def guard(raw: dict) -> dict | None:
    """``PreToolUse``: deny raising the telemetry consent from the assistant."""
    ti = raw.get("tool_input")
    if not isinstance(ti, dict):
        return None
    tool = raw.get("tool_name")
    hit = False
    if tool in ("Bash", "shell"):
        cmd = ti.get("command")
        cmd = " ".join(cmd) if isinstance(cmd, list) else cmd
        hit = isinstance(cmd, str) and bool(RAISE.search(cmd))
    elif tool in ("Edit", "Write", "MultiEdit", "apply_patch"):
        path = str(ti.get("file_path") or ti.get("path") or "")
        text = " ".join(str(ti.get(k) or "") for k in ("new_string", "content", "patch",
                                                         "input"))
        text += " ".join(str(e.get("new_string") or "") for e in ti.get("edits") or []
                         if isinstance(e, dict))
        hit = (path.endswith("kranto.yaml") or "kranto.yaml" in text) and \
            bool(YAML_RAISE.search(text))
    if not hit:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": DENY}}


def hand_over(ev: dict, wait: bool) -> str | None:
    """Give the event to ``kranto telemetry event``. ``wait``: up to ``START_WAIT_S`` for its
    one-time line; else started on its own and not waited for."""
    kranto = shutil.which("kranto")
    if not kranto:
        return None
    data = json.dumps(ev).encode()
    if not wait:
        p = subprocess.Popen([kranto, "telemetry", "event"], stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
        if p.stdin is not None:
            try:
                p.stdin.write(data)
                p.stdin.close()
            except OSError:
                pass
        return None
    r = subprocess.run([kranto, "telemetry", "event"], input=data, capture_output=True,
                       timeout=START_WAIT_S, check=False)
    try:
        out = json.loads(r.stdout or b"{}")
    except ValueError:
        return None
    line = out.get("systemMessage") if isinstance(out, dict) else None
    return line if isinstance(line, str) and len(line) < 400 else None


def main(argv: list[str]) -> int:
    try:
        raw = json.loads(sys.stdin.read(1_000_000) or "{}")
        if not isinstance(raw, dict):
            return 0
        if raw.get("hook_event_name") == "PreToolUse":
            out = guard(raw)
            if out is not None:
                print(json.dumps(out))
            return 0
        ev = reduce(raw, os.environ)
        if ev is None:
            return 0
        ev["assistant"] = "codex" if argv[1:2] == ["codex"] else "claude-code"
        ev["profile"] = "compact" if ev["assistant"] == "codex" else "full"
        line = hand_over(ev, wait=ev["event"] == "start")
        if line:
            print(json.dumps({"systemMessage": line}))
    except Exception:  # noqa: BLE001 - a hook never breaks a session, whatever happens
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
