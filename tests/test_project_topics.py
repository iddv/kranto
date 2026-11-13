"""Project topics (the page's PJ plan,): a topic the page creates for one of its projects
through the JSON API. It gathers like any topic but does not dilute the owner's own: listings
and Today keep it apart, and the card writer skips its themes unless told otherwise. No model
call, no network."""

from types import SimpleNamespace

import pytest

from kranto import cli, feedback, library
from kranto.config import IdeasConfig
from kranto.ideate import cards
from kranto.map.read import latest
from kranto.map.snapshot import take_snapshot
from kranto.store import Store

from .test_map import corpus  # noqa: F401 - fixture
from .test_topics_api import scouted, scouting  # noqa: F401 - fixtures
from .test_web import rt, web  # noqa: F401 - fixtures

REF = "project:p1a2b3c4d"


@pytest.fixture(autouse=True)
def _builds_on(monkeypatch):
    """These tests are about project topics with builds on; ``test_held_while_builds_are_off``
    turns them off itself."""
    from kranto import config
    monkeypatch.setattr(config, "builds_on", lambda cfg: True)


def test_held_while_builds_are_off(store, embedder):
    """.1: with builds off a project topic is listed as paused, its sources are
    not read, the owner's Resume is refused, and no status row is written for any of it."""
    user = library.add_topic(store, embedder, "energy", "batteries")
    proj, _ = library.add_topic_once(store, embedder, "Receipts", "what makes it better",
                                     kind="project", ref=REF)
    s1 = library.add_source(store, "rss", {"url": "https://example.org/a.xml"}, label="a")
    s2 = library.add_source(store, "rss", {"url": "https://example.org/b.xml"}, label="b")
    library.link_topic_source(store, proj, s1)
    library.link_topic_source(store, user, s2)
    library.link_topic_source(store, proj, s2)
    before = store.query("SELECT * FROM status_events ORDER BY id")
    library.configure(held_kinds=("project",))
    assert [t.id for t in library.active_topics(store)] == [user]
    assert {t.id: s for t, s, _ in library.topics_with_status(store)} == \
        {user: "active", proj: "paused"}
    # a source only the project's topic reads waits; one a user topic also reads is read
    assert library.paused_topic_sources(store) == {s1}
    with pytest.raises(ValueError, match="builds are off"):
        library.set_topic_status(store, proj, "paused")
    assert store.query("SELECT * FROM status_events ORDER BY id") == before
    # builds on again: as it was, with nothing to undo
    library.configure(held_kinds=())
    assert {t.id for t in library.active_topics(store)} == {user, proj}
    assert library.paused_topic_sources(store) == set()


# -- the migration ----------------------------------------------------------------------------
def test_migration_23_adds_kind_and_ref_and_old_rows_are_user_topics(tmp_path):
    store = Store.open(tmp_path / "kranto.db")
    try:
        assert 23 in store.applied_migrations()
        cols = {r["name"]: r for r in store.query("PRAGMA table_info(topics)")}
        assert cols["kind"]["notnull"] == 1 and cols["kind"]["dflt_value"] == "'user'"
        assert cols["ref"]["notnull"] == 0
        # a row written as before the migration (no kind, no ref) is a user topic
        store.insert("topics", {"name": "old", "description": "d", "embedding": b"\0" * 4,
                                "embedding_model": "m", "created_at": "2026-01-01T00:00:00Z"})
        row = store.query_one("SELECT kind, ref FROM topics WHERE name = 'old'")
        assert (row["kind"], row["ref"]) == ("user", None)
        assert "topics" in store.append_only_tables()
    finally:
        store.close()


def test_a_topics_kind_is_set_at_insert_and_a_ref_is_added_once(store, embedder):
    tid, existing = library.add_topic_once(store, embedder, "Receipts", "what makes it better",
                                           kind="project", ref=REF)
    assert not existing
    again, existing = library.add_topic_once(store, embedder, "Other name", "other",
                                             kind="project", ref=REF)
    assert (again, existing) == (tid, True)
    [t] = library.active_topics(store)
    assert (t.kind, t.ref, t.name) == ("project", REF, "Receipts")
    for kind, ref, why in [("project", None, "needs a ref"), ("project", "project:", "needs a ref"),
                           ("project", "project:UPPER", "needs a ref"),
                           ("project", "repo:abc", "needs a ref"),
                           ("project", "project:" + "a" * 41, "needs a ref"),
                           ("user", REF, "only a project topic"), ("team", None, "kind")]:
        with pytest.raises(ValueError, match=why):
            library.add_topic_once(store, embedder, "n", "d", kind=kind, ref=ref)
    with pytest.raises(Exception, match="append-only"):
        store.query("UPDATE topics SET kind = 'user' WHERE id = ?", (tid,))


