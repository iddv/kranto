"""Usage reports (section 8): the allow-list fails closed, every mode does what it
says, nothing is posted unanswered or in local or off (and basic posts to the default endpoint,
a fake on loopback here), the canaries never reach a line, a report or a
payload, crash fingerprints carry no message, the field page is the list's, and the route enum
is the app's routes."""

from __future__ import annotations

import gzip
import json
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from kranto import config as config_mod
from kranto import library, telemetry
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.store import Store
from kranto.telemetry import cli as tcli
from kranto.telemetry import docs, local, report, send, timing
from kranto.telemetry import schema as S
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (local.DNT, local.ENV_MODE, local.ENV_ENDPOINT):
        monkeypatch.delenv(k, raising=False)
    yield
    telemetry.configure(None)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    config_mod.init_workspace(h)
    telemetry.configure(h)
    return h


def lines_of(home: Path) -> list[dict]:
    out = []
    for f in sorted((home / "telemetry" / "local").glob("*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


class Spy:
    """An httpx transport that records each request and answers 204."""

    def __init__(self, status=204):
        self.requests, self.status = [], status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


# -- the allow-list --------------------------------------------------------------------------

def test_a_field_not_in_the_list_is_dropped_and_counted(home):
    telemetry.record("error", fingerprint="KeyError:kranto.x.f:1", where="api", bogus=1)
    telemetry.record("not_a_line", kind="x")
    telemetry.record("view", node=12)                      # a required field of a wrong type
    telemetry.record("error", fingerprint="no message here", where="api")
    got = lines_of(home)
    assert got[0]["e"] == "error" and "bogus" not in got[0] and got[0]["_dropped"] == 1
    assert [g["e"] for g in got[1:]] == ["dropped", "dropped", "dropped"]
    assert report.fold_lines(got)["dropped_fields"] == 4


def test_strings_exist_only_as_enums_and_patterns():
    schema = S.union()
    for name, spec in {**schema["resource"], **schema["daily"],
                       **{f"{ln}.{k}": v for ln, f in schema["lines"].items()
                          for k, v in f.items()}}.items():
        if spec.get("type") == "str":
            assert "enum" in spec or "pattern" in spec, name


def test_the_report_check_is_strict():
    S.check_report({"day": "2026-09-24", "errors.other": 1, "pages.load_ms_p50": 3})
    for bad in ({"day": "2026-09-24", "anything": 1},
                {"day": "2026-09-24", "errors.other": -1},
                {"day": "2026-09-24", "api.slow./not/a/route": 1},
                {"day": "today"},
                {"day": "2026-09-24", "settings.caps_set": "a sentence of text"}):
        with pytest.raises(S.SchemaError):
            S.check_report(bad)
    with pytest.raises(S.SchemaError):
        S.check_resource({"schema": 1, "tier": "basic", "version": "0.3.80",
                          "install_id": "0" * 8})
    with pytest.raises(S.SchemaError):
        S.check_resource({"schema": 1, "tier": "basic", "version": "0.3.80", "country": "DE"})


def test_a_family_key_takes_only_its_enum():
    schema = S.merge(S.own(), {"enums": {"action": ["publish"], "node": ["builds"]}})
    assert S.report_spec("actions.publish", schema) is not None
    assert S.report_spec("actions.publish_everything", schema) is None
    assert S.report_spec("pages.builds", schema) is not None
    assert S.report_spec("milestones.first_topic", schema)["type"] == "bool"


# -- modes ----------------------------------------------------------------------------------

def test_off_counts_nothing_and_keeps_nothing(home, monkeypatch):
    telemetry.set_mode(home, "off")
    telemetry.record("view", node="x")
    timing.note("/api/status", 200, 3.0)
    timing.flush()
    assert not (home / "telemetry" / "local").exists()
    assert send.run(home, now=NOW)["mode"] == "off"


def test_dnt_wins_over_detailed(home, monkeypatch):
    telemetry.set_mode(home, "detailed")
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    st = telemetry.status(home)
    assert (st["mode"], st["why"]) == ("off", "DO_NOT_TRACK")
    assert "DO_NOT_TRACK is set" in tcli._status_text(st)


def test_the_environment_decides_before_the_file(home, monkeypatch):
    telemetry.set_mode(home, "off")
    monkeypatch.setenv("KRANTO_TELEMETRY", "basic")
    assert telemetry.effective(home).mode == "basic"
    monkeypatch.setenv("KRANTO_TELEMETRY", "local")
    telemetry.set_mode(home, "detailed")
    assert telemetry.effective(home).mode == "local"


def test_local_is_the_default_and_unanswered(home):
    eff = telemetry.effective(home)
    assert (eff.mode, eff.why, eff.answered) == ("local", "default", False)


def test_set_mode_writes_the_file_and_keeps_its_comments(home):
    telemetry.set_mode(home, "basic")
    text = (home / "kranto.yaml").read_text()
    assert "mode: \"basic\"" in text and "answered_at:" in text
    assert "DO_NOT_TRACK=1 or KRANTO_TELEMETRY=off" in text
    config_mod.load(home, dotenv=False)                     # still a valid config
    with pytest.raises(telemetry.TelemetryError):
        telemetry.set_mode(home, "everything")


def test_a_bad_endpoint_is_refused():
    for bad in ("http://example.test/v1/logs", "ftp://x", "file://relative", "https://"):
        with pytest.raises(telemetry.TelemetryError):
            local.check_endpoint(bad)
    for good in ("https://t.example.test/v1/logs", "http://127.0.0.1:9030/v1/logs",
                 "file:///tmp/x"):
        assert local.check_endpoint(good) == good


# -- sending --------------------------------------------------------------------------------

def _answer(home, mode, at="2026-09-20T10:00:00+00:00", endpoint=None):
    from kranto import setup
    values = {("telemetry", "mode"): mode, ("telemetry", "answered_at"): at}
    if endpoint:
        values[("telemetry", "endpoint")] = endpoint
    setup.write_config_values(home / "kranto.yaml", values)
    local.refresh()


class FakeRelay:
    """The relay on loopback: records each POST and answers 204. Tests never post to the real
    one (``local.DEFAULT_ENDPOINT`` is pointed here)."""

    def __init__(self):
        import http.server
        import threading

        self.posts: list[dict] = []
        relay = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                relay.posts.append({"path": self.path, "headers": dict(self.headers),
                                    "body": body})
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/logs"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def relay(monkeypatch):
    r = FakeRelay()
    monkeypatch.setattr(local, "DEFAULT_ENDPOINT", r.url)
    yield r
    r.close()


_NET: list | None = None          # the audit hook records while this is a list


def _net_hook(event, args):
    if _NET is not None and event in ("socket.connect", "socket.getaddrinfo",
                                      "socket.gethostbyname", "subprocess.Popen"):
        _NET.append((event, repr(args)[:80]))


sys.addaudithook(_net_hook)


def test_the_default_endpoint_is_the_relay_and_the_environment_and_file_override_it(
        home, monkeypatch):
    assert local.DEFAULT_ENDPOINT == "https://dde6yrzwuxncv.cloudfront.net/v1/logs"
    eff = telemetry.effective(home)
    assert (eff.endpoint, eff.endpoint_from) == (local.DEFAULT_ENDPOINT, "default")
    _answer(home, "basic", endpoint="https://mine.example.test/v1/logs")
    eff = telemetry.effective(home)
    assert (eff.endpoint, eff.endpoint_from) == ("https://mine.example.test/v1/logs", "config")
    monkeypatch.setenv(local.ENV_ENDPOINT, "http://127.0.0.1:9030/v1/logs")
    eff = telemetry.effective(home)
    assert (eff.endpoint, eff.endpoint_from) == ("http://127.0.0.1:9030/v1/logs",
                                                 local.ENV_ENDPOINT)
    monkeypatch.setenv(local.DNT, "1")
    assert telemetry.effective(home).mode == "off"


def test_unanswered_local_and_off_open_no_socket(home, relay, monkeypatch):
    """Nothing is sent before an answer, or with local or off, though the default endpoint is
    set: no connection, no lookup, no process (an audit hook, as on an install's copy)."""
    global _NET
    timing.note("/api/status", 200, 3.0)
    timing.flush()
    telemetry.record("view", node="x", ms=1)
    runs = []
    _NET = []
    try:
        runs.append(send.run(home, now=NOW))                     # unanswered
        st = telemetry.status(home)
        assert not st["answered"] and not st["sending"] and st["next"] is None
        for mode in ("local", "off"):
            _answer(home, mode)
            runs.append(send.run(home, now=NOW))
            assert not telemetry.status(home)["sending"]
        monkeypatch.setenv(local.ENV_MODE, "basic")              # DO_NOT_TRACK still wins
        monkeypatch.setenv(local.DNT, "1")
        runs.append(send.run(home, now=NOW))
        seen = list(_NET)
    finally:
        _NET = None
    assert seen == [] and relay.posts == []
    assert all(not r["posted"] and not r["built"] for r in runs)
    assert not (home / "telemetry" / "sent").exists()
    assert not (home / "telemetry" / "queue").exists()


def test_basic_sends_to_the_default_endpoint(home, relay):
    _answer(home, "basic")
    st = telemetry.status(home)
    assert st["sending"] and st["endpoint_from"] == "default" and st["endpoint"] == relay.url
    global _NET
    _NET = []
    try:
        out = send.run(home, now=NOW)
        seen = list(_NET)
    finally:
        _NET = None
    assert any(e == "socket.connect" for e, _ in seen)    # the hook sees a real send
    assert [d for d, s in out["posted"]] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert {s for _, s in out["posted"]} == {204}
    assert [p["path"] for p in relay.posts] == ["/v1/logs"] * 3
    body = gzip.decompress(relay.posts[0]["body"])
    assert body == (home / "telemetry" / "sent" / "2026-09-21.json").read_bytes()
    meta = send.sent(home)[0]
    assert meta["endpoint"] == relay.url and meta["status"] == 204


def test_the_first_report_is_said_to_go_the_morning_after_the_first_whole_day(home):
    eff = local.Effective("basic", "config", local.DEFAULT_ENDPOINT, "default",
                          "2026-09-24T10:00:00+00:00", True)
    minute = send.send_minute(home)
    at = send.next_send(home, eff, NOW)       # answered at 10:00: the 25th goes on the 26th
    assert at == datetime(2026, 9, 26, send.SEND_FROM_UTC, tzinfo=UTC) + \
        timedelta(minutes=minute)
    later = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    assert send.next_send(home, eff, later).date().isoformat() == "2026-10-01"


def test_basic_posts_each_day_once_after_the_answer(home):
    _answer(home, "basic", endpoint="https://t.example.test/v1/logs")
    spy = Spy()
    out = send.run(home, now=NOW, transport=httpx.MockTransport(spy))
    # answered on the 20th at 10:00: the 21st, 22nd and 23rd are due, never the 20th
    assert [d for d, _ in out["posted"]] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    body = gzip.decompress(spy.requests[0].content)
    assert body == (home / "telemetry" / "sent" / "2026-09-21.json").read_bytes()
    assert spy.requests[0].headers["content-encoding"] == "gzip"
    import hashlib
    assert spy.requests[0].headers["x-amz-content-sha256"] == \
        hashlib.sha256(spy.requests[0].content).hexdigest()
    again = send.run(home, now=NOW, transport=httpx.MockTransport(spy))
    assert again["posted"] == [] and len(spy.requests) == 3
    env = json.loads(body)
    rec = env["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    assert rec["timeUnixNano"] == str(int(datetime(2026, 9, 21, tzinfo=UTC).timestamp()) * 10**9)
    assert not any(a["key"] == "kranto.install_id" for a in
                   env["resourceLogs"][0]["resource"]["attributes"])


def test_detailed_carries_a_random_id(home):
    _answer(home, "detailed", endpoint="file:///" + str(home / "out").lstrip("/"))
    send.run(home, now=NOW)
    sent = [json.loads(f.read_text()) for f in (home / "out").glob("*.json")]
    ids = {a["value"]["stringValue"] for e in sent
           for a in e["resourceLogs"][0]["resource"]["attributes"]
           if a["key"] == "kranto.install_id"}
    assert len(ids) == 1 and S.value_ok({"type": "str", "pattern": "uuid4"}, ids.pop(), S.union())


@pytest.mark.parametrize("iid", ["9c69b3ff-9741-4438-8093-a1b2c88ea837",   # "a phone number"
                                 "0b0f4789-7897-4554-9012-799b6d79a554"])
def test_an_install_id_with_phone_like_digits_still_sends(home, iid):
    """the flake of test_detailed_carries_a_random_id was the id itself. About 1 random
    uuid4 in 250 has digit groups the scrubber's phone pattern reads, and the whole day's report
    was refused, every day, for as long as the install kept that id."""
    _answer(home, "detailed", endpoint="file:///" + str(home / "out").lstrip("/"))
    st = local.read_state(home)
    st.update(install_id=iid, install_id_made=NOW.isoformat(timespec="seconds"))
    local.write_state(home, st)
    out = send.run(home, now=NOW)
    assert not out.get("refused"), out
    sent = [json.loads(f.read_text()) for f in (home / "out").glob("*.json")]
    ids = {a["value"]["stringValue"] for e in sent
           for a in e["resourceLogs"][0]["resource"]["attributes"]
           if a["key"] == "kranto.install_id"}
    assert ids == {iid}
    # anything else in the payload that looks like a phone number is still refused
    from kranto.telemetry import report
    assert report.scrubbed({"resource": {"install_id": "call 555-0100-2000"}}) == 1


def test_an_unreachable_endpoint_keeps_the_queue_and_an_answer_ends_it(home):
    _answer(home, "basic", endpoint="https://t.example.test/v1/logs")

    def down(request):
        raise httpx.ConnectError("no route", request=request)
    out = send.run(home, now=NOW, transport=httpx.MockTransport(down))
    assert out["queued"] == 3 and out["unreached"] == "ConnectError"
    out = send.run(home, now=NOW, transport=httpx.MockTransport(Spy(429)))
    assert [s for _, s in out["posted"]] == [429, 429, 429] and out["queued"] == 0


def test_the_queue_is_bounded(home):
    for i in range(send.QUEUE_MAX + 5):
        dropped = send.queue(home, f"2026-08-{i + 1:02d}" if i < 31 else f"2026-09-{i - 30:02d}",
                             b"x" * 10)
    assert len(list(send.qdir(home).glob("*.json"))) == send.QUEUE_MAX
    assert dropped


def test_old_lines_are_pruned(home):
    d = home / "telemetry" / "local"
    d.mkdir(parents=True)
    (d / "2026-09-01.jsonl").write_text("{}\n")
    (d / "2026-09-20.jsonl").write_text("{}\n")
    send.run(home, now=NOW)
    assert sorted(p.name for p in d.iterdir()) == ["2026-09-20.jsonl"]


# -- canaries --------------------------------------------------------------------------------

def test_canaries_never_reach_a_line_a_report_or_a_payload(tmp_path, monkeypatch, embedder):
    token = secrets.token_hex(6)
    home = tmp_path / f"home-{token}"
    config_mod.init_workspace(home)
    telemetry.configure(home)
    monkeypatch.setenv("USER", f"user{token}")
    # key-shaped values built at run time, never literals in the tree
    shaped = {"OPENROUTER_API_KEY": "sk-" + "or-v1-" + token * 4,
              "ANTHROPIC_API_KEY": "sk-" + "ant-" + token * 4,
              "GH_TOKEN": "gh" + "p_" + token * 4}
    (home / ".env").write_text("".join(f"{k}={v}\n" for k, v in shaped.items()))
    store = Store.open(home / "data" / "kranto.db")
    topic = library.add_topic(store, embedder, f"canary-topic-{token}", f"about {token}")
    src = library.add_source(store, "rss", {"url": f"https://{token}.example.test/feed"},
                             label=f"feed {token}")
    library.link_topic_source(store, topic, src)
    canaries = [token, *shaped.values(), f"{token}@example.test", f"canary-org/{token}",
                f"/home/{token}/x"]
    # everything an emitter might wrongly hand over
    for c in canaries:
        telemetry.record("view", node=c, ms=1)
        telemetry.record("error", fingerprint=c, where="api")
        telemetry.record("api", route=c, n2=1)
        telemetry.record("action", kind=c, origin=c, text=c)
    try:
        raise KeyError(f"/home/{token}/x {token}@example.test")
    except KeyError as exc:
        timing.record_error(exc, "api")
    _answer(home, "detailed", endpoint="file:///" + str(tmp_path / "out").lstrip("/"))
    cfg = config_mod.load(home, dotenv=False)
    send.run(home, store=store, cfg=cfg, now=NOW)
    today = report.build(home, NOW.strftime("%Y-%m-%d"), store=store, cfg=cfg, tier="detailed")
    store.close()
    texts = [p.read_text() for p in (home / "telemetry").rglob("*") if p.is_file()]
    texts += [p.read_text() for p in (tmp_path / "out").glob("*")]
    texts.append(json.dumps(today))
    assert len(texts) > 4
    for t in texts:
        for c in canaries:
            assert c not in t
        for marker in ("/home/", "@", "http", "sk-", "example-host"):
            assert marker not in t, marker
    # the second net finds nothing in a report's strings
    assert report.scrubbed(today) == 0


# -- crash fingerprints ----------------------------------------------------------------------

def test_a_fingerprint_has_the_class_and_own_frames_never_the_message():
    fp = None
    try:
        local.check_endpoint("ftp://secret.example.test/home/someone")
    except telemetry.TelemetryError as exc:
        fp = timing.fingerprint(exc)
    assert fp and fp.startswith("TelemetryError:kranto.telemetry.local.check_endpoint:")
    assert "secret" not in fp and "tests" not in fp and fp.count(":") == 2
    assert S.value_ok({"type": "str", "pattern": "fingerprint"}, fp, S.union())
    try:
        json.loads("{")                                  # no frame of Kranto's own
    except ValueError as exc:
        assert timing.fingerprint(exc) is None


def test_a_milestone_from_the_facts_is_kept(home):
    got = report.milestones(home, {"update.applied": 1}, None)
    assert got["milestones.first_update"] is True
    assert report.milestones(home, {}, None)["milestones.first_update"] is True   # kept


def test_a_build_milestone_kept_before_the_cut_stays_stored_and_is_not_sent(home):
    local.write_state(home, {"milestones": ["first_build_ready", "first_topic"]})
    got = report.milestones(home, {}, None)
    assert "milestones.first_build_ready" not in got and got["milestones.first_topic"] is True
    assert "first_build_ready" in local.read_state(home)["milestones"]       # not rewritten


def test_a_build_line_kept_before_the_cut_counts_in_no_report(home):
    lines = [{"e": "build", "outcome": "ready", "wall_s": 30, "usd_cents": 9,
              "stage_wall_s": {"code": 3}},
             {"e": "view", "node": "x", "ms": 5}]
    out = report.fold_lines(lines)
    assert not [k for k in out if k.startswith(("builds.", "stages."))]
    assert out["pages.x"] == 1
    rep = report.allowed({"day": "2026-09-24", "builds.ready": 1, "projects_count": 2,
                          "settings.intake_mode": "manual"})
    assert rep == {"day": "2026-09-24", "dropped_fields": 3}


def test_the_twenty_first_fingerprint_is_other():
    lines = [{"e": "error", "fingerprint": f"KeyError:kranto.m.f:{i}", "where": "api"}
             for i in range(25)]
    out = report.fold_lines(lines)
    assert sum(1 for k in out if k.startswith("errors.KeyError")) == 20
    assert out["errors.other"] == 5


# -- the server -------------------------------------------------------------------------------

@pytest.fixture
def rt(tmp_path, store, embedder, make_client):
    config_mod.init_workspace(tmp_path / "w")
    cfg = Config(root=tmp_path / "w", llm=llm_config(), budget=BudgetConfig(monthly_usd=None),
                 ingest=IngestConfig(), map=MapConfig())
    client = make_client(lambda body: chat_response("{}"))
    return open_runtime(cfg, store=store, embedder=embedder, llm=client)


def test_settings_telemetry_and_views(rt):
    telemetry.configure(rt.cfg.root)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        st = web.get("/api/settings/telemetry").json()
        assert st["mode"] == "local" and not st["answered"] and not st["sending"]
        assert [m["mode"] for m in st["modes"]] == list(telemetry.MODES)
        assert web.post("/api/settings/telemetry", json={"mode": "nope"}).status_code == 400
        st = web.post("/api/settings/telemetry", json={"mode": "basic"}).json()
        assert st["mode"] == "basic" and st["answered"]
        assert st["sending"] and st["why_not"] is None and st["next"]
        assert (st["endpoint"], st["endpoint_from"]) == (local.DEFAULT_ENDPOINT, "default")
        r = web.post("/api/telemetry/view", json={"views": [{"node": "x/42", "ms": 9,
                                                             "url": "#/builds/secret"}]})
        assert r.status_code == 204
        rep = web.get("/api/settings/telemetry/report").json()
        assert rep["report"]["day"] == datetime.now(UTC).strftime("%Y-%m-%d")
        assert rep["resource"]["tier"] == "basic"
        timing.flush()
    got = lines_of(rt.cfg.root)
    assert not any("secret" in json.dumps(g) for g in got)
    api = [g for g in got if g["e"] == "api"]
    assert {"route": "/api/settings/telemetry"}.items() <= api[0].items() or \
        any(g["route"] == "/api/settings/telemetry" for g in api)
    assert all(not g["route"].startswith("/api/settings/telemetry/") or
               g["route"] == "/api/settings/telemetry/report" for g in api)


def test_the_route_enum_is_the_apps_routes(rt):
    app = create_app(rt)
    # the /brb mount's two routes are there when the page is mounted (web/brb.py)
    routes = sorted({r.path for r in app.routes if getattr(r, "path", None)}
                    | {"other", "/brb", "/brb/{path:path}"})
    assert sorted(S.own()["enums"]["route"]) == routes, (
        "add the route to telemetry/schema.json's route enum and run "
        "'kranto telemetry docs > docs/privacy/what-kranto-sends.md':\n"
        + json.dumps(routes))


def test_the_job_records_a_run(rt):
    job = send.make_job(rt.cfg.root, rt.store, lambda: rt.cfg)
    job.run()
    row = rt.store.query_one("SELECT status, summary FROM runs WHERE kind = 'telemetry'")
    assert row["status"] == "ok" and json.loads(row["summary"])["mode"] == "local"


def test_a_report_built_from_a_real_library_validates(rt, embedder):
    topic = library.add_topic(rt.store, embedder, "t", "d")
    src = library.add_source(rt.store, "rss", {"url": "https://ex.test/f"}, label="f")
    library.link_topic_source(rt.store, topic, src)
    p = report.build(rt.cfg.root, "2026-09-24", store=rt.store, cfg=rt.cfg)
    r = p["report"]
    assert r["topics_count"] == 1 and r["watch.sources_by_kind.rss"] == 1
    assert r["milestones.first_topic"] is True and r["milestones.first_update"] is False
    assert r["settings.caps_set"] == "none" and r["provider"] == "openai_compat"
    assert len(send.wire(p)) < 8000


def test_a_line_kept_before_its_route_was_retired_is_dropped_and_counted(rt):
    """Live on 2026-10-23: lines for /api/watches, kept before the update that retired it,
    failed the whole day's report (the privacy page answered 500)."""
    d = rt.cfg.root / "telemetry" / "local"
    d.mkdir(parents=True, exist_ok=True)
    ts = int(datetime(2026, 9, 24, 9, 0, tzinfo=UTC).timestamp())
    lines = [{"e": "api", "ts": ts, "route": "/api/watches", "n2": 2, "slow": 1,
              "h": [0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]},
             {"e": "api", "ts": ts, "route": "/api/topics", "n2": 1, "slow": 1,
              "h": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0]},
             {"e": "view", "ts": ts, "node": "watch/watches"}]
    (d / "2026-09-24.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    p = report.build(rt.cfg.root, "2026-09-24", store=rt.store, cfg=rt.cfg)
    r = p["report"]
    assert not [k for k in r if "watches" in k]
    assert r["api.slow./api/topics"] == 1 and r["api.requests"] == 3
    assert r["dropped_fields"] == 2
    S.check_report(r)


@pytest.mark.parametrize("raw, want", [
    ("0.5.25", ("0.5.25", False)),
    ("0.5.25rc1", ("0.5.25-rc1", False)),
    ("0.5.25rc12+local", ("0.5.25-rc12", False)),
    ("0.5.25.dev3+g1234abc", ("0.5.25", True)),
    ("0.5.25rc1.dev2", ("0.5.25", True)),
    ("0.5.25a1", ("0.5.25", True)),
    ("unknown", ("0.0.0", True)),
    ("0.7.0.dev12", ("0.7.0", True)),        # a nightly, until the relay knows the form
])
def test_every_installs_version_is_one_the_list_allows(raw, want):
    assert report.version_of(raw) == want
    S.check_resource({"schema": 1, "tier": "basic", "version": want[0]})


def test_a_nightly_is_sent_as_its_tag_once_the_relay_knows_the_form(monkeypatch):
    assert report.channel_of("0.7.0", True, "nightly") == "main"
    assert report.channel_of("0.6.2", False, "nightly") == "rc"       # the relay's old word
    assert report.channel_of("0.6.2", False, "stable") == "stable"
    monkeypatch.setattr(report, "RELAY_KNOWS_NIGHTLY", True)
    assert report.version_of("0.7.0.dev12") == ("0.7.0-dev12", False)
    assert report.version_of("0.7.0.dev3+g1234abc") == ("0.7.0", True)
    assert report.channel_of("0.7.0-dev12", False, "stable") == "nightly"
    S.check_resource({"schema": 1, "tier": "basic", "version": "0.7.0-dev12",
                      "channel": "nightly"})


def test_an_rc_builds_its_report(rt, monkeypatch):
    monkeypatch.setattr(report, "__version__", "0.5.25rc1")
    p = report.build(rt.cfg.root, "2026-09-24", store=rt.store, cfg=rt.cfg)
    assert p["resource"]["version"] == "0.5.25-rc1"
    assert p["resource"]["channel"] != "main"


# -- the CLI and the page -------------------------------------------------------------------

def test_the_cli(home, capsys):
    assert tcli.main(home, []) == 0
    assert "local: counted on this machine only" in capsys.readouterr().out
    assert tcli.main(home, ["basic"]) == 0
    out = capsys.readouterr().out
    assert "Never your topics" in out and "relay the maintainer runs on AWS in the EU" in out
    assert f"endpoint   {local.DEFAULT_ENDPOINT} (default)" in out and "sending    on" in out
    assert tcli.main(home, ["show"]) == 0
    shown = capsys.readouterr()
    assert '"day"' in shown.out and "not sent" not in shown.err
    assert tcli.main(home, ["local"]) == 0
    capsys.readouterr()
    assert tcli.main(home, ["show"]) == 0
    assert "not sent" in capsys.readouterr().err
    assert tcli.main(home, ["basic"]) == 0
    capsys.readouterr()
    assert tcli.main(home, ["show", "--wire"]) == 0
    json.loads(capsys.readouterr().out)                  # the bytes alone, as the relay takes
    assert tcli.main(home, ["show", "--sent"]) == 0
    assert "nothing has been sent" in capsys.readouterr().out
    assert tcli.main(home, ["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "basic"


def test_the_field_page_is_the_lists():
    page = (ROOT / "docs" / "privacy" / "what-kranto-sends.md").read_text()
    assert page == docs.page(), "run: kranto telemetry docs > docs/privacy/what-kranto-sends.md"


def test_record_never_raises_on_a_read_only_directory(home):
    d = home / "telemetry" / "local"
    d.mkdir(parents=True)
    os.chmod(d, 0o500)
    try:
        telemetry.record("view", node="x")
    finally:
        os.chmod(d, 0o700)
