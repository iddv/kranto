"""Continue outside (the owner's D3): ``kranto term open`` runs exactly the page's command, and
the page's Continue outside ends the page's process, puts the conversation where your own
Claude Code finds it, and gives the plain command with Kranto's tools and the same-limits one."""
from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from kranto.page.term import cli, service

from .term_common import Screen, canary, make_repo, make_term


@pytest.fixture
def term(tmp_path, monkeypatch):
    t = make_term(tmp_path, monkeypatch, token=canary("claude"),
                  source=make_repo(tmp_path / "source"), sandboxed=False)
    yield t
    for tid in list(t.live):
        t.end(tid, remove=False)


def test_kranto_term_open_runs_the_pages_own_command(term, monkeypatch):
    started = []
    real = service.Pty

    class Spy(real):
        def __init__(self, argv, **kw):
            started.append((argv, kw["env"]))
            super().__init__(argv, **kw)
    monkeypatch.setattr(service, "Pty", Spy)
    o = term.open({"kind": "project", "id": "p1"})
    term.end(o["tid"], remove=False)
    page_argv, page_env = started[0]
    env = {"CLAUDE_CODE_OAUTH_TOKEN": canary("claude"), "PATH": "/usr/bin:/bin"}
    term.serves = False
    argv, cenv = cli.command(term, o["tid"], env, 99)
    # the same command; the page's first start was a new session, this one resumes it only
    # when a transcript exists (none here)
    assert argv == page_argv
    for k in ("CLAUDE_CODE_SHELL_PREFIX", "CLAUDE_CONFIG_DIR", "KRANTO_SHELL", "KRANTO_SHELL_ENV"):
        assert cenv[k] == page_env[k]
    assert cenv["CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"] == "99"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] not in json.dumps([argv, cenv])


def test_the_token_comes_from_your_environment_or_your_claude_env(tmp_path):
    tok = canary("claude")
    assert cli.token_env({"CLAUDE_CODE_OAUTH_TOKEN": tok}, tmp_path)["CLAUDE_CODE_OAUTH_TOKEN"] \
        == tok
    f = tmp_path / ".config" / "kranto" / "claude.env"
    f.parent.mkdir(parents=True)
    f.write_text(f"# the unit's file\nCLAUDE_CODE_OAUTH_TOKEN={tok}\nOTHER=x\n")
    got = cli.token_env({"PATH": "/bin"}, tmp_path)
    assert got["CLAUDE_CODE_OAUTH_TOKEN"] == tok and "OTHER" not in got


def test_continue_outside_ends_here_and_gives_the_plain_and_the_same_limits_commands(term,
                                                                                  tmp_path):
    o = term.open({"kind": "project", "id": "p1"})
    scr = Screen()
    term.live[o["tid"]].pty.attach(scr)
    scr.wait("\n> ")
    term.live[o["tid"]].pty.write(b"say a first turn\n")
    scr.said("a first turn")
    mine = tmp_path / "my-claude"
    out = term.outside(o["tid"], config_dir=mine)
    rec = term.store.get(o["tid"])
    assert rec["reason"] == "outside" and o["tid"] not in term.live
    assert term.view(rec)["words"] == "Continued outside"
    assert list(mine.glob(f"projects/*/{rec['session']}.jsonl"))       # your Claude finds it
    words = shlex.split(out["plain"])
    assert words[:4] == ["cd", rec["cwd"], "&&", "claude"]
    assert words[words.index("--resume") + 1] == rec["session"]
    mcp = json.loads(words[words.index("--mcp-config") + 1])["mcpServers"]["kranto"]
    assert mcp == {"type": "stdio", "command": "kranto", "args": ["mcp", "--term", o["tid"]]}
    assert out["kranto"] == f"kranto term open {o['tid']}"
    assert Path(rec["cwd"]).is_dir()                                   # the copy stays
    assert (term.store.dir(o["tid"]) / "run" / "api.sock").exists()    # Kranto's tools still answer


def test_continue_outside_needs_a_conversation_first(term, tmp_path):
    o = term.open({"kind": "project", "id": "p1"})
    with pytest.raises(service.TermError) as e:
        term.outside(o["tid"], config_dir=tmp_path / "c")
    assert e.value.code == 409


def test_kranto_term_end_falls_back_to_this_process_when_kranto_is_not_running(term, capsys):
    o = term.open({"kind": "project", "id": "p1"})
    assert cli.cmd_end(term, o["tid"], url="http://127.0.0.1:9") == 0
    assert term.store.get(o["tid"])["removed"]
    assert cli.cmd_end(term, "00000000", url="http://127.0.0.1:9") == 2


def test_the_token_comes_from_the_file_the_unit_loads(tmp_path, monkeypatch):
    monkeypatch.delenv("KRANTO_UNIT", raising=False)
    tok = canary("claude")
    env = tmp_path / "secret" / "claude.env"
    env.parent.mkdir()
    env.write_text("CLAUDE_CODE_OAUTH_TOKEN=" + tok + "\n")
    d = tmp_path / ".config" / "systemd" / "user" / "kranto.service.d"
    d.mkdir(parents=True)
    (d / "20-claude-token.conf").write_text("[Service]\nEnvironmentFile=-%h/secret/claude.env\n")
    assert cli.env_files(tmp_path)[0] == env
    assert cli.token_env({"PATH": "/bin"}, tmp_path)["CLAUDE_CODE_OAUTH_TOKEN"] == tok