# -- the API ----------------------------------------------------------------------------------
def test_a_project_topic_is_listed_only_when_asked_for(web, rt):  # noqa: F811
    r = web.post("/api/topics", json={"name": "Receipts", "description":
                                      "people asking for receipt scanning", "kind": "project",
                                      "ref": REF})
    assert r.status_code == 200, r.text
    made = r.json()
    assert (made["kind"], made["ref"], made["existing"]) == ("project", REF, False)
    assert "job" not in made

    def names(query=""):
        data = web.get("/api/topics" + query).json()
        assert all("kind" in t and "ref" in t for t in data["topics"])
        return {t["name"]: (t["kind"], t["ref"]) for t in data["topics"]}

    assert names() == {"energy": ("user", None)}
    assert names("?kind=user") == names()
    assert names("?kind=project") == {"Receipts": ("project", REF)}
    assert names("?kind=all") == {"energy": ("user", None), "Receipts": ("project", REF)}
    assert web.get("/api/topics?kind=team").status_code == 400
    one = web.get(f"/api/topics/{made['id']}").json()
    assert (one["kind"], one["ref"], one["status"]) == ("project", REF, "active")
    [energy] = [t for t in library.active_topics(rt.store) if t.kind == "user"]
    assert web.get(f"/api/topics/{energy.id}").json()["kind"] == "user"
    # the navigator's list stays the owner's; the source picker offers both
    assert [t["name"] for t in web.get("/api/status").json()["topics"]] == ["energy"]
    picker = {t["name"]: t["kind"] for t in web.get("/api/catalog").json()["topics"]}
    assert picker == {"energy": "user", "Receipts": "project"}


def test_posting_the_same_ref_again_returns_the_topic_and_starts_nothing(web, rt):  # noqa: F811
    body = {"name": "Receipts", "description": "receipt scanning", "kind": "project", "ref": REF}
    first = web.post("/api/topics", json=body).json()
    second = web.post("/api/topics", json={**body, "scout": True, "name": "Renamed"})
    assert second.status_code == 200
    out = second.json()
    assert (out["id"], out["existing"], out["kind"], out["ref"]) == (first["id"], True,
                                                                    "project", REF)
    assert "job" not in out
    assert len([t for t in library.active_topics(rt.store) if t.ref == REF]) == 1
    assert library.active_topics(rt.store)[-1].name == "Receipts"


@pytest.mark.parametrize("body,why", [
    ({"kind": "project"}, "needs a ref"),
    ({"kind": "project", "ref": "Project:abc"}, "needs a ref"),
    ({"kind": "project", "ref": "project:a b"}, "needs a ref"),
    ({"kind": "project", "ref": 42}, "needs a ref"),
    ({"ref": REF}, "only a project topic"),
    ({"kind": "team"}, "kind"),
    ({"kind": "project", "ref": REF, "approve": "some"}, "approve must be"),
])
def test_a_bad_kind_ref_or_approve_is_refused(web, rt, body, why):  # noqa: F811
    before = len(library.active_topics(rt.store))
    r = web.post("/api/topics", json={"name": "n", "description": "d", **body})
    assert r.status_code == 400 and why in r.json()["error"]
    assert len(library.active_topics(rt.store)) == before


def test_approve_core_approves_core_proposals_above_the_line(scouting):  # noqa: F811
    rt_, web_ = scouting
    r = web_.post("/api/topics", json={"name": "solar", "description":
                                       "solar microgrid battery storage", "scout": True,
                                       "kind": "project", "ref": REF, "approve": "core"})
    assert r.status_code == 200 and r.json()["job"]["state"] in ("running", "done")
    result = scouted(web_, r.json()["id"])
    line = rt_.cfg.ingest.prefilter_min_similarity
    rows = result["proposals"]
    assert rows
    for p in rows:
        sim = p["validation"]["median_similarity"]
        core_above = p["role"] == "core" and sim is not None and sim >= line
        assert p["review"] == ("approved" if core_above else "proposed"), p
    assert any(p["review"] == "approved" for p in rows)
    assert any(p["role"] == "wildcard" and p["review"] == "proposed" for p in rows)
    calls = len(rt_.llm.fake.requests)
    again = web_.post("/api/topics", json={"name": "solar", "description": "x", "scout": True,
                                           "kind": "project", "ref": REF}).json()
    assert again["existing"] and "job" not in again
    assert len(rt_.llm.fake.requests) == calls, "no second scout"


def test_approve_none_is_the_default_and_proposes_everything(scouting):  # noqa: F811
    rt_, web_ = scouting
    r = web_.post("/api/topics", json={"name": "solar", "description":
                                       "solar microgrid battery storage", "scout": True})
    assert r.json()["kind"] == "user" and r.json()["ref"] is None
    assert all(p["review"] == "proposed" for p in scouted(web_, r.json()["id"])["proposals"])


