"""Kranto's plugin and your own assistant (the owner's Q3, Q6 and Q9, 2026-10-25).

The plugin ships in the wheel (``kranto paths plugin``) and the the server repo is its marketplace.
(``claude plugin validate --strict`` passes on both; tests may not run the real Claude
Code.) Its skill's always-loaded description names the three locks; a description stays under
Claude Code's 1,536-character listing. Two hooks: Kranto's secrets are refused; Kranto's own tools
are
allowed without a second prompt (Kranto's ladder decides them), and nothing else is. ``kranto
assistant setup`` writes inside Kranto's home only and never replaces a file of yours; ``global``
shows the exact change and makes it only with ``--yes``."""

import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from kranto import assistant as A

REPO = Path(__file__).resolve().parents[1]
HOOKS = A.PLUGIN_DIR / "hooks"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, path
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def test_the_plugin_and_its_marketplace():
    manifest = json.loads((A.PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "kranto"
    assert manifest["mcpServers"]["kranto"] == {"type": "stdio", "command": "kranto",
                                               "args": ["mcp"]}
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    (entry,) = market["plugins"]
    assert entry["name"] == "kranto"
    assert (REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file()
    for name in A.SKILLS:
        fm = frontmatter(A.PLUGIN_DIR / "skills" / name / "SKILL.md")
        assert fm["name"] == name and fm["description"], name
        assert len(fm["description"]) < 1536, name
    desc = frontmatter(A.PLUGIN_DIR / "skills" / "kranto" / "SKILL.md")["description"]
    for lock in ("Keys and logins", "the broker", "ticket's confirm"):
        assert lock in desc
    hooks = json.loads((HOOKS / "hooks.json").read_text())
    for group in hooks["hooks"]["PreToolUse"]:
        for h in group["hooks"]:
            script = re.search(r"/hooks/(\w+\.py)", h["command"]).group(1)
            assert (HOOKS / script).is_file(), script


def hook(script: str, event: dict, env: dict | None = None) -> dict | None:
    r = subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(event),
                       capture_output=True, text=True, timeout=20, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_the_secrets_hook(tmp_path):
    home = tmp_path / "kb"
    env = {"HOME": str(tmp_path), "KRANTO_HOME": str(home), "PATH": "/usr/bin:/bin"}
    denied = [
        {"tool_name": "Read", "tool_input": {"file_path": f"{tmp_path}/.config/kranto/tokens/x"}},
        {"tool_name": "Read", "tool_input": {"file_path": f"{home}/data/secrets/k"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat .env"}, "cwd": str(home)},
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": f"{home}/.env"}},
        {"tool_name": "Edit", "tool_input": {"file_path": "~/.config/kranto/claude.env"}},
    ]
    for ev in denied:
        out = hook("secrets.py", ev, env)
        assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny", ev
    for ev in ({"tool_name": "Read", "tool_input": {"file_path": f"{home}/kranto.yaml"}},
               {"tool_name": "Bash", "tool_input": {"command": "kranto status"}},
               {"tool_name": "WebFetch", "tool_input": {"url": "https://x/.env"}}):
        assert hook("secrets.py", ev, env) is None, ev
    assert hook("secrets.py", {"tool_name": "Read", "tool_input": "x"}, env) is None


def test_the_allow_hook_is_for_kranto_tools_only():
    for name in ("mcp__plugin_kranto_kranto__kranto_topic_add", "mcp__kranto__kranto_publish"):
        out = hook("allow.py", {"tool_name": name})
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow", name
    for name in ("Bash", "mcp__evil__kranto_topic_add", "mcp__kranto__other",
                 "mcp__kranto__kranto_x; rm"):
        assert hook("allow.py", {"tool_name": name}) is None, name


def test_setup_writes_inside_kranto_home_only(tmp_path):
    home = tmp_path / "kb"
    home.mkdir()
    changes = A.plan(home)
    assert {c.state for c in changes} == {"new"}
    assert all(c.path.is_relative_to(home) for c in changes)
    names = {str(c.path.relative_to(home)) for c in changes}
    assert names == {"AGENTS.md", ".agents/skills/kranto/SKILL.md",
                     ".agents/skills/add-topic/SKILL.md", ".agents/skills/status/SKILL.md",
                     ".agents/skills/telemetry/SKILL.md",
                     ".agents/skills/report-issue/SKILL.md",
                     ".codex/agents/kranto-digger.toml", ".codex/hooks.json"}
    A.apply(changes)
    assert {c.state for c in A.plan(home)} == {"same"}
    hooks = json.loads((home / ".codex" / "hooks.json").read_text())
    assert "secrets.py" in hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    (home / "AGENTS.md").write_text("# mine\n")
    by = {c.path.name: c.state for c in A.plan(home)}
    assert by["AGENTS.md"] == "theirs"
    A.apply(A.plan(home))
    assert (home / "AGENTS.md").read_text() == "# mine\n"


def run_cli(argv, host):
    from kranto import launcher
    args = launcher.build_parser().parse_args(argv)
    return args.func(args, host)


def test_global_shows_first_and_changes_only_when_asked(tmp_path, capsys, monkeypatch):
    calls = []
    from kranto import launcher
    host = launcher.Host(home=tmp_path, which=lambda c: f"/bin/{c}",
                      run=lambda cmd, timeout=30: calls.append(cmd) or
                      SimpleNamespace(returncode=0))
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path / "kb"))
    assert run_cli(["assistant", "global", "codex"], host) == 0
    out = capsys.readouterr().out
    assert "$ codex mcp add kranto -- /bin/kranto mcp --compact" in out
    assert "Nothing was changed" in out and calls == []
    assert not (tmp_path / ".agents").exists()
    assert run_cli(["assistant", "global", "codex", "--yes"], host) == 0
    assert calls == [["codex", "mcp", "add", "kranto", "--", "/bin/kranto", "mcp", "--compact"]]
    skill = tmp_path / ".agents" / "skills" / "kranto-status" / "SKILL.md"
    assert "name: kranto-status" in skill.read_text()
    assert run_cli(["assistant", "global", "claude", "--yes"], host) == 0
    assert calls[-2:] == [["claude", "plugin", "marketplace", "add", "iddv/kranto"],
                          ["claude", "plugin", "install", "kranto@kranto"]]


def test_paths_plugin(capsys, tmp_path):
    from kranto import launcher
    assert run_cli(["paths", "plugin"], launcher.Host(home=tmp_path)) == 0
    assert capsys.readouterr().out.strip() == str(A.PLUGIN_DIR)
