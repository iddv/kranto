"""Write a post (package POST's P2): card → Write draft → a blog draft on Post with
the card's sources linked, Copy giving its markdown; Kranto's own blog writer added from its folder
the first time; nothing sent. The model is a fake transport; the cub runs in its sandbox."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from kranto.core import api, tickets
from kranto.core.cubs import registry
from kranto.web import post_api
from kranto.web.app import create_app

from .conftest import chat_response, web_client
from .cubhelp import needs_bwrap
from .test_examples_install import add, home  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture

POST_JSON = {"title": "A ledger for battery swaps", "excerpt": "Kiosks lose track of batteries.",
             "body": "Kiosks swap batteries all day [1] and keep no record [2].\n\n## Why now\n\n"
                     "It is cheap to try."}


def writer(body: dict):
    """The blog writer's model: a post as JSON; anything else is said back."""
    system = body["messages"][0]["content"]
    if "blog post" in system:
        return chat_response(json.dumps(POST_JSON))
    return chat_response(body["messages"][-1]["content"])


def card(rt) -> int:  # noqa: F811
    from .test_ideas_api import add_card, obs_ids, old_card
    oids = obs_ids(rt.store)[:2] or [None]
    return add_card(rt.store, "Battery swap ledger", {**old_card(rt.store, oids),
                                                      "title": "Battery swap ledger",
                                                      "one_liner": "A phone page per kiosk."},
                    score=0.9)


def test_what_a_write_asks_for():
    assert post_api.plan_write("card:143", None) == ("blog", "blog.draft_card", "draft_card",
                                                     {"card": 143})
    assert post_api.plan_write("card:143", "toot") == ("toot", "toot.draft", "draft_card",
                                                       {"idea": "143"})
    assert post_api.plan_write("brief:41:2", "blog")[3] == {"brief": 41, "item": 2}
    assert post_api.plan_write("week", "blog")[1] == "blog.draft_week"
    for about, as_ in (("card:x", "blog"), ("idea 143", "blog"), ("card:1", "linkedin"),
                       ("week", "toot"), ("brief:41:2", "toot")):
        with pytest.raises(post_api.WriteError):
            post_api.plan_write(about, as_)


def test_cards_get_answers_the_cards_sources(rt):  # noqa: F811
    n = card(rt)
    ctx = SimpleNamespace(store=rt.store)
    got = api.cards_get(ctx, {"id": n})
    assert got["id"] == n and "Battery swap ledger" in got["title"]
    assert [s["url"] for s in got["sources"]][:1] == ["https://ex.com/1"]
    assert all(s["n"] == i for i, s in enumerate(got["sources"], 1))
    assert "cards.get" in api.reads()
    with pytest.raises(api.ReadError):
        api.cards_get(ctx, {"id": 99999})


def test_a_missing_short_post_writer_is_said_plainly(home):  # noqa: F811
    with pytest.raises(post_api.WriteError) as e:
        post_api.ensure_writer(home, "toot", door="ui")
    assert e.value.code == 409 and "Settings › Posting" in e.value.words


@needs_bwrap
def test_write_a_post_adds_the_blog_writer_once_and_ends_on_post(home):  # noqa: F811
    home.llm.fake.handler = writer
    n = card(home)
    assert registry.latest(home.store, "blog") is None
    out = post_api.write(home, f"card:{n}", "blog", door="ui")
    assert out["cub"] == "blog" and "waits on Post" in out["say"]
    row = registry.latest(home.store, "blog")
    assert row["state"] == "installed" and row["trust"] == "owner"
    [t] = tickets.listing(home.store, cub="blog")
    assert t["kind"] == "draft.sanity" and t["state"] == tickets.OPEN
    assert t["expires_at"] == tickets.NEVER and t["because"] == {"ideas": [n]}
    # on Post: a blog post waiting, its markdown with the card's own sources under it
    got = post_api.post_read(home)
    [d] = got["drafts"]
    assert d["word"] == "blog post" and d["title"] == POST_JSON["title"]
    assert d["fact"] == f"from #{n}" and d["ticket"] == t["id"]
    md = post_api.draft_sheet(home, d["id"])["markdown"]
    assert md.startswith(f"# {POST_JSON['title']}\n\n*{POST_JSON['excerpt']}*")
    assert "## Sources" in md and "](https://ex.com/1)" in md
    # its press is practice: nothing is filed anywhere
    pressed = tickets.confirm(home.store, t["id"], identity={"origin": "ui", "via": "cookie"},
                              confirm=True, context=home)
    assert pressed["state"] == "dry"
    # a second write uses the same writer: no second install
    post_api.write(home, f"card:{n}", "blog", door="ui")
    installs = home.store.query("SELECT DISTINCT job_id FROM cub_installs WHERE cub = 'blog'")
    assert len(installs) == 1


