"""The seven generic surfaces a cub fills: the manifest's new blocks and their
validation, the tile resolved in ``GET /api/features``, the mode word, the read-back schema of
every request kind, and the home's arrangement (``shell:``) with its one writer."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from kranto import features as features_pkg
from kranto.config import ConfigError
from kranto.core import registry, shell, tickets
from kranto.core.manifest import (
    UI,
    Action,
    Form,
    FormField,
    Group,
    ManifestError,
    Tile,
    TodayRow,
    UIList,
)
from kranto.core.settings import SettingError

from .conftest import web_client
from .test_features_core import _act, _v, demo, ping, with_demo  # noqa: F401 - fixtures
from .test_web import rt  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _cub_shop_on(monkeypatch):
    """A pasted manifest's check is the cub shop's: on here (cubs.developer; off by default,
.2, tested in test_hide_off.py)."""
    from kranto.core.cubs import settings as cub_settings
    monkeypatch.setattr(cub_settings, "developer", lambda cfg: True)


def _count(ctx, params):
    return {"count": 2}


def _rows(ctx, params):
    return {"items": [{"id": 1, "name": "one"}], "done": []}


def cub(**over):
    """The demo feature drawn through every surface."""
    ui = UI(kind="send", glyph="mail",
            tile=Tile(line="Monday's issue", count="count", words="waits for Send", tone="wait"),
            today_rows=(TodayRow("issue", "rows", group="needs_you", primary="test.ping",
                                 card="issue"),),
            cards={"issue": {"title": "name", "lines": [], "fields": [], "actions": ["demo.echo"],
                             "origin": "cites", "image_ref": None}},
            lists=(UIList("issues", "Issues", "rows", "issue",
                          groups=(Group("items", "Waits for you"), Group("done", "Sent")),
                          count="items"),),
            forms=(Form("compose", "Compose", "demo.echo",
                        fields=(FormField("subject", "Subject"),
                                FormField("intro", "Intro", "enum", choices=("one", "two")))),))
    base = dict(api={"count": _count, "rows": _rows}, ui=ui,
                actions=(Action("demo.echo", "Echo", _act, doors=("ui", "cli"),
                                fields=(FormField("x", "X", "int"),)),))
    base.update(over)
    return demo(**base)


def test_every_surface_round_trips_and_validates(ping):  # noqa: F811
    m = cub().to_manifest()
    assert _v(m) is m and json.loads(json.dumps(m)) == m
    ui = m["ui"]
    assert ui["kind"] == "send" and ui["glyph"] == "mail"
    assert ui["tile"] == {"line": "Monday's issue", "count": "count", "words": "waits for Send",
                          "tone": "wait"}
    assert ui["lists"][0]["groups"][1] == {"key": "done", "word": "Sent", "tone": "quiet"}
    assert ui["forms"][0]["fields"][1]["choices"] == ["one", "two"]
    assert ui["today_rows"][0]["card"] == "issue"
    assert m["actions"][0]["fields"][0]["kind"] == "int" and m["actions"][0]["place"] == "card"


@pytest.mark.parametrize("change,words", [
    (lambda m: m["ui"].update(glyph="skull"), "ui.glyph is one of"),
    (lambda m: m["ui"].update(kind="crypto"), "ui.kind is one of"),
    (lambda m: m["ui"]["tile"].update(tone="red"), "ui.tile.tone"),
    (lambda m: m["ui"]["tile"].update(count="nope"), "not one of its reads"),
    (lambda m: m["ui"]["tile"].update(colour="#f00"), "unknown keys in ui.tile"),
    (lambda m: m["ui"]["lists"][0].update(card="other"), "no card"),
    (lambda m: m["ui"]["lists"][0].update(count="later"), "names one of its groups"),
    (lambda m: m["ui"]["lists"][0].update(html="<b>"), "unknown keys in ui.lists"),
    (lambda m: m["ui"]["forms"][0].update(submit="demo.nope"), "submit names one of"),
    (lambda m: m["ui"]["forms"][0]["fields"].append({"key": "c", "label": "C",
                                                     "kind": "enum"}), "needs its choices"),
    (lambda m: m["ui"]["forms"][0]["fields"].append({"key": "c", "label": "C",
                                                     "kind": "file"}), "kind is one of"),
    (lambda m: m["ui"]["today_rows"][0].update(primary="money.move"), "primary"),
    (lambda m: m["ui"]["today_rows"][0].update(card="nope"), "no card"),
    (lambda m: m["ui"]["cards"]["issue"].update(component="X.svelte"), "unknown keys"),
    (lambda m: m["ui"]["cards"]["issue"].update(actions=["demo.gone"]), "no action"),
    (lambda m: m["actions"][0].update(place="top"), "place is one of card, head"),
    (lambda m: (m.update(trust="listed"), m["actions"][0].update(place="head")),
     "first-party only"),
])
def test_the_validator_refuses_a_surface_the_core_does_not_draw(change, words, ping):  # noqa: F811
    m = cub().to_manifest()
    change(m)
    with pytest.raises(ManifestError, match=words):
        _v(m)


def test_news_declares_its_surfaces():
    check = {m["id"]: m for m in registry.check()}
    news = check["news"]["ui"]
    assert news["kind"] == "watch" and news["glyph"] == "grid"
    assert news["tile"]["count"] == "count" and news["tile"]["tone"] == "new"
    assert news["today_rows"][0]["read"] == "today" and news["today_rows"][0]["card"] is None
    assert news["cards"]["brief"]["title"] == "headline"
    assert [w["read"] for w in news["widgets"]] == ["widget_brief"]
    assert {a["place"] for a in check["news"]["actions"]} == {"card"}


def test_the_listing_resolves_the_tile_and_says_the_mode(monkeypatch, with_demo, rt):  # noqa: F811
    from kranto.web.app import create_app
    f = cub()
    monkeypatch.setattr(features_pkg, "FEATURES", (f,))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        row = web.get("/api/features").json()["features"][0]
        assert row["tile"] == {"line": "Monday's issue", "count": 2, "words": "waits for Send",
                               "tone": "wait"}
        assert row["mode"] == "live"
    monkeypatch.setattr(features_pkg, "FEATURES", (replace(f, mode=lambda ctx: "drafts only"),))
    assert registry.describe(rt)["features"][0]["mode"] == "drafts only"
    monkeypatch.setattr(features_pkg, "FEATURES", (replace(f, mode=lambda ctx: 1 / 0),))
    assert registry.describe(rt)["features"][0]["mode"] == "unknown"


def test_a_feature_says_off_while_off(rt):  # noqa: F811
    news = registry.by_id("news")
    assert registry.mode_of(rt, news, {}, False) == "off"
    assert registry.mode_of(rt, news, {}, True) != "off"


@pytest.fixture
def own_kind(monkeypatch):
    """A kind only Kranto's own features may ask for (none ships now that Invest is gone)."""
    tickets.kind_names()
    kind = tickets.Kind("publish.own", "Publish as Kranto",
                        {"what": tickets.Field("str", label="What")}, first_party_only=True)
    monkeypatch.setitem(tickets.KINDS, "publish.own", kind)
    return kind


