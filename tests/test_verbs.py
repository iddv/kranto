"""The verbs' door (``core.verbs``, ``web/verbs_api.py``;).

Every caller runs a verb through ``POST /api/verbs/<kind>``; the token says the door, never the
body. The owner pressing (``ui``, ``cli``) is not on the ladder; every other caller is: Do it
runs the verb's own route and the answer carries the page and the row to mark, with a run in
Activity saying who; Ask me in the UI prepares the press, which waits until the owner presses it
on the page; Never refuses with the setting's name. The locks cannot be turned by a setting.
"""

import json

import pytest

from kranto import library, tokens
from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.core import verbs
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, web_client
from .test_brb_mount import FakeApi

BASE = "http://127.0.0.1:8765"


@pytest.fixture
def rt(tmp_path, store, embedder, make_client, monkeypatch):
    brbfake.install(monkeypatch, FakeApi())
    (tmp_path / "kranto.yaml").write_text(
        "llm:\n  models:\n    judge: m\n    reason: m\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(),
                 builds=BuildsConfig(enabled=True),
                 brb=BrbConfig(enabled=True, root=str(tmp_path / "tasks")))
    return open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))


@pytest.fixture
def app(rt):
    return create_app(rt, port=8765)


def bearer(name):
    tokens.Store().ensure_doors()
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def bare(app):
    return web_client(app, BASE, signed_in=False)


def runs_of(rt, kind="verb"):
    from kranto import activity
    activity.flush()
    return [dict(r) for r in rt.store.query(
        "SELECT * FROM run_marks WHERE kind = ? ORDER BY id", (kind,))]


def topic_names(rt):
    return {t.name for t in library.active_topics(rt.store)}


def test_the_table_is_read(app):
    with bare(app) as web:
        r = web.get("/api/verbs")
    assert r.status_code == 200
    got = {v["kind"]: v for v in r.json()["verbs"]}
    assert got["topic.add"]["choice"] == "do" and got["topic.add"]["ladder"] == "reversible"
    assert got["settings.telemetry"]["choice"] == "ask"
    assert got["setup.key"]["choice"] == "never" and got["setup.key"]["locked"]
    # Invest is off by default, and its broker's verbs with it (.2: test_hide_off.py)
    assert "broker.approve" not in got
    assert got["topic.add"]["route"] == {"method": "POST", "path": "/api/topics"}
    assert r.json()["defaults"]["outward"] == "ask"


def test_console_adds_a_topic_and_it_is_attributed(rt, app):
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("console"),
                     json={"fields": {"name": "Marine robotics",
                                      "description": "Underwater autonomy."},
                           "client": "claude"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] and out["by"] == "console:claude"
    tid = out["subject"]["id"]
    assert isinstance(tid, int) and out["page"] == f"#/watch/topic/{tid}/sources"
    assert out["mark"] == f"topic:{tid}" and out["run"]
    assert "Marine robotics" in topic_names(rt)
    marks = runs_of(rt)
    assert [m["mark"] for m in marks] == ["started", "ended"]
    assert marks[0]["by"] == "console:claude" and marks[0]["title"].startswith("Add topic")
    assert marks[-1]["state"] == "ok" and marks[0]["run_uuid"] == out["run"]
    assert verbs.by_words("console:claude") == "by Claude Code"
    assert verbs.by_words("mcp:codex") == "by Codex (outside)"


def test_an_outside_client_is_named_by_its_words_only(rt, app):
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "Tidal power", "description": "d."},
                           "client": "Codex"})
        assert r.json()["by"] == "mcp:codex"
        # words that are not a client's name are dropped: the token is who
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "Wave power", "description": "d."},
                           "client": "ui\n<script>"})
        assert r.json()["by"] == "mcp"
        # a body that claims another door changes nothing
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "Hydrogen", "description": "d."}, "origin": "ui"})
        assert r.status_code == 400 or r.json()["by"] == "mcp"


