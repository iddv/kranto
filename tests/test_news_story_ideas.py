"""A story's idea, chosen by rule from stored rows: a card made from the
story, else a card citing one of its observations, else a card of the theme its observations sit
in on the latest map; with none, the theme Idea from this would card, or why there is none. And
a card's "In the news": the newest story that matches it by the same rules. No model call."""

from __future__ import annotations

import json

from kranto import news_ideas as story
from kranto.features.news import api as news_api
from kranto.ideate import cards

from .test_ideate import Model, mapped  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture


def _topic(store) -> int:
    r = store.query_one("SELECT id FROM topics ORDER BY id LIMIT 1")
    if r:
        return int(r["id"])
    return store.insert("topics", {"name": "energy", "description": "d", "embedding": b"",
                                   "embedding_model": "stub",
                                   "created_at": "2026-10-01T00:00:00Z"})


def _brief(store, items: list[dict]) -> int:
    return store.insert("news_briefs", {
        "topic_id": _topic(store), "period_start": "2026-10-01T00:00:00Z",
        "period_end": "2026-10-02T00:00:00Z", "status": "ok", "items": json.dumps(items),
        "created_at": "2026-10-02T00:00:00Z"})


def _on_map(store) -> tuple[str, list[int]]:
    snap = store.query_one("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1")["id"]
    c = store.query_one("SELECT cluster, lineage_id FROM clusters WHERE snapshot_id = ? "
                        "ORDER BY size DESC LIMIT 1", (snap,))
    obs = [int(r["observation_id"]) for r in store.query(
        "SELECT observation_id FROM snapshot_points WHERE snapshot_id = ? AND cluster = ? "
        "ORDER BY observation_id", (snap, c["cluster"]))]
    return str(c["lineage_id"]), obs


def test_a_story_on_the_map_offers_its_theme_then_names_its_card(mapped, make_client):  # noqa: F811
    lin, obs = _on_map(mapped)
    bid = _brief(mapped, [{"headline": "On the map", "observation_ids": obs[:2]},
                          {"headline": "Search only", "observation_ids": []},
                          {"headline": "Not mapped yet", "observation_ids": [987654]}])
    got = story.story_ideas(mapped, bid, json.loads(mapped.query_one(
        "SELECT items FROM news_briefs WHERE id = ?", (bid,))["items"]))
    assert got["0"]["idea"] is None and got["0"]["theme"]["lineage_id"] == lin
    assert got["0"]["theme"]["size"] > 0 and got["0"]["story"] == f"brief:{bid}:1"
    assert got["1"]["theme"] is None and got["1"]["no_theme"] == story.ONLY_SEARCH
    assert got["2"]["theme"] is None and got["2"]["no_theme"] == story.NOT_ON_MAP
    # Idea from this: theme.card with the story and a hint; the run keeps the story
    report = cards.card_theme(mapped, make_client(Model(card=None)), lin,
                              hint="A kit for measuring it", story=f"brief:{bid}:1")
    assert report.status == "ok" and report.shown == 1, report.error
    [idea] = cards.list_ideas(mapped)
    assert "A kit for measuring it" in (idea["card"].why_selected or "")
    items = json.loads(mapped.query_one("SELECT items FROM news_briefs WHERE id = ?",
                                        (bid,))["items"])
    after = story.story_ideas(mapped, bid, items)
    assert after["0"]["idea"]["id"] == idea["id"] and after["0"]["idea"]["rule"] == 1
    assert after["0"]["idea"]["state"] == "waiting" and after["0"]["idea"]["more"] == 0
    assert after["2"]["idea"] is None
    # the card's own page names the story
    assert story.card_story(mapped, idea["id"]) == {
        "brief_id": bid, "n": 0, "topic_id": _topic(mapped), "headline": "On the map",
        "date": "2026-10-02"}


def test_a_card_citing_the_storys_evidence_is_rule_two(mapped, make_client):  # noqa: F811
    lin, obs = _on_map(mapped)
    cards.card_theme(mapped, make_client(Model(card=None)), lin)
    [idea] = cards.list_ideas(mapped)
    cited = [int(r["observation_id"]) for r in mapped.query(
        "SELECT observation_id FROM idea_citations WHERE idea_id = ?", (idea["id"],))]
    assert cited
    bid = _brief(mapped, [{"headline": "Cited", "observation_ids": cited[:1]},
                          {"headline": "Same theme", "observation_ids": [o for o in obs
                                                                         if o not in cited][:1]}])
    items = json.loads(mapped.query_one("SELECT items FROM news_briefs WHERE id = ?",
                                        (bid,))["items"])
    got = story.story_ideas(mapped, bid, items)
    assert got["0"]["idea"]["id"] == idea["id"] and got["0"]["idea"]["rule"] == 2
    if items[1]["observation_ids"]:
        assert got["1"]["idea"]["rule"] == 3


def test_no_map_yet_says_so(rt):  # noqa: F811
    bid = _brief(rt.store, [{"headline": "h", "observation_ids": [1]}])
    got = story.story_ideas(rt.store, bid, [{"headline": "h", "observation_ids": [1]}])
    assert got["0"] == {"idea": None, "theme": None, "no_theme": story.NO_MAP,
                        "story": f"brief:{bid}:1"}


def test_why_lines_that_open_kranto_on_read_plainly():
    assert news_api.plain_why("Kranto on whether cheap arms can learn.") == \
        "Whether cheap arms can learn."
    assert news_api.plain_why("It Kranto on robot costs.") == "Robot costs."
    assert news_api.plain_why("Cuts the cost of a robot arm.") == "Cuts the cost of a robot arm."
    assert news_api.plain_why(None) is None
