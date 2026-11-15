"""A ticket names the idea card or the trend it rests on: ``because.ideas`` (card
ids) and ``because.trends`` (the radar's keys), checked like the other ids, in the core and in
the SDK's FakeHost alike."""

import pytest

from bears_cub import testing
from kranto.core import tickets

from .test_features_core import _file, ping  # noqa: F401 - fixtures (store: conftest)
from .test_ideas_api import cards  # noqa: F401 - fixture
from .test_web import rt, web  # noqa: F401 - fixtures


def test_a_cards_one_read_lists_the_tickets_that_rest_on_it(web, cards, store, ping):  # noqa: F811
    rid = _file(store, because={"ideas": [cards["new"]]})
    _file(store, fields={"target": "b", "n": 3, "ref": "demo:2"}, because={"trends": ["ai-memory"]})
    got = web.get(f"/api/ideas/{cards['new']}").json()["tickets"]
    assert [(t["id"], t["kind"], t["state"]) for t in got] == [(rid, "test.ping", "needs_confirm")]
    assert web.get(f"/api/ideas/{cards['old']}").json()["tickets"] == []
    assert "tickets" not in web.get("/api/ideas").json()["ideas"][0]       # the one read only
    assert [t["id"] for t in tickets.resting_on(store, "trends", "ai-memory")] == [rid + 1]
    with pytest.raises(ValueError):
        tickets.resting_on(store, "labels", "x")


def test_a_ticket_may_name_its_card_and_its_trend(store, ping):  # noqa: F811
    rid = _file(store, because={"ideas": [112], "trends": ["ai-memory"], "observations": [8231]})
    got = tickets.get(store, rid)["because"]
    assert got == {"ideas": [112], "trends": ["ai-memory"], "observations": [8231]}


@pytest.mark.parametrize("because, words", [
    ({"ideas": ["112"]}, "because.ideas is a list of at most 50 ids"),
    ({"ideas": [True]}, "because.ideas is a list of at most 50 ids"),
    ({"ideas": list(range(51))}, "because.ideas is a list of at most 50 ids"),
    ({"trends": ["AI Memory"]}, "because.trends is a list of at most 50 trend keys"),
    ({"trends": "ai-memory"}, "because.trends is a list of at most 50 trend keys"),
    ({"trends": [7]}, "because.trends is a list of at most 50 trend keys"),
])
def test_a_wrong_card_or_trend_is_refused(store, ping, because, words):  # noqa: F811
    with pytest.raises(tickets.TicketError, match=words):
        _file(store, because=because)
    assert testing._because_problem(because) == words


def test_the_sdk_and_the_core_agree_on_a_trend_key():
    assert testing._because_problem({"ideas": [1], "trends": ["ai-memory"]}) is None
    assert tickets.TREND_KEY.fullmatch("ai-memory")
    assert not tickets.TREND_KEY.fullmatch("AI Memory")
