"""A refused model key is one blocking incident.

An install's OpenRouter key expired on 2026-10-25 08:15 UTC; ingest, ideas and the newsletter cub
failed for two days as three Fix rows (after the second failure each), nine "ingest run
failed" messages and no word for the cause. These tests hold the incident that replaces them.
Nothing touches a model or the network."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import time_machine

from kranto import activity, notify
from kranto.activity import incidents
from kranto.activity import read as activity_read
from kranto.store import iso, utcnow

EXPIRED = "HTTP 401 from https://openrouter.ai/api/v1: API key expired."
CUB_OLD = "HostError: the model did not answer: FatalLLMError"
CUB_NEW = f"HostError: the model did not answer: FatalLLMError: {EXPIRED}"


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


def _run(store, kind, status, error=None, at=None):
    at = at or utcnow()
    with activity.run(store, kind) as r:
        store.insert("runs", {"run_uuid": r.uuid, "kind": kind, "status": status,
                              "started_at": iso(at), "finished_at": iso(at),
                              "summary": json.dumps({}), "error": error})
    return r.uuid


def _reader(store):
    return activity_read.Reader(store, titles={"newsletter": "Newsletter"})


@pytest.mark.parametrize("error, want", [
    (EXPIRED, ("openrouter", "OpenRouter", "expired")),
    ("HTTP 401 from https://api.anthropic.com: invalid x-api-key",
     ("anthropic", "Claude API", "invalid")),
    ("HTTP 402 from https://openrouter.ai/api/v1: Insufficient credits",
     ("openrouter", "OpenRouter", "out of credit")),
    ("no API key: set $OPENROUTER_API_KEY", ("openrouter", "OpenRouter", "missing")),
    ("HTTP 403 from https://openrouter.ai/api/v1: forbidden", ("openrouter", "OpenRouter",
                                                               "refused")),
    (CUB_NEW, ("openrouter", "OpenRouter", "expired")),
])
def test_a_refused_key_is_classed_by_its_provider_and_cause(error, want):
    got = incidents.classify(error)
    assert (got["provider"], got["name"], got["cause"]) == want


def test_a_missing_key_is_said_missing_not_refused():
    assert incidents.title("OpenRouter", "missing") == "Your OpenRouter key is missing"
    said = incidents.sentence("OpenRouter", "missing", "08:15 on 25 Oct", ["reading your sources"])
    assert said == ("Your OpenRouter key is missing (since 08:15 on 25 Oct). Stopped until it is "
                    "set in Settings › Watching: reading your sources.")
    # one kind or many, the words read right ("idea cards stops" on the scratch walk); a
    # provider Kranto cannot name is "your model key", never "model provider's"
    one = incidents.sentence("OpenRouter", "expired", "08:15 on 25 Oct", ["idea cards"])
    assert one.endswith(". Stopped until it is renewed in Settings › Watching: idea cards.")
    got = incidents.classify("HTTP 401 from http://10.1.2.3:4000/v1: invalid api key")
    assert got["provider"] == "10.1.2.3" and got["name"] == "10.1.2.3"
    assert incidents.classify("no API key: set $KRANTO_E2E_UNSET")["name"] == ""
    assert incidents.title("", "missing") == "Your model key is missing"


@pytest.mark.parametrize("error", [
    None, "", "HTTP 403 from https://example.com/feed.xml: forbidden",
    "gave up after 3 attempts: HTTP 503", "HTTP 429 from https://openrouter.ai/api/v1: slow down",
    "crashed before hello (exit 137, memory)",
])
def test_other_failures_are_not_incidents(error):
    assert incidents.classify(error) is None


def test_one_401_is_one_incident_from_the_first_failure_with_renew_the_key(store):
    _run(store, "ingest", "ok", at=utcnow() - timedelta(hours=4))
    _run(store, "ingest", "failed", EXPIRED, at=utcnow() - timedelta(hours=1))
    out = _reader(store).read()
    [inc] = out["incidents"]
    assert inc["id"] == "auth:openrouter" and inc["blocking"] is True
    assert inc["verb"] == "Renew the key" and inc["href"] == "#/settings/watching?sel=ekey"
    assert inc["title"] == "Your OpenRouter key is refused (expired)"
    assert inc["words"].startswith("Your OpenRouter key was refused (expired) at ")
    assert inc["words"].endswith(". Stopped until it is renewed in Settings › Watching: "
                                 "reading your sources.")
    assert [k["kind"] for k in inc["kinds"]] == ["ingest"]
    assert out["failing"] == []                      # its kind has no Fix row of its own
    assert out["counts"]["incidents"] == 1


def test_ingest_ideas_and_a_cub_fold_into_the_one_incident(store):
    t0 = utcnow() - timedelta(days=2)
    _run(store, "ingest", "failed", EXPIRED, at=t0)
    _run(store, "ingest", "failed", EXPIRED, at=t0 + timedelta(hours=3))
    _run(store, "ideas", "failed", EXPIRED, at=t0 + timedelta(hours=4))
    _run(store, "newsletter.weekly", "failed", CUB_OLD, at=t0 + timedelta(hours=5))
    _run(store, "newsletter.weekly", "failed", CUB_NEW, at=t0 + timedelta(hours=6))
    _run(store, "toot.weekly", "failed", "crashed", at=t0 + timedelta(hours=1))
    _run(store, "toot.weekly", "failed", "crashed", at=t0 + timedelta(hours=2))
    out = _reader(store).read()
    [inc] = out["incidents"]
    assert [k["kind"] for k in inc["kinds"]] == ["ingest", "ideas", "newsletter.weekly"]
    assert inc["tries"] == 5 and inc["since"] == iso(t0)
    assert inc["words"].endswith(": reading your sources, idea cards and newsletter's weekly run.")
    assert [f["kind"] for f in out["failing"]] == ["toot.weekly"]   # others keep their rows


def test_a_cub_naming_only_the_class_alone_stays_a_fix_row(store):
    _run(store, "newsletter.weekly", "failed", CUB_OLD, at=utcnow() - timedelta(hours=2))
    _run(store, "newsletter.weekly", "failed", CUB_OLD)
    out = _reader(store).read()
    assert out["incidents"] == [] and [f["kind"] for f in out["failing"]] == [
        "newsletter.weekly"]


def test_the_incident_goes_when_its_kinds_run_well_again(store):
    _run(store, "ingest", "failed", EXPIRED, at=utcnow() - timedelta(hours=2))
    _run(store, "ideas", "failed", EXPIRED, at=utcnow() - timedelta(hours=1))
    _run(store, "ingest", "ok")
    [inc] = _reader(store).incidents()
    assert [k["kind"] for k in inc["kinds"]] == ["ideas"]
    _run(store, "ideas", "ok")
    assert _reader(store).incidents() == []


def test_the_next_runs_say_a_held_kind_is_failing(store):
    from types import SimpleNamespace
    _run(store, "ingest", "failed", EXPIRED, at=utcnow() - timedelta(hours=2))
    sched = SimpleNamespace(next_runs=lambda: {"ingest": iso(utcnow() + timedelta(hours=1))},
                            jobs=[SimpleNamespace(kind="ingest", every_hours=3, job=None)])
    [n] = activity_read.Reader(store, sched).read()["next"]
    assert n["failing_since"] and n["failures_in_a_row"] == 1


def test_run_failed_messages_stop_after_the_first_while_the_key_is_refused(store):
    def fail(kind):
        uuid = _run(store, kind, "failed", EXPIRED)
        return notify.alarm_for_run(store, kind=kind, run_uuid=uuid, status="failed",
                                    error=EXPIRED)
    with time_machine.travel(utcnow() - timedelta(days=1), tick=True):
        _run(store, "ingest", "ok", at=utcnow() - timedelta(days=1))
        assert fail("ingest") is not None
        assert fail("ingest") is None and fail("ingest") is None and fail("ideas") is None
        titles = [m["title"] for m in notify.recent_messages(store)]
        assert titles == ["Your OpenRouter key is refused (expired)"]
    # renewed a day later: a good run, then refused again is said again, once
    _run(store, "ingest", "ok")
    assert fail("ingest") is not None and fail("ingest") is None
    # any other failure still says itself a run
    uuid = _run(store, "ingest", "failed", "crashed")
    assert notify.alarm_for_run(store, kind="ingest", run_uuid=uuid, status="failed",
                                error="crashed") is not None


def test_a_cubs_model_error_keeps_the_providers_cause(monkeypatch):
    from types import SimpleNamespace

    from kranto.core.cubs import host as cub_host
    from kranto.llm import FatalLLMError

    def boom(**kw):
        raise FatalLLMError(EXPIRED, status=401)

    h = cub_host.CubHost.__new__(cub_host.CubHost)
    h.rt = SimpleNamespace(llm=SimpleNamespace(complete=boom))
    h.cub = SimpleNamespace(id="newsletter", version="1", feature="newsletter")
    h.run_uuid = None
    monkeypatch.setattr(cub_host.CubHost, "store", None)
    h.runtime = SimpleNamespace(cap_usd=lambda cub: None)
    monkeypatch.setattr(h, "_grant", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(h, "_per_hour", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(cub_host.api, "spend_of", lambda store, f: {"month_usd": 0.0})
    with pytest.raises(Exception) as got:
        h._m_model_complete({"purpose": "p", "tier": "cheap",
                             "messages": [{"role": "user", "content": "hi"}]})
    said = str(got.value)
    assert "FatalLLMError" in said and "API key expired" in said
    assert incidents.classify(f"HostError: {said}")["provider"] == "openrouter"


def test_kranto_status_says_the_incident_on_its_first_line():
    from kranto.launcher import activity_line, incident_lines
    a = {"running": [], "waiting": [], "failing": [], "counts": {},
         "quiet": "Nothing is running.",
         "incidents": [{"title": "Your OpenRouter key is refused (expired)",
                        "words": "Your OpenRouter key was refused (expired) at 08:15 on 25 Oct: "
                                 "reading your sources stops until it is renewed in Settings › "
                                 "Watching.", "verb": "Renew the key"}]}
    [line] = incident_lines(a)
    assert line.startswith("INCIDENT   Your OpenRouter key was refused (expired)")
    assert line.endswith("(Renew the key)")
    assert activity_line(None, 8765, a).startswith(
        "blocked: Your OpenRouter key is refused (expired); Nothing is running")
    assert incident_lines(None) == [] and incident_lines({"incidents": None}) == []