# -- the card writer (Today's tests are in test_today_api.py, with its fixtures) --------------
def _project_lineages(store, snap, name):
    from kranto.map import read as map_read

    return {c["lineage_id"] for c in map_read.clusters(store, snap["id"])
            if c["topic_mix"].get(name, 0) * 2 >= sum(c["topic_mix"].values()) > 0}


def test_the_card_writer_skips_project_topics_unless_told(corpus, embedder):  # noqa: F811
    solar = library.add_topic(corpus, embedder, "Solar power", "off-grid solar in Kenya")
    bread = library.add_topic(corpus, embedder, "Bread project", "sourdough at home",
                              kind="project", ref=REF)
    by_label = {s.label: s.id for s in library.list_sources(corpus)}
    for label in ("solar-a", "solar-b"):
        library.link_topic_source(corpus, solar, by_label[label])
    for label in ("bread-a", "bread-b"):
        library.link_topic_source(corpus, bread, by_label[label])
    take_snapshot(corpus, embedder, None)
    snap = latest(corpus)
    project = _project_lineages(corpus, snap, "Bread project")
    assert project, "the bread sources make a theme of their own"

    skipped = cards.candidates(corpus, snap)
    carded = cards.candidates(corpus, snap, project_topics="cards")
    assert not {c.lineage_id for c in skipped} & project
    assert {c.lineage_id for c in carded} & project
    # everything else is the same, in the same order
    assert [c for c in carded if c.lineage_id not in project] == skipped
    assert IdeasConfig().project_topics == "skip"


def test_without_project_topics_both_settings_give_the_same_candidates(corpus,  # noqa: F811
                                                                       embedder):
    solar = library.add_topic(corpus, embedder, "Solar power", "off-grid solar in Kenya")
    by_label = {s.label: s.id for s in library.list_sources(corpus)}
    library.link_topic_source(corpus, solar, by_label["solar-a"])
    take_snapshot(corpus, embedder, None)
    snap = latest(corpus)
    assert cards.candidates(corpus, snap) == cards.candidates(corpus, snap,
                                                              project_topics="cards")
    assert cards.candidates(corpus, snap)


def test_the_setting_is_checked(tmp_path):
    from kranto import config as config_mod

    path = tmp_path / "kranto.yaml"
    path.write_text("llm:\n  base_url: http://127.0.0.1:1\n  api_key_env: X\n  models:\n"
                    "    judge: j\n    reason: r\nbudget:\n  monthly_usd: 1\n"
                    "ingest: {}\nmap: {}\nideas:\n  project_topics: always\n")
    with pytest.raises(config_mod.ConfigError, match="ideas.project_topics"):
        config_mod.load(tmp_path, dotenv=False)
    path.write_text(path.read_text().replace("always", "cards"))
    assert config_mod.load(tmp_path, dotenv=False).ideas.project_topics == "cards"


# -- feedback and the CLI ---------------------------------------------------------------------
def test_a_project_is_no_feedback_target_any_more(store):
    """CUT: a project left with builds. Its older rows stay and are skipped
    (``feedback.RETIRED_TARGETS``); no new row names one."""
    assert "project" not in feedback.TARGETS and feedback.TARGETS[-1] == "pair"
    assert "project" in feedback.RETIRED_TARGETS
    with pytest.raises(ValueError, match="target must be"):
        feedback.add(store, {"target": "project", "target_id": "p1a2b3c4d", "value": "useful"})
    assert "project" not in feedback.vocabulary()["targets"]


def test_the_cli_adds_and_lists_project_topics(store, embedder, monkeypatch, capsys):
    rt_ = SimpleNamespace(store=store, embedder=embedder, close=lambda: None)
    monkeypatch.setattr(cli, "_runtime", lambda args: rt_)
    monkeypatch.setattr(cli, "_store", lambda args: (None, store))
    assert cli.main(["topics", "add", "mine", "my own topic", "--no-scout"]) == 0
    assert cli.main(["topics", "add", "Receipts", "receipt scanning", "--no-scout",
                     "--kind", "project", "--ref", REF]) == 0
    assert cli.main(["topics", "add", "Again", "x", "--kind", "project", "--ref", REF]) == 0
    assert "nothing added" in capsys.readouterr().out
    assert cli.main(["topics", "add", "Bad", "x", "--kind", "project", "--no-scout"]) == 2
    capsys.readouterr()
    cli.main(["topics", "list"])
    out = capsys.readouterr().out
    assert "mine" in out and "Receipts" not in out
    cli.main(["topics", "list", "--kind", "project"])
    out = capsys.readouterr().out
    assert "Receipts" in out and REF in out and "mine" not in out
    cli.main(["topics", "list", "--kind", "all"])
    out = capsys.readouterr().out
    assert "Receipts" in out and "mine" in out
