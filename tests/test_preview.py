"""The preview's switch: ``preview.enabled: true`` in the copy's config, and
each of its six lines. Nothing here sends, asks a server or touches a real home."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kranto import launcher, legacy, preview
from kranto.core import tickets
from kranto.core.cubs import settings as cub_settings
from kranto.core.cubs.brokers.base import BrokerContext
from kranto.sources.base import SourceError
from kranto.store import iso, utcnow

UI = {"origin": "ui", "via": "cookie"}
FIELDS = {"draft_ref": "draft:1", "text": "hello", "visibility": "public", "language": "en"}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # registered with monkeypatch, so whatever 'kranto serve' puts there is taken away again
    for name in (preview.ENV, "DO_NOT_TRACK", "KRANTO_HOME", "KRANTO_TELEMETRY"):
        monkeypatch.delenv(name, raising=False)
    preview._cache.clear()


def write_home(home: Path, *, on: bool = True, extra: dict | None = None) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    data = {"telemetry": {"mode": "detailed", "answered_at": "2026-10-01T00:00:00Z"}}
    if on:
        data["preview"] = {"enabled": True, "copied_at": "2026-11-11T08:30:00Z",
                           "commits": {"kranto": "abc1234", "kranto.page": "def5678"}}
    data.update(extra or {})
    (home / "kranto.yaml").write_text(yaml.safe_dump(data))
    return home


class Cfg:
    def __init__(self, root: Path, cubs: dict | None = None):
        self.root = root
        self.cubs = cub_settings.parse(cubs or {})


# -- the switch itself ---------------------------------------------------------------------------


def test_the_switch_is_read_from_the_file_or_the_environment(tmp_path, monkeypatch):
    on, off = write_home(tmp_path / "on"), write_home(tmp_path / "off", on=False)
    assert preview.enabled(on) and not preview.enabled(off) and not preview.enabled(None)
    assert not preview.enabled(tmp_path / "missing")
    monkeypatch.setenv("KRANTO_HOME", str(on))
    assert preview.enabled()                       # a command run by hand in the preview's home
    monkeypatch.delenv("KRANTO_HOME")
    monkeypatch.setenv(preview.ENV, "1")
    assert preview.enabled(off)                    # the served process and its children
    monkeypatch.setenv(preview.ENV, "0")
    assert not preview.enabled(off)


@pytest.mark.parametrize("stored", [None, "yes", 1, [], {"enabled": "true"}, {"enabled": None}])
def test_a_stored_value_of_another_shape_is_not_the_switch(tmp_path, stored):
    home = write_home(tmp_path / "h", on=False, extra={"preview": stored})
    assert preview.enabled(home) is False and preview.status(home) is None


def test_the_config_loader_accepts_the_section(tmp_path):
    from kranto import config as config_mod
    home = tmp_path / "h"
    home.mkdir()
    (home / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML
                                        + "\npreview:\n  enabled: true\n")
    assert config_mod.load(home, dotenv=False).root == home.resolve()
    assert preview.enabled(home)


# -- 1. every posting cub is in practice; confirm and cub.live refuse; nothing leaves ------------


def test_1_no_kind_is_live_on_the_preview(tmp_path):
    cubs = {"toot": {"live": ["post.mastodon"]}}
    assert "post.mastodon" in cub_settings.live_kinds(
        Cfg(write_home(tmp_path / "off", on=False), cubs), "toot")
    assert cub_settings.live_kinds(Cfg(write_home(tmp_path / "on"), cubs), "toot") == []


@pytest.fixture
def post(monkeypatch, store, tmp_path):
    seen = []
    tickets.kind_names()

    def perform(store, ticket, context, mode):
        seen.append(mode)
        return {"state": "done", "note": "sent"}

    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "perform", perform)
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    store.insert("cub_drafts", {"cub": "toot", "service": "mastodon", "ref": "draft:1",
                                "content": "{}", "content_hash": "x", "created_at": iso(utcnow())})
    return seen


def test_1_a_confirm_on_the_preview_says_so_and_writes_nothing(store, post, tmp_path):
    tid = tickets.file(store, cub="toot", trust="owner", granted=("post.mastodon",),
                       kind="post.mastodon", fields=FIELDS, run_uuid="run-1")
    ctx = SimpleNamespace(cfg=Cfg(write_home(tmp_path / "on"), {"toot": {"live":
                                                                         ["post.mastodon"]}}))
    with pytest.raises(tickets.TicketError) as err:
        tickets.confirm(store, tid, identity=UI, confirm=True, context=ctx)
    assert str(err.value) == "This is the preview: nothing is sent." and err.value.code == 409
    assert post == []                                         # the performer never ran
    t = tickets.get(store, tid)
    assert t["state"] == tickets.OPEN                         # the ask still waits
    assert [h["state"] for h in t["history"]] == ["needs_confirm"]


def test_1_a_confirm_elsewhere_is_unchanged(store, post, tmp_path):
    tid = tickets.file(store, cub="toot", trust="owner", granted=("post.mastodon",),
                       kind="post.mastodon", fields=FIELDS, run_uuid="run-1")
    ctx = SimpleNamespace(cfg=Cfg(write_home(tmp_path / "off", on=False),
                                  {"toot": {"live": ["post.mastodon"]}}))
    assert tickets.confirm(store, tid, identity=UI, confirm=True, context=ctx)["state"] == "done"
    assert post == ["live"]


def test_1_the_ask_can_be_pressed_and_says_nothing_is_sent(store, post, tmp_path):
    from kranto.core import asks
    tid = tickets.file(store, cub="toot", trust="owner", granted=("post.mastodon",),
                       kind="post.mastodon", fields=FIELDS, run_uuid="run-1")
    t = tickets.get(store, tid)
    rt = SimpleNamespace(store=store, cubs=None, cfg=Cfg(write_home(tmp_path / "on")))
    a = asks.ask(rt, t)
    # no account is copied and none is needed: Send is pressable and the confirm refuses
    assert a["needs"] is None and a["open"] is True
    assert a["practice"] == {"on": True, "words": preview.NOTHING_SENT, "switch": None}
    assert asks.row(rt, t)["meta"] == "the preview: nothing is sent"
    elsewhere = asks.ask(SimpleNamespace(store=store, cubs=None,
                                         cfg=Cfg(write_home(tmp_path / "off", on=False))), t)
    assert elsewhere["practice"] is None or elsewhere["practice"]["words"] != preview.NOTHING_SENT


def test_1_a_kind_cannot_go_live_on_the_preview(store, tmp_path, monkeypatch):
    from kranto.core.cubs import install
    monkeypatch.setattr(install, "_live_row", lambda store, cid: {"grants": "{}"})
    rt = SimpleNamespace(store=store, cfg=Cfg(write_home(tmp_path / "on")))
    with pytest.raises(install.InstallError) as err:
        install.set_mode(rt, "toot", "post.mastodon", True)
    # refused before the grants are read: whatever the cub asks for, nothing goes live here
    assert err.value.code == 409 and "This is the preview: nothing is sent" in err.value.words


class Conns:
    def __init__(self):
        self.sent = []

    def http_for(self, provider, instance, http):
        conns = self

        class Http:
            def get(self, url, **kw):
                conns.sent.append(("GET", url))
                return "ok"

            def post(self, url, **kw):
                conns.sent.append(("POST", url))
                return "ok"

            def patch(self, url, **kw):
                conns.sent.append(("PATCH", url))
                return "ok"
        return Http()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_1_2_a_broker_sends_nothing_but_a_read_on_the_preview(store, tmp_path, method):
    conns = Conns()
    rt = SimpleNamespace(cfg=Cfg(write_home(tmp_path / "on")), connections=conns, http=None)
    ctx = BrokerContext(store=store, cub="toot", rt=rt, provider="mastodon")
    with pytest.raises(SourceError) as err:
        ctx.send(method, "https://example.invalid/api/v1/statuses", data={"status": "hi"})
    assert err.value.sent is False and preview.NOTHING_SENT in str(err.value)
    assert conns.sent == []
    assert ctx.send("GET", "https://example.invalid/api/v2/instance") == "ok"
    assert conns.sent == [("GET", "https://example.invalid/api/v2/instance")]


def test_1_2_a_broker_elsewhere_sends(store, tmp_path):
    conns = Conns()
    rt = SimpleNamespace(cfg=Cfg(write_home(tmp_path / "off", on=False)), connections=conns,
                         http=None)
    ctx = BrokerContext(store=store, cub="toot", rt=rt, provider="mastodon")
    assert ctx.send("POST", "https://example.invalid/x") == "ok" and conns.sent


def test_1_a_refused_send_is_a_refusal_in_the_tickets_words(store, tmp_path):
    from kranto.core.cubs.brokers.base import outcome_of
    rt = SimpleNamespace(cfg=Cfg(write_home(tmp_path / "on")), connections=Conns(), http=None)
    ctx = BrokerContext(store=store, cub="toot", rt=rt, provider="mastodon")
    with pytest.raises(SourceError) as err:
        ctx.send("POST", "https://example.invalid/x")
    out = outcome_of(err.value, "Mastodon", sending="it posted")
    assert out["state"] == "refused" and "nothing is sent" in out["note"]


def test_2_invest_and_the_radar_are_off_on_the_preview_and_everywhere(tmp_path):
    from kranto import config as config_mod
    from kranto.core import registry
    feats = {f.id: f for f in registry.first_party()}

    def home(name, on):           # the owner's copied settings turn both on
        h = tmp_path / name
        h.mkdir()
        (h / "kranto.yaml").write_text(
            config_mod.DEFAULT_CONFIG_YAML + "\ninvest:\n  enabled: true\nradar:\n  enabled: true\n"
            + ("preview:\n  enabled: true\n" if on else ""))
        return config_mod.load(h, dotenv=False)
    on, off = home("on", True), home("off", False)
    for fid in preview.FORCED_OFF:
        if fid in feats:                      # wave 3 takes them out of Kranto altogether
            assert registry.enabled(off, feats[fid]) and not registry.enabled(on, feats[fid])
    assert registry.enabled(on, feats["news"])        # the rest of Kranto is the same
    # wave 3 took them out of Kranto altogether (cut 2): their sections are retired
    assert "invest" not in feats and "radar" not in feats
    assert set(on.retired) >= {"invest", "radar"} and set(off.retired) >= {"invest", "radar"}


def test_2_no_broker_is_left_to_reach():
    """Invest's broker client left Kranto with it (cut 2); a cub broker's sends are
    BrokerContext.send's, refused on the preview above."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("kranto.core.brokers")


