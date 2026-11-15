import secrets

import httpx
import pytest

from kranto.config import ModelPrice
from kranto.llm import (
    BudgetExceeded,
    FatalLLMError,
    LLMError,
    Paused,
    TransientLLMError,
    TruncatedCompletion,
    UnpricedModel,
)

from .conftest import chat_response

MSG = [{"role": "user", "content": "hi"}]


def call(client, **kw):
    return client.complete(tier="judge", purpose="judge", messages=MSG, prompt_version="t1", **kw)


def calls(store):
    return store.query("SELECT * FROM llm_calls ORDER BY id")


def test_success_records_call_with_cost(make_client, store):
    client = make_client(lambda body: chat_response("hello", cost=0.0021))
    result = call(client, run_uuid="r1")
    assert result.text == "hello"
    assert result.cost_usd == pytest.approx(0.0021)
    [row] = calls(store)
    assert row["status"] == "ok"
    assert row["cost_usd"] == pytest.approx(0.0021)
    assert row["run_uuid"] == "r1"
    assert row["response"] and "hello" in row["response"]
    assert client.fake.requests[0]["usage"] == {"include": True}
    assert client.fake.requests[0]["model"] == "judge-model"


@pytest.mark.parametrize("status", [401, 402, 403, 404])
def test_auth_payment_and_model_errors_are_fatal_and_not_retried(make_client, store, status):
    client = make_client(lambda body: httpx.Response(status, json={"error": {"message": "no"}}))
    with pytest.raises(FatalLLMError) as info:
        call(client)
    assert info.value.status == status
    assert len(client.fake.requests) == 1
    [row] = calls(store)
    assert row["status"] == "error"
    assert row["http_status"] == status
    assert row["cost_usd"] == 0


def test_rate_limit_is_retried_then_succeeds(make_client, store):
    sleeps: list[float] = []
    replies = iter([httpx.Response(429), httpx.Response(503), chat_response("ok")])
    client = make_client(lambda body: next(replies), sleeps=sleeps)
    assert call(client).text == "ok"
    assert len(client.fake.requests) == 3
    assert len(sleeps) == 2
    [row] = calls(store)
    assert row["attempts"] == 3


def test_retry_after_header_is_honoured(make_client):
    sleeps: list[float] = []
    replies = iter([httpx.Response(429, headers={"retry-after": "7"}), chat_response("ok")])
    client = make_client(lambda body: next(replies), sleeps=sleeps)
    call(client)
    assert sleeps == [7.0]


def test_transient_errors_give_up_after_max_retries(make_client, store):
    client = make_client(lambda body: httpx.Response(500), max_retries=2)
    with pytest.raises(TransientLLMError):
        call(client)
    assert len(client.fake.requests) == 3
    [row] = calls(store)
    assert row["status"] == "error"
    assert row["attempts"] == 3


def test_connection_errors_are_transient(make_client):
    def boom(body):
        raise httpx.ConnectError("refused")

    client = make_client(boom, max_retries=1)
    with pytest.raises(TransientLLMError):
        call(client)


def test_other_client_errors_are_item_level(make_client):
    client = make_client(lambda body: httpx.Response(400, json={"error": {"message": "too long"}}))
    with pytest.raises(LLMError) as info:
        call(client)
    assert not isinstance(info.value, (FatalLLMError, TransientLLMError))
    assert "too long" in str(info.value)
    assert len(client.fake.requests) == 1


def test_pause_blocks_before_any_request(make_client, store):
    client = make_client(lambda body: chat_response("x"))
    store.pause("holiday")
    with pytest.raises(Paused, match="holiday"):
        call(client)
    assert client.fake.requests == []
    assert calls(store) == []


def test_budget_is_checked_before_every_call(make_client, store):
    client = make_client(lambda body: chat_response("x", cost=0.6), budget=1.0)
    call(client)
    call(client)
    with pytest.raises(BudgetExceeded):
        call(client)
    assert len(client.fake.requests) == 2


