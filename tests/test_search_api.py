"""The command palette's search (UI-v4.md 2.4): topics, sources and observations in one list,
from the library's own search, with no model call."""

from kranto import library

from .test_web import rt, web  # noqa: F401 - fixtures


def llm_calls(store):
    return store.query_one("SELECT COUNT(*) AS n FROM llm_calls")["n"]


def test_search_returns_the_three_kinds_in_one_list(web, rt):  # noqa: F811
    library.add_source(rt.store, "rss", {"url": "https://ex.com/solar"}, label="Solar Weekly")
    before = llm_calls(rt.store)
    data = web.get("/api/search?q=solar").json()
    assert data["query"] == "solar"
    kinds = [r["kind"] for r in data["results"]]
    assert {"topic", "source", "observation"} <= set(kinds)
    # topics first, then sources, then observations
    assert kinds == sorted(kinds, key=["topic", "source", "observation"].index)
    topic = next(r for r in data["results"] if r["kind"] == "topic")
    assert topic["title"] == "energy" and topic["detail"] == "active"
    source = next(r for r in data["results"] if r["kind"] == "source")
    assert source["title"] == "Solar Weekly" and source["detail"].startswith("rss")
    obs = [r for r in data["results"] if r["kind"] == "observation"]
    assert obs[0]["title"] == "title 0" and "Energy Feed" in obs[0]["detail"]
    assert obs == sorted(obs, key=lambda r: -r["score"])
    assert llm_calls(rt.store) == before, "a search makes no model call"


def test_search_by_words_keeps_only_what_holds_them(web):  # noqa: F811
    data = web.get("/api/search?q=CRDT+sync").json()
    obs = [r for r in data["results"] if r["kind"] == "observation"]
    assert [r["title"] for r in obs] == ["title 2"]
    assert not [r for r in data["results"] if r["kind"] != "observation"]


def test_search_with_nothing_typed_and_its_guard(web):  # noqa: F811
    assert web.get("/api/search").json() == {"query": "", "results": []}
    assert web.get("/api/search?q=%20%20").json()["results"] == []
    one = web.get("/api/search?q=battery&k=1").json()["results"]
    assert len([r for r in one if r["kind"] == "observation"]) == 1
    assert web.get("/api/search?q=solar", headers={"host": "evil.example"}).status_code == 400
