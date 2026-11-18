"""The home as widgets: the six kinds' contract and caps
(``bears_cub.widgets``), the manifest's ``ui.widgets`` block, ``shell.widgets`` and its one
writer, and ``GET /api/home``: the default home is 0.5.10's seven parts, a widget is on the home
only when the person's list names it, and a slow, failing or hostile widget is its own slot's
problem, never the home's."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

from bears_cub import widgets
from bears_cub.widgets import WidgetAnswerError, clean
from kranto import features as features_pkg
from kranto.core import home, manifest, registry, shell
from kranto.core.manifest import UI, ManifestError, UIList, Widget
from kranto.core.settings import SettingError

from .conftest import web_client
from .test_features_core import _v, demo, ping, with_demo  # noqa: F401 - fixtures
from .test_web import rt  # noqa: F401 - fixture

HTML = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


# -- the kinds ----------------------------------------------------------------------------------


def test_each_kind_draws_its_shape_and_says_nothing_changed():
    ok = {
        "stat": {"value": 12, "words": "trends followed",
                 "delta": {"value": "+2", "words": "this week", "tone": "up"},
                 "facts": [{"label": "Watching", "value": "3 of 5"}], "line": "last run 2 h ago"},
        "rows": {"rows": [{"id": 1, "title": "One", "meta": "m", "tone": "wait", "tag": "paper",
                           "at": "2026-10-22T10:00:00Z", "open": "cub/toot?sel=o1"}]},
        "series": {"series": [{"label": "Robotics", "points": [[1, 2], [2, 3.5]], "unit": "%"}],
                   "value": "3.5", "words": "now", "as_of": "2026-10-22T10:00:00Z"},
        "table": {"columns": [{"key": "i", "label": "Instrument", "kind": "text"},
                              {"key": "p", "label": "Price", "kind": "money"}],
                  "rows": [{"i": "XYZ", "p": 12.5}, {"i": "ABC", "p": None}],
                  "note": "Not financial advice."},
        "stages": {"steps": [{"key": "quiet", "word": "quiet"}, {"key": "up", "word": "emerging"}],
                   "items": [{"id": "k", "title": "Humanoids", "step": "up", "since": "Sep",
                              "change": {"from": "quiet", "to": "up",
                                         "at": "2026-10-20T00:00:00Z"}}]},
        "note": {"markdown": "Two **things**, [a list](#/cub/toot?list=posts)."},
    }
    for kind, answer in ok.items():
        out, changes = clean(kind, "M", answer, cub="toot")
        assert changes == [], (kind, changes)
    assert clean("stat", "S", ok["stat"], cub="toot")[0]["value"] == "12"
    assert clean("rows", "M", ok["rows"], cub="toot")[0]["rows"][0]["open"] == "cub/toot?sel=o1"


@pytest.mark.parametrize("kind,answer,words", [
    ("stat", {"words": "x"}, "value is missing"),
    ("stat", {"value": {"a": 1}, "words": "x"}, "value must be text"),
    ("stat", {"value": 1, "words": "x", "delta": {"value": 1, "tone": "sideways"}}, "tone"),
    ("rows", {"rows": "not a list"}, "rows must be a list"),
    ("rows", {"rows": [{"id": 1}]}, r"rows\[0\].title is missing"),
    ("series", {"series": []}, "needs at least 1"),
    ("series", {"series": [{"label": "a", "points": [[1]]}]}, r"is \[x, y\]"),
    ("table", {"columns": [{"key": "a", "label": "A", "kind": "chart"}], "rows": []}, "kind"),
    ("stages", {"steps": [{"key": "a", "word": "A"}], "items": []}, "needs at least 2"),
    ("note", {"markdown": ""}, "markdown is empty"),
    ("note", ["a list"], "must be a mapping"),
    ("pie", {}, "no widget kind pie"),
])
def test_a_wrong_shape_is_refused_in_words(kind, answer, words):
    with pytest.raises(WidgetAnswerError, match=words):
        clean(kind, "M", answer, cub="toot")


def test_the_caps_cut_and_drop_and_say_so():
    rows = {"rows": [{"id": i, "title": "t" * 200} for i in range(30)]}
    out, changes = clean("rows", "S", rows, cub="toot")
    assert len(out["rows"]) == 3 and out["total"] == 20          # 20 answered at most, S draws 3
    assert len(out["rows"][0]["title"]) == 120 and out["rows"][0]["title"].endswith("…")
    assert any("30 answered, 20 drawn" in c for c in changes)
    assert len(clean("rows", "L", rows, cub="toot")[0]["rows"]) == 8
    big = {"value": 1, "words": "x", "line": "y" * 70000}
    with pytest.raises(WidgetAnswerError, match="over 64 KiB"):
        clean("stat", "M", big, cub="toot")
    t = {"columns": [{"key": str(i), "label": "c"} for i in range(9)], "rows": []}
    assert len(clean("table", "M", t, cub="toot")[0]["columns"]) == 5


def test_a_link_never_leaves_the_cubs_own_page():
    rows = {"rows": [{"id": 1, "title": "a", "open": "settings/accounts"},
                     {"id": 2, "title": "b", "open": "cub/other?sel=1"},
                     {"id": 3, "title": "c", "open": "https://evil.example.com"},
                     {"id": 4, "title": "d", "open": "javascript:alert(1)"},
                     {"id": 5, "title": "e", "open": "cub/toot/../settings"},
                     {"id": 6, "title": "f", "open": "cub/tootle"},
                     {"id": 7, "title": "g", "open": "#/cub/toot?list=posts"}]}
    out, changes = clean("rows", "L", rows, cub="toot")
    assert [r.get("open") for r in out["rows"]] == [None] * 6 + ["cub/toot?list=posts"]
    assert len(changes) == 6 and all("leaves toot's page" in c for c in changes)
    # a first-party feature may open its own doors (News's brief opens #/news)
    got = clean("rows", "M", {"rows": [{"id": 1, "title": "a", "open": "news"}]}, cub="news",
                first_party=True)[0]
    assert got["rows"][0]["open"] == "news"


def test_a_note_is_text_its_links_are_kranto_or_its_hosts_and_markup_is_said():
    md = (f"Hi {HTML} [mine](#/cub/toot) [settings](#/settings) [site](https://toot.example/x)"
          " [far](https://evil.example/x) ![img](https://toot.example/a.png) <https://evil.example>"
          "\n# Big\n## Bigger\n### ok")
    out, changes = clean("note", "M", {"markdown": md}, cub="toot", hosts=("toot.example",))
    s = out["markdown"]
    assert "[mine](#/cub/toot)" in s and "[site](https://toot.example/x)" in s
    assert "[settings]" not in s and "settings" in s                # its words, no link
    assert "evil.example/x)" not in s and "far" in s
    assert "![img]" not in s and "<https://evil.example>" not in s
    assert "\n### Big\n### Bigger\n### ok" in s
    assert any("holds HTML: drawn as text" in c for c in changes)
    assert HTML in s                    # kept as text: the page draws it with textContent only


def test_a_widget_in_words():
    w = {"title": "Trends I follow", "kind": "stages", "sizes": ["M", "L"],
         "read": "widget_trends", "every_s": 300}
    assert widgets.describe(w) == ("Trends I follow (stages, M or L, from its read "
                                   "widget_trends, every 5 minutes)")
    assert widgets.describe({**w, "sizes": ["S"], "every_s": 3600}).endswith("every 1 hour)")


# -- the manifest -------------------------------------------------------------------------------


def _w(**over) -> Widget:
    base = dict(id="count", title="Count", kind="stat", read="count", sizes=("S", "M"),
                open="issues")
    base.update(over)
    return Widget(**base)


def _with(*ws) -> object:
    ui = UI(lists=(UIList("issues", "Issues", "rows", "issue"),),
            cards={"issue": {"title": "name", "lines": [], "fields": [], "actions": [],
                             "origin": None, "image_ref": None}}, widgets=ws)
    return demo(api={"count": lambda c, p: {"value": 1, "words": "x"},
                     "rows": lambda c, p: {"rows": []}}, ui=ui)


def test_widgets_round_trip_and_validate(ping):  # noqa: F811
    m = _with(_w()).to_manifest()
    assert m["ui"]["widgets"] == [{"id": "count", "title": "Count", "says": "", "kind": "stat",
                                   "read": "count", "sizes": ["S", "M"], "every_s": 300,
                                   "open": "issues", "empty": ""}]
    assert _v(m) is m
    back = manifest.widget_of(m["ui"]["widgets"][0])
    assert back == _w()


@pytest.mark.parametrize("change,words", [
    (lambda m: m["ui"]["widgets"][0].update(read="nope"), "is not one of its reads"),
    (lambda m: m["ui"]["widgets"][0].update(open="nope"), "open names one of its ui.lists"),
    (lambda m: m["ui"]["widgets"].append(dict(m["ui"]["widgets"][0])), "declared twice"),
    (lambda m: m["ui"]["widgets"][0].update(sizes=["XL"]), r"sizes\[0\] is one of S, M, L"),
    (lambda m: m["ui"]["widgets"][0].update(sizes=[]), "needs at least 1"),
    (lambda m: m["ui"]["widgets"][0].update(every_s=10), "every_s is at least 60"),
    (lambda m: m["ui"]["widgets"][0].update(kind="iframe"), "kind is one of stat"),
    (lambda m: m["ui"]["widgets"][0].update(html="<b>"), "unknown keys in ui.widgets"),
    (lambda m: m["ui"]["widgets"][0].update(title="t" * 41), "at most 40 characters"),
    (lambda m: m["ui"]["widgets"].extend(dict(m["ui"]["widgets"][0], id=f"w{i}")
                                         for i in range(4)), "holds at most 4"),
])
def test_the_validator_refuses_a_widget_the_core_does_not_draw(change, words, ping):  # noqa: F811
    m = _with(_w()).to_manifest()
    change(m)
    with pytest.raises(ManifestError, match=words):
        _v(m)


def test_no_cub_may_take_a_built_in_widgets_word():
    assert set(home.BY_ID) <= manifest.reserved_ids()
    # a retired built-in keeps its word reserved: an older arrangement may still name it
    assert set(home.BY_ID) | home.RETIRED == set(manifest.HOME_WIDGETS)
    assert not set(home.BY_ID) & home.RETIRED


# -- shell.widgets ------------------------------------------------------------------------------


def test_the_default_home_is_the_seven_parts_in_their_order():
    assert home.DEFAULT == ("greeting", "status", "needs", "doors", "new", "cubs", "foot")
    assert shell.parse(None)["shell.widgets"] is None
    got = home.resolve(None, [])
    assert [e["id"] for e in got] == list(home.DEFAULT)
    assert [e["size"] for e in got] == ["L"] * 7 and all(e["phone"] for e in got)


@pytest.mark.parametrize("value,words", [
    ("needs", "is a list"),
    ([{"id": "weather"}], "no built-in widget weather"),
    ([{"id": "Needs"}], "not a widget id"),
    ([{"id": "needs"}, {"id": "needs"}], "on the home already"),
    ([{"id": "toot.ab"}, {"id": "toot.ab"}], "on the home already"),
    ([{"id": "needs", "size": "S"}], "size is one of L, M"),
    ([{"id": "toot.ab", "size": "XL"}], "size is one of S, M, L"),
    ([{"id": "needs", "phone": "no"}], "phone is true or false"),
    ([{"id": "needs", "colour": "red"}], "takes no colour"),
    ([{"id": "topic"}], "topic needs topic"),
    ([{"id": "topic", "options": {"topic": "x"}}], "whole number"),
    ([{"id": "topic", "options": {"topic": 3, "html": 1}}], "takes no html"),
    ([{"id": "toot.ab", "options": {"x": 1}}], "a cub's widget takes no options"),
    ([{"id": "needs"}] * 41, "at most 40"),
])
def test_the_list_refuses_what_it_does_not_take(value, words):
    with pytest.raises(SettingError, match=words):
        shell.check_value("shell.widgets", value)


def test_several_topics_a_flag_and_an_unknown_feature_kept():
    v = [{"id": "topic", "options": {"topic": 13}}, {"id": "topic", "options": {"topic": 4,
                                                                                  "rows": 5}},
         {"id": "spend", "size": "S", "phone": False}, {"id": "gone.widget"}]
    assert shell.check_value("shell.widgets", v) == v
    got = home.resolve(v, [])
    assert [e["known"] for e in got] == [True, True, True, False]
    assert got[2]["phone"] is False and got[0]["size"] == "S" and got[1]["options"]["rows"] == 5
    assert got[3] == {"n": 3, "id": "gone.widget", "known": False}


def test_one_write_reset_and_the_whole_arrangement_back_in_one_write(tmp_path):
    from kranto import config as config_mod
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    cfg = config_mod.load(tmp_path, dotenv=False)
    mine = [{"id": "spend", "size": "M"}, {"id": "needs"}, {"id": "radar.trends"}]
    shell.write(cfg, "shell.widgets", mine)
    shell.write(cfg, "shell.pins", ["invest"])
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.widgets"] == mine
    before = config_mod.load(tmp_path, dotenv=False).shell
    shell.reset(cfg)
    after = config_mod.load(tmp_path, dotenv=False).shell
    assert after["shell.widgets"] is None and after["shell.pins"] is None
    # Undo after Reset to default: every key as it was, in one write
    got = shell.write_many(cfg, {"shell.widgets": before["shell.widgets"],
                                 "shell.pins": before["shell.pins"]})
    assert got["shell.widgets"] == mine and got["shell.pins"] == ["invest"]
    with pytest.raises(SettingError, match="no built-in widget"):
        shell.write_many(cfg, {"shell.pins": None, "shell.widgets": [{"id": "weather"}]})
    assert config_mod.load(tmp_path, dotenv=False).shell["shell.pins"] == ["invest"]  # nothing


# -- GET /api/home ------------------------------------------------------------------------------

RELEASE = threading.Event()


def _slow(ctx, params):
    RELEASE.wait(30)
    return {"value": 1, "words": "late"}


def _hostile(ctx, params):
    return {"rows": [{"id": 1, "title": HTML, "meta": "<b>bold</b>",
                     "open": "https://evil.example.com"}]}


def _broken(ctx, params):
    raise RuntimeError("the cub fell over")


def _fine(ctx, params):
    return {"value": params.get("size"), "words": "sized"}


def _home_feature():
    ws = (Widget("slow", "Slow", "stat", "slow"), Widget("hostile", "Hostile", "rows", "hostile"),
          Widget("broken", "Broken", "stat", "broken"),
          Widget("fine", "Fine", "stat", "fine", sizes=("S", "M")))
    return demo(api={"slow": _slow, "hostile": _hostile, "broken": _broken, "fine": _fine},
                ui=UI(widgets=ws))


@pytest.fixture
def home_app(monkeypatch, with_demo, rt, tmp_path):  # noqa: F811
    from kranto import config as config_mod
    from kranto.web.app import create_app
    RELEASE.clear()
    monkeypatch.setattr(features_pkg, "FEATURES", (_home_feature(),))
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    rt.cfg = replace(rt.cfg, root=tmp_path)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        yield web
    RELEASE.set()


def test_the_default_home_and_installing_a_feature_with_widgets_changes_nothing(home_app):
    got = home_app.get("/api/home").json()
    assert [e["id"] for e in got["widgets"]] == list(home.DEFAULT) and got["custom"] is False
    assert all(e["builtin"] for e in got["widgets"])
    assert got["slots"] == {} and got["rows"] == {"needs_you": {}, "new": {}}
    groups = {g["id"]: g for g in got["library"]}
    assert [w["id"] for w in groups["demo"]["widgets"]] == ["demo.slow", "demo.hostile",
                                                            "demo.broken", "demo.fine"]
    assert not any(w["on_home"] for w in groups["demo"]["widgets"])
    kranto = {w["id"]: w for w in groups["kranto"]["widgets"]}
    assert kranto["needs"]["on_home"] and not kranto["spend"]["on_home"] and kranto["topic"]["many"]
    # Activity: in the library, off by default, every size
    assert not kranto["activity"]["on_home"] and "activity" not in home.DEFAULT
    assert home_app.get("/api/shell").json()["widgets"] == got["widgets"]


def test_a_slow_a_broken_and_a_hostile_widget_never_hold_the_home(home_app, monkeypatch):
    monkeypatch.setattr(home, "BUDGET_S", 0.5)
    mine = [{"id": "demo.slow"}, {"id": "demo.hostile"}, {"id": "demo.broken"},
            {"id": "demo.fine", "size": "S"}, {"id": "needs"}]
    r = home_app.post("/api/shell", json={"key": "shell.widgets", "value": mine})
    assert r.status_code == 200 and [e["id"] for e in r.json()["widgets"]] == [m["id"]
                                                                                for m in mine]
    t0 = time.monotonic()
    s = home_app.get("/api/home").json()["slots"]
    assert time.monotonic() - t0 < 2.5                                # the default budget, 2 s
    assert s["0"] == {"state": "loading"}
    assert s["1"]["state"] == "ok"
    row = s["1"]["data"]["rows"][0]
    assert row["title"] == HTML and row["meta"] == "<b>bold</b>"      # text, as it came
    assert "open" not in row                                          # never off its page
    # its words, and the id Send this error files it under
    assert {k: v for k, v in s["2"].items() if k != "error_id"} == {
        "state": "error", "error": "the cub fell over"}
    assert len(s["2"]["error_id"]) == 8
    assert s["3"] == {"state": "ok", "data": {"value": "S", "words": "sized"}}
    assert "4" not in s                                               # a built-in: the page's
    # asked again while the slow read still runs: the one read in flight, still loading
    assert home_app.get("/api/home?slot=0").json()["slots"] == {"0": {"state": "loading"}}
    RELEASE.set()
    for _ in range(50):
        got = home_app.get("/api/home?slot=0").json()["slots"]["0"]
        if got["state"] == "ok":
            break
        time.sleep(0.05)
    assert got == {"state": "ok", "data": {"value": "1", "words": "late"}}
    assert home_app.get("/api/home?slot=x").status_code == 400


def test_a_feature_that_is_off_draws_no_tile_and_keeps_its_place(home_app, monkeypatch):
    """.2: no tile for a feature that is off; its widget stays in the list
    (known: false) and is drawn again, in its place, once the feature is on."""
    home_app.post("/api/shell", json={"key": "shell.widgets", "value": [{"id": "demo.fine"}]})
    with monkeypatch.context() as m:
        m.setattr(registry, "enabled", lambda cfg, f: False)
        got = home_app.get("/api/home").json()
        assert "0" not in got["slots"] and got["widgets"][0]["known"] is False
    assert "0" in home_app.get("/api/home").json()["slots"]


def test_the_home_reads_only_the_reads_the_widgets_declare(home_app, monkeypatch):
    """A widget calls its own feature's declared read and nothing else: the page names a slot
    by its place, never a read; another of the feature's reads is not called."""
    called = []
    f = _home_feature()
    def spy_of(name):
        def run(ctx, params):
            called.append(name)
            return {"value": 1, "words": name}
        return run

    spy = {k: spy_of(k) for k in f.api}
    monkeypatch.setattr(features_pkg, "FEATURES", (replace(f, api=spy),))
    home_app.post("/api/shell", json={"key": "shell.widgets", "value": [{"id": "demo.fine"}]})
    home_app.get("/api/home?read=slow&feature=demo")
    assert called == ["fine"]


