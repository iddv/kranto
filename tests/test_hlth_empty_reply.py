"""one empty reply never fails a run.

On live (2026-10-29 12:42) one judge call came back HTTP 200 with no content, no tokens and no
cost. The client stored a made-up $0.4379 for it and raised ``UnpricedModel``, whose advice
("set llm.cost_source to 'table'") pointed at pricing, and the whole ingest failed. The reply
was OpenRouter's ``content_filter``: a safety filter declined that one item.

Now an empty reply is retried like any transient fault and, still empty, skips its item for
the run; a refusal skips its item for good (the same text meets the same filter); a call with
no tokens and no cost is stored at $0, marked unpriced; ``UnpricedModel`` is raised only for a
reply that has tokens and no price, and says so.
"""

import httpx
import pytest

from kranto import sources
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig, ModelPrice
from kranto.llm import EmptyReply, RefusedReply, TransientLLMError, UnpricedModel

from .conftest import chat_response, is_screen, llm_config
from .test_tick import CONTRIB, FakeSource, add, ingest, items, seen


@pytest.fixture(autouse=True)
def fake_kind(monkeypatch):
    monkeypatch.setitem(sources.KINDS, "fake", FakeSource)
    FakeSource.feeds = {}


@pytest.fixture
def tick_cfg(tmp_path):
    return Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                  ingest=IngestConfig(max_items_per_source=10, prefilter_min_similarity=0.3,
                                      exploration_fraction=0.0), map=MapConfig())

MSG = [{"role": "user", "content": "hi"}]


def call(client, purpose="judge", **kw):
    return client.complete(tier="judge", purpose=purpose, messages=MSG, prompt_version="t1",
                           **kw)


def empty() -> httpx.Response:
    """A 200 with nothing in it: no content, no usage, no cost."""
    return httpx.Response(200, json={"model": "judge-model", "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": None}}]})


def refused() -> httpx.Response:
    """Live's reply at 12:42, as OpenRouter sent it (the words shortened)."""
    return httpx.Response(200, json={
        "id": "gen-1", "object": "chat.completion", "model": "anthropic/claude-haiku-5.5",
        "provider": "Claude Platform on AWS", "choices": [{
            "index": 0, "logprobs": None, "finish_reason": "content_filter",
            "native_finish_reason": "refusal",
            "message": {"role": "assistant", "content": None,
                        "refusal": "This request triggered cyber-related safeguards.",
                        "reasoning": None}}]})


def rows(store):
    return store.query("SELECT * FROM llm_calls ORDER BY id")


@pytest.mark.parametrize("purpose", ["judge", "screen", "ideas", "deepdive", "news.brief"])
def test_an_empty_reply_is_retried_like_a_transient_fault(make_client, store, purpose):
    sleeps: list[float] = []
    replies = iter([empty(), empty(), chat_response("fine")])
    client = make_client(lambda body: next(replies), sleeps=sleeps)
    assert call(client, purpose).text == "fine"
    assert len(client.fake.requests) == 3 and len(sleeps) == 2
    assert sleeps[1] > sleeps[0] >= 1.0                   # the same backoff as a 5xx
    [row] = rows(store)
    assert row["status"] == "ok" and row["attempts"] == 3


def test_still_empty_after_the_retries_is_transient_at_zero_dollars(make_client, store):
    client = make_client(lambda body: empty(), max_retries=2)
    with pytest.raises(EmptyReply) as info:
        call(client)
    assert isinstance(info.value, TransientLLMError)
    assert "sent an empty reply" in str(info.value) and "3 times" in str(info.value)
    assert "pricing" not in str(info.value) and "cost_source" not in str(info.value)
    [row] = rows(store)
    assert row["status"] == "error" and row["http_status"] == 200 and row["attempts"] == 3
    assert row["cost_usd"] == 0.0
    assert "unpriced" in row["error"] and "stored at $0" in row["error"]
    assert row["response"]                                # what came back is kept