def test_every_request_kind_has_a_read_back_schema(own_kind):
    kinds = tickets.describe_kinds()
    assert {"send.newsletter", "post.mastodon", "book.propose", "publish.own"} <= set(kinds)
    assert kinds["send.buttondown"]["alias_of"] == "send.newsletter"     # one release
    send = kinds["send.newsletter"]
    assert [f["key"] for f in send["fields"]] == ["draft_ref", "subject", "audience", "when"]
    assert send["fields"][1]["label"] == "Subject" and send["page_only"]
    assert send["performs"] and not send["first_party_only"]
    assert kinds["publish.own"]["first_party_only"]
    assert [f["label"] for f in kinds["publish.own"]["fields"]] == ["What"]
    assert not kinds["book.propose"]["performs"]
    post = [f["key"] for f in kinds["post.mastodon"]["fields"]]
    assert post == ["draft_ref", "text", "visibility", "language"]     # no account: the core's
    spec = tickets.KINDS["post.mastodon"]
    back = tickets.readback_of(spec, {"draft_ref": "draft:1", "text": "hello",
                                      "visibility": "public", "language": "en"})
    assert back[1] == ["Text", "hello"]


def _draft(store, cub, ref):
    from kranto.store import iso, utcnow
    store.insert("cub_drafts", {"cub": cub, "service": "mastodon", "ref": ref, "content": "{}",
                                "content_hash": "x", "created_at": iso(utcnow())})