def test_outward_is_prepared_and_the_owner_presses_it(rt, app):
    with bare(app) as web:
        r = web.post("/api/verbs/settings.telemetry", headers=bearer("console"),
                     json={"fields": {"mode": "off"}, "client": "claude"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["prepared"] and not out["ok"] and out["choice"] == "ask"
    assert "nothing has happened" in out["say"] and out["page"] == "#/settings/privacy"
    pid = out["prepared"]
    with web_client(app, BASE) as page:
        listed = page.get("/api/prepared").json()["prepared"]
        assert [p["uuid"] for p in listed] == [pid]
        assert listed[0]["fields"] == {"mode": "off"} and listed[0]["state"] == "open"
        assert listed[0]["by_words"] == "by Claude Code"
        # the prepared run waits in Activity (Needs you reads waiting runs)
        assert "waiting" in [m["mark"] for m in runs_of(rt)]
        # an assistant cannot press its own prepared press
        with bare(app) as web:
            r = web.post(f"/api/prepared/{pid}/press", headers=bearer("console"), json={})
            assert r.status_code == 403
        r = page.post(f"/api/prepared/{pid}/press", json={})
        assert r.status_code == 200 and r.json()["state"] == "pressed", r.text
        r = page.post(f"/api/prepared/{pid}/press", json={})
        assert r.status_code == 409
        assert page.get("/api/prepared").json()["prepared"] == []


def test_a_prepared_press_is_dismissed_and_expires(rt, app):
    with bare(app) as web:
        pid = web.post("/api/verbs/settings.telemetry", headers=bearer("mcp"),
                       json={"fields": {"mode": "off"}}).json()["prepared"]
    with web_client(app, BASE) as page:
        assert page.post(f"/api/prepared/{pid}/dismiss", json={}).json()["state"] == \
            "dismissed"
        rt.store.insert("prepared", {"prepared_uuid": "old", "state": "open",
                                     "verb": "settings.telemetry", "fields": "{}",
                                     "expires_at": "2000-01-01T00:00:00Z",
                                     "created_at": "2000-01-01T00:00:00Z"})
        rows = page.get("/api/prepared?state=all").json()["prepared"]
    assert {r["uuid"]: r["state"] for r in rows} == {pid: "dismissed", "old": "expired"}
    assert all(r["available"] for r in rows)


def test_a_prepared_item_names_what_it_acts_on(rt, app):
    """Needs you says "Archive: Padel", not "topic #15". The name is read with the
    rows (never stored), so an item prepared before says it too; a kind with no name here, a
    row that is gone and an odd id read as None."""
    tid = library.add_topic(rt.store, rt.embedder, "Padel  courts", "Padel clubs.")
    for uuid, kind, sid in (("t", "topic", str(tid)), ("gone", "topic", "999999"),
                            ("cub", "cub", "blog"), ("odd", "topic", "x1")):
        rt.store.insert("prepared", {
            "prepared_uuid": uuid, "state": "open", "verb": "topic.archive",
            "subject_kind": kind, "subject_id": sid, "fields": "{}",
            "expires_at": None, "created_at": "2026-11-14T22:00:00Z"})
    with web_client(app, BASE) as page:
        rows = {r["uuid"]: r for r in page.get("/api/prepared").json()["prepared"]}
    assert rows["t"]["subject_name"] == "Padel courts"
    assert [rows[u]["subject_name"] for u in ("gone", "cub", "odd")] == [None, None, None]


def test_a_prepared_item_whose_verb_left_is_no_longer_available_and_dismissed(rt, app):
    """CUT (``prepared``): live holds six open ``b.factory_issue`` rows from before
    builds left. Each is listed as no longer available, with Dismiss only, never an error; it
    cannot be approved; Dismiss closes it. A row of any odd shape (a null verb, words or
    fields, a number for an expiry) reads too."""
    rt.store.insert("prepared", {
        "prepared_uuid": "fi-1", "state": "open", "verb": "b.factory_issue",
        "fields": json.dumps({"issue": "The console froze", "text": "t"}),
        "by": "console:claude", "page": "#/needs", "subject_kind": "new",
        "words": "File a Kranto issue: prepared by Claude Code; waits for your approval on "
                 "#/needs", "expires_at": None, "created_at": "2026-11-09T07:17:00Z"})
    rt.store.insert("prepared", {
        "prepared_uuid": "odd", "state": "open", "verb": "b.retry", "fields": "not json",
        "by": None, "words": None, "expires_at": None,
        "created_at": "2026-11-09T07:18:00Z"})
    with web_client(app, BASE) as page:
        rows = {r["uuid"]: r for r in page.get("/api/prepared").json()["prepared"]}
        fi, odd = rows["fi-1"], rows["odd"]
        assert fi["available"] is False and fi["state"] == "open"
        assert fi["title"] == "File a Kranto issue (no longer available)"
        assert fi["button"] == "Dismiss" and fi["locked"] is True
        assert "not part of Kranto any more" in fi["says"]
        assert fi["fields"] == {"issue": "The console froze", "text": "t"}
        assert odd["available"] is False and odd["title"] == "b.retry (no longer available)"
        assert odd["fields"] == {} and odd["by_words"] == verbs.by_words(None)
        r = page.post("/api/prepared/fi-1/press", json={})
        assert r.status_code == 410 and "no longer" in r.json()["error"]
        r = page.post("/api/prepared/fi-1/dismiss", json={})
        assert r.status_code == 200 and r.json()["state"] == "dismissed"
        left = [r["uuid"] for r in page.get("/api/prepared").json()["prepared"]]
        assert left == ["odd"]
        assert page.get("/api/prepared?state=all").status_code == 200


def test_the_same_press_asked_twice_waits_once(rt, app):
    """an assistant asked twice for the same thing made two rows for one press.
    The same verb, subject and fields while one is open: the same press, said "Already
    prepared"; other fields, or once it was dismissed: a new one."""
    with bare(app) as web:
        ask = lambda mode: web.post("/api/verbs/settings.telemetry",  # noqa: E731
                                    headers=bearer("console"), json={"fields": {"mode": mode}})
        first = ask("off").json()
        again = ask("off").json()
        assert again["prepared"] == first["prepared"] and again["again"] is True
        assert again["say"].startswith("Already prepared, and nothing has happened")
        other = ask("basic").json()
        assert other["prepared"] != first["prepared"]
    with web_client(app, BASE) as page:
        open_rows = page.get("/api/prepared").json()["prepared"]
        assert sorted(r["uuid"] for r in open_rows) == sorted([first["prepared"],
                                                               other["prepared"]])
        page.post(f"/api/prepared/{first['prepared']}/dismiss", json={})
    with bare(app) as web:
        fresh = web.post("/api/verbs/settings.telemetry", headers=bearer("console"),
                         json={"fields": {"mode": "off"}}).json()
    assert fresh["prepared"] not in (first["prepared"], other["prepared"])
    # one waiting run a press: Needs you reads waiting runs
    waits = [m for m in runs_of(rt) if m["mark"] == "waiting"]
    assert len(waits) == 3


def test_never_refuses_with_the_setting(rt, app):
    with web_client(app, BASE) as page:
        r = page.post("/api/settings/assistant",
                      json={"ladder": {"kinds": {"reversible": "never"}}})
        assert r.status_code == 200, r.text
        kinds = {k["kind"]: k for k in r.json()["kinds"]}
        assert kinds["reversible"]["choice"] == "never"
    assert "reversible: never" in (rt.cfg.root / "kranto.yaml").read_text() or \
        "never" in (rt.cfg.root / "kranto.yaml").read_text()
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("console"),
                     json={"fields": {"name": "Robots", "description": "d."}})
    assert r.status_code == 403 and "Settings › Assistant" in r.json()["error"]
    assert "Robots" not in topic_names(rt)
    # the owner pressing is not on the ladder
    with web_client(app, BASE) as page:
        r = page.post("/api/verbs/topic.add",
                      json={"fields": {"name": "Robots", "description": "d."}})
        assert r.status_code == 200 and r.json()["by"] == "ui", r.text
    assert "Robots" in topic_names(rt)


def test_no_your_broker_row_while_no_broker_verb_is_offered(rt, app):
    """a fresh home's Settings › Assistant had a "Your broker" row with Invest and
    the radar off. The kind is listed only while a verb of it is offered."""
    from kranto.core import verbs
    assert not any(v.ladder == "broker" for v in verbs.all_verbs())     # Invest is off here
    with web_client(app, BASE) as page:
        kinds = [k["kind"] for k in page.get("/api/settings/assistant").json()["kinds"]]
    assert "broker" not in kinds and "outward" in kinds and "read" in kinds


def test_per_verb_exceptions_win_over_the_kind(rt, app):
    with web_client(app, BASE) as page:
        page.post("/api/settings/assistant",
                  json={"ladder": {"kinds": {"reversible": "never"},
                                   "verbs": {"topic.add": "ask"}}})
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "Robots", "description": "d."}})
    assert r.json()["prepared"] and "your setting for Add topic" in r.json()["why"]


