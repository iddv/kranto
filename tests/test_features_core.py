"""The feature core (MR-RESEARCH): the manifest and its one validator, the
pins, the bus with trust and cursors, request tickets and their doors, the scoped context, a
feature's settings, the HTTP door and the import contract."""

from __future__ import annotations

import ast
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from kranto import features as features_pkg
from kranto.config import ConfigError
from kranto.core import api, events, registry, settings, tickets
from kranto.core.context import FeatureContext, OwnTables, PermissionDenied
from kranto.core.manifest import (
    Action,
    Events,
    Feature,
    Job,
    ManifestError,
    Model,
    Permissions,
    Setting,
    Settings,
    Subscribe,
    manifest_hash,
    validate,
)
from kranto.store import iso, utcnow

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

SRC = Path(__file__).resolve().parents[1] / "src" / "kranto"


def _job(ctx):
    ctx.db.insert("demo_rows", {"n": 1})
    return {"status": "ok", "wrote": 1}


def _act(ctx, fields):
    return {"echo": fields.get("x"), "door": ctx.door}


seen_ids: list[int] = []


def _handler(ctx, ev):
    seen_ids.append(ev["id"])


def demo(**over) -> Feature:
    base = dict(
        id="demo", title="Demo", says="A feature for the core's tests.", version="1.0.0",
        jobs=(Job("demo.tick", _job, every_hours=1),),
        owns=("demo_rows",),
        actions=(Action("demo.echo", "Echo", _act, doors=("ui", "cli")),
                 Action("demo.danger", "Danger", _act, doors=("ui",), click="house")),
        settings=Settings(keys={"demo.enabled": Setting("bool", True),
                                "demo.hour": Setting("int", 7, lo=0, hi=23),
                                "demo.secret_switch": Setting("bool", False, by_hand=True),
                                "demo.live.cap": Setting("usd", None, by_hand=True)},
                          sensitive=("demo.hour",)),
        permissions=Permissions(reads=("topics", "library"),
                                model=Model(tiers=("judge",), purposes=("demo_write",)),
                                search=("web",), requests=("test.ping",)),
        events=Events(publishes=("demo.happened",),
                      subscribes=(Subscribe("other.said", "first-party", _handler),)),
    )
    base.update(over)
    return Feature(**base)


@pytest.fixture
def ping(monkeypatch):
    """A high-trust kind for the tests, with a performer that records what it was given."""
    done = []

    def perform(store, ticket, context):
        done.append(ticket["fields"])
        return {"state": "done", "note": "pinged"}

    kind = tickets.Kind("test.ping", "Ping the test service",
                         {"target": tickets.Field("enum", ("a", "b")),
                          "n": tickets.Field("int", lo=1, hi=5),
                          "ref": tickets.Field("str", pattern=r"[a-z0-9:]{1,20}")},
                         perform=perform,
                         readback=lambda f: [("Target", f["target"]), ("Times", str(f["n"]))])
    monkeypatch.setitem(tickets.KINDS, "test.ping", kind)
    return done


@pytest.fixture
def with_demo(monkeypatch, ping, store):
    store._conn.execute("CREATE TABLE IF NOT EXISTS demo_rows (id INTEGER PRIMARY KEY, n INT)")
    f = demo()
    monkeypatch.setattr(features_pkg, "FEATURES", (f,))
    seen_ids.clear()
    return f


# -- the manifest ---------------------------------------------------------------------------------


def _v(m):
    return validate(m, read_families=api.READ_FAMILIES, request_kinds=("test.ping",),
                    core_kinds=events.CORE_KINDS, search_kinds=("web", "discussion"))


def test_a_feature_round_trips_to_the_data_schema_and_validates(ping):
    m = demo().to_manifest()
    assert _v(m) is m
    assert json.loads(json.dumps(m)) == m              # data, not code
    assert m["jobs"][0]["method"] == "_job" and m["schema"] == 1 and m["api"] == "cub/1"
    assert manifest_hash(m) == manifest_hash(json.loads(json.dumps(m)))


