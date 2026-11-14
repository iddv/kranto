"""One ``claude -p`` call that can only answer, for the host's watcher (the server's Claude Code
provider, 4.5): ``host_api.claude_print``.

What the model can do is answer. The command has no tools (``--tools ""`` and
``--allowedTools ""``; with a schema the CLI adds only its StructuredOutput tool), no MCP server
(``--strict-mcp-config`` and no config), no settings, hooks or skills from the user's config or
the cwd (``--setting-sources ""``, ``--disable-slash-commands``), nothing that could prompt
(``--permission-prompts none``), no transcript (``--no-session-persistence``), and the stage's
own system prompt in place of Claude Code's. The item's text goes on stdin, never on the command
line. cwd is an empty directory the host owns. The Claude token, when Kranto has one, goes by pipe
(``handoff.piped``), never in the environment; without one, claude reads the user's own login as
``claude auth status`` does, and Kranto never reads it.

The session's init event is read back (``--output-format stream-json --verbose``): a session
that started with any tool but StructuredOutput, or with an MCP server, is refused as an error
whatever it answered. ``sandbox=True`` runs it under bubblewrap with Kranto's tokens, the GitHub
login, ssh keys and the kranto home's ``.env`` and secrets hidden (network is not limited: claude
needs Anthropic's API); off by default (MP D11).

No ledger row: the host records the call in its own ``llm_calls``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from kranto import legacy

ALLOWED_TOOLS = frozenset({"StructuredOutput"})
TAIL = 500


class PrintError(RuntimeError):
    """claude did not give a result: ``kind`` is ``missing`` (no claude on PATH), ``timeout``,
    ``exit`` (no result event; ``text`` holds the end of its output) or ``tools`` (the session
    had a tool or MCP server it must not have)."""

    def __init__(self, message: str, *, kind: str, text: str = "", exit_code: int | None = None):
        super().__init__(message)
        self.kind, self.text, self.exit_code = kind, text, exit_code


def command(*, system: str, model: str, schema: dict | None = None) -> list[str]:
    """The argv (golden-tested): everything but the prompt, which goes on stdin."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "stream-json", "--verbose",
           "--tools", "", "--allowedTools", "", "--strict-mcp-config",
           "--no-session-persistence", "--setting-sources", "", "--disable-slash-commands",
           "--permission-prompts", "none", "--system-prompt", system]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema, separators=(",", ":"), sort_keys=True)]
    return cmd


def _hidden(home: Path, kranto_home: Path | None) -> list[Path]:
    """What a sandboxed call cannot see: Kranto's tokens and GitHub logins, ssh keys, Kranto
    home's .env and secrets. Both config folders: an install made before the rename keeps its
    tokens in the old one."""
    out = [*legacy.config_dirs(home), home / ".config" / "gh", home / ".ssh"]
    if kranto_home is not None:
        out += [kranto_home / ".env", kranto_home / "data" / "secrets"]
    return out


def boxed(cmd: list[str], cwd: Path, *, kranto_home: Path | None = None) -> list[str]:
    """``cmd`` under bubblewrap: the file system as it is, the hidden paths masked (an empty
    tmpfs for a directory, /dev/null for a file), its own pid, ipc and uts namespaces."""
    home = Path(os.path.expanduser("~"))
    box = ["bwrap", "--bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
           "--new-session"]
    for p in _hidden(home, kranto_home):
        if p.is_dir():
            box += ["--tmpfs", str(p)]
        elif p.exists():
            box += ["--ro-bind", "/dev/null", str(p)]
    return box + ["--chdir", str(cwd), "--"] + cmd


def parse(stdout: str) -> tuple[dict | None, dict | None]:
    """(init event, result event) of a stream-json run."""
    init = result = None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        elif ev.get("type") == "result":
            result = ev
    return init, result


def claude_print(prompt: str, *, system: str, model: str, schema: dict | None = None,
                 timeout: float = 180, cwd: str | Path, sandbox: bool = False,
                 kranto_home: str | Path | None = None, environ: dict | None = None) -> dict:
    """Run one call; return its result event (``claude -p``'s JSON result: ``result``,
    ``structured_output``, ``is_error``, ``usage``, ``total_cost_usd``, ``modelUsage``...) with
    ``exit_code`` and ``init`` (``{"tools", "mcp_servers", "model"}``) added. A result that is an
    error (a usage limit, an expired login) is returned, not raised: the caller reads it.
    Raises ``PrintError`` when there is no result. ``environ``: Kranto's environment, whose
    token is piped (default: this process's)."""
    from . import handoff
    if shutil.which("claude", path=(environ or os.environ).get("PATH")) is None:
        raise PrintError("Claude Code is not installed (no claude on PATH)", kind="missing")
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True, mode=0o700)
    cmd = command(system=system, model=model, schema=schema)
    if sandbox:
        cmd = boxed(cmd, cwd, kranto_home=Path(kranto_home) if kranto_home else None)
    env = handoff.process_env(environ=environ)
    try:
        with handoff.piped(env, environ=environ) as fds:
            p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                               timeout=timeout, env=env, cwd=cwd, pass_fds=fds)
    except subprocess.TimeoutExpired:
        raise PrintError(f"claude did not answer within {timeout:g}s", kind="timeout") from None
    init, result = parse(p.stdout)
    if result is None:
        tail = (p.stdout[-TAIL:] + "\n" + p.stderr[-TAIL:]).strip()
        raise PrintError(f"claude exited {p.returncode} without a result: {tail[-300:]}",
                         kind="exit", text=tail, exit_code=p.returncode)
    tools = list((init or {}).get("tools") or [])
    mcp = list((init or {}).get("mcp_servers") or [])
    if set(tools) - ALLOWED_TOOLS or mcp:
        raise PrintError(f"claude started with tools {tools} and MCP servers {mcp}; refused",
                         kind="tools", exit_code=p.returncode)
    return {**result, "exit_code": p.returncode,
            "init": {"tools": tools, "mcp_servers": mcp, "model": (init or {}).get("model")}}