def test_needs_you_and_new_carry_the_cubs_rows_under_their_allowance(home_app, monkeypatch):
    from kranto.core.manifest import TodayRow
    rows = {"rows": [{"id": i, "title": f"r{i}"} for i in range(30)]}
    f = demo(api={"r": lambda c, p: rows},
             ui=UI(today_rows=(TodayRow("x", "r", group="needs_you"),)))
    monkeypatch.setattr(features_pkg, "FEATURES", (f, replace(f, id="other"),
                                                   replace(f, id="third")))
    home_app.post("/api/shell", json={"key": "shell.hidden", "value": ["other"]})
    home_app.post("/api/shell", json={"key": "shell.needs_you.third", "value": False})
    r = home_app.get("/api/home").json()["rows"]
    assert list(r["needs_you"]) == ["demo"]
    assert len(r["needs_you"]["demo"]["data"]) == 20 and r["new"] == {}
    # without Needs you on the home the greeting's sentence still counts them; with neither,
    # nobody reads them
    home_app.post("/api/shell", json={"key": "shell.widgets",
                                      "value": [{"id": "greeting"}, {"id": "doors"}]})
    assert list(home_app.get("/api/home").json()["rows"]["needs_you"]) == ["demo"]
    home_app.post("/api/shell", json={"key": "shell.widgets", "value": [{"id": "doors"}]})
    assert home_app.get("/api/home").json()["rows"] == {}


