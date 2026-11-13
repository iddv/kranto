"""Short posts' routes: Write a post as short posts (the console's post.write too), I posted
it, Settings › Posting's sites. Nothing is sent: the write itself is replaced by a recorder."""

from __future__ import annotations

from kranto.core.cubs.brokers.social import FILER
from kranto.web import post_api

from .test_web import rt  # noqa: F401 - fixture

# -- the routes: Write a post as short posts, I posted it, Settings › Posting --------------------

def test_the_console_may_write_short_posts_and_nothing_is_sent(rt, monkeypatch):  # noqa: F811
    """SOC-11: the console's post.write {as: short} is prepared like any write (202); every
    ask a short post files waits for the page's confirm."""
    import time

    from kranto.core import verbs
    from kranto.web import verbs_api
    from kranto.web.app import create_app

    from .conftest import web_client
    verbs_api.precheck(rt, verbs.get("post.write"), None, {"about": "card:1", "as": "short"})
    asked = []
    monkeypatch.setattr(post_api, "write", lambda rt, about, as_, door, **k: asked.append(
        (about, as_, k.get("angle"))) or {"cub": FILER, "say": "ok"})
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/post/write", json={"about": "card:1", "as": "short",
                                                 "angle": "Kiosks need ledgers."})
        assert r.status_code == 202
        for _ in range(100):
            if client.get("/api/post/write?about=card:1&as=short").json().get("state") \
                    != "running":
                break
            time.sleep(0.02)
        assert client.post("/api/post/write", json={"about": "week", "as": "short"}
                           ).status_code == 400
        read = client.get("/api/post/sites").json()
        assert {s["id"] for s in read["sites"]} == {"bluesky", "mastodon", "x", "threads"}
        r = client.post("/api/post/sites", json={"sites": ["substack"]})
        assert r.status_code == 400 and "Substack" in r.json()["error"]
        assert client.post("/api/post/sites", json={"sites": ["x"]}).status_code == 200
        assert client.post("/api/post/d/999999/posted", json={}).status_code == 404
    assert asked == [("card:1", "short", "Kiosks need ledgers.")]