def test_a_cub_kind_without_its_performer_is_filed_then_refused_at_the_press(store):
    fields = {"legs": "AMS-LIS", "total": 120.0, "currency": "EUR", "links": "the airline"}
    rid = tickets.file(store, cub="trips", trust="listed", granted=("book.propose",),
                       kind="book.propose", fields=fields)
    with pytest.raises(tickets.TicketError, match="no performer"):
        tickets.confirm(store, rid, identity={"origin": "ui", "via": "cookie"}, confirm=True)
    with pytest.raises(tickets.TicketError, match="page or from the command line"):
        tickets.decline(store, rid, identity=None)
    assert tickets.decline(store, rid, identity={"origin": "cli"})["state"] == "declined"


def test_a_ticket_names_only_the_filing_cubs_draft_and_never_an_account(store, own_kind):
    _draft(store, "other", "draft:8")
    base = {"draft_ref": "draft:8", "text": "hi", "visibility": "public", "language": "en"}
    with pytest.raises(tickets.TicketError, match="not one of toot's drafts"):
        tickets.file(store, cub="toot", trust="listed", granted=("post.mastodon",),
                     kind="post.mastodon", fields=base)
    with pytest.raises(tickets.TicketError, match="unknown: account"):
        tickets.file(store, cub="other", trust="listed", granted=("post.mastodon",),
                     kind="post.mastodon", fields={**base, "account": "@a@b.social"})
    with pytest.raises(tickets.TicketError, match="Kranto's own"):
        tickets.file(store, cub="other", trust="owner", granted=("publish.own",),
                     kind="publish.own", fields={"what": "x"})


PASTED = """\
schema: 1
api: cub/1
id: weekly_note
version: 1.0.0
title: Weekly note
says: A note a week from your topics.
reads: [topics]
model: {tiers: [reason], purposes: [weekly_note], monthly_usd: 1}
jobs:
  - {kind: weekly_note.write, every_hours: 168, at: "08:00", days: [mon]}
provides: [count]
ui: {kind: other, glyph: pen, tile: {line: A note a week, count: count}}
"""


def test_a_pasted_manifest_is_checked_in_words_and_never_installed(rt, own_kind):  # noqa: F811
    from kranto.web.app import create_app
    good = PASTED
    out = registry.check_text(good)
    assert out["ok"] and out["trust"] == "unreviewed" and not out["installable"]
    assert out["manifest"]["id"] == "weekly_note" and "its folder or its git URL" in out["why"]
    assert dict(out["words"])["Trust"].startswith("Nobody at Kranto has read this code")
    assert out["manifest"]["entry"] == "main.py"                     # defaults filled
    assert out["manifest"]["jobs"][0]["deadline_s"] == 600
    import yaml

    from kranto.core.manifest import manifest_hash
    assert out["hash"] == manifest_hash(yaml.safe_load(good))        # the file as written
    assert registry.check_text("")["error"] == "paste the cub's cub.yaml"
    reads = "reads: [topics]"
    for words, change in (("reserved word", ("id: weekly_note", "id: llm")),
                          ("reserved word", ("id: weekly_note", "id: news")),
                          ("cub/2", ("api: cub/1", "api: cub/2")),
                          ("schema 2", ("schema: 1", "schema: 2")),
                          ("Kranto's own", (reads, "trust: first-party\n" + reads)),
                          ("owns no tables", (reads, "owns: [x_rows]\n" + reads)),
                          ("Kranto's own", (reads, "requests: [publish.own]")),
                          ("unknown keys in jobs", ("days: [mon]", "days: [mon], cron: x"))):
        assert words in registry.check_text(good.replace(*change))["error"], words
    assert "not YAML" in registry.check_text("a: [")["error"]
    assert registry.check_text("- a list")["error"] == "a manifest is a mapping of keys"
    bad = good.replace("reads: [topics]", "reads: [secrets]")
    assert "reads[0] is one of" in registry.check_text(bad)["error"]
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        assert web.post("/api/cubs/check", json={"text": good}).json()["ok"]
        assert web.post("/api/cubs/check", json={"text": "x: 1"}).status_code == 400


