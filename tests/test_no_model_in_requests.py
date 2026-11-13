"""The owner's rule (2026-10-11): no request the UI serves waits on a model call. A step that
needs one (the scout, an explanation) runs in the background and the page polls its state.

The fake model here blocks until the test releases it: a route that waited on it would not
answer within the bound."""
import json
import threading
import time
from urllib.parse import unquote_plus

import httpx
import pytest

from kranto import library
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.sources import HTTP
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client
from .test_scout import site
from .test_web import rt, web  # noqa: F401 - fixtures

BOUND_S = 5.0


@pytest.fixture
def blocked(tmp_path, store, embedder, make_client):
    gate, called = threading.Event(), []
    proposals = {"sources": [{"kind": "rss", "value": "https://ex.com/good", "why": "on topic"}]}

    def model(body):
        called.append(time.time())
        assert gate.wait(60), "the test never released the model"
        return chat_response(json.dumps(proposals))

    http = HTTP(transport=httpx.MockTransport(site), resolver=lambda h: ["93.184.216.34"])
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt_ = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(model), http=http)
    with web_client(create_app(rt_)) as web_:
        try:
            yield rt_, web_, gate, called
        finally:
            gate.set()


def timed(fn, *a, **kw):
    t0 = time.time()
    r = fn(*a, **kw)
    return r, time.time() - t0


def test_the_scout_never_holds_a_request(blocked):
    rt_, web_, gate, called = blocked
    r, s = timed(web_.post, "/api/topics", json={"name": "solar", "description":
                                                 "solar microgrid battery storage",
                                                 "scout": True})
    assert r.status_code == 200 and s < BOUND_S, (r.text, s)
    tid = r.json()["id"]
    deadline = time.time() + BOUND_S
    while not called and time.time() < deadline:       # the model is called, in the background
        time.sleep(0.01)
    assert called
    job = web_.get(f"/api/topics/{tid}/scout").json()["job"]
    assert job["state"] == "running" and job["elapsed_s"] >= 0
    # a second press while it runs is the same job: no second paid call
    r, s = timed(web_.post, f"/api/topics/{tid}/scout", json={})
    assert r.status_code == 202 and s < BOUND_S and r.json()["job"]["state"] == "running"
    # the form door too
    r, s = timed(web_.post, f"/topics/{tid}/scout", data={}, follow_redirects=False)
    assert r.status_code == 303 and s < BOUND_S
    assert "The scout is running" in unquote_plus(r.headers["location"])
    assert len(called) == 1
    gate.set()
    deadline = time.time() + 30
    while (job := web_.get(f"/api/topics/{tid}/scout").json()["job"])["state"] == "running":
        assert time.time() < deadline
        time.sleep(0.05)
    assert job["state"] == "done" and job["result"]["message"].startswith("Scout proposed 1")
    assert job["result"]["proposals"]
    assert len(library.list_sources(rt_.store)) >= 1


def test_explain_never_holds_a_request(rt, make_client):  # noqa: F811
    gate, called = threading.Event(), []

    def model(body):
        called.append(1)
        assert gate.wait(60)
        return chat_response("[1] and [2] both describe the same thing.")

    rt.llm = make_client(model)
    try:
        with web_client(create_app(rt)) as web_:
            r, s = timed(web_.post, "/api/explain", json={"observation_id": 1})
            if r.status_code == 400:                   # too few neighbours in this library
                pytest.skip(r.json()["error"])
            assert r.status_code == 202 and s < BOUND_S, (r.text, s)
            r, s = timed(web_.post, "/obs/1/explain")
            assert s < BOUND_S
            gate.set()
            deadline = time.time() + 30
            while (job := web_.get("/api/explain", params={"observation_id": 1})
                   .json()["job"])["state"] == "running":
                assert time.time() < deadline
                time.sleep(0.05)
            assert job["state"] in ("done", "failed")
            assert len(called) == 1
    finally:
        gate.set()