# -- the SDK: FakeHost.widget(), the standard fixture, check's words ----------------------------

WIDGET_YAML = """schema: 1
api: cub/1
id: tally
version: 1.0.0
title: Tally
says: Counts things for the home.
reads: [library]
provides: [items, stat, rows]
http: {hosts: [tally.example]}
ui:
  lists: [{id: items, word: Items, read: items, card: item}]
  cards: {item: {title: name}}
  widgets:
    - {id: count, title: Count, kind: stat, read: stat, sizes: [S, M], open: items}
    - {id: latest, title: Latest, kind: rows, read: rows, sizes: [M, L]}
"""

GOOD = """from bears_cub import Cub

cub = Cub()


@cub.read("items")
def items(ctx, params):
    return {"items": []}


@cub.read("stat")
def stat(ctx, params):
    return {"value": 3, "words": "things counted"}


@cub.read("rows")
def rows(ctx, params):
    seen = ctx.read.observations(limit=20)["observations"]
    return {"rows": [{"id": o["id"], "title": o["title"], "open": "cub/tally?sel=o%d" % o["id"]}
                     for o in seen]}
"""

BAD = GOOD.replace('"open": "cub/tally?sel=o%d" % o["id"]', '"open": o["title"]').replace(
    'return {"value": 3, "words": "things counted"}',
    'return {"value": 3, "words": "things counted", "line": "x" * 500}')


