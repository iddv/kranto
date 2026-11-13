"""A card knows its topic and its citations (L2, migration 35): the writer stores
``idea_topics`` and ``idea_citations`` with the card; a card whose evidence is the archive has
no topic; a card's topic is never a project topic; ``/api/ideas?topic=`` filters in SQL;
``/api/observations/<id>`` names the cards and briefs that cite it, also once the observation
is compacted; migration 35 fills both tables for cards written before it."""

import json
import sqlite3

import pytest

from kranto import feedback, library
from kranto import store as store_mod
from kranto.ideate import cards as card_mod
from kranto.store import Store

from .test_ideas_api import add_card, cards, obs_ids, old_card  # noqa: F401 - fixtures
from .test_web import rt, web  # noqa: F401 - fixtures


def test_the_writer_stores_the_topic_and_the_citations(rt, cards):  # noqa: F811
    store = rt.store
    row = store.query_one("SELECT * FROM idea_topics WHERE idea_id = ?", (cards["new"],))
    energy = store.query_one("SELECT id FROM topics WHERE name = 'energy'")["id"]
    assert row["topic_id"] == energy
    assert json.loads(row["shares"]) == [{"id": energy, "name": "energy", "kind": "user", "n": 1,
                                         "share": 1.0}]
    cites = [dict(r) for r in store.query(
        "SELECT observation_id, n, role FROM idea_citations WHERE idea_id = ? ORDER BY id",
        (cards["new"],))]
    oid = cards["oids"][2]
    assert cites == [{"observation_id": oid, "n": 1, "role": "evidence"},
                     {"observation_id": oid, "n": 1, "role": "demand"}]
    assert card_mod.cited_by(store, oid) == [cards["new"]]


def test_archive_evidence_has_no_topic_and_a_project_topic_is_never_the_cards(rt, cards):  # noqa: F811
    store = rt.store
    archive = old_card(store, cards["oids"][:1])
    archive["evidence"][0].update(observation_id=987654, source="Parallax archive")
    lone = add_card(store, "From the archive", archive)
    got = card_mod.card_topics(store, [lone])[lone]
    assert got == {"topic_id": None, "shares": []}
    # a project topic over the same source: in the shares, after the user topic, never the topic
    proj = library.add_topic(store, rt.embedder, "Kiosk (project)", "what makes Kiosk better",
                             kind="project", ref="project:kiosk")
    src = store.query_one("SELECT id FROM sources WHERE label = 'Energy Feed'")["id"]
    library.link_topic_source(store, proj, src)
    both = add_card(store, "Swap ledger two", old_card(store, cards["oids"][:2]))
    t = card_mod.card_topics(store, [both])[both]
    assert [s.kind for s in t["shares"]] == ["user", "project"]
    assert t["topic_id"] == t["shares"][0].id != proj
    only = library.add_source(store, "rss", {"url": "https://ex.com/kiosk"}, label="Kiosk feed")
    library.link_topic_source(store, proj, only)
    card = old_card(store, cards["oids"][:1])
    card["evidence"][0].update(observation_id=987655, source="Kiosk feed")
    pcard = add_card(store, "Project only", card)
    assert card_mod.card_topics(store, [pcard])[pcard]["topic_id"] is None


def test_the_api_reads_the_stored_topic_and_filters_in_sql(web, rt, cards):  # noqa: F811
    energy = rt.store.query_one("SELECT id FROM topics WHERE name = 'energy'")["id"]
    card = web.get(f"/api/ideas/{cards['new']}").json()
    assert card["topic"] == {"id": energy, "name": "energy", "kind": "user", "n": 1, "share": 1.0}
    listed = web.get(f"/api/ideas?topic={energy}").json()
    assert sorted(i["id"] for i in listed["ideas"]) == sorted([cards["old"], cards["new"],
                                                             cards["hidden"]])
    assert web.get("/api/ideas?topic=energy").json()["count"] == listed["count"]
    assert web.get("/api/ideas?topic=no-such-topic").json()["count"] == 0
    # an edited topic (a newer row superseding it): the card shows the name it has now
    rt.store.insert("topics", {"name": "solar", "description": "d", "embedding": b"",
                               "embedding_model": "stub", "supersedes": energy,
                               "created_at": "2026-10-03T00:00:00Z"})
    assert web.get(f"/api/ideas/{cards['new']}").json()["topic"]["name"] == "solar"