# -- 3. usage reports are never sent ------------------------------------------------------------


def test_3_usage_reports_are_off_whatever_the_copy_says(tmp_path, monkeypatch):
    from kranto.telemetry import local, send
    on = write_home(tmp_path / "on")
    eff = local.effective(on, environ={})
    assert eff.mode == "off" and eff.why == "DO_NOT_TRACK"
    assert local.effective(write_home(tmp_path / "off", on=False), environ={}).mode == "detailed"

    def no_post(*a, **k):
        raise AssertionError("the preview posted a report")
    monkeypatch.setattr(send, "post", no_post)
    out = send.run(on, environ={})
    assert out["mode"] == "off" and out["posted"] == []


# -- 4. no update, no update check, no cub update -----------------------------------------------


class NoSource:
    def latest(self, *a, **k):
        raise AssertionError("the preview asked for a release")


def test_4_the_update_check_asks_nothing_and_writes_nothing(tmp_path):
    from kranto.update import check
    on = write_home(tmp_path / "on")
    cache = check.run_check(on, source=NoSource())
    assert cache["ok"] is True and cache["latest"] is None and cache["preview"]
    assert not (on / "update").exists()
    assert check.available(cache) is None


def test_4_the_update_job_records_why_it_did_nothing(tmp_path, store):
    from kranto.update import check
    on = write_home(tmp_path / "on")
    check.make_job(on, store, 24).run()
    row = store.query_one("SELECT status, summary FROM runs WHERE kind = 'update'")
    assert row["status"] == "ok" and "this is the preview" in row["summary"]