@pytest.mark.parametrize("change,words", [
    (lambda m: m.update(shell=True), "unknown keys in the manifest: shell"),
    (lambda m: m.update(reads=["secrets"]), r"reads\[0\] is one of topics"),
    (lambda m: m.update(requests=["money.withdraw"]), "no such high-trust action"),
    (lambda m: m["model"].update(purposes=["judge"]), "must be demo or start with demo_"),
    (lambda m: m["events"].update(publish=["grade.given"]), "is the core's"),
    (lambda m: m["actions"].append({"kind": "demo.x", "title": "x", "doors": ["mcp"],
                                    "click": "house"}), "its only door is ui"),
    (lambda m: m.update(owns=["observations"]), "must start with demo_"),
    (lambda m: m.update(trust="core"), "trust must be one of"),
    (lambda m: m["http"].update(hosts=["127.0.0.1"]), "not of the expected shape"),
    (lambda m: m["settings"]["keys"]["demo.hour"].update(type="code"), "type is one of"),
])
def test_the_validator_refuses_what_the_core_cannot_grant(change, words, ping):
    m = demo().to_manifest()
    change(m)
    with pytest.raises(ManifestError, match=words):
        _v(m)


def test_the_registry_refuses_a_kind_two_features_publish(monkeypatch, ping):
    twin = demo(id="demo2", jobs=(), owns=(), actions=(), settings=Settings(),
                permissions=Permissions(), events=Events(publishes=("demo.happened",)))
    monkeypatch.setattr(features_pkg, "FEATURES", (demo(), twin))
    with pytest.raises(ManifestError, match="published by demo and demo2"):
        registry.check()


def test_pins_follow_a_first_party_version_and_refuse_a_changed_third_party_one(
        monkeypatch, store, ping):
    monkeypatch.setattr(features_pkg, "FEATURES", (demo(),))
    assert registry.pin(store) == {"demo": "pinned"}
    assert registry.pin(store) == {"demo": "same"}
    monkeypatch.setattr(features_pkg, "FEATURES", (demo(says="Changed, first-party."),))
    assert registry.pin(store) == {"demo": "pinned"}          # a first-party upgrade
    third = demo(trust="listed", version="1.1.0")
    monkeypatch.setattr(features_pkg, "FEATURES", (third,))
    assert registry.pin(store) == {"demo": "pinned"}
    changed = demo(trust="listed", version="1.1.0", says="Asks for more now.")
    monkeypatch.setattr(features_pkg, "FEATURES", (changed,))
    assert registry.pin(store)["demo"].startswith("refused")
    assert registry.refused(store, changed) == "its manifest is not the one approved"


# -- the bus --------------------------------------------------------------------------------------


def test_a_feature_publishes_only_what_it_declares_and_payloads_stay_small(store):
    eid = events.publish(store, feature="demo", trust="first-party", kind="demo.happened",
                         payload={"idea_id": 3, "topic_ids": [1]}, declared=("demo.happened",))
    assert events.get(store, eid)["payload"] == {"idea_id": 3, "topic_ids": [1]}
    with pytest.raises(events.EventError, match="does not declare"):
        events.publish(store, feature="demo", trust="first-party", kind="demo.other",
                       declared=("demo.happened",))
    with pytest.raises(events.EventError, match="not one of the core's"):
        events.publish(store, feature="core", trust="core", kind="demo.happened")
    with pytest.raises(events.EventError, match="read API"):
        events.publish(store, feature="demo", trust="first-party", kind="demo.happened",
                       payload={"text": "x" * 500}, declared=("demo.happened",))
    with pytest.raises(sqlite_error()):
        store._conn.execute("UPDATE events SET kind = 'x'")


def sqlite_error():
    import sqlite3
    return sqlite3.DatabaseError


def test_a_subscription_has_a_trust_floor_and_a_cursor_at_least_once(with_demo, rt):  # noqa: F811
    store = rt.store
    low = events.publish(store, feature="stranger", trust="unreviewed", kind="other.said",
                         declared=("other.said",))
    high = events.publish(store, feature="other", trust="first-party", kind="other.said",
                          declared=("other.said",))
    assert [e["id"] for e in events.read(store, kinds=["other.said"],
                                         min_trust="first-party")] == [high]
    assert low < high
    registry.deliver(rt)
    assert seen_ids == [high]
    registry.deliver(rt)                      # the cursor moved: nothing twice
    assert seen_ids == [high]


