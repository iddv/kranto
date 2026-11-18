"""The console: your own assistant docked in Kranto's page, on the term machinery.

One session per harness, as you, in Kranto's home, never reaped for idleness and not counted
against Open in Claude Code's cap; resumed by default (``--session-id``, then ``--resume``);
``/clear`` followed from the status line's ``session_id``; Kranto's plugin loaded and its
``kranto mcp`` told it is the console. The fake Claude Code TUI stands in (no model, no
network); Codex is checked by its command line only."""
import json
import time

import pytest
import yaml

from kranto.page.term import console as C
from kranto.page.term.service import TermError

from .term_common import Screen, canary, make_term


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    (tmp_path / "user").mkdir()
    kb = tmp_path / "kb"
    kb.mkdir()
    monkeypatch.setenv("KRANTO_HOME", str(kb))
    return kb


@pytest.fixture
def term(tmp_path, monkeypatch, home):
    plugin = tmp_path / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text('{"name": "kranto"}')
    monkeypatch.setattr(C, "plugin_dir", lambda: plugin)
    t = make_term(tmp_path, monkeypatch, token=canary("claude"), sandboxed=False,
                  idle_min=0.0001, max_sessions=1)
    # only the fake Claude Code on PATH: a real claude or codex here is never started
    fake = tmp_path / "claude-install"
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    yield t
    for tid in list(t.live):
        t.end(tid, remove=False)


def attach(term, out) -> Screen:
    scr = Screen()
    term.live[out["tid"]].pty.attach(scr)
    scr.wait("> ")
    return scr


def argv_of(scr: Screen) -> list:
    line = next(ln for ln in scr.text.splitlines() if ln.startswith("argv: "))
    return json.loads(line[len("argv: "):])


def test_settings_read_with_their_defaults():
    assert C.settings({}) == C.DEFAULTS
    s = C.settings({"ask": {"open": False, "harness": "codex", "permission": "ask",
                            "config": "kranto", "model": {"claude": "claude-opus-5-5", "x": "y"},
                            "daily_usd": 2}})
    assert s == {"open": False, "harness": "codex", "permission": "ask", "config": "kranto",
                 "model": {"claude": "claude-opus-5-5"}, "daily_usd": 2.0}
    bad = C.settings({"ask": {"open": "yes", "harness": "gemini", "permission": "bypass",
                              "config": None, "model": "opus", "daily_usd": True}})
    assert bad == C.DEFAULTS


def test_the_own_config_saved_before_the_rename_still_means_kranto_s():
    """The old page saved "the product's own config" under the old name; read as ``kranto``,
    not dropped to the person's own ``~/.claude``."""
    from kranto import legacy

    assert C.settings({"ask": {"config": legacy.CONSOLE_CONFIG}})["config"] == "kranto"
    assert C.settings({"ask": {"config": "own"}})["config"] == "own"


def test_claude_codes_command_line(tmp_path, home):
    spec = C.Spec(tid="c1", harness="claude", tdir=tmp_path / "t", cwd=home, session="s1",
                  add_dirs=("/loop", "/tasks"), plugin=tmp_path / "plugin")
    a = C.argv(spec)
    assert a[:3] == ["claude", "--permission-mode", "auto"]
    assert a[a.index("--plugin-dir") + 1] == str(tmp_path / "plugin")
    assert a[-2:] == ["--session-id", "s1"] and "--add-dir" in a
    settings = json.loads(a[a.index("--settings") + 1])
    assert f"Read({home}/data/secrets/**)" in settings["permissions"]["deny"]
    assert settings["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert "status.json" in settings["statusLine"]["command"]
    spec.resume, spec.permission, spec.model = True, "ask", "claude-opus-5-5"
    a = C.argv(spec)
    assert a[-4:] == ["--model", "claude-opus-5-5", "--resume", "s1"]
    assert a[a.index("--permission-mode") + 1] == "default"
    env = C.env(spec, {"PATH": "/bin", "HOME": "/h"})
    assert env["KRANTO_MCP_CONSOLE"] == "claude" and "CLAUDE_CONFIG_DIR" not in env
    spec.config = "kranto"
    env = C.env(spec, {"PATH": "/bin", "CLAUDE_CODE_OAUTH_TOKEN": "x"},
                ("CLAUDE_CODE_OAUTH_TOKEN", 7))
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "t" / "claude")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR"] == "7"


def test_codexs_command_line(tmp_path, home):
    spec = C.Spec(tid="c2", harness="codex", tdir=tmp_path / "t", cwd=home,
                  add_dirs=("/loop",))
    a = C.argv(spec)
    assert a[0] == "codex" and a[1:3] == ["--cd", str(home)]
    assert a[a.index("-a") + 1] == "on-request" and a[a.index("-s") + 1] == "workspace-write"
    servers = [x for x in a if x.startswith("mcp_servers.kranto.args=")]
    assert servers and "--compact" in servers[0] and '"--console", "codex"' in servers[0]
    spec.resume = True
    assert C.argv(spec)[1:3] == ["resume", "--last"]
    assert C.head_words("codex", None, "auto")["note"].startswith("Codex works with fewer")