def test_the_route_answers_at_once_and_refuses_what_it_cannot_write(rt, monkeypatch):  # noqa: F811
    asked = []
    monkeypatch.setattr(post_api, "write", lambda rt, about, as_, door: asked.append(
        (about, as_, door)) or {"cub": "blog", "say": "ok"})
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/post/write", json={"about": "idea 1"})
        assert r.status_code == 400 and "card:<number>" in r.json()["error"]
        r = client.post("/api/post/write", json={"about": "week", "as": "toot"})
        assert r.status_code == 400
        r = client.post("/api/post/write", json={"about": "card:1", "as": "blog"})
        assert r.status_code == 202 and r.json()["say"] == post_api.WRITING
        for _ in range(100):                     # the job runs in its thread: until it ends
            job = client.get("/api/post/write?about=card:1&as=blog")
            if job.json().get("state") != "running":
                break
            time.sleep(0.02)
        assert job.status_code == 200 and job.json()["state"] == "done"
        assert client.get("/api/post/write?about=card:2").status_code == 404
    assert asked == [("card:1", "blog", "ui")]


class _Cubs:
    """A cubs' runtime whose one action answers ``out`` (or raises it)."""

    def __init__(self, out):
        self.out = out

    def action(self, *a, **k):
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


def test_a_write_that_fails_says_why_in_words(monkeypatch):
    """No model answering (the preview has no key): the job ends failed with the owner's words,
    never the machinery's."""
    failed = ("failed: the handler raised HostError after Kranto answered: the model did not "
              "answer: TransientLLMError")
    said = post_api.not_written(failed)
    assert said.startswith("No draft was written: the model did not answer")
    assert "Settings › Watching" in said
    assert post_api.not_written("Brief 41 has no item 9.") == \
        "No draft was written: Brief 41 has no item 9."
    assert "handler" not in post_api.not_written("failed: the handler raised KeyError")
    monkeypatch.setattr(post_api, "ensure_writer", lambda runtime, cid, door: None)
    for out in ({"ok": False, "error": failed}, RuntimeError("the model did not answer")):
        with pytest.raises(post_api.WriteError) as e:
            post_api.write(SimpleNamespace(cubs=_Cubs(out)), "card:1", "blog", door="ui")
        assert e.value.words.startswith("No draft was written: the model did not answer")


# -- 4: a write that cannot start says so at once, and a failed one stays on Post -----------

def _until_done(client, about, as_="blog"):
    for _ in range(200):
        job = client.get(f"/api/post/write?about={about}&as={as_}").json()
        if job.get("state") != "running":
            return job
        time.sleep(0.02)
    return job


def test_with_no_model_key_write_stops_at_once_and_post_keeps_why(rt, monkeypatch):  # noqa: F811
    """Codex 1, 13, Gemini 5: with no key the job started ("Writing the draft"), then failed as
    "the model did not answer", and a reload lost it. Now: 409 in plain words with the setting's
    link, and Post lists it with Try again's subject until it is dismissed."""
    monkeypatch.setattr(type(rt.llm), "has_key", property(lambda self: False))
    started = []
    monkeypatch.setattr(post_api, "write", lambda *a, **k: started.append(a))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/post/write", json={"about": "card:7", "as": "blog"})
        assert r.status_code == 409, r.text
        assert r.json()["error"] == post_api.NO_KEY and "no model key is set" in post_api.NO_KEY
        assert r.json()["fix"] == "settings/watching"
        assert started == []                                   # no job ran
        [f] = client.get("/api/post").json()["failed"]
        assert f["about"] == "card:7" and f["as"] == "blog" and f["error"] == post_api.NO_KEY
        assert f["fix"] == "settings/watching" and f["title"] == "card #7"
        # dismissed: it goes, and a second dismiss of nothing says so
        gone = client.post("/api/post/write/dismiss", json={"about": "card:7", "as": "blog"})
        assert gone.json() == {"ok": True}
        assert client.get("/api/post").json()["failed"] == []
        assert client.post("/api/post/write/dismiss", json={"about": "card:8"}).status_code == 404