def test_a_handler_that_raises_keeps_its_cursor(monkeypatch, store, rt):  # noqa: F811
    calls = []

    def flaky(ctx, ev):
        calls.append(ev["id"])
        if len(calls) == 1:
            raise RuntimeError("down")

    f = demo(events=Events(subscribes=(Subscribe("other.said", "first-party", flaky),)))
    monkeypatch.setattr(features_pkg, "FEATURES", (f,))
    eid = events.publish(rt.store, feature="other", trust="first-party", kind="other.said",
                         declared=("other.said",))
    registry.deliver(rt)
    registry.deliver(rt)
    assert calls == [eid, eid] and events.cursor(rt.store, "demo", "other.said") == eid


# -- request tickets ------------------------------------------------------------------------------

UI = {"origin": "ui", "via": "cookie"}


def _file(store, **over):
    args = dict(cub="demo", trust="first-party", granted=("test.ping",), kind="test.ping",
                fields={"target": "a", "n": 2, "ref": "demo:1"},
                because={"events": [1], "observations": [8231]}, subject=("demo_row", 1))
    args.update(over)
    return tickets.file(store, **args)


def test_a_ticket_needs_the_grant_and_typed_fields(store, ping):
    with pytest.raises(tickets.TicketError, match="may not request"):
        _file(store, granted=())
    with pytest.raises(tickets.TicketError, match="must be one of a, b"):
        _file(store, fields={"target": "c", "n": 2, "ref": "x"})
    with pytest.raises(tickets.TicketError, match="unknown: note"):
        _file(store, fields={"target": "a", "n": 2, "ref": "x", "note": "buy XYZ now"})
    with pytest.raises(tickets.TicketError, match="between 1"):
        _file(store, fields={"target": "a", "n": 50, "ref": "x"})
    with pytest.raises(tickets.TicketError, match="because names"):
        _file(store, because={"prose": "trust me"})
    rid = _file(store)
    t = tickets.get(store, rid)
    assert t["state"] == "needs_confirm" and t["readback"] == [["Target", "a"], ["Times", "2"]]
    assert t["because"]["observations"] == [8231]
    with pytest.raises(tickets.TicketError, match="waits for you already"):
        _file(store)
    assert events.read(store, kinds=["ticket.filed"])[0]["payload"]["ticket_id"] == rid


@pytest.mark.parametrize("identity", [None, {"origin": "cli", "via": "bearer"},
                                      {"origin": "mcp", "via": "bearer"},
                                      {"origin": "agent:x", "via": "bearer"},
                                      {"origin": "ui", "via": "bearer"}])
def test_only_the_pages_session_confirms(store, ping, identity):
    rid = _file(store)
    with pytest.raises(tickets.TicketError, match="on the page only") as e:
        tickets.confirm(store, rid, identity=identity, confirm=True)
    assert e.value.code == 403 and ping == []
    assert tickets.get(store, rid)["state"] == "needs_confirm"


def test_a_ticket_is_confirmed_once_and_its_outcome_recorded(store, ping):
    rid = _file(store)
    with pytest.raises(tickets.TicketError, match="confirm: true"):
        tickets.confirm(store, rid, identity=UI, confirm="yes")
    out = tickets.confirm(store, rid, identity=UI, confirm=True)
    assert out["state"] == "done" and len(ping) == 1
    with pytest.raises(tickets.TicketError, match="happens once"):
        tickets.confirm(store, rid, identity=UI, confirm=True)
    assert len(ping) == 1
    assert [h["state"] for h in tickets.get(store, rid)["history"]] == \
        ["needs_confirm", "confirmed", "done"]


def test_an_expired_ticket_cannot_be_confirmed(store, ping):
    rid = _file(store, now=utcnow() - timedelta(days=3))
    assert tickets.get(store, rid)["state"] == "expired"
    with pytest.raises(tickets.TicketError, match="happens once|waited past its time"):
        tickets.confirm(store, rid, identity=UI, confirm=True)
    assert ping == []


