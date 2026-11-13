"""Kranto's plugin hook (PreToolUse): an assistant never reads or edits Kranto's secrets.

Claude Code (and Codex, once its hooks are trusted) sends the tool call as JSON on stdin; this
answers ``deny`` when the call names one of Kranto's secret places: the keys under
``<home>/data/secrets/``, ``<home>/.env``, the tokens under ``~/.config/kranto/tokens/``,
``~/.config/kranto/claude.env``, and the assistants' own login files. Anything else passes
(exit 0, no answer). Stdlib only, so it starts in a few milliseconds; it never reads a secret.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
from pathlib import Path

TOOLS = {"Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Bash", "Grep", "Glob",
         "shell", "apply_patch", "read_file", "write_file"}
REASON = ("Kranto's secrets are off limits to the assistant (keys, tokens and logins are the "
          "owner's, on the page)")


def config_dirs() -> list[Path]:
    """Kranto's config folders: ``~/.config/kranto``, and any other folder there that holds a
    ``tokens`` folder (an install made before the product's rename keeps its own name). The
    hook runs alone, without the package, so it cannot ask which names those were."""
    base = Path.home() / ".config"
    found = [base / "kranto"]
    with contextlib.suppress(OSError):
        found += [d for d in sorted(base.iterdir()) if d not in found and (d / "tokens").is_dir()]
    return found


def kranto_home() -> Path | None:
    env = os.environ.get("KRANTO_HOME")
    if env:
        return Path(env).expanduser()
    for d in config_dirs():
        try:
            text = (d / "home").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return Path(text).expanduser()
    return None


def secret_places() -> list[str]:
    """The places, as text a path or a command would contain."""
    home = Path.home()
    out = [str(home / ".claude" / ".credentials.json"), str(home / ".codex" / "auth.json"),
           "/.config/kranto/tokens", "/.config/kranto/claude.env", "/data/secrets",
           ".credentials.json", ".codex/auth.json"]
    for d in config_dirs():
        out += [str(d / "tokens"), str(d / "claude.env"), f"/.config/{d.name}/tokens",
                f"/.config/{d.name}/claude.env"]
    b = kranto_home()
    if b is not None:
        out += [str(b / "data" / "secrets"), str(b / ".env")]
    return out


def texts(tool_input: dict) -> list[str]:
    """Every value of the call that could name a file: paths, patterns, a command."""
    out = []
    for k in ("file_path", "path", "notebook_path", "pattern", "glob", "command", "cmd",
              "patch", "input"):
        v = tool_input.get(k)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [str(x) for x in v]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict) and isinstance(edit.get("file_path"), str):
            out.append(edit["file_path"])
    return out


def names_secret(text: str, places: list[str], cwd: str | None) -> bool:
    t = os.path.expanduser(text)
    if cwd and not t.startswith("/") and not re.search(r"\s", t):
        t = os.path.normpath(os.path.join(cwd, t))
    if any(p in t for p in places):
        return True
    b = kranto_home()
    if b is not None and re.search(r"(^|[\s/'\"])\.env\b", t) and \
            (str(b) in t or (cwd and os.path.normpath(cwd) == os.path.normpath(str(b)))):
        return True
    return bool(re.search(r"(^|[\s/'\"])(data/secrets|\.config/kranto/tokens)(/|\b)", t))


def decide(event: dict) -> dict | None:
    if event.get("tool_name") not in TOOLS:
        return None
    ti = event.get("tool_input")
    if not isinstance(ti, dict):
        return None
    places = secret_places()
    if any(names_secret(t, places, event.get("cwd")) for t in texts(ti)):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "deny",
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
