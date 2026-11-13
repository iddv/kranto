"""Tokens, not dollars, for a measured amount (the owner's ruling, 2026-10-09): runs, the
month, today, a topic, the heartbeat and an observation's call read token counts from
llm_calls; no counts means nothing shown, never dollars."""

from datetime import timedelta

from kranto import heartbeat
from kranto.store import iso, utcnow

from .test_web import rt, web  # noqa: F401 - fixtures


def call(store, run_uuid, prompt, completion, *, ago=timedelta(0), cost=0.01):
    store.insert("llm_calls", {
        "run_uuid": run_uuid, "purpose": "judge", "tier": "judge", "model": "m",
        "prompt_version": "v", "request": "{}", "response": "{}", "status": "ok",
        "attempts": 1, "prompt_tokens": prompt, "completion_tokens": completion,
        "cost_usd": cost, "created_at": iso(utcnow() - ago)})


def run(store, run_uuid):
    store.insert("runs", {"run_uuid": run_uuid, "kind": "ingest", "status": "ok",
                          "started_at": iso(utcnow()), "finished_at": iso(utcnow()),
                          "summary": '{"spend_usd": 0.02}', "error": None})


def test_runs_carry_tokens_and_old_ones_none(web, rt):  # noqa: F811
    call(rt.store, "with", 1200, 300)
    call(rt.store, "with", 800, 200)
    call(rt.store, "old", None, None)          # a record from before counts: nothing shown
    run(rt.store, "with")
    run(rt.store, "old")
    h = web.get("/api/health").json()
    by = {r["run_uuid"]: r for r in h["runs"]}
    assert by["with"]["tokens"] == {"in": 2000, "out": 500} and by["old"]["tokens"] is None
    assert h["tokens_month"]["in"] >= 2000


def test_status_has_tokens_today(web, rt):  # noqa: F811
    before = (web.get("/api/status").json()["tokens_today"] or {"in": 0, "out": 0})
    call(rt.store, None, 5000, 700)
    after = web.get("/api/status").json()["tokens_today"]
    assert after["in"] - before["in"] == 5000 and after["out"] - before["out"] == 700


def test_store_tokens_since_is_none_without_counts(rt):  # noqa: F811
    assert rt.store.tokens_since(utcnow() + timedelta(days=1)) is None
    assert rt.store.run_tokens([]) == {}


def test_heartbeat_speaks_tokens_not_dollars(rt):  # noqa: F811
    call(rt.store, None, 1_250_000, 40_000, ago=timedelta(days=1))
    beat = heartbeat.compose(rt.store, rt.cfg, utcnow())
    line = next(x for x in beat.body.splitlines() if x.startswith("Model calls:"))
    assert "tokens in" in line and "M" in line and "$" not in beat.body
    assert beat.stats["tokens_week"]["in"] >= 1_250_000


def test_compact_token_counts():
    assert [heartbeat.compact(n) for n in (0, 950, 1000, 1234, 12_345, 999_999, 1_200_000,
                                           3_000_000)] == \
        ["0", "950", "1k", "1.2k", "12k", "1M", "1.2M", "3M"]
