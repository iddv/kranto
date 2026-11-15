"""The Claude token goes to ``claude`` through a pipe and nowhere else (TS.REVIEW R1;
box/handoff.py): the box's environment carries no login variable, the watcher's own provider
keys reach no process Kranto starts, and Kranto's shell prefix drops every login variable again for
each tool command. Canaries are made at run time. (The build loop's launches, its no-tools
prompts and the lab's calls left with it, CUT; the console's sessions are tested in
test_term_session.py and, in real bubblewrap, test_term_sandbox.py; the no-tools call in
test_print_call.py.)"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from kranto.page.box import handoff, sandbox, shell

from .term_common import canary

OAUTH, KEY = "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"


def test_the_sandbox_passes_no_login_variable():
    env = {OAUTH: "a", KEY: "b", "ANTHROPIC_AUTH_TOKEN": "c", "ANTHROPIC_BASE_URL": "u",
           "LANG": "C", "XAI_API_KEY": "d"}
    old = dict(os.environ)
    try:
        os.environ.update(env)
        got = sandbox.process_env()
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert got["ANTHROPIC_BASE_URL"] == "u" and got["LANG"] == "C"
    assert not any(k in got for k in handoff.LOGIN_VARS)


@pytest.mark.parametrize("name", ["XAI_API_KEY", "EXA_API_KEY", "BRAVE_API_KEY",
                                  "TAVILY_API_KEY"])
def test_a_watchers_key_reaches_no_process_kranto_starts(monkeypatch, name):
    monkeypatch.setenv(name, canary(name.split("_")[0].lower()))
    assert name not in handoff.process_env() and name in handoff.LOGIN_VARS
    script = (Path(handoff.__file__).parent / "kranto-shell").read_text()
    assert name in script.split("line=$1")[0]


def test_piped_hands_the_token_over_by_descriptor_only(monkeypatch):
    tok = canary("claude")
    monkeypatch.setenv(OAUTH, tok)
    monkeypatch.setattr(handoff, "_stored", lambda environ=None: None)
    env = {OAUTH: tok, "ANTHROPIC_AUTH_TOKEN": canary("gw"), "LANG": "C"}
    with handoff.piped(env) as fds:
        assert len(fds) == 1 and env[handoff.TOKEN_ENV[OAUTH]] == str(fds[0])
        assert os.read(fds[0], 4096).decode() == tok
        assert tok not in str(env) and "ANTHROPIC_AUTH_TOKEN" not in env
    monkeypatch.delenv(OAUTH)
    monkeypatch.delenv(KEY, raising=False)
    env = {}
    with handoff.piped(env) as fds:
        assert fds == () and not any(k in env for k in handoff.LOGIN_VARS)


# -- the shell prefix itself ----------------------------------------------------------------
def prefix(cmd: str, env: dict, kind: str) -> str:
    run_env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **env,
               **shell.env(kind, shell.install())}
    p = subprocess.run([run_env["CLAUDE_CODE_SHELL_PREFIX"], cmd], env=run_env,
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return p.stdout


def test_the_prefix_drops_every_login_variable(tmp_path):
    c = {k: canary("v") for k in handoff.LOGIN_VARS}
    other = canary("other")
    keep = prefix("env", {**c, "SOME_CAPABILITY_SETTING": other}, "plain")
    strict = prefix("env", {**c, "SOME_CAPABILITY_SETTING": other}, "term-plain")
    for value in c.values():
        assert value not in keep and value not in strict
    assert other in keep and other not in strict          # a session's prefix is strict


def test_the_prefix_refuses_anything_but_one_command_line():
    p = subprocess.run([str(shell.install()), "a", "b"], capture_output=True, text=True)
    assert p.returncode == 2 and "one command line" in p.stderr


def test_the_installed_prefix_is_the_scripts_and_executable(tmp_path):
    a = shell.install()
    assert a.read_bytes() == shell.SCRIPT.read_bytes() and os.access(a, os.X_OK)
    a.chmod(0o644)
    assert os.access(shell.install(), os.X_OK)            # repaired
    dest = shell.install(tmp_path / "x" / "kranto-shell")
    assert dest.is_file() and os.access(dest, os.X_OK)
