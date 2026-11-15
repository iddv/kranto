"""The server's runs for the page's agent traces: a run with its model calls (request and
response where retention kept them, said when it did not), a cub's host calls (the op, never a
payload) and its events; the owner's only, as a trace's reads are."""

import json

from kranto import tokens
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import web_client
from .test_auth import BASE, bare, runtime

UUID = "0f9e8d7c-run-1"


def seed(store) -> None:
    now = iso(utcnow())
    store.insert("runs", {"run_uuid": UUID, "kind": "ideas", "status": "ok", "started_at": now,
                          "finished_at": now, "summary": "3 cards", "error": None})
    for i, (req, resp) in enumerate(((json.dumps({"messages": ["judge this"]}), "{\"keep\": 1}"),
                                     ("explain", "because"), ("", None))):
        store.insert("llm_calls", {"run_uuid": UUID, "purpose": f"p{i}", "tier": "default",
                                   "model": "m", "prompt_version": "v1", "request": req,
                                   "response": resp, "status": "ok", "attempts": 1,
                                   "prompt_tokens": 10, "completion_tokens": 5,
                                   "cost_usd": 0.01, "latency_ms": 900, "created_at": now})
    store.insert("cub_calls", {"cub": "invest", "service": "broker", "op": "quote",
                               "status": "ok", "run_uuid": UUID, "ms": 40, "bytes_in": 10,
                               "bytes_out": 99, "detail": "quote", "created_at": now})


def test_a_run_whole_for_the_owner(tmp_path, store, embedder, make_client):
    rt = runtime(tmp_path, store, embedder, make_client)
    seed(rt.store)
    app = create_app(rt, port=8765)
    with web_client(app, BASE) as web:
        listed = web.get("/api/runs").json()["runs"]
        assert [r["run_uuid"] for r in listed] == [UUID] and listed[0]["calls"] == 3
        assert abs(listed[0]["cost_usd"] - 0.03) < 1e-9
        one = web.get(f"/api/runs/{UUID}").json()
    assert one["run"]["kind"] == "ideas"
    assert [c["purpose"] for c in one["calls"]] == ["p0", "p1", "p2"]
    assert one["calls"][0]["response"] == "{\"keep\": 1}"
    assert one["calls"][2]["expired"] is True and "expired" not in one["calls"][0]
    assert one["cub_calls"] == [{"cub": "invest", "service": "broker", "op": "quote",
                                 "status": "ok", "ms": 40, "bytes_in": 10, "bytes_out": 99,
                                 "created_at": one["cub_calls"][0]["created_at"]}]   # no detail


def test_the_runs_are_the_owners_only(tmp_path, store, embedder, make_client):
    rt = runtime(tmp_path, store, embedder, make_client)
    seed(rt.store)
    app = create_app(rt, port=8765)
    tokens.Store().add("agent:RC")
    with bare(app) as web:
        for path in ("/api/runs", f"/api/runs/{UUID}"):
            assert web.get(path).status_code == 401, path
            r = web.get(path, headers={"authorization": "Bearer "
                                       + tokens.Store().value("agent:RC")})
            assert r.status_code == 403, path


def test_an_unknown_run(tmp_path, store, embedder, make_client):
    rt = runtime(tmp_path, store, embedder, make_client)
    app = create_app(rt, port=8765)
    with web_client(app, BASE) as web:
        assert web.get("/api/runs/nope-nope-nope").status_code == 404
        assert web.get("/api/runs/..%2f..").status_code == 404
        assert web.get("/api/runs?limit=x").status_code == 400
