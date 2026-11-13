"""What a paid API other than a model costs: the ``api_spend`` table
(migration 26), X's list prices, and the full text behind an X post that links off X."""

import sqlite3

import pytest

from kranto import pricing
from kranto.sources import Item
from kranto.sources.fulltext import full_text_target
from kranto.store import Store, iso, utcnow


def test_migration_26_adds_an_append_only_api_spend_table(tmp_path):
    store = Store.open(tmp_path / "kranto.db")
    try:
        assert 26 in store.applied_migrations()
        assert "api_spend" in store.append_only_tables()
        row = store.insert("api_spend", {"provider": "x", "source_id": None, "run_uuid": None,
                                         "kind": "post_read", "count": 20,
                                         "usd": pricing.x_cost("post_read", 20),
                                         "created_at": iso(utcnow())})
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query("UPDATE api_spend SET usd = 0 WHERE id = ?", (row,))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query("DELETE FROM api_spend WHERE id = ?", (row,))
    finally:
        store.close()


def test_x_prices_are_per_resource_and_owned_reads_are_cheaper():
    assert pricing.x_cost("post_read", 20) == pytest.approx(0.10)
    assert pricing.x_cost("owned_read", 20) == pytest.approx(0.02)
    assert pricing.x_cost("user_read", 1) == pytest.approx(0.01)
    assert pricing.x_cost("list_read", 3) == pytest.approx(0.015)
    # an unknown line is priced as a post read, never as free
    assert pricing.x_cost("something_new", 2) == pytest.approx(0.01)
    assert pricing.x_cost("post_read", -5) == 0
    assert pricing.X_PRICES_AS_OF == "2026-10-17"


def test_an_x_post_that_links_off_x_has_its_article_fetched():
    linked = Item(id="1", title="A new paper", body="A new paper on CRDTs",
                  url="https://x.com/i/status/1", link="https://example.org/paper")
    assert full_text_target("x", linked) == "https://example.org/paper"
    own = Item(id="2", title="Just a thought", body="Just a thought",
               url="https://x.com/i/status/2")
    assert full_text_target("x", own) is None