def test_a_write_that_failed_in_its_job_stays_on_post_after_a_restart(rt, monkeypatch):  # noqa: F811
    def boom(*a, **k):
        raise post_api.WriteError(post_api.not_written("the model did not answer"), 502)
    monkeypatch.setattr(post_api, "write", boom)
    app = create_app(rt)
    with web_client(app, "http://127.0.0.1:8765") as client:
        assert client.post("/api/post/write", json={"about": "card:3"}).status_code == 202
        assert _until_done(client, "card:3")["state"] == "failed"
        [f] = client.get("/api/post").json()["failed"]
        assert f["error"].startswith("No draft was written: the model did not answer")
    # a new server on the same home reads the kept job (the page's reload after a restart)
    from kranto.web.jobs import Jobs
    kept = [j["key"] for j in Jobs(rt.cfg.data_dir / "jobs").listing("post:")
            if j["state"] == "failed"]
    assert kept == ["post:blog:card:3"]


def test_no_api_key_is_said_as_no_model_key():
    said = post_api.not_written("failed: FatalLLMError: no API key: set $OPENROUTER_API_KEY")
    assert said == post_api.NO_KEY


def test_an_assistants_post_write_with_no_key_is_refused_never_prepared(rt, monkeypatch):  # noqa: F811
    """Codex 1: an approved post.write said "Write a post: done" for a job that failed in 0.8 s."""
    from kranto.core import verbs
    from kranto.web import verbs_api
    monkeypatch.setattr(type(rt.llm), "has_key", property(lambda self: False))
    with pytest.raises(verbs_api.VerbError) as e:
        verbs_api.precheck(rt, verbs.get("post.write"), None, {"about": "card:1", "as": "blog"})
    assert "no model key is set" in str(e.value)


def test_the_owners_site_cub_reads_as_blog_and_post_names_no_cub():
    """ G4: "Post to example.com asks", "blog post · by examplecom" and
    kranto_f_examplecom_* showed the owner's site name to a stranger; its build launch post
    stayed."""
    manifest = {
        "id": "examplecom",
        "title": "Post to example.com",
        "says": "Drafts a post for example.com.",
        "actions": [
            {"kind": "examplecom.draft_week", "title": "Draft from a week"},
            {"kind": "examplecom.draft_build", "title": "Draft a build's launch post"},
        ],
        "ui": {
            "tile": {"line": "Posts for example.com"},
            "pages": [
                {
                    "forms": [
                        {"submit": "examplecom.draft_build"},
                        {"submit": "examplecom.draft_week"},
                    ]
                }
            ],
        },
    }
    shown = registry.shown_manifest("examplecom", manifest)
    words = json.dumps(shown)
    assert shown["title"] == "Blog" and "example.com" not in words and "draft_build" not in words
    assert [a["kind"] for a in shown["actions"]] == ["examplecom.draft_week"]  # its kinds stay
    assert manifest["title"] == "Post to example.com"  # the stored one too
    assert registry.shown_manifest("toot", {"title": "Toot"}) == {"title": "Toot"}
    assert post_api.fact_of("blog", None, "2026-11-10T08:00:00Z", "examplecom") == ""


def test_a_post_job_is_an_activity_run():
    from kranto.activity import words
    from kranto.web import jobs

    assert "post" in jobs.RUN_KINDS
    assert words.title_of("post", "failed") == "A post's draft"
