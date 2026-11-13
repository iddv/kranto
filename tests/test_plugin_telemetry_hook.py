"""Kranto's plugin hook for the usage events (``plugin/hooks/telemetry.py``, TEL 2026-10-27): it
never slows or breaks a session (Kranto missing, slow or broken: exit 0, nothing printed, within
its timeout), prints only the one-time line, keeps nothing of a prompt but a Kranto slash
command's name, denies raising the telemetry consent, and is wired for every event it needs in
Claude Code's plugin and in Codex's hooks file."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kranto import assistant as asst

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "src" / "kranto" / "plugin" / "hooks" / "telemetry.py"
HOOKS_JSON = ROOT / "src" / "kranto" / "plugin" / "hooks" / "hooks.json"

START = {
    "hook_event_name": "SessionStart",
    "session_id": "s-1",
    "source": "startup",
    "model": "claude-sonnet-5-5",
    "cwd": "/home/someone/x",
    "transcript_path": "/home/someone/t",
}


def fake_kranto(tmp_path, body: str) -> dict:
    """A PATH whose only ``kranto`` runs ``body`` (Python)."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    b = d / "kranto"
    b.write_text(f"#!{sys.executable}\nimport sys, time, json\n{body}\n")
    b.chmod(0o755)
    return {"PATH": f"{d}:/usr/bin:/bin", "HOME": str(tmp_path)}


def run(event: dict, env: dict, arg="claude") -> tuple[subprocess.CompletedProcess, float]:
    t = time.monotonic()
    r = subprocess.run(
        [sys.executable, str(HOOK), arg],
        input=json.dumps(event).encode(),
        capture_output=True,
        env=env,
        timeout=20,
        check=False,
    )
    return r, time.monotonic() - t


EVENTS = [
    START,
    {"hook_event_name": "SessionEnd", "session_id": "s-1", "reason": "other"},
    {"hook_event_name": "UserPromptSubmit", "session_id": "s-1", "prompt": "/kranto:status please"},
    {
        "hook_event_name": "PostToolUse",
        "session_id": "s-1",
        "tool_name": "mcp__plugin_kranto_kranto__kranto_topic_add",
        "tool_input": {},
        "tool_response": {},
    },
    {
        "hook_event_name": "PostToolUseFailure",
        "session_id": "s-1",
        "tool_name": "mcp__plugin_kranto_kranto__kranto_topic_add",
        "error": "timed out",
    },
    {"hook_event_name": "Stop", "session_id": "s-1"},
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: e["hook_event_name"])
def test_with_kranto_missing_it_exits_0_at_once_and_prints_nothing(tmp_path, event):
    r, took = run(event, {"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b"" and took < 2


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: e["hook_event_name"])
def test_with_kranto_slow_it_exits_0_within_its_timeout_and_prints_nothing(tmp_path, event):
    env = fake_kranto(tmp_path, "time.sleep(8)\nprint(json.dumps({'systemMessage': 'late'}))")
    r, took = run(event, env)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    limit = 5 if event["hook_event_name"] == "SessionStart" else 3  # hooks.json's
    assert took < limit - 1, took


@pytest.mark.parametrize(
    "out", ["not json", '{"other": 1}', "", "[1, 2]", "Traceback (most recent call last):"]
)
def test_with_kranto_broken_it_prints_nothing(tmp_path, out):
    env = fake_kranto(tmp_path, f"sys.stdin.read()\nprint({out!r})\nsys.exit(1)")
    r, _ = run(START, env)
    assert r.returncode == 0 and r.stdout == b""


def test_the_one_time_line_is_its_only_output(tmp_path):
    env = fake_kranto(
        tmp_path,
        "ev = json.loads(sys.stdin.read())\n"
        "assert ev['event'] == 'start' and ev['assistant'] == 'claude-code'\n"
        "assert 'cwd' not in ev and 'transcript_path' not in ev\n"
        "print(json.dumps({'systemMessage': 'the line'}))",
    )
    r, _ = run(START, env)
    assert r.returncode == 0 and json.loads(r.stdout) == {"systemMessage": "the line"}


def test_garbage_in_is_silence(tmp_path):
    for raw in (b"", b"not json", b"[]", b'{"hook_event_name": 3}'):
        r = subprocess.run(
            [sys.executable, str(HOOK), "claude"],
            input=raw,
            capture_output=True,
            env={"PATH": str(tmp_path)},
            timeout=10,
            check=False,
        )
        assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


def _mod():
    import importlib.util

    spec = importlib.util.spec_from_file_location("kranto_hook_t", HOOK)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_prompt_is_kept_only_as_a_kranto_commands_name():
    m = _mod()
    assert (
        m.reduce({"hook_event_name": "UserPromptSubmit", "prompt": "fix /kranto:status x"}, {})
        is None
    )
    assert (
        m.reduce({"hook_event_name": "UserPromptSubmit", "prompt": "tell me a secret"}, {}) is None
    )
    ev = m.reduce(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s",
            "prompt": "/kranto:add-topic Marine robots /home/someone",
        },
        {},
    )
    assert ev == {"session": "s", "place": "outside", "event": "prompt", "command": "add-topic"}
    ev = m.reduce(
        {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}, {}
    )
    assert ev is None  # only Kranto's tools
    ev = m.reduce(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "s",
            "tool_name": "mcp__kranto__kranto_act",
            "tool_input": {"verb": "topic.add", "fields": {"name": "secret"}},
            "tool_response": {"isError": True, "error": "bad"},
        },
        {"KRANTO_MCP_CONSOLE": "codex"},
    )
    assert (
        ev["verb"] == "topic.add"
        and ev["event"] == "tool_failed"
        and ev["place"] == "console"
        and "fields" not in json.dumps(ev)
    )


