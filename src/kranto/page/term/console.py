"""The console: your own Claude Code (or Codex) docked in Kranto's page (with the
owner's answers of 2026-10-25).

One long-lived terminal session per harness per install, served by ``term`` like Open in
Claude Code's (the PTY, its ring, the viewers, the one-time tickets), with three differences:
it runs **as you, unsandboxed, in Kranto's home** (the loop home and the tasks root added), it is
**never reaped** for idleness and does not count against ``term.max_sessions``, and it
**resumes by default** (Claude Code ``--session-id`` the first time, ``--resume`` after; ``/clear``
is noticed from the status line's ``session_id`` and the record follows it).

What it starts with (``ask:`` in ``loop.yaml``; Settings › Assistant):

- ``harness``: ``claude`` (first when installed) or ``codex``; each keeps its own conversation.
- ``model.<harness>``: ``--model`` / ``-m``; unset: the harness's own default.
- ``open``: the panel opens with the page by itself. Default true for a home whose loop.yaml
  does not say; a home made by ``kranto up`` from 0.7.0 on says false (``NEW_HOME``).
- ``permission``: ``auto`` (the owner's Q3: Claude Code's auto mode) · ``ask`` (asks before
  edits and commands) · ``accept-edits``. Bypass is refused. Default ``auto`` when loop.yaml
  does not say; a new home says ``ask`` (``NEW_HOME``).
- ``config``: ``own`` (your login, settings, plugins, MCP servers and CLAUDE.md: it is your
  Claude Code) or ``kranto`` (Kranto's plugin and settings only, a config dir of its own, Kranto's
  Claude token by pipe as Open in Claude Code has it). Switching offers a restart (the page).
- ``daily_usd``: none by default (the owner's rule); with one, the session ends at the cap.

Kranto's tools come from **Kranto's plugin** (``--plugin-dir``: its skill, its agent, its hooks and
its MCP server). The environment says ``KRANTO_MCP_CONSOLE=<harness>``, so the plugin's ``kranto
mcp`` acts with the console's own token and name: one Kranto server, attributed "by Claude
Code". Codex has no per-session plugin: its server comes from ``-c mcp_servers.kranto…`` with
``--compact`` (no tool search), the skills and the hook from Kranto's home (``kranto assistant
setup``). Codex's side is built from its documentation (0.164.0) and could not be run here.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kranto import legacy

from .. import paths

HARNESSES: dict[str, dict[str, Any]] = {
    "claude": {"name": "Claude Code", "bin": "claude",
               "models": [("claude-sonnet-5-5", "Sonnet 5.5"), ("claude-opus-5-5", "Opus 5.5"),
                          ("claude-haiku-5-5", "Haiku 5.5"), ("claude-fable-5-1", "Fable 5.1")],
               "new": "/clear", "extras": True},
    "codex": {"name": "Codex", "bin": "codex", "models": [], "new": "/new", "extras": False},
}
ORDER = ("claude", "codex")
PERMISSIONS = ("auto", "ask", "accept-edits")
CONFIGS = ("own", "kranto")
DEFAULTS: dict[str, Any] = {"open": True, "harness": None, "model": {}, "permission": "auto", "config": "own",
            "daily_usd": None}
# A home made from now on starts safer than DEFAULTS (the operator's S1 of 2026-11-17): the
# console does not open by itself and asks before every edit and command, until the person
# turns it up in Settings › Assistant. ``kranto up`` writes these into a new home's loop.yaml
# (``NEW_HOME_YAML``); a home whose loop.yaml does not say keeps DEFAULTS, as before.
NEW_HOME: dict[str, Any] = {"open": False, "permission": "ask"}
NEW_HOME_YAML = (
    "# The console (your own Claude Code or Codex beside every page; Settings › Assistant).\n"
    "# A new home's does not open by itself and asks before every edit and command; turn it\n"
    "# up in Settings › Assistant. Without these lines it opens by itself in auto mode.\n"
    "ask:\n"
    "  open: false\n"
    "  permission: ask\n")
PERMISSION_WORDS = {"auto": "decides edits and commands by itself (Claude Code's auto mode)",
                    "ask": "asks before every edit and command",
                    "accept-edits": "makes edits by itself and asks before commands"}
CLAUDE_MODE = {"auto": "auto", "ask": "default", "accept-edits": "acceptEdits"}
CODEX_APPROVAL = {"auto": "on-request", "ask": "untrusted", "accept-edits": "on-request"}
CONSOLE_ENV = "KRANTO_MCP_CONSOLE"
URL_ENV = "KRANTO_MCP_URL"
SECRET_GLOBS = ("data/secrets/**", ".env")


def settings(cfg: dict | None) -> dict:
    """``ask:`` with its defaults; a value of the wrong shape reads as its default."""
    raw = (cfg or {}).get("ask") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = dict(DEFAULTS)
    if isinstance(raw.get("open"), bool):
        out["open"] = raw["open"]
    if raw.get("harness") in HARNESSES:
        out["harness"] = raw["harness"]
    if isinstance(raw.get("model"), dict):
        out["model"] = {k: str(v) for k, v in raw["model"].items()
                        if k in HARNESSES and isinstance(v, str) and v}
    if raw.get("permission") in PERMISSIONS:
        out["permission"] = raw["permission"]
    if raw.get("config") in CONFIGS:
        out["config"] = raw["config"]
    d = raw.get("daily_usd")
    if isinstance(d, int | float) and not isinstance(d, bool) and d > 0:
        out["daily_usd"] = float(d)
    return out


def describe(cfg: dict | None) -> dict[str, Any]:
    """What the console does in this home, for ``kranto doctor`` and the docs: ``{open,
    permission, said, words}``. ``said`` is whether loop.yaml (or Settings › Assistant) chose
    each, else Kranto's default (DEFAULTS) is in force; ``words`` is one plain line."""
    raw = (cfg or {}).get("ask") if isinstance(cfg, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    s = settings(cfg)
    said = isinstance(raw.get("open"), bool) and raw.get("permission") in PERMISSIONS
    opens = "opens by itself" if s["open"] else "opens when you click ✦ (or ⌘J)"
    words = f"{opens}; {PERMISSION_WORDS[s['permission']]}"
    if not said:
        words += " (Kranto's default when loop.yaml does not say; Settings › Assistant changes it)"
    else:
        words += " (Settings › Assistant changes it)"
    return {"open": s["open"], "permission": s["permission"], "said": said, "words": words}


def doctor_line(loop_home: str | Path) -> str:
    """``describe``'s words for the home whose page settings live in ``loop_home`` (its
    loop.yaml as written, never merged with DEFAULTS); an unreadable file reads as empty."""
    import yaml

    try:
        raw = yaml.safe_load(paths.LoopLayout(Path(loop_home)).settings.read_text("utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        raw = None
    return describe(raw if isinstance(raw, dict) else None)["words"]


def installed(environ=None) -> dict[str, str]:
    """The harnesses on Kranto's PATH: ``{harness: path}``, Claude Code first."""
    env = os.environ if environ is None else environ
    out = {}
    for h in ORDER:
        p = shutil.which(str(HARNESSES[h]["bin"]), path=env.get("PATH"))
        if p:
            out[h] = p
    return out


def chosen(cfg: dict | None, environ=None) -> str | None:
    """The harness the console opens: the setting when installed, else the first installed."""
    have = installed(environ)
    h = settings(cfg)["harness"]
    if h in have:
        return h
    return next(iter(have), None)


def outside_servers(harness: str, config: str, environ=None, cwd: Path | None = None) -> list[str]:
    """The MCP servers your own configuration adds to the console besides Kranto's (the owner's
    Q2: the panel lists them), by name only: Claude Code's user servers and this folder's
    (``~/.claude.json`` ``mcpServers`` and ``projects[<Kranto's home>].mcpServers``, the folder's
    ``.mcp.json``), Codex's ``[mcp_servers.<name>]`` in ``~/.codex/config.toml``. With Kranto's
    configuration none load. Nothing else of those files is read into the answer."""
    if config != "own":
        return []
    env = os.environ if environ is None else environ
    home = Path(env.get("HOME") or Path.home())
    here = str(cwd or kranto_home())
    names: set[str] = set()

    def keys(obj: Any) -> set[str]:
        return {str(k) for k in obj} if isinstance(obj, dict) else set()
    try:
        if harness == "claude":
            for p in (home / ".claude.json", Path(here) / ".mcp.json"):
                if p.is_file():
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        names |= keys(data.get("mcpServers"))
                        proj = data.get("projects")
                        if isinstance(proj, dict):
                            names |= keys((proj.get(here) or {}).get("mcpServers"))
        elif harness == "codex":
            import tomllib
            p = Path(env.get("CODEX_HOME") or home / ".codex") / "config.toml"
            if p.is_file():
                names |= keys(tomllib.loads(p.read_text(encoding="utf-8")).get("mcp_servers"))
    except (OSError, ValueError, AttributeError):
        return []
    names.discard("kranto")
    names.discard(legacy.MCP_SERVER)      # Kranto too: the entry added before the rename
    return sorted(n[:60] for n in names)


def plugin_dir() -> Path | None:
    """Kranto's plugin: the copy Kranto wrote in its home without the skill of a feature that is
    off (``<home>/assistant/plugin``,.2), else Kranto package's own
    (``kranto paths plugin``)."""
    try:
        copy = kranto_home() / "assistant" / "plugin"
        if (copy / ".claude-plugin" / "plugin.json").is_file():
            return copy
    except OSError:
        pass
    spec = importlib.util.find_spec("kranto")
    if spec is None or not spec.origin:
        return None
    d = Path(spec.origin).parent / "plugin"
    return d if (d / ".claude-plugin" / "plugin.json").is_file() else None


def kranto_home() -> Path:
    """Kranto's home (``$KRANTO_HOME``, else the one ``kranto up`` recorded), the console's folder;
    your home when neither says."""
    found = paths.kranto_home(user_home=Path.home(), default=None)
    return Path(found) if found else Path.home()


@dataclass
class Spec:
    """One console's launch."""
    tid: str
    harness: str
    tdir: Path                                  # <loop home>/term/<tid>
    cwd: Path                                   # Kranto's home
    session: str | None = None                  # Claude Code's session id (Codex: none)
    resume: bool = False
    model: str | None = None
    permission: str = "auto"
    config: str = "own"
    add_dirs: tuple = ()
    plugin: Path | None = None
    binary: str = ""
    kranto_url: str | None = None                # Kranto that started it (kranto mcp's)
    extra_env: dict = field(default_factory=dict)

    @property
    def meter(self) -> Path:
        return self.tdir / "meter"

    @property
    def claude_dir(self) -> Path | None:
        """The config dir of a kranto-scoped console (``config: Kranto``); yours otherwise."""
        return self.tdir / "claude" if self.config == "kranto" else None


def claude_settings(spec: Spec) -> dict:
    meter = spec.meter / "status.json"
    deny = []
    for g in SECRET_GLOBS:          # Edit covers every editing tool (Write, MultiEdit)
        for tool in ("Read", "Edit"):
            deny.append(f"{tool}({spec.cwd}/{g})")
    for p in tuple(f"~/.config/{d.name}/{f}" for d in legacy.config_dirs()
                   for f in ("tokens/**", "claude.env")):
        deny += [f"Read({p})", f"Edit({p})"]
    here = spec.meter / "here.txt"
    # Claude Code hands the line its session's JSON (cost, model, session_id): Kranto keeps it
    # in meter/, and the line under the prompt says the page you are on (never the model's)
    line = (f"cat > {meter}.tmp && mv -f {meter}.tmp {meter}; "
            f"printf 'Kranto · %s' \"$(cat {here} 2>/dev/null)\"")
    return {"permissions": {"deny": deny, "disableBypassPermissionsMode": "disable"},
            "includeCoAuthoredBy": False,
            "statusLine": {"type": "command", "command": line, "padding": 0},
            "cleanupPeriodDays": 3650}


def claude_args(spec: Spec) -> list[str]:
    args = ["--permission-mode", CLAUDE_MODE.get(spec.permission, "auto"),
            "--settings", json.dumps(claude_settings(spec), separators=(",", ":"))]
    for d in spec.add_dirs:
        args += ["--add-dir", str(d)]
    if spec.plugin is not None:
        args += ["--plugin-dir", str(spec.plugin)]
    if spec.model:
        args += ["--model", spec.model]
    if spec.session:
        args += ["--resume", spec.session] if spec.resume else ["--session-id", spec.session]
    return args


def kranto_command() -> list[str]:
    """``kranto mcp`` as this install runs it: the ``kranto`` on PATH, else this python."""
    b = shutil.which("kranto")
    return [b, "mcp"] if b else [sys.executable, "-m", "kranto.page.mcp.server"]


def codex_args(spec: Spec) -> list[str]:
    cmd = kranto_command()
    server = [*cmd[1:], "--compact", "--console", "codex"]
    if spec.kranto_url:
        server += ["--url", spec.kranto_url]
    args = ["resume", "--last"] if spec.resume else []
    args += ["--cd", str(spec.cwd)]
    for d in spec.add_dirs:
        args += ["--add-dir", str(d)]
    args += ["-a", CODEX_APPROVAL.get(spec.permission, "on-request"), "-s", "workspace-write",
             "-c", f"mcp_servers.kranto.command={json.dumps(cmd[0])}",
             "-c", f"mcp_servers.kranto.args={json.dumps(server)}"]
    if spec.model:
        args += ["-m", spec.model]
    return args


def argv(spec: Spec) -> list[str]:
    if spec.harness == "claude":
        return [spec.binary or "claude", *claude_args(spec)]
    if spec.harness == "codex":
        return [spec.binary or "codex", *codex_args(spec)]
    raise ValueError(f"no harness {spec.harness!r}")


def env(spec: Spec, environ=None, token: tuple[str, int] | None = None) -> dict:
    """Your environment (it is you), with the console's marks: the plugin's ``kranto mcp`` acts
    as the console, the terminal's type, and for a kranto-scoped Claude Code its own config dir
    and Kranto's token by pipe (``token``: the variable and the descriptor)."""
    from ..box import handoff
    out: dict[str, str] = dict(os.environ if environ is None else environ)
    # a harness's own markers Kranto's process may have inherited (Kranto started from inside a
    # Claude Code session) are not the console's: they would change how it behaves
    for k in [k for k in out if k == "CLAUDECODE" or (k.startswith("CLAUDE_CODE_")
                                                       and k not in handoff.TOKEN_FD_ENV)]:
        out.pop(k)
    out.update({CONSOLE_ENV: spec.harness, "TERM": "xterm-256color", "COLORTERM": "truecolor"})
    if spec.kranto_url:
        out[URL_ENV] = spec.kranto_url
    if spec.claude_dir is not None:
        handoff.scrub(out)
        out["CLAUDE_CONFIG_DIR"] = str(spec.claude_dir)
        if token is not None:
            var, fd = token
            out[handoff.TOKEN_ENV[var]] = str(fd)
    out.update(spec.extra_env)
    return out


def transcript(spec: Spec, session: str | None, environ=None) -> Path | None:
    """Claude Code's transcript of ``session`` (for the meter); None for Codex."""
    if spec.harness != "claude" or not session:
        return None
    from ..box.claude_dirs import project_key
    env_ = os.environ if environ is None else environ
    base = spec.claude_dir or Path(env_.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return Path(base) / "projects" / project_key(Path(spec.cwd)) / f"{session}.jsonl"


LAST_LINES = 6        # what it last said: the reply's first lines (R11: short first)
LAST_CHARS = 600
TAIL_BYTES = 256_000  # a transcript is read from its end: the last reply is near it
PAGE_LINK = re.compile(r"(?:https?://[^\s)\]]+)?(#/[\w\-/:%?=&.]+)")


def last_reply(path: Path | None) -> dict:
    """What the console last said, for the phone's sheet: the newest
    assistant turn's text in Claude Code's transcript, its first lines, when, and the first Kranto
    page it linked (``#/…``). ``{"said": None, "why": …}`` when there is none to read: Codex
    keeps no transcript here, a conversation not started has none, a reply that only ran tools
    has no words."""
    if path is None:
        return {"said": None, "why": "this assistant keeps no transcript Kranto can read"}
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return {"said": None, "why": "no conversation yet"}
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except ValueError:
            continue                                   # a line cut by the tail's start
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        content = (row.get("message") or {}).get("content")
        texts: list[str] = [str(c["text"]) for c in content if isinstance(c, dict)
                            and c.get("type") == "text" and isinstance(c.get("text"), str)] \
            if isinstance(content, list) else []
        text = "\n".join(t for t in texts if t.strip()).strip()
        if not text:
            continue
        kept = [ln for ln in text.splitlines() if ln.strip()][:LAST_LINES]
        said = "\n".join(kept)
        if len(said) > LAST_CHARS:
            said = said[:LAST_CHARS - 1].rstrip() + "…"
        link = PAGE_LINK.search(text)
        return {"said": said, "more": said != text, "at": row.get("timestamp"),
                "page": link.group(1) if link else None}
    return {"said": None, "why": "it has not said anything yet"}


def head_words(harness: str, model: str | None, permission: str) -> dict:
    """The panel's head, in words: "Claude Code · Sonnet 5.5 · works by itself"."""
    h = HARNESSES[harness]
    name = dict(h["models"]).get(model or "", model) if model else None
    mode = {"auto": "decides edits and commands by itself (auto mode)",
            "ask": "asks before edits and commands",
            "accept-edits": "edits by itself, asks before commands"}[permission]
    return {"harness": h["name"], "model": name, "mode": mode,
            "extras": h["extras"],
            "note": None if h["extras"] else
            "Codex works with fewer extras: no status line, and its cost is not reported"}
