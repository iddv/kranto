"""Tickets in the mode of the press: a cub's kind is live only while it
is listed in ``cubs.<id>.live``, the cub's ``kranto`` range holds and ``cubs.STOP`` does not
exist; otherwise the press resolves ``dry`` and the performer is told so (or, with the STOP
file, never called). Kranto's own features keep their own modes."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from kranto.core import events, tickets
from kranto.core.cubs import settings as cub_settings
from kranto.store import iso, utcnow

UI = {"origin": "ui", "via": "cookie"}
FIELDS = {"draft_ref": "draft:1", "text": "hello", "visibility": "public", "language": "en"}


class Ctx:
    def __init__(self, cubs=None):
        self.cfg = type("Cfg", (), {"cubs": cub_settings.parse(cubs or {})})()


@pytest.fixture
def post(monkeypatch, store, tmp_path):
    """``post.mastodon`` with a recording performer, a draft of the toot cub, no STOP file."""
    seen = []
    tickets.kind_names()                  # the adapters register theirs first; this one wins

    def perform(store, ticket, context, mode):
        seen.append(mode)
        return {"state": "dry" if mode == "dry" else "done", "note": f"{mode}: ok"}

    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "perform", perform)
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    store.insert("cub_drafts", {"cub": "toot", "service": "mastodon", "ref": "draft:1",
                                "content": "{}", "content_hash": "x", "created_at": iso(utcnow())})
    return seen


def _file(store, **over):
    args = dict(cub="toot", trust="owner", granted=("post.mastodon",), kind="post.mastodon",
                fields=FIELDS, run_uuid="run-1")
    args.update(over)
    return tickets.file(store, **args)


def test_a_cub_ticket_resolves_dry_until_its_kind_is_live(store, post):
    tid = _file(store)
    out = tickets.confirm(store, tid, identity=UI, confirm=True, context=Ctx())
    assert out["state"] == "dry" and out["mode"] == "dry" and post == ["dry"]
    assert [h["state"] for h in out["history"]] == ["needs_confirm", "confirmed", "dry"]
    assert out["history"][1]["note"] == "mode: dry" and out["run_uuid"] == "run-1"
    [ev] = events.read(store, kinds=["ticket.resolved"])
    assert ev["payload"] == {"ticket_id": tid, "kind": "post.mastodon", "cub": "toot",
                             "state": "dry"}


def test_a_live_kind_runs_the_performer_live(store, post):
    tid = _file(store)
    ctx = Ctx({"toot": {"live": ["post.mastodon"]}})
    assert tickets.confirm(store, tid, identity=UI, confirm=True, context=ctx)["state"] == "done"
    assert post == ["live"]


def test_the_stop_file_resolves_dry_without_the_performer(store, post, tmp_path):
    (tmp_path / "cubs.STOP").touch()
    tid = _file(store)
    ctx = Ctx({"toot": {"live": ["post.mastodon"]}})
    out = tickets.confirm(store, tid, identity=UI, confirm=True, context=ctx)
    assert out["state"] == "dry" and "cubs.STOP exists" in out["note"] and post == []


def test_outside_its_range_a_cub_runs_dry(store, post, monkeypatch):
    store.insert("cubs", {"cub": "toot", "state": "installed", "version": "1.0.0",
                          "trust": "owner", "source_kind": "folder", "tree_hash": "t",
                          "manifest_hash": "m", "bears_range": ">=9.0",
                          "created_at": iso(utcnow())})
    tid = _file(store)
    ctx = Ctx({"toot": {"live": ["post.mastodon"]}})
    out = tickets.confirm(store, tid, identity=UI, confirm=True, context=ctx)
    assert out["state"] == "dry" and post == ["dry"]
    assert "outside its range" in tickets.press_mode(store, ctx.cfg, out)[1]


def test_a_performer_that_reports_done_in_dry_mode_is_not_believed(store, post, monkeypatch):
    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "perform",
                        lambda store, ticket, context, mode: {"state": "done", "note": "sent"})
    tid = _file(store)
    out = tickets.confirm(store, tid, identity=UI, confirm=True, context=Ctx())
    assert out["state"] == "unknown" and "in practice" in out["note"]


def test_a_first_party_ticket_keeps_its_own_mode(store):
    t = {"trust": "first-party", "kind": "trade.instruct", "cub": "invest"}
    assert tickets.press_mode(store, Ctx().cfg, t) == ("live", None)


def test_duplicates_name_the_open_ticket_and_caps_can_only_be_lowered(store, post):
    tid = _file(store)
    with pytest.raises(tickets.TicketError) as e:
        _file(store)
    assert e.value.code == 409 and e.value.ticket_id == tid
    store.insert("cub_drafts", {"cub": "toot", "service": "mastodon", "ref": "draft:2",
                                "content": "{}", "content_hash": "y", "created_at": iso(utcnow())})
    with pytest.raises(tickets.TicketError, match="at most 1") as e:
        _file(store, fields={**FIELDS, "draft_ref": "draft:2"}, per_day=1)
    assert e.value.code == 429
    assert tickets.KINDS["post.mastodon"].per_day == 5


def test_an_expired_ticket_records_its_expiry_when_pressed(store, post, monkeypatch):
    # a ticket filed with a time limit (a kind that has one, or a draft's ask of an earlier
    # release)
    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "expires_hours", 48)
    tid = _file(store, now=utcnow() - timedelta(days=3))
    with pytest.raises(tickets.TicketError, match="waited past its time"):
        tickets.confirm(store, tid, identity=UI, confirm=True, context=Ctx())
    states = [h["state"] for h in tickets.get(store, tid)["history"]]
    assert states == ["needs_confirm", "expired"] and post == []


def test_the_daily_sweep_and_a_stop_expire_open_tickets(store, post, monkeypatch):
    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "expires_hours", 48)
    old = _file(store, now=utcnow() - timedelta(days=3))
    monkeypatch.setattr(tickets.KINDS["post.mastodon"], "expires_hours", None)
    assert tickets.expire_due(store) == 1
    assert tickets.state_of(store, old)["state"] == "expired"
    store.insert("cub_drafts", {"cub": "toot", "service": "mastodon", "ref": "draft:3",
                                "content": "{}", "content_hash": "z", "created_at": iso(utcnow())})
    new = _file(store, fields={**FIELDS, "draft_ref": "draft:3"})
    assert tickets.expire_all(store, cub="toot", note="the cub was stopped") == 1
    t = tickets.get(store, new)
    assert t["state"] == "expired" and t["note"] == "the cub was stopped"
    assert t["history"][-1]["door"] == "core"


def test_the_cubs_section(tmp_path):
    from kranto import config as config_mod
    from kranto.config import ConfigError
    from kranto.core.settings import SettingError
    v = cub_settings.parse(None)
    assert v["cubs.enabled"] is True and v["cubs.max_running"] == 3 and v["per"] == {}
    got = cub_settings.parse({"enabled": False, "toot": {"live": ["post.mastodon"],
                                                         "memory_mb": 256}})
    assert got["cubs.enabled"] is False and got["per"]["toot"]["memory_mb"] == 256
    for raw, words in (({"colour": 1}, "expected a mapping"),
                       ({"Toot": {}}, "unknown keys in cubs"),
                       ({"toot": {"live": ["post.pigeon"]}}, "no request kind"),
                       ({"toot": {"pids": 4}}, "from 8 to 512"),
                       ({"toot": {"theme": "x"}}, "not one of a cub's keys"),
                       ({"max_running": 9}, "from 1 to 8")):
        with pytest.raises(ConfigError, match=words):
            cub_settings.parse(raw)
    cfg = type("C", (), {"cubs": cub_settings.parse({"default_monthly_usd": None})})()
    assert cub_settings.cub_value(cfg, "x", "monthly_usd", trust="listed") is None
    cfg = type("C", (), {"cubs": v})()
    assert cub_settings.cub_value(cfg, "x", "monthly_usd", trust="owner") is None
    assert cub_settings.cub_value(cfg, "x", "monthly_usd", trust="unreviewed") == 5.0
    assert cub_settings.cub_value(cfg, "x", "calls_per_day", trust="listed") == 200
    assert cub_settings.limits(cfg, "x", "owner") == {"memory_mb": 512, "pids": 64,
                                                      "cpu_pct": 100, "tmp_mb": 64, "kv_mb": 8}
    with pytest.raises(SettingError, match="a listed cub may have at most 1024"):
        cub_settings.check_per_cub("x", "memory_mb", 2048, trust="listed")
    assert cub_settings.check_per_cub("x", "memory_mb", 2048, trust="owner") == 2048
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    c = config_mod.load(tmp_path, dotenv=False)
    cub_settings.write(c, "cubs.toot.live", ["post.mastodon"])
    cub_settings.write(c, "cubs.max_running", 2)
    back = config_mod.load(tmp_path, dotenv=False)
    assert cub_settings.live_kinds(back, "toot") == ["post.mastodon"]
    assert back.cubs["cubs.max_running"] == 2
    with pytest.raises(SettingError, match="not one of the cubs keys"):
        cub_settings.write(c, "cubs.enabled.x", True)
    c2 = replace(back)
    assert cub_settings.cub_enabled(c2, "toot") is True