def test_a_performer_that_raises_leaves_the_ticket_unknown_never_retried(store, monkeypatch,
                                                                         ping):
    def boom(store, ticket, context):
        raise TimeoutError("no answer")
    monkeypatch.setattr(tickets.KINDS["test.ping"], "perform", boom)
    rid = _file(store)
    assert tickets.confirm(store, rid, identity=UI, confirm=True)["state"] == "unknown"
    with pytest.raises(tickets.TicketError):
        tickets.confirm(store, rid, identity=UI, confirm=True)


def test_the_daily_cap_per_feature(store, ping, monkeypatch):
    monkeypatch.setattr(tickets.KINDS["test.ping"], "per_day", 2)
    _file(store, fields={"target": "a", "n": 1, "ref": "r1"})
    _file(store, fields={"target": "a", "n": 1, "ref": "r2"})
    with pytest.raises(tickets.TicketError, match="at most 2"):
        _file(store, fields={"target": "a", "n": 1, "ref": "r3"})


# -- the scoped context ---------------------------------------------------------------------------


def test_own_tables_only_and_select_or_insert_only(store):
    db = OwnTables(store, "demo_")
    store._conn.execute("CREATE TABLE IF NOT EXISTS demo_rows (id INTEGER PRIMARY KEY, n INT)")
    db.insert("demo_rows", {"n": 4})
    assert db.query_one("SELECT n FROM demo_rows")["n"] == 4
    for sql in ("SELECT * FROM observations", "SELECT * FROM demo_rows JOIN topics t",
                "DELETE FROM demo_rows", "SELECT 1; DROP TABLE demo_rows",
                "INSERT INTO llm_calls (x) VALUES (1)"):
        with pytest.raises(PermissionDenied):
            db.query(sql)
    with pytest.raises(PermissionDenied):
        db.insert("observations", {"x": 1})


def test_the_model_client_takes_declared_purposes_and_no_tools(with_demo, rt):  # noqa: F811
    ctx = FeatureContext(with_demo, rt)
    call = dict(messages=[{"role": "user", "content": "hi"}], prompt_version="p-1")
    with pytest.raises(PermissionDenied, match="purpose"):
        ctx.llm.complete(purpose="judge", tier="judge", **call)
    with pytest.raises(PermissionDenied, match="reason tier"):
        ctx.llm.complete(purpose="demo_write", tier="reason", **call)
    for bad in ({"tools": ({"name": "place_order"},)}, {"provider": "xai"}, {"model": "x"}):
        with pytest.raises(PermissionDenied, match="no tools"):
            ctx.llm.complete(purpose="demo_write", tier="judge", **call, **bad)
    got = ctx.llm.complete(purpose="demo_write", tier="judge", **call)
    assert got.text == '{"sources": []}'


def test_a_feature_cap_stops_its_calls(monkeypatch, with_demo, rt):  # noqa: F811
    f = demo(permissions=Permissions(model=Model(tiers=("judge",), purposes=("demo_write",),
                                                 monthly_usd=0.0005)))
    monkeypatch.setattr(features_pkg, "FEATURES", (f,))
    rt.store.insert("llm_calls", dict(purpose="demo_write", tier="judge", model="m",
                                      prompt_version="p", request="{}", response="{}",
                                      status="ok", attempts=1, cost_usd=0.001,
                                      created_at=iso(utcnow())))
    from kranto.core.context import CapReached
    with pytest.raises(CapReached):
        FeatureContext(f, rt).llm.complete(purpose="demo_write", tier="judge", messages=[],
                                           prompt_version="p")
    assert events.read(rt.store, kinds=["spend.capped"])


def test_search_is_scoped_and_cannot_fetch(with_demo, rt):  # noqa: F811
    ctx = FeatureContext(with_demo, rt)
    assert not hasattr(ctx.search, "fetch")
    with pytest.raises(PermissionDenied):
        ctx.search.search("robots", kind="code")


