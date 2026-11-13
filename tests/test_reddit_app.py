"""Reddit with the owner's own app (the owner's D-R1): the pasted app credentials are
exchanged for a token with the app's own Basic credentials, the account is named, every request
carries the unmasked user agent, and a subreddit is read through Reddit's API with scores and the
top comments, removed posts and comments left out. Without the app, the public feed. No network:
httpx.MockTransport."""

from __future__ import annotations

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from kranto.connections.oauth import OAuthError
from kranto.connections.reddit import RedditProvider, _Bearer, user_agent
from kranto.sources import HTTP
from kranto.sources.reddit import RedditSource

CID = "app" + "-id-123"                      # built at runtime: no secret-shaped literal
SECRET = "s" * 8 + "-app"
REFRESH = "r" * 10 + "-tok"
TOKEN = "t" * 12


def http(handler):
    return HTTP(transport=httpx.MockTransport(handler), resolver=lambda h: ["151.101.1.140"])


POST = {"id": "abc", "title": "Churchill XI sets the Agility vote", "selftext": "Vote soon.",
        "permalink": "/r/SPACs/comments/abc/x/", "is_self": True, "score": 420,
        "num_comments": 88, "created_utc": 1761580800, "author": "someone"}
GONE = {"id": "def", "title": "removed", "selftext": "[removed]", "permalink": "/r/SPACs/d/",
        "is_self": True, "score": 1, "num_comments": 0, "created_utc": 1761580800}
LINK = {"id": "ghi", "title": "A filing", "selftext": "", "permalink": "/r/SPACs/comments/ghi/y/",
        "is_self": False, "url": "https://www.sec.gov/x.htm", "score": 5, "num_comments": 2,
        "created_utc": 1761580900}
COMMENTS = [{"kind": "Listing"}, {"data": {"children": [
    {"data": {"body": "Redeem by the 29th.", "score": 50, "author": "a"}},
    {"data": {"body": "[deleted]", "score": 9, "author": "[deleted]"}}]}}]


def reddit(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.reddit.com" and request.url.path == "/api/v1/access_token":
        basic = base64.b64encode(f"{CID}:{SECRET}".encode()).decode()
        assert request.headers["authorization"] == f"Basic {basic}"
        assert request.headers["user-agent"].startswith("kranto/")
        form = parse_qs(request.content.decode())
        assert form == {"grant_type": ["refresh_token"], "refresh_token": [REFRESH]}
        return httpx.Response(200, json={"access_token": TOKEN, "expires_in": 3600})
    assert request.url.host == "oauth.reddit.com"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert "one person's reading tool" in request.headers["user-agent"]
    if request.url.path == "/api/v1/me":
        return httpx.Response(200, json={"name": "owner_name"})
    if request.url.path == "/r/SPACs/new":
        return httpx.Response(200, json={"data": {"children": [
            {"data": POST}, {"data": GONE}, {"data": LINK}]}})
    if request.url.path.startswith("/r/SPACs/comments/"):
        return httpx.Response(200, json=COMMENTS)
    return httpx.Response(404)


def test_the_owners_app_is_pasted_named_and_sends_an_unmasked_user_agent():
    p = RedditProvider(http(reddit))
    grant = p.paste({"client_id": CID, "client_secret": SECRET, "refresh_token": REFRESH})
    assert grant.account == "u/owner_name"
    assert p.headers({"access_token": TOKEN, "account": "u/owner_name"}, "GET", "x")[
        "User-Agent"].endswith("(by u/owner_name; one person's reading tool)")
    assert user_agent(None).endswith("(by u/unknown; one person's reading tool)")
    with pytest.raises(OAuthError, match="refresh token is required"):
        p.paste({"client_id": CID, "client_secret": SECRET})


def test_a_subreddit_is_read_through_the_api_with_scores_and_top_comments():
    authed = http(reddit).with_auth(_Bearer("oauth.reddit.com", {"access_token": TOKEN,
                                                                  "account": "u/owner_name"}))
    items = RedditSource(authed, subreddit="r/SPACs", comments=1).fetch()
    assert [i.id for i in items] == ["t3_abc", "t3_ghi"]          # the removed one is left out
    first = items[0]
    assert first.url == "https://www.reddit.com/r/SPACs/comments/abc/x/" and first.link is None
    assert "Score 420, 88 comments on Reddit." in first.body
    assert "Top comments: Redeem by the 29th. (score 50)" in first.body
    assert "[deleted]" not in first.body
    assert items[1].link == "https://www.sec.gov/x.htm" and "Top comments" not in items[1].body


def test_without_the_app_the_public_feed_is_read(monkeypatch):
    feed = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            '<id>t3_zzz</id><title>A post</title><link href="https://www.reddit.com/r/SPACs/'
            'comments/zzz/"/><updated>2026-10-27T10:00:00+00:00</updated>'
            '<content type="html">text</content></entry></feed>')
    seen = []

    def public(request):
        seen.append(str(request.url))
        return httpx.Response(200, text=feed)
    import kranto.sources.reddit as mod
    monkeypatch.setattr(mod.PACER, "wait", lambda: None)          # no wait in a test
    items = RedditSource(http(public), subreddit="SPACs").fetch()
    assert seen == ["https://www.reddit.com/r/SPACs/new/.rss"] and items[0].id == "t3_zzz"