@pytest.mark.parametrize(
    "cmd,denied",
    [
        ("kranto telemetry basic", True),
        ("cd ~ && kranto  telemetry detailed", True),
        ("kranto telemetry off", False),
        ("kranto telemetry show", False),
        ("ls", False),
    ],
)
def test_raising_consent_from_the_shell_is_denied(cmd, denied):
    out = _mod().guard(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}}
    )
    assert (out is not None) == denied
    if denied:
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "#/settings/privacy" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_writing_a_sending_mode_into_the_config_is_denied():
    m = _mod()
    deny = m.guard(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/x/kranto.yaml",
                "new_string": "telemetry:\n  mode: detailed\n",
            },
        }
    )
    assert deny is not None
    assert (
        m.guard(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/x/kranto.yaml",
                    "new_string": "telemetry:\n  mode: off\n",
                },
            }
        )
        is None
    )
    assert (
        m.guard(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": "/x/notes.md", "content": "mode: basic"},
            }
        )
        is None
    )


def test_the_plugin_wires_every_event_with_a_short_timeout():
    hooks = json.loads(HOOKS_JSON.read_text())["hooks"]
    for ev in (
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
        "PreToolUse",
    ):
        cmds = [h for g in hooks[ev] for h in g["hooks"] if "telemetry.py" in h["command"]]
        assert cmds, ev
        assert all(h["timeout"] <= 5 for h in cmds), ev
    for ev in ("PostToolUse", "PostToolUseFailure"):
        assert all("kranto" in g["matcher"] for g in hooks[ev])


def test_codex_gets_the_same_hook_where_its_events_allow():
    codex = json.loads(asst.home_files()[".codex/hooks.json"])["hooks"]
    for ev in (
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PostToolUse",
        "Stop",
        "PreToolUse",
    ):
        cmds = [h["command"] for g in codex[ev] for h in g["hooks"]]
        assert any("telemetry.py" in c and c.endswith(" codex") for c in cmds), ev
    assert all(h["timeout"] <= 3 for g in codex["SessionEnd"] for h in g["hooks"])
    assert ".agents/skills/telemetry/SKILL.md" in asst.home_files()


def test_the_hook_is_stdlib_only_and_opens_no_socket():
    import ast

    tree = ast.parse(HOOK.read_text())
    mods = {
        a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    } | {
        n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    assert mods <= {"__future__", "json", "os", "re", "shutil", "subprocess", "sys"}, mods
    assert "socket" not in HOOK.read_text() and "urllib" not in HOOK.read_text()
    assert os.environ.get("PATH") is not None
