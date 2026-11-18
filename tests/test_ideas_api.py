"""GET /api/ideas: idea cards for the page's intake and Kranto UI."""

import json

import numpy as np
import pytest

from kranto import grades, library
from kranto.store import vec_to_blob
from kranto.stored.cards import Card
from kranto.web.ideas_api import embedding_text

from .test_web import rt, web  # noqa: F401 - fixtures


def obs_ids(store):
    return [r["id"] for r in store.query("SELECT id FROM observations ORDER BY id")]


def add_theme(store, lineage, size, topic_mix, name="Solar kits", cluster=0, snap=None):
    snap = snap or store.insert("snapshots", {
        "fingerprint": "f", "embedding_model": "stub", "n": size, "k": 1, "params": "{}",
        "quality": "{}", "density": "{}", "created_at": "2026-10-01T00:00:00Z"})
    store.insert("clusters", {
        "snapshot_id": snap, "cluster": cluster, "lineage_id": lineage, "size": size,
        "share": 1.0,
        "centroid": vec_to_blob(np.zeros(4, dtype=np.float32)), "centroid_2d": "[0, 0]",
        "keywords": json.dumps(["solar", "kits"]), "name": name, "source_mix": "{}",
        "max_source_share": 0.5, "cross_source": 1, "topic_mix": json.dumps(topic_mix),
        "representatives": "[]", "trajectory": "[]"})
    return snap


def add_card(store, title, card, *, status="shown", score=0.5, lineage=None, dropped=()):
    """A card as the writer stores it (``insert_card``: its topics and citations with it)."""
    from kranto.ideate.cards import insert_card
    return insert_card(store, {
        "fingerprint": "f", "lineage_id": lineage, "origin": "cross_source",
        "evidence_key": f"k-{title}", "input_ids": "[]", "title": title,
        "card": json.dumps(card), "score": score, "status": status,
        "dropped": json.dumps(list(dropped)), "created_at": "2026-10-02T00:00:00Z"})


def old_card(store, oids):
    """A card as written before #96: supported evidence with its snapshot, no who/demand."""
    rows = library.observations_by_id(store, oids)
    return {"title": "Solar kits for clinics", "pattern": "p", "where_now": "w",
            "thesis": "Clinics need power. Kits are cheap now.", "cheapest_test": "t",
            "risks": "r", "prediction": {"statement": "s", "by": None}, "ratings": {},
            "evidence": [{"n": n, "claim": f"claim {n}", "observation_id": oid,
                          "summary": rows[oid]["summary"], "source": rows[oid]["source_label"],
                          "observed_at": "2026-09-20T10:00:00Z",
                          "url": f"https://ex.com/{n}"} for n, oid in enumerate(oids, 1)]}


@pytest.fixture
def cards(rt):  # noqa: F811
    store = rt.store
    oids = obs_ids(store)
    broad = library.add_topic(store, rt.embedder, "clinics", "small health clinics")
    add_theme(store, "lin-a", 10, {"energy": 6, "clinics": 2})
    old = add_card(store, "Solar kits for clinics", old_card(store, oids[:2]), lineage="lin-a",
                   score=0.4, dropped=[{"n": 3, "claim": "x", "reason": "unsupported"}])
    new = {**old_card(store, oids[2:3]), "title": "Battery swap ledger",
           "who": "kiosk owners who rent out batteries",
           "smallest_v1": "A phone page that logs each swap.",
           "demand": {"statement": "Kiosk owners ask for a ledger.", "supported": 2,
                      "evidence": [{"n": 1, "claim": "asks", "observation_id": oids[2]}]},
           "citations": [{"observation_id": oids[2], "url": "https://ex.com/9",
                          "date": "2026-09-21", "observed_at": "2026-09-21T08:00:00Z",
                          "claim": "kiosks rent batteries", "source": "Energy Feed",
                          "for": "evidence"}],
           "output_kind": "cli", "insight": "Kiosks rent batteries but log swaps on paper [1].",
           "existing": [{"n": 1, "name": "SwapBook", "covers": "fleet rentals"}],
           "gap": "nothing for one kiosk", "moment": "a battery goes missing",
           "mechanism": "a phone page that logs each swap"}
    newer = add_card(store, "Battery swap ledger", new, score=0.9)
    hidden = add_card(store, "Unsupported one", old_card(store, oids[3:4]), status="unsupported",
                      score=0.99)
    grades.add_grade(store, "idea", old, "useful")
    return {"old": old, "new": newer, "hidden": hidden, "oids": oids, "clinics": broad}