def test_4_an_update_is_never_launched(tmp_path):
    from kranto.update import launch

    def run(cmd):
        raise AssertionError(f"ran {cmd}")
    with pytest.raises(launch.LaunchError) as err:
        launch.launch(write_home(tmp_path / "on"), "v9.9.9", env={}, run=run)
    assert "this is the preview" in str(err.value)


def test_4_kranto_update_refuses_in_the_preview(tmp_path, monkeypatch, capsys):
    from .test_kranto import make_host
    on = write_home(tmp_path / "on")
    host = make_host(tmp_path)
    assert launcher.main(["--home", str(on), "update", "--yes"], host) != 0
    assert "this is the preview: it is never updated" in capsys.readouterr().err
    assert host.machine.calls == []


def test_4_the_cubs_are_not_updated(tmp_path, store):
    from kranto.core.cubs import install, updates
    rt = SimpleNamespace(store=store, cfg=Cfg(write_home(tmp_path / "on")), cubs=object())
    out = updates.run(rt)
    assert "this is the preview" in out["why"]
    row = store.query_one("SELECT status FROM runs WHERE kind = ?", (updates.KIND,))
    assert row["status"] == "skipped"
    with pytest.raises(install.InstallError) as err:
        install.apply_update(rt, "job-1", "toot", door="ui")
    assert err.value.code == 409 and "preview" in err.value.words


