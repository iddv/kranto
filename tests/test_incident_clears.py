"""An incident goes when it is fixed (the page #488).

Live, 28 Oct: one ``ideas`` run got OpenRouter's 402 "would exceed your available credits given
your current in-flight requests" at 20:44. Kranto said "Your OpenRouter key is refused (no
credit) … Stopped until it is renewed" and kept saying it through 467 good calls, a passing key
test and three updates, each of which logged it again as a new error; nothing could put it away.
Here: a later good call to the provider or a passing key test clears it, the owner can dismiss
any incident, that 402 is low credit (retried, never "stopped"), a 402 of an empty balance is
out of credit, and a stored failure is not logged again by a new process. A prepared item's
waiting run goes when the item is approved. Nothing touches a model or the network."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx
import pytest

from kranto import activity, rowsafe, setup
from kranto.activity import incidents
from kranto.activity import read as activity_read
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

SQUEEZE = ("This request would exceed your available credits given your current in-flight "
           "requests. Retry after in-flight requests settle, or add credits.")
LIVE_402 = f"HTTP 402 from https://openrouter.ai/api/v1: {SQUEEZE}"
EMPTY_402 = "HTTP 402 from https://openrouter.ai/api/v1: Insufficient credits"
EXPIRED = "HTTP 401 from https://openrouter.ai/api/v1: API key expired."


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


def _run(store, kind, status, error=None, at=None, summary=None):
    at = at or utcnow()
    with activity.run(store, kind) as r:
        store.insert("runs", {"run_uuid": r.uuid, "kind": kind, "status": status,
                              "started_at": iso(at), "finished_at": iso(at),
                              "summary": json.dumps(summary or {}), "error": error})
    return r.uuid


def _call(store, provider, status="ok", at=None):
    store.insert("llm_calls", {"purpose": "t", "tier": "cheap", "model": "m", "prompt_version": "1",
                               "request": "{}", "status": status, "attempts": 1,
                               "provider": provider, "created_at": iso(at or utcnow())})


def _reader(store):
    return activity_read.Reader(store)


@pytest.mark.parametrize("error, cause", [
    (LIVE_402, "low credit"),
    (f"gave up after 3 attempts at https://openrouter.ai/api/v1: {SQUEEZE}", "low credit"),
    (EMPTY_402, "out of credit"),
    ("HTTP 402 from https://openrouter.ai/api/v1: Payment required", "out of credit"),
    (EXPIRED, "expired"),
    ("HTTP 403 from https://openrouter.ai/api/v1: forbidden", "refused"),
])
def test_a_402_is_low_credit_or_out_of_credit_and_a_401_is_a_refused_key(error, cause):
    got = incidents.classify(error)
    assert got["provider"] == "openrouter" and got["cause"] == cause


def test_live_402_is_low_credit_that_waits_never_a_refused_key_that_stops(store):
    _run(store, "ideas", "failed", LIVE_402, at=utcnow() - timedelta(hours=1))
    [inc] = _reader(store).incidents()
    assert inc["cause"] == "low credit" and inc["blocking"] is False and inc["tone"] == "amber"
    assert inc["title"] == "OpenRouter credit is low: calls wait and try again"
    assert "refused" not in inc["words"] and "Stopped" not in inc["words"]
    assert "try again on their next run" in inc["words"]
    assert inc["verb"] == "Check the key" and inc["dismiss"] is True
    assert "goes by itself when a call to OpenRouter works" in inc["clears"]
    assert [r["kind"] for r in inc["runs"]] == ["ideas"]


def test_a_later_good_call_to_the_same_provider_clears_it_whatever_kind_made_it(store):
    t = utcnow() - timedelta(hours=10)
    _run(store, "ideas", "failed", LIVE_402, at=t)
    _call(store, "openrouter", "ok", at=t - timedelta(minutes=5))       # before: holds
    _call(store, "anthropic", "ok", at=t + timedelta(hours=1))           # another provider
    _call(store, "openrouter", "error", at=t + timedelta(hours=1))       # a failed call
    assert [i["id"] for i in _reader(store).incidents()] == ["auth:openrouter"]
    _call(store, "openrouter", "ok", at=t + timedelta(hours=3))          # ingest's 262 calls
    assert _reader(store).incidents() == []
    # a new failure after it raises it again, from that failure
    _run(store, "ingest", "failed", EXPIRED, at=t + timedelta(hours=4))
    [inc] = _reader(store).incidents()
    assert inc["since"] == iso(t + timedelta(hours=4)) and inc["cause"] == "expired"
    assert inc["blocking"] is True and inc["verb"] == "Renew the key"


def test_a_passing_key_test_clears_it(store):
    _run(store, "ideas", "failed", EMPTY_402, at=utcnow() - timedelta(hours=1))
    [inc] = _reader(store).incidents()
    assert inc["title"] == "Your OpenRouter key is out of credit" and inc["blocking"] is True
    setup.record_key_test(store, setup.KeyTest(False, "openrouter.ai refused the key (HTTP 401)"),
                          "https://openrouter.ai/api/v1")
    assert len(_reader(store).incidents()) == 1                          # a failing test: holds
    setup.record_key_test(store, setup.KeyTest(True, "OpenRouter accepted the key"),
                          "https://example.com/v1")
    assert len(_reader(store).incidents()) == 1                          # another endpoint
    setup.record_key_test(store, setup.KeyTest(True, "OpenRouter accepted the key"),
                          "https://openrouter.ai/api/v1")
    assert _reader(store).incidents() == []


def test_the_owner_dismisses_an_incident_until_it_happens_again(rt):  # noqa: F811
    _run(rt.store, "ideas", "failed", EXPIRED, at=utcnow() - timedelta(hours=1))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        assert web.get("/api/activity").json()["counts"]["incidents"] == 1
        assert web.post("/api/activity/dismiss", json={"incident": "auth:xai"}).status_code == 404
        res = web.post("/api/activity/dismiss", json={"incident": "auth:openrouter"})
        assert res.status_code == 200 and res.json() == {"ok": True, "incident": "auth:openrouter"}
        assert web.get("/api/activity").json()["incidents"] == []
        assert web.post("/api/activity/dismiss", json={}).status_code == 400
    _run(rt.store, "ingest", "failed", EXPIRED, at=utcnow() + timedelta(seconds=2))
    assert [i["id"] for i in _reader(rt.store).incidents()] == ["auth:openrouter"]


def test_a_failure_kept_before_a_restart_is_not_logged_again(tmp_path, monkeypatch, caplog):
    rowsafe.configure(tmp_path)
    monkeypatch.setattr(rowsafe, "_seen", {})
    with caplog.at_level(logging.WARNING, logger=rowsafe.log.name):
        first = rowsafe.note_failure("auth:openrouter", LIVE_402, where="activity:auth:openrouter")
        rowsafe.note_failure("auth:openrouter", LIVE_402, where="activity:auth:openrouter")
    kept = (tmp_path / rowsafe.FILE).read_text().splitlines()
    assert len(kept) == 1 and len(caplog.records) == 1
    # a restart (an update): the process has seen nothing, the file keeps it
    monkeypatch.setattr(rowsafe, "_seen", {})
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=rowsafe.log.name):
        again = rowsafe.note_failure("auth:openrouter", LIVE_402, where="activity:auth:openrouter")
    assert again["id"] == first["id"] and again["at"] == first["at"]
    assert (tmp_path / rowsafe.FILE).read_text().splitlines() == kept
    assert caplog.records == []
    rowsafe.configure(None)


def test_the_in_flight_402_is_tried_again_by_the_client():
    from kranto.providers.base import ProviderError
    from kranto.providers.openai_compat import OpenAICompatProvider
    answers = iter([httpx.Response(402, json={"error": {"message": SQUEEZE}}),
                    httpx.Response(402, json={"error": {"message": "Insufficient credits"}})])
    http = httpx.Client(transport=httpx.MockTransport(lambda req: next(answers)))
    p = OpenAICompatProvider(name="openrouter", base_url="https://openrouter.ai/api/v1",
                             key_env="X", cost_source="provider", key=lambda: "k", http=http)
    with pytest.raises(ProviderError) as squeeze:
        p.send({"model": "m", "messages": []})
    assert squeeze.value.kind == "transient" and squeeze.value.status == 402
    with pytest.raises(ProviderError) as empty:
        p.send({"model": "m", "messages": []})
    assert empty.value.kind == "fatal"


def test_a_prepared_items_waiting_run_goes_when_it_is_approved_or_dismissed(store):
    def prepared(state, pid="p1"):
        store.insert("prepared", {"prepared_uuid": pid, "state": state, "verb": "b.factory_issue",
                                  "fields": "{}", "created_at": iso(utcnow()),
                                  "expires_at": iso(utcnow() + timedelta(days=7))})
    with activity.run(store, "verb", title="Prepared: File a Kranto issue") as r:
        prepared("open")
        r.waiting("File a Kranto issue: prepared by Claude Code", {"verb": "File issue",
                                                                  "href": "#/needs"})
        store.insert("runs", {"run_uuid": r.uuid, "kind": "verb", "status": "ok",
                              "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                              "summary": json.dumps({"verb": "b.factory_issue",
                                                     "prepared": "p1"}), "error": None})
    activity.flush()
    assert [w["kind"] for w in _reader(store).waiting()] == ["verb"]
    prepared("pressed")
    assert _reader(store).waiting() == []
    # the words such a run kept before this release are said as they are now
    from kranto.activity import words as W
    assert (
        W.plain("File a Kranto issue: prepared by Claude Code; waits for your press on #/needs")
        == "File a Kranto issue: prepared by Claude Code; waits for your approval on #/needs"
    )