def _cub(folder, main: str, yaml_text: str = WIDGET_YAML):
    folder.mkdir(exist_ok=True)
    (folder / "cub.yaml").write_text(yaml_text)
    (folder / "main.py").write_text(main)
    return folder


def test_fakehost_draws_a_widget_as_kranto_does(tmp_path):
    from bears_cub.testing import FakeHost
    h = FakeHost.from_folder(_cub(tmp_path / "good", GOOD))
    h.library.add_topic(1, "Robotics")
    h.library.add_observation(10, 1, "A humanoid charges in nine minutes")
    assert h.widget("count") == {"value": "3", "words": "things counted"}     # its first size
    got = h.widget("latest", "L")
    assert got["rows"][0]["open"] == "cub/tally?sel=o10" and got["total"] == 1
    assert {"method": "widget", "params": {"id": "latest", "size": "L"}} in h.calls
    with pytest.raises(WidgetAnswerError, match="drawn at S, M, not L"):
        h.widget("count", "L")
    with pytest.raises(KeyError):
        h.widget("nope")


def test_fakehost_and_the_standard_fixture_refuse_what_kranto_would_change(tmp_path):
    from bears_cub import standard
    from bears_cub.testing import FakeHost
    folder = _cub(tmp_path / "bad", BAD)
    h = FakeHost.from_folder(folder)
    with pytest.raises(WidgetAnswerError, match="line cut to 120"):
        h.widget("count", "S")
    found = standard.problems(folder)
    assert any(p.startswith("widget count (stat, S): count at S: line cut") for p in found)
    # the planted instruction is in the library: its title would be the link
    assert any(p.startswith("widget latest (rows, M)") and "leaves tally's page" in p
               for p in found)
    assert standard.problems(_cub(tmp_path / "good", GOOD)) == []