# -- 5. the status bar's sentence ---------------------------------------------------------------


def test_5_status_carries_the_sentence_and_the_date(tmp_path):
    st = preview.status(write_home(tmp_path / "on"))
    # 10 (Gemini 13): never "Nothing is sent" (Welcome's key test reaches the provider)
    quiet = "Nothing is posted; no update or usage report goes out."
    assert st == {"line": f"Preview: a copy of your data from 11 November. {quiet}",
                  "copied_at": "2026-11-11T08:30:00Z",
                  "commits": {"kranto": "abc1234", "kranto.page": "def5678"}}
    assert preview.status(write_home(tmp_path / "off", on=False)) is None
    empty = write_home(tmp_path / "empty", extra={"preview": {"enabled": True, "empty": True}})
    assert preview.status(empty)["line"] == f"Preview: an empty home. {quiet}"
    assert "Nothing is sent" not in st["line"]


def test_5_api_status_says_preview(tmp_path, store, embedder, make_client):
    from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import llm_config, web_client
    for name, on in (("on", True), ("off", False)):
        root = write_home(tmp_path / name, on=on)
        cfg = Config(root=root, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                     ingest=IngestConfig(), map=MapConfig())
        rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
        with web_client(create_app(rt, None), "http://127.0.0.1:8766") as web:
            got = web.get("/api/status").json()["preview"]
        if on:
            assert got["line"].startswith("Preview: a copy of your data from 11 November.")
        else:
            assert got is None


# -- 6. kranto serve refuses live's folders and live's port --------------------------------------


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    home = tmp_path / "u"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KRANTO_LOOP_HOME", raising=False)
    return home


@pytest.mark.parametrize("name", [h.removeprefix("~/") for h in legacy.live_homes()])
def test_6_live_folders_by_name_are_refused(user_home, name):
    live = user_home / name
    assert "the live install's" in preview.refusal(live, None, 8766, user_home)
    assert "the live install's" in preview.refusal(live / "data", None, 8766, user_home)
    assert "loop home" in preview.refusal(user_home / "p", live, 8766, user_home)


def test_6_the_home_kranto_service_names_is_refused(user_home):
    units = user_home / ".config" / "systemd" / "user"
    units.mkdir(parents=True)
    live = user_home / "somewhere" / "kb"
    write_home(live, on=False, extra={"brb": {"loop_home": str(user_home / "lh")}})
    (units / "kranto.service").write_text(
        f"[Service]\nEnvironment=KRANTO_HOME={live}\nExecStart=/x/kranto serve --port 8799\n")
    assert "the live install's" in preview.refusal(live, None, 8766, user_home)
    assert "loop home" in preview.refusal(user_home / "p", user_home / "lh", 8766, user_home)
    assert "port 8799" in preview.refusal(user_home / "p", user_home / "pl", 8799, user_home)


def test_6_the_live_port_is_refused_and_a_copy_is_not(user_home):
    p = user_home / "kranto-preview"
    assert "port 8765" in preview.refusal(p / "home", p / "loop", 8765, user_home)
    assert preview.refusal(p / "home", p / "loop", 8766, user_home) is None


def _serve_home(user_home: Path, home: Path, loop: Path, port: int, on: bool = True) -> None:
    launcher.make_home(home, port, user_home)
    data = yaml.safe_load((home / "kranto.yaml").read_text()) if (home / "kranto.yaml").exists() \
        else yaml.safe_load((home / "kranto.yaml").read_text())
    name = "kranto.yaml" if (home / "kranto.yaml").exists() else "kranto.yaml"
    data.setdefault("brb", {})["loop_home"] = str(loop)
    if on:
        data["preview"] = {"enabled": True, "copied_at": "2026-11-11T08:30:00Z"}
    (home / name).write_text(yaml.safe_dump(data))


def test_6_serve_refuses_on_live_and_marks_the_process_on_a_copy(user_home, monkeypatch, capsys):
    from kranto import cli

    from .test_kranto import make_host
    seen = []
    monkeypatch.setattr(cli, "cmd_serve", lambda ns: seen.append(ns) or 0)
    host = make_host(user_home)
    live = user_home / legacy.WORKSPACE.removeprefix("~/")
    _serve_home(user_home, live, user_home / "x-loop", 8766)
    assert launcher.main(["--home", str(live), "serve"], host) != 0
    assert "the live install's" in capsys.readouterr().err and seen == []
    assert preview.ENV not in os.environ
    copy = user_home / "kranto-preview" / "home"
    _serve_home(user_home, copy, user_home / "kranto-preview" / "loop", 8765)
    assert launcher.main(["--home", str(copy), "serve"], host) != 0
    assert "port 8765" in capsys.readouterr().err and seen == []
    assert launcher.main(["--home", str(copy), "serve", "--port", "8766"], host) == 0
    assert seen[-1].port == 8766
    assert os.environ[preview.ENV] == "1" and os.environ["DO_NOT_TRACK"] == "1"