def test_the_locks(rt, app):
    with bare(app) as web:
        for kind in ("setup.key", "ticket.confirm", "token.add",
                     "assistant.ladder"):
            r = web.post(f"/api/verbs/{kind}", headers=bearer("console"),
                         json={"subject": {"id": "1"}})
            assert r.status_code == 403 and "only" in r.json()["error"], kind
        # a house verb is always prepared, whatever the ladder says
        r = web.post("/api/verbs/cub.live", headers=bearer("console"),
                     json={"subject": {"id": "newsletter"}})
        assert r.json().get("prepared") and r.json()["why"].startswith("this is confirmed on")
        # an assistant cannot change its own ladder
        r = web.post("/api/settings/assistant", headers=bearer("console"),
                     json={"ladder": {"kinds": {"outward": "do"}}})
        assert r.status_code == 403
    with web_client(app, BASE) as page:
        r = page.post("/api/settings/assistant",
                      json={"ladder": {"kinds": {"credential": "do"}}})
        assert r.status_code == 400 and "cannot be changed" in r.json()["error"]


def test_fields_are_checked(app):
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "X", "colour": "red"}})
        assert r.status_code == 400 and "no field colour" in r.json()["error"]
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": 3}})
        assert r.status_code == 400 and "topic.add.name is line" in r.json()["error"]
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"), json={"fields": {}})
        assert r.status_code == 400 and "needs name" in r.json()["error"]
        r = web.post("/api/verbs/topic.pause", headers=bearer("mcp"), json={})
        assert r.status_code == 400 and "send subject" in r.json()["error"]
        r = web.post("/api/verbs/nope.nope", headers=bearer("mcp"), json={})
        assert r.status_code == 404
        r = web.post("/api/verbs/topic.add", json={"fields": {"name": "X", "description": "d."}})
        assert r.status_code == 401