def test_the_console_runs_resumes_and_follows_clear(term, home):
    st = term.console_state()
    assert st["harness"] == "claude" and st["plugin"]
    assert {h["id"]: h["installed"] for h in st["harnesses"]} == {"claude": True,
                                                                  "codex": False}
    out = term.open_console(cols=90, rows=20)
    scr = attach(term, out)
    a = argv_of(scr)
    assert "--session-id" in a and "--plugin-dir" in a
    rec = term.store.get(out["tid"])
    assert rec["console"] and rec["cwd"] == str(home) and out["harness"] == "claude"
    # not Open in Claude Code's: not listed there, not counted against its cap
    assert all(s["tid"] != out["tid"] for s in term.list()["sessions"])
    # never reaped for idleness (idle_min is a fraction of a second here)
    time.sleep(0.2)
    term.tick()
    assert term.live[out["tid"]].pty.alive
    # a second open attaches to the same process
    again = term.open_console()
    assert again["tid"] == out["tid"] and again["ticket"] != out["ticket"]
    # /clear: the status line's session_id is the new conversation's
    term.live[out["tid"]].pty.write(b"say hello\n")
    scr.said("hello")
    meter = term.store.dir(out["tid"]) / "meter"
    (meter / "status.json").write_text(json.dumps({"session_id": "s-new",
                                                    "cost": {"total_cost_usd": 0.0}}))
    term.tick()
    assert term.store.get(out["tid"])["session"] == "s-new"
    # New conversation types the harness's own command
    term.console_new("claude")
    scr.wait("you said: /clear")
    # End keeps the conversation; Open resumes it
    term.console_end("claude")
    rec = term.store.get(out["tid"])
    assert rec["state"] == "ended" and not rec.get("removed")
    transcript = C.transcript(term.console_spec(rec), "s-new")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n")
    out2 = term.open_console()
    assert out2["tid"] == out["tid"]
    a = argv_of(attach(term, out2))
    assert a[a.index("--resume") + 1] == "s-new"


def test_end_this_session_starts_fresh_and_previous_sessions_resume(term, home):
    """ (the owner: "the conversation just stays there"): End this session ends it, and the
    next Open is a new conversation (a new ``--session-id``, a clean prompt); the ended one is
    listed under Previous sessions and resumes from there, the fresh one joining the list."""
    out = term.open_console()
    attach(term, out)
    first = term.store.get(out["tid"])["session"]
    transcript = C.transcript(term.console_spec(term.store.get(out["tid"])), first)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n")
    ended = term.console_end("claude", fresh=True)
    assert ended["state"] == "ended" and ended["session"] != first
    prev = term.console_state()["conversations"]["claude"]["previous"]
    assert [p["session"] for p in prev] == [first]
    again = term.open_console()
    a = argv_of(attach(term, again))
    second = a[a.index("--session-id") + 1]
    assert again["tid"] == out["tid"] and second != first and "--resume" not in a
    # Previous sessions › the first: it resumes, and the fresh one is kept beside it
    term.console_resume("claude", first)
    assert out["tid"] not in term.live or not term.live[out["tid"]].pty.alive
    assert [p["session"] for p in
            term.console_state()["conversations"]["claude"]["previous"]] == [second]
    back = term.open_console()
    a = argv_of(attach(term, back))
    assert a[a.index("--resume") + 1] == first
    with pytest.raises(Exception, match="no such previous session"):
        term.console_resume("claude", "not-one-of-them")


def test_open_in_claude_code_does_not_count_the_console(term):
    term.open_console()
    running = [t for t in term.running() if not term.live[t].console]
    assert running == []


def test_a_missing_harness_says_so(term):
    with pytest.raises(Exception) as e:
        term.open_console("codex")
    assert "not installed" in str(e.value)


def test_kranto_only_without_a_token_says_the_consoles_own_way_on(term, tmp_path, monkeypatch):
    """A stranger's console under Kranto's only configuration and no token answered with Open in
    Claude Code's words and a hand-written systemd drop-in, while doctor names kranto setup claude
    (KPUB C5): the console says its own sentence, the same way on as doctor's."""
    from kranto.page.term import service
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("KRANTO_CLAUDE_DIR", str(tmp_path / "no-login"))   # no token kept either
    term.console_settings({"config": "kranto"})
    with pytest.raises(service.TermError) as e:
        term.open_console()
    said = str(e.value)
    assert e.value.code == 503 and said == service.CONSOLE_NO_TOKEN
    assert said.startswith("The console") and "kranto setup claude" in said
    assert "Settings › Assistant" in said
    # Open in Claude Code's own line says the same way on; neither speaks of a drop-in
    assert term.status()["why"] == service.NO_TOKEN and "kranto setup claude" in service.NO_TOKEN
    assert not [w for w in (said, service.NO_TOKEN) if "drop-in" in w or "EnvironmentFile" in w]