def test_6_serve_elsewhere_is_unchanged(user_home, monkeypatch):
    from kranto import cli

    from .test_kranto import make_host
    seen = []
    monkeypatch.setattr(cli, "cmd_serve", lambda ns: seen.append(ns) or 0)
    live = user_home / "kranto-kb"
    _serve_home(user_home, live, user_home / "kranto-loop", 8765, on=False)
    assert launcher.main(["--home", str(live), "serve"], make_host(user_home)) == 0
    assert seen and preview.ENV not in os.environ


# -- kranto-preview away, the one line, its PATH (fixes 5b and 14) --------------------------

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preview" / "kranto-preview"
ONE_LINE = (f"ssh -t -L 8766:127.0.0.1:8766 {socket.gethostname().split('.')[0]} "
            "'~/kranto-preview/bin/kranto-preview open; exec $SHELL -l'")


def test_the_build_installs_kranto_with_its_mcp_extra():
    """ 18: kranto mcp on the preview said "install the MCP extra" (the operator added it by
    hand for the outside test): the build installs kranto[mcp] and stops if mcp is missing."""
    src = SCRIPT.read_text()
    assert '"kranto[mcp] @ file://$meta"' in src and '--find-links "$ROOT/dist"' in src
    assert "import mcp" in src


def _library(home: Path) -> Path:
    from kranto.store import Store
    db = home / "data" / "kranto.db"
    Store.open(db).close()
    return db


def test_away_writes_the_marker_on_a_preview_home(tmp_path):
    import json

    from kranto.core import home as home_mod
    from kranto.store import Store
    home = write_home(tmp_path / "copy")
    db = _library(home)
    now = utcnow()
    marker = preview.mark_away(home, 9, now=now)
    store = Store.open(db)
    try:
        assert json.loads(store.get_setting(home_mod.VISIT_KEY)) == marker
        v = home_mod.visit_of(store)
    finally:
        store.close()
    assert v is not None and v["previous"] is None
    assert (now - home_mod._parse(v["at"])).days == 9


def test_away_refuses_on_any_home_that_is_not_a_preview_even_with_the_environment(
        tmp_path, monkeypatch):
    from kranto.core import home as home_mod
    from kranto.store import Store
    live = write_home(tmp_path / "live", on=False)
    db = _library(live)
    monkeypatch.setenv(preview.ENV, "1")              # the served process's mark is not enough
    with pytest.raises(preview.PreviewRefused, match="not a preview"):
        preview.mark_away(live, 9)
    store = Store.open(db)
    try:
        assert store.get_setting(home_mod.VISIT_KEY) is None
    finally:
        store.close()
    with pytest.raises(ValueError):
        preview.mark_away(write_home(tmp_path / "copy"), 0)


def _run(*args: str, root: Path) -> tuple[int, str, str]:
    import subprocess
    env = {"HOME": str(root), "PATH": "/usr/bin:/bin", "KRANTO_PREVIEW_ROOT": str(root / "bp")}
    p = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env,
                       timeout=60, check=False)
    return p.returncode, p.stdout, p.stderr


def test_help_and_opens_first_line_carry_the_one_line_for_the_owners_pc(tmp_path):
    code, out, _ = _run("help", root=tmp_path)
    assert code == 0 and ONE_LINE.replace(ONE_LINE.split()[4], "<this machine>") in out \
        and "away [days]" in out
    _, out, _ = _run("open", root=tmp_path)        # not running here: it still says the line first
    assert out.splitlines()[0] == f"From your own PC, run this one line: {ONE_LINE}"


def test_the_script_puts_local_bin_on_its_own_path():
    text = SCRIPT.read_text()
    head = text[:text.index("ROOT=")]
    assert 'PATH="$HOME/.local/bin:$PATH"' in head and "export PATH" in head


def test_away_in_the_script_takes_whole_days_only(tmp_path):
    code, _, err = _run("away", "nine", root=tmp_path)
    assert code != 0 and "whole number of days" in err