def test_lists_every_card_with_status_score_grade(web, cards):  # noqa: F811
    r = web.get("/api/ideas")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3 and "default_output_kind" not in body      # builds'
    assert not [i for i in body["ideas"] if "intake" in i]
    by_id = {i["id"]: i for i in body["ideas"]}
    # the owner's order: the card graded useful first, then the rest by taste
    # and what they stand on, never the score; the unsupported one has no place
    assert body["ideas"][0]["id"] == cards["old"]
    assert body["ideas"][0]["rank"]["line"] == "you graded it useful"
    shown = [i for i in body["ideas"] if i["status"] == "shown"]
    assert [i["rank"]["position"] for i in shown] == [1, 2]
    assert by_id[cards["hidden"]]["rank"]["position"] is None
    rest = [(-i["rank"]["taste"], -i["facts"]["asks"], -i["facts"]["cited"],
             -i["facts"]["sources"], -i["id"]) for i in body["ideas"][1:]]
    assert rest == sorted(rest)
    assert {i["id"] for i in body["ideas"]} == {cards["hidden"], cards["new"], cards["old"]}
    old = by_id[cards["old"]]
    assert (old["status"], old["score"], old["grade"]) == ("shown", 0.4, "useful")
    assert by_id[cards["new"]]["grade"] is None
    assert by_id[cards["hidden"]]["status"] == "unsupported"
    shown = web.get("/api/ideas?status=shown").json()["ideas"]
    assert {i["id"] for i in shown} == {cards["old"], cards["new"]}
    assert web.get("/api/ideas?status=nope").status_code == 400


def test_old_cards_tolerate_missing_96_fields_and_get_citations(web, cards):  # noqa: F811
    old = web.get(f"/api/ideas/{cards['old']}").json()
    assert old["who"] is None and old["smallest_v1"] == "" and old["demand"] is None
    assert old["output_kind"] is None              # none written; no build's default
    assert [c["url"] for c in old["citations"]] == ["https://ex.com/1", "https://ex.com/2"]
    c = old["citations"][0]
    assert c == {"observation_id": cards["oids"][0], "url": "https://ex.com/1",
                 "date": "2026-09-20", "observed_at": "2026-09-20T10:00:00Z",
                 "claim": "claim 1", "source": "Energy Feed", "for": "evidence"}
    assert old["dropped"] == [{"n": 3, "claim": "x", "reason": "unsupported"}]
    assert old["evidence"][0]["compacted"] is False
    assert old["thesis"].startswith("Clinics need power") and old["one_liner"] == \
        "Clinics need power."


def test_new_cards_carry_who_smallest_v1_demand_and_citations(web, cards):  # noqa: F811
    new = web.get(f"/api/ideas/{cards['new']}").json()
    assert new["who"] == "kiosk owners who rent out batteries"
    assert new["smallest_v1"] == "A phone page that logs each swap."
    assert new["demand"]["statement"] == "Kiosk owners ask for a ledger."
    assert new["demand"]["supported"] == 2 and len(new["demand"]["evidence"]) == 1
    assert new["citations"] == [{"observation_id": cards["oids"][2], "url": "https://ex.com/9",
                                 "date": "2026-09-21", "observed_at": "2026-09-21T08:00:00Z",
                                 "claim": "kiosks rent batteries", "source": "Energy Feed",
                                 "for": "evidence"}]
    assert new["output_kind"] == "cli"
    # the insight fields (a card prompt that states the insight first); None on older cards
    assert new["insight"].startswith("Kiosks rent batteries") and new["gap"] and new["moment"]
    assert new["existing"] == [{"n": 1, "name": "SwapBook", "covers": "fleet rentals"}]
    assert new["mechanism"] == "a phone page that logs each swap"
    old = web.get(f"/api/ideas/{cards['old']}").json()
    assert all(old[k] is None for k in ("insight", "existing", "gap", "moment", "mechanism"))


def test_topics_come_from_the_evidence_not_the_theme(web, rt, cards):  # noqa: F811
    # lin-a's theme counts 2 members from clinics, but no evidence of the card is from a
    # clinics source: the card is energy's alone
    old = web.get(f"/api/ideas/{cards['old']}").json()
    energy = old["topics"][0]
    assert energy["name"] == "energy" and energy["share"] == 1.0 and energy["id"]
    assert old["topics"] == [energy] and old["topic"] == energy
    assert old["theme"]["name"] == "Solar kits" and old["theme"]["lineage_id"] == "lin-a"
    # a card with no theme still has its evidence's topics
    new = web.get(f"/api/ideas/{cards['new']}").json()
    assert [t["name"] for t in new["topics"]] == ["energy"] and new["theme"] is None
    assert web.get(f"/api/ideas?topic={cards['clinics']}").json()["count"] == 0
    assert web.get("/api/ideas?topic=energy").json()["count"] == 3
    # one of three cited observations from a clinics source (compacted: the card's own
    # snapshot names the source): clinics gets a third
    store = rt.store
    wire = library.add_source(store, "rss", {"url": "https://ex.com/clinics"}, label="Clinic Wire")
    library.link_topic_source(store, cards["clinics"], wire)
    card = old_card(store, cards["oids"][:2])
    card["evidence"].append({"n": 3, "claim": "c", "observation_id": 999999, "summary": "s",
                             "source": "Clinic Wire", "observed_at": "2026-09-20T10:00:00Z",
                             "url": "https://ex.com/3"})
    mixed = add_card(store, "Clinic power ledger", card, lineage="lin-a")
    got = web.get(f"/api/ideas/{mixed}").json()
    assert [(t["name"], t["share"]) for t in got["topics"]] == [("energy", 0.6667),
                                                                ("clinics", 0.3333)]
    assert got["topics"][1]["id"] == cards["clinics"]
    assert [i["id"] for i in web.get(f"/api/ideas?topic={cards['clinics']}").json()["ideas"]] \
        == [mixed]