def test_a_refusal_is_not_retried_and_says_the_filters_words(make_client, store):
    client = make_client(lambda body: refused())
    with pytest.raises(RefusedReply) as info:
        call(client)
    assert len(client.fake.requests) == 1
    assert "declined to answer" in str(info.value)
    assert "cyber-related safeguards" in str(info.value)
    [row] = rows(store)
    assert row["status"] == "error" and row["cost_usd"] == 0.0
    assert "unpriced" in row["error"] and "conservative" not in row["error"]


def test_no_tokens_and_no_cost_is_zero_and_unpriced_never_an_estimate(make_client, store):
    """A reply with content but no usage at all: $0, marked unpriced; nothing raised."""
    client = make_client(lambda body: chat_response("ok", cost=None, prompt=None,
                                                    completion=None))
    result = call(client)
    assert result.text == "ok" and result.cost_usd == 0.0
    [row] = rows(store)
    assert row["status"] == "ok" and row["cost_usd"] == 0.0
    assert row["error"].startswith("unpriced:")


def test_unpriced_model_names_the_model_and_the_real_cause(make_client, store):
    client = make_client(lambda body: chat_response("x", cost=None, prompt=1000, completion=50))
    with pytest.raises(UnpricedModel) as info:
        call(client)
    words = str(info.value)
    assert "'judge-model'" in words and "reported no cost" in words
    assert "1000 input and 50 output tokens" in words
    [row] = rows(store)
    assert row["cost_usd"] > 0                             # estimated from real tokens


def test_unpriced_from_a_table_says_the_table_has_no_price(make_client, store):
    """Tokens in, none out (a provider that counts only one side): the table cannot price it."""
    client = make_client(lambda body: chat_response("x", cost=None, prompt=1000, completion=None),
                         cost_source="table",
                         pricing={"judge-model": ModelPrice(input_per_mtok=1.0,
                                                            output_per_mtok=1.0)})
    with pytest.raises(UnpricedModel, match="'judge-model' has no price in llm.pricing"):
        call(client)


# -- the run -------------------------------------------------------------------------------


@pytest.fixture
def judge_says(make_client):
    """A client whose screen passes and whose judge answers ``reply(item text)``."""
    from .conftest import SCREEN_PASS

    def make(reply, **kw):
        def handler(body):
            if is_screen(body):
                return chat_response(SCREEN_PASS)
            return reply(body["messages"][-1]["content"])
        return make_client(handler, **kw)
    return make


def test_one_empty_judge_reply_degrades_the_run_never_fails_it(tick_cfg, store, judge_says,
                                                               embedder):
    """Live's 12:36 run, replayed: one judge call empty among good ones."""
    add(store, "a", items(3))
    client = judge_says(lambda text: empty() if "battery 1" in text else chat_response(CONTRIB),
                        max_retries=2)
    report = ingest(tick_cfg, store, client, embedder)
    assert report.status == "degraded"
    src = report.sources[0]
    assert src.empty_replies == 1 and src.llm_errors == 1
    assert seen(store) == {"item0": "contributed", "item2": "contributed"}   # item1 waits
    run = store.query_one("SELECT * FROM runs WHERE run_uuid = ?", (report.run_uuid,))
    assert run["status"] == "degraded"
    # the next run reads it again, and it is judged when the reply comes back
    client2 = judge_says(lambda text: chat_response(CONTRIB))
    assert ingest(tick_cfg, store, client2, embedder).status == "ok"
    assert seen(store)["item1"] == "contributed"


def test_a_refused_item_is_consumed_and_the_run_goes_on(tick_cfg, store, judge_says, embedder):
    add(store, "a", items(5))
    client = judge_says(lambda text: refused() if "battery" in text and "battery 4" not in text
                        else chat_response(CONTRIB))
    report = ingest(tick_cfg, store, client, embedder)
    # four refusals in a row are four items, not a broken endpoint: never "failed"
    assert report.status == "degraded"
    assert report.sources[0].refused == 4
    assert seen(store) == {"item0": "item_error", "item1": "item_error", "item2": "item_error",
                           "item3": "item_error", "item4": "contributed"}
    refusals = store.query("SELECT llm_call_id FROM items_seen WHERE outcome = 'item_error'")
    assert all(r["llm_call_id"] for r in refusals)