def test_a_change_taken_at_start_offers_the_restart_and_it_resumes(term, home):
    """The owner's Q2: switching whose configuration or the permission mode
    offers to restart the console; the restart (the panel's End, then Open) resumes the same
    conversation with the new setting. Nothing running: nothing to offer."""
    assert term.console_settings({"permission": "ask"})["restart"] is False
    out = term.open_console()
    attach(term, out)
    session = term.store.get(out["tid"])["session"]
    assert term.console_settings({"permission": "accept-edits"})["restart"] is True
    assert term.console_settings({"config": "kranto"})["restart"] is True
    assert term.console_settings({"config": "own"})["restart"] is True
    assert term.console_settings({"open": True})["restart"] is False      # read on each visit
    term.console_end("claude")
    rec = term.store.get(out["tid"])
    transcript = C.transcript(term.console_spec(rec), session)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n")
    again = term.open_console()
    a = argv_of(attach(term, again))
    assert again["tid"] == out["tid"] and a[a.index("--resume") + 1] == session
    assert a[a.index("--permission-mode") + 1] == "acceptEdits"


def test_the_outside_servers_are_named_and_nothing_else_is_read_out(tmp_path, home):
    user = tmp_path / "user"
    (user / ".claude.json").write_text(json.dumps({
        "mcpServers": {"github": {"command": "gh-mcp", "env": {"GITHUB_TOKEN": "x" * 8}},
                       "kranto": {"command": "kranto"}},
        "projects": {str(home): {"mcpServers": {"postgres": {"command": "pg"}}},
                     "/elsewhere": {"mcpServers": {"other": {}}}}}))
    (home / ".mcp.json").write_text(json.dumps({"mcpServers": {"linear": {"url": "u"}}}))
    env = {"HOME": str(user)}
    assert C.outside_servers("claude", "own", env, home) == ["github", "linear", "postgres"]
    assert C.outside_servers("claude", "kranto", env, home) == []        # Kranto's only: none
    (user / ".codex").mkdir()
    (user / ".codex" / "config.toml").write_text('[mcp_servers.notion]\ncommand = "n"\n'
                                                '[mcp_servers.kranto]\ncommand = "kranto"\n')
    assert C.outside_servers("codex", "own", env, home) == ["notion"]
    (user / ".claude.json").write_text("{not json")
    assert C.outside_servers("claude", "own", env, home) == []          # unreadable: none said


def test_settings_are_written_to_loop_yaml(term):
    out = term.console_settings({"permission": "ask", "model": {"claude": "claude-haiku-5-5"},
                                 "open": False, "daily_usd": 1.5})
    assert out["settings"]["permission"] == "ask" and out["settings"]["open"] is False
    data = yaml.safe_load(term.app.loop_cfg().layout.settings.read_text())
    assert data["ask"]["model"] == {"claude": "claude-haiku-5-5"}
    assert data["ask"]["daily_usd"] == 1.5
    with pytest.raises(TermError, match="permission is ") as bad:
        term.console_settings({"permission": "bypass"})
    assert bad.value.code == 400
    with pytest.raises(TermError, match="nothing to set") as empty:
        term.console_settings({})
    assert empty.value.code == 400
    term.console_here("#/watch", "Watch › Topics")


def _turn(kind, *texts, tools=False, at="2026-11-11T19:00:00Z"):
    content = [{"type": "text", "text": t} for t in texts]
    if tools:
        content.append({"type": "tool_use", "name": "kranto_read", "input": {}})
    return json.dumps({"type": kind, "timestamp": at, "message": {"role": kind, "content": content}})


def test_what_it_last_said_is_the_newest_reply_with_words_and_its_page(tmp_path):
    """the phone's sheet: the newest assistant turn that has words, its first six
    lines, when, and the first kranto page it links; a turn of tools alone is skipped"""
    t = tmp_path / "s.jsonl"
    long = "\n".join(f"line {i}" for i in range(10))
    t.write_text("\n".join([
        _turn("user", "What is new in Robotics?"),
        _turn("assistant", "Robotics has a new brief: http://127.0.0.1:8765/#/news/b/26 with 5 items.\n" + long,
              at="2026-11-11T19:01:00Z"),
        _turn("user", "thanks"),
        _turn("assistant", tools=True, at="2026-11-11T19:02:00Z"),       # tools, no words
        "{not json",                                                    # a cut line
    ]) + "\n")
    got = C.last_reply(t)
    assert got["said"].splitlines()[0].startswith("Robotics has a new brief")
    assert len(got["said"].splitlines()) == C.LAST_LINES and got["more"] is True
    assert got["page"] == "#/news/b/26" and got["at"] == "2026-11-11T19:01:00Z"


def test_what_it_last_said_says_why_when_there_is_nothing(tmp_path):
    assert C.last_reply(None) == {"said": None, "why": "this assistant keeps no transcript Kranto can read"}
    assert C.last_reply(tmp_path / "none.jsonl")["why"] == "no conversation yet"
    t = tmp_path / "s.jsonl"
    t.write_text(_turn("user", "hello") + "\n")
    assert C.last_reply(t) == {"said": None, "why": "it has not said anything yet"}


def test_the_last_read_answers_without_a_conversation(term):
    got = term.console_last("claude")
    assert got == {"harness": "claude", "said": None, "why": "no conversation yet"}