def test_snapshot_17_a_new_theme_on_a_reused_cluster_number_has_no_ideas(web, rt):  # noqa: F811
    """A real install's snapshot 17 (2026-10-18): cluster 18 is a new robotics lineage; earlier maps
    gave the number 18 to other themes, which have cards. No card is on the new lineage, and
    a broad theme with one robotics member in 590 does not make its card a robotics idea."""
    store = rt.store
    oids = obs_ids(store)
    robotics = library.add_topic(store, rt.embedder, "Robotics", "robots at home and work")
    feed = library.add_source(store, "rss", {"url": "https://ex.com/robots"}, label="Robot Weekly")
    library.link_topic_source(store, robotics, feed)
    s11 = add_theme(store, "lin-power", 239, {"energy": 200}, "AI data center power demands",
                    cluster=18)
    add_theme(store, "lin-example-host", 420, {"energy": 50}, "Self-hosted the server tools",
              cluster=18)
    s17 = add_theme(store, "lin-robots", 77, {"Robotics": 43, "energy": 2},
                    "Weekly robotics newsletter digests", cluster=18)
    add_theme(store, "lin-broad", 590, {"energy": 255, "Robotics": 1}, "LLM inference serving",
              cluster=3, snap=s17)
    add_theme(store, "lin-power", 268, {"energy": 220}, "AI data center power demands",
              cluster=5, snap=s17)
    power = add_card(store, "Grid-aware batch scheduler", old_card(store, oids[:1]),
                     lineage="lin-power")
    broad = add_card(store, "Audit agent traces", old_card(store, oids[1:3]), lineage="lin-broad")
    assert s11 != s17
    ideas = web.get("/api/ideas").json()["ideas"]
    assert not [i for i in ideas if i["lineage_id"] == "lin-robots"]
    by_id = {i["id"]: i for i in ideas}
    # each card's theme is its own lineage's, never cluster 18's of the latest map
    assert by_id[power]["theme"]["name"] == "AI data center power demands"
    assert by_id[broad]["theme"]["name"] == "LLM inference serving"
    assert [t["name"] for t in by_id[broad]["topics"]] == ["energy"]
    assert web.get(f"/api/ideas?topic={robotics}").json()["count"] == 0


def test_embedding_is_the_local_embedders_and_a_reference_on_request(web, rt, cards):  # noqa: F811
    old = web.get(f"/api/ideas/{cards['old']}").json()
    emb = old["embedding"]
    assert emb["model"] == rt.embedder.model_name and emb["dim"] == rt.embedder.dim
    assert emb["text"] == embedding_text("Solar kits for clinics",
                                         Card(thesis="Clinics need power. Kits are cheap now."))
    expected = rt.embedder.embed_documents([emb["text"]])[0]
    assert np.allclose(emb["vector"], expected, atol=1e-5)
    ref = web.get(f"/api/ideas/{cards['old']}?embedding=ref").json()["embedding"]
    assert ref == {"model": rt.embedder.model_name, "dim": rt.embedder.dim,
                   "href": f"/api/ideas/{cards['old']}"}
    listed = web.get("/api/ideas?embedding=ref").json()["ideas"]
    assert all("vector" not in i["embedding"] for i in listed)
    assert web.get("/api/ideas?embedding=yes").status_code == 400


def test_unknown_card_and_the_guard(web, cards):  # noqa: F811
    assert web.get("/api/ideas/424242").status_code == 404
    assert web.get("/api/ideas/x").status_code == 404
    assert web.get("/api/ideas", headers={"host": "evil.example"}).status_code == 400
    assert web.post("/api/ideas", json={}).status_code == 405


def test_reading_makes_no_model_call_and_writes_nothing(web, rt, cards):  # noqa: F811
    def counts():
        return [rt.store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
                for t in ("llm_calls", "ideas", "grades")]
    before = counts()
    web.get("/api/ideas")
    web.get(f"/api/ideas/{cards['old']}")
    assert counts() == before