def test_reads_follow_the_grant(with_demo, rt):  # noqa: F811
    ctx = FeatureContext(with_demo, rt)
    topics = ctx.read("topics.list")["topics"]
    assert topics and topics[0]["name"] == "energy"
    obs = ctx.read("library.observations", topic_id=topics[0]["id"], limit=2)
    assert obs["observations"][0]["label"].startswith("obs ")
    with pytest.raises(api.ReadError, match="may not read ideas"):
        ctx.read("ideas.list")
    with pytest.raises(tickets.TicketError, match="may not request"):
        ctx.request("test.other", {})
    assert not hasattr(ctx, "broker")          # Invest's broker left Kranto (cut 2)


# -- settings -------------------------------------------------------------------------------------


def test_a_features_section_is_checked_and_defaulted(with_demo):
    assert settings.parse_section(with_demo, None)["demo.hour"] == 7
    assert settings.parse_section(with_demo, {"live": {"cap": 5}})["demo.live.cap"] == 5.0
    with pytest.raises(ConfigError, match="unknown keys in demo: demo.color"):
        settings.parse_section(with_demo, {"color": "red"})
    with pytest.raises(ConfigError, match="from 0 to 23"):
        settings.parse_section(with_demo, {"hour": 30})


def test_writes_go_to_the_file_and_by_hand_keys_never(with_demo, tmp_path):
    from kranto import config as config_mod
    (tmp_path / "kranto.yaml").write_text(config_mod.DEFAULT_CONFIG_YAML)
    cfg = config_mod.load(tmp_path, dotenv=False)
    assert settings.write(cfg, "demo", "demo.hour", 9)["demo.hour"] == 9
    assert config_mod.load(tmp_path, dotenv=False).features["demo"]["demo.hour"] == 9
    with pytest.raises(settings.SettingError, match="by hand"):
        settings.write(cfg, "demo", "demo.secret_switch", True)


# -- the HTTP door --------------------------------------------------------------------------------


def test_the_page_lists_features_and_confirms_only_from_its_session(with_demo, rt):  # noqa: F811
    from kranto.web.app import create_app
    app = create_app(rt)
    with web_client(app, "http://127.0.0.1:8765") as web:
        listing = web.get("/api/features").json()
        assert [f["id"] for f in listing["features"]] == ["demo"]
        assert "test.ping" in listing["request_kinds"] and listing["api"] == "cub/1"
        rid = _file(rt.store)
        assert web.get(f"/api/requests/{rid}").json()["state"] == "needs_confirm"
        cli = app.state.app.auth.store.value("cli")
        r = web.post(f"/api/requests/{rid}/confirm", json={"confirm": True},
                     headers={"authorization": f"Bearer {cli}"})
        assert r.status_code == 403
        assert web.post(f"/api/requests/{rid}/confirm", json={}).status_code == 400
        r = web.post(f"/api/requests/{rid}/confirm", json={"confirm": True})
        assert r.status_code == 200 and r.json()["state"] == "done"
        assert web.post(f"/api/requests/{rid}/confirm", json={"confirm": True}).status_code \
            == 409
        r = web.post("/api/f/demo/act/echo", json={"fields": {"x": 3}})
        assert r.json() == {"echo": 3, "door": "ui"}
        assert web.post("/api/f/demo/act/danger", json={}).status_code == 400
        r = web.post("/api/f/demo/act/danger", json={"confirm": True},
                     headers={"authorization": f"Bearer {cli}"})
        assert r.status_code == 403
        assert web.post("/api/f/demo/settings", json={"key": "demo.hour", "value": 8}) \
            .status_code == 400                        # sensitive: needs the confirm
        assert web.get("/api/read/topics.list").json()["topics"]
        assert web.get("/api/read/nope").status_code == 404
        assert web.get("/api/events?kind=ticket.resolved").json()["events"]