# -- the arrangement ------------------------------------------------------------------------------


def test_the_shell_section_defaults_and_refuses_what_it_does_not_know():
    v = shell.parse(None)
    assert v["shell.layout"] == "new" and v["shell.pins"] is None and v["shell.needs_cap"] == 3
    got = shell.parse({"layout": "classic", "pins": ["invest"], "needs_you": {"toot": True}})
    assert got["shell.layout"] == "classic" and got["shell.pins"] == ["invest"] \
        and got["needs_you"]["toot"]
    # the layout's two keys until 0.5.8 are still read: false in either is classic
    assert shell.parse({"home": True, "doors": True})["shell.layout"] == "new"
    assert shell.parse({"home": False})["shell.layout"] == "classic"
    assert shell.parse({"doors": False})["shell.layout"] == "classic"
    assert shell.parse({"doors": False, "layout": "new"})["shell.layout"] == "new"
    with pytest.raises(ConfigError, match="true or false"):
        shell.parse({"doors": "yes"})
    for raw, words in (({"colour": "red"}, "unknown keys in shell"),
                       ({"layout": "tabs"}, "one of new, classic"),
                       ({"needs_cap": 20}, "from 1 to 10"),
                       ({"pins": ["aa", "bb", "cc", "dd", "ee", "ff", "gg"]}, "at most 6"),
                       ({"pins": ["xx", "xx"]}, "twice"),
                       ({"new": {"toot": "yes"}}, "true or false")):
        with pytest.raises(ConfigError, match=words):
            shell.parse(raw)


def test_needs_you_by_trust_and_pins_by_install_order(monkeypatch):
    strangers = [replace(demo(), id=f"c{i}", trust=t)
                 for i, t in enumerate(("listed", "owner", "unreviewed", "generated", "reviewed",
                                        "first-party", "listed"))]
    cfg = type("C", (), {"shell": shell.parse({"hidden": ["c1"]})})()
    a = shell.arrangement(cfg, [registry.by_id("news"), *strangers])
    assert [c["id"] for c in a["cubs"]] == [f"c{i}" for i in range(7)]   # News is a door
    allowed = {c["id"]: c["needs_you"] for c in a["cubs"]}
    assert allowed == {"c0": False, "c1": True, "c2": False, "c3": False, "c4": False,
                       "c5": True, "c6": False}
    assert a["pins"] == ["c0", "c2", "c3", "c4", "c5", "c6"] and a["hidden"] == ["c1"]