def test_a_widget_whose_read_is_not_one_of_its_reads_is_refused_in_words(tmp_path):
    from bears_cub import check
    from bears_cub.schema import ManifestError as SDKManifestError
    from bears_cub.testing import FakeHost
    folder = _cub(tmp_path / "other", GOOD,
                  WIDGET_YAML.replace("read: rows, sizes", "read: other, sizes"))
    with pytest.raises(SDKManifestError, match="its read 'other' is not one of its reads"):
        FakeHost.from_folder(folder)
    assert any("its read 'other' is not one of its reads" in p for p in check.problems(folder))


def test_check_and_the_install_dialog_say_each_widget_in_words(tmp_path, capsys):
    import yaml

    from bears_cub import check
    from kranto.core.cubs import inspect
    from kranto.core.manifest import grants_of
    assert check.main([str(_cub(tmp_path / "good", GOOD))]) == 0
    out = capsys.readouterr().out
    assert ("widget: shows on the home, if its owner adds it: Count (stat, S or M, from its "
            "read stat, every 5 minutes)") in out
    m = registry.validate_cub(yaml.safe_load(WIDGET_YAML))
    lines = [b for a, b in inspect.words(m, grants_of(m), trust="owner") if a.startswith("Shows")]
    assert lines == ["Count (stat, S or M, from its read stat, every 5 minutes)",
                     "Latest (rows, M or L, from its read rows, every 5 minutes)"]