def test_missing_api_key_is_fatal_without_request(make_client):
    client = make_client(lambda body: chat_response("x"), api_key="")
    with pytest.raises(FatalLLMError, match="TEST_KEY"):
        call(client)
    assert client.fake.requests == []


@pytest.mark.parametrize("cost", [None, "abc", -5, "nan"])
def test_unusable_provider_cost_is_refused_loudly_and_still_counted(make_client, store, cost):
    """#43: a missing cost was stored as NULL and counted as $0; a negative cost
    took month spend below zero and switched the budget off."""
    client = make_client(lambda body: chat_response("x", cost=cost, prompt=100, completion=20))
    with pytest.raises(UnpricedModel, match="conservative estimate"):
        call(client)
    [row] = calls(store)
    expected = (100 * 15.0 + 20 * 75.0) / 1_000_000
    assert row["cost_usd"] == pytest.approx(expected)
    assert "conservative estimate" in row["error"]
    assert store.month_spend() == pytest.approx(expected)


def test_table_pricing_refuses_unknown_model_before_request(make_client):
    client = make_client(lambda body: chat_response("x"), cost_source="table", pricing={})
    with pytest.raises(UnpricedModel):
        call(client)
    assert client.fake.requests == []


def test_table_pricing_computes_cost(make_client):
    client = make_client(
        lambda body: chat_response("x", cost=None, prompt=1_000_000, completion=200_000),
        cost_source="table",
        pricing={"judge-model": ModelPrice(1.0, 5.0)},
    )
    assert call(client).cost_usd == pytest.approx(2.0)
    assert "usage" not in client.fake.requests[0]


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"nope": True}),
    httpx.Response(200, text="<html>Bad gateway</html>"),
])
def test_a_reply_that_is_not_a_completion_is_retried_then_transient(make_client, store, response):
    """#43: these were item-level errors, so a gateway error page consumed every item."""
    client = make_client(lambda body: response)
    with pytest.raises(TransientLLMError, match="malformed response"):
        call(client)
    assert len(client.fake.requests) == 4  # max_retries 3
    [row] = calls(store)
    assert row["status"] == "error"


def test_api_key_is_scrubbed_from_stored_and_raised_errors(make_client, store):
    key = "sk-or-v1-canary-" + secrets.token_hex(5)  # built at runtime: no key-shaped literal
    client = make_client(lambda body: httpx.Response(
        401, json={"error": {"message": f"invalid key Bearer {key}"}}), api_key=key)
    with pytest.raises(FatalLLMError) as exc:
        call(client)
    assert key not in str(exc.value) and "[redacted]" in str(exc.value)
    assert key not in calls(store)[0]["error"]


def test_unknown_tier(make_client):
    client = make_client(lambda body: chat_response("x"))
    with pytest.raises(LLMError, match="tier"):
        client.complete(tier="nope", purpose="p", messages=MSG, prompt_version="v")


@pytest.mark.parametrize("text, finish_reason, expect", [
    ('{"partial": ', "length", "cut off at max_tokens=50"),
    (None, "length", "cut off at max_tokens=50"),
    (None, "stop", "no content"),
    ("   ", None, "no content"),
])
def test_truncated_or_empty_replies_are_errors_but_still_cost(
        make_client, store, text, finish_reason, expect):
    """#38: a reasoning model spent the whole budget and the partial or empty
    reply was parsed as an answer, so the scout and idea cards failed silently."""
    client = make_client(lambda body: chat_response(text, cost=0.02, completion=50,
                                                    finish_reason=finish_reason))
    with pytest.raises(TruncatedCompletion, match=expect) as exc:
        call(client, max_tokens=50)
    assert isinstance(exc.value, LLMError) and exc.value.call_id
    [row] = calls(store)
    assert row["status"] == "error" and expect in row["error"]
    assert row["cost_usd"] == 0.02 and row["response"]
    assert store.month_spend() == pytest.approx(0.02)


def test_complete_reply_with_stop_is_not_truncated(make_client, store):
    client = make_client(lambda body: chat_response("done", finish_reason="stop"))
    assert call(client).text == "done"
    assert calls(store)[0]["status"] == "ok"