def test_an_observation_says_what_cites_it_also_once_compacted(web, rt, cards):  # noqa: F811
    store = rt.store
    oid = cards["oids"][0]
    topic = store.query_one("SELECT id FROM topics WHERE name = 'energy'")["id"]
    store.insert("news_briefs", {"topic_id": topic, "period_start": "2026-10-01T00:00:00Z",
                                 "period_end": "2026-10-02T00:00:00Z", "status": "ok",
                                 "items": json.dumps([{"headline": "h", "observation_ids": [oid]},
                                                      "not an item"]),
                                 "created_at": "2026-10-02T00:00:00Z"})
    got = web.get(f"/api/observations/{oid}").json()["cited_by"]
    assert got["ideas"] == [cards["old"]] and len(got["briefs"]) == 1
    rt.store.insert("observations", {**{k: v for k, v in dict(rt.store.query_one(
        "SELECT * FROM observations WHERE id = ?", (oid,))).items() if k != "id"},
        "item_id": "uncited"})
    uncited = rt.store.query_one("SELECT MAX(id) AS m FROM observations")["m"]
    assert web.get(f"/api/observations/{uncited}").json()["cited_by"] == {
        "ideas": [], "briefs": []}
    # a purged observation keeps its citation rows: the card still says it cites it
    gone = old_card(store, cards["oids"][:1])
    gone["evidence"][0]["observation_id"] = 424242
    kept = add_card(store, "Cites a compacted one", gone)
    assert card_mod.cited_by(store, 424242) == [kept]
    ev = web.get(f"/api/ideas/{kept}").json()["evidence"][0]
    assert ev["observation_id"] == 424242 and ev["compacted"] is True


@pytest.fixture
def before_35(tmp_path, monkeypatch):
    """A library migrated up to 34, with cards as they were written before 35."""
    db = tmp_path / "kranto.db"
    monkeypatch.setattr(store_mod, "_MIGRATIONS",
                        [m for m in store_mod._MIGRATIONS if m[0] < 35])
    s = Store.open(db)
    topic = s.insert("topics", {"name": "energy", "description": "d", "embedding": b"",
                                "embedding_model": "stub", "created_at": "2026-10-01T00:00:00Z"})
    proj = s.insert("topics", {"name": "Kiosk (project)", "description": "d", "embedding": b"",
                               "embedding_model": "stub", "kind": "project", "ref": "project:k",
                               "created_at": "2026-10-01T00:00:00Z"})
    src = library.add_source(s, "rss", {"url": "https://ex.com/feed"}, label="Energy Feed")
    other = library.add_source(s, "rss", {"url": "https://ex.com/o"}, label="Other")
    for t in (topic, proj):
        library.link_topic_source(s, t, src)
    oids = []
    for i in range(3):
        call = s.insert("llm_calls", dict(purpose="judge", tier="judge", model="m",
                                          prompt_version="v", request="{}", response="{}",
                                          status="ok", attempts=1, cost_usd=0,
                                          created_at="2026-09-24T10:00:00Z"))
        oids.append(s.insert("observations", {
            "source_id": src if i < 2 else other, "item_id": f"i{i}", "kind": "beat",
            "title": "t", "summary": "s", "why_it_matters": "w", "content_quality": 0.5,
            "durability": 0.5, "opportunity": 0.5, "signal": 0.1, "tags": "[]",
            "embedding": b"", "embedding_model": "stub", "llm_call_id": call,
            "prompt_version": "v", "created_at": "2026-09-24T10:00:00Z"}))

    def card(title, evidence, demand=None, origin="cross_source"):
        body = {"title": title, "evidence": evidence, **({"demand": demand} if demand else {})}
        return s.insert("ideas", {"fingerprint": "f", "origin": origin, "evidence_key": title,
                                  "input_ids": "[]", "title": title, "card": json.dumps(body),
                                  "score": 0.5, "status": "shown", "dropped": "[]",
                                  "created_at": "2026-10-02T00:00:00Z"})
    ids = {
        "mine": card("Mine", [{"n": n, "observation_id": o} for n, o in enumerate(oids, 1)],
                     {"statement": "asks", "evidence": [{"n": 1, "observation_id": oids[1]}]}),
        "compacted": card("Compacted", [{"n": 1, "observation_id": 999, "source": "Energy Feed"}]),
        "archive": card("Archive", [{"n": 1, "observation_id": 998, "source": "Parallax"}],
                        origin="dispatch"),
        "odd": card("Odd", ["not an object", {"n": 1, "observation_id": "x"}]),
    }
    s.close()
    monkeypatch.undo()
    return db, ids, topic, proj, oids