def test_the_one_writer_writes_the_file_and_reset_puts_the_defaults_back(tmp_path):
    from kranto import config as config_mod
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    cfg = config_mod.load(tmp_path, dotenv=False)
    # a file that says classic (written before open-source wave 1) is kept as it says
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML
                                         + "\nshell:\n  layout: classic\n")
    shell.write(cfg, "shell.pins", ["invest"])
    shell.write(cfg, "shell.needs_you.toot", True)
    back = config_mod.load(tmp_path, dotenv=False).shell
    assert back["shell.layout"] == "classic" and back["shell.pins"] == ["invest"] and \
        back["needs_you"] == {"toot": True}
    with pytest.raises(SettingError, match="not one of the shell's keys"):
        shell.write(cfg, "shell.theme", "dark")
    with pytest.raises(SettingError, match="one of new, classic"):
        shell.write(cfg, "shell.layout", "tabs")
    # one layout: classic is never written again, by its key or an old switch
    for key, value in (("shell.layout", "classic"), ("shell.home", False), ("shell.doors", False)):
        with pytest.raises(SettingError, match="one layout"):
            shell.write(cfg, key, value)
    with pytest.raises(SettingError, match="one layout"):
        shell.write_many(cfg, {"shell.layout": "classic", "shell.new_cap": 2})
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.layout"] == "classic"
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.new_cap"] == 4  # none written
    # the arrangement draws new whatever the file says; reset keeps what it says
    cfg = config_mod.load(tmp_path, dotenv=False)
    a = shell.arrangement(cfg, [])
    assert a["layout"] == "new" and a["home"] and a["doors"]
    out = shell.reset(cfg)
    again = config_mod.load(tmp_path, dotenv=False).shell
    assert out["shell.layout"] == again["shell.layout"] == "classic"  # the file's word stays
    assert again["shell.pins"] is None and again["needs_you"] == {}
    # an old switch written true is the layout it meant, never its own key again
    assert shell.write(cfg, "shell.doors", True)["shell.layout"] == "new"
    import yaml
    assert (
        set(yaml.safe_load((tmp_path / "kranto.yaml").read_text())["shell"]) & {"home", "doors"}
        == set()
    )


def test_the_old_switches_are_migrated_once_as_the_layout(tmp_path):
    from kranto import config as config_mod

    yml = tmp_path / "kranto.yaml"
    yml.write_text(
        config_mod.DEFAULT_CONFIG_YAML + "\n# the home\nshell:\n  home: true  # mock D\n"
        '  doors: false\n  pins: ["invest"]\n\nnews:\n  enabled: true\n'
    )
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.layout"] == "classic"
    assert shell.migrate(tmp_path) == "classic"
    text = yml.read_text()
    assert "home: true" not in text and "doors:" not in text and "# the home" in text
    got = config_mod.load(tmp_path, dotenv=False)
    assert got.shell["shell.layout"] == "classic" and got.shell["shell.pins"] == ["invest"]
    assert shell.migrate(tmp_path) is None  # once: nothing left to do
    assert yml.read_text() == text
    # a layout already written wins over the old switches beside it
    yml.write_text(config_mod.DEFAULT_CONFIG_YAML + '\nshell:\n  layout: "new"\n  home: false\n')
    assert shell.migrate(tmp_path) == "new" and "  home: false" not in yml.read_text()
    # flow style is left as it is; its old keys go on being read
    yml.write_text(config_mod.DEFAULT_CONFIG_YAML + "\nshell: {home: false}\n")
    assert shell.migrate(tmp_path) is None
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.layout"] == "classic"


def test_the_shell_over_http_is_typed_and_logged(rt, tmp_path):  # noqa: F811
    from kranto import config as config_mod
    from kranto.web.app import create_app

    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    rt.cfg = replace(rt.cfg, root=tmp_path)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        a = web.get("/api/shell").json()
        assert a["layout"] == "new" and a["needs_cap"] == 3 and a["home"] and a["doors"]
        # one layout: classic is refused, new is still a write
        assert (
            web.post("/api/shell", json={"key": "shell.layout", "value": "classic"}).status_code
            == 400
        )
        r = web.post("/api/shell", json={"key": "shell.layout", "value": "new"})
        assert r.status_code == 200 and r.json()["layout"] == "new"
        assert r.json()["home"] and r.json()["doors"]  # as a 0.5.8 page reads it
        assert web.post("/api/shell", json={"key": "shell.layout", "value": "x"}).status_code == 400
        # Kranto's own News is a door, and no cub is installed: no row
        assert [c["id"] for c in a["cubs"]] == []
        r = web.post("/api/shell", json={"key": "shell.new_cap", "value": 2})
        assert r.status_code == 200 and r.json()["new_cap"] == 2
        assert web.post("/api/shell", json={"key": "shell.new_cap", "value": 99}).status_code == 400
        assert web.post("/api/shell", json={"reset": True}).json()["new_cap"] == 4
        ev = web.get("/api/events?kind=settings.changed").json()["events"]
        assert [e["payload"]["key"] for e in ev][-2:] == ["shell.new_cap", "shell.reset"]
