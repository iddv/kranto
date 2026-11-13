"""Each idea card's prior art from live search: one search before the
card is written, the dated block in the prompt, what the card says exists checked against it,
novelty claims kept only with a recent dated result, and the sentence when there is no search.
No network, no model."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from kranto import websearch
from kranto.config import SearchConfig
from kranto.ideate import cards
from kranto.websearch import backends as b

from .fake_search import FakeSearch
from .test_ideate import Model, card_json, mapped  # noqa: F401 - fixture

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def results(fake=None, store=None, **cfg):
    fake = fake or FakeSearch()
    http = fake.http()
    s = websearch.Searcher(store, SearchConfig(**cfg), {"exa": b.Exa(http),
                                                       "github": b.GitHub(http)},
                           caller="cards", http=http)
    s.clock = lambda: NOW
    return s


def a_card(**fields):
    _, card = cards.parse_card(json.dumps({"card": {
        "title": "t", "pattern": "p", "where_now": "w", "thesis": "t",
        "evidence": [{"n": 1, "claim": "a"}], "ratings": {k: [0.5, "r"] for k in cards.RATINGS},
        **fields}}), 3)
    return card


def test_what_exists_is_checked_against_the_block_and_novelty_needs_a_recent_result():
    from kranto.store import Store
    store = Store.memory()
    found = results(store=store).search("sync engines", kind="code")
    # exa 1 is dated 2026-10-12 (recent), exa 3 2025-01-04 (old), gh 4 2026-05-02
    card = a_card(
        thesis="Teams switch sync engines often [exa 1]. Nothing does this today. It helps.",
        pattern="It works for desktop apps [exa 1].",
        where_now="No existing tool handles schema drift [exa 3]. Mobile apps now sync.",
        prior_art=[{"result": "exa 1", "what": "compares three engines"},
                   {"result": "[EXA 2]", "what": "a CRDT sync server"},
                   {"result": "exa 9", "what": "not in the block"}],
        ratings={**{k: [0.5, "r"] for k in cards.RATINGS},
                 "execution_gap": [0.7, "No one offers this yet."]})
    cards.apply_prior_art(card, found, NOW, 12)
    prior = card["prior_art"]
    assert prior["live"] and prior["backends"][0] == websearch.EXA_FREE_LABEL
    assert [e["label"] for e in prior["existing"]] == ["exa 1", "exa 2"]
    assert prior["existing"][0]["date"] == "2026-10-12"
    assert prior["hits"][0]["url"] == "https://example.dev/blog/sync-engines-2026"
    assert card["thesis"] == "Teams switch sync engines often [exa 1]. It helps."
    assert card["where_now"] == "Mobile apps now sync."
    assert card["pattern"] == "It works for desktop apps [exa 1]."
    assert card["ratings"]["execution_gap"]["reason"].startswith("(a novelty claim was removed")
    assert {d["field"] for d in card["novelty_dropped"]} == {"thesis", "where_now",
                                                              "ratings.execution_gap"}
    assert "prior_art_cited" not in card
    # a recent dated result keeps the claim
    kept = a_card(thesis="Nothing does this for mobile apps yet [exa 1].")
    cards.apply_prior_art(kept, found, NOW, 12)
    assert kept["thesis"] == "Nothing does this for mobile apps yet [exa 1]."
    store.close()


def test_with_no_search_the_card_says_so():
    none = cards.prior_art_search(None, cards.Candidate("rising", "l", 1, "w", [1], "sync"))
    text = cards.prior_art_text(none, 12)
    assert "No prior-art search ran" in text and websearch.NO_SEARCH in text
    card = a_card(thesis="Nothing does this today.")
    cards.apply_prior_art(card, none, NOW, 12)
    assert card["prior_art"]["live"] is False and card["prior_art"]["note"] == websearch.NO_SEARCH
    assert card["thesis"] == ""                       # no search: no novelty claim stands


def test_each_card_searches_its_subject_once_and_stores_the_block(mapped, make_client):  # noqa: F811
    fake = FakeSearch()
    model = Model(card=json.dumps({"card": {
        **json.loads(card_json())["card"],
        "prior_art": [{"result": "exa 1", "what": "already compares sync engines"}]}}))
    client = make_client(model)
    report = cards.generate_ideas(mapped, client, max_cards=1,
                                  searcher=results(fake, mapped))
    assert report.status == "ok", report.error
    searched = [c for c in fake.calls if c[2].get("method") == "tools/call"]
    assert len(searched) == 1 and searched[0][2]["params"]["arguments"]["query"]
    assert any(c[0] == "api.github.com" for c in fake.calls)
    prompt = client.fake.requests[0]["messages"][0]["content"]
    assert "Prior art, searched for what these observations are about" in prompt
    assert "[exa 1] 2026-10-12" in prompt and "Rules for prior art" in prompt
    [idea] = cards.list_ideas(mapped)
    prior = idea["card"].prior_art
    assert prior.live and prior.existing[0].label == "exa 1"
    rows = mapped.query("SELECT caller FROM api_spend")
    assert {r["caller"] for r in rows} == {"cards"}


def test_the_cards_switch_off_searches_nothing(mapped, make_client):  # noqa: F811
    fake = FakeSearch()
    client = make_client(Model())
    cards.generate_ideas(mapped, client, max_cards=1,
                         searcher=results(fake, mapped, callers={"cards": "off"}))
    assert fake.calls == []
    prompt = client.fake.requests[0]["messages"][0]["content"]
    assert "No prior-art search ran (live search is off for the cards" in prompt
