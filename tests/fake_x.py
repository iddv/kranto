"""A fake X API: OAuth 2.0 with PKCE for a public client, token rotation,
revoke, and the read endpoints Kranto uses, as an ``httpx`` transport. The reply shapes follow
the examples on X's public endpoint pages (``tests/fixtures/x/``); nothing here came from a
real call, and no test reaches X.

Every token and code is made at run time. The fake keeps a log of every request and a count of
the resources it returned per price line, which the ledger tests compare with ``api_spend``."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs

import httpx

FIXTURES = Path(__file__).with_name("fixtures") / "x"
SCOPES = "tweet.read users.read list.read bookmark.read like.read offline.access"
USER_ID = "2244994945"
USERNAME = "reader"


def fixture(name: str) -> dict:
    """A recorded example body: the JSON after the file's header comment lines."""
    text = (FIXTURES / name).read_text()
    return json.loads("\n".join(ln for ln in text.splitlines() if not ln.startswith("//")))


def post(pid: int, text: str, **extra) -> dict:
    """A post as X returns it with Kranto's fields."""
    return {"id": str(pid), "text": text, "created_at": extra.pop("created_at",
                                                                  "2026-10-16T10:00:00.000Z"),
            "conversation_id": extra.pop("conversation_id", str(pid)),
            "edit_history_post_ids": extra.pop("edit_history_post_ids", [str(pid)]),
            "public_metrics": extra.pop("public_metrics", {
                "repost_count": 2, "reply_count": 0, "like_count": 10, "quote_count": 1,
                "bookmark_count": 3, "impression_count": 400}), **extra}


# max_results each endpoint takes, and whether it takes since_id (X's API reference,
# 2026-10-17); a request outside them is answered 400, as X does
RANGES = {"list": (1, 100, False), "home": (1, 100, True), "profile": (5, 100, True),
          "search": (10, 100, True), "bookmarks": (1, 100, False), "likes": (5, 100, False)}