def test_migration_35_fills_topics_and_citations_for_old_cards(before_35):
    db, ids, topic, proj, oids = before_35
    s = Store.open(db)
    try:
        assert 35 in s.applied_migrations()
        got = card_mod.card_topics(s, ids.values())
        mine = got[ids["mine"]]
        assert mine["topic_id"] == topic
        assert [(x.id, x.kind, x.n, x.share) for x in mine["shares"]] == [
            (topic, "user", 2, 0.6667), (proj, "project", 2, 0.6667)]
        # the cited label counts once the observation is gone, as the API's read did
        assert got[ids["compacted"]]["topic_id"] == topic
        assert got[ids["archive"]] == {"topic_id": None, "shares": []}
        assert got[ids["odd"]] == {"topic_id": None, "shares": []}
        rows = [tuple(r) for r in s.query(
            "SELECT idea_id, observation_id, n, role FROM idea_citations ORDER BY id")]
        mine = ids["mine"]
        assert rows == [(mine, oids[0], 1, "evidence"), (mine, oids[1], 2, "evidence"),
                        (mine, oids[2], 3, "evidence"), (ids["compacted"], 999, 1, "evidence"),
                        (ids["archive"], 998, 1, "evidence"), (mine, oids[1], 1, "demand")]
        # both are library rows: append-only, and ideas was not rewritten
        for table in ("idea_topics", "idea_citations"):
            with pytest.raises(sqlite3.DatabaseError, match="append-only"):
                s.query(f"UPDATE {table} SET created_at = 'x'")
        assert "topic_id" not in {r["name"] for r in s.query("PRAGMA table_info(ideas)")}
    finally:
        s.close()


def test_a_build_is_not_graded_and_a_card_has_no_build_grade(web, rt, cards):  # noqa: F811
    """a build is something the owner started, so it is not graded; the card's
    ``build_grade`` is gone with it. A build grade written before stays a
    history row; the index on ``context.card`` (migration 36) stays, as migrations only add."""
    post = {"target": "build", "target_id": "i235df527", "value": "not_useful",
            "reasons": ["wrong_scope"], "context": {"card": cards["new"], "idea": "i235df527"}}
    r = web.post("/api/feedback", json=post)
    assert r.status_code == 400 and "target must be" in r.json()["error"]      # CUT
    assert "build" in feedback.RETIRED_TARGETS
    assert "build_grade" not in web.get(f"/api/ideas/{cards['new']}").json()
    plan = " ".join(r[3] for r in rt.store.query(
        "EXPLAIN QUERY PLAN SELECT id FROM feedback WHERE json_extract(context, '$.card') IN (?)",
        (cards["new"],)))
    assert "feedback_card" in plan