def test_a_feature_job_records_its_run_and_is_off_while_the_feature_is(with_demo, rt,  # noqa: F811
                                                                       monkeypatch):
    rt.store._conn.execute("CREATE TABLE IF NOT EXISTS demo_rows (id INTEGER PRIMARY KEY, "
                           "n INT)")
    [job] = registry.jobs(lambda: rt)
    assert job.kind == "demo.tick" and job.every_hours == 1
    job.run()
    row = rt.store.query_one("SELECT status, summary FROM runs WHERE kind = 'demo.tick'")
    assert row["status"] == "ok" and json.loads(row["summary"]) == {"wrote": 1}
    assert events.read(rt.store, kinds=["job.finished"])[0]["payload"]["kind"] == "demo.tick"
    from dataclasses import replace
    rt.cfg = replace(rt.cfg, features={"demo": {**settings.section(rt.cfg, "demo"),
                                                "demo.enabled": False}})
    assert job.every_hours == 0


def test_grades_publish_grade_given(store):
    from kranto import feedback
    # a card's grade (grades are kept on ideas and evidence only,)
    oid = store.insert("ideas", {
        "snapshot_id": None, "fingerprint": "f", "lineage_id": None, "origin": "cross_source",
        "evidence_key": "k", "input_ids": "[]", "title": "t", "card": "{}", "score": 0.1,
        "status": "shown", "dropped": "[]", "created_at": iso(utcnow())})
    feedback.add(store, {"target": "idea", "target_id": oid, "value": "useful"})
    [ev] = events.read(store, kinds=["grade.given"])
    assert ev["payload"] == {"target": "idea", "target_id": str(oid), "value": "useful"}
    assert ev["trust"] == "core"


def test_the_scheduler_runs_its_tick_hooks():
    from kranto.scheduler import Scheduler
    seen = []
    s = Scheduler(store=None, jobs=[], ticks=[lambda: seen.append(1),
                                              lambda: (_ for _ in ()).throw(RuntimeError())])
    s.run_ticks()
    assert seen == [1]


# -- the import contract ----------------------------------------------------------------


ALLOWED = ("kranto.core", "kranto.stored")