def test_a_subject_verb_and_a_form_verb(rt, app):
    tid, _ = library.add_topic_once(rt.store, rt.embedder, "Robotics", "Robots.")
    with bare(app) as web:
        r = web.post("/api/verbs/topic.pause", headers=bearer("console"),
                     json={"subject": {"id": tid}, "client": "codex"})
        assert r.status_code == 200 and r.json()["ok"], r.text
        assert r.json()["page"] == f"#/watch/topic/{tid}" and r.json()["undo"] == "topic.resume"
        r = web.post("/api/verbs/kranto.pause", headers=bearer("console"),
                     json={"fields": {"reason": "asked by Codex"}})
        assert r.status_code == 200 and r.json()["ok"], r.text
    assert rt.store.pause_reason() == "asked by Codex"
    marks = [m for m in runs_of(rt) if m["mark"] == "started"]
    assert [m["by"] for m in marks] == ["console:codex", "console"]
    assert marks[0]["subject_kind"] == "topic" and marks[0]["subject_id"] == str(tid)


def test_an_owner_only_route_stays_the_owners(app):
    """The guard lets an assistant's token write the verbs' door and nothing else of Kranto's."""
    with bare(app) as web:
        for path in ("/api/topics", "/pause", "/api/settings/assistant"):
            r = web.post(path, headers=bearer("console"), json={})
            assert r.status_code == 403 and "only runs actions" in r.json()["error"], path


def test_feature_actions_are_verbs():
    fv = verbs.feature_verbs()
    assert fv and all(v.kind.startswith("f.") and v.path == "/api/f/{feature}/act/{action}"
                      for v in fv)
    for v in fv:
        if v.click == "house":
            assert v.doors == verbs.PAGE_ONLY and v.lock == "ask"
        assert dict(v.fixed)["feature"] and dict(v.fixed)["action"]


def test_a_feature_action_runs_through_the_console(rt, app):
    v = next(v for v in verbs.feature_verbs() if v.click == "click")
    with bare(app) as web:
        r = web.post(f"/api/verbs/{v.kind}", headers=bearer("console"),
                     json={"subject": {"id": "x"}})
    # past the doors: the feature itself answers (it may be off here, or need its input)
    assert r.status_code != 403 or "is not run from" not in r.text, r.text


