"""An install made before the rename keeps working after it updates: its unit, its config folder
(the home pointer, the tokens, the console's Claude login, ``claude.env``, ``cubs.STOP``), the
old command, its MCP entry and the plugin's allow-list, and a browser's old session cookie. Each
is read where it is (``kranto.legacy``); nothing is moved. A new install gets the new names.
systemctl is a fake; nothing here starts a service, calls a model or touches the network."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kranto import launcher, legacy, paths, product, tokens
from kranto.page import claude_login
from kranto.page import tokens as page_tokens

from .test_kranto import make_host

OLD_ENV = legacy.ENV_PREFIXES[0]


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    home = tmp_path / "u"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for k in ("KRANTO_LOOP_HOME", "KRANTO_HOME", "KRANTO_UNIT", "KRANTO_TOKENS_DIR",
              "KRANTO_CLAUDE_DIR", "KRANTO_CUBS_STOP", OLD_ENV + "UNIT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(launcher, "UNIT", product.UNIT)
    monkeypatch.setattr(launcher, "port_in_use", lambda port, host="127.0.0.1": False)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    return home


def old_install(user_home: Path, kb: Path | None = None) -> dict[str, Path]:
    """The shape of an install made before the rename: its unit (no unit variable) and four
    drop-ins, the old config folder alone, with the home pointer in it."""
    kb = kb or user_home / "oldkb"
    launcher.make_home(kb, 8765, user_home)
    units = user_home / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    unit = units / legacy.UNIT
    # CRLF kept on one line on purpose: the file is kept byte for byte but for Description
    unit.write_bytes(
        b"[Unit]\nDescription=the old words\nAfter=network-online.target\n\n[Service]\n"
        + f"Environment={OLD_ENV}HOME=%h/oldkb\n".encode()
        + b"ExecStart=%h/.local/bin/" + legacy.COMMAND.encode() + b" serve --host 127.0.0.1\r\n"
        b"Restart=on-failure\n\n[Install]\nWantedBy=default.target\n")
    dropins = units / f"{legacy.UNIT}.d"
    dropins.mkdir()
    for n in ("10-a.conf", "20-b.conf", "30-memory.conf", "40-d.conf"):
        (dropins / n).write_text(f"[Service]\n# {n}\n")
    conf = user_home / ".config" / legacy.CONFIG_DIR
    conf.mkdir(parents=True)
    (conf / "home").write_text(f"{kb}\n")
    return {"kb": kb, "units": units, "unit": unit, "dropins": dropins, "conf": conf}


# -- the unit -------------------------------------------------------------------------------------


def test_up_on_an_old_install_keeps_its_unit_and_rewrites_only_the_description(user_home):
    old = old_install(user_home)
    before = old["unit"].read_bytes()
    drops = {p.name: p.read_bytes() for p in old["dropins"].iterdir()}
    host = make_host(user_home)
    assert launcher.host_unit(host) == legacy.UNIT
    assert launcher.kranto_home(None, host) == old["kb"].resolve()
    assert launcher.main(["up", "--no-browser"], host) == 0
    assert not (old["units"] / product.UNIT).exists()          # never one beside it
    assert not (user_home / ".config" / product.CONFIG_DIR).exists()   # never moved
    after = old["unit"].read_bytes()
    want = before.replace(b"Description=the old words",
                          b"Description=" + launcher.UNIT_DESCRIPTION.encode())
    assert after == want and after != before
    assert {p.name: p.read_bytes() for p in old["dropins"].iterdir()} == drops
    calls = [c[2:] for c in host.machine.calls if c[0] == "systemctl"]
    assert ["enable", "--now", legacy.UNIT] in calls
    assert not any(product.UNIT in c for c in calls)
    # the tokens are made where the old install keeps them
    assert (old["conf"] / "tokens" / "index.json").is_file()
    # a second up changes nothing
    host.machine.calls.clear()
    assert launcher.main(["up", "--no-browser"], host) == 0
    assert old["unit"].read_bytes() == want
    assert ["restart", legacy.UNIT] not in [c[2:] for c in host.machine.calls]


def test_a_unit_named_by_the_old_variable_is_kept_too(user_home, monkeypatch):
    """An old install that runs under another unit (named by the old variable, as the release's
    rehearsal and the end-to-end test do) is kept by its text, not its name: a rollback to the
    version before the rename must still start from it."""
    old = old_install(user_home)
    other = old["units"] / "scratch-test.service"
    other.write_bytes(old["unit"].read_bytes())
    old["unit"].unlink()
    monkeypatch.setattr(launcher, "UNIT", "scratch-test.service")
    host = make_host(user_home)
    before = other.read_bytes()
    path, changed = launcher.install_unit(host, "[Unit]\nDescription=new\n")
    assert path == other and changed
    assert other.read_bytes() == before.replace(
        b"Description=the old words", b"Description=" + launcher.UNIT_DESCRIPTION.encode())
    # a unit the new version wrote is written as usual
    other.write_text("[Service]\nExecStart=%h/.local/bin/kranto serve\n")
    path, changed = launcher.install_unit(host, "[Unit]\nDescription=new\n")
    assert changed and other.read_text() == "[Unit]\nDescription=new\n"


def test_up_on_a_new_install_writes_the_new_names(user_home):
    host = make_host(user_home)
    assert launcher.host_unit(host) == product.UNIT
    assert launcher.main(["up", "--no-browser"], host) == 0
    units = user_home / ".config" / "systemd" / "user"
    assert (units / product.UNIT).is_file() and not (units / legacy.UNIT).exists()
    assert (user_home / ".config" / product.CONFIG_DIR / "tokens" / "index.json").is_file()
    assert not (user_home / ".config" / legacy.CONFIG_DIR).exists()
    assert (user_home / ".kranto" / product.HOME_FILE).is_file()


def test_status_down_and_logs_name_the_old_unit(user_home):
    old_install(user_home)
    host = make_host(user_home)
    host.machine.active[legacy.UNIT] = "active"
    lines, _ = launcher.status_lines(launcher.kranto_home(None, host), host)
    assert any(f"{legacy.UNIT}: active" in ln for ln in lines), lines
    assert launcher.cmd_down(SimpleNamespace(disable=False), host) == 0
    assert host.machine.calls[-1][-1] == legacy.UNIT


def test_the_old_units_home_variable_is_read(user_home):
    old = old_install(user_home)
    (old["conf"] / "home").unlink()                            # no pointer: the unit says
    assert paths.unit_home(user_home, old["units"], legacy.UNIT) == user_home / "oldkb"


# -- the config folder's stores ------------------------------------------------------------------


@pytest.mark.parametrize("mod", [tokens, page_tokens])
def test_the_token_store_is_the_old_folders_on_an_old_install(user_home, mod):
    assert mod.tokens_dir() == user_home / ".config" / product.CONFIG_DIR / "tokens"
    old = old_install(user_home)
    assert mod.tokens_dir() == old["conf"] / "tokens"
    assert mod.tokens_dir(home=user_home) == old["conf"] / "tokens"
    assert mod.tokens_dir({"HOME": str(user_home), "KRANTO_UNIT": "kranto-test.service"}) == \
        old["conf"] / "tokens.kranto-test"
    host = make_host(user_home)
    assert launcher.token_store(host).root == old["conf"] / "tokens"


def test_the_consoles_claude_login_is_the_old_folders_on_an_old_install(user_home):
    old = old_install(user_home)
    assert claude_login.store_dir() == old["conf"] / "claude"
    assert launcher.claude_store(make_host(user_home)) == old["conf"] / "claude"


def test_claude_env_and_the_drop_ins_are_the_old_units(user_home):
    from kranto.page.term import cli as term_cli

    old = old_install(user_home)
    (old["dropins"] / "50-env.conf").write_text("[Service]\nEnvironmentFile=-%h/x.env\n")
    files = term_cli.env_files(user_home)
    assert files == [user_home / "x.env", old["conf"] / "claude.env"]


def test_cubs_stop_is_honoured_in_either_folder(user_home):
    from kranto.core import tickets

    old = old_install(user_home)
    assert tickets.stop_file() == old["conf"] / "cubs.STOP"
    assert not tickets.stop_file().exists()
    (old["conf"] / "cubs.STOP").touch()
    assert tickets.stop_file().exists()
    (user_home / ".config" / product.CONFIG_DIR).mkdir()        # both folders now
    assert tickets.stop_file() == old["conf"] / "cubs.STOP"      # still honoured
    (old["conf"] / "cubs.STOP").unlink()
    # an empty new folder does not pull the install away from its own folder
    assert tickets.stop_file() == old["conf"] / "cubs.STOP"
    (user_home / ".config" / product.CONFIG_DIR / "home").write_text("/kb\n")
    assert tickets.stop_file() == user_home / ".config" / product.CONFIG_DIR / "cubs.STOP"


def test_a_sandboxed_print_call_hides_both_config_folders(tmp_path):
    from kranto.page.box import print_call

    hidden = print_call._hidden(tmp_path, None)
    for d in legacy.config_dirs(tmp_path):
        assert d in hidden


# -- the old command ------------------------------------------------------------------------------


def test_the_old_command_says_so_on_a_terminal_once_a_day(user_home, capsys):
    old = old_install(user_home)
    exe = str(user_home / ".local" / "bin" / legacy.COMMAND)
    assert launcher.alias_notice(exe, tty=True, user_home=user_home, now=0.0)
    assert capsys.readouterr().err == legacy.alias_notice() + "\n"
    assert (old["conf"] / launcher.ALIAS_STAMP).is_file()       # in the old folder
    assert not launcher.alias_notice(exe, tty=True, user_home=user_home, now=3600.0)
    assert launcher.alias_notice(exe, tty=True, user_home=user_home, now=3 * 86400.0)
    capsys.readouterr()
    # silent in scripts, and as the new command
    assert not launcher.alias_notice(exe, tty=False, user_home=user_home, now=9 * 86400.0)
    assert not launcher.alias_notice(str(user_home / product.COMMAND), tty=True,
                                     user_home=user_home, now=9 * 86400.0)
    assert capsys.readouterr().err == ""


# -- the browser's session cookie -----------------------------------------------------------------


def test_the_old_session_cookie_is_accepted_and_new_sign_ins_set_the_new_one(tmp_path):
    from kranto.web.auth import Auth, old_cookie_name

    store = tokens.Store(tmp_path / "t")
    store.ensure_doors()
    ui = store.value("ui")
    auth = Auth(store, port=8765)
    assert auth.cookie == tokens.cookie_name(8765)
    assert old_cookie_name(8765) == f"{legacy.COOKIE}_8765" and old_cookie_name() == legacy.COOKIE

    def req(cookies):
        return SimpleNamespace(headers={}, cookies=cookies)
    ident, _ = auth.identify(req({auth.old_cookie: ui}))
    assert ident and ident["origin"] == "ui" and ident["via"] == "cookie"
    assert auth.identify(req({auth.old_cookie: "x" * 40}))[0] is None
    # the new cookie wins when both are there
    assert auth.identify(req({auth.cookie: "x" * 40, auth.old_cookie: ui}))[0] is None
    # a new sign-in sets the new cookie only
    from starlette.responses import JSONResponse

    set_cookies = auth._signed_in(JSONResponse({}), ui).headers.getlist("set-cookie")
    assert len(set_cookies) == 1 and set_cookies[0].startswith(auth.cookie + "=")


def test_the_pages_own_server_accepts_the_old_cookie_too(tmp_path):
    from kranto.page.ui import server as page_server

    store = page_tokens.Store(tmp_path / "t")
    store.ensure_doors()
    ui = store.value("ui")
    handler = page_server.make_handler(SimpleNamespace(), store)
    port = 8765
    h = handler.__new__(handler)           # no socket: identify reads the headers alone
    h.server = SimpleNamespace(server_address=("127.0.0.1", port))
    for cookie, ok in ((f"{legacy.COOKIE}_{port}={ui}", True),
                       (f"{tokens.cookie_name(port)}={ui}", True),
                       (f"{legacy.COOKIE}_{port}=nope", False), ("", False)):
        h.headers = {"Cookie": cookie}
        ident, _ = h.identify()
        assert bool(ident) is ok, cookie


# -- MCP and the plugin's hooks -------------------------------------------------------------------


def test_the_old_command_serves_the_old_tool_names():
    from kranto.page.mcp import server as S

    shown, inner = S.renamer(legacy.MCP_SERVER)
    assert shown("kranto_status") == f"{legacy.MCP_SERVER}_status"
    assert inner(f"{legacy.MCP_SERVER}_status") == "kranto_status"
    same = S.renamer(product.MCP_SERVER)
    assert same[0]("kranto_status") == "kranto_status"
    if not S.available():
        pytest.skip("the MCP extra is not installed")
    for name, prefix in ((legacy.MCP_SERVER, legacy.MCP_SERVER + "_"),
                         (product.MCP_SERVER, product.MCP_SERVER + "_")):
        srv = S.build_server(SimpleNamespace(who=None), term=True, name=name)
        listed = asyncio.run(srv.kranto_list()).tools
        assert listed and all(t.name.startswith(prefix) for t in listed), name
        assert srv.name == name


HOOKS = Path(launcher.__file__).resolve().parent / "plugin" / "hooks"


def hook(script: str, event: dict, env: dict) -> dict | None:
    r = subprocess.run([sys.executable, "-I", str(HOOKS / script)], input=json.dumps(event),
                       capture_output=True, text=True, timeout=20, env=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def test_the_allow_hook_accepts_both_prefixes_and_nothing_else(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    for prefix in legacy.MCP_ALLOW_PREFIXES:
        out = hook("allow.py", {"tool_name": prefix + "status"}, env)
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow", prefix
    s = legacy.MCP_SERVER
    assert hook("allow.py", {"tool_name": f"mcp__plugin_{s}_{s}__{s}_status"}, env)
    for name in (f"mcp__{s}__other", f"mcp__evil__{s}_status", f"mcp__{s}__{s}_x; rm", "Bash"):
        assert hook("allow.py", {"tool_name": name}, env) is None, name


def test_the_allow_hook_copied_away_from_the_package_knows_an_old_store(tmp_path):
    """A plugin installed from the marketplace has no package beside it: a config folder that
    holds a token store names a server."""
    copy = tmp_path / "plugin" / "hooks"
    copy.mkdir(parents=True)
    for f in ("allow.py", "_names.py"):
        (copy / f).write_text((HOOKS / f).read_text())
    home = tmp_path / "h"
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    s = legacy.MCP_SERVER

    def run(name):
        r = subprocess.run([sys.executable, "-I", str(copy / "allow.py")],
                           input=json.dumps({"tool_name": name}), capture_output=True,
                           text=True, timeout=20, env=env)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    assert run(f"mcp__{product.MCP_SERVER}__{product.MCP_SERVER}_status")
    assert not run(f"mcp__{s}__{s}_status")
    (home / ".config" / legacy.CONFIG_DIR / "tokens").mkdir(parents=True)
    (home / ".config" / legacy.CONFIG_DIR / "tokens" / "index.json").write_text("{}")
    assert run(f"mcp__{s}__{s}_status")


def test_the_secrets_hook_guards_the_old_folder(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    old = tmp_path / ".config" / legacy.CONFIG_DIR
    for path in (old / "tokens" / "x", old / "claude.env"):
        out = hook("secrets.py", {"tool_name": "Read", "tool_input": {"file_path": str(path)}},
                   env)
        assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny", path
    assert hook("secrets.py", {"tool_name": "Read",
                               "tool_input": {"file_path": str(old / "notes.txt")}}, env) is None


def test_the_hooks_never_name_the_old_product():
    for f in HOOKS.iterdir():
        if f.suffix in (".py", ".json"):
            assert legacy.MCP_SERVER not in f.read_text(), f
