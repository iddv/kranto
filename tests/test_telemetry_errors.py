"""Error reports: they follow the telemetry choice exactly (nothing leaves
with local, off, unanswered or DO_NOT_TRACK: a test fails if a connection is even attempted),
one report per signature with a count, the limits, the batch passes Kranto's own list and the
relay's, and the hooks (a request, a job, a run that failed without raising) report."""

from __future__ import annotations

import gzip
import json
import socket
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route
from starlette.testclient import TestClient

from kranto import config as config_mod
from kranto import telemetry
from kranto.telemetry import errors, local, timing
from kranto.telemetry import schema as S

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_790_000_000.0
ENDPOINT = "http://127.0.0.1:9/v1/logs"        # never reached: every test passes a transport


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (local.DNT, local.ENV_MODE):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv(local.ENV_ENDPOINT, ENDPOINT)
    errors._pending.clear()
    yield
    errors._pending.clear()
    errors._flusher = None
    telemetry.configure(None)


def make_home(tmp_path, mode: str | None) -> Path:
    h = tmp_path / "home"
    config_mod.init_workspace(h)
    if mode is not None:
        telemetry.set_mode(h, mode)
    telemetry.configure(h)
    return h


class Spy:
    def __init__(self, status=204):
        self.requests, self.status = [], status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)


def body_of(req: httpx.Request) -> dict:
    return json.loads(gzip.decompress(req.content))


def boom(msg="unsupported format string passed to NoneType.__format__"):
    raise TypeError(msg)


def caught(fn=boom, *a) -> BaseException:
    try:
        fn(*a)
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("no exception")


class _InServer:
    """``errors.start`` without its thread: reports kept in memory, as in the server."""

    def __init__(self, home):
        self.home = home


def in_server(home):
    errors._flusher = _InServer(home)


# -- consent ---------------------------------------------------------------------------------

@pytest.fixture
def no_network(monkeypatch):
    """Any connection attempt fails the test."""
    def refuse(*a, **k):
        raise AssertionError("a connection was attempted")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.parametrize("mode,env", [(None, {}), ("local", {}), ("off", {}),
                                      ("basic", {local.DNT: "1"}),
                                      ("detailed", {local.ENV_MODE: "off"}),
                                      ("basic", {local.ENV_MODE: "local"})])