def imports_problems(path: Path, package: str) -> list[str]:
    """What a feature module does that the contract forbids: import kranto outside
    ``kranto.core``, ``kranto.stored`` and its own package, or reach past its context to
    the store."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:                       # relative: within its own package only
                if node.level > 1 and path.name != "__init__.py" or node.level > 2:
                    bad.append(f"{path.name}: from {'.' * node.level}{mod}")
                continue
            # the core, and the stored-data contracts (a feature's own types
            # derive from kranto.stored)
            if mod.startswith("kranto") and not (mod.startswith(ALLOWED)
                                                   or mod.startswith(package)):
                bad.append(f"{path.name}: from {mod}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("kranto") and not (a.name.startswith(ALLOWED)
                                                          or a.name.startswith(package)):
                    bad.append(f"{path.name}: import {a.name}")
        elif isinstance(node, ast.Attribute) and node.attr in ("store", "rt", "_store") and \
                isinstance(node.value, ast.Name) and node.value.id == "ctx":
            bad.append(f"{path.name}: ctx.{node.attr}")
    return bad


def test_features_import_only_the_core_and_themselves():
    root = SRC / "features"
    problems = []
    # a package with no FEATURE is no feature (features/post holds the prose eval,)
    for pkg in [p for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
                and re.search(r"^FEATURE\b", (p / "__init__.py").read_text(), re.M)]:
        for py in pkg.rglob("*.py"):
            problems += imports_problems(py, f"kranto.features.{pkg.name}")
    assert problems == []


def test_the_contract_catches_a_reach_past_the_core(tmp_path):
    bad = tmp_path / "x.py"
    bad.write_text("from kranto.store import Store\nfrom kranto import llm\n"
                   "import kranto.web.app\ndef f(ctx):\n    return ctx.store.query('x')\n")
    assert len(imports_problems(bad, "kranto.features.x")) == 4
    ok = tmp_path / "y.py"
    ok.write_text("from kranto.core import Feature\nfrom . import brief\n"
                  "def f(ctx):\n    return ctx.db.query('SELECT 1 FROM x_rows')\n")
    assert imports_problems(ok, "kranto.features.x") == []


def test_features_ship_with_a_brain_free_model_tool_list():
    """No feature action is a model's: none has the mcp or agent door for a high-trust kind,
    and no manifest names a tool."""
    for f in features_pkg.FEATURES:
        for a in f.actions:
            if any(w in a.kind for w in ("place", "order", "confirm")):
                assert set(a.doors) <= {"ui"}, a.kind


def test_a_key_says_where_it_sits_on_its_settings_page():
    """a key's group and Advanced reach the page (settings.describe) and
    round-trip through the data form; placed() puts the keys of a feature in their groups."""
    from kranto.core.manifest import placed
    keys = placed({"demo.enabled": Setting("bool", True), "demo.hour": Setting("int", 7),
                   "demo.max": Setting("int", 3)}, groups={"When": ("demo.hour",)},
                  advanced=("demo.max",))
    assert (keys["demo.hour"].group, keys["demo.hour"].advanced) == ("When", False)
    assert (keys["demo.max"].group, keys["demo.max"].advanced) == ("", True)
    assert keys["demo.enabled"] == Setting("bool", True)
    with pytest.raises(KeyError):
        placed({"demo.a": Setting("bool")}, advanced=("demo.b",))
    f = Feature("demo", "Demo", "a demo", "1.0.0", settings=Settings(keys=keys))
    rows = {r["key"]: r for r in settings.describe(f, {})}
    assert (rows["demo.hour"]["group"], rows["demo.max"]["advanced"]) == ("When", True)
    data = f.to_manifest()["settings"]["keys"]
    assert data["demo.hour"]["group"] == "When" and data["demo.max"]["advanced"] is True
    # the first-party features say theirs
    by = {x.id: x for x in features_pkg.FEATURES}
    assert by["news"].settings.keys["news.hour"].group == "News"
    assert by["news"].settings.keys["news.max_items"].advanced
    assert all(s.advanced for s in by["news"].settings.keys.values() if s.by_hand)


def test_check_says_where_its_keys_sit():
    from bears_cub.check import settings_words
    m = {"id": "demo", "title": "Demo", "settings": {"keys": {
        "demo.a": {"type": "bool", "group": "The issue"},
        "demo.b": {"type": "int", "group": "The issue"},
        "demo.c": {"type": "str"}, "demo.d": {"type": "str", "advanced": True}}}}
    assert settings_words(m) == ("on Settings › Demo: The issue (2 keys), Demo's settings "
                                 "(1 key); 1 under Advanced")
    assert settings_words({"id": "x", "settings": {"keys": {}}}) is None


def test_a_cubs_page_keys_round_trip_and_check_says_them():
    """ui.primary, a list's empty words and its groups' tones round-trip through
    the data form; the reference cubs say them; bears_cub.check words them."""
    from pathlib import Path

    import yaml

    from bears_cub.check import page_words
    from kranto.core.manifest import UI, Group, UIList
    f = Feature("demo", "Demo", "a demo", "1.0.0",
                ui=UI(lists=(UIList("posts", "Posts", "posts", "post",
                                    (Group("waiting", "Waits", "wait"), Group("done", "Done")),
                                    empty="No post yet."),), primary="demo.go"))
    ui = f.to_manifest()["ui"]
    assert ui["primary"] == "demo.go" and ui["lists"][0]["empty"] == "No post yet."
    assert [g["tone"] for g in ui["lists"][0]["groups"]] == ["wait", "quiet"]
    ex = Path(features_pkg.__file__).parents[1] / "cubs" / "examples"
    news = yaml.safe_load((ex / "newsletter" / "cub.yaml").read_text())
    assert news["ui"]["primary"] == "compose" and news["ui"]["cards"]["issue"]["open"] == "page"
    assert news["ui"]["cards"]["issue"]["body"] == "body_markdown"
    assert page_words(news) == [
        "its one primary in the head: Compose",
        "its Issues list says, when empty: No issue yet. Monday 08:00 composes one from the "
        "week's briefs; Compose makes one now.",
        "an issue opens as a page, its body_markdown drawn as text"]
    toot = yaml.safe_load((ex / "toot" / "cub.yaml").read_text())
    assert toot["ui"]["primary"] == "draft" and "open" not in toot["ui"]["cards"]["post"]
