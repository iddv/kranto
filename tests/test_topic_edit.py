"""The owner edits a topic (migration 38): its name and description as a revision under
the same id, its sources added and removed from the topic, archived and restored; each change
recorded with who made it, and what Undo sends back."""

import sqlite3

import pytest

from kranto import library
from kranto.map.snapshot import take_snapshot
from kranto.store import Store
from kranto.web import types as T

from .test_map import corpus  # noqa: F401 - fixture
from .test_topics_api import EVIL, themed  # noqa: F401 - fixture
from .test_web import rt, web  # noqa: F401 - fixtures
from .test_web_types import problems


def _topic(client, tid):
    return client.get(f"/api/topics/{tid}").json()


def test_an_edit_keeps_the_id_and_is_seen_everywhere_at_once(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    before = library.active_topics(rt.store)[0].embedding.copy()
    assert web.post(f"/api/topics/{t.id}", json={"description": "x"},
                    headers=EVIL).status_code == 403
    r = web.post(f"/api/topics/{t.id}", json={"name": "Energy access",
                                              "description": "off-grid solar in East Africa"})
    assert r.status_code == 200 and problems(r.json(), T.TopicEdit) == []
    rev = r.json()["revision"]
    assert r.json()["changed"] == ["name", "description"] and rev["by"] == "ui"
    assert rev["before"] == {"name": "energy", "description": "solar and batteries in Africa"}
    # the same id, the new words, a new embedding: every reader goes through topics_now
    [now] = library.active_topics(rt.store)
    assert (now.id, now.name) == (t.id, "Energy access")
    assert not (now.embedding == before).all()
    assert [x["name"] for x in web.get("/api/topics").json()["topics"]] == ["Energy access"]
    assert web.get("/api/catalog").json()["topics"][0]["name"] == "Energy access"
    page = _topic(web, t.id)
    assert page["description"] == "off-grid solar in East Africa"
    assert page["history"][0]["what"] == "edit" and page["history"][0]["by"] == "ui"
    # the topics row is as written: append-only, nothing rewritten
    assert rt.store.query_one("SELECT name FROM topics WHERE id = ?", (t.id,))["name"] == "energy"
    # Undo sends before back: another revision
    r = web.post(f"/api/topics/{t.id}", json={**rev["before"], "note": "undo"})
    assert r.json()["changed"] == ["name", "description"]
    assert _topic(web, t.id)["name"] == "energy"
    assert library.topic_names_ever(rt.store, t.id) == {"energy", "Energy access"}
    # the same words change nothing
    assert web.post(f"/api/topics/{t.id}", json={"name": "energy"}).json() == {
        "id": t.id, "changed": None, "revision": None}


def test_an_edit_is_validated(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    other = library.add_topic(rt.store, rt.embedder, "storage", "home batteries")
    for body, words in (({}, "send a name"), ({"name": "  "}, "a name and a description"),
                        ({"name": "x" * 121}, "at most 120"), ({"description": 3}, "text"),
                        ({"name": "Storage"}, "another topic is called"),
                        ({"name": "y", "origin": "evil"}, "origin is one of")):
        r = web.post(f"/api/topics/{t.id}", json=body)
        assert r.status_code == 400 and words in r.json()["error"], (body, r.text)
    assert web.post("/api/topics/999", json={"name": "z"}).status_code == 404
    proj = library.add_topic(rt.store, rt.embedder, "Kiosk (project)", "Kiosk",
                             kind="project", ref="project:kiosk")
    r = web.post(f"/api/topics/{proj}", json={"name": "Kiosk"})
    assert r.status_code == 400 and "follows its project" in r.json()["error"]
    assert web.post(f"/api/topics/{other}", json={"name": "Batteries", "origin": "chat"}
                    ).json()["revision"]["by"] == "chat"


def test_sources_are_added_and_removed_from_one_topic(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    [own] = [s.id for s in library.list_sources(rt.store)]
    shared = library.add_source(rt.store, "rss", {"url": "https://ex.com/shared"}, label="Shared")
    second = library.add_topic(rt.store, rt.embedder, "storage", "home batteries")
    library.link_topic_source(rt.store, second, shared)
    loose = library.add_source(rt.store, "rss", {"url": "https://ex.com/loose"}, label="Loose",
                               status="proposed")

    r = web.post(f"/api/topics/{t.id}/sources", json={"add": [shared, loose], "remove": [own]})
    assert r.status_code == 200 and problems(r.json(), T.TopicSourcesChange) == []
    # the removed one had no other topic: retired (never the broad lane); the proposed one
    # added is approved
    assert r.json() == {"id": t.id, "added": [shared, loose], "removed": [own],
                        "retired": [own], "approved": [loose], "remaining": {str(own): []}}
    labels = {s["label"] for s in _topic(web, t.id)["source_rows"]}
    assert labels == {"Shared", "Loose"}
    assert all(b["label"] != "Energy Feed" for b in web.get("/api/topics").json()["broad"])
    status = {s.id: s.status for s in library.list_sources(rt.store)}
    assert status[own] == "retired" and status[loose] == "approved"
    # removing a shared one leaves it with its other topic, approved
    r = web.post(f"/api/topics/{t.id}/sources", json={"remove": [shared]}).json()
    assert r["removed"] == [shared] and r["retired"] == []
    # ...and says what it still feeds, for the toast
    assert r["remaining"] == {str(shared): [{"id": second, "name": "storage", "kind": "user"}]}
    assert {x.id for x in library.topics_for_source(rt.store, shared)} == {second}
    # Undo: adding back links again (an event row, the topic_sources row untouched) and
    # approves the retired one
    r = web.post(f"/api/topics/{t.id}/sources", json={"add": [own, shared]}).json()
    assert r["added"] == [own, shared] and r["approved"] == [own]
    assert {s["label"] for s in _topic(web, t.id)["source_rows"]} == {
        "Energy Feed", "Shared", "Loose"}
    ops = [h["what"] for h in _topic(web, t.id)["history"] if h["what"] in ("link", "unlink")]
    assert sorted(ops) == ["link"] * 4 + ["unlink"] * 2
    # the evidence of a removed source stays readable, filed under no topic
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM topic_sources")["n"] == 4


def test_a_sources_change_is_validated(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    [own] = [s.id for s in library.list_sources(rt.store)]
    for body in ({}, {"add": "1"}, {"add": [True]}, {"add": [own], "remove": [own]},
                 {"add": list(range(51))}, {"remove": [own], "origin": "x"}):
        assert web.post(f"/api/topics/{t.id}/sources", json=body).status_code == 400, body
    assert web.post(f"/api/topics/{t.id}/sources", json={"add": [999]}).status_code == 404
    assert web.post("/api/topics/999/sources", json={"add": [own]}).status_code == 404
    assert web.post(f"/api/topics/{t.id}/sources", json={"add": [own]},
                    headers=EVIL).status_code == 403
    # removing what is not linked changes nothing
    assert web.post(f"/api/topics/{t.id}/sources", json={"remove": [own]}).json()["removed"]
    assert web.post(f"/api/topics/{t.id}/sources", json={"remove": [own]}).json()["removed"] == []


def test_archiving_takes_a_topic_off_the_lists_and_undo_brings_it_back(web, rt):  # noqa: F811
    [t] = library.active_topics(rt.store)
    [src] = [s.id for s in library.list_sources(rt.store)]
    r = web.post(f"/api/topics/{t.id}/status", json={"status": "archived"})
    assert problems(r.json(), T.TopicStatusChange) == []
    assert r.json() == {"id": t.id, "status": "archived", "was": "active", "changed": True}
    data = web.get("/api/topics").json()
    assert data["topics"] == [] and [x["name"] for x in data["archived"]] == ["energy"]
    assert data["archived"][0]["status"] == "archived"
    # not read, not the broad lane; its page, evidence and cards stay readable
    assert library.paused_topic_sources(rt.store) == {src} and data["broad"] == []
    assert _topic(web, t.id)["status"] == "archived"
    assert web.get(f"/api/observations?topic={t.id}").json()["results"]
    assert web.get("/api/catalog").json()["topics"] == []
    # Undo sends was back
    assert web.post(f"/api/topics/{t.id}/status", json={"status": "active"}).json()["was"] == \
        "archived"
    assert [x["name"] for x in web.get("/api/topics").json()["topics"]] == ["energy"]
    assert library.paused_topic_sources(rt.store) == set()


def test_a_renamed_topic_keeps_the_themes_filed_under_its_old_name(themed):  # noqa: F811
    client, solar, _ = themed
    before = client.get(f"/api/topics/{solar}").json()
    assert before["themes"] >= 1
    client.post(f"/api/topics/{solar}", json={"name": "Off-grid solar"})
    after = client.get(f"/api/topics/{solar}").json()
    assert after["name"] == "Off-grid solar" and after["themes"] == before["themes"]
    assert [c["topic_share"] for c in after["themes_list"]] == \
        [c["topic_share"] for c in before["themes_list"]]


def test_a_new_map_files_stories_under_the_new_name(corpus, embedder):  # noqa: F811
    solar = library.add_topic(corpus, embedder, "Solar power", "off-grid solar in Kenya")
    for s in library.list_sources(corpus):
        if s.label.startswith("solar"):
            library.link_topic_source(corpus, solar, s.id)
    library.edit_topic(corpus, embedder, solar, name="Off-grid solar", by="ui")
    take_snapshot(corpus, embedder, None)
    mixes = [r["topic_mix"] for r in corpus.query("SELECT topic_mix FROM clusters")]
    assert any("Off-grid solar" in m for m in mixes) and not any("Solar power" in m for m in mixes)


def test_the_new_tables_are_append_only(tmp_path, embedder):
    store = Store.open(tmp_path / "a.db")
    t = library.add_topic(store, embedder, "solar", "off-grid solar")
    src = library.add_source(store, "rss", {"url": "https://ex.com/f"}, label="F")
    library.link_topic_source(store, t, src)
    library.edit_topic(store, embedder, t, name="Solar", by="ui")
    library.unlink_topic_source(store, t, src, by="ui")
    for table in ("topic_revisions", "topic_source_events"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.query(f"DELETE FROM {table}")


def test_the_cli_edits_and_archives_a_topic(store, embedder, monkeypatch, capsys):
    from types import SimpleNamespace

    from kranto import cli
    rt_ = SimpleNamespace(store=store, embedder=embedder, close=lambda: None)
    monkeypatch.setattr(cli, "_runtime", lambda args: rt_)
    monkeypatch.setattr(cli, "_store", lambda args: (None, store))
    t = library.add_topic(store, embedder, "solar", "off-grid solar")
    assert cli.main(["topics", "edit", str(t), "--name", "Solar"]) == 0
    assert "name changed (was 'solar')" in capsys.readouterr().out
    assert store.query_one("SELECT by FROM topic_revisions")["by"] == "cli"
    assert cli.main(["topics", "edit", str(t)]) == 2
    assert cli.main(["topics", "archive", str(t)]) == 0
    assert library.active_topics(store) == []
    assert cli.main(["topics", "archive", str(t), "--restore"]) == 0
    assert [x.name for x in library.active_topics(store)] == ["Solar"]
