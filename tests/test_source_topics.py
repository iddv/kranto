"""A source and the topics it feeds (track): a row names its topics with
their kind and the topic it was found for; its page counts each topic's watched sources and
kept items this month, and what judging its own items cost; a removed source says what it
still feeds; an observation says the topics its source feeds."""

import pytest

from kranto import library, source_health
from kranto.store import iso, utcnow
from kranto.web import types as T

from .test_web import rt, web  # noqa: F401 - fixtures
from .test_web_types import problems


def _seen(store, source_id, n, kept, cost=0.002, tokens=(100, 20)):
    now = iso(utcnow())
    for i in range(n):
        call = store.insert("llm_calls", dict(
            purpose="judge", tier="judge", model="m", prompt_version="v", request="{}",
            status="ok", attempts=1, cost_usd=cost, prompt_tokens=tokens[0],
            completion_tokens=tokens[1], created_at=now))
        store.insert("items_seen", dict(
            source_id=source_id, item_id=f"t{source_id}-{i}",
            outcome="contributed" if i < kept else "gated", llm_call_id=call, created_at=now))


@pytest.fixture
def shared(rt):  # noqa: F811
    """energy (the fixture's) and a project topic share one source; a scout's proposal for
    energy waits."""
    [energy] = library.active_topics(rt.store)
    [own] = [s.id for s in library.list_sources(rt.store)]
    proj = library.add_topic(rt.store, rt.embedder, "Kiosk (project)", "a kiosk",
                             kind="project", ref="project:kiosk")
    both = library.add_source(rt.store, "rss", {"url": "https://ex.com/both"}, label="Both")
    library.link_topic_source(rt.store, energy.id, both)
    library.link_topic_source(rt.store, proj, both)
    prop = library.add_source(rt.store, "rss", {"url": "https://ex.com/p"}, label="Proposed",
                              origin="scout", status="proposed",
                              validation={"topic_id": proj, "role": "core", "why": "close"})
    return {"energy": energy.id, "proj": proj, "own": own, "both": both, "prop": prop}


def test_a_row_names_its_topics_their_kind_and_the_topic_it_was_found_for(web, rt, shared):  # noqa: F811
    data = web.get("/api/sources").json()
    assert problems(data, T.Sources) == []
    rows = {s["id"]: s for s in data["sources"]}
    assert rows[shared["both"]]["topics"] == [
        {"id": shared["energy"], "name": "energy", "kind": "user"},
        {"id": shared["proj"], "name": "Kiosk (project)", "kind": "project"}]
    # added by hand: the first topic it was added to; proposed: the topic the scout named
    assert rows[shared["both"]]["found_for"]["id"] == shared["energy"]
    assert rows[shared["prop"]]["found_for"] == {"id": shared["proj"], "name": "Kiosk (project)",
                                                 "kind": "project"}
    # a paused topic keeps its name on the rows (it was "topic N" before)
    library.set_topic_status(rt.store, shared["energy"], "paused", "test")
    rows = {s["id"]: s for s in web.get("/api/sources").json()["sources"]}
    assert rows[shared["own"]]["topics"][0]["name"] == "energy"


def test_a_sources_page_counts_each_topic_it_feeds_and_its_spend(web, rt, shared):  # noqa: F811
    _seen(rt.store, shared["both"], 5, kept=3)
    _seen(rt.store, shared["own"], 4, kept=1, cost=0.001)
    page = web.get(f"/api/sources/{shared['both']}").json()
    assert problems(page, T.SourcePage) == []
    facts = {f["id"]: f for f in page["topic_facts"]}
    # energy: the fixture's source (its four observations were kept items too, and 1 more)
    # and the shared one's 3, this month
    mine = web.get(f"/api/sources/{shared['own']}").json()["kept_month"]
    assert mine == 4 + 1
    energy, proj = facts[shared["energy"]], facts[shared["proj"]]
    assert (energy["sources"], energy["kept_month"]) == (2, mine + 3)
    assert (proj["sources"], proj["kept_month"]) == (1, 3)
    # builds off (absent means off,.1): a project's topic is listed as paused
    assert proj["kind"] == "project" and proj["status"] == "paused"
    assert page["kept_month"] == 3
    assert page["spend_month"] == {"usd": pytest.approx(5 * 0.002),
                                   "tokens": {"in": 500, "out": 100}}
    # a topic's spend is the sum of its sources' (no call shared between them here)
    topic = web.get(f"/api/topics/{shared['energy']}").json()
    own = web.get(f"/api/sources/{shared['own']}").json()["spend_month"]
    assert topic["spend_month_usd"] == pytest.approx(page["spend_month"]["usd"] + own["usd"])
    assert topic["tokens_month"]["in"] == 500 + own["tokens"]["in"]
    # nothing judged: no tokens, no cost
    quiet = web.get(f"/api/sources/{shared['prop']}").json()
    assert quiet["spend_month"] == {"usd": 0.0, "tokens": None} and quiet["topic_facts"] == []


def test_model_spend_counts_a_shared_screening_call_once(rt, shared):  # noqa: F811
    # the fixture's observations were judged by calls of their own: counted apart
    base = source_health.model_spend(rt.store, [shared["own"]])[0]
    now = iso(utcnow())
    call = rt.store.insert("llm_calls", dict(
        purpose="screen", tier="screen", model="m", prompt_version="v", request="{}",
        status="ok", attempts=1, cost_usd=0.01, prompt_tokens=10, completion_tokens=1,
        created_at=now))
    for sid in (shared["own"], shared["both"]):
        rt.store.insert("items_seen", dict(source_id=sid, item_id=f"x{sid}", outcome="gated",
                                           screen_call_id=call, created_at=now))
    usd, _ = source_health.model_spend(rt.store, [shared["own"], shared["both"]])
    assert usd == pytest.approx(base + 0.01)
    assert source_health.model_spend(rt.store, [shared["both"]]) == (
        pytest.approx(0.01), {"in": 10, "out": 1})
    assert source_health.model_spend(rt.store, [shared["own"]])[0] == pytest.approx(base + 0.01)
    assert source_health.model_spend(rt.store, []) == (0.0, None)


def test_an_observation_says_the_topics_its_source_feeds(web, rt, shared):  # noqa: F811
    obs = rt.store.query_one("SELECT id, source_id FROM observations LIMIT 1")
    page = web.get(f"/api/observations/{obs['id']}").json()
    assert problems(page, T.ObservationPage) == []
    assert page["topics"] == [{"id": shared["energy"], "name": "energy", "kind": "user"}]
    library.link_topic_source(rt.store, shared["proj"], obs["source_id"])
    page = web.get(f"/api/observations/{obs['id']}").json()
    assert [t["name"] for t in page["topics"]] == ["energy", "Kiosk (project)"]