def test_the_ladder_setting_round_trips(tmp_path):
    from kranto import config as config_mod
    ask = config_mod.parse_ask({"ladder": {"kinds": {"spend": "ask"}}})
    assert ask.ladder == {"kinds": {"spend": "ask"}, "verbs": {}}
    with pytest.raises(config_mod.ConfigError):
        config_mod.parse_ask({"ladder": {"kinds": {"credential": "do"}}})
    with pytest.raises(config_mod.ConfigError):
        config_mod.parse_ask({"other": 1})
    assert config_mod.parse_ask(None).ladder == {"kinds": {}, "verbs": {}}
    assert json.dumps(verbs.ladder_setting(None)) == '{"kinds": {}, "verbs": {}}'


def test_what_an_assistant_did_is_kept_for_the_page(rt, app):
    """Reflection: each verb an assistant ran or prepared is a line of
    ``<data>/verbs.json``; the page's live feed sees it and reads ``/api/verbs/recent``."""
    with bare(app) as web:
        assert web.get("/api/verbs/recent").json() == {"seq": 0, "recent": []}
        r = web.post("/api/verbs/topic.add", headers=bearer("console"),
                     json={"fields": {"name": "Kelp", "description": "Kelp farming."},
                           "client": "claude"})
        tid = r.json()["subject"]["id"]
        web.post("/api/verbs/settings.telemetry", headers=bearer("mcp"),
                 json={"fields": {"mode": "off"}, "client": "codex"})
        got = web.get("/api/verbs/recent").json()
        assert got["seq"] == 2
        last, first = got["recent"]
        assert first["mark"] == f"topic:{tid}" and first["by_words"] == "by Claude Code"
        assert first["page"] == f"#/watch/topic/{tid}/sources" and first["run"]
        assert last["prepared"] and last["by_words"] == "by Codex (outside)"
        assert [x["seq"] for x in web.get("/api/verbs/recent?since=1").json()["recent"]] == [2]
        # the owner's own press is no line: the page that pressed already shows it
        with web_client(app, BASE) as page:
            page.post("/api/verbs/topic.add",
                      json={"fields": {"name": "Seagrass", "description": "d."}})
        assert web.get("/api/verbs/recent").json()["seq"] == 2
    assert (rt.cfg.data_dir / "verbs.json").is_file()


def test_a_prepared_item_says_its_button_and_its_end_reaches_every_page(rt, app):
    """a prepared item's one button is the action's own words, never a house word;
    a locked kind says so (the toast offers Open only); its approval or dismissal is a line of
    ``verbs.json`` too, so every open page takes it away at once, and its waiting run goes."""
    from kranto.activity import read as activity_read
    from kranto.web.verbs_api import button_words
    assert button_words("File a Kranto issue") == "File issue"
    assert button_words("Add a topic") == "Add topic"
    assert button_words("Turn usage reports off") == "Turn usage reports off"
    assert button_words("") == "Approve"
    with bare(app) as web:
        pid = web.post("/api/verbs/settings.telemetry", headers=bearer("console"),
                       json={"fields": {"mode": "off"}, "client": "claude"}).json()["prepared"]
        made = web.get("/api/verbs/recent").json()["recent"][0]
    assert made["prepared"] == pid and made["resolved"] is None and made["button"]
    with web_client(app, BASE) as page:
        [row] = page.get("/api/prepared").json()["prepared"]
        assert row["button"] == button_words(row["title"]) and row["says"]
        # consent is locked: approved in its own dialog, never from a toast
        assert row["ladder"] == "outward" and row["locked"] is True
        assert [w["kind"] for w in activity_read.Reader(rt.store).waiting()] == ["verb"]
        assert page.post(f"/api/prepared/{pid}/press", json={}).status_code == 200
    with bare(app) as web:
        got = web.get("/api/verbs/recent").json()
    assert got["recent"][0]["prepared"] == pid and got["recent"][0]["resolved"] == "approved"
    assert got["recent"][0]["mark"] == ""
    assert activity_read.Reader(rt.store).waiting() == []