def test_without_consent_nothing_is_kept_and_nothing_leaves(tmp_path, monkeypatch, no_network,
                                                            mode, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    home = make_home(tmp_path, mode)
    in_server(home)
    for _ in range(3):
        errors.report(caught(), "api", route="/api/topics/{topic_id:int}")
    errors.report_failure("UpdateSelfCheck", "update", home=home)
    timing.record_error(caught(), "api")
    assert errors.pending() == [] and not (errors.edir(home) / "spool.jsonl").exists()
    spy = Spy()
    out = errors.flush(home, now=T0 + 3600, transport=httpx.MockTransport(spy))
    assert out["sent"] == 0 and spy.requests == []
    assert errors.sent(home) == []


def test_choosing_off_deletes_what_waits(tmp_path):
    home = make_home(tmp_path, "basic")
    errors.report(caught(), "api", home=home)           # not in the server: the spool
    in_server(home)
    errors.report(caught(), "job", job="ingest")
    assert errors.waiting(home) and errors.pending()
    telemetry.set_mode(home, "off")
    assert errors.pending() == [] and not (errors.edir(home) / "spool.jsonl").exists()
    errors._flusher = None
    assert errors.waiting(home) == []


# -- one report per signature, the limits ----------------------------------------------------

def test_one_report_per_signature_with_its_count_and_once_an_hour(tmp_path):
    home = make_home(tmp_path, "basic")
    in_server(home)
    exc = caught()
    for _ in range(100):
        errors.report(exc, "api", route="/api/topics/{topic_id:int}")
    assert len(errors.pending()) == 1 and errors.pending()[0]["count"] == 100
    spy = Spy()
    t = httpx.MockTransport(spy)
    first = errors.pending()[0]["first"]
    assert errors.flush(home, now=first + 10, transport=t)["sent"] == 0   # gathering a burst
    out = errors.flush(home, now=first + errors.GATHER_S, transport=t)
    assert out["sent"] == 1 and len(spy.requests) == 1
    rec = body_of(spy.requests[0])["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    attrs = {a["key"]: next(iter(a["value"].values())) for a in rec["attributes"]}
    assert attrs["kranto.count"] == "100" and attrs["event.name"] == "kranto.error"
    assert attrs["kranto.route"] == "/api/topics/{topic_id:int}"
    assert int(rec["timeUnixNano"]) % (3600 * 10**9) == 0             # the hour, no finer
    # again within the hour: counted, not sent
    for _ in range(5):
        errors.report(exc, "api")
    assert errors.flush(home, now=first + 1800, transport=t)["sent"] == 0
    assert errors.pending()[0]["count"] == 5
    out = errors.flush(home, now=first + errors.GATHER_S + errors.RESEND_S, transport=t)
    assert out["sent"] == 1 and len(spy.requests) == 2


def test_what_happens_during_a_post_is_kept_for_the_next_report(tmp_path):
    home = make_home(tmp_path, "basic")
    in_server(home)
    exc = caught()
    for _ in range(4):
        errors.report(exc, "api")

    def during(request):
        for _ in range(2):
            errors.report(exc, "api")       # the same error, while the batch is in flight
        return httpx.Response(204)
    first = errors.pending()[0]["first"]
    assert errors.flush(home, now=first + 61, transport=httpx.MockTransport(during))["sent"] == 1
    (left,) = errors.pending()
    assert left["count"] == 2


def test_the_command_line_says_one_report_and_two_reports(tmp_path, capsys):
    from kranto.telemetry import cli as tcli

    home = make_home(tmp_path, "basic")
    in_server(home)
    errors.report(caught(), "api")
    errors.flush(home, now=errors.pending()[0]["first"] + 61, transport=httpx.MockTransport(Spy()))
    tcli.main(home, ["status"])
    tcli.main(home, ["show", "--sent"])
    out = capsys.readouterr().out
    assert "1 report, HTTP 204" in out and "1 error report," in out and "1 reports" not in out


def test_the_limits_per_batch_hour_and_day(tmp_path, monkeypatch):
    home = make_home(tmp_path, "basic")
    in_server(home)
    for i in range(70):
        e = errors._entry(errtrace_failure(f"Failure{i:02d}"), "job", None, "ingest", T0)
        with errors._lock:
            errors._merge(e)
    spy = Spy()
    t = httpx.MockTransport(spy)
    sizes = []
    for k in range(6):                         # six looks in one hour
        out = errors.flush(home, now=T0 + 120 + k * 60, transport=t)
        sizes.append(out["sent"])
    assert sizes == [10, 10, 10, 10, 0, 0]     # at most 10 a batch, 4 batches an hour
    for k in range(4):                         # the next hour
        sizes.append(errors.flush(home, now=T0 + 3800 + k * 60, transport=t)["sent"])
    assert sum(sizes) == errors.MAX_DAY        # at most 50 a day; the rest waits
    assert len(errors.pending()) == 20
    nxt = T0 + 86400 + 4000
    assert errors.flush(home, now=nxt, transport=t)["sent"] == 10   # the next day


def errtrace_failure(name):
    from kranto import errtrace
    return errtrace.failure(name, "")


def test_unreached_keeps_the_reports_and_waits(tmp_path):
    home = make_home(tmp_path, "detailed")
    in_server(home)
    errors.report(caught(), "api")

    def down(request):
        raise httpx.ConnectError("no route")
    first = errors.pending()[0]["first"]
    out = errors.flush(home, now=first + 61, transport=httpx.MockTransport(down))
    assert "unreached" in out and len(errors.pending()) == 1
    spy = Spy()
    assert errors.flush(home, now=first + 120, transport=httpx.MockTransport(spy))["sent"] == 0
    assert errors.flush(home, now=first + 61 + errors.RETRY_S,
                        transport=httpx.MockTransport(spy))["sent"] == 1
    sent = body_of(spy.requests[0])
    res = {a["key"]: a["value"] for a in sent["resourceLogs"][0]["resource"]["attributes"]}
    assert "kranto.install_id" in res and res["kranto.tier"] == {"stringValue": "detailed"}


def test_the_spool_from_another_process_is_taken_in(tmp_path):
    home = make_home(tmp_path, "basic")
    for _ in range(3):
        errors.report(caught(), "update", home=home)       # e.g. the update helper
    lines = (errors.edir(home) / "spool.jsonl").read_text().splitlines()
    assert len(lines) == 3
    assert sum(e["count"] for e in errors.waiting(home)) == 3
    in_server(home)
    spy = Spy()
    errors.flush(home, now=T0, transport=httpx.MockTransport(spy))
    assert not (errors.edir(home) / "spool.jsonl").exists()
    assert errors.pending()[0]["count"] == 3 and errors.pending()[0]["where"] == "update"


def test_a_basic_batch_has_no_identifier_and_what_was_sent_is_kept(tmp_path):
    home = make_home(tmp_path, "basic")
    in_server(home)
    errors.report(caught(), "api")
    spy = Spy()
    errors.flush(home, now=errors.pending()[0]["first"] + 61, transport=httpx.MockTransport(spy))
    body = spy.requests[0].content
    assert b"install_id" not in gzip.decompress(body)
    (meta,) = errors.sent(home)
    assert meta["reports"] == 1 and meta["status"] == 204 and meta["tier"] == "basic"
    assert errors.sent_body(home, meta["id"]) == gzip.decompress(body)
    assert errors.sent_body(home, "../../etc/passwd") is None
    st = telemetry.status(home)
    assert st["errors"]["sent"] == 1 and st["errors"]["last_sent"]["id"] == meta["id"]


# -- the list (the relay's side left Kranto with ops/: cut 2) ----------------------

@pytest.mark.parametrize("field,value", [
    ("message", "token for /home/someone/x"), ("message", "Robotics has no sources"),
    ("stack", "/home/someone/kranto/x.py:12"), ("stack", "kranto.x.f:12 > secret.txt"),
    ("type", "My Error"), ("signature", "XYZ"), ("count", 0), ("where", "elsewhere")])
def test_kranto_refuses_what_the_list_does_not_allow(tmp_path, field, value):
    rec = {"signature": "0123456789abcdef", "type": "TypeError", "where": "api",
           "message": "", "stack": "kranto.x.f:1", "count": 1, field: value}
    with pytest.raises(S.SchemaError):
        S.check_error(rec)


def test_a_request_that_raises_is_reported_with_its_route_pattern(tmp_path):
    home = make_home(tmp_path, "basic")
    in_server(home)

    def topic(request):
        boom()

    app = Starlette(routes=[Route("/api/topics/{topic_id:int}", topic)],
                    middleware=[Middleware(timing.TimingMiddleware)])
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/api/topics/12").status_code == 500
    (e,) = errors.pending()
    assert e["where"] == "api" and e["route"] == "/api/topics/{topic_id:int}"
    assert e["type"] == "TypeError"
    assert e["message"] == "unsupported format string passed to NoneType.__format__"
    assert "12" not in json.dumps(errors.record_of(e))


def test_a_job_that_raises_is_reported_with_its_kind(tmp_path):
    from kranto.scheduler import _count_error

    home = make_home(tmp_path, "basic")
    in_server(home)
    exc = caught()
    _count_error(exc, "scheduler", "ingest")
    (e,) = errors.pending()
    assert e["job"] == "ingest" and e["where"] == "scheduler"
    _count_error(exc, "scheduler", "send.newsletter")    # a cub's job is other; same signature
    (e,) = errors.pending()
    assert e["count"] == 2 and e["job"] == "other"


def test_a_run_that_failed_without_raising_is_reported(tmp_path):
    from kranto.activity import _report_failed

    home = make_home(tmp_path, "basic")
    in_server(home)
    _report_failed("ideas", "KeyError: 'Robotics'")
    _report_failed("ingest", "Robotics: 3 sources failed")
    got = {e["job"]: e for e in errors.pending()}
    assert got["ideas"]["type"] == "KeyError" and got["ideas"]["message"] == "'<x>'"
    assert got["ingest"]["type"] == "JobFailed" and "Robotics" not in json.dumps(got)
    assert got["ingest"]["stack"] == "" and got["ingest"]["where"] == "job"


def test_the_flusher_saves_what_waits_and_loads_it_again(tmp_path):
    home = make_home(tmp_path, "basic")
    fl = errors.Flusher(home, tick_s=3600)
    fl.start()
    errors._flusher = fl
    try:
        errors.report(caught(), "api")
    finally:
        fl.stop()
    errors._pending.clear()
    assert json.loads((errors.edir(home) / "pending.json").read_text())[0]["count"] == 1
    errors._load_pending(home)
    assert errors.pending()[0]["count"] == 1


def test_the_privacy_page_lists_every_error_field_and_the_words():
    from kranto.telemetry import docs

    page = docs.page()
    for k in S.own()["error"]:
        assert f"| `{k}` |" in page
    assert "`NoneType`" in page and "within minutes" in page
    assert (ROOT / "docs" / "privacy" / "what-kranto-sends.md").read_text() == page


def test_show_sent_takes_its_day_or_batch_after_the_flag(tmp_path, capsys):
    from kranto.telemetry import cli as tcli

    home = make_home(tmp_path, "basic")
    in_server(home)
    errors.report(caught(), "api")
    errors.flush(home, now=errors.pending()[0]["first"] + 61, transport=httpx.MockTransport(Spy()))
    (meta,) = errors.sent(home)
    capsys.readouterr()
    assert tcli.main(home, ["show", "--sent", meta["id"]]) == 0
    assert '"kranto.error"' in capsys.readouterr().out
    assert tcli.main(home, ["show", meta["id"], "--sent"]) == 0