class FakeX:
    def __init__(self) -> None:
        self.client_id = "cid" + secrets.token_urlsafe(24)
        self.code = secrets.token_urlsafe(20)
        self.access = secrets.token_urlsafe(32)
        self.refresh_token = secrets.token_urlsafe(32)
        self.spent_refresh: set[str] = set()
        self.challenge: str | None = None
        self.redirect_uri: str | None = None
        self.scope = SCOPES
        self.give_refresh = True
        self.expires_in = 7200
        self.revoked: set[str] = set()
        self.credits = True
        self.limited_until: int | None = None
        self.requests: list[httpx.Request] = []
        self.returned: Counter = Counter()
        # what the read endpoints answer: newest first, as X orders them
        self.timeline: list[dict] = [post(1849000000000000003, "A CRDT engine for SQLite "
                                          "ships offline sync https://t.co/a1",
                                          entities={"urls": [{
                                              "url": "https://t.co/a1",
                                              "expanded_url": "https://example.org/crdt",
                                              "display_url": "example.org/crdt"}]}),
                                     post(1849000000000000002, "Microgrids in rural Kenya "
                                          "are now cheaper than the grid extension"),
                                     post(1849000000000000001, "An older post about local-first "
                                          "software")]
        self.includes: list[dict] = []
        self.thread: list[dict] = []           # what conversation_id: searches return
        self.owned_lists: list[dict] = [{"id": "42", "name": "Builders"}]
        self.lookup_missing: set[str] = set()

    # -- helpers ----------------------------------------------------------------------------

    def bearer_ok(self, request: httpx.Request) -> bool:
        return request.headers.get("authorization") == f"Bearer {self.access}" \
            and self.access not in self.revoked

    def _tokens(self) -> dict:
        reply = {"token_type": "bearer", "expires_in": self.expires_in,
                 "access_token": self.access, "scope": self.scope}
        if self.give_refresh:
            reply["refresh_token"] = self.refresh_token
        return reply

    def _page(self, data: list[dict], kind: str, *, params, endpoint: str) -> httpx.Response:
        low, high, takes_since = RANGES[endpoint]
        limit = int(params.get("max_results") or (10 if endpoint == "search" else 100))
        if not low <= limit <= high or ("since_id" in params and not takes_since):
            return httpx.Response(400, json={"title": "Invalid Request", "status": 400,
                                             "detail": "One or more parameters to your request "
                                                       "was invalid."})
        if "tweet.fields" in params or "user.fields" in params or \
                "author_id" in (params.get("expansions") or ""):
            return httpx.Response(400, json={"title": "Invalid Request", "status": 400,
                                             "detail": "not asked by Kranto"})
        since = params.get("since_id")
        if since:
            data = [p for p in data if int(p["id"]) > int(since)]
        query = params.get("query") or ""
        if endpoint == "search" and query.startswith("conversation_id:"):
            conv = query.split()[0].split(":", 1)[1]
            data = [p for p in self.thread if p.get("conversation_id") == conv]
        elif endpoint == "search":
            data = [p for p in data if p.get("conversation_id") == p["id"]]
        data = data[:limit]
        body: dict = {"meta": {"result_count": len(data)}}
        if data:
            body["data"] = data
            body["meta"].update(newest_id=data[0]["id"], oldest_id=data[-1]["id"])
            self.returned[kind] += len(data)
            wanted = {r["id"] for p in data for r in p.get("referenced_posts") or []}
            inc = [t for t in self.includes if t["id"] in wanted]
            if inc and "referenced_posts" in (params.get("expansions") or ""):
                body["includes"] = {"posts": inc}
                self.returned["post_read"] += len(inc)
        return httpx.Response(200, json=body)

    # -- the transport ----------------------------------------------------------------------

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        params = dict(request.url.params)
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} \
            if request.method == "POST" else {}
        if request.url.host not in ("api.x.com", "x.com"):
            return httpx.Response(404)
        if path == "/2/oauth2/token":
            if "authorization" in request.headers:
                return httpx.Response(400, json={"error": "invalid_request",
                                                 "error_description": "public client"})
            if form.get("client_id") != self.client_id:
                return httpx.Response(401, json={"error": "unauthorized_client"})
            if form.get("grant_type") == "refresh_token":
                old = form.get("refresh_token")
                if old != self.refresh_token or old in self.spent_refresh:
                    return httpx.Response(400, json={"error": "invalid_request",
                                                     "error_description": "Value passed for "
                                                     "the token was invalid."})
                self.spent_refresh.add(old)
                self.access = secrets.token_urlsafe(32)
                self.refresh_token = secrets.token_urlsafe(32)
                return httpx.Response(200, json=self._tokens())
            verifier = form.get("code_verifier", "")
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            if form.get("grant_type") != "authorization_code" or form.get("code") != self.code \
                    or digest.decode().rstrip("=") != self.challenge \
                    or form.get("redirect_uri") != self.redirect_uri:
                return httpx.Response(400, json={"error": "invalid_request"})
            self.code = secrets.token_urlsafe(20)          # a code is spent once
            return httpx.Response(200, json=self._tokens())
        if path == "/2/oauth2/revoke":
            if form.get("client_id") != self.client_id:
                return httpx.Response(401, json={"error": "unauthorized_client"})
            self.revoked.add(form.get("token") or "")
            return httpx.Response(200, json={"revoked": True})
        if not self.bearer_ok(request):
            return httpx.Response(401, json={"title": "Unauthorized", "type":
                                             "about:blank", "status": 401,
                                             "detail": "Unauthorized"})
        if self.limited_until is not None:
            return httpx.Response(429, headers={"x-rate-limit-reset": str(self.limited_until)},
                                  json={"title": "Too Many Requests", "status": 429,
                                        "detail": "Too Many Requests"})
        if not self.credits:
            return httpx.Response(402, json={
                "title": "CreditsDepleted", "status": 402, "type": "about:blank",
                "detail": "Your enrolled account does not have any credits to fulfill this "
                          "request."})
        if path == "/2/users/me":
            self.returned["user_read"] += 1
            return httpx.Response(200, json={"data": {"id": USER_ID, "name": "A Reader",
                                                      "username": USERNAME}})
        if path.startswith("/2/lists/") and path.endswith("/tweets"):
            return self._page(self.timeline, "post_read", params=params, endpoint="list")
        if path == f"/2/users/{USER_ID}/timelines/reverse_chronological":
            return self._page(self.timeline, "post_read", params=params, endpoint="home")
        if path == f"/2/users/{USER_ID}/bookmarks":
            return self._page(self.timeline, "owned_read", params=params, endpoint="bookmarks")
        if path == f"/2/users/{USER_ID}/liked_tweets":
            return self._page(self.timeline, "owned_read", params=params, endpoint="likes")
        if path.startswith("/2/users/") and path.endswith("/tweets"):
            return self._page(self.timeline, "post_read", params=params, endpoint="profile")
        if path == "/2/tweets/search/recent":
            return self._page(self.timeline, "post_read", params=params, endpoint="search")
        if path == f"/2/users/{USER_ID}/owned_lists":
            self.returned["list_read"] += len(self.owned_lists)
            return httpx.Response(200, json={"data": self.owned_lists,
                                             "meta": {"result_count": len(self.owned_lists)}})
        if path.startswith("/2/lists/"):
            self.returned["list_read"] += 1
            return httpx.Response(200, json={"data": {"id": path.rsplit("/", 1)[1],
                                                      "name": "Builders"}})
        if path.startswith("/2/users/by/username/"):
            self.returned["user_read"] += 1
            return httpx.Response(200, json={"data": {"id": "783214", "name": "X",
                                                      "username": path.rsplit("/", 1)[1]}})
        if path == "/2/tweets":
            ids = (params.get("ids") or "").split(",")
            found = [p for p in self.timeline if p["id"] in ids and p["id"] not in
                     self.lookup_missing]
            body: dict = {}
            if found:
                body["data"] = found
                self.returned["post_read"] += len(found)
            gone = [i for i in ids if i in self.lookup_missing]
            if gone:
                body["errors"] = [{"value": i, "detail": f"Could not find tweet with ids: [{i}].",
                                   "title": "Not Found Error", "resource_type": "tweet",
                                   "parameter": "ids", "resource_id": i,
                                   "type": "https://api.twitter.com/2/problems/resource-not-found"}
                                  for i in gone]
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"title": "Not Found Error"})

    def authorized_with(self, query: dict, redirect_uri: str) -> None:
        """What X's consent page does: remember the challenge and the callback."""
        self.challenge = query["code_challenge"]
        self.redirect_uri = redirect_uri

    @staticmethod
    def epoch_in(seconds: int) -> int:
        return int(time.time()) + seconds
